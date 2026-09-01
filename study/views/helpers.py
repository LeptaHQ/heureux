"""Shared view helpers, scope resolution, and constants."""

from __future__ import annotations

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .. import content_loader as content_module
from .. import queue as queue_module
from ..models import (
    Card,
    CardState,
    CardType,
    MemoryQuestionProgress,
    Phrase,
    PhraseTier,
    Prompt,
    Rating,
    Response,
    ReviewLog,
    Task,
    Theme,
    WritingSujet,
)
from ..progress import (
    MATURE_INTERVAL_DAYS,
    ProgressSummary,
    SubjectProgress,
    combine_progress,
    progress_summary,
    subject_progress_by_response,
    summarize_subject_progress,
    writing_sujet_progress_by_id,
)
from ..routing import review_url

MATURE_DAYS = MATURE_INTERVAL_DAYS


RECENT_SESSION_GAP = timezone.timedelta(minutes=30)


FUNCTIONAL_PHRASE_CATEGORY_NAMES = frozenset(
    {
        "Structurer et prendre position",
        "Nuancer et comparer",
        "Cause, conséquence et évaluation",
        "Schémas d'argumentation",
    }
)


def _memory_progress(user, memories):
    memories = tuple(memories)
    completed_by_memory = {
        memory.number: set()
        for memory in memories
    }
    for memory_number, question_key in (
        MemoryQuestionProgress.objects.filter(
            user=user,
            memory_number__in=completed_by_memory,
        ).values_list("memory_number", "question_key")
    ):
        completed_by_memory[memory_number].add(question_key)

    states = {}
    for memory in memories:
        valid_keys = set(memory.question_keys)
        completed_keys = frozenset(
            completed_by_memory[memory.number] & valid_keys
        )
        states[memory.number] = {
            "completed_keys": completed_keys,
            "progress": progress_summary(
                total=memory.question_count,
                started=len(completed_keys),
                completed=len(completed_keys),
            ),
        }
    return states


_EMPTY_SUBJECT_PROGRESS = SubjectProgress(
    status="new",
    label="À commencer",
    explicitly_completed=False,
    has_highlight=False,
    response_practice_started=False,
    vocabulary_activity_started=False,
    vocabulary_total=0,
    vocabulary_started=0,
    vocabulary_completed=0,
    vocabulary_mastered=0,
    vocabulary_due=0,
)


def _tache_two_response_ids_by_subject_key(content_keys):
    """Map Tâche 2 subject keys onto the response each one shares."""
    return dict(
        Prompt.objects.filter(
            content_key__in=content_keys,
            is_active=True,
            response__is_active=True,
        ).values_list("content_key", "response_id")
    )


def _tache_two_progress(user, months):
    """Attach material-specific progress to Tâche 2 months and subjects."""
    months = tuple(months)
    content_keys = [
        content_module.tache_two_subject_content_key(
            month.slug,
            batch.number,
            subject.number,
        )
        for month in months
        for batch in month.batches
        for subject in batch.subjects
    ]
    response_id_by_content_key = _tache_two_response_ids_by_subject_key(
        content_keys
    )
    progress_by_response = subject_progress_by_response(
        user,
        set(response_id_by_content_key.values()),
    )
    progress_by_content_key = {
        content_key: progress_by_response[response_id]
        for content_key, response_id in response_id_by_content_key.items()
    }

    all_progress = []
    month_rows = []
    for month in months:
        month_progress = []
        batch_rows = []
        for batch in month.batches:
            batch_progress = []
            subjects = []
            for subject in batch.subjects:
                content_key = content_module.tache_two_subject_content_key(
                    month.slug,
                    batch.number,
                    subject.number,
                )
                progress = progress_by_content_key.get(
                    content_key,
                    _EMPTY_SUBJECT_PROGRESS,
                )
                vocabulary_progress = progress.vocabulary_progress
                batch_progress.append(progress)
                month_progress.append(progress)
                all_progress.append(progress)
                subjects.append(
                    {
                        "number": subject.number,
                        "number_label": subject.number_label,
                        "title": subject.title,
                        "prompt": subject.prompt,
                        "questions": subject.questions,
                        "question_count": subject.question_count,
                        "memory_question_count": subject.memory_question_count,
                        "content_key": content_key,
                        "response_id": response_id_by_content_key.get(
                            content_key
                        ),
                        "progress": progress,
                        "vocabulary_progress": vocabulary_progress,
                        "vocabulary_started_only": max(
                            vocabulary_progress.started
                            - vocabulary_progress.completed,
                            0,
                        ),
                    }
                )
            batch_summary = summarize_subject_progress(batch_progress)
            batch_rows.append(
                {
                    "number": batch.number,
                    "number_label": batch.number_label,
                    "subjects": tuple(subjects),
                    "subject_count": batch.subject_count,
                    "question_count": batch.question_count,
                    "first_subject_number": batch.first_subject_number,
                    "last_subject_number": batch.last_subject_number,
                    **batch_summary,
                }
            )
        month_summary = summarize_subject_progress(month_progress)
        month_rows.append(
            {
                "number": month.number,
                "slug": month.slug,
                "name": month.name,
                "batches": tuple(batch_rows),
                "batch_count": month.batch_count,
                "subject_count": month.subject_count,
                "question_count": month.question_count,
                **month_summary,
            }
        )

    summary = summarize_subject_progress(all_progress)
    return {
        "months": tuple(month_rows),
        "progress_by_content_key": progress_by_content_key,
        "summary": summary,
        **summary,
    }


