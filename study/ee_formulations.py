"""Read the EE3 formulation curriculum without importing models or learner data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path

from .content_loader import (
    EE_TACHE_THREE_DIR,
    load_ee_subject_themes,
    parse_ee_tache_three_responses,
)

FORMULATIONS_PATH = EE_TACHE_THREE_DIR / "formulations.json"
CONTENT_KEY_PREFIX = "formulation:ee3:v1:"
FUNCTION_CATEGORIES = (
    "titres",
    "synthese",
    "affirmation",
    "opposition",
    "concession",
    "conditions",
    "arguments",
    "exemples",
    "consequences",
    "conclusions",
)
EXAMPLE_SOURCE_FIELDS = ("reformulation", "position", "position_claire")
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


@dataclass(frozen=True)
class FormulationCategory:
    slug: str
    kind: str
    title: str
    description: str
    icon: str


@dataclass(frozen=True)
class FormulationExample:
    french: str
    english: str
    source_key: str
    source_field: str


@dataclass(frozen=True)
class FormulationEntry:
    slug: str
    category: str
    label: str
    french: str
    english: str
    usage: str
    grammar: str
    example: str
    example_english: str
    source_key: str
    transfer_prompt: str
    essential: bool
    themes: tuple[str, ...]
    examples: tuple[FormulationExample, ...] = ()

    def __post_init__(self) -> None:
        if not self.examples:
            object.__setattr__(
                self,
                "examples",
                (
                    FormulationExample(
                        french=self.example,
                        english=self.example_english,
                        source_key=self.source_key,
                        source_field="position_claire",
                    ),
                ),
            )
        elif (
            self.example != self.examples[0].french
            or self.example_english != self.examples[0].english
            or self.source_key != self.examples[0].source_key
        ):
            raise ValueError("Compatibility fields must match examples[0]")

    @property
    def content_key(self) -> str:
        return CONTENT_KEY_PREFIX + self.slug

    @property
    def primary_example(self) -> FormulationExample:
        return self.examples[0]


@dataclass(frozen=True)
class FormulationCatalog:
    categories: tuple[FormulationCategory, ...]
    entries: tuple[FormulationEntry, ...]
    source_response_count: int

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def category_count(self) -> int:
        return len(self.categories)


def _text(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location}: expected a non-empty string")
    return value


def _slug(value: object, location: str) -> str:
    value = _text(value, location)
    if not _SLUG.fullmatch(value):
        raise ValueError(f"{location}: expected a lowercase hyphenated slug")
    return value


def _record(value: object, expected: set[str], location: str) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{location}: expected exactly {sorted(expected)}")
    return value


def _whitespace(text: str) -> str:
    return " ".join(text.split())


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def load_ee_formulations(path: Path = FORMULATIONS_PATH) -> FormulationCatalog:
    """Validate structure, coverage and quotation provenance, not teaching semantics.

    The French frames and translations are editorial adaptations. Every example
    must quote its named field in an effective model, with whitespace
    normalization alone.
    """
    payload = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object
    )
    _record(
        payload,
        {"version", "source_response_count", "categories", "entries"},
        str(path),
    )
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise ValueError("Formulations require version 1")
    for name in ("categories", "entries"):
        if not isinstance(payload[name], list) or not payload[name]:
            raise ValueError(f"{name}: expected a non-empty list")

    themes, theme_by_key = load_ee_subject_themes(3)
    theme_slugs = {theme.slug for theme in themes}
    responses = {
        response.content_key: response
        for response in parse_ee_tache_three_responses()
    }
    count = payload["source_response_count"]
    if type(count) is not int or count != len(responses):
        raise ValueError("source_response_count must match the effective corpus")

    categories = []
    category_by_slug = {}
    category_fields = {field.name for field in fields(FormulationCategory)}
    for index, raw in enumerate(payload["categories"]):
        location = f"categories[{index}]"
        row = _record(raw, category_fields, location)
        for name in category_fields:
            _text(row[name], f"{location}.{name}")
        slug = _slug(row["slug"], f"{location}.slug")
        _slug(row["icon"], f"{location}.icon")
        if slug in category_by_slug:
            raise ValueError(f"Duplicate category: {slug}")
        if row["kind"] not in ("function", "theme"):
            raise ValueError(f"{location}.kind: expected function or theme")
        allowed = FUNCTION_CATEGORIES if row["kind"] == "function" else theme_slugs
        if slug not in allowed:
            raise ValueError(f"{location}: unknown {row['kind']} category {slug}")
        category = FormulationCategory(**row)
        categories.append(category)
        category_by_slug[slug] = category
    if set(category_by_slug) != set(FUNCTION_CATEGORIES) | theme_slugs:
        raise ValueError("Categories must cover all functions and subject themes")

    entries = []
    entry_slugs = set()
    frame_texts = set()
    used_categories = set()
    used_sources = set()
    essential_categories = set()
    entry_fields = {field.name for field in fields(FormulationEntry)}
    compatibility_fields = {"example", "example_english", "source_key"}
    text_fields = entry_fields - {"essential", "themes", "examples"}
    example_fields = {field.name for field in fields(FormulationExample)}
    for index, raw in enumerate(payload["entries"]):
        location = f"entries[{index}]"
        row = _record(raw, entry_fields, location)
        for name in text_fields:
            _text(row[name], f"{location}.{name}")
        slug = _slug(row["slug"], f"{location}.slug")
        if len(CONTENT_KEY_PREFIX + slug) > 96:
            raise ValueError(f"{location}: content_key exceeds 96 characters")
        if slug in entry_slugs:
            raise ValueError(f"Duplicate entry: {slug}")
        entry_slugs.add(slug)
        frame = _whitespace(row["french"]).casefold()
        if frame in frame_texts:
            raise ValueError(f"Duplicate frame text: {slug}")
        frame_texts.add(frame)
        # Slots are named teaching cues, never empty or nested bracket markers.
        without_slots = re.sub(r"\[[^\[\]]+\]", "", row["french"])
        slots = re.findall(r"\[([^\[\]]*)\]", row["french"])
        if "[" in without_slots or "]" in without_slots or any(
            not slot.strip() or not any(char.isalpha() for char in slot)
            for slot in slots
        ):
            raise ValueError(f"{location}: malformed or unnamed slot")
        category = category_by_slug.get(row["category"])
        if category is None:
            raise ValueError(f"{location}: unknown category")
        if type(row["essential"]) is not bool:
            raise ValueError(f"{location}.essential: expected a boolean")
        tags = row["themes"]
        if not isinstance(tags, list) or any(
            not isinstance(tag, str) or tag not in theme_slugs for tag in tags
        ):
            raise ValueError(f"{location}.themes: expected known theme slugs")
        if len(set(tags)) != len(tags):
            raise ValueError(f"{location}.themes: duplicate theme")
        raw_examples = row["examples"]
        if not isinstance(raw_examples, list) or not raw_examples:
            raise ValueError(f"{location}.examples: expected a non-empty list")
        parsed_examples = []
        normalized_examples = set()
        for example_index, raw_example in enumerate(raw_examples):
            example_location = f"{location}.examples[{example_index}]"
            example_row = _record(raw_example, example_fields, example_location)
            for name in example_fields:
                _text(example_row[name], f"{example_location}.{name}")
            response = responses.get(example_row["source_key"])
            if response is None:
                raise ValueError(
                    f"{example_location}: source_key is not an effective response"
                )
            source_field = example_row["source_field"]
            if source_field not in EXAMPLE_SOURCE_FIELDS:
                raise ValueError(
                    f"{example_location}.source_field: expected one of "
                    f"{EXAMPLE_SOURCE_FIELDS}"
                )
            example = _whitespace(example_row["french"])
            normalized = example.casefold()
            if normalized in normalized_examples:
                raise ValueError(f"{location}: duplicate normalized example")
            normalized_examples.add(normalized)
            if example not in _whitespace(getattr(response, source_field)):
                raise ValueError(
                    f"{example_location}: example is not verbatim evidence "
                    f"from {source_field}"
                )
            parsed_examples.append(FormulationExample(**example_row))
        primary = parsed_examples[0]
        if (
            row["example"] != primary.french
            or row["example_english"] != primary.english
            or row["source_key"] != primary.source_key
        ):
            raise ValueError(
                f"{location}: compatibility example fields must match "
                "examples[0]"
            )
        if category.kind == "theme" and category.slug not in tags:
            raise ValueError(f"{location}: theme category must occur in themes")
        if tags and theme_by_key[primary.source_key] not in tags:
            raise ValueError(f"{location}: themes must include the source theme")
        entries.append(
            FormulationEntry(
                **{
                    key: value
                    for key, value in row.items()
                    if key not in {"themes", "examples"}
                },
                themes=tuple(tags),
                examples=tuple(parsed_examples),
            )
        )
        used_categories.add(category.slug)
        used_sources.update(example.source_key for example in parsed_examples)
        if row["essential"]:
            essential_categories.add(category.slug)
    if used_categories != set(category_by_slug):
        raise ValueError("Every category must contain an entry")
    if used_sources != set(responses):
        missing = sorted(set(responses) - used_sources)
        raise ValueError(f"Every effective response must ground an entry; missing {missing}")
    if not set(FUNCTION_CATEGORIES) <= essential_categories:
        raise ValueError("Essentials must cover the complete function pipeline")
    return FormulationCatalog(tuple(categories), tuple(entries), count)


@lru_cache(maxsize=1)
def get_ee_formulations() -> FormulationCatalog:
    return load_ee_formulations()
