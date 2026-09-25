"""Private, task-isolated learning state for EE formulation banks."""

from dataclasses import asdict
import hashlib
import re
import unicodedata

from django.db.models import Q

from .ee_formulations import get_ee_formulations
from .models import Annotation, MemoryQuestionProgress
from .progress import progress_summary


LANGUAGE_CONTENT_KEY_PREFIX = "formulation-language:ee3:v1:"
LANGUAGE_CONTENT_KEY_PREFIXES = {
    1: "formulation-language:ee1:v1:",
    3: LANGUAGE_CONTENT_KEY_PREFIX,
}
FORMULATION_SOURCE_KEY_RE = re.compile(
    r"^formulation:ee(?P<tache>[13]):v1:(?P<slug>[a-z0-9-]+)$"
)
FORMULATION_ENTRY_PATH_RE = re.compile(
    r"^/expression/ecrite/tache-(?P<tache>[13])/"
    r"formulations/fiches/(?P<slug>[a-z0-9-]+)/$"
)
FORMULATION_ENTRY_PATHS = {
    1: "/expression/ecrite/tache-1/formulations/fiches/{slug}/",
    3: "/expression/ecrite/tache-3/formulations/fiches/{slug}/",
}


def formulation_progress_states(user, catalogs):
    catalogs = tuple(catalogs)
    keys_by_tache = {
        catalog.tache: {entry.content_key for entry in catalog.entries}
        for catalog in catalogs
    }
    all_keys = set().union(*keys_by_tache.values()) if catalogs else set()
    learned_all = set(
        MemoryQuestionProgress.objects.filter(
            user=user, memory_number=1, question_key__in=all_keys,
        ).values_list("question_key", flat=True)
    )
    path_to_key = {
        FORMULATION_ENTRY_PATHS[catalog.tache].format(slug=entry.slug):
        entry.content_key
        for catalog in catalogs
        for entry in catalog.entries
    }
    activity_all = set()
    for source_key, source_path in Annotation.objects.filter(
        Q(source_key__in=all_keys) | Q(source_path__in=path_to_key),
        user=user,
    ).values_list("source_key", "source_path"):
        if source_key in all_keys:
            activity_all.add(source_key)
        elif source_path in path_to_key:
            activity_all.add(path_to_key[source_path])
    states = {}
    for tache, keys in keys_by_tache.items():
        learned = learned_all & keys
        started = learned | (activity_all & keys)
        states[tache] = (
            learned,
            started,
            progress_summary(
                total=len(keys),
                started=len(started),
                completed=len(learned),
            ),
        )
    return states


def formulation_progress_state(user, catalog=None, *, tache=3):
    catalog = catalog or get_ee_formulations(tache)
    return formulation_progress_states(user, (catalog,))[catalog.tache]


def formulation_progress(user, catalog=None, *, tache=3):
    learned, _started, summary = formulation_progress_state(
        user, catalog, tache=tache,
    )
    return learned, summary


def _entry_summary(entries, learned, started):
    keys = {entry.content_key for entry in entries}
    return progress_summary(
        total=len(keys),
        started=len(keys & started),
        completed=len(keys & learned),
    )


def formulation_entry_progress_payload(user, catalog, entry):
    learned, started, overall = formulation_progress_state(user, catalog)
    category_entries = tuple(
        item for item in catalog.entries
        if item.category == entry.category
    )
    essential_entries = tuple(
        item for item in catalog.entries if item.essential
    )
    status = (
        "done"
        if entry.content_key in learned
        else "active"
        if entry.content_key in started
        else "new"
    )
    return {
        "completed": entry.content_key in learned,
        "status": status,
        "label": {
            "done": "Apprise",
            "active": "En cours",
            "new": "À apprendre",
        }[status],
        "slug": entry.slug,
        "tache": catalog.tache,
        "overall": asdict(overall),
        "category": {
            "slug": entry.category,
            **asdict(_entry_summary(category_entries, learned, started)),
        },
        "essentials": asdict(
            _entry_summary(essential_entries, learned, started)
        ),
    }


def formulation_annotation_progress_payload(user, source_key, source_path):
    match = FORMULATION_SOURCE_KEY_RE.fullmatch(source_key or "")
    if match is None:
        match = FORMULATION_ENTRY_PATH_RE.fullmatch(
            (source_path or "").split("?", 1)[0]
        )
    if match is None:
        return {}
    tache = int(match.group("tache"))
    catalog = get_ee_formulations(tache)
    entry = next(
        (
            item for item in catalog.entries
            if item.slug == match.group("slug")
        ),
        None,
    )
    if entry is None:
        return {}
    return {
        "formulation_progress": formulation_entry_progress_payload(
            user, catalog, entry,
        )
    }


def formulation_language_item_id(category_slug, french):
    normalized = unicodedata.normalize(
        "NFC", " ".join(french.split()).casefold(),
    )
    return hashlib.sha256(
        f"{category_slug}\0{normalized}".encode("utf-8"),
    ).hexdigest()[:16]


def formulation_language_content_key(category_slug, french, *, tache=3):
    return (
        LANGUAGE_CONTENT_KEY_PREFIXES[tache]
        + category_slug
        + ":"
        + formulation_language_item_id(category_slug, french)
    )


def formulation_language_progress(user, category_slug, items, *, tache=3):
    keys = {
        formulation_language_content_key(
            category_slug, item.french, tache=tache,
        )
        for item in items
    }
    learned = set(
        MemoryQuestionProgress.objects.filter(
            user=user, memory_number=1, question_key__in=keys,
        ).values_list("question_key", flat=True)
    )
    return learned, progress_summary(
        total=len(keys), started=len(learned), completed=len(learned),
    )