def _tache_two_progress_by_content_key(user, months):
    """Return {content_key: SubjectProgress} for every Tâche 2 subject."""
    content_keys = [
        content_module.tache_two_subject_content_key(
            month.slug,
            batch.number,
            subject.number,
        )
        for month in months
        for batch in month.batches
        for subject in batch.subjects
    ]
    response_id_by_content_key = _tache_two_response_ids_by_subject_key(
        content_keys
    )
    progress_by_response = subject_progress_by_response(
        user,
        set(response_id_by_content_key.values()),
    )
    progress_by_content_key = {
        content_key: progress_by_response[response_id]
        for content_key, response_id in response_id_by_content_key.items()
    }
    return progress_by_content_key, response_id_by_content_key


def _tache_two_theme_progress(user, months=None):
    """Group Tâche 2 subjects by theme with per-subject progress."""
    if months is None:
        months = content_module.load_tache_two_subject_months()
    months = tuple(months)
    themes, mapping = content_module.load_tache_two_subject_themes()
    progress_by_content_key, response_id_by_content_key = (
        _tache_two_progress_by_content_key(user, months)
    )

    subjects_by_theme = {theme.slug: [] for theme in themes}
    all_progress = []
    for month in months:
        for batch in month.batches:
            for subject in batch.subjects:
                content_key = content_module.tache_two_subject_content_key(
                    month.slug,
                    batch.number,
                    subject.number,
                )
                theme_slug = mapping.get(content_key)
                if theme_slug not in subjects_by_theme:
                    continue
                progress = progress_by_content_key.get(
                    content_key,
                    _EMPTY_SUBJECT_PROGRESS,
                )
                vocabulary_progress = progress.vocabulary_progress
                all_progress.append(progress)
                subjects_by_theme[theme_slug].append(
                    {
                        "month_slug": month.slug,
                        "batch_number": batch.number,
                        "number": subject.number,
                        "number_label": subject.number_label,
                        "title": subject.title,
                        "prompt": subject.prompt,
                        "questions": subject.questions,
                        "question_count": subject.question_count,
                        "memory_question_count": subject.memory_question_count,
                        "content_key": content_key,
                        "response_id": response_id_by_content_key.get(
                            content_key
                        ),
                        "progress": progress,
                        "vocabulary_progress": vocabulary_progress,
                        "vocabulary_started_only": max(
                            vocabulary_progress.started
                            - vocabulary_progress.completed,
                            0,
                        ),
                    }
                )

    theme_rows = []
    for theme in sorted(themes, key=lambda item: item.order):
        subjects = subjects_by_theme[theme.slug]
        for index, subject in enumerate(subjects, start=1):
            subject["index"] = index
        theme_summary = summarize_subject_progress(
            [subject["progress"] for subject in subjects]
        )
        theme_rows.append(
            {
                "slug": theme.slug,
                "name": theme.name,
                "icon": theme.icon,
                "order": theme.order,
                "subjects": tuple(subjects),
                "subject_count": len(subjects),
                "question_count": sum(
                    subject["question_count"] for subject in subjects
                ),
                **theme_summary,
            }
        )

    summary = summarize_subject_progress(all_progress)
    return {
        "themes": tuple(theme_rows),
        "progress_by_content_key": progress_by_content_key,
        "summary": summary,
        "theme_count": len(theme_rows),
        **summary,
    }


_DUE_CARD_STATES = (
    CardState.LEARNING,
    CardState.RELEARNING,
    CardState.REVIEW,
)


def _deck_stat_aggregates(now) -> dict:
    """The conditional counts every deck summary is built from.

    Passed to ``aggregate`` for one deck or to ``annotate`` after a
    ``values(<group>)`` to summarize every deck on a page at once.
    """
    return {
        "total": Count("id", distinct=True),
        "new": Count("id", distinct=True, filter=Q(state=CardState.NEW)),
        "started_new": Count(
            "id",
            distinct=True,
            filter=Q(state=CardState.NEW, started_at__isnull=False),
        ),
        "learning": Count(
            "id",
            distinct=True,
            filter=Q(
                state__in=[CardState.LEARNING, CardState.RELEARNING]
            ),
        ),
        "review": Count("id", distinct=True, filter=Q(state=CardState.REVIEW)),
        "mature": Count(
            "id",
            distinct=True,
            filter=Q(
                state=CardState.REVIEW,
                interval_days__gte=MATURE_DAYS,
            ),
        ),
        "due": Count(
            "id",
            distinct=True,
            filter=Q(state__in=_DUE_CARD_STATES, due__lte=now),
        ),
    }


_EMPTY_DECK_COUNTS = {
    "total": 0,
    "new": 0,
    "started_new": 0,
    "learning": 0,
    "review": 0,
    "mature": 0,
    "due": 0,
}


