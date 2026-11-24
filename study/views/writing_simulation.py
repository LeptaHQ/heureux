"""Shared timed simulation views for EE Tâche 1 and Tâche 2."""

from __future__ import annotations

import json
import logging
import threading
import unicodedata
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.paginator import Paginator
from django.db import close_old_connections, transaction
from django.db.models import Count, Max
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_http_methods, require_POST, require_safe
from django.views.decorators.vary import vary_on_headers

from study.catalogue import loader as content_module
from study.catalogue.loader import _ee_word_count
from study.models import (
    Task,
    WritingSimulationAttempt,
    WritingSimulationAttemptStatus,
    WritingSimulationEvaluationStatus,
    WritingSujet,
)
from study.review.progress import writing_sujet_progress_by_id

logger = logging.getLogger(__name__)

MAX_BODY_LENGTH = 20_000
EVALUATION_STALE_AFTER = timedelta(minutes=5)
PICKER_STATUSES = {"new": "Sans séance", "done": "Déjà pratiqués"}
PICKER_ORDERS = {"recent": "Dernière séance", "least": "Moins pratiqués d’abord"}


@dataclass(frozen=True)
class WritingSimulationSpec:
    number: int
    word_min: int
    word_max: int
    minutes_setting: str
    evaluator: object
    response_label: str
    response_placeholder: str
    session_prompt: str
    picker_intro: str

    @property
    def task_slug(self):
        return f"tache-{self.number}"

    @property
    def task_label(self):
        return f"EE Tâche {self.number}"

    @property
    def route_prefix(self):
        return f"ee{self.number}_simulation"

    @property
    def minutes(self):
        return getattr(settings, self.minutes_setting)

    @property
    def route_names(self):
        prefix = self.route_prefix
        return {
            "picker": f"study:ee{self.number}_subject_picker",
            "setup": f"study:{prefix}",
            "start": f"study:{prefix}_start",
            "attempt": f"study:{prefix}_attempt",
            "timer": f"study:{prefix}_timer",
            "evaluate": f"study:{prefix}_evaluate",
        }

    @property
    def context(self):
        return {
            "number": self.number,
            "code": f"EE{self.number}",
            "label": self.task_label,
            "word_min": self.word_min,
            "word_max": self.word_max,
            "minutes": self.minutes,
            "response_label": self.response_label,
            "response_placeholder": self.response_placeholder,
        }


def task_for(spec):
    return get_object_or_404(
        Task.objects.select_related("part"),
        part__slug="ee",
        part__is_active=True,
        part__available=True,
        slug=spec.task_slug,
        is_active=True,
        available=True,
    )


def _single_post_value(request, key):
    values = request.POST.getlist(key)
    if len(values) != 1:
        raise ValueError(f"Le champ {key} est invalide.")
    return values[0]


def _fold(value):
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )


def _session_steps(spec, *, done=False, minutes=None):
    minutes = spec.minutes if minutes is None else minutes
    return [
        {
            "key": "reading",
            "name": "Consigne",
            "meta": "à lire",
            "about": "Prenez connaissance de la situation et du destinataire.",
        },
        {
            "key": "live",
            "name": "Rédaction",
            "meta": f"{minutes} min",
            "about": "Rédigez votre production sans correction automatique.",
        },
        {
            "key": "done",
            "name": "Bilan",
            "meta": "à chaud",
            "about": "Relisez votre production et consultez votre session.",
        },
    ]


def _session_context(
    spec,
    *,
    selected_subject="",
    title="Simulation",
    prompt=None,
    minutes=None,
    done=False,
):
    minutes = spec.minutes if minutes is None else minutes
    route_names = spec.route_names
    return {
        "simulation": spec.context,
        **spec.context,
        "route_names": route_names,
        "session_back_url": reverse(route_names["picker"]),
        "session_back_label": "Choisir un sujet",
        "session_brand_icon": "pen-line",
        "session_brand": f"Studio écrit · {spec.task_label}",
        "session_kicker": "Expression écrite",
        "session_title": title,
        "session_prompt": prompt or spec.session_prompt.format(
            word_min=spec.word_min,
            word_max=spec.word_max,
            minutes=minutes,
        ),
        "session_selected_subject": selected_subject,
        "session_steps": _session_steps(spec, done=done, minutes=minutes),
        "session_show_clock": False,
    }


