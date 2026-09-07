"""Original course contract, independent of the preserved reference library."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from .learning_content import (
    LearningSection,
    _exact_fields,
    _object,
    _parse_section,
    _slug,
    _text,
    _text_list,
    load_learning_catalog,
)

CONTENT_ROOT = Path(__file__).resolve().parent / "content" / "learning"
COURSE_ROOT = CONTENT_ROOT / "courses"
CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1-preparation")
LEVEL_DIRECTORIES = dict(zip(CEFR_LEVELS, ("a1", "a2", "b1", "b2", "c1-preparation")))
BENCHMARK_COUNTS = {"A1": 134, "A2": 165, "B1": 96, "B2": 84}
POOL_MINIMUMS = {"practice": 4, "check": 8, "review": 4}


def normalize_answer(
    value: str, *, case_sensitive: bool = False, terminal_punctuation_sensitive: bool = False
) -> str:
    """Typography only: accents, punctuation and grammatical endings survive."""
    value = unicodedata.normalize("NFC", value).translate(
        str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'"})
    )
    value = " ".join(value.split())
    if not terminal_punctuation_sensitive:
        value = value.rstrip(".!?…").rstrip()
    return value if case_sensitive else value.casefold()


def content_digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    ).hexdigest()


def _positive_integer(value, location: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{location} must be a positive integer")
    return value


def _version(value, location: str) -> int:
    if type(value) is not int or value != 1:
        raise ValueError(f"{location} must be 1")
    return value


def _array(value, location: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{location} must be a list")
    return value


def _unique(values, location: str):
    if len(set(values)) != len(values):
        raise ValueError(f"{location} must be unique")
    return values


def _identifiers(value, location: str, *, allow_empty=False) -> tuple[str, ...]:
    values = _text_list(value, location, allow_empty=allow_empty)
    return _unique(tuple(_slug(item, location) for item in values), location)


def _url(value, location: str) -> str:
    value = _text(value, location)
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"https", "http"} or not parsed.netloc
        or parsed.username or parsed.password or any(char.isspace() for char in value)
    ):
        raise ValueError(f"{location} must be an absolute HTTP(S) URL")
    return value


@dataclass(frozen=True)
class CourseSource:
    label: str
    url: str


@dataclass(frozen=True)
class CourseItem:
    id: str
    kind: str
    pool: str
    section_id: str
    prompt: str
    choices: tuple[str, ...]
    answers: tuple[str, ...]
    explanation: str
    case_sensitive: bool = False
    terminal_punctuation_sensitive: bool = False

    @property
    def item_version(self) -> str:
        return content_digest(asdict(self))

    @property
    def exposure_key(self) -> str:
        # Renaming an item or editing feedback must not make a seen prompt fresh.
        return content_digest(normalize_answer(self.prompt))


@dataclass(frozen=True)
class ProductionTask:
    prompt: str
    model_answer: str
    translation: str
    rubric: tuple[str, ...]


@dataclass(frozen=True)
class CourseLesson:
    version: int
    id: str
    slug: str
    cefr_level: str
    topic: str
    title: str
    summary: str
    order: int
    duration_minutes: int
    prerequisites: tuple[str, ...]
    objectives: tuple[str, ...]
    keywords: tuple[str, ...]
    sources: tuple[CourseSource, ...]
    related_legacy_ids: tuple[str, ...]
    sections: tuple[LearningSection, ...]
    practice: tuple[CourseItem, ...]
    production_task: ProductionTask

    @property
    def level(self) -> str:
        return self.cefr_level

    @property
    def content_version(self) -> str:
        return content_digest(asdict(self))

    @property
    def searchable_text(self) -> str:
        return " ".join((self.title, self.summary, self.cefr_level, *self.keywords))


@dataclass(frozen=True)
class CourseModule:
    id: str
    slug: str
    title: str
    description: str
    icon: str
    lessons: tuple[CourseLesson, ...]


@dataclass(frozen=True)
class CourseCatalog:
    lessons: tuple[CourseLesson, ...]
    modules: tuple[CourseModule, ...]
    title: str = "Apprendre le français"
    description: str = (
        "An original A1–B2 course and C1-preparation bridge. Reading completion "
        "and controlled grammar practice are separate, not CEFR/TCF certification."
    )

    def lesson_by_slug(self, slug: str) -> tuple[CourseModule, CourseLesson] | None:
        for module in self.modules:
            for lesson in module.lessons:
                if lesson.slug == slug:
                    return module, lesson
        return None


def parse_course_lesson(value, *, directory: str, reference=None) -> CourseLesson:
    reference = reference or load_learning_catalog()
    location = f"course {directory}"
    value = _object(value, location)
    _exact_fields(value, set(CourseLesson.__dataclass_fields__), location)
    level = _text(value["cefr_level"], f"{location}.cefr_level")
    if level not in CEFR_LEVELS or LEVEL_DIRECTORIES[level] != directory:
        raise ValueError(f"{location}.cefr_level does not match its directory")
    lesson_id = _slug(value["id"], f"{location}.id")
    slug = _slug(value["slug"], f"{location}.slug")
    prefix = level[:2].lower() + "-"
    if not lesson_id.startswith(prefix) or not slug.startswith(prefix):
        raise ValueError(f"{location} id and slug must start with {prefix}")
    topic = _slug(value["topic"], f"{location}.topic")
    if topic not in {module.id for module in reference.modules}:
        raise ValueError(f"{location}.topic is not a reference module")
    related = _identifiers(
        value["related_legacy_ids"], f"{location}.related_legacy_ids", allow_empty=True
    )
    if not set(related) <= {lesson.id for lesson in reference.lessons}:
        raise ValueError(f"{location}.related_legacy_ids contains a missing lesson")
    sections = tuple(
        _parse_section(section, f"{location}.sections[{index}]")
        for index, section in enumerate(_array(value["sections"], f"{location}.sections"))
    )
    section_ids = _unique(tuple(section.id for section in sections), "section IDs")
    if not sections or any(
        not (section.paragraphs or section.points) for section in sections
    ):
        raise ValueError(f"{location}.sections require visible teaching")
    if sum(len(section.examples) for section in sections) < 8:
        raise ValueError(f"{location} requires at least eight examples")
    if sum(len(section.mistakes) for section in sections) < 2:
        raise ValueError(f"{location} requires at least two corrections")
    items = []
    for index, raw in enumerate(_array(value["practice"], f"{location}.practice")):
        item_location = f"{location}.practice[{index}]"
        raw = _object(raw, item_location)
        optional = {"case_sensitive", "terminal_punctuation_sensitive"}
        _exact_fields(
            raw, (set(CourseItem.__dataclass_fields__) - optional) | (raw.keys() & optional),
            item_location,
        )
        normalization = {key: raw.get(key, False) for key in optional}
        if any(type(flag) is not bool for flag in normalization.values()):
            raise ValueError(f"{item_location} normalization flags must be booleans")
        kind = _text(raw["kind"], f"{item_location}.kind")
        pool = _text(raw["pool"], f"{item_location}.pool")
        if kind not in {"text", "choice"} or pool not in POOL_MINIMUMS:
            raise ValueError(f"{item_location} has an invalid kind or pool")
        section_id = _slug(raw["section_id"], f"{item_location}.section_id")
        if section_id not in section_ids:
            raise ValueError(f"{item_location}.section_id does not resolve")
        choices = _text_list(raw["choices"], f"{item_location}.choices", allow_empty=True)
        answers = _text_list(raw["answers"], f"{item_location}.answers")
        _unique(tuple(normalize_answer(item, **normalization) for item in choices), f"{item_location}.choices")
        _unique(tuple(normalize_answer(item, **normalization) for item in answers), f"{item_location}.answers")
        if kind == "choice" and (
            len(choices) < 2 or not set(answers) <= set(choices)
        ):
            raise ValueError(f"{item_location} choice answers must be members of choices")
        if kind == "text" and choices:
            raise ValueError(f"{item_location} text items require choices: []")
        items.append(CourseItem(
            id=_slug(raw["id"], f"{item_location}.id"),
            kind=kind, pool=pool, section_id=section_id,
            prompt=_text(raw["prompt"], f"{item_location}.prompt"),
            choices=choices, answers=answers,
            explanation=_text(raw["explanation"], f"{item_location}.explanation"),
            **normalization,
        ))
    _unique(tuple(item.id for item in items), f"{location} item IDs")
    _unique(tuple(item.exposure_key for item in items), f"{location} item prompts")
    for pool, minimum in POOL_MINIMUMS.items():
        selected = [item for item in items if item.pool == pool]
        if len(selected) < minimum:
            raise ValueError(f"{location} requires at least {minimum} {pool} items")
        if pool != "practice" and sum(item.kind == "text" for item in selected) * 2 < len(selected):
            raise ValueError(f"{location} at least half of {pool} items must be text")
    sources = []
    for raw in _array(value["sources"], f"{location}.sources"):
        raw = _object(raw, f"{location}.sources")
        _exact_fields(raw, {"label", "url"}, f"{location}.sources")
        sources.append(CourseSource(
            _text(raw["label"], "source.label"), _url(raw["url"], "source.url")
        ))
    if not sources:
        raise ValueError(f"{location}.sources must not be empty")
    production = _object(value["production_task"], f"{location}.production_task")
    _exact_fields(production, set(ProductionTask.__dataclass_fields__), "production_task")
    return CourseLesson(
        version=_version(value["version"], f"{location}.version"),
        id=lesson_id, slug=slug, cefr_level=level, topic=topic,
        title=_text(value["title"], f"{location}.title"),
        summary=_text(value["summary"], f"{location}.summary"),
        order=_positive_integer(value["order"], f"{location}.order"),
        duration_minutes=_positive_integer(value["duration_minutes"], f"{location}.duration_minutes"),
        prerequisites=_identifiers(value["prerequisites"], f"{location}.prerequisites", allow_empty=True),
        objectives=_text_list(value["objectives"], f"{location}.objectives"),
        keywords=_text_list(value["keywords"], f"{location}.keywords"),
        sources=tuple(sources), related_legacy_ids=related,
        sections=sections, practice=tuple(items),
        production_task=ProductionTask(
            prompt=_text(production["prompt"], "production_task.prompt"),
            model_answer=_text(production["model_answer"], "production_task.model_answer"),
            translation=_text(production["translation"], "production_task.translation"),
            rubric=_text_list(production["rubric"], "production_task.rubric"),
        ),
    )


def build_course_catalog(lessons, reference=None) -> CourseCatalog:
    reference = reference or load_learning_catalog()
    lessons = tuple(sorted(lessons, key=lambda lesson: (CEFR_LEVELS.index(lesson.cefr_level), lesson.order)))
    _unique(tuple(lesson.id for lesson in lessons), "course IDs")
    _unique(tuple(lesson.slug for lesson in lessons), "course slugs")
    _unique(tuple((lesson.cefr_level, lesson.order) for lesson in lessons), "per-level order")
    if {lesson.id for lesson in lessons} & {lesson.id for lesson in reference.lessons}:
        raise ValueError("Course IDs must not collide with legacy IDs")
    previous_ids = set()
    for lesson in lessons:
        if not set(lesson.prerequisites) <= previous_ids:
            raise ValueError(f"{lesson.id} prerequisites must reference earlier course lessons")
        previous_ids.add(lesson.id)
    modules = tuple(
        CourseModule(
            module.id, module.slug, module.title, module.description, module.icon,
            tuple(lesson for lesson in lessons if lesson.topic == module.id),
        )
        for module in reference.modules
        if any(lesson.topic == module.id for lesson in lessons)
    )
    return CourseCatalog(lessons=lessons, modules=modules)


def _read_catalog(root: Path) -> CourseCatalog:
    lessons = []
    for path in sorted(root.rglob("*.json")):
        if path.parent.parent != root or path.parent.name not in LEVEL_DIRECTORIES.values():
            raise ValueError(f"Unexpected course file location: {path}")
        lessons.append(parse_course_lesson(
            json.loads(path.read_text(encoding="utf-8")), directory=path.parent.name
        ))
    return build_course_catalog(lessons)


@lru_cache(maxsize=1)
def _bundled_course_catalog() -> CourseCatalog:
    return _read_catalog(COURSE_ROOT)


def load_course_catalog(root: Path | None = None) -> CourseCatalog:
    """Bundled content is validated once per process, never sent as a JSON bank."""
    return _bundled_course_catalog() if root is None else _read_catalog(Path(root))


@dataclass(frozen=True)
class CoverageEntry:
    source_url: str
    source_title: str
    lesson_id: str
    section_ids: tuple[str, ...]
    practice_ids: tuple[str, ...]
    disposition: str
    evidence: str


def validate_coverage_ledger(value, benchmark, catalog: CourseCatalog) -> tuple[CoverageEntry, ...]:
    value = _object(value, "coverage")
    _exact_fields(value, {"version", "level", "source_index_url", "entries"}, "coverage")
    _version(value["version"], "coverage.version")
    level = _text(value["level"], "coverage.level")
    if level not in BENCHMARK_COUNTS or benchmark["level"] != level:
        raise ValueError("coverage.level does not match the benchmark")
    if value["source_index_url"] != benchmark["url"]:
        raise ValueError("coverage.source_index_url does not match the benchmark")
    sources = {entry["url"]: entry["title"] for entry in benchmark["entries"]}
    if len(sources) != BENCHMARK_COUNTS[level] or len(sources) != len(benchmark["entries"]):
        raise ValueError("Benchmark count or uniqueness is invalid")
    lessons = {lesson.id: lesson for lesson in catalog.lessons}
    entries = []
    for raw in _array(value["entries"], "coverage.entries"):
        raw = _object(raw, "coverage.entry")
        _exact_fields(raw, set(CoverageEntry.__dataclass_fields__), "coverage.entry")
        url = _url(raw["source_url"], "coverage.source_url")
        if url not in sources or raw["source_title"] != sources[url]:
            raise ValueError("Coverage source URL/title must exactly match the benchmark")
        lesson_id = _slug(raw["lesson_id"], "coverage.lesson_id")
        lesson = lessons.get(lesson_id)
        if lesson is None or lesson.cefr_level != level:
            raise ValueError("Coverage lesson must exist at the mapped level")
        sections = _identifiers(raw["section_ids"], "coverage.section_ids")
        items = _identifiers(raw["practice_ids"], "coverage.practice_ids")
        section_map = {section.id: section for section in lesson.sections}
        item_map = {item.id: item for item in lesson.practice}
        if not set(sections) <= section_map.keys() or not set(items) <= item_map.keys():
            raise ValueError("Coverage sections and practice items must resolve")
        if not any(section_map[key].examples for key in sections):
            raise ValueError("Coverage requires visible examples in mapped sections")
        if any(item_map[key].section_id not in sections for key in items):
            raise ValueError("Coverage practice must exercise a mapped section")
        disposition = _text(raw["disposition"], "coverage.disposition")
        if disposition not in {"original-lesson", "consolidated", "recognition-track"}:
            raise ValueError("Coverage disposition is not a finished mapping")
        evidence = _text(raw["evidence"], "coverage.evidence")
        if len(evidence.split()) < 6 or normalize_answer(evidence) in {"covered", "fully covered"}:
            raise ValueError("Coverage requires specific teaching and exercise evidence")
        entries.append(CoverageEntry(
            url, sources[url], lesson_id, sections, items, disposition, evidence
        ))
    counts = Counter(entry.source_url for entry in entries)
    if set(counts) != set(sources) or any(count != 1 for count in counts.values()):
        raise ValueError("Coverage must map every benchmark URL exactly once")
    return tuple(entries)