def _deck_stats_from_counts(counts) -> dict:
    """Shape the raw conditional counts into the deck summary templates read."""
    total = counts["total"]
    new = counts["new"]
    started_new = counts["started_new"]
    learning = counts["learning"]
    review = counts["review"]
    mature = counts["mature"]
    due = counts["due"]
    seen = total - new + started_new
    return {
        "total": total,
        "new": new,
        "started_new": started_new,
        "learning": learning,
        "review": review,
        "mature": mature,
        "review_young": review - mature,
        "due": due,
        "seen": seen,
        "reviewed": total - new,
        "pct": round(100 * seen / total) if total else 0,
        "mature_pct": round(100 * mature / total) if total else 0,
    }


def empty_deck_stats() -> dict:
    """The summary a deck without a single card renders."""
    return _deck_stats_from_counts(_EMPTY_DECK_COUNTS)


def deck_stats(qs, now=None) -> dict:
    now = now or timezone.now()
    # One conditional aggregate instead of seven COUNTs: the scoped queryset
    # joins several tables and is DISTINCT, so each extra count was a full
    # `SELECT COUNT(*) FROM (SELECT DISTINCT <every column>)` scan.
    return _deck_stats_from_counts(
        queue_module.narrow(qs).aggregate(**_deck_stat_aggregates(now))
    )


def grouped_deck_stats(qs, group_field, now=None) -> dict:
    """``deck_stats`` for every group of a queryset in a single aggregate.

    Returns ``{group value: deck stats}``, with no entry for groups the
    queryset does not reach — callers fall back to :func:`empty_deck_stats`.
    """
    now = now or timezone.now()
    return {
        row[group_field]: _deck_stats_from_counts(row)
        for row in (
            queue_module.narrow(qs)
            .values(group_field)
            .annotate(**_deck_stat_aggregates(now))
        )
    }


def deck_stats_from_rows(rows, now) -> dict:
    """``deck_stats`` for rows already fetched for another purpose.

    ``rows`` are card dicts carrying ``state``, ``interval_days``, ``due`` and
    ``started_at``; suspended rows must already be filtered out, exactly as
    ``scoped_cards`` does before :func:`deck_stats` counts them.
    """
    counts = dict(_EMPTY_DECK_COUNTS)
    for row in rows:
        state = row["state"]
        counts["total"] += 1
        if state == CardState.NEW:
            counts["new"] += 1
            if row["started_at"] is not None:
                counts["started_new"] += 1
        elif state in (CardState.LEARNING, CardState.RELEARNING):
            counts["learning"] += 1
        elif state == CardState.REVIEW:
            counts["review"] += 1
            if row["interval_days"] >= MATURE_DAYS:
                counts["mature"] += 1
        if (
            state in _DUE_CARD_STATES
            and row["due"] is not None
            and row["due"] <= now
        ):
            counts["due"] += 1
    return _deck_stats_from_counts(counts)


BATCH_ROW_FIELDS = (
    "id",
    "phrase_id",
    "state",
    "due",
    "suspended",
    "started_at",
    "response_practice_started_at",
)


def batch_rows(scope: dict, user, *, extra_fields=()):
    """The ordered card rows :func:`review_batches_from_rows` partitions.

    Fetching them for a parent scope and filtering the list per child scope in
    Python gives the same lots as one query per child: the ordering ends on the
    card id, so it is total, and restricting a totally ordered list preserves
    the order of every subset.
    """
    return list(
        queue_module.scoped_cards(
            scope,
            user=user,
            include_suspended=True,
        )
        .order_by(*queue_module.batch_ordering(scope))
        .values(*BATCH_ROW_FIELDS, *extra_fields)
    )


def review_batches_from_rows(rows, scope: dict, now=None) -> list[dict]:
    """Describe stable lots and each lot's first-pass progress."""
    base_scope = {key: value for key, value in scope.items() if key != "batch"}
    phrase_batches = queue_module._uses_phrase_batches(base_scope)
    if phrase_batches:
        grouped_rows = {}
        for row in rows:
            grouped_rows.setdefault(row["phrase_id"], []).append(row)
        units = list(grouped_rows.values())
    else:
        units = [[row] for row in rows]

    now = now or timezone.now()
    size = queue_module.batch_size(base_scope)
    batches = []
    for number, start in enumerate(
        range(0, len(units), size),
        start=1,
    ):
        units_in_batch = units[start : start + size]
        active_units = [
            [row for row in unit if not row["suspended"]]
            for unit in units_in_batch
        ]
        active_units = [unit for unit in active_units if unit]
        started_count = sum(
            any(
                row["state"] != CardState.NEW
                or (
                    row["started_at"]
                    if phrase_batches
                    else row["response_practice_started_at"]
                )
                is not None
                for row in unit
            )
            for unit in active_units
        )
        completed_count = sum(
            all(row["state"] != CardState.NEW for row in unit)
            for unit in active_units
        )
        available_now = sum(
            row["state"] == CardState.NEW
            or (
                row["due"] is not None
                and row["due"] <= now
                and row["state"]
                in {
                    CardState.LEARNING,
                    CardState.RELEARNING,
                    CardState.REVIEW,
                }
            )
            for unit in active_units
            for row in unit
        )
        if not active_units:
            status = "unavailable"
            status_label = "Suspendu"
        elif completed_count == len(active_units):
            status = "complete"
            status_label = "Terminé"
        elif started_count:
            status = "in-progress"
            status_label = "En cours"
        else:
            status = "not-started"
            status_label = "À commencer"
        end = start + len(units_in_batch)
        batch_scope = {**base_scope, "batch": str(number)}
        batches.append(
            {
                "number": number,
                "start": start + 1,
                "end": end,
                "card_count": sum(len(unit) for unit in units_in_batch),
                "phrase_count": (
                    len(units_in_batch) if phrase_batches else None
                ),
                "active_count": len(active_units),
                "completed_count": completed_count,
                "seen_count": completed_count,
                "started_count": started_count,
                "available_now": available_now,
                "phrase_batch": phrase_batches,
                "status": status,
                "status_label": status_label,
                "progress_status": {
                    "complete": "done",
                    "in-progress": "active",
                    "not-started": "new",
                    "unavailable": "new",
                }[status],
                "can_review": available_now > 0,
                "review_url": review_url(batch_scope),
            }
        )
    next_batch_found = False
    for batch in batches:
        batch["is_next"] = batch["can_review"] and not next_batch_found
        next_batch_found = next_batch_found or batch["can_review"]
    return batches


