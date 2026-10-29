"""Exact-text, public-only English question translations prepared with DeepL."""

from functools import lru_cache
import hashlib
import json
import logging
from pathlib import Path

from django.conf import settings

from . import content_loader


THEMES = frozenset({
    "arrivee", "logement", "vie-quartier", "travail", "ecole-etudes",
    "sorties-spectacles", "garde-enfants-animaux", "benevolat-associations",
    "hebergements-touristiques",
})
DEFAULT_PATH = content_loader.QUESTION_BANK_DIR / "translations" / "questions.en.json"
logger = logging.getLogger(__name__)


def translation_path():
    return Path(getattr(settings, "EO2_QUESTION_TRANSLATIONS_PATH", DEFAULT_PATH))


def fingerprint(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scoped_dialogues():
    from . import catalogue

    _, themes = catalogue.tache_two_subject_themes()
    rows = {}
    for key, dialogue in catalogue.tache_two_dialogues().items():
        if themes[key] in THEMES:
            rows.setdefault(dialogue.group, dialogue)
    return rows


def empty_manifest():
    return {
        "version": 1, "provider": "deepl", "source_language": "FR",
        "target_language": settings.DEEPL_TARGET_LANG, "generated_at": None, "groups": {},
    }


def validate_manifest(value):
    if (
        not isinstance(value, dict) or value.get("version") != 1
        or value.get("provider") != "deepl" or value.get("source_language") != "FR"
        or value.get("target_language") not in {"EN-GB", "EN-US"}
        or not isinstance(value.get("groups"), dict)
    ):
        raise ValueError("Invalid EO2 DeepL translation manifest.")
    allowed = scoped_dialogues()
    for group, rows in value["groups"].items():
        if group not in allowed or not isinstance(rows, dict):
            raise ValueError("EO2 translations contain an unsupported group.")
        for digest, row in rows.items():
            if (
                not isinstance(row, dict) or not isinstance(row.get("french"), str)
                or not isinstance(row.get("english"), str)
                or fingerprint(row["french"]) != digest
                or not row["english"].strip().endswith("?") or len(row["english"]) > 1200
            ):
                raise ValueError("Invalid or mismatched EO2 question translation.")
            if "deepl_english" in row and (
                not isinstance(row["deepl_english"], str)
                or not row["deepl_english"].strip().endswith("?")
                or not isinstance(row.get("review_note"), str) or not row["review_note"].strip()
            ):
                raise ValueError("Reviewed EO2 translations must retain their DeepL original and review note.")
    return value


@lru_cache(maxsize=8)
def _read_manifest(path, modified, size):
    return validate_manifest(json.loads(Path(path).read_text(encoding="utf-8")))


def manifest():
    path = translation_path()
    stat = path.stat()
    return _read_manifest(str(path), stat.st_mtime_ns, stat.st_size)


def language_presentation(dialogue, questions):
    if dialogue is None or dialogue.group not in scoped_dialogues():
        return None
    try:
        saved = manifest()
    except (OSError, ValueError):
        logger.error("EO2 saved translations are invalid or inaccessible.", exc_info=True)
        return {
            "ready": False, "available": 0, "total": len(questions),
            "english_lang": "en", "error": True,
        }
    translations = saved["groups"].get(dialogue.group, {})
    available = 0
    for question in questions:
        row = translations.get(fingerprint(question["text"]))
        question["english"] = row["english"].strip() if row else ""
        available += bool(question["english"])
    return {
        "ready": bool(questions) and available == len(questions),
        "available": available, "total": len(questions),
        "english_lang": saved["target_language"].lower(),
    }
