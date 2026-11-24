"""Timed EE Tâche 1 writing simulation."""

from __future__ import annotations

import logging
import json
import threading
from datetime import timedelta

from django.db import close_old_connections, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from study.catalogue.loader import _ee_word_count
from study.expression.ee.tache_1 import evaluation
from study.models import (
    Task,
    WritingSimulationAttempt,
    WritingSimulationEvaluationStatus,
    WritingSimulationAttemptStatus,
    WritingSujet,
)


TASK_SLUG = "tache-1"
PART_SLUG = "ee"
WORD_MIN = 60
WORD_MAX = 120
SIMULATION_MINUTES = 20
MAX_BODY_LENGTH = 20_000
EVALUATION_STALE_AFTER = timedelta(minutes=5)
logger = logging.getLogger(__name__)


def _task():
    return get_object_or_404(
        Task.objects.select_related("part"),
        part__slug=PART_SLUG,
        part__is_active=True,
        part__available=True,
        slug=TASK_SLUG,
        is_active=True,
        available=True,
    )


def _single_post_value(request, key):
    values = request.POST.getlist(key)
    if len(values) != 1:
        raise ValueError(f"Le champ {key} est invalide.")
    return values[0]


def _attempt_context(attempt, *, error="", now=None):
    now = now or timezone.now()
    remaining = max(0, int((attempt.deadline_at - now).total_seconds()))
    return {
        "attempt": attempt,
        "task": attempt.task,
        "prompt": attempt.snapshot.get("prompt", ""),
        "category_label": attempt.snapshot.get("category_label", ""),
        "word_min": attempt.snapshot.get("word_min", WORD_MIN),
        "word_max": attempt.snapshot.get("word_max", WORD_MAX),
        "remaining_seconds": remaining,
        "word_count": _ee_word_count(attempt.body),
        "error": error,
    }


def _expire_if_needed(attempt, now=None):
    now = now or timezone.now()
    if (
        attempt.status == WritingSimulationAttemptStatus.ACTIVE
        and attempt.deadline_at <= now
    ):
        attempt.status = WritingSimulationAttemptStatus.EXPIRED
        attempt.submitted_at = now
        attempt.word_count = _ee_word_count(attempt.body)
        attempt.save(update_fields=["status", "submitted_at", "word_count"])
        return True
    return False


def _setup_context(request, task):
    subjects = list(
        WritingSujet.objects.filter(task=task, is_active=True)
        .only("pk", "category", "category_label", "prompt", "order")
        .order_by("category_label", "order", "pk")
    )
    categories = []
    by_category = {}
    for sujet in subjects:
        rows = by_category.setdefault(
            sujet.category,
            {"label": sujet.category_label, "subjects": []},
        )
        rows["subjects"].append(sujet)
    categories.extend(by_category.values())
    attempts = list(
        WritingSimulationAttempt.objects.filter(user=request.user, task=task)
        .select_related("sujet")
        .defer("body")
        .order_by("-started_at", "-id")[:8]
    )
    return {
        "task": task,
        "categories": categories,
        "attempts": attempts,
        "subject_count": len(subjects),
        "word_min": WORD_MIN,
        "word_max": WORD_MAX,
        "simulation_minutes": SIMULATION_MINUTES,
        "selected_sujet_id": request.GET.get("sujet_id", ""),
    }


@never_cache
@require_safe
def setup(request):
    task = _task()
    return render(
        request,
        "study/simulation/ee1_setup.html",
        _setup_context(request, task),
    )


@never_cache
@require_POST
@transaction.atomic
def start(request):
    task = _task()
    try:
        subject_value = _single_post_value(request, "sujet_id").strip()
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))

    subjects = WritingSujet.objects.filter(task=task, is_active=True)
    if subject_value:
        if not subject_value.isdigit():
            return HttpResponseBadRequest("Sujet invalide.")
        sujet = get_object_or_404(subjects, pk=int(subject_value))
    else:
        sujet = subjects.order_by("?").first()
        if sujet is None:
            return HttpResponseBadRequest("Aucun sujet EE1 n'est disponible.")

    now = timezone.now()
    attempt = WritingSimulationAttempt.objects.create(
        user=request.user,
        task=task,
        sujet=sujet,
        snapshot={
            "prompt": sujet.prompt,
            "category": sujet.category,
            "category_label": sujet.category_label,
            "sujet_slug": sujet.slug,
            "word_min": WORD_MIN,
            "word_max": WORD_MAX,
            "simulation_minutes": SIMULATION_MINUTES,
        },
        started_at=now,
        deadline_at=now + timedelta(minutes=SIMULATION_MINUTES),
    )
    return redirect("study:ee1_simulation_attempt", attempt_id=attempt.pk)