def _review_batches(scope: dict, user, now=None) -> list[dict]:
    """Stable lots for one scope, fetching that scope's rows on its own."""
    base_scope = {key: value for key, value in scope.items() if key != "batch"}
    return review_batches_from_rows(
        batch_rows(base_scope, user),
        base_scope,
        now,
    )


def summarize_review_batches(batches) -> ProgressSummary:
    """Bubble active lot completion into one parent progress summary."""
    available = [batch for batch in batches if batch["status"] != "unavailable"]
    return progress_summary(
        total=len(available),
        started=sum(
            batch["status"] in {"in-progress", "complete"}
            for batch in available
        ),
        completed=sum(batch["status"] == "complete" for batch in available),
    )


def review_day_counts(user=None, logs=None) -> dict:
    """Reviews per local calendar day, in one grouped query.

    The database does the day bucketing, so this reads one short row per active
    day instead of the learner's whole review history — tens of thousands of
    timestamps for the same handful of dates.
    """
    logs = ReviewLog.objects.filter(user=user) if logs is None else logs
    return {
        row["reviewed_day"]: row["total"]
        for row in (
            logs.annotate(reviewed_day=TruncDate("reviewed_at"))
            .order_by()
            .values("reviewed_day")
            .annotate(total=Count("id"))
        )
        if row["reviewed_day"] is not None
    }


def current_streak(now=None, logs=None, user=None, day_counts=None) -> int:
    """Consecutive days (up to today) with at least one review.

    ``day_counts`` reuses a :func:`review_day_counts` mapping the caller has
    already fetched.
    """
    now = now or timezone.now()
    days = set(
        day_counts
        if day_counts is not None
        else review_day_counts(user=user, logs=logs)
    )
    if not days:
        return 0
    today = timezone.localtime(now).date()
    cursor = today
    if cursor not in days:
        cursor = today - timezone.timedelta(days=1)
        if cursor not in days:
            return 0
    streak = 0
    while cursor in days:
        streak += 1
        cursor = cursor - timezone.timedelta(days=1)
    return streak


def recent_review_sessions(logs, *, limit=8) -> list[dict]:
    """Group recent review logs into focused sessions separated by 30 minutes."""
    recent_logs = list(
        logs.select_related(
            "card__response__theme",
            "card__phrase",
        ).order_by("-reviewed_at")[:400]
    )
    sessions = []
    current = None
    for log in recent_logs:
        if (
            current is None
            or current["started_at"] - log.reviewed_at > RECENT_SESSION_GAP
        ):
            if len(sessions) >= limit:
                break
            current = {
                "started_at": log.reviewed_at,
                "ended_at": log.reviewed_at,
                "review_count": 0,
                "correct_count": 0,
                "revisit_count": 0,
                "response_count": 0,
                "phrase_count": 0,
                "elapsed_ms": 0,
                "topics_set": set(),
            }
            sessions.append(current)

        current["started_at"] = log.reviewed_at
        current["review_count"] += 1
        current["elapsed_ms"] += log.elapsed_ms
        if log.rating == Rating.AGAIN:
            current["revisit_count"] += 1
        else:
            current["correct_count"] += 1
        if log.card.response_id:
            current["response_count"] += 1
            current["topics_set"].add(log.card.response.theme.display_name)
        else:
            current["phrase_count"] += 1
            current["topics_set"].add("Expressions")

    for session in sessions:
        session["accuracy"] = round(
            100 * session["correct_count"] / session["review_count"]
        )
        session["study_minutes"] = (
            max(1, round(session["elapsed_ms"] / 60000))
            if session["elapsed_ms"]
            else None
        )
        topics = sorted(session.pop("topics_set"))
        session["topics"] = topics[:3]
        session["extra_topics"] = max(0, len(topics) - 3)
    return sessions


def _task_scope(task) -> dict:
    return {"part": task.part.slug, "task": task.slug}


def _task_cards(task, user=None, kind=None):
    scope = _task_scope(task)
    if kind:
        scope["kind"] = kind
    return queue_module.scoped_cards(scope, user=user)


def _task_phrases(task):
    return Phrase.objects.filter(
        is_active=True,
        tier=PhraseTier.SHARED,
        source_prompts__is_active=True,
        source_prompts__theme__is_active=True,
        source_prompts__theme__task=task,
    ).distinct()


