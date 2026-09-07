"""Dedicated learning, check, review and unscored production pages."""

from dataclasses import asdict

from django.db import transaction
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from ..course_content import load_course_catalog
from ..course_practice import (
    PracticeError, abandon_attempt, evidence_state, practice_event, public_snapshot,
    start_attempt, submit_check,
)
from ..models import CourseAttempt, CourseProduction


def _lesson(slug):
    result = load_course_catalog().lesson_by_slug(slug)
    if result is None:
        raise Http404
    return result[1]


@never_cache
@require_http_methods(["GET", "POST"])
def course_practice(request, lesson_slug):
    lesson = _lesson(lesson_slug)
    error = ""
    if request.method == "POST":
        try:
            attempt = start_attempt(request.user, lesson, request.POST.get("mode"))
        except PracticeError as exc:
            error = str(exc)
        else:
            return redirect("study:course_attempt", attempt_id=attempt.pk)
    return render(request, "study/course_practice.html", {
        "lesson": lesson, "evidence": evidence_state(request.user, lesson),
        "attempts": CourseAttempt.objects.filter(user=request.user, lesson_id=lesson.id),
        "productions": CourseProduction.objects.filter(user=request.user, lesson_id=lesson.id),
        "error": error,
    }, status=400 if error else 200)


def _attempt_context(attempt):
    items = public_snapshot(attempt)["items"]
    first = {}
    hints = set()
    for event in attempt.events:
        if event["action"] == "answer":
            first.setdefault(event["item_id"], event)
        else:
            hints.add(event["item_id"])
    for item, private in zip(items, attempt.snapshot["items"]):
        item["answer"] = first.get(item["id"])
        item["hinted"] = item["id"] in hints
        if attempt.status == "completed" or (
            attempt.mode == "practice" and (item["answer"] or item["hinted"])
        ):
            item["feedback"] = {
                "answers": private["answers"], "explanation": private["explanation"],
            }
    return {"attempt": attempt, "items": items}


@never_cache
@require_http_methods(["GET", "POST"])
def course_attempt(request, attempt_id):
    attempt = get_object_or_404(CourseAttempt, user=request.user, pk=attempt_id)
    error = ""
    if request.method == "POST":
        action = request.POST.get("action", "submit")
        try:
            if action == "abandon":
                abandon_attempt(request.user, attempt.pk)
            elif attempt.mode == "practice":
                practice_event(
                    request.user, attempt.pk, request.POST.get("item_id"),
                    action, request.POST.get("response", ""),
                )
            elif action == "submit":
                responses = {
                    key.removeprefix("answer-"): request.POST[key]
                    for key in request.POST if key.startswith("answer-")
                }
                if any(len(request.POST.getlist(key)) != 1 for key in request.POST):
                    raise PracticeError("Duplicate form fields are not accepted.")
                submit_check(request.user, attempt.pk, responses)
            else:
                raise PracticeError("Checks do not offer hints or answer previews.")
        except PracticeError as exc:
            error = str(exc)
        else:
            return redirect("study:course_attempt", attempt_id=attempt.pk)
    return render(
        request, "study/course_attempt.html",
        {**_attempt_context(attempt), "error": error}, status=400 if error else 200,
    )


@require_POST
def course_production_create(request, lesson_slug):
    lesson = _lesson(lesson_slug)
    body = request.POST.get("body", "").strip()
    if not body or len(body) > 20000:
        return HttpResponseBadRequest("Write a response of 1 to 20,000 characters.")
    production = CourseProduction.objects.create(
        user=request.user, lesson_id=lesson.id, content_version=lesson.content_version,
        task_snapshot={
            **asdict(lesson.production_task), "rubric": list(lesson.production_task.rubric),
            "title": lesson.title, "slug": lesson.slug,
        },
        body=body,
    )
    return redirect("study:course_production", production_id=production.pk)


@never_cache
@require_http_methods(["GET", "POST"])
def course_production(request, production_id):
    production = get_object_or_404(CourseProduction, user=request.user, pk=production_id)
    if request.method == "POST":
        if request.POST.get("reviewed") != "1":
            return HttpResponseBadRequest("Confirm your own review of the rubric.")
        with transaction.atomic():
            production = CourseProduction.objects.select_for_update().get(pk=production.pk, user=request.user)
            if production.self_reviewed_at is None:
                production.self_reviewed_at = timezone.now()
                production.save(update_fields=["self_reviewed_at"])
        return redirect("study:course_production", production_id=production.pk)
    return render(request, "study/course_production.html", {"production": production})
