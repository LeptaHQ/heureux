"""Strict, response-grounded vocabulary references for EE Tâche 1 themes."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from .content_loader import EE_TACHE_DIRS, load_ee_subject_themes, load_ee_writing_categories
from .ee_formulation_language import (
    FormulationLanguageExample,
    FormulationLanguageItem,
)
from .ee_formulations import _slug, _text, _unique_json_object, _whitespace


VOCABULARY_PATH = EE_TACHE_DIRS[1] / "formulation_vocabulary.json"


def load_ee_formulation_vocabulary(
    path: Path | None = None,
) -> MappingProxyType:
    path = VOCABULARY_PATH if path is None else path
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_unique_json_object,
    )
    if set(payload) != {"version", "themes"}:
        raise ValueError(f"{path}: expected version and themes")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("EE1 formulation vocabulary requires version 1")
    if not isinstance(payload["themes"], list) or not payload["themes"]:
        raise ValueError("themes: expected a non-empty list")

    themes, source_theme_by_key = load_ee_subject_themes(1)
    expected_theme_slugs = [theme.slug for theme in themes]
    responses = {
        sujet.source_key: sujet.versions[0]
        for category in load_ee_writing_categories(1)
        for sujet in category.sujets
        if sujet.versions
    }
    result = {}
    entry_slugs = set()
    terms = set()
    for theme_index, raw_theme in enumerate(payload["themes"]):
        location = f"themes[{theme_index}]"
        if not isinstance(raw_theme, dict) or set(raw_theme) != {
            "slug", "entries",
        }:
            raise ValueError(f"{location}: expected slug and entries")
        theme_slug = _slug(raw_theme["slug"], f"{location}.slug")
        if theme_index >= len(expected_theme_slugs) or (
            theme_slug != expected_theme_slugs[theme_index]
        ):
            raise ValueError("Vocabulary themes must match the EE1 theme order")
        raw_entries = raw_theme["entries"]
        if not isinstance(raw_entries, list) or not raw_entries:
            raise ValueError(f"{location}.entries: expected a non-empty list")
        items = []
        for entry_index, raw_entry in enumerate(raw_entries):
            entry_location = f"{location}.entries[{entry_index}]"
            if not isinstance(raw_entry, dict) or set(raw_entry) != {
                "slug", "term", "meaning", "usage", "examples",
            }:
                raise ValueError(
                    f"{entry_location}: unexpected vocabulary fields"
                )
            slug = _slug(raw_entry["slug"], f"{entry_location}.slug")
            if slug in entry_slugs:
                raise ValueError(f"Duplicate vocabulary slug: {slug}")
            entry_slugs.add(slug)
            for name in ("term", "meaning", "usage"):
                _text(raw_entry[name], f"{entry_location}.{name}")
            normalized_term = _whitespace(raw_entry["term"]).casefold()
            if normalized_term in terms:
                raise ValueError(
                    f"Duplicate vocabulary term: {raw_entry['term']}"
                )
            terms.add(normalized_term)
            raw_examples = raw_entry["examples"]
            if not isinstance(raw_examples, list) or not raw_examples:
                raise ValueError(
                    f"{entry_location}.examples: expected a non-empty list"
                )
            examples = []
            seen_examples = set()
            for example_index, raw_example in enumerate(raw_examples):
                example_location = (
                    f"{entry_location}.examples[{example_index}]"
                )
                if not isinstance(raw_example, dict) or set(raw_example) != {
                    "french", "english", "source_key", "source_field",
                }:
                    raise ValueError(
                        f"{example_location}: unexpected example fields"
                    )
                for name in raw_example:
                    _text(raw_example[name], f"{example_location}.{name}")
                if raw_example["source_field"] != "body":
                    raise ValueError(
                        f"{example_location}.source_field: expected body"
                    )
                response = responses.get(raw_example["source_key"])
                if response is None:
                    raise ValueError(
                        f"{example_location}: unknown effective response"
                    )
                if source_theme_by_key[raw_example["source_key"]] != theme_slug:
                    raise ValueError(
                        f"{example_location}: source belongs to another theme"
                    )
                french = _whitespace(raw_example["french"])
                normalized_example = french.casefold()
                if normalized_example in seen_examples:
                    raise ValueError(
                        f"{entry_location}: duplicate example"
                    )
                seen_examples.add(normalized_example)
                if french not in _whitespace(response.body):
                    raise ValueError(
                        f"{example_location}: example is not verbatim evidence"
                    )
                if normalized_term not in normalized_example:
                    raise ValueError(
                        f"{example_location}: example does not contain term"
                    )
                examples.append(
                    FormulationLanguageExample(
                        raw_example["french"],
                        ((raw_example["source_key"], "body"),),
                    )
                )
            items.append(
                FormulationLanguageItem(
                    french=raw_entry["term"],
                    english=raw_entry["meaning"],
                    examples=tuple(examples),
                    role="vocabulary",
                    usage=raw_entry["usage"],
                )
            )
        result[theme_slug] = tuple(items)
    if list(result) != expected_theme_slugs:
        raise ValueError("Vocabulary must cover every EE1 theme exactly once")
    return MappingProxyType(result)


@lru_cache(maxsize=1)
def get_ee_formulation_vocabulary() -> MappingProxyType:
    return load_ee_formulation_vocabulary()


def formulation_vocabulary_for(theme_slug: str):
    return get_ee_formulation_vocabulary().get(theme_slug, ())