@require_GET
@vary_on_headers("X-Requested-With")
def subject_picker(request, spec):
    task = task_for(spec)
    subjects = list(
        WritingSujet.objects.filter(task=task, is_active=True)
        .only("pk", "category", "category_label", "prompt", "order", "slug")
        .order_by("category_label", "order", "pk")
    )
    subjects_by_slug = {sujet.slug: sujet for sujet in subjects}
    canonical_slug_by_slug = content_module.ee_writing_canonical_slug_by_slug(
        spec.number
    )
    progress_sujet_id_by_id = {
        sujet.pk: subjects_by_slug.get(
            canonical_slug_by_slug.get(sujet.slug, sujet.slug),
            sujet,
        ).pk
        for sujet in subjects
    }
    attempts = {
        row["sujet_id"]: row
        for row in WritingSimulationAttempt.objects.filter(
            user=request.user,
            task=task,
            sujet__isnull=False,
        )
        .values("sujet_id")
        .annotate(count=Count("pk"), latest=Max("started_at"))
    }
    query = request.GET.get("q", "").strip()[:120]
    category = request.GET.get("theme", "")
    status = request.GET.get("etat", "")
    if status not in PICKER_STATUSES:
        status = ""
    order = request.GET.get("tri", "")
    if order not in {"az", "za", *PICKER_ORDERS}:
        order = ""

    categories = {}
    rows = []
    needle = _fold(query)
    for sujet in subjects:
        categories[sujet.category] = sujet.category_label
        summary = attempts.get(sujet.pk, {})
        count = summary.get("count", 0)
        if (
            (category and sujet.category != category)
            or (status == "new" and count)
            or (status == "done" and not count)
            or (
                needle
                and needle not in _fold(f"{sujet.prompt} {sujet.category_label}")
            )
        ):
            continue
        rows.append(
            {
                "sujet": sujet,
                "count": count,
                "latest": summary.get("latest"),
                "setup_url": (
                    f"{reverse(spec.route_names['setup'])}?sujet_id={sujet.pk}"
                ),
            }
        )

    if order in {"az", "za"}:
        rows.sort(key=lambda row: _fold(row["sujet"].prompt), reverse=order == "za")
    elif order == "recent":
        rows.sort(
            key=lambda row: (row["latest"] is not None, row["latest"]),
            reverse=True,
        )
    elif order == "least":
        rows.sort(key=lambda row: row["count"])

    page = Paginator(rows, 15).get_page(request.GET.get("page"))
    progress_by_id = writing_sujet_progress_by_id(
        request.user,
        {
            progress_sujet_id_by_id[row["sujet"].pk]
            for row in page.object_list
        },
        task_id=task.pk,
    )
    for row in page.object_list:
        progress_sujet_id = progress_sujet_id_by_id[row["sujet"].pk]
        row["progress_sujet_id"] = progress_sujet_id
        row["progress"] = progress_by_id[progress_sujet_id]

    practiced_total = sum(
        bool(attempts.get(sujet.pk, {}).get("count")) for sujet in subjects
    )
    picker = {
        "back_url": reverse("study:simulation_track", args=["ee"]),
        "back_label": "Expression écrite",
        "kicker": f"Simulation · {spec.task_label}",
        "title": "Choisir un sujet",
        "heading_id": f"ee{spec.number}-title",
        "intro": spec.picker_intro.format(
            word_min=spec.word_min,
            word_max=spec.word_max,
        ),
        "tone": "sim-tone--ee",
        "icon": "pen-line",
        "results_id": f"ee{spec.number}-topic-results",
        "kind": f"ee{spec.number}",
        "show_practice_summary": True,
    }
    return render(
        request,
        (
            "study/simulation/subject_picker_results.html"
            if request.headers.get("X-Requested-With") == "fetch"
            else "study/simulation/subject_picker.html"
        ),
        {
            "task": task,
            "page": page,
            "total": len(subjects),
            "practiced_total": practiced_total,
            "picker": picker,
            "directory_selection": {
                "themes": sorted(categories.items(), key=lambda item: _fold(item[1])),
                "theme": category,
                "unavailable_theme": category and category not in categories,
                "query": query,
                "status": status,
                "order": order,
                "active": bool(category or query or status or order),
                "status_choices": PICKER_STATUSES.items(),
                "extra_orders": PICKER_ORDERS.items(),
            },
        },
    )


def _setup_context(request, spec, task):
    subjects = list(
        WritingSujet.objects.filter(task=task, is_active=True)
        .only("pk", "category", "category_label", "prompt", "order")
        .order_by("category_label", "order", "pk")
    )
    by_category = {}
    for sujet in subjects:
        by_category.setdefault(
            sujet.category,
            {"label": sujet.category_label, "subjects": []},
        )["subjects"].append(sujet)
    selected_sujet_id = request.GET.get("sujet_id", "")
    selected_sujet = next(
        (sujet for sujet in subjects if str(sujet.pk) == selected_sujet_id),
        None,
    )
    attempts = list(
        WritingSimulationAttempt.objects.filter(user=request.user, task=task)
        .select_related("sujet")
        .defer("body")
        .order_by("-started_at", "-id")[:8]
    )
    return {
        **_session_context(
            spec,
            selected_subject=selected_sujet.prompt if selected_sujet else "",
        ),
        "task": task,
        "categories": list(by_category.values()),
        "attempts": attempts,
        "subject_count": len(subjects),
        "selected_sujet_id": selected_sujet_id,
        "start_url": reverse(spec.route_names["start"]),
    }


