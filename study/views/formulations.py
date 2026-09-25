"""Category-first study and optional, ungraded recall of reusable EE3 frames."""

import unicodedata
from urllib.parse import urlencode

from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from ..ee_formulations import get_ee_formulations
from ..formulation_progress import formulation_progress
from ..models import MemoryQuestionProgress, Prompt
from .helpers import _route_task


FILTER_KEYS = ("q", "category", "theme", "status", "essential", "mode", "entry")


def _fold(text):
    return "".join(
        char for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )


def _filters(data, catalog):
    if any(len(data.getlist(key)) > 1 for key in FILTER_KEYS):
        raise Http404("Filtre répété.")
    values = {key: data.get(key, "").strip() for key in FILTER_KEYS}
    choices = {
        "category": {item.slug for item in catalog.categories},
        "theme": {item.slug for item in catalog.categories if item.kind == "theme"},
        "status": {"new", "learned"},
        "essential": {"1"},
        "mode": {"table", "practice"},
        "entry": {item.slug for item in catalog.entries},
    }
    for key, allowed in choices.items():
        if values[key] and values[key] not in allowed:
            raise Http404("Filtre inconnu.")
    if len(values["q"]) > 200:
        raise Http404("Recherche trop longue.")
    return {key: value for key, value in values.items() if value}


def formulation_url(filters=None):
    url = reverse("study:ee_formulations")
    return url + ("?" + urlencode(filters) if filters else "")


def _selection(catalog, filters, learned):
    query = _fold(filters.get("q", ""))
    categories = {item.slug: item for item in catalog.categories}
    result = []
    for entry in catalog.entries:
        if filters.get("category") and entry.category != filters["category"]:
            continue
        if filters.get("theme") and filters["theme"] not in entry.themes:
            continue
        if filters.get("essential") and not entry.essential:
            continue
        is_learned = entry.content_key in learned
        if filters.get("status") == "learned" and not is_learned:
            continue
        if filters.get("status") == "new" and is_learned:
            continue
        text = " ".join((
            entry.label, entry.french, entry.english, entry.usage, entry.grammar,
            entry.example, categories[entry.category].title,
            *(categories[slug].title for slug in entry.themes),
        ))
        if query and query not in _fold(text):
            continue
        result.append(entry)
    return result


@require_GET
def formulations(request):
    task = _route_task("ee", "tache-3", request=request)
    if not task.available:
        raise Http404
    catalog = get_ee_formulations()
    filters = _filters(request.GET, catalog)
    learned, progress = formulation_progress(request.user, catalog)
    selected = _selection(catalog, filters, learned)
    practice = filters.get("mode") == "practice"
    index = next(
        (i for i, entry in enumerate(selected) if entry.slug == filters.get("entry")),
        0,
    )
    visible = selected[index:index + 1] if practice else selected
    sources = {}
    for key, prompt_id in Prompt.objects.filter(
        response__content_key__in={entry.source_key for entry in visible},
        response__is_active=True, is_active=True, theme__is_active=True,
        theme__task=task,
    ).order_by("response_id", "number", "pk").values_list("response__content_key", "pk"):
        sources.setdefault(key, reverse("study:response_detail", args=["ee", "tache-3", prompt_id]))
    categories = {item.slug: item for item in catalog.categories}
    rows = [
        {
            "entry": entry,
            "category": categories[entry.category],
            "learned": entry.content_key in learned,
            "source_url": sources.get(entry.source_key, ""),
            "copy_id": "formulation-copy-" + entry.slug,
        }
        for entry in visible
    ]
    browse_filters = {key: value for key, value in filters.items() if key not in {"mode", "entry"}}
    groups = []
    for kind, title in (("function", "Fonctions d’écriture"), ("theme", "Arguments par thème")):
        items = []
        for category in catalog.categories:
            if category.kind != kind:
                continue
            entries = [entry for entry in catalog.entries if entry.category == category.slug]
            items.append({
                "category": category,
                "count": len(entries),
                "completed": sum(entry.content_key in learned for entry in entries),
                "url": formulation_url({"category": category.slug}),
            })
        groups.append({"title": title, "items": items})
    return render(request, "study/formulations.html", {
        "part": task.part, "task": task, "catalog": catalog,
        "filters": filters, "filter_fields": filters.items(),
        "browse_fields": browse_filters.items(),
        "groups": groups, "categories": catalog.categories,
        "themes": [item for item in catalog.categories if item.kind == "theme"],
        "rows": rows, "progress": progress, "result_count": len(selected),
        "essential_count": sum(entry.essential for entry in catalog.entries),
        "practice": practice, "position": index + 1,
        "browse_url": formulation_url(browse_filters),
        "practice_url": formulation_url({**browse_filters, "mode": "practice"}),
        "previous_url": formulation_url({**filters, "entry": selected[index - 1].slug}) if practice and index else "",
        "next_url": formulation_url({**filters, "entry": selected[index + 1].slug}) if practice and index + 1 < len(selected) else "",
    })


@require_POST
def formulation_learned(request, slug):
    task = _route_task("ee", "tache-3", request=request)
    if not task.available:
        raise Http404
    catalog = get_ee_formulations()
    filters = _filters(request.POST, catalog)
    entry = next((entry for entry in catalog.entries if entry.slug == slug), None)
    if entry is None:
        raise Http404
    completed = request.POST.getlist("completed")
    if completed not in (["0"], ["1"]):
        return HttpResponseBadRequest("État de progression invalide.")
    lookup = {"user": request.user, "memory_number": 1, "question_key": entry.content_key}
    if completed == ["1"]:
        MemoryQuestionProgress.objects.get_or_create(**lookup)
    else:
        MemoryQuestionProgress.objects.filter(**lookup).delete()
    return redirect(formulation_url(filters) + "#formulation-" + entry.slug)
