"""Server-owned selection, exposure tracking and deterministic grammar feedback."""

from __future__ import annotations

import secrets
from dataclasses import asdict
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .course_content import POOL_MINIMUMS, normalize_answer
from .models import CourseAttempt

MAX_ANSWER_LENGTH = 4000
REVIEW_DELAY = timedelta(days=7)


class PracticeError(ValueError):
    pass


def successful_check(user, lesson):
    return CourseAttempt.objects.filter(
        user=user, lesson_id=lesson.id, content_version=lesson.content_version,
        mode="check", status="completed", criterion_met=True,
    ).order_by("submitted_at").first()


def evidence_state(user, lesson):
    check = successful_check(user, lesson)
    due_at = check.submitted_at + REVIEW_DELAY if check else None
    review = None
    if check:
        review = check.reviews.filter(
            status="completed", criterion_met=True,
        ).order_by("-submitted_at").first()
    return {
        "check": check, "review": review, "due_at": due_at,
        "review_due": bool(due_at and timezone.now() >= due_at and not review),
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


def _selected_items(lesson, mode, seen):
    bank = [item for item in lesson.practice if item.pool == mode]
    fresh = [item for item in bank if item.exposure_key not in seen]
    count = POOL_MINIMUMS[mode]

    def sufficient(items):
        return len(items) >= count and (
            mode == "practice" or sum(item.kind == "text" for item in items) >= count // 2
        )

    candidates = fresh if sufficient(fresh) else bank
    random = secrets.SystemRandom()
    if mode == "practice":
        selected = random.sample(candidates, count)
    else:
        text = random.sample([item for item in candidates if item.kind == "text"], count // 2)
        selected = text + random.sample([item for item in candidates if item not in text], count - len(text))
    random.shuffle(selected)
    return selected


@transaction.atomic
def start_attempt(user, lesson, mode):
    if mode not in POOL_MINIMUMS:
        raise PracticeError("Unknown practice mode.")
    # Serialize cross-mode starts too: a second tab cannot allocate the same fresh items.
    get_user_model().objects.select_for_update().get(pk=user.pk)
    active = CourseAttempt.objects.filter(
        user=user, lesson_id=lesson.id, mode=mode, status="active"
    ).first()
    if active:
        return active
    check = None
    if mode == "review":
        check = successful_check(user, lesson)
        if not check or timezone.now() < check.submitted_at + REVIEW_DELAY:
            raise PracticeError("Review opens seven days after a successful check.")
    seen = {
        item["exposure_key"]
        for snapshot in CourseAttempt.objects.filter(user=user).values_list("snapshot", flat=True)
        for item in snapshot["items"]
    }
    selected = _selected_items(lesson, mode, seen)
    independent = mode != "practice" and all(item.exposure_key not in seen for item in selected)
    snapshot = {
        "title": lesson.title, "slug": lesson.slug, "cefr_level": lesson.cefr_level,
        "version": lesson.version,
        "items": [
            {
                **asdict(item), "choices": list(item.choices), "answers": list(item.answers),
                "item_version": item.item_version, "exposure_key": item.exposure_key,
            }
            for item in selected
        ],
    }
    return CourseAttempt.objects.create(
        user=user, lesson_id=lesson.id, content_version=lesson.content_version,
        mode=mode, snapshot=snapshot, independent=independent, review_of=check,
    )


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
