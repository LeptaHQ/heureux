"""Shared timed simulation views for the three writing tasks."""

from __future__ import annotations

import hashlib
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
from study.navigation.routing import subject_selection_url
from study.review.progress import writing_sujet_progress_by_id
from study.simulation import writing_evaluation
from study.simulation.evaluation import PROVIDER_LABELS, EvaluationError, available_providers
from .simulation import (
    PickerSubject,
    picker_rows,
    render_subject_picker,
    saved_session_context,
    studio_navigation,
    subject_picker_context,
)

logger = logging.getLogger(__name__)

MAX_BODY_LENGTH = 20_000
EVALUATION_STALE_AFTER = timedelta(minutes=5)
_FINISHED_FIELDS = ("status", "submitted_at", "word_count")
_DRAFT_CONFLICT = (
    "Un autre onglet a enregistré un brouillon plus récent. Votre texte est affiché ci-dessous, "
    "mais n’a pas été enregistré. Rechargez le brouillon enregistré ou relisez votre texte avant de l’enregistrer à nouveau."
)
_EVALUATION_FIELDS = ("status", "evaluation_status", "evaluation", "evaluation_started_at", "evaluation_error")
_EVALUATION_SEND_LABELS = {**PROVIDER_LABELS, "groq": "Groq (Qwen 3.8 27B)"}


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


