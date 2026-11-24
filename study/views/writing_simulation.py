"""Shared timed simulation views for EE Tâche 1 and Tâche 2."""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import Count, Max, Q
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_http_methods, require_POST, require_safe
from django.views.decorators.vary import vary_on_headers

from study.catalogue import loader as content_module
from study.catalogue import registry as catalogue
from study.catalogue.loader import _ee_word_count
from study.models import (
    Prompt,
    Task,
    WritingSimulationAttempt,
    WritingSimulationAttemptStatus,
    WritingSimulationEvaluationStatus,
    WritingSujet,
)
from study.review.progress import writing_sujet_progress_by_id
from study.simulation import writing_evaluation
from study.simulation.evaluation import PROVIDER_LABELS, EvaluationError, available_providers
from .simulation import render_subject_picker, studio_navigation, subject_picker_context

logger = logging.getLogger(__name__)

MAX_BODY_LENGTH = 20_000
EVALUATION_STALE_AFTER = timedelta(minutes=5)
_FINISHED_FIELDS = ("status", "submitted_at", "word_count")


@dataclass(frozen=True)
class WritingSimulationSpec:
    number: int
    word_min: int
    word_max: int
    minutes_setting: str
    response_label: str
    response_placeholder: str

    @property
    def task_slug(self):
        return f"tache-{self.number}"

    @property
    def task_label(self):
        return f"EE Tâche {self.number}"

    @property
    def word_range(self):
        return f"{self.word_min}–{self.word_max} mots"

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
            "delete": f"study:{prefix}_delete",
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