def _active_task(part_slug, task_slug):
    """The active task a slug pair names, or ``None``."""
    if not task_slug:
        return None
    tasks = Task.objects.select_related("part").filter(
        slug=task_slug,
        is_active=True,
        part__is_active=True,
    )
    if part_slug:
        tasks = tasks.filter(part__slug=part_slug)
    return tasks.first()


def active_task_for_request(request, part_slug, task_slug):
    """Resolve a task once per request, shared by the view and the app shell.

    A page that names a task resolves it in the view, and the shell context
    processor resolves the same row again to light up the navigation. Memoising
    on the request keeps that to a single query. The cache lives and dies with
    the request object, so nothing is shared between users or requests.
    """
    cache = getattr(request, "_study_active_tasks", None)
    if cache is None:
        cache = {}
        request._study_active_tasks = cache
    key = (part_slug or "", task_slug or "")
    if key not in cache:
        cache[key] = _active_task(part_slug, task_slug)
    return cache[key]


def _route_task(part_slug, task_slug, *, request=None):
    """The active task a URL names, 404ing when it is missing.

    Pass ``request`` to share the lookup with the app shell instead of paying
    for the same row twice.
    """
    if request is None:
        return get_object_or_404(
            Task.objects.select_related("part"),
            slug=task_slug,
            part__slug=part_slug,
            is_active=True,
            part__is_active=True,
        )
    task = active_task_for_request(request, part_slug, task_slug)
    if task is None:
        raise Http404("No Task matches the given query.")
    return task


_EMPTY_TASK_CONTENT_COUNTS = {
    "theme_count": 0,
    "prompt_count": 0,
    "phrase_count": 0,
    "functional_phrase_count": 0,
    "subject_vocabulary_count": 0,
    "subject_vocabulary_prompt_count": 0,
    "theme_vocabulary_count": 0,
    "writing_sujet_ids": (),
    "writing_sujet_category_count": 0,
    "writing_sujet_response_count": 0,
}


def _task_content_counts(tasks):
    """Static, user-independent content counts for several tasks at once.

    Every card on a part page shows the same handful of catalogue counts.
    Fetched per task they cost six round trips each; grouped by task they cost
    a fixed handful of queries for the whole page, which is what a serverless
    Postgres bills for.

    Returns ``{task_id: counts}`` with an entry for every task passed in, so a
    task without content still reads as zeroes.
    """
    tasks = list(tasks)
    counts = {
        task.pk: dict(_EMPTY_TASK_CONTENT_COUNTS)
        for task in tasks
    }
    available = [task for task in tasks if task.available]
    task_ids = [task.pk for task in available]
    if not task_ids:
        return counts

    for row in (
        Theme.objects.filter(task_id__in=task_ids, is_active=True)
        .order_by()
        .values("task_id")
        .annotate(total=Count("id"))
    ):
        counts[row["task_id"]]["theme_count"] = row["total"]

    for row in (
        Prompt.objects.filter(theme__task_id__in=task_ids, is_active=True)
        .order_by()
        .values("theme__task_id")
        .annotate(total=Count("id"))
    ):
        counts[row["theme__task_id"]]["prompt_count"] = row["total"]

    for row in (
        Phrase.objects.filter(
            is_active=True,
            tier__in=(
                PhraseTier.SHARED,
                PhraseTier.SUBJECT,
                PhraseTier.THEME,
            ),
            source_prompts__is_active=True,
            source_prompts__theme__is_active=True,
            source_prompts__theme__task_id__in=task_ids,
        )
        .order_by()
        .values("source_prompts__theme__task_id")
        .annotate(
            shared=Count("id", distinct=True, filter=Q(tier=PhraseTier.SHARED)),
            functional=Count(
                "id",
                distinct=True,
                filter=Q(
                    tier=PhraseTier.SHARED,
                    category__name__in=FUNCTIONAL_PHRASE_CATEGORY_NAMES,
                ),
            ),
            subject=Count(
                "id",
                distinct=True,
                filter=Q(tier=PhraseTier.SUBJECT),
            ),
            theme=Count("id", distinct=True, filter=Q(tier=PhraseTier.THEME)),
        )
    ):
        entry = counts[row["source_prompts__theme__task_id"]]
        entry["phrase_count"] = row["shared"]
        entry["functional_phrase_count"] = row["functional"]
        entry["subject_vocabulary_count"] = row["subject"]
        entry["theme_vocabulary_count"] = row["theme"]

    for row in (
        Prompt.objects.filter(
            is_active=True,
            response__is_active=True,
            theme__is_active=True,
            theme__task_id__in=task_ids,
            phrases__is_active=True,
            phrases__tier=PhraseTier.SUBJECT,
        )
        .order_by()
        .values("theme__task_id")
        .annotate(total=Count("id", distinct=True))
    ):
        counts[row["theme__task_id"]]["subject_vocabulary_prompt_count"] = row[
            "total"
        ]

    writing_task_ids = [
        task.pk
        for task in available
        if (task.part.slug, task.slug) == content_module.EE_TACHE_ONE_TASK
    ]
    if writing_task_ids:
        _add_writing_sujet_counts(counts, writing_task_ids)
    return counts


