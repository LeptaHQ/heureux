"""Server-owned selection, exposure tracking and deterministic grammar feedback."""

from __future__ import annotations

import secrets
from collections import Counter
from dataclasses import asdict
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from .course_content import POOL_MINIMUMS, normalize_answer
from .models import CourseAttempt, CourseExposureIndex, CourseItemExposure

MAX_ANSWER_LENGTH = 4000
REVIEW_DELAY = timedelta(days=7)
EXPOSURE_BATCH_SIZE = 100


class PracticeError(ValueError):
    pass


def successful_check(user, lesson):
    return CourseAttempt.objects.filter(
        user=user, lesson_id=lesson.id, content_version__in=lesson.assessment_versions,
        mode="check", status="completed", criterion_met=True,
    ).order_by("submitted_at").first()


def evidence_state(user, lesson):
    check = successful_check(user, lesson)
    due_at = check.submitted_at + REVIEW_DELAY if check else None
    review = None
    rehearsed_review = None
    active_fresh_review = False
    if check:
        review = check.reviews.filter(
            status="completed", independent=True, criterion_met=True,
        ).order_by("-submitted_at").first()
        rehearsed_review = check.reviews.filter(
            status="completed", independent=False, criterion_met=True,
        ).order_by("-submitted_at").first()
        active_fresh_review = check.reviews.filter(status="active", independent=True).exists()
    seen_prompts, seen_ids = _exposures(user, lesson)
    fresh_review = [
        item for item in lesson.practice
        if item.pool == "review" and _is_fresh(lesson, item, seen_prompts, seen_ids)
    ]
    fresh_available = active_fresh_review or _sufficient(fresh_review, "review")
    review_due = bool(due_at and timezone.now() >= due_at and not review)
    return {
        "check": check, "review": review, "due_at": due_at,
        "rehearsed_review": rehearsed_review,
        "fresh_review_available": fresh_available,
        "review_due": review_due,
        "review_exhausted": review_due and not fresh_available,
    }


def public_snapshot(attempt):
    """Safe even for in-progress exports: no hidden answer or feedback fields."""
    return {
        "lesson_id": attempt.lesson_id,
        "title": attempt.snapshot["title"],
        "slug": attempt.snapshot["slug"],
        "cefr_level": attempt.snapshot["cefr_level"],
        "items": [
            {key: item[key] for key in (
                "id", "kind", "pool", "section_id", "prompt", "choices", "item_version",
                "case_sensitive", "terminal_punctuation_sensitive",
            )}
            for item in attempt.snapshot["items"]
        ],
    }


def lock_course_user(user):
    """Acquire the course lifecycle lock inside the caller's transaction."""
    # Serialize lifecycle operations without blocking unrelated user-FK checks.
    return get_user_model().objects.select_for_update(no_key=True).only("pk").get(pk=user.pk)


def _index_attempts(attempts):
    rows = [
        CourseItemExposure(
            attempt_id=attempt.pk, user_id=attempt.user_id, lesson_id=attempt.lesson_id,
            item_id=item["id"], exposure_key=item["exposure_key"],
        )
        for attempt in attempts for item in attempt.snapshot["items"]
    ]
    CourseItemExposure.objects.bulk_create(rows)
    # Commit readiness only with the complete projection, including empty banks.
    CourseExposureIndex.objects.bulk_create([
        CourseExposureIndex(attempt_id=attempt.pk) for attempt in attempts
    ])


def _reconcile_exposures(user):
    indexed = CourseExposureIndex.objects.filter(attempt_id=OuterRef("pk"))
    missing = CourseAttempt.objects.filter(user=user).filter(~Exists(indexed)).order_by()
    while attempt_ids := list(missing.values_list("pk", flat=True)[:EXPOSURE_BATCH_SIZE]):
        attempts = list(
            CourseAttempt.objects.filter(user=user, pk__in=attempt_ids)
            .select_for_update().only("pk", "user_id", "lesson_id", "snapshot").order_by("pk")
        )
        _index_attempts(attempts)


def _locked_exposures(user, lesson):
    _reconcile_exposures(user)
    history = CourseItemExposure.objects.filter(user=user)
    seen_prompts = set(history.filter(
        exposure_key__in=[item.exposure_key for item in lesson.practice],
    ).order_by().values_list("exposure_key", flat=True).distinct())
    seen_ids = {
        (lesson.id, item_id) for item_id in history.filter(
            lesson_id=lesson.id, item_id__in=[item.id for item in lesson.practice],
        ).order_by().values_list("item_id", flat=True).distinct()
    }
    return seen_prompts, seen_ids