@never_cache
@require_safe
def setup(request, spec):
    task = task_for(spec)
    return render(
        request,
        "study/simulation/writing_simulation_setup.html",
        _setup_context(request, spec, task),
    )


@never_cache
@require_POST
@transaction.atomic
def start(request, spec):
    task = task_for(spec)
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
            return HttpResponseBadRequest(f"Aucun sujet {spec.task_label} n'est disponible.")

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
            "word_min": spec.word_min,
            "word_max": spec.word_max,
            "simulation_minutes": spec.minutes,
        },
        started_at=now,
        deadline_at=now + timedelta(minutes=spec.minutes),
    )
    return redirect(spec.route_names["attempt"], attempt_id=attempt.pk)


def _attempt_context(attempt, spec, *, error="", now=None):
    now = now or timezone.now()
    remaining = max(0, int((attempt.deadline_at - now).total_seconds()))
    word_min, word_max = _attempt_limits(attempt, spec)
    context = _session_context(
        spec,
        selected_subject=attempt.snapshot.get("prompt", ""),
        minutes=attempt.snapshot.get("simulation_minutes", spec.minutes),
    )
    context.update(
        {
            "attempt": attempt,
            "task": attempt.task,
            "prompt": attempt.snapshot.get("prompt", ""),
            "category_label": attempt.snapshot.get("category_label", ""),
            "remaining_seconds": remaining,
            "remaining_minutes": remaining // 60,
            "remaining_second_remainder": remaining % 60,
            "word_count": _ee_word_count(attempt.body),
            "word_min": word_min,
            "word_max": word_max,
            "max_body_length": MAX_BODY_LENGTH,
            "error": error,
            "saved": False,
            "timer_url": reverse(spec.route_names["timer"], args=[attempt.pk]),
        }
    )
    return context


@never_cache
@require_POST
@transaction.atomic
def update_timer(request, spec, attempt_id):
    try:
        minutes = int(_single_post_value(request, "timer_minutes"))
        seconds = int(_single_post_value(request, "timer_seconds"))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Durée invalide.")
    if not 0 <= minutes <= 1440 or not 0 <= seconds <= 59:
        return HttpResponseBadRequest("Durée invalide.")

    attempt = get_object_or_404(
        WritingSimulationAttempt.objects.select_for_update(of=("self",)),
        user=request.user,
        pk=attempt_id,
    )
    now = timezone.now()
    if attempt.status != WritingSimulationAttemptStatus.ACTIVE:
        return redirect(spec.route_names["attempt"], attempt_id=attempt.pk)
    attempt.deadline_at = now + timedelta(minutes=minutes, seconds=seconds)
    attempt.save(update_fields=["deadline_at"])
    return redirect(spec.route_names["attempt"], attempt_id=attempt.pk)


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


def _result_context(attempt, spec):
    word_min, word_max = _attempt_limits(attempt, spec)
    context = _session_context(
        spec,
        title="Bilan de votre session",
        selected_subject=attempt.snapshot.get("prompt", ""),
        minutes=attempt.snapshot.get("simulation_minutes", spec.minutes),
        prompt=(
            "Une lecture concise de votre production, de sa conformité à la consigne "
            "et de ses priorités de progression."
        ),
        done=True,
    )
    context.update({
        "attempt": attempt,
        "task": attempt.task,
        "word_min": word_min,
        "word_max": word_max,
        "subject_url": (
            reverse("study:writing_sujet_detail", args=["ee", attempt.task.slug, attempt.sujet_id])
            if attempt.sujet_id else ""
        ),
        "debrief_back_url": reverse("study:simulation_track", args=["ee"]),
        "debrief_back_label": "Retour à EE",
    })
    return context


def _attempt_limits(attempt, spec):
    snapshot = attempt.snapshot or {}
    minimum = snapshot.get("word_min", spec.word_min)
    maximum = snapshot.get("word_max", spec.word_max)
    if (
        type(minimum) is not int
        or type(maximum) is not int
        or minimum < 1
        or maximum < minimum
    ):
        return spec.word_min, spec.word_max
    return minimum, maximum