def _add_writing_sujet_counts(counts, task_ids):
    """EE Tâche 1 sujet ids, category count, and model-response count."""
    sujet_ids_by_task = {task_id: [] for task_id in task_ids}
    categories_by_task = {task_id: set() for task_id in task_ids}
    for task_id, sujet_id, category in WritingSujet.objects.filter(
        task_id__in=task_ids,
        is_active=True,
    ).values_list("task_id", "pk", "category"):
        sujet_ids_by_task[task_id].append(sujet_id)
        categories_by_task[task_id].add(category)
    for task_id in task_ids:
        entry = counts[task_id]
        entry["writing_sujet_ids"] = sujet_ids_by_task[task_id]
        entry["writing_sujet_category_count"] = len(categories_by_task[task_id])

    for row in (
        WritingSujet.objects.filter(task_id__in=task_ids, is_active=True)
        .exclude(versions=[])
        .order_by()
        .values("task_id")
        .annotate(total=Count("id"))
    ):
        counts[row["task_id"]]["writing_sujet_response_count"] = row["total"]


def _counts_for_task(task, content_counts=None):
    """Counts for one task, batched by the caller when possible."""
    if content_counts and task.pk in content_counts:
        return content_counts[task.pk]
    return _task_content_counts([task])[task.pk]


def _ee_tache_one_task_card(task, user, content_counts=None, summary=None):
    """Deck card for EE Tâche 1 with explicit subject completion."""
    counts = _counts_for_task(task, content_counts)
    sujet_ids = list(counts["writing_sujet_ids"])
    total = len(sujet_ids)
    response_total = counts["writing_sujet_response_count"]
    if summary is not None and summary["stats"] is not None:
        stats = summary["stats"]
        total = summary["prompt_count"]
    else:
        progress_by_sujet = writing_sujet_progress_by_id(
            user,
            sujet_ids,
        )
        started = sum(
            progress.started for progress in progress_by_sujet.values()
        )
        completed = sum(
            progress.completed for progress in progress_by_sujet.values()
        )
        progress = progress_summary(
            total=total,
            started=started,
            completed=completed,
        )
        stats = {
            "progress": progress,
            "total": progress.total,
            "completed": progress.completed,
            "started_new": max(started - completed, 0),
            "seen": started,
            "due": 0,
        }
    return {
        "task": task,
        "stats": stats,
        "response_stats": {"total": response_total},
        "phrase_stats": None,
        "functional_phrase_stats": None,
        "counts": None,
        "phrase_counts": None,
        "revisit_count": 0,
        "theme_count": counts["writing_sujet_category_count"],
        "prompt_count": total,
        "phrase_count": 0,
        "functional_phrase_count": 0,
        "subject_vocabulary_count": 0,
        "subject_vocabulary_prompt_count": 0,
        "question_bank": None,
        "show_phrases": False,
    }


