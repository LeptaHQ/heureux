"""The source-backed Learn curriculum and per-learner lesson progress."""

from __future__ import annotations

from django.db import transaction
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..learning_content import LearningCatalog, load_learning_catalog
from ..models import LearningLessonProgress
from ..progress import progress_summary


LEARNING_STATUS_LABELS = {
    "new": "À découvrir",
    "active": "En cours",
    "done": "Terminée",
}


def _learning_progress_rows(user, catalog: LearningCatalog) -> dict[str, dict]:
    lesson_ids = [lesson.id for lesson in catalog.lessons]
    return {
        row["lesson_id"]: row
        for row in LearningLessonProgress.objects.filter(
            user=user,
            lesson_id__in=lesson_ids,
        ).values("lesson_id", "started_at", "completed_at")
    }


def learning_summary(user, catalog: LearningCatalog | None = None) -> dict:
    catalog = catalog or load_learning_catalog()
    rows = _learning_progress_rows(user, catalog)
    completed_ids = {
        lesson_id
        for lesson_id, row in rows.items()
        if row["completed_at"] is not None
    }
    summary = progress_summary(
        total=len(catalog.lessons),
        started=len(rows),
        completed=len(completed_ids),
    )
    next_lesson = next(
        (
            lesson
            for lesson in catalog.lessons
            if lesson.id in rows and lesson.id not in completed_ids
        ),
        None,
    )
    if next_lesson is None:
        next_lesson = next(
            (
                lesson
                for lesson in catalog.lessons
                if lesson.id not in completed_ids
            ),
            None,
        )
    return {
        "progress": summary,
        "rows": rows,
        "completed_ids": completed_ids,
        "next_lesson": next_lesson,
        "next_url": (
            reverse("study:learn_lesson", args=[next_lesson.slug])
            if next_lesson
            else reverse("study:learn")
        ),
    }


def _lesson_card(lesson, progress_row):
    completed = bool(progress_row and progress_row["completed_at"])
    started = bool(progress_row)
    status = "done" if completed else "active" if started else "new"
    return {
        "lesson": lesson,
        "url": reverse("study:learn_lesson", args=[lesson.slug]),
        "progress_url": reverse(
            "study:learn_lesson_progress",
            args=[lesson.slug],
        ),
        "status": status,
        "status_label": LEARNING_STATUS_LABELS[status],
        "completed": completed,
        "started": started,
    }


def learn(request):
    catalog = load_learning_catalog()
    state = learning_summary(request.user, catalog)
    modules = []
    lesson_count = 0
    for module in catalog.modules:
        lessons = [
            _lesson_card(lesson, state["rows"].get(lesson.id))
            for lesson in module.lessons
        ]
        module_summary = progress_summary(
            total=len(lessons),
            started=sum(lesson["started"] for lesson in lessons),
            completed=sum(lesson["completed"] for lesson in lessons),
        )
        lesson_count += len(lessons)
        modules.append(
            {
                "module": module,
                "lessons": lessons,
                "progress": module_summary,
            }
        )
    return render(
        request,
        "study/learn.html",
        {
            "catalog": catalog,
            "modules": modules,
            "summary": state["progress"],
            "lesson_count": lesson_count,
        },
    )


def learn_lesson(request, lesson_slug):
    catalog = load_learning_catalog()
    result = catalog.lesson_by_slug(lesson_slug)
    if result is None:
        raise Http404
    module, lesson = result
    lessons = catalog.lessons
    lesson_index = lessons.index(lesson)
    previous_lesson = lessons[lesson_index - 1] if lesson_index else None
    next_lesson = (
        lessons[lesson_index + 1]
        if lesson_index + 1 < len(lessons)
        else None
    )
    state = learning_summary(request.user, catalog)
    progress_row = state["rows"].get(lesson.id)
    return render(
        request,
        "study/learn_lesson.html",
        {
            "catalog": catalog,
            "module": module,
            "lesson": lesson,
            "lesson_number": lesson_index + 1,
            "lesson_total": len(lessons),
            "is_started": progress_row is not None,
            "is_completed": bool(
                progress_row and progress_row["completed_at"] is not None
            ),
            "summary": state["progress"],
            "start_url": reverse(
                "study:learn_lesson_start",
                args=[lesson.slug],
            ),
            "progress_url": reverse(
                "study:learn_lesson_progress",
                args=[lesson.slug],
            ),
            "previous_lesson": previous_lesson,
            "next_lesson": next_lesson,
        },
    )


@require_POST
def learn_lesson_start(request, lesson_slug):
    catalog = load_learning_catalog()
    result = catalog.lesson_by_slug(lesson_slug)
    if result is None:
        raise Http404
    _module, lesson = result
    LearningLessonProgress.objects.get_or_create(
        user=request.user,
        lesson_id=lesson.id,
    )
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"started": True})
    return redirect(reverse("study:learn_lesson", args=[lesson.slug]))


@require_POST
def learn_lesson_progress(request, lesson_slug):
    catalog = load_learning_catalog()
    result = catalog.lesson_by_slug(lesson_slug)
    if result is None:
        raise Http404
    _module, lesson = result
    completed = request.POST.get("completed")
    if completed not in {"0", "1"}:
        message = "État de leçon invalide."
        if request.headers.get("X-Requested-With") == "fetch":
            return JsonResponse({"error": message}, status=400)
        return HttpResponseBadRequest(message)

    with transaction.atomic():
        progress, _created = (
            LearningLessonProgress.objects.select_for_update().get_or_create(
                user=request.user,
                lesson_id=lesson.id,
            )
        )
        if completed == "1" and progress.completed_at is None:
            progress.completed_at = timezone.now()
            progress.save(update_fields=["completed_at"])
        elif completed == "0" and progress.completed_at is not None:
            progress.completed_at = None
            progress.save(update_fields=["completed_at"])

    state = learning_summary(request.user, catalog)
    summary = state["progress"]
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse(
            {
                "completed": completed == "1",
                "completed_count": summary.completed,
                "total": summary.total,
                "percent": summary.percent,
                "status": summary.status,
                "status_label": summary.label,
            }
        )
    return redirect(
        reverse("study:learn_lesson", args=[lesson.slug])
        + "#lesson-completion"
    )