@transaction.atomic
def _exposures(user, lesson):
    lock_course_user(user)
    return _locked_exposures(user, lesson)


def _is_fresh(lesson, item, seen_prompts, seen_ids):
    return item.exposure_key not in seen_prompts and (lesson.id, item.id) not in seen_ids


def _sufficient(items, mode):
    count = POOL_MINIMUMS[mode]
    return len(items) >= count and (
        mode == "practice" or sum(item.kind == "text" for item in items) >= count // 2
    )


def _item_history(user, lesson):
    """Keep only latest completed first answers for exactly unchanged items."""
    versions = {item.id: item.item_version for item in lesson.practice}
    latest, assessed = {}, {}
    history = CourseAttempt.objects.filter(
        user=user, lesson_id=lesson.id, status="completed",
    ).order_by("-submitted_at", "-started_at", "-id").values_list(
        "snapshot", "events", "mode", "independent", "content_version", "submitted_at",
    )
    content_versions = lesson.assessment_versions
    for snapshot, events, mode, independent, version, submitted_at in history.iterator(chunk_size=100):
        first = _first_answers(events)
        for item in snapshot["items"]:
            if versions.get(item["id"]) != item["item_version"] or item["id"] not in first:
                continue
            event = first[item["id"]]
            record = {
                "correct": event["correct"], "blank": not event["response"].strip(),
                "hinted": event["hinted"], "at": submitted_at,
                "older_content": version not in content_versions,
                "independent": independent,
            }
            latest.setdefault(item["id"], record)
            if mode in {"check", "review"}:
                assessed.setdefault(item["id"], record)
    return latest, assessed


def _section_guidance(lesson, latest, assessed):
    rows = []
    for section in lesson.sections:
        bank = [item for item in lesson.practice if item.section_id == section.id]
        learning = [item for item in bank if item.pool == "practice"]
        records = [latest[item.id] for item in bank if item.id in latest]
        missed = [record for record in records if not record["correct"]]
        hinted = [record for record in records if record["hinted"]]
        untried = [item for item in learning if item.id not in latest]
        if missed:
            priority, needs = 0, missed
            reason = "Recent incorrect or blank first answers; revisit this section."
        elif hinted:
            priority, needs = 1, hinted
            reason = "Hint-supported first answers; try without help."
        elif untried or not records:
            priority, needs = 2, []
            reason = "No completed first answer for some items; try something untested."
        else:
            priority, needs = 3, []
            reason = "Revisit earlier learning; no current missed first answers recorded."
        checks = [assessed[item.id] for item in bank if item.id in assessed]
        rows.append({
            "id": section.id, "title": section.title, "reason": reason,
            "priority": priority,
            "recent_need": max((record["at"].timestamp() for record in needs), default=0),
            "practice_count": len(learning),
            "check_count": sum(item.pool == "check" for item in bank),
            "review_count": sum(item.pool == "review" for item in bank),
            "assessed": len(checks),
            "untested": sum(item.pool != "practice" and item.id not in assessed for item in bank),
            "correct": sum(record["correct"] for record in checks),
            "blank": sum(record["blank"] for record in checks),
            "fresh": sum(record["independent"] for record in checks),
            "rehearsed": sum(not record["independent"] for record in checks),
            "older_content": sum(record["older_content"] for record in checks),
            "last_assessed": max((record["at"] for record in checks), default=None),
        })
    return rows


def practice_guidance(user, lesson):
    latest, assessed = _item_history(user, lesson)
    return _section_guidance(lesson, latest, assessed)


def _assessment_sample(candidates, count, random):
    remaining = list(candidates)
    random.shuffle(remaining)
    selected, sections = [], Counter()
    text_count, quota = 0, count // 2
    while len(selected) < count:
        slots_left = count - len(selected) - 1
        texts_left = sum(item.kind == "text" for item in remaining)
        # Reserve enough slots for constructed answers before spreading sections.
        feasible = [
            item for item in remaining
            if text_count + (item.kind == "text")
            + min(slots_left, texts_left - (item.kind == "text")) >= quota
        ]
        item = min(feasible, key=lambda item: (
            sections[item.section_id],
            item.kind != "text" if text_count < quota else False,
        ))
        selected.append(item)
        remaining.remove(item)
        sections[item.section_id] += 1
        text_count += item.kind == "text"
    return selected