@never_cache
@require_http_methods(["GET", "POST"])
def attempt(request, attempt_id):
    if request.method == "GET":
        with transaction.atomic():
            attempt = get_object_or_404(
                WritingSimulationAttempt.objects.select_for_update(of=("self",)).select_related(
                    "task__part", "sujet",
                ),
                user=request.user,
                pk=attempt_id,
            )
            _expire_if_needed(attempt)
            is_active = attempt.status == WritingSimulationAttemptStatus.ACTIVE
        if not is_active:
            return render(
                request,
                "study/simulation/ee1_result.html",
                {"attempt": attempt, "task": attempt.task},
            )
        return render(
            request,
            "study/simulation/ee1_attempt.html",
            _attempt_context(attempt),
        )

    try:
        action = _single_post_value(request, "action")
        body = _single_post_value(request, "body")
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if action not in {"save", "submit", "abandon"}:
        return HttpResponseBadRequest("Action invalide.")
    with transaction.atomic():
        attempt = get_object_or_404(
            WritingSimulationAttempt.objects.select_for_update(of=("self",)).select_related(
                "task__part", "sujet",
            ),
            user=request.user,
            pk=attempt_id,
        )
        if attempt.status != WritingSimulationAttemptStatus.ACTIVE:
            return redirect("study:ee1_simulation_attempt", attempt_id=attempt.pk)
        if len(body) > MAX_BODY_LENGTH:
            attempt.body = body
            return render(
                request,
                "study/simulation/ee1_attempt.html",
                _attempt_context(
                    attempt,
                    error="Votre réponse est trop longue pour être enregistrée.",
                ),
                status=400,
            )

        now = timezone.now()
        attempt.body = body
        attempt.last_saved_at = now
        if attempt.deadline_at <= now:
            attempt.status = WritingSimulationAttemptStatus.EXPIRED
            attempt.submitted_at = now
            attempt.word_count = _ee_word_count(body)
            attempt.save(
                update_fields=[
                    "body",
                    "last_saved_at",
                    "status",
                    "submitted_at",
                    "word_count",
                ]
            )
            return redirect("study:ee1_simulation_attempt", attempt_id=attempt.pk)

        if action == "save":
            attempt.save(update_fields=["body", "last_saved_at"])
            return redirect(
                reverse("study:ee1_simulation_attempt", args=[attempt.pk])
                + "?saved=1"
            )

        if action == "abandon":
            attempt.status = WritingSimulationAttemptStatus.ABANDONED
            attempt.submitted_at = now
            attempt.word_count = _ee_word_count(body)
            attempt.save(
                update_fields=[
                    "body",
                    "last_saved_at",
                    "status",
                    "submitted_at",
                    "word_count",
                ]
            )
            return redirect("study:ee1_simulation_attempt", attempt_id=attempt.pk)

        cleaned = body.strip()
        word_count = _ee_word_count(cleaned)
        if not cleaned:
            error = "Rédigez votre message avant de le remettre."
        elif word_count < WORD_MIN or word_count > WORD_MAX:
            error = f"Votre message doit compter entre {WORD_MIN} et {WORD_MAX} mots."
        else:
            attempt.body = cleaned
            attempt.status = WritingSimulationAttemptStatus.SUBMITTED
            attempt.submitted_at = now
            attempt.last_saved_at = now
            attempt.word_count = word_count
            attempt.save(
                update_fields=[
                    "body",
                    "status",
                    "submitted_at",
                    "last_saved_at",
                    "word_count",
                ]
            )
            return redirect("study:ee1_simulation_attempt", attempt_id=attempt.pk)

        attempt.body = body
        return render(
            request,
            "study/simulation/ee1_attempt.html",
            _attempt_context(attempt, error=error, now=now),
            status=400,
        )


def _evaluation_payload(attempt):
    stale = (
        attempt.evaluation_status == WritingSimulationEvaluationStatus.PROCESSING
        and attempt.evaluation_started_at
        and timezone.now() - attempt.evaluation_started_at >= EVALUATION_STALE_AFTER
    )
    return {
        "status": (
            WritingSimulationEvaluationStatus.UNAVAILABLE
            if stale
            else attempt.evaluation_status
        ),
        "report": attempt.evaluation if attempt.evaluation_status == WritingSimulationEvaluationStatus.READY else None,
        "error": (
            "Le bilan précédent n’a pas abouti. Vous pouvez relancer l’évaluation."
            if stale
            else attempt.evaluation_error
            if attempt.evaluation_status == WritingSimulationEvaluationStatus.UNAVAILABLE
            else ""
        ),
        "retryable": stale or attempt.evaluation_status == WritingSimulationEvaluationStatus.UNAVAILABLE,
    }


