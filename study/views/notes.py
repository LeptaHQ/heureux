"""Annotations, notes, and highlight views."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.utils import IntegrityError
from django.db.models import Count, Q
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .. import content_loader as content_module
from ..forms import (
    NoteForm,
)
from ..models import (
    Annotation,
    AnnotationKind,
    Prompt,
    Task,
    WritingSujet,
)
from ..progress import (
    writing_sujet_id_from_source_key,
    writing_sujet_progress_by_id,
)
from ..routing import prompt_detail_url
from ..templatetags.study_markdown import render_markdown

from .helpers import _route_task

MAX_ANNOTATION_QUOTE_LENGTH = 5000


MAX_ANNOTATION_BODY_LENGTH = 20000


ANNOTATION_SOURCE_KEY_RE = re.compile(r"^[A-Za-z0-9:._-]{0,200}$")
SUBJECT_SOURCE_PATH_RE = re.compile(
    r"^/expression/(?P<part>orale|ecrite)/"
    r"(?P<task>[-a-zA-Z0-9_]+)/"
    r"sujets/(?P<prompt_id>\d+)/$"
)
TACHE_TWO_SUBJECT_PATH_RE = re.compile(
    r"^/expression/(?P<part>orale|ecrite)/"
    r"(?P<task>[-a-zA-Z0-9_]+)/"
    r"sujets/(?P<month>[a-z0-9-]+)/batch-(?P<batch>\d+)/"
    r"(?P<subject>\d+)/$"
)
WRITING_SUJET_PATH_RE = re.compile(
    r"^/expression/(?P<part>orale|ecrite)/"
    r"(?P<task>[-a-zA-Z0-9_]+)/"
    r"sujets/messages/(?P<sujet_id>\d+)/"
    r"(?P<edit>personnaliser/)?$"
)
EXPRESSION_PART_BY_PATH = {
    "orale": "eo",
    "ecrite": "ee",
}
COMPREHENSION_PATH_PREFIX = "/comprehension/"
COMPREHENSION_NOTE_MODES = ("ecrite", "orale")
COMPREHENSION_NOTE_LABELS = {
    "ecrite": "Compréhension écrite",
    "orale": "Compréhension orale",
}
CUSTOM_NOTE_FILTER = Q(
    kind=AnnotationKind.NOTE,
    task__isnull=True,
    quote="",
    source_path="",
)


def _comprehension_scope_prefix(mode):
    return f"{COMPREHENSION_PATH_PREFIX}{mode}/"


def _scope_annotations(
    annotations,
    *,
    task,
    aggregate,
    comprehension,
    custom=False,
):
    """Restrict a base annotation queryset to a single notes scope.

    ``custom`` keeps standalone notes created from the notes screen.
    ``comprehension`` ("ecrite"/"orale") keeps task-less notes captured on the
    matching compréhension pages. Générales excludes both groups so these
    folders never overlap. ``aggregate`` (Toutes) keeps everything.
    """
    if custom:
        return annotations.filter(CUSTOM_NOTE_FILTER)
    if comprehension:
        return annotations.filter(
            task__isnull=True,
            source_path__startswith=_comprehension_scope_prefix(comprehension),
        )
    if aggregate:
        return annotations
    annotations = annotations.filter(task=task)
    if task is None:
        annotations = annotations.exclude(
            source_path__startswith=COMPREHENSION_PATH_PREFIX
        ).exclude(CUSTOM_NOTE_FILTER)
    return annotations


def _annotation_counts(user):
    """Every notes-nav count for one learner, from a single grouped scan.

    Returns ``(task_totals, folder_counts)``: ``{task_id: total}`` for the
    tasks that own annotations, and the task-less split the folder nav shows.
    Grouping by task resolves both in one pass — the task list and the folder
    counts used to scan the same rows twice. The conditional columns only
    describe the task-less bucket, which is the only row that reads them.
    """
    task_totals = {}
    folders = {"custom": 0, "ecrite": 0, "orale": 0, "general": 0}
    rows = (
        Annotation.objects.filter(user=user)
        .order_by()
        .values("task_id")
        .annotate(
            total=Count("id"),
            custom=Count("id", filter=CUSTOM_NOTE_FILTER),
            ecrite=Count(
                "id",
                filter=Q(
                    source_path__startswith=_comprehension_scope_prefix(
                        "ecrite"
                    )
                ),
            ),
            orale=Count(
                "id",
                filter=Q(
                    source_path__startswith=_comprehension_scope_prefix(
                        "orale"
                    )
                ),
            ),
        )
    )
    for row in rows:
        total = row["total"] or 0
        if row["task_id"] is not None:
            task_totals[row["task_id"]] = total
            continue
        custom = row["custom"] or 0
        ecrite = row["ecrite"] or 0
        orale = row["orale"] or 0
        folders = {
            "custom": custom,
            "ecrite": ecrite,
            "orale": orale,
            "general": total - custom - ecrite - orale,
        }
    return task_totals, folders


def _annotation_scope_key(annotation):
    """Return the scope-nav bucket key for an annotation.

    Mirrors :func:`_scope_annotations`: task notes map to ``task:<pk>``,
    standalone notes to ``custom``, compréhension notes to
    ``ecrite``/``orale``, and everything else to ``general``. Used to keep the
    scope-nav counts in sync when an item is deleted in place.
    """
    if annotation.task_id is not None:
        return f"task:{annotation.task_id}"
    if (
        annotation.kind == AnnotationKind.NOTE
        and not annotation.quote
        and not annotation.source_path
    ):
        return "custom"
    source_path = annotation.source_path or ""
    for mode in COMPREHENSION_NOTE_MODES:
        if source_path.startswith(_comprehension_scope_prefix(mode)):
            return mode
    return "general"


_TASK_LESS_SCOPE_LABELS = {
    "custom": "Notes personnelles",
    "ecrite": COMPREHENSION_NOTE_LABELS["ecrite"],
    "orale": COMPREHENSION_NOTE_LABELS["orale"],
    "general": "Notes générales",
}


def _annotation_scope_label(annotation):
    if annotation.task_id is not None:
        return f"{annotation.task.part.short_name} · {annotation.task.name}"
    return _TASK_LESS_SCOPE_LABELS[_annotation_scope_key(annotation)]


def _fixed_scope_label(task, *, comprehension=None, custom=False):
    """The one label every row of a single-folder scope carries.

    Outside « Toutes », :func:`_scope_annotations` has already narrowed the
    rows to one bucket, so the label is a property of the folder rather than of
    each row: no ``task``/``part`` join, and no per-row classification.
    """
    if task is not None:
        return f"{task.part.short_name} · {task.name}"
    if custom:
        return _TASK_LESS_SCOPE_LABELS["custom"]
    if comprehension:
        return _TASK_LESS_SCOPE_LABELS[comprehension]
    return _TASK_LESS_SCOPE_LABELS["general"]


def _apply_scope_labels(
    annotations,
    *,
    task,
    aggregate,
    comprehension,
    custom,
):
    if aggregate:
        for annotation in annotations:
            annotation.scope_label = _annotation_scope_label(annotation)
        return
    label = _fixed_scope_label(task, comprehension=comprehension, custom=custom)
    for annotation in annotations:
        annotation.scope_label = label


@require_http_methods(["GET", "POST"])
def notes_overview(request):
    if {"part", "task", "scope"}.intersection(request.GET):
        raise Http404
    return _notes_scope(request, aggregate=True)


def _annotation_scope_url(task=None, *, custom=False):
    if task:
        return reverse(
            "study:task_notes",
            args=[task.part.slug, task.slug],
        )
    if custom:
        return reverse("study:custom_notes")
    return reverse("study:general_notes")


def _annotation_tab_url(task, kind, *, custom=False):
    tab = (
        "highlights"
        if kind == AnnotationKind.HIGHLIGHT
        else "notes"
    )
    return f"{_annotation_scope_url(task, custom=custom)}?tab={tab}"


def _annotation_study_url(
    task=None,
    *,
    aggregate=False,
    comprehension=None,
    custom=False,
):
    if task:
        return reverse(
            "study:task_annotation_study",
            args=[task.part.slug, task.slug],
        )
    if comprehension:
        return reverse(
            "study:comprehension_annotation_study",
            args=[comprehension],
        )
    if custom:
        return reverse("study:custom_annotation_study")
    if aggregate:
        return reverse("study:annotation_study")
    return reverse("study:general_annotation_study")


_HIGHLIGHT_ORIGIN_LABELS = {
    "responses": "Réponse",
    "expressions": "Expression",
}


def _highlight_origin(highlight):
    """Classify a highlight by the kind of source it was captured from."""
    source_key = highlight.source_key or ""
    if source_key.startswith("phrase:"):
        return "expressions"
    if source_key.startswith("response:"):
        return "responses"
    source = urlsplit(highlight.source_path or "")
    source_query = parse_qs(source.query)
    is_expression = (
        "/vocabulaire/" in source.path
        or source.path == reverse("study:vocabulary")
        or source_query.get("kind") == ["phrase"]
    )
    return "expressions" if is_expression else "responses"


_ANNOTATION_DATE_BUCKETS = (
    ("today", "Aujourd’hui"),
    ("yesterday", "Hier"),
    ("week", "Cette semaine"),
    ("month", "Ce mois-ci"),
    ("earlier", "Plus tôt"),
)


def _annotation_date_bucket(local_date, today, yesterday, week_start):
    if local_date >= today:
        return "today"
    if local_date == yesterday:
        return "yesterday"
    if local_date >= week_start:
        return "week"
    if local_date.year == today.year and local_date.month == today.month:
        return "month"
    return "earlier"


def _annotation_date_sections(annotations):
    """Group annotations into ordered, non-empty relative-date sections.

    Sections are keyed on ``created_at`` (the stable capture date) so the
    learning timeline never reshuffles when a card's ``updated_at`` changes,
    e.g. when toggling "à étudier".
    """
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=6)
    items = {key: [] for key, _title in _ANNOTATION_DATE_BUCKETS}
    for annotation in annotations:
        local_date = timezone.localtime(annotation.created_at).date()
        bucket = _annotation_date_bucket(
            local_date, today, yesterday, week_start
        )
        items[bucket].append(annotation)
    return [
        {"key": key, "title": title, "items": items[key]}
        for key, title in _ANNOTATION_DATE_BUCKETS
        if items[key]
    ]


def _filter_annotation_query(annotations, query):
    if not query:
        return annotations
    return annotations.filter(
        Q(title__icontains=query)
        | Q(body__icontains=query)
        | Q(quote__icontains=query)
        | Q(source_title__icontains=query)
    )


def _filter_annotation_status(annotations, status):
    if status == "todo":
        return annotations.filter(
            completed_at__isnull=True,
            study_later=False,
        )
    if status == "done":
        return annotations.filter(completed_at__isnull=False)
    if status == "study":
        return annotations.filter(study_later=True)
    return annotations


def _notes_scope(
    request,
    task=None,
    *,
    aggregate=False,
    comprehension=None,
    custom=False,
):
    annotations = Annotation.objects.filter(user=request.user)
    if aggregate:
        # « Toutes » is the only folder that mixes scopes, so it is the only
        # one that has to reach a task and a part to label each row.
        annotations = annotations.select_related("task__part")
    annotations = _scope_annotations(
        annotations,
        task=task,
        aggregate=aggregate,
        comprehension=comprehension,
        custom=custom,
    )
    query = (request.GET.get("q") or "").strip()
    annotations = _filter_annotation_query(annotations, query)
    status = (
        request.GET.get("status")
        if request.GET.get("status") in {"todo", "done", "study"}
        else ""
    )
    active_tab = (
        request.GET.get("tab")
        if not custom
        and request.GET.get("tab") in {"notes", "highlights"}
        else "notes"
    )
    if request.method == "POST":
        active_tab = "notes"
        instance = Annotation(
            user=request.user,
            task=task,
            kind=AnnotationKind.NOTE,
        )
        form = NoteForm(request.POST, instance=instance)
        if form.is_valid():
            note = form.save()
            if task is None and not custom:
                return redirect(
                    _annotation_scope_url(custom=True)
                    + f"?tab=notes#note-{note.id}"
                )
            return redirect(
                _annotation_redirect(request, note)
                + f"#note-{note.id}"
            )
    else:
        form = NoteForm()
    # Both tabs render from the same rows, so fetch them once in final order
    # and split by kind here rather than paying for a query per tab.
    rows = list(
        _filter_annotation_status(annotations, status).order_by(
            "-created_at", "-id"
        )
    )
    notes = []
    highlights = []
    for annotation in rows:
        if annotation.kind == AnnotationKind.HIGHLIGHT:
            highlights.append(annotation)
        else:
            notes.append(annotation)
    _apply_scope_labels(
        rows,
        task=task,
        aggregate=aggregate,
        comprehension=comprehension,
        custom=custom,
    )
    for highlight in highlights:
        highlight.origin_label = _HIGHLIGHT_ORIGIN_LABELS[
            _highlight_origin(highlight)
        ]
    # The hero count covers the whole folder, before the status filter. With no
    # status filter — or with « À étudier », which selects exactly those rows —
    # the loaded rows already answer it.
    if status in {"", "study"}:
        study_count = sum(1 for annotation in rows if annotation.study_later)
    else:
        study_count = annotations.filter(study_later=True).count()
    task_totals, general_counts = _annotation_counts(request.user)
    task_filters = [
        {
            "task": filter_task,
            "count": task_totals.get(filter_task.pk, 0),
        }
        # Tasks retired from the catalogue stay listed while they still own
        # annotations; their ids come from the counts above, so this needs no
        # join back onto the annotations.
        for filter_task in Task.objects.select_related("part")
        .filter(Q(is_active=True) | Q(pk__in=list(task_totals)))
        .order_by("part__order", "order")
    ]
    preserved = {}
    if query:
        preserved["q"] = query
    if status:
        preserved["status"] = status
    tab_url_prefix = "?" + (urlencode(preserved) + "&" if preserved else "")
    status_base_params = {"tab": active_tab}
    if query:
        status_base_params["q"] = query
    status_filters = []
    for value, label in (
        ("", "Tous"),
        ("todo", "À faire"),
        ("done", "Terminées"),
        ("study", "À étudier"),
    ):
        params = dict(status_base_params)
        if value:
            params["status"] = value
        status_filters.append(
            {
                "value": value,
                "label": label,
                "active": status == value,
                "url": request.path + "?" + urlencode(params),
            }
        )
    flashcard_params = {
        "mode": "all",
        "tab": active_tab,
    }
    if query:
        flashcard_params["q"] = query
    if status:
        flashcard_params["status"] = status
    flashcard_url = (
        _annotation_study_url(
            task,
            aggregate=aggregate,
            comprehension=comprehension,
            custom=custom,
        )
        + "?"
        + urlencode(flashcard_params)
    )
    return render(
        request,
        "study/notes_list.html",
        {
            "part": task.part if task else None,
            "task": task,
            "comprehension": comprehension,
            "custom": custom,
            "scope_title": (
                task.name
                if task
                else COMPREHENSION_NOTE_LABELS[comprehension]
                if comprehension
                else "Notes personnelles"
                if custom
                else "Toutes mes notes"
                if aggregate
                else "Notes générales"
            ),
            "notes": notes,
            "highlights": highlights,
            "notes_sections": _annotation_date_sections(notes),
            "highlights_sections": _annotation_date_sections(highlights),
            "active_tab": active_tab,
            "study_count": study_count,
            "form": form,
            "aggregate": aggregate,
            "query": query,
            "status": status,
            "task_filters": task_filters,
            "general_count": general_counts["general"],
            "custom_count": general_counts["custom"],
            "ce_count": general_counts["ecrite"],
            "co_count": general_counts["orale"],
            "tab_url_prefix": tab_url_prefix,
            "status_filters": status_filters,
            "filters_reset_url": (
                request.path + "?" + urlencode({"tab": active_tab})
            ),
            "flashcard_url": flashcard_url,
            "study_queue_url": _annotation_study_url(
                task,
                aggregate=aggregate,
                comprehension=comprehension,
                custom=custom,
            ),
        },
    )


def task_notes(request, part_slug, task_slug):
    return _notes_scope(
        request,
        _route_task(part_slug, task_slug, request=request),
    )


def general_notes(request):
    return _notes_scope(request)


def custom_notes(request):
    return _notes_scope(request, custom=True)


def comprehension_notes(request, mode):
    if mode not in COMPREHENSION_NOTE_MODES:
        raise Http404
    return _notes_scope(request, comprehension=mode)


def _annotation_anchor(annotation):
    prefix = (
        "highlight"
        if annotation.kind == AnnotationKind.HIGHLIGHT
        else "note"
    )
    return f"{prefix}-{annotation.id}"


ANNOTATION_SEARCH_LIMIT = 100


@require_GET
def annotation_search(request):
    query = (request.GET.get("q") or "").strip()
    kind = (request.GET.get("kind") or "").strip()
    study_only = request.GET.get("study") == "1"
    task_id = (request.GET.get("task") or "").strip()

    annotations = Annotation.objects.filter(user=request.user).select_related(
        "task__part"
    )
    if query:
        annotations = annotations.filter(
            Q(title__icontains=query)
            | Q(body__icontains=query)
            | Q(quote__icontains=query)
            | Q(source_title__icontains=query)
        )
    if kind in AnnotationKind.values:
        annotations = annotations.filter(kind=kind)
    else:
        active_tab = ""
    if study_only:
        annotations = annotations.filter(study_later=True)
    if task_id.isdigit():
        task_id = int(task_id)
        annotations = annotations.filter(task_id=task_id)
    else:
        task_id = None

    # One row past the limit tells us whether the result set was truncated, so
    # the exact total is only worth a scan when it actually was.
    results = list(
        annotations.order_by("-created_at", "-id")[:ANNOTATION_SEARCH_LIMIT + 1]
    )
    result_limit_reached = len(results) > ANNOTATION_SEARCH_LIMIT
    if result_limit_reached:
        del results[ANNOTATION_SEARCH_LIMIT:]
        result_count = annotations.count()
    else:
        result_count = len(results)
    for annotation in results:
        annotation.scope_label = _annotation_scope_label(annotation)
        annotation.notes_url = (
            _annotation_tab_url(
                annotation.task,
                annotation.kind,
                custom=_annotation_scope_key(annotation) == "custom",
            )
            + "#"
            + _annotation_anchor(annotation)
        )
    task_options = (
        Task.objects.filter(
            pk__in=Annotation.objects.filter(user=request.user)
            .exclude(task_id=None)
            .order_by()
            .values("task_id")
        )
        .select_related("part")
        .order_by("part__order", "order", "name")
    )
    return render(
        request,
        "study/annotation_search.html",
        {
            "query": query,
            "selected_kind": kind,
            "study_only": study_only,
            "selected_task_id": task_id,
            "task_options": task_options,
            "results": results,
            "result_count": result_count,
            "result_limit_reached": result_limit_reached,
        },
    )


@require_GET
def annotation_study(
    request,
    part_slug=None,
    task_slug=None,
    general_only=False,
    comprehension=None,
    custom_only=False,
):
    if "scope" in request.GET:
        raise Http404
    if comprehension is not None and comprehension not in COMPREHENSION_NOTE_MODES:
        raise Http404
    requested_mode = (request.GET.get("mode") or "").strip()
    if requested_mode not in {"", "all"} or "item" in request.GET:
        raise Http404
    task = (
        _route_task(part_slug, task_slug, request=request)
        if part_slug is not None and task_slug is not None
        else None
    )
    study_mode = "all" if requested_mode == "all" else "queue"
    aggregate = (
        not task
        and not comprehension
        and not general_only
        and not custom_only
    )
    annotations = Annotation.objects.filter(user=request.user)
    if aggregate:
        # Only the all-notes deck mixes scopes, so it is the only one whose
        # cards need a task and a part to label themselves.
        annotations = annotations.select_related("task__part")
    annotations = _scope_annotations(
        annotations,
        task=task,
        aggregate=aggregate,
        comprehension=comprehension,
        custom=custom_only,
    )
    query = ""
    status = ""
    active_tab = ""
    if study_mode == "queue":
        annotations = annotations.filter(study_later=True)
    else:
        query = (request.GET.get("q") or "").strip()
        status = (
            request.GET.get("status")
            if request.GET.get("status") in {"todo", "done", "study"}
            else ""
        )
        active_tab = (
            request.GET.get("tab")
            if not custom_only
            and request.GET.get("tab") in {"notes", "highlights"}
            else "notes"
        )
        annotations = _filter_annotation_query(annotations, query)
        annotations = _filter_annotation_status(annotations, status)
        annotations = annotations.filter(
            kind=(
                AnnotationKind.HIGHLIGHT
                if active_tab == "highlights"
                else AnnotationKind.NOTE
            )
        )
    items = list(annotations.order_by("-updated_at", "-id"))
    _apply_scope_labels(
        items,
        task=task,
        aggregate=aggregate,
        comprehension=comprehension,
        custom=custom_only,
    )
    back_url = (
        _annotation_scope_url(task)
        if task
        else reverse(
            "study:comprehension_notes", args=[comprehension]
        )
        if comprehension
        else reverse("study:general_notes")
        if general_only
        else reverse("study:custom_notes")
        if custom_only
        else reverse("study:notes_overview")
    )
    if study_mode == "all":
        back_params = {"tab": active_tab}
        if query:
            back_params["q"] = query
        if status:
            back_params["status"] = status
        back_url += "?" + urlencode(back_params)
    return render(
        request,
        "study/annotation_study.html",
        {
            "part": task.part if task else None,
            "task": task,
            "items": items,
            "study_mode": study_mode,
            "scope_title": (
                task.name
                if task
                else COMPREHENSION_NOTE_LABELS[comprehension]
                if comprehension
                else "Notes personnelles"
                if custom_only
                else "Notes générales"
                if general_only
                else "Toutes mes notes"
            ),
            "back_url": back_url,
        },
    )


def _safe_source_path(value):
    value = (value or "").strip()
    parsed = urlsplit(value)
    if (
        not value
        or parsed.scheme
        or parsed.netloc
        or not parsed.path.startswith("/")
    ):
        raise ValueError("Invalid source path.")
    path = parsed.path
    if parsed.query:
        path += "?" + parsed.query
    return path[:500]


def _annotation_task(value):
    if not value:
        return None
    try:
        task_id = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid task.") from error
    return get_object_or_404(
        Task.objects.select_related("part"),
        pk=task_id,
        is_active=True,
    )


def _annotation_source_key(value):
    value = (value or "").strip()
    if not ANNOTATION_SOURCE_KEY_RE.fullmatch(value):
        raise ValueError("Invalid annotation source key.")
    return value


def _writing_sujet_progress_payload(user, source_key):
    """Refreshed EE Tâche 1 progress for a highlight's sujet, if it has one.

    Only ``writing-sujet:<id>`` source keys resolve, and the progress helper
    derives its answer from the learner's own rows, so the sujet itself never
    has to be fetched. A key can still carry an id no sujet can have — the
    pattern accepts ``writing-sujet:0:personal`` — so the lookup stays
    optional rather than assuming a row comes back.
    """
    sujet_id = writing_sujet_id_from_source_key(source_key)
    if sujet_id is None or sujet_id <= 0:
        return {}
    progress = writing_sujet_progress_by_id(user, [sujet_id]).get(sujet_id)
    if progress is None:
        return {}
    return {
        "writing_sujet_progress": {
            "sujet_id": sujet_id,
            "completed": progress.explicitly_completed,
            "sujet": {
                "status": progress.status,
                "label": progress.label,
            },
        }
    }


def _annotation_overlap_ids(value):
    if value is None:
        return None
    if not value:
        return []
    parts = value.split(",")
    if len(parts) > 100:
        raise ValueError("Too many overlapping highlights.")
    ids = [int(part) for part in parts]
    if any(pk <= 0 for pk in ids):
        raise ValueError("Invalid overlapping highlight.")
    return list(dict.fromkeys(ids))


def _annotation_overlap_revisions(value):
    if value is None:
        return None
    revisions = json.loads(value)
    if not isinstance(revisions, dict) or len(revisions) > 100:
        raise ValueError("Invalid highlight revisions.")
    parsed = {}
    for raw_id, revision in revisions.items():
        pk = int(raw_id)
        if pk <= 0 or not isinstance(revision, str) or len(revision) > 64:
            raise ValueError("Invalid highlight revision.")
        parsed[pk] = revision
    return parsed


def _annotation_prompt_scope(prompt):
    canonical = prompt.response.canonical_prompt or prompt
    canonical_path = prompt_detail_url(canonical)
    sibling_paths = [
        prompt_detail_url(sibling)
        for sibling in prompt.response.prompts.filter(
            is_active=True,
            theme__task__isnull=False,
        ).select_related("theme__task__part")
    ]
    source_filter = Q()
    for sibling_path in sibling_paths:
        source_filter |= Q(source_path=sibling_path)
        source_filter |= Q(
            source_path__startswith=f"{sibling_path}?"
        )
    return canonical_path, source_filter


def _annotation_writing_sujet_scope(sujet, tache, *, prefer_edit=False):
    canonical_by_slug = content_module.ee_writing_canonical_slug_by_slug(tache)
    canonical_slug = canonical_by_slug.get(sujet.slug, sujet.slug)
    sibling_slugs = [
        slug
        for slug, target_slug in canonical_by_slug.items()
        if target_slug == canonical_slug
    ]
    siblings = list(
        WritingSujet.objects.filter(
            task=sujet.task,
            slug__in=sibling_slugs,
            is_active=True,
        ).order_by("order", "pk")
    )
    canonical = next(
        (item for item in siblings if item.slug == canonical_slug),
        sujet,
    )
    canonical_path = reverse(
        (
            "study:writing_sujet_edit"
            if prefer_edit
            else "study:writing_sujet_detail"
        ),
        args=[sujet.task.part.slug, sujet.task.slug, canonical.pk],
    )
    source_filter = Q()
    for sibling in siblings:
        for route_name in (
            "study:writing_sujet_detail",
            "study:writing_sujet_edit",
        ):
            sibling_path = reverse(
                route_name,
                args=[sujet.task.part.slug, sujet.task.slug, sibling.pk],
            )
            source_filter |= Q(source_path=sibling_path)
            source_filter |= Q(source_path__startswith=f"{sibling_path}?")
    return canonical_path, source_filter


def _annotation_source_scope(source_path):
    base_path = source_path.split("?", 1)[0]
    match = SUBJECT_SOURCE_PATH_RE.fullmatch(base_path)
    if match:
        prompt = (
            Prompt.objects.filter(
                pk=match.group("prompt_id"),
                is_active=True,
                response__is_active=True,
                theme__task__part__slug=EXPRESSION_PART_BY_PATH[
                    match.group("part")
                ],
                theme__task__slug=match.group("task"),
            )
            .select_related("response")
            .first()
        )
        if prompt is not None:
            return _annotation_prompt_scope(prompt)
    writing_match = WRITING_SUJET_PATH_RE.fullmatch(base_path)
    if writing_match:
        part_slug = EXPRESSION_PART_BY_PATH[writing_match.group("part")]
        task_slug = writing_match.group("task")
        tache = {
            content_module.EE_TACHE_ONE_TASK: 1,
            content_module.EE_TACHE_TWO_TASK: 2,
        }.get((part_slug, task_slug))
        if tache is not None:
            sujet = (
                WritingSujet.objects.filter(
                    pk=writing_match.group("sujet_id"),
                    is_active=True,
                    task__part__slug=part_slug,
                    task__slug=task_slug,
                )
                .select_related("task__part")
                .first()
            )
            if sujet is not None:
                return _annotation_writing_sujet_scope(
                    sujet,
                    tache,
                    prefer_edit=bool(writing_match.group("edit")),
                )
    tache_two_match = TACHE_TWO_SUBJECT_PATH_RE.fullmatch(base_path)
    if tache_two_match:
        prompt = (
            Prompt.objects.filter(
                content_key=content_module.tache_two_subject_content_key(
                    tache_two_match.group("month"),
                    int(tache_two_match.group("batch")),
                    int(tache_two_match.group("subject")),
                ),
                is_active=True,
                response__is_active=True,
                theme__task__part__slug=EXPRESSION_PART_BY_PATH[
                    tache_two_match.group("part")
                ],
                theme__task__slug=tache_two_match.group("task"),
            )
            .select_related("response")
            .first()
        )
        if prompt is not None:
            return _annotation_prompt_scope(prompt)
    return source_path, Q(source_path=source_path)


@require_GET
def annotations_for_source(request):
    try:
        source_path = _safe_source_path(request.GET.get("source_path"))
    except ValueError:
        return HttpResponseBadRequest("Invalid source path.")
    _, source_filter = _annotation_source_scope(source_path)
    highlights = list(
        Annotation.objects.filter(
            source_filter,
            user=request.user,
            kind=AnnotationKind.HIGHLIGHT,
        ).values(
            "id",
            "quote",
            "source_key",
            "start_offset",
            "end_offset",
            "prefix",
            "suffix",
            "updated_at",
        )
    )
    for highlight in highlights:
        highlight["revision"] = highlight.pop("updated_at").isoformat()
        highlight["delete_url"] = reverse(
            "study:annotation_delete",
            args=[highlight["id"]],
        )
    return JsonResponse({"highlights": highlights})


@require_POST
def annotation_create(request):
    kind = (request.POST.get("kind") or "").strip()
    if kind not in AnnotationKind.values:
        return HttpResponseBadRequest("Invalid annotation kind.")
    quote = request.POST.get("quote") or ""
    body = (request.POST.get("body") or "").strip()
    if not quote.strip():
        return JsonResponse(
            {"error": "Sélectionnez du texte avant de continuer."},
            status=400,
        )
    if len(quote) > MAX_ANNOTATION_QUOTE_LENGTH:
        return JsonResponse(
            {"error": "La sélection est trop longue."},
            status=400,
        )
    if len(body) > MAX_ANNOTATION_BODY_LENGTH:
        return JsonResponse(
            {"error": "La note est trop longue."},
            status=400,
        )
    try:
        task = _annotation_task(request.POST.get("task_id"))
        source_path = _safe_source_path(request.POST.get("source_path"))
        source_path, source_filter = _annotation_source_scope(source_path)
        source_key = _annotation_source_key(request.POST.get("source_key"))
        overlap_ids = _annotation_overlap_ids(request.POST.get("overlap_ids"))
        overlap_revisions = _annotation_overlap_revisions(
            request.POST.get("overlap_revisions")
        )
        start_offset = int(request.POST.get("start_offset", ""))
        end_offset = int(request.POST.get("end_offset", ""))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Invalid annotation data.")
    if start_offset < 0 or end_offset <= start_offset:
        return HttpResponseBadRequest("Invalid annotation offsets.")
    if overlap_ids and (
        overlap_revisions is None
        or set(overlap_ids) != set(overlap_revisions)
    ):
        return HttpResponseBadRequest("Invalid highlight revisions.")

    values = {
        "task": task,
        "quote": quote,
        "source_title": (request.POST.get("source_title") or "")[:300],
        "prefix": (request.POST.get("prefix") or "")[-160:],
        "suffix": (request.POST.get("suffix") or "")[:160],
        "body": body,
    }
    removed_ids = []
    try:
        if kind == AnnotationKind.HIGHLIGHT:
            with transaction.atomic():
                candidates = Annotation.objects.select_for_update().filter(
                    source_filter,
                    user=request.user,
                    kind=kind,
                    source_key=source_key,
                )
                if overlap_ids is None:
                    candidates = candidates.filter(
                        start_offset__lt=end_offset,
                        end_offset__gt=start_offset,
                    )
                    overlapping = list(
                        candidates.order_by("-updated_at", "-id")
                    )
                else:
                    overlapping = list(
                        candidates.filter(id__in=overlap_ids).order_by(
                            "-updated_at",
                            "-id",
                        )
                    )
                    if overlap_revisions is not None and (
                        len(overlapping) != len(overlap_ids)
                        or any(
                            item.updated_at.isoformat()
                            != overlap_revisions[item.id]
                            for item in overlapping
                        )
                    ):
                        return JsonResponse(
                            {
                                "error": (
                                    "Ce surlignage a changé dans un autre onglet. "
                                    "Réessayez avec la version actualisée."
                                )
                            },
                            status=409,
                        )
                    exact_retry = (
                        candidates.filter(
                            start_offset=start_offset,
                            end_offset=end_offset,
                        )
                        .exclude(id__in=overlap_ids)
                        .first()
                    )
                    if exact_retry:
                        if exact_retry.quote != quote:
                            return JsonResponse(
                                {
                                    "error": (
                                        "Les surlignages de cette page ont changé. "
                                        "Supprimez le passage en conflit avant de "
                                        "réessayer."
                                    )
                                },
                                status=409,
                            )
                        overlapping.append(exact_retry)
                annotation = next(
                    (
                        item
                        for item in overlapping
                        if item.start_offset == start_offset
                        and item.end_offset == end_offset
                    ),
                    overlapping[0] if overlapping else None,
                )
                created = annotation is None
                if created:
                    annotation = Annotation(
                        user=request.user,
                        kind=kind,
                        source_path=source_path,
                        source_key=source_key,
                        start_offset=start_offset,
                        end_offset=end_offset,
                        **values,
                    )
                else:
                    annotation.task = task
                    annotation.quote = quote
                    annotation.source_title = values["source_title"]
                    annotation.prefix = values["prefix"]
                    annotation.suffix = values["suffix"]
                    annotation.body = body
                    annotation.start_offset = start_offset
                    annotation.end_offset = end_offset
                    annotation.study_later = any(
                        item.study_later for item in overlapping
                    )
                annotation.full_clean(validate_constraints=False)
                try:
                    with transaction.atomic():
                        annotation.save()
                except IntegrityError:
                    concurrent = candidates.filter(
                        start_offset=start_offset,
                        end_offset=end_offset,
                    ).first()
                    if (
                        not created
                        or overlapping
                        or concurrent is None
                        or concurrent.quote != quote
                    ):
                        return JsonResponse(
                            {
                                "error": (
                                    "Les surlignages de cette page ont changé. "
                                    "Actualisez la page puis réessayez."
                                )
                            },
                            status=409,
                        )
                    annotation = concurrent
                    created = False
                removed_ids = [
                    item.id for item in overlapping if item.id != annotation.id
                ]
                if removed_ids:
                    Annotation.objects.filter(
                        user=request.user,
                        id__in=removed_ids,
                    ).delete()
        else:
            annotation = Annotation(
                user=request.user,
                kind=kind,
                source_path=source_path,
                source_key=source_key,
                start_offset=start_offset,
                end_offset=end_offset,
                **values,
            )
            annotation.full_clean()
            annotation.save()
            created = True
    except ValidationError as error:
        return JsonResponse(
            {"error": " ".join(error.messages)},
            status=400,
        )
    payload = {
        "id": annotation.id,
        "created": created,
        "removed_ids": removed_ids,
        "revision": annotation.updated_at.isoformat(),
        "delete_url": reverse(
            "study:annotation_delete",
            args=[annotation.id],
        ),
        "notes_url": (
            _annotation_tab_url(
                task,
                annotation.kind,
                custom=_annotation_scope_key(annotation) == "custom",
            )
            + "#"
            + _annotation_anchor(annotation)
        ),
    }
    if annotation.kind == AnnotationKind.HIGHLIGHT:
        payload.update(
            _writing_sujet_progress_payload(
                request.user,
                annotation.source_key,
            )
        )
    return JsonResponse(payload, status=201 if created else 200)


def _is_fetch(request):
    return request.headers.get("X-Requested-With") == "fetch"


def _annotation_next_url(request):
    """The caller-supplied return URL, when it is safe to follow."""
    candidate = request.POST.get("next")
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return None


def _annotation_redirect(request, annotation):
    return _annotation_next_url(request) or _annotation_tab_url(
        annotation.task,
        annotation.kind,
        custom=_annotation_scope_key(annotation) == "custom",
    )


def _annotation_action_queryset(request):
    """The learner's annotations, joined only when the response needs it.

    A card action answers JSON, or redirects to the URL the form carried;
    neither walks to the task. It is only the bare fallback redirect that
    rebuilds a folder URL, and there one compact join beats lazily loading the
    task and its part one round trip at a time.
    """
    annotations = Annotation.objects.filter(user=request.user)
    if _is_fetch(request) or _annotation_next_url(request) is not None:
        return annotations
    return annotations.select_related("task__part")


@require_POST
def annotation_update(request, pk):
    annotation = get_object_or_404(
        _annotation_action_queryset(request),
        pk=pk,
        kind=AnnotationKind.NOTE,
    )
    form = NoteForm(request.POST, instance=annotation)
    if not form.is_valid():
        return JsonResponse(
            {"error": "Corrigez la note avant de l'enregistrer."},
            status=400,
        )
    form.save()
    redirect_url = _annotation_redirect(request, annotation) + f"#note-{pk}"
    if _is_fetch(request):
        # The rendered body lets callers such as the study deck refresh a
        # single card instead of reloading and losing their place.
        return JsonResponse(
            {
                "redirect_url": redirect_url,
                "id": annotation.pk,
                "title": annotation.title,
                "body": annotation.body,
                "body_html": render_markdown(annotation.body),
            }
        )
    return redirect(redirect_url)


@require_POST
def annotation_study_toggle(request, pk):
    annotation = get_object_or_404(
        _annotation_action_queryset(request),
        pk=pk,
    )
    value = request.POST.get("study_later")
    if value not in {"0", "1"}:
        return HttpResponseBadRequest("Invalid study status.")
    annotation.study_later = value == "1"
    annotation.save(update_fields=["study_later", "updated_at"])
    if _is_fetch(request):
        return JsonResponse(
            {
                "study_later": annotation.study_later,
                "id": annotation.pk,
                "kind": annotation.kind,
            }
        )
    return redirect(_annotation_redirect(request, annotation))


@require_POST
def annotation_complete_toggle(request, pk):
    annotation = get_object_or_404(
        _annotation_action_queryset(request),
        pk=pk,
    )
    value = request.POST.get("completed")
    if value not in {"0", "1"}:
        return HttpResponseBadRequest("Invalid completion status.")
    annotation.completed_at = timezone.now() if value == "1" else None
    annotation.save(update_fields=["completed_at", "updated_at"])
    if _is_fetch(request):
        return JsonResponse(
            {
                "completed": annotation.completed,
                "id": annotation.pk,
                "kind": annotation.kind,
            }
        )
    return redirect(_annotation_redirect(request, annotation))


@require_POST
def annotation_delete(request, pk):
    annotation = get_object_or_404(
        _annotation_action_queryset(request),
        pk=pk,
    )
    is_fetch = _is_fetch(request)
    # Resolved before the row goes away, and only for the caller that follows
    # it: a fetch response never redirects.
    target = None if is_fetch else _annotation_redirect(request, annotation)
    payload = {
        "deleted": True,
        "id": annotation.pk,
        "kind": annotation.kind,
        "was_study": annotation.study_later,
        "scope": _annotation_scope_key(annotation),
    }
    source_key = annotation.source_key
    kind = annotation.kind
    annotation.delete()
    if kind == AnnotationKind.HIGHLIGHT:
        payload.update(
            _writing_sujet_progress_payload(request.user, source_key)
        )
    if is_fetch:
        return JsonResponse(payload)
    return redirect(target)


TRANSLATION_MAX_LENGTH = 2000


@require_POST
def translate_selection(request):
    """Translate a selected passage server-side.

    Browsers only ship the on-device Translator API on desktop, so mobile
    needs a server round trip. Nothing is sent anywhere unless an operator
    configures ``TRANSLATION_API_URL`` with a LibreTranslate-compatible
    endpoint (self-hosted by default).
    """
    endpoint = getattr(settings, "TRANSLATION_API_URL", "")
    if not endpoint:
        return JsonResponse(
            {"error": "not_configured"},
            status=503,
        )

    text = (request.POST.get("text") or "").strip()
    if not text:
        return HttpResponseBadRequest("Aucun texte à traduire.")
    if len(text) > TRANSLATION_MAX_LENGTH:
        return JsonResponse({"error": "too_long"}, status=413)

    cache_key = "translation:fr:en:" + hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()
    cached = cache.get(cache_key)
    if cached is not None:
        return JsonResponse({"translation": cached, "cached": True})

    payload = {
        "q": text,
        "source": "fr",
        "target": "en",
        "format": "text",
    }
    api_key = getattr(settings, "TRANSLATION_API_KEY", "")
    if api_key:
        payload["api_key"] = api_key
    api_request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            api_request,
            timeout=getattr(settings, "TRANSLATION_TIMEOUT", 8),
        ) as api_response:
            body = json.loads(api_response.read().decode("utf-8"))
    except Exception:  # pragma: no cover - network failure paths
        return JsonResponse({"error": "upstream"}, status=502)

    translation = (body or {}).get("translatedText") or ""
    if isinstance(translation, list):
        translation = translation[0] if translation else ""
    translation = str(translation).strip()
    if not translation:
        return JsonResponse({"error": "empty"}, status=502)

    cache.set(cache_key, translation, 60 * 60 * 24 * 30)
    return JsonResponse({"translation": translation})