def _task_card(
    task,
    now,
    user,
    *,
    with_stats=True,
    with_deck_stats=True,
    content_counts=None,
    summaries=None,
):
    """Build a part-page card for a single task.

    ``with_stats=False`` skips every SRS aggregate for callers that only need
    the content counts. ``with_deck_stats=False`` keeps the subject progress
    summary but drops the per-deck vocabulary stats and queue counts, for
    callers that only render subject progress — the expression hub and the home
    page reach those numbers through :func:`expression_task_summaries` instead.
    ``content_counts`` is the :func:`_task_content_counts` mapping for every
    task on the page; when it is missing (or lacks this task) the counts are
    fetched for this task alone. ``summaries`` is the matching
    :func:`expression_task_summaries` mapping: it carries the same subject
    summary this card would otherwise rebuild one task at a time, so passing it
    removes the per-task prompt lookup, subject-progress pass and due
    aggregate.
    """
    question_bank = None
    subject_state = None
    summary = (summaries or {}).get(task.pk)
    if (
        task.available
        and (task.part.slug, task.slug) == content_module.EE_TACHE_ONE_TASK
    ):
        return _ee_tache_one_task_card(task, user, content_counts, summary)
    content_totals = (
        _counts_for_task(task, content_counts)
        if task.available
        else _EMPTY_TASK_CONTENT_COUNTS
    )
    batched_stats = (
        dict(summary["stats"])
        if summary is not None and summary["stats"] is not None
        else None
    )
    if (
        task.available
        and with_stats
        and (task.part.slug, task.slug) == content_module.QUESTION_BANK_TASK
    ):
        if batched_stats is None:
            subject_state = _tache_two_progress(
                user,
                content_module.load_tache_two_subject_months(),
            )
            subject_summary = subject_state["summary"]
        else:
            subject_summary = batched_stats
        vocabulary_batches = _review_batches(
            {
                **_task_scope(task),
                "kind": "theme_vocab",
            },
            user,
        )
        vocabulary_progress = summarize_review_batches(vocabulary_batches)
        task_progress = combine_progress(
            [vocabulary_progress, subject_summary["progress"]]
        )
        vocabulary_count = content_totals["theme_vocabulary_count"]
        vocabulary_theme_count = len(
            content_module.load_tache_two_subject_themes()[0]
        )
        question_bank = {
            "title": "Vocabulaire par thème",
            "theme_vocabulary": True,
            "theme_count": vocabulary_theme_count,
            "vocabulary_count": vocabulary_count,
            "batch_count": len(vocabulary_batches),
            "subject_count": subject_summary["total"],
            "progress": task_progress,
            "vocabulary_progress": vocabulary_progress,
            "subject_progress": subject_summary["progress"],
            "active_count": max(
                task_progress.started - task_progress.completed,
                0,
            ),
        }
    if task.available:
        if not with_stats:
            response_stats = None
            phrase_stats = None
            functional_phrase_stats = None
            stats = None
            counts = None
            phrase_counts = None
            revisit_count = 0
        else:
            if batched_stats is not None:
                response_stats = batched_stats
            elif subject_state is None:
                response_ids = set(
                    Prompt.objects.filter(
                        theme__task=task,
                        theme__is_active=True,
                        is_active=True,
                        response__is_active=True,
                    ).values_list("response_id", flat=True)
                )
                response_progress = subject_progress_by_response(
                    user,
                    response_ids,
                )
                response_stats = summarize_subject_progress(
                    response_progress.values()
                )
            else:
                response_stats = dict(subject_state["summary"])
            if batched_stats is None:
                response_stats["due"] = deck_stats(
                    _task_cards(task, user, "spine"),
                    now,
                )["due"]
            stats = response_stats
            if with_deck_stats:
                phrase_stats = deck_stats(
                    _task_cards(task, user, "phrase"), now
                )
                functional_phrase_stats = deck_stats(
                    _task_cards(task, user, "phrase").filter(
                        phrase__tier=PhraseTier.SHARED,
                        phrase__category__name__in=(
                            FUNCTIONAL_PHRASE_CATEGORY_NAMES
                        ),
                    ),
                    now,
                )
                counts = queue_module.queue_counts(
                    _task_scope(task),
                    now,
                    user=user,
                )
                phrase_counts = queue_module.queue_counts(
                    {**_task_scope(task), "kind": "phrase"},
                    now,
                    user=user,
                )
                revisit_count = queue_module.scoped_count(
                    _task_cards(task, user, "revisit")
                )
            else:
                phrase_stats = None
                functional_phrase_stats = None
                counts = None
                phrase_counts = None
                revisit_count = 0
        theme_count = content_totals["theme_count"]
        prompt_count = content_totals["prompt_count"]
        phrase_count = content_totals["phrase_count"]
        functional_phrase_count = content_totals["functional_phrase_count"]
        subject_vocabulary_count = content_totals["subject_vocabulary_count"]
        subject_vocabulary_prompt_count = content_totals[
            "subject_vocabulary_prompt_count"
        ]
    else:
        response_stats = None
        phrase_stats = None
        functional_phrase_stats = None
        stats = None
        counts = None
        phrase_counts = None
        revisit_count = 0
        theme_count = 0
        prompt_count = 0
        phrase_count = 0
        functional_phrase_count = 0
        subject_vocabulary_count = 0
        subject_vocabulary_prompt_count = 0
    return {
        "task": task,
        "stats": stats,
        "response_stats": response_stats,
        "phrase_stats": phrase_stats,
        "functional_phrase_stats": functional_phrase_stats,
        "counts": counts,
        "phrase_counts": phrase_counts,
        "revisit_count": revisit_count,
        "theme_count": theme_count,
        "prompt_count": prompt_count,
        "phrase_count": phrase_count,
        "functional_phrase_count": functional_phrase_count,
        "subject_vocabulary_count": subject_vocabulary_count,
        "subject_vocabulary_prompt_count": subject_vocabulary_prompt_count,
        "question_bank": question_bank,
        "show_phrases": bool(phrase_count),
    }


def _due_response_counts_by_task(user, task_ids, now):
    """Due response cards per task, in one aggregate instead of one per task.

    Equivalent to ``deck_stats(_task_cards(task, user, "spine"), now)["due"]``
    run for every task: a spine card always targets a response (a card may hold
    a response or a phrase, never both), so grouping by the response's task
    resolves to the same cards the per-task queue scope selects.
    """
    if not task_ids:
        return {}
    return {
        row["response__theme__task_id"]: row["total"]
        for row in (
            Card.objects.current_content()
            .filter(
                user=user,
                card_type=CardType.SPINE,
                suspended=False,
                state__in=_DUE_CARD_STATES,
                due__lte=now,
                response__theme__task_id__in=task_ids,
            )
            .order_by()
            .values("response__theme__task_id")
            .annotate(total=Count("id", distinct=True))
        )
    }


def _expression_prompt_rows(task_ids):
    """Active prompts of several tasks, with the flags their totals filter on.

    One row per prompt, so the caller can count prompts per task and collect
    the responses those prompts point at without a query per task.
    """
    if not task_ids:
        return ()
    return (
        Prompt.objects.filter(theme__task_id__in=task_ids, is_active=True)
        .order_by()
        .values_list(
            "theme__task_id",
            "content_key",
            "response_id",
            "theme__is_active",
            "response__is_active",
        )
    )


