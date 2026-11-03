"""Cached DeepL glosses for exact public EO3 response text."""

from functools import lru_cache
import hashlib
import json
import logging
from pathlib import Path

from django.conf import settings

from . import content_loader


DEFAULT_PATH = content_loader.CONTENT_DIR / "tache_3" / "translations" / "responses.en.json"
ARGUMENT_FIELDS = ("idea", "developpement", "exemple", "consequence")
logger = logging.getLogger(__name__)


def translation_path():
    return Path(getattr(settings, "EO3_RESPONSE_TRANSLATIONS_PATH", DEFAULT_PATH))


def fingerprint(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scoped_models():
    from . import catalogue

    return catalogue.tache_three_models()


def model_theme(model):
    return model.group.removeprefix("eo/tache-3/").rsplit("-p", 1)[0]


def response_fields(response, identities=None):
    fields = {"introduction": response.position_claire}
    for index, argument in enumerate(response.arguments):
        identity = identities[index] if identities is not None else getattr(
            argument, "annotation_id", argument.order,
        )
        for field in ARGUMENT_FIELDS:
            fields[f"argument-{identity}-{field}"] = getattr(argument, field)
    fields.update(nuance=response.nuance, conclusion=response.conclusion)
    return {key: text for key, text in fields.items() if text.strip()}


def public_fields(model):
    return response_fields(model.response, model.argument_ids)


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
        raise ValueError("Invalid EO3 DeepL translation manifest.")
    allowed = scoped_models()
    for group, rows in value["groups"].items():
        if group not in allowed or not isinstance(rows, dict):
            raise ValueError("EO3 translations contain an unsupported group.")
        for digest, row in rows.items():
            if (
                not isinstance(row, dict) or not isinstance(row.get("french"), str)
                or not row["french"].strip() or fingerprint(row["french"]) != digest
                or not isinstance(row.get("english"), str) or not row["english"].strip()
                or len(row["english"]) > 20000
            ):
                raise ValueError("Invalid or mismatched EO3 response translation.")
            if "deepl_english" in row and (
                not isinstance(row["deepl_english"], str) or not row["deepl_english"].strip()
                or not isinstance(row.get("review_note"), str) or not row["review_note"].strip()
            ):
                raise ValueError("Reviewed EO3 translations must retain their DeepL original and review note.")
    return value


@lru_cache(maxsize=8)
def _read_manifest(path, modified, size):
    return validate_manifest(json.loads(Path(path).read_text(encoding="utf-8")))


def manifest():
    path = translation_path()
    stat = path.stat()
    return _read_manifest(str(path), stat.st_mtime_ns, stat.st_size)


def language_presentation(model, response, arguments):
    if model is None:
        return None
    fields = response_fields(response, tuple(
        getattr(argument, "annotation_id", argument.order) for argument in arguments
    ))
    try:
        saved = manifest()
    except (OSError, ValueError):
        logger.error("EO3 saved translations are invalid or inaccessible.", exc_info=True)
        return {
            "ready": False, "available": 0, "total": len(fields),
            "fields": {}, "english_lang": "en", "error": True,
        }
    rows = saved["groups"].get(model.group, {})
    translated = {}
    for field, text in fields.items():
        row = rows.get(fingerprint(text))
        translated[field] = row["english"].strip() if row else ""
    available = sum(bool(text) for text in translated.values())
    return {
        "ready": bool(fields) and available == len(fields),
        "available": available, "total": len(fields), "fields": translated,
        "english_lang": saved["target_language"].lower(), "error": False,
    }
