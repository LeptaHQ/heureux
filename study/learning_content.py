"""Load and validate the source-controlled Learn curriculum."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Tuple


LEARNING_CONTENT_PATH = (
    Path(__file__).resolve().parent / "content" / "learning" / "curriculum.json"
)

LEARNING_LEVELS = {"Fondamental", "Intermédiaire", "Avancé"}
LEARNING_SOURCE_TYPES = {"pdf", "notion", "mixed", "editorial-gap-fill"}
LEARNING_VOCABULARY_KINDS = {"noun", "verb", "adjective", "expression"}
LEARNING_VOCABULARY_LABELS = {
    "noun": "Nom",
    "verb": "Verbe",
    "adjective": "Adjectif",
    "expression": "Expression",
}
LEARNING_ICONS = {
    "book-open",
    "compass",
    "graduation-cap",
    "messages",
    "pen-line",
    "scale",
    "sparkles",
    "target",
}
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
NOUN_ARTICLE_RE = re.compile(
    r"^(?:(?:un|une|le|la|les|des)\s+|l['’])",
    re.IGNORECASE,
)
NOUN_GENDER_RE = re.compile(
    r"\((?:m\.|f\.|m\./f\.|m\. pl\.|f\. pl\.)\)$",
    re.IGNORECASE,
)
FORBIDDEN_LEARNING_COPY = (
    "on retrouve «",
    "dans cette leçon, le groupe «",
    "reinforces the target vocabulary item",
    "the first model shows",
    "practical step:",
    "apply the choice in a complete sentence",
)


@dataclass(frozen=True)
class LearningExample:
    french: str
    english: str
    note: str


@dataclass(frozen=True)
class LearningMistake:
    avoid: str
    prefer: str
    why: str


@dataclass(frozen=True)
class LearningSection:
    id: str
    title: str
    paragraphs: Tuple[str, ...]
    points: Tuple[str, ...]
    examples: Tuple[LearningExample, ...]
    mistakes: Tuple[LearningMistake, ...]


@dataclass(frozen=True)
class LearningVocabulary:
    kind: str
    french: str
    english: str
    example: str
    note: str

    @property
    def kind_label(self) -> str:
        return LEARNING_VOCABULARY_LABELS[self.kind]


@dataclass(frozen=True)
class LearningPractice:
    prompt: str
    hint: str
    answer: str


@dataclass(frozen=True)
class LearningLesson:
    id: str
    slug: str
    title: str
    summary: str
    level: str
    duration_minutes: int
    source_type: str
    sources: Tuple[str, ...]
    objectives: Tuple[str, ...]
    sections: Tuple[LearningSection, ...]
    vocabulary: Tuple[LearningVocabulary, ...]
    practice: Tuple[LearningPractice, ...]
    takeaways: Tuple[str, ...]
    keywords: Tuple[str, ...]

    @property
    def searchable_text(self) -> str:
        return " ".join(
            (self.title, self.summary, self.level, *self.keywords)
        )


@dataclass(frozen=True)
class LearningModule:
    id: str
    slug: str
    title: str
    description: str
    icon: str
    color: str
    order: int
    lessons: Tuple[LearningLesson, ...]


@dataclass(frozen=True)
class LearningCatalog:
    title: str
    description: str
    modules: Tuple[LearningModule, ...]

    @property
    def lessons(self) -> Tuple[LearningLesson, ...]:
        return tuple(
            lesson
            for module in self.modules
            for lesson in module.lessons
        )

    def lesson_by_slug(
        self,
        lesson_slug: str,
    ) -> tuple[LearningModule, LearningLesson] | None:
        for module in self.modules:
            for lesson in module.lessons:
                if lesson.slug == lesson_slug:
                    return module, lesson
        return None


def _object(value, location: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be an object")
    return value


def _exact_fields(value: dict, fields: set[str], location: str) -> None:
    actual = set(value)
    if actual != fields:
        missing = sorted(fields - actual)
        unexpected = sorted(actual - fields)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise ValueError(f"{location} has invalid fields ({'; '.join(details)})")


def _text(value, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location} must be a non-empty string")
    return value.strip()


def _optional_text(value, location: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{location} must be a string")
    return value.strip()


def _text_list(value, location: str, *, allow_empty: bool = False) -> Tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        qualifier = "" if allow_empty else " non-empty"
        raise ValueError(f"{location} must be a{qualifier} list")
    return tuple(
        _text(item, f"{location} item {index}")
        for index, item in enumerate(value, start=1)
    )


def _slug(value, location: str) -> str:
    value = _text(value, location)
    if len(value) > 80 or not SLUG_RE.fullmatch(value):
        raise ValueError(f"{location} must be a kebab-case identifier")
    return value


def _parse_example(value, location: str) -> LearningExample:
    value = _object(value, location)
    _exact_fields(value, {"french", "english", "note"}, location)
    return LearningExample(
        french=_text(value["french"], f"{location}.french"),
        english=_text(value["english"], f"{location}.english"),
        note=_optional_text(value["note"], f"{location}.note"),
    )


def _parse_mistake(value, location: str) -> LearningMistake:
    value = _object(value, location)
    _exact_fields(value, {"avoid", "prefer", "why"}, location)
    return LearningMistake(
        avoid=_text(value["avoid"], f"{location}.avoid"),
        prefer=_text(value["prefer"], f"{location}.prefer"),
        why=_text(value["why"], f"{location}.why"),
    )


def _parse_section(value, location: str) -> LearningSection:
    value = _object(value, location)
    _exact_fields(
        value,
        {"id", "title", "paragraphs", "points", "examples", "mistakes"},
        location,
    )
    examples = value["examples"]
    mistakes = value["mistakes"]
    if not isinstance(examples, list):
        raise ValueError(f"{location}.examples must be a list")
    if not isinstance(mistakes, list):
        raise ValueError(f"{location}.mistakes must be a list")
    return LearningSection(
        id=_slug(value["id"], f"{location}.id"),
        title=_text(value["title"], f"{location}.title"),
        paragraphs=_text_list(
            value["paragraphs"],
            f"{location}.paragraphs",
            allow_empty=True,
        ),
        points=_text_list(
            value["points"],
            f"{location}.points",
            allow_empty=True,
        ),
        examples=tuple(
            _parse_example(item, f"{location}.examples[{index}]")
            for index, item in enumerate(examples)
        ),
        mistakes=tuple(
            _parse_mistake(item, f"{location}.mistakes[{index}]")
            for index, item in enumerate(mistakes)
        ),
    )


def _parse_vocabulary(value, location: str) -> LearningVocabulary:
    value = _object(value, location)
    _exact_fields(
        value,
        {"kind", "french", "english", "example", "note"},
        location,
    )
    kind = _text(value["kind"], f"{location}.kind")
    if kind not in LEARNING_VOCABULARY_KINDS:
        raise ValueError(f"{location}.kind is not supported")
    french = _text(value["french"], f"{location}.french")
    if kind == "noun" and (
        not NOUN_ARTICLE_RE.search(french)
        or not NOUN_GENDER_RE.search(french)
    ):
        raise ValueError(
            f"{location}.french must give every noun an article and gender marker"
        )
    return LearningVocabulary(
        kind=kind,
        french=french,
        english=_text(value["english"], f"{location}.english"),
        example=_text(value["example"], f"{location}.example"),
        note=_optional_text(value["note"], f"{location}.note"),
    )


def _parse_practice(value, location: str) -> LearningPractice:
    value = _object(value, location)
    _exact_fields(value, {"prompt", "hint", "answer"}, location)
    return LearningPractice(
        prompt=_text(value["prompt"], f"{location}.prompt"),
        hint=_text(value["hint"], f"{location}.hint"),
        answer=_text(value["answer"], f"{location}.answer"),
    )


def _parse_lesson(value, location: str) -> LearningLesson:
    value = _object(value, location)
    _exact_fields(
        value,
        {
            "id",
            "slug",
            "title",
            "summary",
            "level",
            "duration_minutes",
            "source_type",
            "sources",
            "objectives",
            "sections",
            "vocabulary",
            "practice",
            "takeaways",
            "keywords",
        },
        location,
    )
    level = _text(value["level"], f"{location}.level")
    if level not in LEARNING_LEVELS:
        raise ValueError(f"{location}.level is not supported")
    source_type = _text(value["source_type"], f"{location}.source_type")
    if source_type not in LEARNING_SOURCE_TYPES:
        raise ValueError(f"{location}.source_type is not supported")
    duration = value["duration_minutes"]
    if not isinstance(duration, int) or isinstance(duration, bool) or duration < 1:
        raise ValueError(f"{location}.duration_minutes must be a positive integer")
    sources = _text_list(
        value["sources"],
        f"{location}.sources",
        allow_empty=source_type == "editorial-gap-fill",
    )
    if source_type == "editorial-gap-fill" and sources:
        raise ValueError(f"{location}.sources must be empty for editorial content")
    sections = value["sections"]
    vocabulary = value["vocabulary"]
    practice = value["practice"]
    for field_name, field_value in (
        ("sections", sections),
        ("vocabulary", vocabulary),
        ("practice", practice),
    ):
        if not isinstance(field_value, list) or not field_value:
            raise ValueError(f"{location}.{field_name} must be a non-empty list")
    parsed_sections = tuple(
        _parse_section(item, f"{location}.sections[{index}]")
        for index, item in enumerate(sections)
    )
    section_ids = [section.id for section in parsed_sections]
    if len(section_ids) != len(set(section_ids)):
        raise ValueError(f"{location} repeats a section id")
    objectives = _text_list(value["objectives"], f"{location}.objectives")
    parsed_vocabulary = tuple(
        _parse_vocabulary(item, f"{location}.vocabulary[{index}]")
        for index, item in enumerate(vocabulary)
    )
    parsed_practice = tuple(
        _parse_practice(item, f"{location}.practice[{index}]")
        for index, item in enumerate(practice)
    )
    takeaways = _text_list(value["takeaways"], f"{location}.takeaways")
    lesson = LearningLesson(
        id=_slug(value["id"], f"{location}.id"),
        slug=_slug(value["slug"], f"{location}.slug"),
        title=_text(value["title"], f"{location}.title"),
        summary=_text(value["summary"], f"{location}.summary"),
        level=level,
        duration_minutes=duration,
        source_type=source_type,
        sources=sources,
        objectives=objectives,
        sections=parsed_sections,
        vocabulary=parsed_vocabulary,
        practice=parsed_practice,
        takeaways=takeaways,
        keywords=_text_list(value["keywords"], f"{location}.keywords"),
    )
    examples = [
        example
        for section in lesson.sections
        for example in section.examples
    ]
    corrections = [
        mistake
        for section in lesson.sections
        for mistake in section.mistakes
    ]
    if len(examples) < 4:
        raise ValueError(f"{location} must contain at least four examples")
    if len(corrections) < 2:
        raise ValueError(f"{location} must contain at least two corrections")
    example_keys = [example.french.casefold() for example in examples]
    if len(example_keys) != len(set(example_keys)):
        raise ValueError(f"{location} repeats a French example")
    if objectives == takeaways:
        raise ValueError(f"{location} repeats objectives as takeaways")
    if any(section.points == objectives for section in lesson.sections):
        raise ValueError(f"{location} repeats objectives as section points")
    if any(
        paragraph == lesson.summary
        for section in lesson.sections
        for paragraph in section.paragraphs
    ):
        raise ValueError(f"{location} repeats its summary as a paragraph")
    return lesson


def _parse_module(value, location: str) -> LearningModule:
    value = _object(value, location)
    _exact_fields(
        value,
        {
            "id",
            "slug",
            "title",
            "description",
            "icon",
            "color",
            "order",
            "lessons",
        },
        location,
    )
    icon = _text(value["icon"], f"{location}.icon")
    if icon not in LEARNING_ICONS:
        raise ValueError(f"{location}.icon is not supported")
    color = _text(value["color"], f"{location}.color")
    if not COLOR_RE.fullmatch(color):
        raise ValueError(f"{location}.color must be a six-digit hex color")
    order = value["order"]
    if not isinstance(order, int) or isinstance(order, bool) or order < 1:
        raise ValueError(f"{location}.order must be a positive integer")
    lessons = value["lessons"]
    if not isinstance(lessons, list) or not lessons:
        raise ValueError(f"{location}.lessons must be a non-empty list")
    return LearningModule(
        id=_slug(value["id"], f"{location}.id"),
        slug=_slug(value["slug"], f"{location}.slug"),
        title=_text(value["title"], f"{location}.title"),
        description=_text(value["description"], f"{location}.description"),
        icon=icon,
        color=color,
        order=order,
        lessons=tuple(
            _parse_lesson(item, f"{location}.lessons[{index}]")
            for index, item in enumerate(lessons)
        ),
    )


def _load_learning_catalog(path: Path) -> LearningCatalog:
    source = path.read_text(encoding="utf-8")
    source_key = source.casefold()
    if re.search(r"\btcf\b", source_key):
        raise ValueError(f"{path.name} contains a prohibited exam acronym")
    for snippet in FORBIDDEN_LEARNING_COPY:
        if snippet in source_key:
            raise ValueError(
                f"{path.name} contains forbidden filler copy: {snippet!r}"
            )
    payload = json.loads(source)
    payload = _object(payload, path.name)
    _exact_fields(
        payload,
        {"version", "title", "description", "modules"},
        path.name,
    )
    if payload["version"] != 1:
        raise ValueError(f"{path.name} must use learning-content version 1")
    modules = payload["modules"]
    if not isinstance(modules, list) or not modules:
        raise ValueError(f"{path.name}.modules must be a non-empty list")
    parsed_modules = tuple(
        sorted(
            (
                _parse_module(item, f"{path.name}.modules[{index}]")
                for index, item in enumerate(modules)
            ),
            key=lambda module: module.order,
        )
    )
    module_ids = [module.id for module in parsed_modules]
    module_slugs = [module.slug for module in parsed_modules]
    lesson_ids = [
        lesson.id for module in parsed_modules for lesson in module.lessons
    ]
    lesson_slugs = [
        lesson.slug for module in parsed_modules for lesson in module.lessons
    ]
    for values, label in (
        (module_ids, "module id"),
        (module_slugs, "module slug"),
        (lesson_ids, "lesson id"),
        (lesson_slugs, "lesson slug"),
    ):
        if len(values) != len(set(values)):
            raise ValueError(f"{path.name} repeats a {label}")
    example_keys = [
        example.french.casefold()
        for module in parsed_modules
        for lesson in module.lessons
        for section in lesson.sections
        for example in section.examples
    ]
    if len(example_keys) != len(set(example_keys)):
        raise ValueError(f"{path.name} repeats a French example")
    vocabulary_keys = [
        vocabulary.french.casefold()
        for module in parsed_modules
        for lesson in module.lessons
        for vocabulary in lesson.vocabulary
    ]
    if len(vocabulary_keys) != len(set(vocabulary_keys)):
        raise ValueError(f"{path.name} repeats a vocabulary target")
    return LearningCatalog(
        title=_text(payload["title"], f"{path.name}.title"),
        description=_text(payload["description"], f"{path.name}.description"),
        modules=parsed_modules,
    )


@lru_cache(maxsize=1)
def _load_default_learning_catalog() -> LearningCatalog:
    return _load_learning_catalog(LEARNING_CONTENT_PATH)


def load_learning_catalog(
    path: Path = LEARNING_CONTENT_PATH,
) -> LearningCatalog:
    """Return the validated Learn curriculum, cached for bundled content."""
    if path == LEARNING_CONTENT_PATH:
        return _load_default_learning_catalog()
    return _load_learning_catalog(path)
