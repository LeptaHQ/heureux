"""Private, task-isolated learning state for EE formulation banks."""

import hashlib
import unicodedata

from .ee_formulations import get_ee_formulations
from .models import MemoryQuestionProgress
from .progress import progress_summary


LANGUAGE_CONTENT_KEY_PREFIX = "formulation-language:ee3:v1:"
LANGUAGE_CONTENT_KEY_PREFIXES = {
    1: "formulation-language:ee1:v1:",
    3: LANGUAGE_CONTENT_KEY_PREFIX,
}


def formulation_progress(user, catalog=None, *, tache=3):
    catalog = catalog or get_ee_formulations(tache)
    keys = {entry.content_key for entry in catalog.entries}
    learned = set(
        MemoryQuestionProgress.objects.filter(
            user=user, memory_number=1, question_key__in=keys,
        ).values_list("question_key", flat=True)
    )
    return learned, progress_summary(
        total=len(keys), started=len(learned), completed=len(learned),
    )


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
