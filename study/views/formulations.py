"""Nested directory and optional, ungraded recall of reusable EE frames."""

import unicodedata
from dataclasses import asdict
from urllib.parse import urlencode, urlsplit

from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import Resolver404, resolve, reverse
from django.views.decorators.http import require_GET, require_POST

from ..content_loader import ee_writing_sujet_slug
from ..ee_formulation_language import formulation_language_for
from ..ee_formulation_vocabulary import formulation_vocabulary_for
from ..ee_formulations import get_ee_formulations
from ..formulation_progress import (
    formulation_entry_progress_payload,
    formulation_language_content_key,
    formulation_language_item_id,
    formulation_language_progress,
    formulation_progress_state,
)
from ..models import MemoryQuestionProgress, Prompt, WritingSujet
from ..progress import progress_summary
from .helpers import _route_task


FILTER_KEYS = ("q", "status", "mode", "entry")
LEGACY_FILTER_KEYS = (*FILTER_KEYS, "category", "theme", "essential")
ROUTES = {
    1: {
        "directory": "study:ee_tache_one_formulations",
        "essentials": "study:ee_tache_one_formulation_essentials",
        "function": "study:ee_tache_one_formulation_function",
        "theme": "study:ee_tache_one_formulation_theme",
        "search": "study:ee_tache_one_formulation_search",
        "language": "study:ee_tache_one_formulation_language",
        "language_progress": "study:ee_tache_one_formulation_language_progress",
        "entry": "study:ee_tache_one_formulation_entry",
        "progress": "study:ee_tache_one_formulation_progress",
    },
    3: {
        "directory": "study:ee_formulations",
        "essentials": "study:ee_formulation_essentials",
        "function": "study:ee_formulation_function",
        "theme": "study:ee_formulation_theme",
        "search": "study:ee_formulation_search",
        "language": "study:ee_formulation_language",
        "language_progress": "study:ee_formulation_language_progress",
        "entry": "study:ee_formulation_entry",
        "progress": "study:ee_formulation_progress",
    },
}


def _language_bank_for(category, *, tache):
    if category is None:
        return ()
    if tache == 1 and category.kind == "theme":
        return formulation_vocabulary_for(category.slug)
    if tache == 3:
        return formulation_language_for(category)
    return ()