def _selected_items(lesson, mode, seen_prompts, seen_ids, latest=None, guidance=None):
    bank = [item for item in lesson.practice if item.pool == mode]
    if not _sufficient(bank, mode):
        raise PracticeError("This bank has insufficient items or text answers for this session.")
    fresh = [item for item in bank if _is_fresh(lesson, item, seen_prompts, seen_ids)]
    count = POOL_MINIMUMS[mode]
    random = secrets.SystemRandom()
    if mode == "practice":
        latest = {} if latest is None else latest
        rows = guidance if guidance is not None else _section_guidance(lesson, latest, {})
        priorities = {row["id"]: row for row in rows}
        random.shuffle(bank)
        selected, sections = [], Counter()
        for _ in range(count):
            item = min(bank, key=lambda item: (
                priorities[item.section_id]["priority"], sections[item.section_id],
                -priorities[item.section_id]["recent_need"],
                not _is_fresh(lesson, item, seen_prompts, seen_ids),
                item.id in latest and latest[item.id]["correct"] and not latest[item.id]["hinted"],
            ))
            selected.append(item)
            bank.remove(item)
            sections[item.section_id] += 1
    else:
        candidates = fresh if _sufficient(fresh, mode) else bank
        selected = _assessment_sample(candidates, count, random)
    random.shuffle(selected)
    return selected


def _selection_notes(lesson, mode, selected, seen_prompts, seen_ids, guidance):
    sampled = {item.section_id for item in selected}
    bank = [item for item in lesson.practice if item.pool == mode]
    fresh = [item for item in bank if _is_fresh(lesson, item, seen_prompts, seen_ids)]
    eligible = fresh if mode != "practice" and _sufficient(fresh, mode) else bank
    eligible_sections = {item.section_id for item in eligible}
    return {
        "sampled": len(sampled), "total": len(lesson.sections),
        "omitted": [section.title for section in lesson.sections if section.id not in sampled],
        "unavailable": [
            section.title for section in lesson.sections if section.id not in eligible_sections
        ],
        "focus": [
            {
                "title": row["title"], "reason": row["reason"],
                "rehearsed": any(
                    item.section_id == row["id"]
                    and not _is_fresh(lesson, item, seen_prompts, seen_ids) for item in selected
                ),
            }
            for row in guidance if row["id"] in sampled
        ] if mode == "practice" else [],
    }


@transaction.atomic
def start_attempt(user, lesson, mode):
    if mode not in POOL_MINIMUMS:
        raise PracticeError("Unknown practice mode.")
    # Serialize cross-mode starts too: a second tab cannot allocate the same fresh items.
    lock_course_user(user)
    active = CourseAttempt.objects.filter(
        user=user, lesson_id=lesson.id, mode=mode, status="active"
    ).first()
    if active:
        _reconcile_exposures(user)
        return active
    check = None
    if mode == "review":
        check = successful_check(user, lesson)
        if not check or timezone.now() < check.submitted_at + REVIEW_DELAY:
            raise PracticeError("Review opens seven days after a successful check.")
    seen_prompts, seen_ids = _locked_exposures(user, lesson)
    latest, guidance = {}, []
    if mode == "practice":
        latest, assessed = _item_history(user, lesson)
        guidance = _section_guidance(lesson, latest, assessed)
    selected = _selected_items(lesson, mode, seen_prompts, seen_ids, latest, guidance)
    independent = mode != "practice" and all(
        _is_fresh(lesson, item, seen_prompts, seen_ids) for item in selected
    )
    snapshot = {
        "title": lesson.title, "slug": lesson.slug, "cefr_level": lesson.cefr_level,
        "version": lesson.version,
        "selection": _selection_notes(lesson, mode, selected, seen_prompts, seen_ids, guidance),
        "items": [
            {
                **asdict(item), "choices": list(item.choices), "answers": list(item.answers),
                "item_version": item.item_version, "exposure_key": item.exposure_key,
            }
            for item in selected
        ],
    }
    attempt = CourseAttempt.objects.create(
        user=user, lesson_id=lesson.id, content_version=lesson.content_version,
        mode=mode, snapshot=snapshot, independent=independent, review_of=check,
    )
    _index_attempts([attempt])
    return attempt