@never_cache
@require_http_methods(["GET", "POST"])
def attempt(request, spec, attempt_id):
    if request.method == "GET":
        with transaction.atomic():
            attempt = get_object_or_404(
                WritingSimulationAttempt.objects.select_for_update(of=("self",)).select_related(
                    "task__part", "sujet"
                ),
                user=request.user,
                pk=attempt_id,
            )
            _expire_if_needed(attempt)
            is_active = attempt.status == WritingSimulationAttemptStatus.ACTIVE
        if not is_active:
            return render(
                request,
                "study/simulation/writing_simulation_result.html",
                _result_context(attempt, spec),
            )
        return render(
            request,
            "study/simulation/writing_simulation_attempt.html",
            _attempt_context(attempt, spec),
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
                "task__part", "sujet"
            ),
            user=request.user,
            pk=attempt_id,
        )
        if attempt.status != WritingSimulationAttemptStatus.ACTIVE:
            return redirect(spec.route_names["attempt"], attempt_id=attempt.pk)
        if len(body) > MAX_BODY_LENGTH:
            attempt.body = body
            return render(
                request,
                "study/simulation/writing_simulation_attempt.html",
                _attempt_context(
                    attempt,
                    spec,
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
                update_fields=["body", "last_saved_at", "status", "submitted_at", "word_count"]
            )
            return redirect(spec.route_names["attempt"], attempt_id=attempt.pk)

        if action == "save":
            attempt.save(update_fields=["body", "last_saved_at"])
            return redirect(
                reverse(spec.route_names["attempt"], args=[attempt.pk]) + "?saved=1"
            )

        if action == "abandon":
            attempt.status = WritingSimulationAttemptStatus.ABANDONED
            attempt.submitted_at = now
            attempt.word_count = _ee_word_count(body)
            attempt.save(
                update_fields=["body", "last_saved_at", "status", "submitted_at", "word_count"]
            )
            return redirect(spec.route_names["attempt"], attempt_id=attempt.pk)

        cleaned = body.strip()
        word_min, word_max = _attempt_limits(attempt, spec)
        word_count = _ee_word_count(cleaned)
        if not cleaned:
            error = f"Rédigez {spec.response_label.lower()} avant de le remettre."
        elif word_count < word_min or word_count > word_max:
            error = (
                f"{spec.response_label} doit compter entre "
                f"{word_min} et {word_max} mots."
            )
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
            return redirect(spec.route_names["attempt"], attempt_id=attempt.pk)

        attempt.body = body
        return render(
            request,
            "study/simulation/writing_simulation_attempt.html",
            _attempt_context(attempt, spec, error=error, now=now),
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
        "report": (
            attempt.evaluation
            if attempt.evaluation_status == WritingSimulationEvaluationStatus.READY
            else None
        ),
        "error": (
            "Le bilan précédent n’a pas abouti. Vous pouvez relancer l’évaluation."
            if stale
            else attempt.evaluation_error
            if attempt.evaluation_status == WritingSimulationEvaluationStatus.UNAVAILABLE
            else ""
        ),
        "retryable": stale
        or attempt.evaluation_status == WritingSimulationEvaluationStatus.UNAVAILABLE,
    }


def run_evaluation(attempt_id, started_at, spec):
    close_old_connections()
    try:
        attempt = (
            WritingSimulationAttempt.objects.filter(
                pk=attempt_id,
                evaluation_status=WritingSimulationEvaluationStatus.PROCESSING,
                evaluation_started_at=started_at,
            )
            .only("snapshot", "body", "word_count")
            .first()
        )
        if attempt is None:
            return
        try:
            report = spec.evaluator.score(
                subject=attempt.snapshot.get("prompt", ""),
                response=attempt.body,
                word_count=attempt.word_count or _ee_word_count(attempt.body),
            )
        except spec.evaluator.oral_evaluation.EvaluationError as exc:
            status = WritingSimulationEvaluationStatus.UNAVAILABLE
            error = str(exc)
            report = {}
        except Exception:
            logger.exception("%s evaluation worker failed", spec.task_label)
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
def evaluate(request, spec, attempt_id, *, thread_module=threading):
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
            if request.headers.get("Accept") == "text/html":
                return render(
                    request,
                    "study/simulation/writing_simulation_result.html",
                    _result_context(attempt, spec),
                )
            return evaluation_json(attempt)
        if attempt.evaluation_status == WritingSimulationEvaluationStatus.READY:
            return evaluation_json(attempt)
        now = timezone.now()
        if (
            attempt.evaluation_status == WritingSimulationEvaluationStatus.PROCESSING
            and attempt.evaluation_started_at
            and now - attempt.evaluation_started_at < EVALUATION_STALE_AFTER
        ):
            return evaluation_json(attempt, status=202)
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
            lambda attempt_id=attempt.pk, started_at=now: thread_module.Thread(
                target=run_evaluation,
                args=(attempt_id, started_at, spec),
                daemon=True,
            ).start()
        )
        return evaluation_json(attempt, status=202)


def evaluation_json(attempt, *, status=200):
    from django.http import JsonResponse

    return JsonResponse(_evaluation_payload(attempt), status=status)
