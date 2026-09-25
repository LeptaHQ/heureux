"""Nested directory and optional, ungraded recall of reusable EE3 frames."""

import unicodedata
from urllib.parse import urlencode, urlsplit

from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import Resolver404, resolve, reverse
from django.views.decorators.http import require_GET, require_POST

from ..ee_formulation_language import formulation_language_for
from ..ee_formulations import get_ee_formulations
from ..formulation_progress import formulation_progress
from ..models import MemoryQuestionProgress, Prompt
from ..progress import progress_summary
from .helpers import _route_task


FILTER_KEYS = ("q", "status", "mode", "entry")
LEGACY_FILTER_KEYS = (*FILTER_KEYS, "category", "theme", "essential")
COLLECTION_ROUTES = {
    "essentials": "study:ee_formulation_essentials",
    "function": "study:ee_formulation_function",
    "theme": "study:ee_formulation_theme",
    "search": "study:ee_formulation_search",
}
RETURN_ROUTES = {
    "ee_formulation_essentials",
    "ee_formulation_function",
    "ee_formulation_theme",
    "ee_formulation_search",
}
def _fold(text):
    return "".join(
        char for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )


def _filters(data, catalog, *, keys=FILTER_KEYS):
    if any(len(data.getlist(key)) > 1 for key in keys):
        raise Http404("Filtre répété.")
    values = {key: data.get(key, "").strip() for key in keys}
    choices = {
        "status": {"new", "learned"},
        "mode": {"table", "practice"},
        "entry": {item.slug for item in catalog.entries},
        "category": {item.slug for item in catalog.categories},
        "theme": {item.slug for item in catalog.categories if item.kind == "theme"},
        "essential": {"1"},
    }
    for key, allowed in choices.items():
        if key in values and values[key] and values[key] not in allowed:
            raise Http404("Filtre inconnu.")
    if "q" in values and len(values["q"]) > 200:
        raise Http404("Recherche trop longue.")
    return {key: value for key, value in values.items() if value}


def _progress(entries, learned):
    completed = sum(entry.content_key in learned for entry in entries)
    return progress_summary(
        total=len(entries),
        started=completed,
        completed=completed,
    )


def collection_url(kind, slug="", filters=None):
    route = COLLECTION_ROUTES[kind]
    args = [slug] if slug else []
    url = reverse(route, args=args)
    return url + ("?" + urlencode(filters) if filters else "")


def formulation_url(filters=None):
    """Keep old internal callers on a stable replacement URL."""
    return reverse("study:ee_formulations") + (
        "?" + urlencode(filters) if filters else ""
    )


def _selection(entries, categories, filters, learned):
    query = _fold(filters.get("q", ""))
    result = []
    for entry in entries:
        is_learned = entry.content_key in learned
        if filters.get("status") == "learned" and not is_learned:
            continue
        if filters.get("status") == "new" and is_learned:
            continue
        text = " ".join((
            entry.label, entry.french, entry.english, entry.usage, entry.grammar,
            entry.example, entry.example_english, entry.transfer_prompt,
            categories[entry.category].title,
            *(categories[slug].title for slug in entry.themes),
        ))
        if query and query not in _fold(text):
            continue
        result.append(entry)
    return result


def _directory_item(category, entries, learned, *, kind):
    return {
        "category": category,
        "count": len(entries),
        "completed": sum(entry.content_key in learned for entry in entries),
        "progress": _progress(entries, learned),
        "url": collection_url(kind, category.slug),
    }


def _legacy_destination(filters, catalog):
    forwarded = {
        key: value for key, value in filters.items()
        if key in FILTER_KEYS
    }
    categories = {category.slug: category for category in catalog.categories}
    if filters.get("theme"):
        return collection_url("theme", filters["theme"], forwarded)
    if filters.get("category"):
        category = categories[filters["category"]]
        kind = "function" if category.kind == "function" else "theme"
        return collection_url(kind, category.slug, forwarded)
    if filters.get("essential"):
        return collection_url("essentials", filters=forwarded)
    return collection_url("search", filters=forwarded)


@require_GET
def formulations(request):
    task = _route_task("ee", "tache-3", request=request)
    if not task.available:
        raise Http404
    catalog = get_ee_formulations()
    if request.GET:
        filters = _filters(request.GET, catalog, keys=LEGACY_FILTER_KEYS)
        return redirect(_legacy_destination(filters, catalog))

    learned, progress = formulation_progress(request.user, catalog)
    essentials = [entry for entry in catalog.entries if entry.essential]
    function_items = []
    theme_items = []
    for category in catalog.categories:
        if category.kind == "function":
            entries = [
                entry for entry in essentials
                if entry.category == category.slug
            ]
            if entries:
                item = _directory_item(
                    category, entries, learned, kind="function",
                )
                item["expanded_count"] = sum(
                    entry.category == category.slug
                    for entry in catalog.entries
                )
                function_items.append(item)
        else:
            entries = [
                entry for entry in catalog.entries
                if entry.category == category.slug
            ]
            if entries:
                theme_items.append(
                    _directory_item(category, entries, learned, kind="theme")
                )
    return render(request, "study/formulation_directory.html", {
        "part": task.part,
        "task": task,
        "progress": progress,
        "tables": (
            {
                "slug": "essentials",
                "title": "Essentiels",
                "description": (
                    "Les constructions à maîtriser pour bâtir une réponse "
                    "complète, classées par fonction d’écriture."
                ),
                "items": function_items,
                "progress": _progress(essentials, learned),
                "all_url": collection_url("essentials"),
                "all_label": "Ouvrir les essentiels",
            },
            {
                "slug": "themes",
                "title": "Thèmes",
                "description": (
                    "Des arguments, bénéfices, limites et solutions prêts "
                    "à adapter aux sujets fréquents."
                ),
                "items": theme_items,
                "progress": _progress(
                    [
                        entry for entry in catalog.entries
                        if entry.category in {
                            category.slug for category in catalog.categories
                            if category.kind == "theme"
                        }
                    ],
                    learned,
                ),
                "all_url": collection_url("search"),
                "all_label": "Rechercher dans tout le catalogue",
            },
        ),
        "search_url": collection_url("search"),
    })