def _answer(item, response):
    if not isinstance(response, str) or len(response) > MAX_ANSWER_LENGTH:
        raise PracticeError("Answer is invalid or too long.")
    if item["kind"] == "choice" and response not in item["choices"]:
        raise PracticeError("Choose one of the offered answers.")
    normalization = {
        "case_sensitive": item.get("case_sensitive", False),
        "terminal_punctuation_sensitive": item.get("terminal_punctuation_sensitive", False),
    }
    return normalize_answer(response, **normalization) in {
        normalize_answer(answer, **normalization) for answer in item["answers"]
    }


def _first_answers(events):
    first = {}
    for event in events:
        if event["action"] == "answer":
            first.setdefault(event["item_id"], event)
    return first


def _complete(attempt):
    first = _first_answers(attempt.events)
    if len(first) != len(attempt.snapshot["items"]):
        return
    text_ids = {item["id"] for item in attempt.snapshot["items"] if item["kind"] == "text"}
    correct = sum(event["correct"] for event in first.values())
    text_correct = sum(first[item_id]["correct"] for item_id in text_ids)
    total, text_total = len(first), len(text_ids)
    attempt.results = {
        "correct": correct, "total": total,
        "text_correct": text_correct, "text_total": text_total,
        "choice_correct": correct - text_correct, "choice_total": total - text_total,
        "hinted_items": len({event["item_id"] for event in attempt.events if event["action"] == "hint"}),
    }
    attempt.criterion_met = (
        attempt.mode != "practice" and text_total > 0
        and correct * 100 >= total * 80 and text_correct * 100 >= text_total * 75
    )
    attempt.status = "completed"
    attempt.submitted_at = timezone.now()


@transaction.atomic
def submit_check(user, attempt_id, responses):
    attempt = CourseAttempt.objects.select_for_update().get(user=user, pk=attempt_id)
    if attempt.mode not in {"check", "review"}:
        raise PracticeError("Use the learning form for practice.")
    if attempt.status == "completed":
        return attempt
    if attempt.status != "active":
        raise PracticeError("This session was abandoned.")
    items = attempt.snapshot["items"]
    if set(responses) != {item["id"] for item in items}:
        raise PracticeError("Submit exactly the selected questions, including any blank answers.")
    now = timezone.now().isoformat()
    attempt.events = [
        {"action": "answer", "item_id": item["id"], "response": responses[item["id"]],
         "correct": _answer(item, responses[item["id"]]), "at": now, "hinted": False}
        for item in items
    ]
    _complete(attempt)
    attempt.save(update_fields=["events", "results", "criterion_met", "status", "submitted_at"])
    return attempt


@transaction.atomic
def practice_event(user, attempt_id, item_id, action, response=""):
    attempt = CourseAttempt.objects.select_for_update().get(user=user, pk=attempt_id)
    if attempt.mode != "practice" or attempt.status != "active":
        raise PracticeError("Hints and learning retries are only available in active practice.")
    item = next((item for item in attempt.snapshot["items"] if item["id"] == item_id), None)
    if item is None or action not in {"hint", "answer"}:
        raise PracticeError("Unknown practice item or action.")
    prior = [event for event in attempt.events if event["item_id"] == item_id]
    if action == "hint" and any(event["action"] == "hint" for event in prior):
        return attempt
    if action == "answer" and any(event["action"] == "answer" for event in prior):
        raise PracticeError("The first response is saved. Start a new learning session to retry.")
    event = {"action": action, "item_id": item_id, "at": timezone.now().isoformat()}
    if action == "answer":
        event.update(
            response=response, correct=_answer(item, response),
            hinted=any(event["action"] == "hint" for event in prior),
        )
    attempt.events = [*attempt.events, event]
    _complete(attempt)
    attempt.save(update_fields=["events", "results", "criterion_met", "status", "submitted_at"])
    return attempt


@transaction.atomic
def abandon_attempt(user, attempt_id):
    attempt = CourseAttempt.objects.select_for_update().get(user=user, pk=attempt_id)
    if attempt.status == "active":
        attempt.status = "abandoned"
        attempt.save(update_fields=["status"])
    return attempt