def _attempt_url(request, spec, attempt_id, *, saved=False):
    return subject_selection_url(
        reverse(spec.route_names["attempt"], args=[attempt_id], query={"saved": 1} if saved else None),
        request,
    )


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
        siblings = subjects.filter(theme__slug=theme).order_by("number", "pk").values_list("pk", "text", "response_id")
        canonical = {}
    else:
        siblings = subjects.filter(category=theme).order_by("order", "pk").values_list("pk", "prompt", "slug")
        canonical = content_module.ee_writing_canonical_slug_by_slug(spec.number)
    setup_url = reverse(spec.route_names["setup"])
    return studio_navigation(
        request, picker, theme=theme, label=label, selected=subject_id,
        subjects=(
            (pk, canonical.get(group, group), frozen_title if pk == subject_id and frozen_title else text,
             f"{setup_url}?sujet_id={pk}")
            for pk, text, group in siblings
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
    if comparison:
        sources = catalogue.ee_tache_three_sources_by_key()
        publications = subjects.order_by("theme__name", "number", "pk").values_list(
            "pk", "text", "theme__slug", "theme__display_name", "content_key", "response_id",
        )

        def comparison_subjects():
            for pk, title, theme, label, content_key, group in publications.iterator():
                month, source = sources[content_key]
                yield PickerSubject(pk, title, theme, label, f"{label} · {month.name} · {source.combinaison}", group)

        entries = comparison_subjects()
    else:
        canonical_slugs = content_module.ee_writing_canonical_slug_by_slug(spec.number)
        publications = subjects.order_by("category_label", "order", "pk").values_list(
            "pk", "prompt", "category", "category_label", "slug",
        )
        entries = (
            PickerSubject(pk, title, theme, label, label, canonical_slugs.get(slug, slug))
            for pk, title, theme, label, slug in publications.iterator()
        )
    setup_url = reverse(spec.route_names["setup"])
    context = subject_picker_context(request, entries, attempts)
    picker_rows(context, attempts, lambda entry: {
        "row_id": f"sujet-{entry.key}", "url": f"{setup_url}?sujet_id={entry.key}", "subject_id": entry.key,
    })
    page_rows = context["page"].object_list
    if not comparison and page_rows:
        visible = subjects.only("prompt", "slug").in_bulk([row["subject_id"] for row in page_rows])
        ids_by_slug = dict(subjects.filter(
            slug__in={canonical_slugs.get(sujet.slug) for sujet in visible.values()},
        ).values_list("slug", "pk"))
        for row in page_rows:
            sujet = visible.get(row["subject_id"])
            if sujet is None:
                continue
            row["sujet"] = sujet
            row["progress_sujet_id"] = ids_by_slug.get(canonical_slugs.get(sujet.slug), sujet.pk)
        progress = writing_sujet_progress_by_id(
            request.user, {row["progress_sujet_id"] for row in page_rows if "sujet" in row}, task_id=task.pk,
        )
        for row in page_rows:
            if "sujet" in row:
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
    attempts = WritingSimulationAttempt.objects.filter(user=request.user, task=task)
    if selected_sujet:
        field = "prompt_id" if spec.number == 3 else "sujet_id"
        attempts = attempts.filter(**{field: selected_sujet.pk})
    attempts = (
        attempts.only("status", "started_at", "evaluation_status")
        .annotate(has_saved_report=Q(evaluation__reports__has_any_keys=list(PROVIDER_LABELS)))
        .order_by("-started_at", "-id")
    )

    def saved_row(item):
        if item.status in {WritingSimulationAttemptStatus.ABANDONED, WritingSimulationAttemptStatus.ACTIVE}:
            summary = item.get_status_display()
        else:
            has_report = item.evaluation_status == WritingSimulationEvaluationStatus.READY or item.has_saved_report
            summary = "Bilan disponible" if has_report else "Sans bilan"
        return {
            "id": item.pk,
            "created_at": item.started_at,
            "url": _attempt_url(request, spec, item.pk),
            "summary": summary,
        }
    delete_query = {"sujet_id": selected_sujet.pk} if selected_sujet else {}
    if "seances" in request.GET:
        delete_query["seances"] = request.GET["seances"]
    return {
        **_session_context(
            spec,
            selected_subject=(selected_sujet.text if spec.number == 3 else selected_sujet.prompt) if selected_sujet else "",
        ),
        **_writing_navigation(request, spec, task, selected_sujet.pk if selected_sujet else None, **category),
        "task": task,
        **saved_session_context(request, attempts, saved_row),
        "selected_sujet_id": selected_sujet_id,
        "start_url": subject_selection_url(reverse(spec.route_names["start"]), request),
        "delete_url": subject_selection_url(reverse(spec.route_names["delete"], query=delete_query), request),
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
    return redirect(_attempt_url(request, spec, attempt.pk))


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


def _draft_revision(attempt):
    text = json.dumps([attempt.body, attempt.position_body], ensure_ascii=True)
    return hashlib.sha256(text.encode()).hexdigest()


def _apply_draft(attempt, draft, submitted_revision):
    revision = _draft_revision(attempt)
    conflict = submitted_revision != revision and any(getattr(attempt, field) != value for field, value in draft.items())
    for field, value in draft.items():
        setattr(attempt, field, value)
    return revision, conflict


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


def _attempt_context(request, attempt, spec, *, error="", now=None, revision=None, draft_conflict=False):
    now = now or timezone.now()
    remaining = math.ceil((attempt.deadline_at - now).total_seconds())
    minutes, seconds = divmod(max(0, remaining), 60)
    word_min, word_max = _attempt_limits(attempt, spec)
    prompt = attempt.snapshot.get("prompt", "")
    provider = _auto_evaluation_provider(spec)
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
            "remaining_minutes": minutes,
            "remaining_second_remainder": seconds,
            "word_count": _word_count(attempt),
            "response_parts": _response_parts(attempt, spec),
            "documents": attempt.snapshot.get("documents", ()),
            "word_min": word_min,
            "word_max": word_max,
            "max_body_length": MAX_BODY_LENGTH,
            "error": error,
            "draft_revision": _draft_revision(attempt) if revision is None else revision,
            "draft_conflict": draft_conflict,
            "timer_url": subject_selection_url(reverse(spec.route_names["timer"], args=[attempt.pk]), request),
            "auto_evaluation": provider,
            "auto_evaluation_label": _EVALUATION_SEND_LABELS.get(provider, ""),
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
        submitted_revision = _single_post_value(request, "draft_revision") if draft else ""
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if sum(map(len, draft.values())) > MAX_BODY_LENGTH:
        return HttpResponseBadRequest("Votre réponse est trop longue pour être enregistrée.")

    attempt = get_object_or_404(
        _owned_attempts(request, spec).select_for_update(of=("self",)).select_related("task__part"),
        pk=attempt_id,
    )
    now = timezone.now()
    if attempt.status != WritingSimulationAttemptStatus.ACTIVE:
        return redirect(_attempt_url(request, spec, attempt.pk))
    fields = list(draft)
    if draft:
        revision, conflict = _apply_draft(attempt, draft, submitted_revision)
        if conflict:
            return _render_draft_conflict(request, attempt, spec, revision)
        attempt.last_saved_at = now
        fields.append("last_saved_at")
    attempt.deadline_at = now + timedelta(minutes=minutes, seconds=seconds)
    fields.append("deadline_at")
    attempt.save(update_fields=fields)
    return redirect(_attempt_url(request, spec, attempt.pk))


def _render_draft_conflict(request, attempt, spec, revision):
    return render(request, "study/simulation/writing_simulation_attempt.html", _attempt_context(
        request, attempt, spec, error=_DRAFT_CONFLICT, revision=revision, draft_conflict=True,
    ), status=409)


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
        minutes=attempt.snapshot.get("simulation_minutes", spec.minutes),
    )
    submitted = attempt.status == WritingSimulationAttemptStatus.SUBMITTED
    configured = _writing_providers(spec)
    can_assess = submitted and _has_response(attempt)
    can_load_evaluation = bool(configured) or attempt.evaluation_status in (
        WritingSimulationEvaluationStatus.PROCESSING, WritingSimulationEvaluationStatus.READY,
    ) or (spec.number == 1 and bool(_ee1_reports(attempt)))
    context.update({
        **_attempt_navigation(request, attempt, spec),
        "attempt": attempt,
        "task": attempt.task,
        "session_is_debrief": True,
        "session_debrief_prompt": content_module.ee_tache_three_instruction(prompt) if spec.number == 3 and prompt else prompt,
        "session_saved": submitted,
        "session_notice": "Cette session a été abandonnée et reste privée dans votre historique."
        if attempt.status == WritingSimulationAttemptStatus.ABANDONED else "",
        "word_min": word_min,
        "word_max": word_max,
        "show_evaluation": can_assess,
        "can_load_evaluation": can_load_evaluation,
        "session_title_assessment": can_assess and (bool(configured) or len(providers) > 1),
        "evaluation_provider": provider,
        "evaluation_provider_label": _EVALUATION_SEND_LABELS[provider],
        "evaluation_providers": [(key, PROVIDER_LABELS[key]) for key in providers],
        "assessment_form_id": "writing-evaluation-form",
        "subject_url": subject_selection_url(subject_url, request) if subject_url else "",
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
    query = {
        key: request.GET[key] for key in ("sujet_id", "seances")
        if request.GET.get(key, "").isdecimal()
    }
    return redirect(subject_selection_url(reverse(spec.route_names["setup"], query=query), request))


@never_cache
@require_http_methods(["GET", "POST"])
def attempt(request, spec, attempt_id):
    if request.method == "GET":
        attempt = get_object_or_404(_owned_attempts(request, spec).select_related("task__part"), pk=attempt_id)
        if attempt.status != WritingSimulationAttemptStatus.ACTIVE:
            return render(
                request,
                "study/simulation/writing_simulation_result.html",
                _result_context(request, attempt, spec),
            )
        return render(
            request,
            "study/simulation/writing_simulation_attempt.html",
            _attempt_context(request, attempt, spec),
        )

    try:
        action = _single_post_value(request, "action")
        draft = _draft_fields(request, spec)
        submitted_revision = (
            "" if action == "expire" and "draft_revision" not in request.POST
            else _single_post_value(request, "draft_revision")
        )
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
            return redirect(_attempt_url(request, spec, attempt.pk))
        # Older timers sent no revision. Accept their drafts only if they cannot overwrite a saved one.
        if action == "expire" and not submitted_revision and not (attempt.body or attempt.position_body):
            submitted_revision = _draft_revision(attempt)
        revision, conflict = _apply_draft(attempt, draft, submitted_revision)
        if conflict:
            return _render_draft_conflict(request, attempt, spec, revision)
        if sum(map(len, draft.values())) > MAX_BODY_LENGTH:
            return render(
                request,
                "study/simulation/writing_simulation_attempt.html",
                _attempt_context(
                    request,
                    attempt,
                    spec,
                    error="Votre réponse est trop longue pour être enregistrée.",
                    revision=revision,
                ),
                status=400,
            )

        now = timezone.now()
        attempt.last_saved_at = now
        fields = [*draft, "last_saved_at"]
        if action in {"save", "expire"}:
            attempt.save(update_fields=fields)
            return redirect(_attempt_url(request, spec, attempt.pk, saved=True))

        if action == "abandon":
            attempt.status = WritingSimulationAttemptStatus.ABANDONED
            attempt.submitted_at = now
            attempt.word_count = _word_count(attempt)
            attempt.save(update_fields=[*fields, *_FINISHED_FIELDS])
            return redirect(_attempt_url(request, spec, attempt.pk))

        error = ""
        if spec.number != 3 and not attempt.body.strip():
            error = f"Rédigez {spec.response_label.lower()} avant de le remettre."
        else:
            for part in _response_parts(attempt, spec):
                if not part["min"] <= part["count"] <= part["max"]:
                    error = f"{part['label']} doit compter entre {part['min']} et {part['max']} mots."
                    break
        if not error:
            attempt.status = WritingSimulationAttemptStatus.SUBMITTED
            attempt.submitted_at = now
            attempt.word_count = _word_count(attempt)
            fields.extend(_FINISHED_FIELDS)
            provider = _auto_evaluation_provider(spec)
            if provider and request.POST.getlist("evaluation_consent") == [provider]:
                _queue_evaluation(attempt, spec, provider if spec.number == 1 else None, now, update_fields=fields)
            else:
                attempt.save(update_fields=fields)
            return redirect(_attempt_url(request, spec, attempt.pk))

        return render(
            request,
            "study/simulation/writing_simulation_attempt.html",
            _attempt_context(request, attempt, spec, error=error, now=now, revision=revision),
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
    configured = _writing_providers(SPECS[1])
    available = configured | reports.keys()
    last_provider = attempt.evaluation.get("provider")
    if last_provider in PROVIDER_LABELS and attempt.evaluation_status == WritingSimulationEvaluationStatus.PROCESSING:
        available.add(last_provider)
    providers = tuple(key for key in PROVIDER_LABELS if key in available) or (default,)
    if last_provider in providers and attempt.evaluation_status in (
        WritingSimulationEvaluationStatus.PROCESSING, WritingSimulationEvaluationStatus.UNAVAILABLE,
    ):
        return providers, last_provider
    if "groq" in reports:
        return providers, "groq"
    if reports:
        return providers, last_provider if last_provider in reports else next(iter(reports))
    return providers, _auto_evaluation_provider(SPECS[1], configured=configured) or providers[0]


def _writing_providers(spec):
    configured = available_providers()
    return configured if spec.number == 1 else configured & {"groq"}


def _auto_evaluation_provider(spec, *, configured=None):
    if configured is None:
        configured = _writing_providers(spec)
    preferred = writing_evaluation.provider_for(spec.number)
    return next((provider for provider in (preferred, "groq", "cloudflare") if provider in configured), "")


def _evaluation_payload(attempt, provider=None):
    status = attempt.evaluation_status
    report = attempt.evaluation if status == WritingSimulationEvaluationStatus.READY else None
    if provider:
        report = _ee1_reports(attempt).get(provider)
        if report is not None:
            status = WritingSimulationEvaluationStatus.READY
        elif status == WritingSimulationEvaluationStatus.READY or attempt.evaluation.get("provider") not in (None, provider):
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
            current = WritingSimulationAttempt.objects.select_for_update().filter(**claim).only("evaluation").first()
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
    attempts = _owned_attempts(request, spec).only(*_EVALUATION_FIELDS)
    if request.method == "GET":
        attempt = get_object_or_404(attempts, pk=attempt_id)
        if attempt.status != WritingSimulationAttemptStatus.SUBMITTED:
            return HttpResponseBadRequest("Cette réponse ne peut pas encore être évaluée.")
        provider = None
        if spec.number == 1:
            providers, default = _ee1_evaluation_options(attempt)
            provider = request.GET.get("provider", default)
            if provider not in providers:
                return JsonResponse({"error": "Modèle d’évaluation invalide."}, status=400)
        return evaluation_json(attempt, provider=provider)

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
            attempts.select_for_update(of=("self",)).only(*_EVALUATION_FIELDS, "body", "position_body"),
            pk=attempt_id,
        )
        now = timezone.now()
        if attempt.status != WritingSimulationAttemptStatus.SUBMITTED:
            return HttpResponseBadRequest("Cette réponse ne peut pas encore être évaluée.")
        if not _has_response(attempt):
            return HttpResponseBadRequest("Aucune réponse à évaluer.")
        provider = None
        if spec.number == 1:
            providers, _ = _ee1_evaluation_options(attempt)
            provider = data.get("provider")
            if provider not in providers:
                return JsonResponse({"error": "Choisissez un modèle disponible avant de lancer l’évaluation."}, status=409)
        elif data.get("provider") not in (None, "groq"):
            return HttpResponseBadRequest("Le modèle d’évaluation n’est pas disponible.")
        cached = (
            provider in _ee1_reports(attempt) if provider
            else attempt.evaluation_status == WritingSimulationEvaluationStatus.READY
        )
        if cached:
            return evaluation_json(attempt, provider=provider)
        if (provider or "groq") not in _writing_providers(spec):
            return JsonResponse(
                {"error": "Ce modèle n’est pas disponible pour une nouvelle évaluation."},
                status=409,
            )
        if (
            attempt.evaluation_status == WritingSimulationEvaluationStatus.PROCESSING
            and attempt.evaluation_started_at
            and now - attempt.evaluation_started_at < EVALUATION_STALE_AFTER
        ):
            if provider and provider != attempt.evaluation.get("provider"):
                return JsonResponse({"error": "Un autre bilan est déjà en cours."}, status=409)
            return evaluation_json(attempt, status=202, provider=provider)
        _queue_evaluation(attempt, spec, provider, now)
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