def _collection_definition(catalog, kind, slug):
    categories = {category.slug: category for category in catalog.categories}
    if kind == "essentials":
        return {
            "title": "Les essentiels",
            "eyebrow": "Parcours recommandé",
            "description": (
                "Les formulations indispensables pour synthétiser, prendre "
                "position, développer deux raisons et conclure."
            ),
            "entries": [entry for entry in catalog.entries if entry.essential],
            "category": None,
        }
    if kind == "search":
        return {
            "title": "Toutes les formulations",
            "eyebrow": "Recherche",
            "description": (
                "Rechercher une construction, un argument ou une situation "
                "dans tout le catalogue."
            ),
            "entries": list(catalog.entries),
            "category": None,
        }
    category = categories.get(slug)
    expected_kind = "function" if kind == "function" else "theme"
    if category is None or category.kind != expected_kind:
        raise Http404("Subdivision inconnue.")
    return {
        "title": category.title,
        "eyebrow": "Essentiels · Fonction d’écriture" if kind == "function"
        else "Thèmes · Arguments à adapter",
        "description": category.description,
        "entries": [
            entry for entry in catalog.entries
            if entry.category == category.slug
        ],
        "category": category,
    }


@require_GET
def formulation_collection(request, kind, slug=""):
    task = _route_task("ee", "tache-3", request=request)
    if not task.available:
        raise Http404
    catalog = get_ee_formulations()
    definition = _collection_definition(catalog, kind, slug)
    filters = _filters(request.GET, catalog)
    learned, overall_progress = formulation_progress(request.user, catalog)
    categories = {item.slug: item for item in catalog.categories}
    selected = _selection(
        definition["entries"], categories, filters, learned,
    )
    practice = filters.get("mode") == "practice"
    index = next(
        (
            i for i, entry in enumerate(selected)
            if entry.slug == filters.get("entry")
        ),
        0,
    )
    visible = selected[index:index + 1] if practice else selected
    sources = {}
    for key, prompt_id in Prompt.objects.filter(
        response__content_key__in={
            entry.source_key for entry in visible
        },
        response__is_active=True,
        is_active=True,
        theme__is_active=True,
        theme__task=task,
    ).order_by(
        "response_id", "number", "pk",
    ).values_list("response__content_key", "pk"):
        sources.setdefault(
            key,
            reverse(
                "study:response_detail",
                args=["ee", "tache-3", prompt_id],
            ),
        )
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
    browse_filters = {
        key: value for key, value in filters.items()
        if key not in {"mode", "entry"}
    }
    base_url = collection_url(kind, slug)
    language_bank = formulation_language_for(definition["category"])
    return render(request, "study/formulations.html", {
        "part": task.part,
        "task": task,
        "definition": definition,
        "filters": filters,
        "filter_fields": filters.items(),
        "rows": rows,
        "overall_progress": overall_progress,
        "progress": _progress(definition["entries"], learned),
        "result_count": len(selected),
        "practice": practice,
        "position": index + 1,
        "language_bank": language_bank,
        "language_bank_label": (
            "Verbes utiles" if definition["category"]
            and definition["category"].slug == "synthese"
            else "Vocabulaire utile"
        ),
        "language_bank_title": (
            "Verbes utiles pour présenter les documents"
            if definition["category"]
            and definition["category"].slug == "synthese"
            else f"Vocabulaire utile : {definition['title']}"
        ),
        "return_url": base_url,
        "browse_url": collection_url(kind, slug, browse_filters),
        "practice_url": collection_url(
            kind, slug, {**browse_filters, "mode": "practice"},
        ),
        "previous_url": collection_url(
            kind, slug, {**filters, "entry": selected[index - 1].slug},
        ) if practice and index else "",
        "next_url": collection_url(
            kind, slug, {**filters, "entry": selected[index + 1].slug},
        ) if practice and index + 1 < len(selected) else "",
    })


def _safe_return_path(value):
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return ""
    try:
        match = resolve(parsed.path)
    except Resolver404:
        return ""
    if match.url_name not in RETURN_ROUTES:
        return ""
    return parsed.path


@require_POST
def formulation_learned(request, slug):
    task = _route_task("ee", "tache-3", request=request)
    if not task.available:
        raise Http404
    catalog = get_ee_formulations()
    filters = _filters(request.POST, catalog)
    entry = next(
        (entry for entry in catalog.entries if entry.slug == slug),
        None,
    )
    if entry is None:
        raise Http404
    completed = request.POST.getlist("completed")
    if completed not in (["0"], ["1"]):
        return HttpResponseBadRequest("État de progression invalide.")
    lookup = {
        "user": request.user,
        "memory_number": 1,
        "question_key": entry.content_key,
    }
    if completed == ["1"]:
        MemoryQuestionProgress.objects.get_or_create(**lookup)
    else:
        MemoryQuestionProgress.objects.filter(**lookup).delete()
    destination = (
        _safe_return_path(request.POST.get("next", ""))
        or reverse("study:ee_formulations")
    )
    if filters:
        destination += "?" + urlencode(filters)
    return redirect(destination + "#formulation-" + entry.slug)