def _writing_task_summaries(summaries, user, task_ids, content_counts=None):
    """EE Tâche 1 progress, which counts sujets rather than responses."""
    if not task_ids:
        return
    sujet_ids_by_task = {task_id: [] for task_id in task_ids}
    if content_counts and all(
        task_id in content_counts for task_id in task_ids
    ):
        # The catalogue pass already listed every sujet of these tasks.
        for task_id in task_ids:
            sujet_ids_by_task[task_id] = list(
                content_counts[task_id]["writing_sujet_ids"]
            )
    else:
        for task_id, sujet_id in (
            WritingSujet.objects.filter(task_id__in=task_ids, is_active=True)
            .order_by()
            .values_list("task_id", "pk")
        ):
            sujet_ids_by_task[task_id].append(sujet_id)
    progress_by_sujet = writing_sujet_progress_by_id(
        user,
        [
            sujet_id
            for sujet_ids in sujet_ids_by_task.values()
            for sujet_id in sujet_ids
        ],
    )
    for task_id, sujet_ids in sujet_ids_by_task.items():
        items = [
            progress_by_sujet[sujet_id]
            for sujet_id in sujet_ids
            if sujet_id in progress_by_sujet
        ]
        started = sum(progress.started for progress in items)
        completed = sum(progress.completed for progress in items)
        summary = progress_summary(
            total=len(sujet_ids),
            started=started,
            completed=completed,
        )
        summaries[task_id] = {
            "prompt_count": len(sujet_ids),
            "stats": {
                "progress": summary,
                "total": summary.total,
                "completed": summary.completed,
                "started_new": max(started - completed, 0),
                "seen": started,
                "due": 0,
            },
        }


def expression_task_summaries(now, user, tasks, content_counts=None):
    """Hub and dashboard progress for many tasks in a fixed few queries.

    The expression hub and the home page read only four values per task: the
    active prompt count, and the subject summary's ``progress``, ``seen``,
    ``total`` and ``due``. Building a whole :func:`_task_card` to reach them
    costs about nine queries per task, because every task repeats the same
    prompt lookup, the same subject-progress lookups and the same due-card
    aggregate. This batches all of them: one prompt query, one subject-progress
    pass, and one due-card aggregate for the entire page.

    ``tasks`` should come from a part prefetch so ``task.part`` is already
    loaded. ``content_counts`` is an optional :func:`_task_content_counts`
    mapping; when the caller already has one, the EE Tâche 1 sujet ids come
    from it instead of a second lookup. Returns
    ``{task_id: {"prompt_count": int, "stats": dict | None}}`` with an entry
    for every task, unavailable ones reading as an empty card.
    """
    summaries = {
        task.pk: {"prompt_count": 0, "stats": None}
        for task in tasks
    }
    available = [task for task in tasks if task.available]
    if not available:
        return summaries

    writing_task_ids = []
    subject_task_ids = []
    question_bank_task_id = None
    for task in available:
        task_key = (task.part.slug, task.slug)
        if task_key == content_module.EE_TACHE_ONE_TASK:
            writing_task_ids.append(task.pk)
            continue
        subject_task_ids.append(task.pk)
        if task_key == content_module.QUESTION_BANK_TASK:
            question_bank_task_id = task.pk

    response_ids_by_task = {task_id: set() for task_id in subject_task_ids}
    response_id_by_content_key = {}
    for (
        task_id,
        content_key,
        response_id,
        theme_is_active,
        response_is_active,
    ) in _expression_prompt_rows(subject_task_ids):
        summaries[task_id]["prompt_count"] += 1
        if not response_is_active:
            continue
        response_id_by_content_key[content_key] = response_id
        if theme_is_active:
            response_ids_by_task[task_id].add(response_id)

    # Tâche 2 counts subject occurrences, not responses: equivalent subjects
    # share one response and one progress, yet each occurrence is a sujet.
    subject_keys_by_task = {}
    if question_bank_task_id is not None:
        subject_keys_by_task[question_bank_task_id] = tuple(
            content_module.tache_two_subject_content_key(
                month.slug,
                batch.number,
                subject.number,
            )
            for month in content_module.load_tache_two_subject_months()
            for batch in month.batches
            for subject in batch.subjects
        )

    wanted_response_ids = set()
    for task_id in subject_task_ids:
        content_keys = subject_keys_by_task.get(task_id)
        if content_keys is None:
            wanted_response_ids.update(response_ids_by_task[task_id])
            continue
        wanted_response_ids.update(
            response_id_by_content_key[content_key]
            for content_key in content_keys
            if content_key in response_id_by_content_key
        )

    progress_by_response = subject_progress_by_response(
        user,
        wanted_response_ids,
    )
    due_by_task = _due_response_counts_by_task(user, subject_task_ids, now)

    for task_id in subject_task_ids:
        content_keys = subject_keys_by_task.get(task_id)
        if content_keys is None:
            items = [
                progress_by_response[response_id]
                for response_id in response_ids_by_task[task_id]
            ]
        else:
            items = [
                progress_by_response.get(
                    response_id_by_content_key.get(content_key),
                    _EMPTY_SUBJECT_PROGRESS,
                )
                for content_key in content_keys
            ]
        stats = summarize_subject_progress(items)
        # The card counts due responses, not the due subject vocabulary the
        # subject summary carries.
        stats["due"] = due_by_task.get(task_id, 0)
        summaries[task_id]["stats"] = stats

    _writing_task_summaries(
        summaries,
        user,
        writing_task_ids,
        content_counts,
    )
    return summaries