LANGUAGE_ROLE_LABELS = {
    "vocabulary": "Vocabulaire courant",
    "reporting": "Présenter les documents",
    "notion": "Notions clés",
    "collocation": "Associations utiles",
    "benefit": "Bienfaits et avantages",
    "risk": "Limites et risques",
    "condition": "Conditions de réussite",
    "solution": "Solutions",
    "mechanism": "Mécanismes d’argumentation",
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
        "status": {"new", "active", "learned"},
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


def _progress(entries, learned, started):
    keys = {entry.content_key for entry in entries}
    completed = sum(entry.content_key in learned for entry in entries)
    return progress_summary(
        total=len(entries),
        started=len(keys & started),
        completed=completed,
    )


def _entry_status(entry, learned, started):
    if entry.content_key in learned:
        return "done"
    if entry.content_key in started:
        return "active"
    return "new"


def collection_url(kind, slug="", filters=None, *, tache=3):
    route = ROUTES[tache][kind]
    args = [slug] if slug else []
    url = reverse(route, args=args)
    return url + ("?" + urlencode(filters) if filters else "")


def _selection(entries, categories, filters, learned, started):
    query = _fold(filters.get("q", ""))
    result = []
    for entry in entries:
        is_learned = entry.content_key in learned
        is_started = entry.content_key in started
        if filters.get("status") == "learned" and not is_learned:
            continue
        if filters.get("status") == "active" and (
            is_learned or not is_started
        ):
            continue
        if filters.get("status") == "new" and is_started:
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


def _response_urls(task, source_keys, *, tache):
    if tache == 1:
        slug_by_key = {
            source_key: ee_writing_sujet_slug(source_key)
            for source_key in source_keys
        }
        sources = {}
        for sujet_id, slug in WritingSujet.objects.filter(
            task=task,
            slug__in=slug_by_key.values(),
            is_active=True,
        ).values_list("pk", "slug"):
            sources[slug] = reverse(
                "study:writing_sujet_detail",
                args=["ee", "tache-1", sujet_id],
            )
        return {
            source_key: sources.get(slug, "")
            for source_key, slug in slug_by_key.items()
        }
    sources = {}
    for key, prompt_id in Prompt.objects.filter(
        response__content_key__in=source_keys,
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
    return sources


def _source_urls(task, entries, *, tache):
    return _response_urls(task, {
        example.source_key
        for entry in entries
        for example in entry.examples
    }, tache=tache)


def _entry_row(entry, categories, learned, started, sources, *, tache):
    return {
        "entry": entry,
        "category": categories[entry.category],
        "learned": entry.content_key in learned,
        "status": _entry_status(entry, learned, started),
        "source_url": sources.get(entry.source_key, ""),
        "examples": tuple(
            {
                "content": example,
                "source_url": sources.get(example.source_key, ""),
                "source_label": (
                    "Réponse"
                    if tache == 1
                    else (
                        "Titre"
                        if example.source_field == "reformulation"
                        else (
                            "Partie 1"
                            if example.source_field == "position"
                            else "Partie 2"
                        )
                    )
                ),
            }
            for example in entry.examples
        ),
        "copy_id": "formulation-copy-" + entry.slug,
        "progress_url": reverse(
            ROUTES[tache]["progress"], args=[entry.slug],
        ),
    }


def _language_sections(
    language_bank, source_urls, category_slug, learned, *, tache,
):
    grouped = {role: [] for role in LANGUAGE_ROLE_LABELS}
    for item in language_bank:
        role = item.role or "reporting"
        item_id = formulation_language_item_id(
            category_slug, item.french,
        )
        content_key = formulation_language_content_key(
            category_slug, item.french, tache=tache,
        )
        grouped[role].append({
            "item": item,
            "item_id": item_id,
            "learned": content_key in learned,
            "progress_url": reverse(
                ROUTES[tache]["language_progress"],
                args=[category_slug, item_id],
            ),
            "examples": tuple(
                {
                    "text": example.text,
                    "sources": tuple(
                        {
                            "label": (
                                "Réponse"
                                if tache == 1
                                else (
                                    "Titre"
                                    if field == "reformulation"
                                    else (
                                        "Partie 1"
                                        if field == "position"
                                        else "Partie 2"
                                    )
                                )
                            ),
                            "url": source_urls.get(source_key, ""),
                        }
                        for source_key, field in example.provenance
                    ),
                }
                for example in item.examples
            ),
        })
    return tuple(
        {
            "role": role,
            "title": title,
            "items": grouped[role],
        }
        for role, title in LANGUAGE_ROLE_LABELS.items()
        if grouped[role]
    )


def _directory_item(
    category, entries, learned, started, *, kind, tache,
):
    url = collection_url(kind, category.slug, tache=tache)
    language_bank = _language_bank_for(category, tache=tache)
    return {
        "category": category,
        "count": len(entries),
        "completed": sum(entry.content_key in learned for entry in entries),
        "progress": _progress(entries, learned, started),
        "url": url,
        "reference_label": (
            "Verbes utiles" if category.slug == "synthese"
            else "Vocabulaire utile"
        ) if language_bank else "",
        "reference_url": (
            reverse(
                ROUTES[tache]["language"], args=[category.slug],
            ) if language_bank else ""
        ),
        "reference_count": len(language_bank),
        "topics": [
            {
                "slug": entry.slug,
                "label": entry.label,
                "french": entry.french,
                "url": reverse(
                    ROUTES[tache]["entry"], args=[entry.slug],
                ),
                "progress_url": reverse(
                    ROUTES[tache]["progress"], args=[entry.slug],
                ),
                "learned": entry.content_key in learned,
                "status": _entry_status(entry, learned, started),
                "essential": entry.essential,
            }
            for entry in entries
        ],
    }


def _legacy_destination(filters, catalog, *, tache):
    forwarded = {
        key: value for key, value in filters.items()
        if key in FILTER_KEYS
    }
    categories = {category.slug: category for category in catalog.categories}
    if filters.get("theme"):
        return collection_url(
            "theme", filters["theme"], forwarded, tache=tache,
        )
    if filters.get("category"):
        category = categories[filters["category"]]
        kind = "function" if category.kind == "function" else "theme"
        return collection_url(
            kind, category.slug, forwarded, tache=tache,
        )
    if filters.get("essential"):
        return collection_url("essentials", filters=forwarded, tache=tache)
    return collection_url("search", filters=forwarded, tache=tache)


@require_GET
def formulations(request, tache=3):
    task = _route_task("ee", f"tache-{tache}", request=request)
    if not task.available:
        raise Http404
    catalog = get_ee_formulations(tache)
    if request.GET:
        filters = _filters(request.GET, catalog, keys=LEGACY_FILTER_KEYS)
        return redirect(_legacy_destination(filters, catalog, tache=tache))

    learned, started, progress = formulation_progress_state(
        request.user, catalog,
    )
    function_items = []
    theme_items = []
    for category in catalog.categories:
        if category.kind == "function":
            entries = [
                entry for entry in catalog.entries
                if entry.category == category.slug
            ]
            if entries:
                function_items.append(
                    _directory_item(
                        category, entries, learned, started, kind="function",
                        tache=tache,
                    )
                )
        else:
            entries = [
                entry for entry in catalog.entries
                if entry.category == category.slug
            ]
            if entries:
                theme_items.append(
                    _directory_item(
                        category, entries, learned, started,
                        kind="theme", tache=tache,
                    )
                )
    return render(request, "study/formulation_directory.html", {
        "part": task.part,
        "task": task,
        "progress": progress,
        "return_url": reverse(ROUTES[tache]["directory"]),
        "directory_url": reverse(ROUTES[tache]["directory"]),
        "tache": tache,
        "tables": (
            {
                "slug": "functions",
                "title": "Fonctions d’écriture",
                "description": (
                    "Les formulations classées par étape de la réponse."
                ),
                "items": function_items,
                "progress": _progress(
                    [
                        entry for entry in catalog.entries
                        if entry.category in {
                            category.slug for category in catalog.categories
                            if category.kind == "function"
                        }
                    ],
                    learned,
                    started,
                ),
            },
            {
                "slug": "themes",
                "title": "Thèmes",
                "description": (
                    (
                        "Des formulations concrètes pour décrire, informer, "
                        "inviter, demander et conseiller selon chaque situation."
                    )
                    if tache == 1 else (
                        "Des arguments, bénéfices, limites et solutions prêts "
                        "à adapter aux sujets fréquents."
                    )
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
                    started,
                ),
            },
        ),
        "search_url": collection_url("search", tache=tache),
    })


def _collection_definition(catalog, kind, slug):
    categories = {category.slug: category for category in catalog.categories}
    if kind == "essentials":
        return {
            "title": "Les essentiels",
            "eyebrow": "Parcours recommandé",
            "description": (
                (
                    "Les formulations indispensables pour ouvrir un message, "
                    "annoncer son objectif, donner des informations précises, "
                    "formuler une demande et conclure."
                )
                if catalog.tache == 1 else (
                    "Les formulations indispensables pour synthétiser, prendre "
                    "position, développer deux raisons et conclure."
                )
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
        "eyebrow": (
            "Essentiels · Fonction d’écriture"
            if kind == "function"
            else (
                "Thèmes · Messages à adapter"
                if catalog.tache == 1
                else "Thèmes · Arguments à adapter"
            )
        ),
        "description": category.description,
        "entries": [
            entry for entry in catalog.entries
            if entry.category == category.slug
        ],
        "category": category,
    }


@require_GET
def formulation_collection(request, kind, slug="", tache=3):
    task = _route_task("ee", f"tache-{tache}", request=request)
    if not task.available:
        raise Http404
    catalog = get_ee_formulations(tache)
    definition = _collection_definition(catalog, kind, slug)
    filters = _filters(request.GET, catalog)
    learned, started, overall_progress = formulation_progress_state(
        request.user, catalog,
    )
    categories = {item.slug: item for item in catalog.categories}
    selected = _selection(
        definition["entries"], categories, filters, learned, started,
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
    sources = _source_urls(task, visible, tache=tache)
    rows = [
        _entry_row(
            entry, categories, learned, started, sources, tache=tache,
        )
        for entry in visible
    ]
    browse_filters = {
        key: value for key, value in filters.items()
        if key not in {"mode", "entry"}
    }
    base_url = collection_url(kind, slug, tache=tache)
    language_bank = _language_bank_for(
        definition["category"], tache=tache,
    )
    return render(request, "study/formulations.html", {
        "part": task.part,
        "task": task,
        "annotation_task": task,
        "tache": tache,
        "directory_url": reverse(ROUTES[tache]["directory"]),
        "definition": definition,
        "filters": filters,
        "filter_fields": filters.items(),
        "rows": rows,
        "overall_progress": overall_progress,
        "progress": _progress(definition["entries"], learned, started),
        "progress_scope": (
            definition["category"].slug
            if definition["category"]
            else ("essentials" if kind == "essentials" else "overall")
        ),
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
        "browse_url": collection_url(
            kind, slug, browse_filters, tache=tache,
        ),
        "practice_url": collection_url(
            kind, slug, {**browse_filters, "mode": "practice"}, tache=tache,
        ),
        "previous_url": collection_url(
            kind, slug, {**filters, "entry": selected[index - 1].slug},
            tache=tache,
        ) if practice and index else "",
        "next_url": collection_url(
            kind, slug, {**filters, "entry": selected[index + 1].slug},
            tache=tache,
        ) if practice and index + 1 < len(selected) else "",
    })


@require_GET
def formulation_entry(request, slug, tache=3):
    task = _route_task("ee", f"tache-{tache}", request=request)
    if not task.available:
        raise Http404
    catalog = get_ee_formulations(tache)
    entry = next(
        (item for item in catalog.entries if item.slug == slug),
        None,
    )
    if entry is None:
        raise Http404
    categories = {item.slug: item for item in catalog.categories}
    category = categories[entry.category]
    siblings = [
        item for item in catalog.entries
        if item.category == category.slug
    ]
    position = siblings.index(entry)
    learned, started, overall_progress = formulation_progress_state(
        request.user, catalog,
    )
    row = _entry_row(
        entry,
        categories,
        learned,
        started,
        _source_urls(task, [entry], tache=tache),
        tache=tache,
    )
    kind = "function" if category.kind == "function" else "theme"
    return render(request, "study/formulation_entry.html", {
        "part": task.part,
        "task": task,
        "annotation_task": task,
        "tache": tache,
        "directory_url": reverse(ROUTES[tache]["directory"]),
        "row": row,
        "category": category,
        "overall_progress": overall_progress,
        "progress": _progress(siblings, learned, started),
        "position": position + 1,
        "total": len(siblings),
        "return_url": request.path,
        "filter_fields": (),
        "back_url": collection_url(kind, category.slug, tache=tache),
        "previous_entry": siblings[position - 1] if position else None,
        "previous_url": reverse(
            ROUTES[tache]["entry"],
            args=[siblings[position - 1].slug],
        ) if position else "",
        "next_entry": (
            siblings[position + 1] if position + 1 < len(siblings)
            else None
        ),
        "next_url": reverse(
            ROUTES[tache]["entry"],
            args=[siblings[position + 1].slug],
        ) if position + 1 < len(siblings) else "",
    })


@require_GET
def formulation_language_reference(request, slug, tache=3):
    task = _route_task("ee", f"tache-{tache}", request=request)
    if not task.available:
        raise Http404
    catalog = get_ee_formulations(tache)
    category = next(
        (item for item in catalog.categories if item.slug == slug),
        None,
    )
    language_bank = _language_bank_for(category, tache=tache)
    if category is None or not language_bank:
        raise Http404
    learned, language_progress = formulation_language_progress(
        request.user, category.slug, language_bank, tache=tache,
    )
    source_urls = _response_urls(task, {
        source_key
        for item in language_bank
        for example in item.examples
        for source_key, _field in example.provenance
    }, tache=tache)
    return render(request, "study/formulation_language.html", {
        "part": task.part,
        "task": task,
        "tache": tache,
        "directory_url": reverse(ROUTES[tache]["directory"]),
        "category": category,
        "language_bank": language_bank,
        "language_sections": _language_sections(
            language_bank,
            source_urls,
            category.slug,
            learned,
            tache=tache,
        ),
        "language_progress": language_progress,
        "example_count": sum(
            len(item.examples) for item in language_bank
        ),
        "back_url": (
            reverse(ROUTES[tache]["directory"])
            + "#formulation-group-"
            + category.slug
        ),
        "reference_title": (
            "Verbes utiles pour présenter les documents"
            if category.slug == "synthese"
            else f"Vocabulaire utile : {category.title}"
        ),
    })


@require_POST
def formulation_language_learned(request, slug, item_id, tache=3):
    task = _route_task("ee", f"tache-{tache}", request=request)
    if not task.available:
        raise Http404
    catalog = get_ee_formulations(tache)
    category = next(
        (item for item in catalog.categories if item.slug == slug),
        None,
    )
    language_bank = _language_bank_for(category, tache=tache)
    if category is None or not language_bank:
        raise Http404
    item = next(
        (
            item for item in language_bank
            if formulation_language_item_id(
                category.slug, item.french,
            ) == item_id
        ),
        None,
    )
    if item is None:
        raise Http404
    completed = request.POST.getlist("completed")
    if completed not in (["0"], ["1"]):
        if request.headers.get("X-Requested-With") == "fetch":
            return JsonResponse(
                {"error": "État de progression invalide."},
                status=400,
            )
        return HttpResponseBadRequest("État de progression invalide.")
    lookup = {
        "user": request.user,
        "memory_number": 1,
        "question_key": formulation_language_content_key(
            category.slug, item.french, tache=tache,
        ),
    }
    if completed == ["1"]:
        MemoryQuestionProgress.objects.get_or_create(**lookup)
    else:
        MemoryQuestionProgress.objects.filter(**lookup).delete()
    if request.headers.get("X-Requested-With") == "fetch":
        learned, progress = formulation_language_progress(
            request.user,
            category.slug,
            language_bank,
            tache=tache,
        )
        return JsonResponse({
            "completed": lookup["question_key"] in learned,
            "item_id": item_id,
            "progress": asdict(progress),
        })
    return redirect(
        reverse(ROUTES[tache]["language"], args=[category.slug])
        + "#vocabulaire-"
        + item_id
    )


def _safe_return_path(value, *, tache):
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return ""
    try:
        match = resolve(parsed.path)
    except Resolver404:
        return ""
    if match.url_name not in {
        route.removeprefix("study:")
        for key, route in ROUTES[tache].items()
        if key not in {"progress", "language_progress"}
    }:
        return ""
    return parsed.path


@require_POST
def formulation_learned(request, slug, tache=3):
    task = _route_task("ee", f"tache-{tache}", request=request)
    if not task.available:
        raise Http404
    catalog = get_ee_formulations(tache)
    filters = _filters(request.POST, catalog)
    entry = next(
        (entry for entry in catalog.entries if entry.slug == slug),
        None,
    )
    if entry is None:
        raise Http404
    completed = request.POST.getlist("completed")
    if completed not in (["0"], ["1"]):
        if request.headers.get("X-Requested-With") == "fetch":
            return JsonResponse(
                {"error": "État de progression invalide."},
                status=400,
            )
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
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse(
            formulation_entry_progress_payload(
                request.user, catalog, entry,
            )
        )
    destination = (
        _safe_return_path(request.POST.get("next", ""), tache=tache)
        or reverse(ROUTES[tache]["directory"])
    )
    if filters:
        destination += "?" + urlencode(filters)
    return redirect(destination + "#formulation-" + entry.slug)