def _run_evaluation(attempt_id, started_at):
    close_old_connections()
    try:
        attempt = WritingSimulationAttempt.objects.filter(
            pk=attempt_id,
            evaluation_status=WritingSimulationEvaluationStatus.PROCESSING,
            evaluation_started_at=started_at,
        ).only("snapshot", "body", "word_count").first()
        if attempt is None:
            return
        try:
            report = evaluation.score(
                subject=attempt.snapshot.get("prompt", ""),
                response=attempt.body,
                word_count=attempt.word_count or _ee_word_count(attempt.body),
            )
        except evaluation.oral_evaluation.EvaluationError as exc:
            status = WritingSimulationEvaluationStatus.UNAVAILABLE
            error = str(exc)
            report = {}
        except Exception:
            logger.exception("EE1 evaluation worker failed")
            status = WritingSimulationEvaluationStatus.UNAVAILABLE
            error = "Le bilan est temporairement indisponible. Votre réponse reste disponible."
            report = {}
        else:
            status = WritingSimulationEvaluationStatus.READY
            error = ""
        with transaction.atomic():
            current = WritingSimulationAttempt.objects.select_for_update().filter(
                pk=attempt_id,
                evaluation_status=WritingSimulationEvaluationStatus.PROCESSING,
                evaluation_started_at=started_at,
            ).first()
            if current is None:
                return
            current.evaluation_status = status
            current.evaluation = report
            current.evaluation_error = error
            current.evaluated_at = timezone.now()
            current.save(
                update_fields=[
                    "evaluation_status",
                    "evaluation",
                    "evaluation_error",
                    "evaluated_at",
                ]
            )
    finally:
        close_old_connections()


@never_cache
@require_http_methods(["GET", "POST"])
@csrf_protect
def evaluate(request, attempt_id):
    if request.method == "POST":
        if request.content_type != "application/json":
            return HttpResponseBadRequest("Un consentement explicite est requis.")
        try:
            data = json.loads(request.body or b"{}")
        except (TypeError, ValueError):
            return HttpResponseBadRequest("Un consentement explicite est requis.")
        if data != {"consent": True}:
            return HttpResponseBadRequest("Un consentement explicite est requis.")
    with transaction.atomic():
        attempt = get_object_or_404(
            WritingSimulationAttempt.objects.select_for_update(of=("self",)),
            user=request.user,
            pk=attempt_id,
        )
        if attempt.status not in {
            WritingSimulationAttemptStatus.SUBMITTED,
            WritingSimulationAttemptStatus.EXPIRED,
        }:
            return HttpResponseBadRequest("Cette réponse ne peut pas encore être évaluée.")
        if not attempt.body.strip():
            return HttpResponseBadRequest("Aucune réponse à évaluer.")
        if request.method == "GET":
            return render(request, "study/simulation/ee1_result.html", {
                "attempt": attempt,
                "task": attempt.task,
            }) if request.headers.get("Accept") == "text/html" else _evaluation_json(attempt)
        if attempt.evaluation_status == WritingSimulationEvaluationStatus.READY:
            return _evaluation_json(attempt)
        now = timezone.now()
        if (
            attempt.evaluation_status == WritingSimulationEvaluationStatus.PROCESSING
            and attempt.evaluation_started_at
            and now - attempt.evaluation_started_at < EVALUATION_STALE_AFTER
        ):
            return _evaluation_json(attempt, status=202)
        attempt.evaluation_status = WritingSimulationEvaluationStatus.PROCESSING
        attempt.evaluation = {}
        attempt.evaluation_error = ""
        attempt.evaluation_started_at = now
        attempt.evaluated_at = None
        attempt.save(
            update_fields=[
                "evaluation_status",
                "evaluation",
                "evaluation_error",
                "evaluation_started_at",
                "evaluated_at",
            ]
        )
        transaction.on_commit(
            lambda attempt_id=attempt.pk, started_at=now: threading.Thread(
                target=_run_evaluation,
                args=(attempt_id, started_at),
                daemon=True,
            ).start()
        )
        return _evaluation_json(attempt, status=202)


def _evaluation_json(attempt, *, status=200):
    from django.http import JsonResponse

    return JsonResponse(_evaluation_payload(attempt), status=status)