SPECS = {
    1: WritingSimulationSpec(
        number=1,
        word_min=60,
        word_max=120,
        minutes_setting="EE1_SIMULATION_MINUTES",
        response_label="Votre message",
        response_placeholder="Rédigez votre message ici…",
    ),
    2: WritingSimulationSpec(
        number=2,
        word_min=120,
        word_max=150,
        minutes_setting="EE2_SIMULATION_MINUTES",
        response_label="Votre production",
        response_placeholder="Rédigez votre production ici…",
    ),
    3: WritingSimulationSpec(
        number=3,
        word_min=content_module.EE_TACHE_THREE_WORD_LIMIT[0],
        word_max=content_module.EE_TACHE_THREE_WORD_LIMIT[1],
        minutes_setting="EE3_SIMULATION_MINUTES",
        response_label="Votre production",
        response_placeholder="Reformulez les deux points de vue sans donner votre avis…",
    ),
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


def _subjects(task, spec):
    if spec.number != 3:
        return WritingSujet.objects.filter(task=task, is_active=True)
    return Prompt.objects.filter(
        theme__task=task, theme__is_active=True, is_active=True, response__is_active=True,
        content_key__in=[
            key for key, (_, source) in catalogue.ee_tache_three_sources_by_key().items()
            if source.has_usable_documents
        ],
    )


def _subject_id(value):
    return int(value) if 0 < len(value) <= 18 and value.isascii() and value.isdecimal() else None


def _writing_navigation(request, spec, task, subject_id, *, theme="", label="", frozen_title=""):
    picker = spec.route_names["picker"]
    if not subject_id:
        return studio_navigation(request, picker)
    subjects = _subjects(task, spec)
    if not theme:
        fields = ("theme__slug", "theme__display_name") if spec.number == 3 else ("category", "category_label")
        category = subjects.filter(pk=subject_id).values_list(*fields).first()
        if not category:
            return studio_navigation(request, picker)
        theme, label = category
    if spec.number == 3:
        siblings = subjects.filter(theme__slug=theme).order_by("number", "pk").values_list("pk", "text")
    else:
        siblings = subjects.filter(category=theme).order_by("order", "pk").values_list("pk", "prompt")
    setup_url = reverse(spec.route_names["setup"])
    return studio_navigation(
        request, picker, theme=theme, label=label, selected=subject_id,
        subjects=(
            (pk, frozen_title if pk == subject_id and frozen_title else text, f"{setup_url}?sujet_id={pk}")
            for pk, text in siblings
        ),
    )


def _session_steps(spec, minutes):
    word_limits = spec.word_range
    if spec.number == 3:
        synthesis, opinion = content_module.EE_TACHE_THREE_SECTION_LIMITS
        word_limits = f"{synthesis[0]}–{synthesis[1]} mots · {opinion[0]}–{opinion[1]} mots"
    return [
        {
            "key": "reading",
            "name": "Consigne",
            "meta": "",
        },
        {
            "key": "live",
            "name": "Rédaction",
            "meta": f"{minutes} min",
            "about": word_limits,
        },
        {
            "key": "done",
            "name": "Bilan",
            "meta": "",
        },
    ]


def _session_context(
    spec,
    *,
    selected_subject="",
    prompt="",
    minutes=None,
):
    minutes = spec.minutes if minutes is None else minutes
    route_names = spec.route_names
    return {
        "simulation": spec.context,
        **spec.context,
        "route_names": route_names,
        "session_brand_icon": "pen-line",
        "session_brand": f"Studio écrit · {spec.task_label}",
        "session_kicker": "Expression écrite",
        "session_prompt": prompt,
        "session_selected_subject": selected_subject,
        "session_steps": _session_steps(spec, minutes),
        "session_show_clock": False,
    }


@require_GET
@vary_on_headers("X-Requested-With")
def subject_picker(request, spec):
    task = task_for(spec)
    subjects = _subjects(task, spec)
    comparison = spec.number == 3
    subject_field = "prompt_id" if comparison else "sujet_id"
    attempts = {
        row[subject_field]: row
        for row in WritingSimulationAttempt.objects.filter(
            user=request.user, task=task, **{f"{subject_field}__isnull": False},
        )
        .values(subject_field)
        .annotate(count=Count("pk"), latest=Max("started_at"))
    }
    rows = []
    if comparison:
        subjects = subjects.select_related("theme").only(
            "text", "content_key", "theme__slug", "theme__display_name",
        ).order_by("theme__name", "number", "pk")
    else:
        subjects = subjects.only("category", "category_label", "prompt", "slug").order_by("category_label", "order", "pk")
    setup_url = reverse(spec.route_names["setup"])
    sources = catalogue.ee_tache_three_sources_by_key() if comparison else {}
    for sujet in subjects:
        summary = attempts.get(sujet.pk, {})
        caption = sujet.theme.display_name if comparison else sujet.category_label
        if comparison:
            month, source = sources[sujet.content_key]
            publication = f"{caption} · {month.name} · {source.combinaison}"
        else:
            publication = caption
        rows.append({
            "sujet": sujet,
            "row_id": f"sujet-{sujet.pk}",
            "title": sujet.text if comparison else sujet.prompt,
            "theme": sujet.theme.slug if comparison else sujet.category,
            "theme_label": caption, "caption": publication,
            "url": f"{setup_url}?sujet_id={sujet.pk}",
            "count": summary.get("count", 0), "latest": summary.get("latest"),
        })
    context = subject_picker_context(request, rows)
    page_rows = context["page"].object_list
    if not comparison:
        canonical_slugs = content_module.ee_writing_canonical_slug_by_slug(spec.number)
        ids_by_slug = {row["sujet"].slug: row["sujet"].pk for row in rows}
        for row in page_rows:
            sujet = row["sujet"]
            row["progress_sujet_id"] = ids_by_slug.get(canonical_slugs.get(sujet.slug), sujet.pk)
        progress = writing_sujet_progress_by_id(request.user, {row["progress_sujet_id"] for row in page_rows}, task_id=task.pk)
        for row in page_rows:
            row["progress"] = progress[row["progress_sujet_id"]]
    context["task"] = task
    context["picker"] = {
        "back_url": reverse("study:simulation_track", args=["ee"]),
        "back_label": "Expression écrite",
        "kicker": f"Simulation · {spec.task_label}",
        "title": "Choisir un sujet",
        "heading_id": f"ee{spec.number}-title",
        "format": spec.word_range,
        "tone": "sim-tone--ee",
        "icon": "pen-line",
        "results_id": f"ee{spec.number}-topic-results",
        "writing_progress": not comparison,
        "show_practice_summary": True,
    }
    return render_subject_picker(request, context)


def _setup_context(request, spec, task):
    selected_sujet_id = request.GET.get("sujet_id", "")
    selected_sujet = None
    category = {}
    if selected_sujet_id:
        subjects = _subjects(task, spec)
        if spec.number == 3:
            subjects = subjects.select_related("theme").only("text", "theme__slug", "theme__display_name")
        else:
            subjects = subjects.only("prompt", "category", "category_label")
        selected_sujet = subjects.filter(pk=_subject_id(selected_sujet_id)).first()
        if spec.number == 3 and selected_sujet is None:
            raise Http404
        if selected_sujet:
            category = (
                {"theme": selected_sujet.theme.slug, "label": selected_sujet.theme.display_name}
                if spec.number == 3 else {"theme": selected_sujet.category, "label": selected_sujet.category_label}
            )
    attempts = (
        WritingSimulationAttempt.objects.filter(user=request.user, task=task)
        .only("status", "started_at", "deadline_at", "evaluation_status")
        .annotate(has_saved_report=Q(evaluation__reports__has_any_keys=list(PROVIDER_LABELS)))
        .order_by("-started_at", "-id")[:8]
    )
    saved_sessions = []
    now = timezone.now()
    for item in attempts:
        if item.status == WritingSimulationAttemptStatus.ABANDONED or (
            item.status == WritingSimulationAttemptStatus.ACTIVE and item.deadline_at > now
        ):
            summary = item.get_status_display()
        else:
            has_report = item.evaluation_status == WritingSimulationEvaluationStatus.READY or item.has_saved_report
            summary = "Bilan disponible" if has_report else "Sans bilan"
        saved_sessions.append({
            "id": item.pk,
            "created_at": item.started_at,
            "url": reverse(spec.route_names["attempt"], args=[item.pk]),
            "summary": summary,
        })
    return {
        **_session_context(
            spec,
            selected_subject=(selected_sujet.text if spec.number == 3 else selected_sujet.prompt) if selected_sujet else "",
        ),
        **_writing_navigation(request, spec, task, selected_sujet.pk if selected_sujet else None, **category),
        "task": task,
        "saved_sessions": saved_sessions,
        "selected_sujet_id": selected_sujet_id,
        "start_url": reverse(spec.route_names["start"]),
        "delete_url": reverse(
            spec.route_names["delete"], query={"sujet_id": selected_sujet.pk} if selected_sujet else None,
        ),
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

    subjects = _subjects(task, spec)
    if subject_value:
        pk = _subject_id(subject_value)
        if pk is None:
            return HttpResponseBadRequest("Sujet invalide.")
        sujet = get_object_or_404(subjects, pk=pk)
    else:
        sujet = subjects.order_by("?").first()
        if sujet is None:
            return HttpResponseBadRequest(f"Aucun sujet {spec.task_label} n'est disponible.")

    if spec.number == 3:
        _, source = catalogue.ee_tache_three_sources_by_key()[sujet.content_key]
        identity = {"prompt": sujet}
        snapshot = {
            "prompt": sujet.text, "prompt_key": sujet.content_key,
            "category": sujet.theme.slug,
            "category_label": sujet.theme.display_name,
            "documents": [source.document1, source.document2],
        }
    else:
        identity = {"sujet": sujet}
        snapshot = {
            "prompt": sujet.prompt, "category": sujet.category,
            "category_label": sujet.category_label, "sujet_slug": sujet.slug,
        }
    now = timezone.now()
    attempt = WritingSimulationAttempt.objects.create(
        user=request.user,
        task=task,
        **identity,
        snapshot={
            **snapshot,
            "word_min": spec.word_min,
            "word_max": spec.word_max,
            "simulation_minutes": spec.minutes,
        },
        started_at=now,
        deadline_at=now + timedelta(minutes=spec.minutes),
    )
    return redirect(spec.route_names["attempt"], attempt_id=attempt.pk)


def _response_parts(attempt, spec):
    word_min, word_max = _attempt_limits(attempt, spec)
    if spec.number == 3:
        labels = ("Synthèse neutre", "Point de vue argumenté")
        placeholders = (spec.response_placeholder, "Présentez et justifiez votre point de vue…")
        fields = ("body", "position_body")
        limits = content_module.EE_TACHE_THREE_SECTION_LIMITS
    else:
        labels, placeholders, fields = (spec.response_label,), (spec.response_placeholder,), ("body",)
        limits = ((word_min, word_max),)
    return [
        {
            "field": field, "id": "writing-body" if field == "body" else "writing-position",
            "label": label, "placeholder": placeholder, "text": getattr(attempt, field),
            "min": minimum, "max": maximum, "count": _ee_word_count(getattr(attempt, field)),
        }
        for field, label, placeholder, (minimum, maximum) in zip(fields, labels, placeholders, limits)
    ]


def _draft_fields(request, spec):
    body = _single_post_value(request, "body")
    fields = {"body": body}
    if spec.number == 3:
        fields["position_body"] = _single_post_value(request, "position_body")
    return fields


def _has_response(attempt):
    return bool(attempt.body.strip() or attempt.position_body.strip())


def _word_count(attempt):
    return _ee_word_count(attempt.body) + _ee_word_count(attempt.position_body)


def _attempt_navigation(request, attempt, spec):
    return _writing_navigation(
        request, spec, attempt.task, attempt.prompt_id if spec.number == 3 else attempt.sujet_id,
        theme=attempt.snapshot.get("category", ""), label=attempt.snapshot.get("category_label", ""),
        frozen_title=attempt.snapshot.get("prompt", ""),
    )


def _attempt_context(request, attempt, spec, *, error="", now=None):
    now = now or timezone.now()
    remaining = max(0, math.ceil((attempt.deadline_at - now).total_seconds()))
    word_min, word_max = _attempt_limits(attempt, spec)
    prompt = attempt.snapshot.get("prompt", "")
    context = _session_context(
        spec,
        selected_subject=attempt.snapshot.get("prompt", ""),
        minutes=attempt.snapshot.get("simulation_minutes", spec.minutes),
    )
    context.update(
        {
            **_attempt_navigation(request, attempt, spec),
            "attempt": attempt,
            "task": attempt.task,
            "prompt": content_module.ee_tache_three_instruction(prompt) if spec.number == 3 else prompt,
            "category_label": attempt.snapshot.get("category_label", ""),
            "remaining_seconds": remaining,
            "remaining_minutes": remaining // 60,
            "remaining_second_remainder": remaining % 60,
            "word_count": _word_count(attempt),
            "response_parts": _response_parts(attempt, spec),
            "documents": attempt.snapshot.get("documents", ()),
            "word_min": word_min,
            "word_max": word_max,
            "max_body_length": MAX_BODY_LENGTH,
            "error": error,
            "saved": False,
            "timer_url": reverse(spec.route_names["timer"], args=[attempt.pk]),
            "auto_evaluation": bool(settings.GROQ_API_KEY),
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
    try:
        draft = _draft_fields(request, spec) if "body" in request.POST or "position_body" in request.POST else {}
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if sum(map(len, draft.values())) > MAX_BODY_LENGTH:
        return HttpResponseBadRequest("Votre réponse est trop longue pour être enregistrée.")

    attempt = get_object_or_404(
        _owned_attempts(request, spec).select_for_update(of=("self",)),
        pk=attempt_id,
    )
    now = timezone.now()
    if attempt.status != WritingSimulationAttemptStatus.ACTIVE:
        return redirect(spec.route_names["attempt"], attempt_id=attempt.pk)
    fields = list(draft)
    for field, value in draft.items():
        setattr(attempt, field, value)
    if draft:
        attempt.last_saved_at = now
        fields.append("last_saved_at")
    if attempt.deadline_at > now:
        attempt.deadline_at = now + timedelta(minutes=minutes, seconds=seconds)
        fields.append("deadline_at")
    if _mark_expired(attempt, now):
        fields.extend(_FINISHED_FIELDS)
    attempt.save(update_fields=fields)
    return redirect(spec.route_names["attempt"], attempt_id=attempt.pk)


def _mark_expired(attempt, now):
    if (
        attempt.status == WritingSimulationAttemptStatus.ACTIVE
        and attempt.deadline_at <= now
    ):
        attempt.status = WritingSimulationAttemptStatus.EXPIRED
        attempt.submitted_at = now
        attempt.word_count = _word_count(attempt)
        return True
    return False


def _result_context(request, attempt, spec):
    word_min, word_max = _attempt_limits(attempt, spec)
    if spec.number == 1:
        providers, provider = _ee1_evaluation_options(attempt)
    else:
        providers, provider = (), writing_evaluation.provider_for(spec.number)
    subject_url = ""
    if attempt.sujet_id:
        subject_url = reverse("study:writing_sujet_detail", args=["ee", attempt.task.slug, attempt.sujet_id])
    elif attempt.prompt_id:
        subject_url = reverse("study:response_detail", args=["ee", attempt.task.slug, attempt.prompt_id])
    prompt = attempt.snapshot.get("prompt", "")
    context = _session_context(
        spec,
        prompt=content_module.ee_tache_three_instruction(prompt) if spec.number == 3 and prompt else prompt,
        minutes=attempt.snapshot.get("simulation_minutes", spec.minutes),
    )
    notices = {
        WritingSimulationAttemptStatus.EXPIRED: "Le temps est écoulé ; votre brouillon a été conservé.",
        WritingSimulationAttemptStatus.ABANDONED: "Cette session a été abandonnée et reste privée dans votre historique.",
    }
    context.update({
        **_attempt_navigation(request, attempt, spec),
        "attempt": attempt,
        "task": attempt.task,
        "session_is_debrief": True,
        "session_saved": attempt.status == WritingSimulationAttemptStatus.SUBMITTED,
        "session_notice": notices.get(attempt.status, ""),
        "word_min": word_min,
        "word_max": word_max,
        "session_title_assessment": _has_response(attempt) and attempt.status != WritingSimulationAttemptStatus.ABANDONED,
        "evaluation_provider": provider,
        "evaluation_provider_label": PROVIDER_LABELS[provider],
        "evaluation_providers": [(key, PROVIDER_LABELS[key]) for key in providers],
        "assessment_form_id": "writing-evaluation-form",
        "subject_url": subject_url,
        "response_parts": _response_parts(attempt, spec),
        "documents": attempt.snapshot.get("documents", ()),
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


def _owned_attempts(request, spec):
    return WritingSimulationAttempt.objects.filter(
        user=request.user, task__part__slug="ee", task__slug=spec.task_slug,
    )


@never_cache
@require_POST
@csrf_protect
def delete(request, spec):
    try:
        attempt_id = UUID(_single_post_value(request, "simulation"))
    except ValueError:
        raise Http404 from None
    deleted, _ = _owned_attempts(request, spec).filter(pk=attempt_id).delete()
    if not deleted:
        raise Http404
    sujet_id = request.GET.get("sujet_id", "")
    return redirect(reverse(
        spec.route_names["setup"], query={"sujet_id": sujet_id} if sujet_id.isdecimal() else None,
    ))


@never_cache
@require_http_methods(["GET", "POST"])
def attempt(request, spec, attempt_id):
    if request.method == "GET":
        attempt = get_object_or_404(_owned_attempts(request, spec).select_related("task__part"), pk=attempt_id)
        # A read must not freeze the old draft before the editor's last POST arrives.
        now = timezone.now()
        _mark_expired(attempt, now)
        if attempt.status != WritingSimulationAttemptStatus.ACTIVE:
            return render(
                request,
                "study/simulation/writing_simulation_result.html",
                _result_context(request, attempt, spec),
            )
        return render(
            request,
            "study/simulation/writing_simulation_attempt.html",
            _attempt_context(request, attempt, spec, now=now),
        )

    try:
        action = _single_post_value(request, "action")
        draft = _draft_fields(request, spec)
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if action not in {"save", "submit", "abandon", "expire"}:
        return HttpResponseBadRequest("Action invalide.")
    with transaction.atomic():
        attempt = get_object_or_404(
            _owned_attempts(request, spec).select_for_update(of=("self",)).select_related("task__part"),
            pk=attempt_id,
        )
        if attempt.status != WritingSimulationAttemptStatus.ACTIVE:
            return redirect(spec.route_names["attempt"], attempt_id=attempt.pk)
        for field, value in draft.items():
            setattr(attempt, field, value)
        if sum(map(len, draft.values())) > MAX_BODY_LENGTH:
            return render(
                request,
                "study/simulation/writing_simulation_attempt.html",
                _attempt_context(
                    request,
                    attempt,
                    spec,
                    error="Votre réponse est trop longue pour être enregistrée.",
                ),
                status=400,
            )

        now = timezone.now()
        attempt.last_saved_at = now
        fields = [*draft, "last_saved_at"]
        if _mark_expired(attempt, now):
            attempt.save(update_fields=[*fields, *_FINISHED_FIELDS])
            return redirect(spec.route_names["attempt"], attempt_id=attempt.pk)

        if action in {"save", "expire"}:
            attempt.save(update_fields=fields)
            return redirect(
                reverse(spec.route_names["attempt"], args=[attempt.pk]) + "?saved=1"
            )

        if action == "abandon":
            attempt.status = WritingSimulationAttemptStatus.ABANDONED
            attempt.submitted_at = now
            attempt.word_count = _word_count(attempt)
            attempt.save(update_fields=[*fields, *_FINISHED_FIELDS])
            return redirect(spec.route_names["attempt"], attempt_id=attempt.pk)

        error = ""
        if spec.number != 3 and not attempt.body.strip():
            error = f"Rédigez {spec.response_label.lower()} avant de le remettre."
        else:
            for part in _response_parts(attempt, spec):
                if not part["min"] <= part["count"] <= part["max"]:
                    error = f"{part['label']} doit compter entre {part['min']} et {part['max']} mots."
                    break
        if not error:
            for field, value in draft.items():
                setattr(attempt, field, value.strip())
            attempt.status = WritingSimulationAttemptStatus.SUBMITTED
            attempt.submitted_at = now
            attempt.word_count = _word_count(attempt)
            fields.extend(_FINISHED_FIELDS)
            if settings.GROQ_API_KEY and request.POST.getlist("evaluation_consent") == ["groq"]:
                _queue_evaluation(attempt, spec, "groq" if spec.number == 1 else None, now, update_fields=fields)
            else:
                attempt.save(update_fields=fields)
            return redirect(spec.route_names["attempt"], attempt_id=attempt.pk)

        return render(
            request,
            "study/simulation/writing_simulation_attempt.html",
            _attempt_context(request, attempt, spec, error=error, now=now),
            status=400,
        )


def _ee1_reports(attempt):
    if "reports" in attempt.evaluation:
        return attempt.evaluation["reports"]
    # All writing reports saved before the model picker used Groq.
    return {"groq": attempt.evaluation} if attempt.evaluation_status == WritingSimulationEvaluationStatus.READY else {}


def _ee1_evaluation_options(attempt):
    default = writing_evaluation.provider_for(1)
    reports = _ee1_reports(attempt)
    available = available_providers() | reports.keys()
    providers = tuple(key for key in PROVIDER_LABELS if key in available) or (default,)
    last_provider = attempt.evaluation.get("provider")
    if last_provider not in providers:
        last_provider = default if default in reports else next(iter(reports), None)
    if last_provider is None:
        last_provider = default if default in providers else providers[0]
    return providers, last_provider


def _evaluation_payload(attempt, provider=None):
    status = attempt.evaluation_status
    report = attempt.evaluation if status == WritingSimulationEvaluationStatus.READY else None
    if provider:
        report = _ee1_reports(attempt).get(provider)
        if report is not None:
            status = WritingSimulationEvaluationStatus.READY
        elif status == WritingSimulationEvaluationStatus.READY or (
            status == WritingSimulationEvaluationStatus.UNAVAILABLE
            and attempt.evaluation.get("provider") not in (None, provider)
        ):
            status = WritingSimulationEvaluationStatus.NOT_REQUESTED
    stale = (
        status == WritingSimulationEvaluationStatus.PROCESSING
        and attempt.evaluation_started_at
        and timezone.now() - attempt.evaluation_started_at >= EVALUATION_STALE_AFTER
    )
    return {
        "status": (
            WritingSimulationEvaluationStatus.UNAVAILABLE
            if stale
            else status
        ),
        "report": report,
        "error": (
            "Le bilan précédent n’a pas abouti. Vous pouvez relancer l’évaluation."
            if stale
            else attempt.evaluation_error
            if status == WritingSimulationEvaluationStatus.UNAVAILABLE
            else ""
        ),
        "retryable": stale
        or status == WritingSimulationEvaluationStatus.UNAVAILABLE,
    }


def run_evaluation(attempt_id, started_at, spec, provider=None):
    claim = {
        "pk": attempt_id,
        "evaluation_status": WritingSimulationEvaluationStatus.PROCESSING,
        "evaluation_started_at": started_at,
    }
    if provider:
        claim["evaluation__provider"] = provider
    close_old_connections()
    try:
        attempt = (
            WritingSimulationAttempt.objects.filter(**claim)
            .only("snapshot", "body", "position_body", "word_count")
            .first()
        )
        if attempt is None:
            return
        word_min, word_max = _attempt_limits(attempt, spec)
        provider_name = provider or writing_evaluation.provider_for(spec.number)
        if provider_name not in PROVIDER_LABELS:
            provider_name = "unknown"
        log_context = f"task=ee{spec.number} provider={provider_name} attempt={attempt.pk}"
        logger.info("writing evaluation started %s", log_context)
        started = time.monotonic()
        try:
            report = writing_evaluation.score(
                task_number=spec.number,
                subject=attempt.snapshot.get("prompt", ""),
                response=attempt.body,
                word_count=attempt.word_count or _word_count(attempt),
                word_min=word_min,
                word_max=word_max,
                **({"provider": provider} if provider else {}),
                **(
                    {"position": attempt.position_body, "documents": attempt.snapshot.get("documents", ())}
                    if spec.number == 3 else {}
                ),
            )
        except EvaluationError as exc:
            status = WritingSimulationEvaluationStatus.UNAVAILABLE
            error = str(exc)
            report = {}
            if isinstance(exc, writing_evaluation.UnverifiedReport):
                logger.warning(
                    "writing evaluation rejected %s field=%s reason=%s passages=%d elapsed_ms=%d",
                    log_context, exc.field, exc.reason,
                    exc.passage_count, (time.monotonic() - started) * 1000,
                )
            else:
                logger.warning(
                    "writing evaluation failed %s error_status=%d elapsed_ms=%d",
                    log_context, exc.status, (time.monotonic() - started) * 1000,
                )
        except Exception as exc:
            logger.error(
                "writing evaluation worker failed %s error_type=%s elapsed_ms=%d",
                log_context, type(exc).__name__, (time.monotonic() - started) * 1000,
            )
            status = WritingSimulationEvaluationStatus.UNAVAILABLE
            error = "Le bilan est temporairement indisponible. Votre réponse reste disponible."
            report = {}
        else:
            status = WritingSimulationEvaluationStatus.READY
            error = ""
        with transaction.atomic():
            current = WritingSimulationAttempt.objects.select_for_update().filter(**claim).first()
            if current is None:
                return
            current.evaluation_status = status
            if provider:
                if status == WritingSimulationEvaluationStatus.READY:
                    current.evaluation["reports"][provider] = report
            else:
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
        if status == WritingSimulationEvaluationStatus.READY:
            logger.info(
                "writing evaluation ready %s elapsed_ms=%d",
                log_context, (time.monotonic() - started) * 1000,
            )
    finally:
        close_old_connections()


@never_cache
@require_http_methods(["GET", "POST"])
@csrf_protect
def evaluate(request, spec, attempt_id):
    if request.method == "POST":
        if request.content_type != "application/json":
            return HttpResponseBadRequest("Un consentement explicite est requis.")
        try:
            data = json.loads(request.body or b"{}")
        except (TypeError, ValueError):
            return HttpResponseBadRequest("Un consentement explicite est requis.")
        if not isinstance(data, dict) or data.get("consent") is not True or data.keys() - {"consent", "provider"}:
            return HttpResponseBadRequest("Un consentement explicite est requis.")
    with transaction.atomic():
        attempt = get_object_or_404(
            _owned_attempts(request, spec).select_for_update(of=("self",)),
            pk=attempt_id,
        )
        now = timezone.now()
        expired = _mark_expired(attempt, now)
        if attempt.status not in {
            WritingSimulationAttemptStatus.SUBMITTED,
            WritingSimulationAttemptStatus.EXPIRED,
        }:
            return HttpResponseBadRequest("Cette réponse ne peut pas encore être évaluée.")
        if not _has_response(attempt):
            return HttpResponseBadRequest("Aucune réponse à évaluer.")
        provider = None
        if spec.number == 1:
            providers, default = _ee1_evaluation_options(attempt)
            provider = request.GET.get("provider", default) if request.method == "GET" else data.get("provider")
            if provider not in providers:
                return JsonResponse({"error": "Choisissez un modèle disponible avant de lancer l’évaluation."}, status=409)
        elif request.method == "POST" and data.get("provider") not in (None, "groq"):
            return HttpResponseBadRequest("Le modèle d’évaluation n’est pas disponible.")
        if request.method == "GET":
            if request.headers.get("Accept") == "text/html":
                return render(
                    request,
                    "study/simulation/writing_simulation_result.html",
                    _result_context(request, attempt, spec),
                )
            return evaluation_json(attempt, provider=provider)
        cached = (
            provider in _ee1_reports(attempt) if provider
            else attempt.evaluation_status == WritingSimulationEvaluationStatus.READY
        )
        if cached:
            return evaluation_json(attempt, provider=provider)
        if (
            attempt.evaluation_status == WritingSimulationEvaluationStatus.PROCESSING
            and attempt.evaluation_started_at
            and now - attempt.evaluation_started_at < EVALUATION_STALE_AFTER
        ):
            return evaluation_json(attempt, status=202, provider=provider)
        if provider and provider not in available_providers():
            return JsonResponse(
                {"error": "Ce modèle n’est pas disponible pour une nouvelle évaluation."},
                status=409,
            )
        _queue_evaluation(attempt, spec, provider, now, update_fields=_FINISHED_FIELDS if expired else ())
        return evaluation_json(attempt, status=202, provider=provider)


def _queue_evaluation(attempt, spec, provider, now, *, update_fields=()):
    attempt.evaluation = {"provider": provider, "reports": _ee1_reports(attempt)} if provider else {}
    attempt.evaluation_status = WritingSimulationEvaluationStatus.PROCESSING
    attempt.evaluation_error = ""
    attempt.evaluation_started_at = now
    attempt.evaluated_at = None
    attempt.save(update_fields=[
        *update_fields, "evaluation_status", "evaluation", "evaluation_error",
        "evaluation_started_at", "evaluated_at",
    ])
    transaction.on_commit(
        lambda attempt_id=attempt.pk: threading.Thread(
            target=run_evaluation,
            args=(attempt_id, now, spec, provider),
            daemon=True,
        ).start()
    )


def evaluation_json(attempt, *, status=200, provider=None):
    return JsonResponse(_evaluation_payload(attempt, provider), status=status)
