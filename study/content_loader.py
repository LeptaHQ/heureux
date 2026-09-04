"""Parse the bundled study banks into structured, importable data.

Pure functions only — no Django imports — so the parser is easy to test and
reuse. The module owns the expression response corpora, theme taxonomies,
equivalent-subject groups, and the Tâche 2 master question bank.
"""

from __future__ import annotations

import csv
import difflib
import hashlib
import html
import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CONTENT_DIR = Path(__file__).resolve().parent / "content"
RESPONSES_DIR = CONTENT_DIR / "responses"
STUDY_SHEETS_PATH = CONTENT_DIR / "study_sheets.md"
PHRASES_PATH = CONTENT_DIR / "phrases.tsv"
SUBJECT_VOCABULARY_DIR = CONTENT_DIR / "subject_vocabulary"
COMPREHENSION_VOCABULARY_DIR = CONTENT_DIR / "comprehension_vocabulary"
THEMES_PATH = CONTENT_DIR / "themes.json"
SECTIONS_PATH = CONTENT_DIR / "sections.json"
COMPREHENSION_DIR = CONTENT_DIR / "comprehension"
COMPREHENSION_TESTS_PATH = COMPREHENSION_DIR / "tests.json"
EO_TACHE_ONE_TASK = ("eo", "tache-1")
EO_TACHE_ONE_QUESTION_BANK_DIR = CONTENT_DIR / "tache_1"
QUESTION_BANK_PATH = CONTENT_DIR / "tache_2" / "master_question_bank_1.json"
QUESTION_BANK_DIR = QUESTION_BANK_PATH.parent
AI_EXAMINER_PROMPT_PATH = QUESTION_BANK_DIR / "ai_examiner_prompt.md"
TACHE_TWO_SUBJECTS_DIR = QUESTION_BANK_DIR / "subjects"
TACHE_TWO_VOCABULARY_DIR = QUESTION_BANK_DIR / "vocabulary"
TACHE_TWO_THEME_VOCABULARY_DIR = QUESTION_BANK_DIR / "theme_vocabulary"
TACHE_TWO_SUBJECT_THEMES_PATH = TACHE_TWO_SUBJECTS_DIR / "subject_themes.json"
TACHE_TWO_EQUIVALENT_GROUPS_PATH = (
    TACHE_TWO_SUBJECTS_DIR / "equivalent_groups.json"
)
QUESTION_BANK_TASK = ("eo", "tache-2")
EO_TACHE_THREE_TASK = ("eo", "tache-3")
EO_TACHE_THREE_THEME_VOCABULARY_DIR = (
    CONTENT_DIR / "tache_3" / "theme_vocabulary"
)

EE_TACHE_THREE_TASK = ("ee", "tache-3")
EE_TACHE_THREE_CONTENT_PREFIX = "ee-tache3:"
EE_TACHE_THREE_DIR = CONTENT_DIR / "ee" / "tache_3"
EE_TACHE_THREE_RESPONSES_DIR = EE_TACHE_THREE_DIR / "responses"
EE_TACHE_THREE_SUBJECTS_DIR = EE_TACHE_THREE_DIR / "subjects"
EE_TACHE_THREE_VOCABULARY_DIR = EE_TACHE_THREE_DIR / "vocabulary"
EE_TACHE_THREE_MEMOIRES_DIR = EE_TACHE_THREE_DIR / "memoires"
EE_TACHE_THREE_AUTHOR_RESPONSES_PATH = (
    EE_TACHE_THREE_DIR / "author_responses.json"
)
EE_TACHE_THREE_VOCABULARY_PER_RESPONSE = 30

EE_TACHE_ONE_TASK = ("ee", "tache-1")
EE_TACHE_ONE_DIR = CONTENT_DIR / "ee" / "tache_1"
EE_TACHE_ONE_SUJETS_PATH = EE_TACHE_ONE_DIR / "sujets.json"

EE_TACHE_TWO_TASK = ("ee", "tache-2")
EE_TACHE_TWO_CONTENT_PREFIX = "ee-tache2:"
EE_TACHE_TWO_DIR = CONTENT_DIR / "ee" / "tache_2"
EE_TACHE_TWO_SUBJECTS_DIR = EE_TACHE_TWO_DIR / "subjects"

EE_TACHE_ONE_CONTENT_PREFIX = "ee-tache1:"
EE_TACHE_ONE_SUBJECTS_DIR = EE_TACHE_ONE_DIR / "subjects"
EE_WRITING_TASKS = {
    1: EE_TACHE_ONE_TASK,
    2: EE_TACHE_TWO_TASK,
}
EE_WRITING_RESPONSE_DIRS = {
    1: EE_TACHE_ONE_DIR / "responses",
    2: EE_TACHE_TWO_DIR / "responses",
}
EE_AI_EXAMINER_PROMPT_PATHS = {
    1: EE_TACHE_ONE_DIR / "ai_examiner_prompt.md",
    2: EE_TACHE_TWO_DIR / "ai_examiner_prompt.md",
    3: EE_TACHE_THREE_DIR / "ai_examiner_prompt.md",
}
EE_WRITING_WORD_LIMITS = {
    1: (60, 120),
    2: (120, 150),
}
EE_TACHE_THREE_WORD_LIMIT = (120, 180)
EE_2025_SOURCE_URL = (
    "https://www.formation-tcfcanada.com/epreuve/"
    "expression-ecrite/sujets-actualites/{month}-2025"
)
EE_ASTUCES_URL = (
    "https://www.formation-tcfcanada.com/epreuve/expression-ecrite/astuces"
)

# The 2025 corpus is published month by month; février 2025 was never
# published by the source, so it is legitimately absent everywhere.
EE_MONTH_ORDER = (
    "janvier",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "aout",
    "septembre",
    "octobre",
    "novembre",
    "decembre",
)
EE_TACHE_DIRS = {
    1: EE_TACHE_ONE_DIR,
    2: EE_TACHE_TWO_DIR,
    3: EE_TACHE_THREE_DIR,
}
EE_TACHE_CONTENT_PREFIXES = {
    1: EE_TACHE_ONE_CONTENT_PREFIX,
    2: EE_TACHE_TWO_CONTENT_PREFIX,
    3: EE_TACHE_THREE_CONTENT_PREFIX,
}

# Question-bank-backed tasks mapped to their JSON directory and progress-key
# namespace. EO T1 opens its single bank directly, EO T2 retains the files for
# subject references and legacy redirects, and EE T3 exposes Mémoires.
MEMOIRE_TASKS = {
    EO_TACHE_ONE_TASK: (EO_TACHE_ONE_QUESTION_BANK_DIR, "eo-tache1"),
    QUESTION_BANK_TASK: (QUESTION_BANK_DIR, ""),
    EE_TACHE_THREE_TASK: (EE_TACHE_THREE_MEMOIRES_DIR, "ee-tache3"),
}

EXPECTED_PROMPTS = 167
EXPECTED_UNIQUE = 130
EXPECTED_FAMILIES = 17
EXPECTED_PHRASES = 1410
SUBJECT_VOCABULARY_PER_RESPONSE = 50
SUBJECT_VOCABULARY_PER_KIND = 10
TACHE_TWO_VOCABULARY_MIN_PER_RESPONSE = 30
TACHE_TWO_THEME_VOCABULARY_PER_THEME = 45
TACHE_TWO_THEME_VOCABULARY_PER_KIND = 15
TACHE_TWO_THEME_VOCABULARY_FIELDS = (
    "id",
    "kind",
    "french",
    "anchor",
    "english",
    "example",
    "usage",
)
TACHE_TWO_THEME_VOCABULARY_KINDS = (
    "mot-cle",
    "expression-utile",
    "fragment",
)
TACHE_TWO_THEME_VOCABULARY_CATEGORIES = {
    "mot-cle": "Thème · Mots clés",
    "expression-utile": "Thème · Expressions utiles",
    "fragment": "Thème · Fragments de phrase",
}
TACHE_TWO_THEME_NOUN_SUFFIX_RE = re.compile(
    r" \((?P<gender>[mf])\.(?P<plural> pl\.)?\)$"
)
TACHE_TWO_THEME_NOUN_ARTICLE_RE = re.compile(
    r"^(?:(?P<article>un|une|le|la|les|des)\s+|(?P<elided>l['’]))",
    re.IGNORECASE,
)
TACHE_TWO_THEME_INFINITIVE_RE = re.compile(
    r"^(?:s['’]|se\s+)?[\wÀ-ÿ-]+(?:er|ir|re)\b",
    re.IGNORECASE,
)
EO_TACHE_THREE_THEME_VOCABULARY_PER_THEME = 60
EO_TACHE_THREE_THEME_VOCABULARY_PER_KIND = 15
EO_TACHE_THREE_THEME_VOCABULARY_FIELDS = (
    "id",
    "kind",
    "french",
    "anchor",
    "english",
    "example",
    "usage",
)
EO_TACHE_THREE_THEME_VOCABULARY_KINDS = (
    "notion-cle",
    "verbe-collocation",
    "expression-idiomatique",
    "construction-argumentative",
)
EO_TACHE_THREE_THEME_VOCABULARY_CATEGORIES = {
    "notion-cle": "EO Tâche 3 · Notions clés",
    "verbe-collocation": "EO Tâche 3 · Verbes et collocations",
    "expression-idiomatique": "EO Tâche 3 · Expressions et locutions",
    "construction-argumentative": (
        "EO Tâche 3 · Constructions argumentatives"
    ),
}
EO_TACHE_THREE_NOTION_USAGE_RE = re.compile(
    r"^Nom (?P<gender>masculin|féminin)(?P<plural> pluriel)? "
    r"— (?P<form>pluriel|singulier) : .+\.",
)
EO_TACHE_THREE_VERB_USAGE_RE = re.compile(
    r"^Verbe — infinitif : .+ ; construction : .+\.",
)
SUBJECT_VOCABULARY_FIELDS = (
    "id",
    "kind",
    "french",
    "english",
    "example",
    "usage",
)
SUBJECT_VOCABULARY_KINDS = (
    "mot-cle",
    "collocation",
    "expression",
    "tournure",
    "phrase-modele",
)
SUBJECT_VOCABULARY_CATEGORIES = {
    "mot-cle": "Mots clés du sujet",
    "collocation": "Collocations du sujet",
    "expression": "Expressions du sujet",
    "tournure": "Tournures pour l'oral",
    "phrase-modele": "Phrases modèles",
}
COMPREHENSION_VOCABULARY_PER_TEST = 50
COMPREHENSION_VOCABULARY_PER_KIND = 10
COMPREHENSION_VOCABULARY_KINDS = (
    "mot-cle",
    "verbe-action",
    "expression",
    "reformulation",
    "phrase-modele",
)
COMPREHENSION_VOCABULARY_CATEGORIES = {
    "mot-cle": "Compréhension · Mots clés",
    "verbe-action": "Compréhension · Verbes et actions",
    "expression": "Compréhension · Expressions",
    "reformulation": "Compréhension · Reformulations",
    "phrase-modele": "Compréhension · Phrases modèles",
}
COMPREHENSION_VOCABULARY_FIELDS = (
    "id",
    "kind",
    "french",
    "english",
    "example",
    "usage",
    "questions",
)
EE_TACHE_THREE_VOCABULARY_FIELDS = (
    "id",
    "kind",
    "french",
    "english",
    "example",
    "usage",
)
EE_TACHE_THREE_VOCABULARY_KINDS = (
    "mot-cle",
    "collocation",
    "expression",
    "tournure",
    "phrase-modele",
    "verbe-action",
    "reformulation",
)
EE_TACHE_THREE_VOCABULARY_CATEGORIES = {
    "mot-cle": "EE Tâche 3 · Mots clés",
    "collocation": "EE Tâche 3 · Collocations",
    "expression": "EE Tâche 3 · Expressions",
    "tournure": "EE Tâche 3 · Tournures",
    "phrase-modele": "EE Tâche 3 · Phrases modèles",
    "verbe-action": "EE Tâche 3 · Verbes et actions",
    "reformulation": "EE Tâche 3 · Reformulations",
}
PHRASE_FIELDS = (
    "id",
    "tier",
    "category",
    "english_cue",
    "expression",
    "anchor",
    "example",
    "sources",
    "note",
)
PHRASE_MAX_LENGTHS = {
    "id": 16,
    "tier": 16,
    "category": 120,
    "english_cue": 200,
    "expression": 300,
    "anchor": 300,
}

# study_sheets label -> responses directory name.
LABEL_TO_THEME = {
    "Culture": "Culture",
    "Famille": "Famille",
    "Education": "Education",
    "Santé": "Sante",
    "Techno": "Technologie",
    "Environ": "Environnement",
    "Economie": "Economie",
}


@dataclass(frozen=True)
class ThemeData:
    slug: str
    name: str
    display: str
    order: int
    color: str
    icon: str
    task: str = ""


@dataclass(frozen=True)
class TaskData:
    slug: str
    name: str
    subtitle: str
    icon: str
    color: str
    order: int
    available: bool


@dataclass(frozen=True)
class SectionData:
    slug: str
    name: str
    short_name: str
    icon: str
    color: str
    order: int
    available: bool
    tasks: Tuple[TaskData, ...]


@dataclass(frozen=True)
class QuestionBankQuestionData:
    content_key: str
    text: str
    note: str = ""


@dataclass(frozen=True)
class QuestionBankGroupData:
    title: str
    guidance: str
    questions: Tuple[QuestionBankQuestionData, ...]


@dataclass(frozen=True)
class QuestionBankSectionData:
    number: int
    title: str
    guidance: str
    groups: Tuple[QuestionBankGroupData, ...]

    @property
    def anchor(self) -> str:
        return f"banque-partie-{self.number}"

    @property
    def number_label(self) -> str:
        return f"{self.number:02d}"

    @property
    def question_count(self) -> int:
        return sum(len(group.questions) for group in self.groups)

    @property
    def question_keys(self) -> Tuple[str, ...]:
        return tuple(
            question.content_key
            for group in self.groups
            for question in group.questions
        )


@dataclass(frozen=True)
class QuestionBankData:
    number: int
    title: str
    label: str
    icon: str
    subtitle: str
    sections: Tuple[QuestionBankSectionData, ...]
    key_namespace: str = ""

    @property
    def category_count(self) -> int:
        return len(self.sections)

    @property
    def question_count(self) -> int:
        return sum(section.question_count for section in self.sections)

    @property
    def question_keys(self) -> Tuple[str, ...]:
        return tuple(
            question_key
            for section in self.sections
            for question_key in section.question_keys
        )

    @property
    def annotation_key_prefix(self) -> str:
        base = "question-bank"
        if self.key_namespace:
            base = f"question-bank:{self.key_namespace}"
        if self.number == 1:
            return base
        return f"{base}:memory-{self.number:02d}"


@dataclass(frozen=True)
class TacheTwoSubjectQuestionData:
    text: str
    memory_number: Optional[int] = None
    memory_section: Optional[int] = None

    @property
    def uses_memory(self) -> bool:
        return self.memory_number is not None


@dataclass(frozen=True)
class TacheTwoSubjectData:
    number: int
    title: str
    prompt: str
    questions: Tuple[TacheTwoSubjectQuestionData, ...]

    @property
    def number_label(self) -> str:
        return f"{self.number:02d}"

    @property
    def question_count(self) -> int:
        return len(self.questions)

    @property
    def memory_question_count(self) -> int:
        return sum(question.uses_memory for question in self.questions)


@dataclass(frozen=True)
class TacheTwoSubjectBatchData:
    number: int
    subjects: Tuple[TacheTwoSubjectData, ...]

    @property
    def number_label(self) -> str:
        return f"{self.number:02d}"

    @property
    def subject_count(self) -> int:
        return len(self.subjects)

    @property
    def question_count(self) -> int:
        return sum(subject.question_count for subject in self.subjects)

    @property
    def first_subject_number(self) -> int:
        return self.subjects[0].number

    @property
    def last_subject_number(self) -> int:
        return self.subjects[-1].number


@dataclass(frozen=True)
class TacheTwoSubjectMonthData:
    number: int
    slug: str
    name: str
    batches: Tuple[TacheTwoSubjectBatchData, ...]

    @property
    def batch_count(self) -> int:
        return len(self.batches)

    @property
    def subject_count(self) -> int:
        return sum(batch.subject_count for batch in self.batches)

    @property
    def question_count(self) -> int:
        return sum(batch.question_count for batch in self.batches)


@dataclass(frozen=True)
class TacheTwoThemeData:
    slug: str
    name: str
    icon: str
    order: int


@dataclass(frozen=True)
class TacheTwoEquivalentGroupData:
    id: str
    theme: str
    canonical: str
    members: Tuple[str, ...]


@dataclass(frozen=True)
class EeSubjectThemeData:
    slug: str
    name: str
    icon: str
    order: int


@dataclass(frozen=True)
class EeEquivalentGroupData:
    id: str
    theme: str
    canonical: str
    members: Tuple[str, ...]


@dataclass(frozen=True)
class EeWritingSubjectData:
    source_id: int
    content_key: str
    combinaison: str
    position: int
    prompt: str

    @property
    def combination_number(self) -> str:
        return self.combinaison.removeprefix("Combinaison ").strip()


@dataclass(frozen=True)
class EeWritingMonthData:
    number: int
    slug: str
    name: str
    year: int
    sujets: Tuple[EeWritingSubjectData, ...]


@dataclass(frozen=True)
class ArgumentData:
    order: int
    idea: str
    developpement: str
    exemple: str
    consequence: str


@dataclass(frozen=True)
class PromptData:
    content_key: str
    theme: str
    number: int
    text: str
    family: str
    is_canonical: bool


@dataclass
class ResponseData:
    content_key: str
    body_hash: str
    theme: str
    family: str
    prompt: str
    reformulation: str
    position: str
    position_claire: str
    nuance: str
    conclusion: str
    body: str
    body_html: str
    arguments: List[ArgumentData]
    prompts: List[PromptData] = field(default_factory=list)


@dataclass(frozen=True)
class PhraseData:
    phrase_id: str
    tier: str
    category: str
    english_cue: str
    expression: str
    anchor: str
    example: str
    note: str
    sources_raw: str
    sources: Tuple[Tuple[str, int], ...]
    order: int


@dataclass(frozen=True)
class ComprehensionVocabularyData:
    phrase: PhraseData
    test_slug: str
    question_numbers: Tuple[int, ...]


@dataclass(frozen=True)
class ComprehensionChoiceData:
    letter: str
    text_fr: str
    text_en: str
    rationale: str
    is_correct: bool


@dataclass(frozen=True)
class ComprehensionQuestionData:
    content_key: str
    number: int
    passage_fr: str
    passage_en: str
    prompt_fr: str
    prompt_en: str
    correct_explanation: str
    choices: Tuple[ComprehensionChoiceData, ...]


@dataclass(frozen=True)
class ComprehensionTestData:
    slug: str
    mode: str
    number: int
    title: str
    description: str
    expected_question_count: int
    order: int
    is_published: bool
    questions: Tuple[ComprehensionQuestionData, ...]


def _slugify(value: str) -> str:
    replacements = {
        "à": "a", "â": "a", "ä": "a", "ç": "c", "é": "e", "è": "e",
        "ê": "e", "ë": "e", "î": "i", "ï": "i", "ô": "o", "ö": "o",
        "ù": "u", "û": "u", "ü": "u", "œ": "oe", "’": "", "'": "",
    }
    value = value.lower()
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:110] or "x"


def prompt_content_key(theme_slug: str, number: int) -> str:
    return f"{theme_slug}:p{number}"


def family_content_key(order: int) -> str:
    return f"family:{order:02d}"


def phrase_category_content_key(name: str) -> str:
    return f"phrase-category:{_slugify(name)}"


def _normalize(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in value.strip().splitlines())


def _natural_key(path: Path) -> Tuple[int, ...]:
    numbers = tuple(int(n) for n in re.findall(r"\d+", path.stem))
    return numbers or (0,)


def load_themes() -> List[ThemeData]:
    raw = json.loads(THEMES_PATH.read_text(encoding="utf-8"))
    themes = [
        ThemeData(
            slug=meta.get("slug") or _slugify(name),
            name=name,
            display=meta["display"],
            order=meta["order"],
            color=meta["color"],
            icon=meta["icon"],
            task=meta.get("task", ""),
        )
        for name, meta in raw.items()
    ]
    themes.sort(key=lambda t: t.order)
    return themes


def load_sections() -> List[SectionData]:
    raw = json.loads(SECTIONS_PATH.read_text(encoding="utf-8"))
    sections: List[SectionData] = []
    for part in raw.get("parts", []):
        tasks = tuple(
            TaskData(
                slug=t["slug"],
                name=t["name"],
                subtitle=t.get("subtitle", ""),
                icon=t.get("icon", "target"),
                color=t.get("color", part.get("color", "#6366f1")),
                order=t.get("order", 0),
                available=bool(t.get("available", True)),
            )
            for t in part.get("tasks", [])
        )
        tasks = tuple(sorted(tasks, key=lambda t: t.order))
        sections.append(
            SectionData(
                slug=part["slug"],
                name=part["name"],
                short_name=part.get("short_name", part["name"]),
                icon=part.get("icon", "file-text"),
                color=part.get("color", "#6366f1"),
                order=part.get("order", 0),
                available=bool(part.get("available", True)),
                tasks=tasks,
            )
        )
    sections.sort(key=lambda s: s.order)
    return sections


def _load_master_prompt(path: Path) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    heading = "## Master prompt"
    _, found_heading, prompt_section = text.partition(heading)
    if not found_heading:
        raise ValueError(f"{path.name} is missing its Master prompt section")

    _, found_fence, fenced_content = prompt_section.partition("```text\n")
    if not found_fence:
        raise ValueError(f"{path.name} is missing its Master prompt text fence")

    prompt, found_closing_fence, _ = fenced_content.partition("\n```")
    prompt = prompt.strip()
    if not found_closing_fence or not prompt:
        raise ValueError(f"{path.name} has an incomplete Master prompt")
    return prompt


def load_ai_examiner_prompt(path: Path = AI_EXAMINER_PROMPT_PATH) -> str:
    """Extract the copy-ready oral master prompt from its Markdown guide."""
    return _load_master_prompt(path)


def load_ee_ai_examiner_prompt(tache: int, path: Optional[Path] = None) -> str:
    """Extract one task-specific written-expression evaluator prompt."""
    if tache not in EE_AI_EXAMINER_PROMPT_PATHS:
        raise ValueError(f"Unsupported EE task: {tache}")
    return _load_master_prompt(path or EE_AI_EXAMINER_PROMPT_PATHS[tache])


def ee_tache_three_instruction(subject: str) -> str:
    """Return the complete candidate-facing instruction for one Tâche 3 topic."""
    subject = subject.strip()
    if not subject:
        raise ValueError("An EE Tâche 3 subject is required")
    return (
        "Rédigez un texte de 120 à 180 mots sur le sujet ci-dessous. "
        "Dans une première partie de 40 à 60 mots, présentez une synthèse "
        "neutre des deux documents. Dans une deuxième partie de 80 à 120 "
        "mots, donnez et justifiez votre point de vue personnel.\n\n"
        f"Sujet : {subject}"
    )


def ee_exam_subject_packet(
    tache: int,
    subject: str,
    *,
    document1: str = "",
    document2: str = "",
    source_note: str = "",
) -> str:
    """Format one exact written-expression subject for copying or evaluation."""
    subject = subject.strip()
    if tache not in {1, 2, 3}:
        raise ValueError(f"Unsupported EE task: {tache}")
    if not subject:
        raise ValueError("An EE subject is required")

    if tache in EE_WRITING_WORD_LIMITS:
        minimum, maximum = EE_WRITING_WORD_LIMITS[tache]
        sections = [
            f"Expression écrite — Tâche {tache}",
            f"Required length: {minimum}-{maximum} words",
            f"Sujet :\n{subject}",
        ]
    else:
        sections = [
            f"Expression écrite — Tâche {tache}",
            ee_tache_three_instruction(subject),
        ]
    if tache == 3:
        document1 = document1.strip()
        document2 = document2.strip()
        if not document1 or not document2:
            raise ValueError("Both source documents are required for EE Tâche 3")
        sections.extend(
            [
                f"Document 1 :\n{document1}",
                f"Document 2 :\n{document2}",
            ]
        )
        if source_note.strip():
            sections.append(f"Source note :\n{source_note.strip()}")
    return "\n\n".join(sections)


def build_ee_ai_examiner_prompt(
    tache: int,
    subject: str,
    *,
    document1: str = "",
    document2: str = "",
    source_note: str = "",
) -> str:
    """Build a subject-specific evaluator prompt that waits for one response."""
    packet = ee_exam_subject_packet(
        tache,
        subject,
        document1=document1,
        document2=document2,
        source_note=source_note,
    )
    return (
        f"{load_ee_ai_examiner_prompt(tache)}\n\n"
        "======================================================================\n"
        "ACTIVE PRACTICE PACKET\n"
        "======================================================================\n\n"
        f"{packet}\n\n"
        "Candidate response: WAIT FOR MY NEXT MESSAGE."
    )


def load_question_bank(
    path: Path = QUESTION_BANK_PATH,
    key_namespace: str = "",
) -> QuestionBankData:
    raw = json.loads(path.read_text(encoding="utf-8"))
    memory_number = raw.get("number")
    title = str(raw.get("title", "")).strip()
    label = str(raw.get("label", "")).strip()
    icon = str(raw.get("icon", "")).strip()
    subtitle = str(raw.get("subtitle", "")).strip()
    if not isinstance(memory_number, int) or memory_number < 1:
        raise ValueError("The question bank needs a positive memory number")
    if not title or not label or not icon or not subtitle:
        raise ValueError(
            "The question bank needs a title, label, icon, and subtitle"
        )
    sections: List[QuestionBankSectionData] = []
    seen_questions = set()
    for raw_section in raw.get("sections", []):
        number = int(raw_section["number"])
        section_title = str(raw_section.get("title", "")).strip()
        if not section_title:
            raise ValueError(f"Question-bank section {number} has no title")

        groups: List[QuestionBankGroupData] = []
        for raw_group in raw_section.get("groups", []):
            questions: List[QuestionBankQuestionData] = []
            for raw_question in raw_group.get("questions", []):
                if isinstance(raw_question, str):
                    text = raw_question.strip()
                    note = ""
                else:
                    text = str(raw_question.get("text", "")).strip()
                    note = str(raw_question.get("note", "")).strip()
                if not text:
                    raise ValueError(
                        f"Question-bank section {number} contains an empty question"
                    )
                normalized = text.casefold()
                if normalized in seen_questions:
                    raise ValueError(f"Duplicate question-bank phrase: {text}")
                seen_questions.add(normalized)
                digest = hashlib.sha256(
                    normalized.encode("utf-8")
                ).hexdigest()
                key_prefix = f"{key_namespace}:" if key_namespace else ""
                questions.append(
                    QuestionBankQuestionData(
                        content_key=(
                            f"memory:{key_prefix}{memory_number}"
                            f":question:{digest}"
                        ),
                        text=text,
                        note=note,
                    )
                )
            if not questions:
                raise ValueError(
                    f"Question-bank section {number} contains an empty group"
                )
            groups.append(
                QuestionBankGroupData(
                    title=str(raw_group.get("title", "")).strip(),
                    guidance=str(raw_group.get("guidance", "")).strip(),
                    questions=tuple(questions),
                )
            )
        if not groups:
            raise ValueError(f"Question-bank section {number} has no groups")
        sections.append(
            QuestionBankSectionData(
                number=number,
                title=section_title,
                guidance=str(raw_section.get("guidance", "")).strip(),
                groups=tuple(groups),
            )
        )

    expected_numbers = list(range(1, len(sections) + 1))
    actual_numbers = [section.number for section in sections]
    if actual_numbers != expected_numbers:
        raise ValueError(
            "Question-bank sections must be ordered consecutively from 1"
        )
    if not sections:
        raise ValueError("The question bank has no sections")

    return QuestionBankData(
        number=memory_number,
        title=title,
        label=label,
        icon=icon,
        subtitle=subtitle,
        sections=tuple(sections),
        key_namespace=key_namespace,
    )


def load_question_banks(
    directory: Path = QUESTION_BANK_DIR,
    key_namespace: str = "",
) -> Tuple[QuestionBankData, ...]:
    banks = tuple(
        sorted(
            (
                load_question_bank(path, key_namespace=key_namespace)
                for path in directory.glob("*.json")
            ),
            key=lambda bank: bank.number,
        )
    )
    if not banks:
        raise ValueError("A question-bank directory needs at least one bank")
    numbers = [bank.number for bank in banks]
    if numbers != list(range(1, len(banks) + 1)):
        raise ValueError(
            "Question banks must be numbered consecutively from 1"
        )
    return banks


def load_tache_two_subject_months(
    directory: Path = TACHE_TWO_SUBJECTS_DIR,
) -> Tuple[TacheTwoSubjectMonthData, ...]:
    paths = sorted(directory.glob("*/batch_*.json"), key=_natural_key)
    if not paths:
        raise ValueError("Tâche 2 needs at least one subject batch")

    memory_sections = {
        (memory.number, section.number)
        for memory in load_question_banks()
        for section in memory.sections
    }
    month_rows = {}
    month_numbers = {}
    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw_month = raw.get("month", {})
        month_number = raw_month.get("number")
        month_slug = str(raw_month.get("slug", "")).strip()
        month_name = str(raw_month.get("name", "")).strip()
        batch_number = raw.get("batch")
        if not isinstance(month_number, int) or month_number < 1:
            raise ValueError(f"{path.name} needs a positive month number")
        if not re.fullmatch(r"[a-z0-9-]+", month_slug):
            raise ValueError(f"{path.name} has an invalid month slug")
        if not month_name:
            raise ValueError(f"{path.name} needs a month name")
        if not isinstance(batch_number, int) or batch_number < 1:
            raise ValueError(f"{path.name} needs a positive batch number")

        existing_slug = month_numbers.get(month_number)
        if existing_slug and existing_slug != month_slug:
            raise ValueError(
                f"Month {month_number} is used by both "
                f"{existing_slug} and {month_slug}"
            )
        month_numbers[month_number] = month_slug
        month_row = month_rows.setdefault(
            month_slug,
            {
                "number": month_number,
                "name": month_name,
                "batches": {},
            },
        )
        if (
            month_row["number"] != month_number
            or month_row["name"] != month_name
        ):
            raise ValueError(f"Inconsistent metadata for month {month_slug}")
        if batch_number in month_row["batches"]:
            raise ValueError(
                f"Duplicate batch {batch_number} for month {month_slug}"
            )

        subjects: List[TacheTwoSubjectData] = []
        for raw_subject in raw.get("subjects", []):
            subject_number = raw_subject.get("number")
            title = str(raw_subject.get("title", "")).strip()
            prompt = str(raw_subject.get("prompt", "")).strip()
            if not isinstance(subject_number, int) or subject_number < 1:
                raise ValueError(
                    f"{path.name} contains an invalid subject number"
                )
            if not title or not prompt:
                raise ValueError(
                    f"Subject {subject_number} needs a title and prompt"
                )

            questions: List[TacheTwoSubjectQuestionData] = []
            seen_questions = set()
            for raw_question in raw_subject.get("questions", []):
                if isinstance(raw_question, str):
                    text = raw_question.strip()
                    memory_number = None
                    memory_section = None
                else:
                    text = str(raw_question.get("text", "")).strip()
                    memory_section = raw_question.get("memory_section")
                    memory_number = (
                        raw_question.get("memory_number", 1)
                        if memory_section is not None
                        else None
                    )
                if not text or not text.endswith("?"):
                    raise ValueError(
                        f"Every item in subject {subject_number} "
                        "must be a complete question"
                    )
                normalized = text.casefold()
                if normalized in seen_questions:
                    raise ValueError(
                        f"Duplicate question in subject {subject_number}: {text}"
                    )
                seen_questions.add(normalized)
                if memory_section is not None:
                    if (
                        not isinstance(memory_number, int)
                        or not isinstance(memory_section, int)
                        or (memory_number, memory_section)
                        not in memory_sections
                    ):
                        raise ValueError(
                            f"Invalid Memory reference in subject "
                            f"{subject_number}: {memory_number}/"
                            f"{memory_section}"
                        )
                questions.append(
                    TacheTwoSubjectQuestionData(
                        text=text,
                        memory_number=memory_number,
                        memory_section=memory_section,
                    )
                )
            if not questions:
                raise ValueError(f"Subject {subject_number} has no questions")
            subjects.append(
                TacheTwoSubjectData(
                    number=subject_number,
                    title=title,
                    prompt=prompt,
                    questions=tuple(questions),
                )
            )

        if not subjects:
            raise ValueError(f"{path.name} contains no subjects")
        subject_numbers = [subject.number for subject in subjects]
        if subject_numbers != sorted(set(subject_numbers)):
            raise ValueError(
                f"Subjects in {path.name} must be unique and ordered"
            )
        month_row["batches"][batch_number] = TacheTwoSubjectBatchData(
            number=batch_number,
            subjects=tuple(subjects),
        )

    months: List[TacheTwoSubjectMonthData] = []
    for month_slug, month_row in sorted(
        month_rows.items(),
        key=lambda item: item[1]["number"],
    ):
        batches = tuple(
            month_row["batches"][number]
            for number in sorted(month_row["batches"])
        )
        batch_numbers = [batch.number for batch in batches]
        if batch_numbers != list(range(1, len(batches) + 1)):
            raise ValueError(
                f"Batches for {month_slug} must be consecutive from 1"
            )
        subject_numbers = [
            subject.number
            for batch in batches
            for subject in batch.subjects
        ]
        if subject_numbers != list(range(1, len(subject_numbers) + 1)):
            raise ValueError(
                f"Subjects for {month_slug} must be consecutive from 1"
            )
        months.append(
            TacheTwoSubjectMonthData(
                number=month_row["number"],
                slug=month_slug,
                name=month_row["name"],
                batches=batches,
            )
        )

    actual_month_numbers = [month.number for month in months]
    if actual_month_numbers != list(range(1, len(months) + 1)):
        raise ValueError("Tâche 2 months must be consecutive from 1")
    return tuple(months)


def tache_two_subject_content_key(
    month_slug: str,
    batch_number: int,
    subject_number: int,
) -> str:
    return (
        f"tache2:{month_slug}:batch-{batch_number:02d}:"
        f"subject-{subject_number:02d}"
    )


def load_tache_two_subject_themes(
    path: Path = TACHE_TWO_SUBJECT_THEMES_PATH,
) -> Tuple[Tuple[TacheTwoThemeData, ...], Dict[str, str]]:
    """Load the theme taxonomy and the content_key -> theme-slug mapping."""
    data = json.loads(path.read_text(encoding="utf-8"))
    themes = tuple(
        TacheTwoThemeData(
            slug=theme["slug"],
            name=theme["name"],
            icon=theme.get("icon", "messages"),
            order=int(theme["order"]),
        )
        for theme in data["themes"]
    )
    mapping = {
        str(key): str(value) for key, value in data["subjects"].items()
    }
    return themes, mapping


def load_tache_two_equivalent_groups(
    path: Path = TACHE_TWO_EQUIVALENT_GROUPS_PATH,
    *,
    months: Optional[Tuple[TacheTwoSubjectMonthData, ...]] = None,
    subject_themes_path: Path = TACHE_TWO_SUBJECT_THEMES_PATH,
) -> Tuple[TacheTwoEquivalentGroupData, ...]:
    """Load audited groups whose questions and progression are truly shared."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "groups"}
        or data["version"] != 1
    ):
        raise ValueError("Tâche 2 equivalent groups must use version 1")
    if not isinstance(data["groups"], list):
        raise ValueError("Tâche 2 equivalent groups must contain a groups list")

    months = months or load_tache_two_subject_months()
    subjects_by_key = {
        tache_two_subject_content_key(
            month.slug, batch.number, subject.number
        ): subject
        for month in months
        for batch in month.batches
        for subject in batch.subjects
    }
    subject_order = {
        content_key: index
        for index, content_key in enumerate(subjects_by_key)
    }
    _themes, theme_by_key = load_tache_two_subject_themes(
        subject_themes_path
    )
    seen_ids = set()
    seen_members = set()
    groups = []
    for index, row in enumerate(data["groups"], start=1):
        location = f"Tâche 2 equivalent group {index}"
        if not isinstance(row, dict) or set(row) != {
            "id",
            "theme",
            "canonical",
            "members",
        }:
            raise ValueError(f"{location} has invalid fields")
        if not isinstance(row["members"], list):
            raise ValueError(f"{location} members must be a list")
        group_id = str(row["id"]).strip()
        theme = str(row["theme"]).strip()
        canonical = str(row["canonical"]).strip()
        members = tuple(
            str(member).strip() for member in row["members"]
        )
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", group_id):
            raise ValueError(f"{location} has an invalid id")
        if group_id in seen_ids:
            raise ValueError(f"Duplicate Tâche 2 equivalent group {group_id!r}")
        if len(members) < 2 or len(set(members)) != len(members):
            raise ValueError(
                f"{location} needs at least two unique members"
            )
        if canonical not in members:
            raise ValueError(f"{location} must include its canonical subject")
        unknown = set(members) - set(subjects_by_key)
        if unknown:
            raise ValueError(
                f"{location} references unknown subjects: "
                + ", ".join(sorted(unknown))
            )
        duplicate_members = set(members) & seen_members
        if duplicate_members:
            raise ValueError(
                f"{location} repeats grouped subjects: "
                + ", ".join(sorted(duplicate_members))
            )
        wrong_theme = [
            member
            for member in members
            if theme_by_key.get(member) != theme
        ]
        if wrong_theme:
            raise ValueError(
                f"{location} crosses theme boundaries: "
                + ", ".join(wrong_theme)
            )
        expected_canonical = min(
            members,
            key=subject_order.__getitem__,
        )
        if canonical != expected_canonical:
            raise ValueError(
                f"{location} canonical must be {expected_canonical!r}"
            )
        canonical_questions = tuple(
            question.text
            for question in subjects_by_key[canonical].questions
        )
        drifted = [
            member
            for member in members
            if tuple(
                question.text
                for question in subjects_by_key[member].questions
            )
            != canonical_questions
        ]
        if drifted:
            raise ValueError(
                f"{location} does not share its canonical questions: "
                + ", ".join(drifted)
            )
        seen_ids.add(group_id)
        seen_members.update(members)
        groups.append(
            TacheTwoEquivalentGroupData(
                id=group_id,
                theme=theme,
                canonical=canonical,
                members=members,
            )
        )
    return tuple(groups)


def tache_two_category_by_content_key() -> Dict[str, TacheTwoThemeData]:
    themes, mapping = load_tache_two_subject_themes()
    by_slug = {theme.slug: theme for theme in themes}
    return {
        content_key: by_slug[slug]
        for content_key, slug in mapping.items()
    }


def tache_two_theme_name(theme: TacheTwoThemeData) -> str:
    return f"Tâche 2 · {theme.name}"


def tache_two_family_name(theme: TacheTwoThemeData) -> str:
    return f"Tâche 2 · {theme.name}"


def tache_two_themes(
    months: Optional[Tuple[TacheTwoSubjectMonthData, ...]] = None,
) -> List[ThemeData]:
    themes, _ = load_tache_two_subject_themes()
    return [
        ThemeData(
            slug=f"tache-2-{theme.slug}",
            name=tache_two_theme_name(theme),
            display=theme.name,
            order=100 + theme.order,
            color="#d3263a",
            icon=theme.icon,
            task="eo/tache-2",
        )
        for theme in themes
    ]


def tache_two_families(
    months: Optional[Tuple[TacheTwoSubjectMonthData, ...]] = None,
) -> List[Tuple[str, int]]:
    themes, _ = load_tache_two_subject_themes()
    return [
        (tache_two_family_name(theme), 1000 + theme.order)
        for theme in themes
    ]


@dataclass(frozen=True)
class _TacheTwoOccurrence:
    """One Tâche 2 subject as it appears in a given month and batch."""

    content_key: str
    theme: str
    family: str
    number: int
    prompt: str
    questions: Tuple[str, ...]
    body: str
    body_hash: str


def parse_tache_two_responses(
    months: Optional[Tuple[TacheTwoSubjectMonthData, ...]] = None,
) -> List[ResponseData]:
    months = months or load_tache_two_subject_months()
    category_by_key = tache_two_category_by_content_key()
    theme_prompt_numbers: Dict[str, int] = {}
    occurrences: List[_TacheTwoOccurrence] = []
    for month in months:
        for batch in month.batches:
            for subject in batch.subjects:
                content_key = tache_two_subject_content_key(
                    month.slug,
                    batch.number,
                    subject.number,
                )
                category = category_by_key.get(content_key)
                if category is None:
                    raise ValueError(
                        "Tâche 2 subject "
                        f"{content_key} has no theme mapping"
                    )
                theme = tache_two_theme_name(category)
                family = tache_two_family_name(category)
                prompt_number = theme_prompt_numbers.get(theme, 0) + 1
                theme_prompt_numbers[theme] = prompt_number
                questions = tuple(
                    question.text for question in subject.questions
                )
                body = "\n".join(questions)
                occurrences.append(
                    _TacheTwoOccurrence(
                        content_key=content_key,
                        theme=theme,
                        family=family,
                        number=prompt_number,
                        prompt=subject.prompt,
                        questions=questions,
                        body=body,
                        body_hash=hashlib.sha256(
                            body.encode("utf-8")
                        ).hexdigest(),
                    )
                )

    groups: Dict[str, List[_TacheTwoOccurrence]] = {}
    for occurrence in occurrences:
        groups.setdefault(occurrence.body_hash, []).append(occurrence)

    responses = []
    for occurrence in occurrences:
        members = groups[occurrence.body_hash]
        canonical = members[0]
        if occurrence is not canonical:
            continue
        questions = canonical.questions
        responses.append(
            ResponseData(
                content_key=canonical.content_key,
                body_hash=canonical.body_hash,
                theme=canonical.theme,
                family=canonical.family,
                prompt=canonical.prompt,
                reformulation="",
                position="",
                position_claire="",
                nuance="",
                conclusion="",
                body=canonical.body,
                body_html=(
                    "<ol>"
                    + "".join(
                        f"<li>{html.escape(question)}</li>"
                        for question in questions
                    )
                    + "</ol>"
                ),
                arguments=[
                    ArgumentData(
                        order=number,
                        idea=question,
                        developpement="",
                        exemple="",
                        consequence="",
                    )
                    for number, question in enumerate(
                        questions,
                        start=1,
                    )
                ],
                prompts=[
                    PromptData(
                        content_key=member.content_key,
                        theme=member.theme,
                        number=member.number,
                        text=member.prompt,
                        family=member.family,
                        is_canonical=(member is canonical),
                    )
                    for member in members
                ],
            )
        )
    return responses


def tache_two_response_key_by_subject_key(
    responses: Optional[List[ResponseData]] = None,
) -> Dict[str, str]:
    """Map every Tâche 2 subject key onto the shared response it belongs to."""
    if responses is None:
        responses = parse_tache_two_responses()
    return {
        prompt.content_key: response.content_key
        for response in responses
        if response.content_key.startswith("tache2:")
        for prompt in response.prompts
    }


def _tache_two_vocabulary_signature(entries) -> Optional[Tuple]:
    """Comparable view of a vocabulary block, ignoring its phrase ids."""
    if not isinstance(entries, list):
        return None
    return tuple(
        (
            entry.get("kind"),
            entry.get("french"),
            entry.get("english"),
            entry.get("example"),
            entry.get("usage"),
        )
        if isinstance(entry, dict)
        else None
        for entry in entries
    )


def tache_two_phrase_id_merges(
    groups: Optional[Tuple[TacheTwoEquivalentGroupData, ...]] = None,
    directory: Path = TACHE_TWO_VOCABULARY_DIR,
) -> Dict[str, str]:
    """Map retired equivalent-deck phrase ids onto the canonical deck."""
    if groups is None:
        groups = load_tache_two_equivalent_groups()
    entries_by_subject_key = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("subjects", []):
            if isinstance(row, dict):
                entries_by_subject_key[row.get("subject_key")] = row.get(
                    "entries"
                )

    merges = {}
    for group in groups:
        canonical_entries = entries_by_subject_key.get(group.canonical)
        canonical_signature = _tache_two_vocabulary_signature(
            canonical_entries
        )
        if canonical_signature is None:
            raise ValueError(
                f"Missing canonical vocabulary for {group.canonical!r}"
            )
        canonical_ids = tuple(
            entry.get("id") for entry in canonical_entries
        )
        if not all(
            isinstance(phrase_id, str) and phrase_id
            for phrase_id in canonical_ids
        ):
            raise ValueError(
                f"Invalid canonical vocabulary ids for {group.canonical!r}"
            )
        for member in group.members:
            if member == group.canonical:
                continue
            member_entries = entries_by_subject_key.get(member)
            if (
                _tache_two_vocabulary_signature(member_entries)
                != canonical_signature
            ):
                raise ValueError(
                    f"{member!r} does not share canonical vocabulary with "
                    f"{group.canonical!r}"
                )
            for entry, target_id in zip(
                member_entries,
                canonical_ids,
                strict=True,
            ):
                source_id = entry.get("id")
                if not isinstance(source_id, str) or not source_id:
                    raise ValueError(
                        f"Invalid equivalent vocabulary id for {member!r}"
                    )
                previous = merges.setdefault(source_id, target_id)
                if previous != target_id:
                    raise ValueError(
                        f"Conflicting phrase merge for {source_id!r}"
                    )
    return merges


def parse_tache_two_subject_vocabulary(
    responses: Optional[List[ResponseData]] = None,
    directory: Path = TACHE_TWO_VOCABULARY_DIR,
) -> List[PhraseData]:
    if responses is None:
        responses = parse_tache_two_responses()
    response_by_key = {
        response.content_key: response
        for response in responses
        if response.content_key.startswith("tache2:")
    }
    if not response_by_key:
        return []
    response_key_by_subject_key = tache_two_response_key_by_subject_key(
        responses
    )

    seen_subject_keys = set()
    seen_ids = {}
    phrases = []
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ValueError("No Tâche 2 subject-vocabulary JSON files found")
    response_order_by_key = {
        response_key: index
        for index, response_key in enumerate(response_by_key)
    }
    payloads = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError(
                f"{path.name} must use Tâche 2 vocabulary version 1"
            )
        subject_rows = payload.get("subjects")
        if not isinstance(subject_rows, list):
            raise ValueError(f"{path.name} must contain a subjects list")
        first_response_order = min(
            (
                response_order_by_key.get(
                    response_key_by_subject_key.get(row.get("subject_key")),
                    len(response_order_by_key),
                )
                for row in subject_rows
                if isinstance(row, dict)
            ),
            default=len(response_order_by_key),
        )
        payloads.append(
            (first_response_order, path.name, path, subject_rows)
        )

    entries_by_subject_key = {
        row.get("subject_key"): row.get("entries")
        for _, _, _path, subject_rows in payloads
        for row in subject_rows
        if isinstance(row, dict)
    }

    base_order = (
        EXPECTED_PHRASES
        + EXPECTED_UNIQUE * SUBJECT_VOCABULARY_PER_RESPONSE
        + (
            sum(
                1
                for _path in COMPREHENSION_VOCABULARY_DIR.glob("*.json")
            )
            * COMPREHENSION_VOCABULARY_PER_TEST
        )
    )
    for _, _, path, subject_rows in sorted(payloads):
        for subject_index, subject_row in enumerate(subject_rows, start=1):
            location = f"{path.name} subject {subject_index}"
            if not isinstance(subject_row, dict):
                raise ValueError(f"{location} must be an object")
            subject_key = subject_row.get("subject_key")
            response_key = response_key_by_subject_key.get(subject_key)
            if response_key is None:
                raise ValueError(
                    f"{location} references unknown subject {subject_key!r}"
                )
            if subject_key in seen_subject_keys:
                raise ValueError(
                    f"Duplicate Tâche 2 vocabulary for {subject_key!r}"
                )
            seen_subject_keys.add(subject_key)

            if response_key != subject_key:
                # Equivalent subject: it shares the canonical vocabulary.
                if _tache_two_vocabulary_signature(
                    subject_row.get("entries")
                ) != _tache_two_vocabulary_signature(
                    entries_by_subject_key.get(response_key)
                ):
                    raise ValueError(
                        f"{location} shares its questions with "
                        f"{response_key!r} but not its vocabulary"
                    )
                continue

            entries = subject_row.get("entries")
            if not isinstance(entries, list):
                raise ValueError(f"{location} must contain an entries list")
            if (
                len(entries) < TACHE_TWO_VOCABULARY_MIN_PER_RESPONSE
                or len(entries) % SUBJECT_VOCABULARY_PER_KIND
            ):
                raise ValueError(
                    f"{subject_key} must have at least "
                    f"{TACHE_TWO_VOCABULARY_MIN_PER_RESPONSE} vocabulary "
                    f"entries in groups of {SUBJECT_VOCABULARY_PER_KIND}"
                )
            actual_kinds = tuple(
                entry.get("kind") if isinstance(entry, dict) else None
                for entry in entries
            )
            kind_blocks = [
                actual_kinds[
                    start : start + SUBJECT_VOCABULARY_PER_KIND
                ]
                for start in range(
                    0,
                    len(actual_kinds),
                    SUBJECT_VOCABULARY_PER_KIND,
                )
            ]
            block_kinds = []
            for block in kind_blocks:
                if len(set(block)) != 1 or block[0] not in (
                    SUBJECT_VOCABULARY_KINDS
                ):
                    raise ValueError(
                        f"{subject_key} must group each vocabulary kind "
                        f"in sets of {SUBJECT_VOCABULARY_PER_KIND}"
                    )
                block_kinds.append(block[0])
            if len(block_kinds) != len(set(block_kinds)):
                raise ValueError(
                    f"{subject_key} repeats a vocabulary-kind group"
                )

            response = response_by_key[subject_key]
            response_questions = {
                argument.idea for argument in response.arguments
            }
            sources = tuple(
                (prompt.theme, prompt.number)
                for prompt in response.prompts
            )
            sources_raw = "; ".join(
                f"{theme} P{number}" for theme, number in sources
            )
            seen_targets = set()
            for entry_index, entry in enumerate(entries, start=1):
                entry_location = f"{subject_key} entry {entry_index}"
                if not isinstance(entry, dict):
                    raise ValueError(f"{entry_location} must be an object")
                if set(entry) != set(SUBJECT_VOCABULARY_FIELDS):
                    raise ValueError(
                        f"{entry_location} fields must be "
                        f"{SUBJECT_VOCABULARY_FIELDS}"
                    )
                values = {}
                for field_name in SUBJECT_VOCABULARY_FIELDS:
                    value = entry.get(field_name)
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError(
                            f"{entry_location} has an empty "
                            f"{field_name!r} field"
                        )
                    values[field_name] = value.strip()

                phrase_id = values["id"]
                phrase_id_key = phrase_id.casefold()
                if len(phrase_id) > PHRASE_MAX_LENGTHS["id"]:
                    raise ValueError(
                        f"{entry_location} id exceeds "
                        f"{PHRASE_MAX_LENGTHS['id']} characters"
                    )
                if phrase_id_key in seen_ids:
                    raise ValueError(
                        f"Duplicate Tâche 2 vocabulary id {phrase_id!r} "
                        f"in {seen_ids[phrase_id_key]} and {entry_location}"
                    )
                seen_ids[phrase_id_key] = entry_location

                french = values["french"]
                english = values["english"]
                example = values["example"]
                if len(french) > PHRASE_MAX_LENGTHS["expression"]:
                    raise ValueError(
                        f"{entry_location} french target is too long"
                    )
                if len(english) > PHRASE_MAX_LENGTHS["english_cue"]:
                    raise ValueError(
                        f"{entry_location} english cue is too long"
                    )
                target_key = french.casefold()
                if target_key in seen_targets:
                    raise ValueError(
                        f"{subject_key} repeats french target {french!r}"
                    )
                seen_targets.add(target_key)
                if example not in response_questions:
                    raise ValueError(
                        f"{entry_location} example must be copied exactly "
                        "from a prepared response question"
                    )
                if example.casefold().count(target_key) != 1:
                    raise ValueError(
                        f"{entry_location} example must contain its french "
                        "target exactly once"
                    )
                if (
                    values["kind"] == "phrase-modele"
                    and example.casefold() == target_key
                ):
                    raise ValueError(
                        f"{entry_location} phrase model needs a contextual "
                        "example, not a duplicate target"
                    )

                phrases.append(
                    PhraseData(
                        phrase_id=phrase_id,
                        tier="subject",
                        category=SUBJECT_VOCABULARY_CATEGORIES[
                            values["kind"]
                        ],
                        english_cue=english,
                        expression=french,
                        anchor=french,
                        example=example,
                        note=values["usage"],
                        sources_raw=sources_raw,
                        sources=sources,
                        order=base_order + len(phrases) + 1,
                    )
                )

    missing = sorted(set(response_key_by_subject_key) - seen_subject_keys)
    if missing:
        raise ValueError(
            "Missing Tâche 2 subject vocabulary for: "
            + ", ".join(missing)
        )
    return phrases


def parse_tache_two_theme_vocabulary(
    responses: Optional[List[ResponseData]] = None,
    directory: Path = TACHE_TWO_THEME_VOCABULARY_DIR,
) -> List[PhraseData]:
    """Validate and parse the reusable vocabulary for every Tâche 2 theme."""
    if responses is None:
        responses = parse_tache_two_responses()

    themes, subject_theme_by_key = load_tache_two_subject_themes()
    theme_by_slug = {theme.slug: theme for theme in themes}
    source_by_theme = {}
    for response in responses:
        theme_slug = subject_theme_by_key.get(response.content_key)
        if theme_slug is None or not response.prompts:
            continue
        prompt = response.prompts[0]
        source_by_theme.setdefault(
            theme_slug,
            (prompt.theme, prompt.number),
        )
    missing_sources = sorted(set(theme_by_slug) - set(source_by_theme))
    if missing_sources:
        raise ValueError(
            "No representative Tâche 2 subject found for themes: "
            + ", ".join(missing_sources)
        )

    paths = sorted(directory.glob("*.json"))
    expected_file_names = {f"{theme.slug}.json" for theme in themes}
    actual_file_names = {path.name for path in paths}
    if actual_file_names != expected_file_names:
        missing = sorted(expected_file_names - actual_file_names)
        unexpected = sorted(actual_file_names - expected_file_names)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise ValueError(
            "Tâche 2 theme-vocabulary files do not match the theme taxonomy: "
            + "; ".join(details)
        )

    payload_by_theme = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name} must contain a JSON object")
        if set(payload) != {"version", "theme", "name", "entries"}:
            raise ValueError(
                f"{path.name} must contain version, theme, name, and entries"
            )
        if payload["version"] != 1:
            raise ValueError(
                f"{path.name} must use Tâche 2 theme-vocabulary version 1"
            )
        theme_slug = payload["theme"]
        theme = theme_by_slug.get(theme_slug)
        if theme is None or path.name != f"{theme_slug}.json":
            raise ValueError(f"{path.name} has an invalid theme slug")
        if payload["name"] != theme.name:
            raise ValueError(
                f"{path.name} must use the theme name {theme.name!r}"
            )
        payload_by_theme[theme_slug] = payload

    seen_ids = {}
    seen_targets = {}
    phrases = []
    base_order = 800_000
    expected_kinds = tuple(
        kind
        for kind in TACHE_TWO_THEME_VOCABULARY_KINDS
        for _ in range(TACHE_TWO_THEME_VOCABULARY_PER_KIND)
    )
    for theme in themes:
        entries = payload_by_theme[theme.slug]["entries"]
        if not isinstance(entries, list):
            raise ValueError(f"{theme.slug}.json must contain an entries list")
        if len(entries) != TACHE_TWO_THEME_VOCABULARY_PER_THEME:
            raise ValueError(
                f"{theme.slug}.json must contain exactly "
                f"{TACHE_TWO_THEME_VOCABULARY_PER_THEME} entries"
            )
        actual_kinds = tuple(
            entry.get("kind") if isinstance(entry, dict) else None
            for entry in entries
        )
        if actual_kinds != expected_kinds:
            raise ValueError(
                f"{theme.slug}.json must group exactly "
                f"{TACHE_TWO_THEME_VOCABULARY_PER_KIND} entries for each "
                "kind in the documented order"
            )

        source = source_by_theme[theme.slug]
        sources_raw = f"{source[0]} P{source[1]}"
        for entry_index, entry in enumerate(entries, start=1):
            location = f"{theme.slug}.json entry {entry_index}"
            if not isinstance(entry, dict):
                raise ValueError(f"{location} must be an object")
            if set(entry) != set(TACHE_TWO_THEME_VOCABULARY_FIELDS):
                raise ValueError(
                    f"{location} fields must be "
                    f"{TACHE_TWO_THEME_VOCABULARY_FIELDS}"
                )
            values = {}
            for field_name in TACHE_TWO_THEME_VOCABULARY_FIELDS:
                value = entry.get(field_name)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"{location} has an empty {field_name!r} field"
                    )
                values[field_name] = value.strip()

            phrase_id = values["id"]
            phrase_id_key = phrase_id.casefold()
            if len(phrase_id) > PHRASE_MAX_LENGTHS["id"]:
                raise ValueError(
                    f"{location} id exceeds "
                    f"{PHRASE_MAX_LENGTHS['id']} characters"
                )
            if phrase_id_key in seen_ids:
                raise ValueError(
                    f"Duplicate Tâche 2 theme-vocabulary id {phrase_id!r} "
                    f"in {seen_ids[phrase_id_key]} and {location}"
                )
            seen_ids[phrase_id_key] = location

            french = values["french"]
            anchor = values["anchor"]
            english = values["english"]
            example = values["example"]
            if len(french) > PHRASE_MAX_LENGTHS["expression"]:
                raise ValueError(f"{location} french target is too long")
            if len(anchor) > PHRASE_MAX_LENGTHS["anchor"]:
                raise ValueError(f"{location} anchor is too long")
            if len(english) > PHRASE_MAX_LENGTHS["english_cue"]:
                raise ValueError(f"{location} english cue is too long")
            target_key = french.casefold()
            if target_key in seen_targets:
                raise ValueError(
                    f"Duplicate Tâche 2 theme-vocabulary target {french!r} "
                    f"in {seen_targets[target_key]} and {location}"
                )
            seen_targets[target_key] = location
            anchor_key = anchor.casefold()
            noun_match = TACHE_TWO_THEME_NOUN_SUFFIX_RE.search(french)
            if values["kind"] == "mot-cle":
                if noun_match:
                    noun_target = french[: noun_match.start()]
                    if anchor != noun_target:
                        raise ValueError(
                            f"{location} noun anchor must exactly match the "
                            "article and noun without its gender marker"
                        )
                    article_match = TACHE_TWO_THEME_NOUN_ARTICLE_RE.match(
                        noun_target
                    )
                    if article_match is None:
                        raise ValueError(
                            f"{location} noun must begin with an article"
                        )
                    article = (
                        article_match.group("article") or "l'"
                    ).casefold()
                    gender = noun_match.group("gender")
                    plural = bool(noun_match.group("plural"))
                    if (
                        article in {"un", "le"} and (gender != "m" or plural)
                        or article in {"une", "la"}
                        and (gender != "f" or plural)
                        or article in {"les", "des"} and not plural
                        or article == "l'" and plural
                    ):
                        raise ValueError(
                            f"{location} article and gender/number marker "
                            "do not agree"
                        )
                elif not TACHE_TWO_THEME_INFINITIVE_RE.match(french):
                    raise ValueError(
                        f"{location} noun must include an article and a "
                        "gender/number marker"
                    )
            elif noun_match:
                raise ValueError(
                    f"{location} gender/number markers are reserved for "
                    "mot-cle noun entries"
                )
            if example.casefold().count(anchor_key) != 1:
                raise ValueError(
                    f"{location} example must contain its anchor exactly once"
                )
            if not example.endswith("?"):
                raise ValueError(
                    f"{location} example must be a direct question ending in ?"
                )
            if example.casefold() == anchor_key:
                raise ValueError(
                    f"{location} needs a contextual example, not a duplicate "
                    "anchor"
                )

            phrases.append(
                PhraseData(
                    phrase_id=phrase_id,
                    tier="theme",
                    category=TACHE_TWO_THEME_VOCABULARY_CATEGORIES[
                        values["kind"]
                    ],
                    english_cue=english,
                    expression=french,
                    anchor=anchor,
                    example=example,
                    note=values["usage"],
                    sources_raw=sources_raw,
                    sources=(source,),
                    order=base_order + len(phrases) + 1,
                )
            )
    return phrases


def parse_eo_tache_three_theme_vocabulary(
    responses: Optional[List[ResponseData]] = None,
    directory: Path = EO_TACHE_THREE_THEME_VOCABULARY_DIR,
) -> List[PhraseData]:
    """Validate and parse the argumentative vocabulary for EO Tâche 3."""
    if responses is None:
        responses = parse_responses()

    themes = tuple(
        theme
        for theme in load_themes()
        if theme.task == "/".join(EO_TACHE_THREE_TASK)
    )
    theme_by_slug = {theme.slug: theme for theme in themes}
    theme_by_name = {theme.name: theme for theme in themes}
    source_by_theme = {}
    for response in responses:
        for prompt in response.prompts:
            theme = theme_by_name.get(prompt.theme)
            if theme is not None:
                source_by_theme.setdefault(
                    theme.slug,
                    (prompt.theme, prompt.number),
                )
    missing_sources = sorted(set(theme_by_slug) - set(source_by_theme))
    if missing_sources:
        raise ValueError(
            "No representative EO Tâche 3 subject found for themes: "
            + ", ".join(missing_sources)
        )

    paths = sorted(directory.glob("*.json"))
    expected_file_names = {f"{theme.slug}.json" for theme in themes}
    actual_file_names = {path.name for path in paths}
    if actual_file_names != expected_file_names:
        missing = sorted(expected_file_names - actual_file_names)
        unexpected = sorted(actual_file_names - expected_file_names)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise ValueError(
            "EO Tâche 3 theme-vocabulary files do not match the theme "
            "taxonomy: " + "; ".join(details)
        )

    payload_by_theme = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name} must contain a JSON object")
        if set(payload) != {"version", "theme", "name", "entries"}:
            raise ValueError(
                f"{path.name} must contain version, theme, name, and entries"
            )
        if payload["version"] != 1:
            raise ValueError(
                f"{path.name} must use EO Tâche 3 theme-vocabulary version 1"
            )
        theme_slug = payload["theme"]
        theme = theme_by_slug.get(theme_slug)
        if theme is None or path.name != f"{theme_slug}.json":
            raise ValueError(f"{path.name} has an invalid theme slug")
        if payload["name"] != theme.display:
            raise ValueError(
                f"{path.name} must use the theme name {theme.display!r}"
            )
        payload_by_theme[theme_slug] = payload

    theme_id_codes = {
        "culture": "cu",
        "famille": "fa",
        "education": "ed",
        "sante": "sa",
        "technologie": "te",
        "environnement": "en",
        "economie": "ec",
    }
    kind_id_codes = {
        "notion-cle": "n",
        "verbe-collocation": "v",
        "expression-idiomatique": "i",
        "construction-argumentative": "c",
    }
    expected_kinds = tuple(
        kind
        for kind in EO_TACHE_THREE_THEME_VOCABULARY_KINDS
        for _ in range(EO_TACHE_THREE_THEME_VOCABULARY_PER_KIND)
    )
    seen_ids = {}
    seen_targets = {}
    phrases = []
    base_order = 850_000
    for theme in themes:
        entries = payload_by_theme[theme.slug]["entries"]
        if not isinstance(entries, list):
            raise ValueError(f"{theme.slug}.json must contain an entries list")
        if len(entries) != EO_TACHE_THREE_THEME_VOCABULARY_PER_THEME:
            raise ValueError(
                f"{theme.slug}.json must contain exactly "
                f"{EO_TACHE_THREE_THEME_VOCABULARY_PER_THEME} entries"
            )
        actual_kinds = tuple(
            entry.get("kind") if isinstance(entry, dict) else None
            for entry in entries
        )
        if actual_kinds != expected_kinds:
            raise ValueError(
                f"{theme.slug}.json must group exactly "
                f"{EO_TACHE_THREE_THEME_VOCABULARY_PER_KIND} entries for "
                "each kind in the documented order"
            )

        source = source_by_theme[theme.slug]
        sources_raw = f"{source[0]} P{source[1]}"
        kind_positions = {
            kind: 0 for kind in EO_TACHE_THREE_THEME_VOCABULARY_KINDS
        }
        for entry_index, entry in enumerate(entries, start=1):
            location = f"{theme.slug}.json entry {entry_index}"
            if not isinstance(entry, dict):
                raise ValueError(f"{location} must be an object")
            if set(entry) != set(EO_TACHE_THREE_THEME_VOCABULARY_FIELDS):
                raise ValueError(
                    f"{location} fields must be "
                    f"{EO_TACHE_THREE_THEME_VOCABULARY_FIELDS}"
                )
            values = {}
            for field_name in EO_TACHE_THREE_THEME_VOCABULARY_FIELDS:
                value = entry.get(field_name)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"{location} has an empty {field_name!r} field"
                    )
                values[field_name] = value.strip()

            kind = values["kind"]
            kind_positions[kind] += 1
            expected_id = (
                f"t3{theme_id_codes[theme.slug]}{kind_id_codes[kind]}"
                f"{kind_positions[kind]:02d}"
            )
            phrase_id = values["id"]
            if phrase_id != expected_id:
                raise ValueError(
                    f"{location} must use the id {expected_id!r}"
                )
            phrase_id_key = phrase_id.casefold()
            if len(phrase_id) > PHRASE_MAX_LENGTHS["id"]:
                raise ValueError(
                    f"{location} id exceeds "
                    f"{PHRASE_MAX_LENGTHS['id']} characters"
                )
            if phrase_id_key in seen_ids:
                raise ValueError(
                    f"Duplicate EO Tâche 3 theme-vocabulary id "
                    f"{phrase_id!r} in {seen_ids[phrase_id_key]} and "
                    f"{location}"
                )
            seen_ids[phrase_id_key] = location

            french = values["french"]
            anchor = values["anchor"]
            english = values["english"]
            example = values["example"]
            usage = values["usage"]
            if len(french) > PHRASE_MAX_LENGTHS["expression"]:
                raise ValueError(f"{location} french target is too long")
            if len(anchor) > PHRASE_MAX_LENGTHS["anchor"]:
                raise ValueError(f"{location} anchor is too long")
            if len(english) > PHRASE_MAX_LENGTHS["english_cue"]:
                raise ValueError(f"{location} english cue is too long")
            target_key = french.casefold()
            if target_key in seen_targets:
                raise ValueError(
                    f"Duplicate EO Tâche 3 theme-vocabulary target "
                    f"{french!r} in {seen_targets[target_key]} and "
                    f"{location}"
                )
            seen_targets[target_key] = location

            noun_match = TACHE_TWO_THEME_NOUN_SUFFIX_RE.search(french)
            if kind == "notion-cle":
                if noun_match is None:
                    raise ValueError(
                        f"{location} notion must include a gender/number "
                        "marker"
                    )
                noun_target = french[: noun_match.start()]
                if anchor != noun_target:
                    raise ValueError(
                        f"{location} notion anchor must exactly match the "
                        "article and noun without its gender marker"
                    )
                article_match = TACHE_TWO_THEME_NOUN_ARTICLE_RE.match(
                    noun_target
                )
                if article_match is None:
                    raise ValueError(
                        f"{location} notion must begin with an article"
                    )
                article = (
                    article_match.group("article") or "l'"
                ).casefold()
                gender = noun_match.group("gender")
                plural = bool(noun_match.group("plural"))
                if (
                    article in {"un", "le"} and (gender != "m" or plural)
                    or article in {"une", "la"} and (gender != "f" or plural)
                    or article in {"les", "des"} and not plural
                    or article == "l'" and plural
                ):
                    raise ValueError(
                        f"{location} article and gender/number marker do not "
                        "agree"
                    )
                usage_match = EO_TACHE_THREE_NOTION_USAGE_RE.match(usage)
                expected_usage_gender = (
                    "masculin" if gender == "m" else "féminin"
                )
                expected_form = "singulier" if plural else "pluriel"
                if (
                    usage_match is None
                    or usage_match.group("gender") != expected_usage_gender
                    or bool(usage_match.group("plural")) != plural
                    or usage_match.group("form") != expected_form
                ):
                    raise ValueError(
                        f"{location} usage must state the notion's gender and "
                        f"{expected_form} form"
                    )
            elif noun_match is not None:
                raise ValueError(
                    f"{location} gender/number markers are reserved for "
                    "notion-cle entries"
                )
            elif kind == "verbe-collocation":
                if EO_TACHE_THREE_VERB_USAGE_RE.match(usage) is None:
                    raise ValueError(
                        f"{location} usage must state the infinitive and "
                        "governed construction"
                    )
            elif kind == "expression-idiomatique":
                if not usage.startswith("Expression "):
                    raise ValueError(
                        f"{location} usage must identify the expression"
                    )
            elif not usage.startswith("Construction argumentative — "):
                raise ValueError(
                    f"{location} usage must identify the argumentative "
                    "construction"
                )

            if example.casefold().count(anchor.casefold()) != 1:
                raise ValueError(
                    f"{location} example must contain its anchor exactly once"
                )
            if not example.endswith((".", "!", "…")):
                raise ValueError(
                    f"{location} example must be an argumentative statement"
                )
            if example.casefold() == anchor.casefold():
                raise ValueError(
                    f"{location} needs a contextual example, not a duplicate "
                    "anchor"
                )

            phrases.append(
                PhraseData(
                    phrase_id=phrase_id,
                    tier="theme",
                    category=EO_TACHE_THREE_THEME_VOCABULARY_CATEGORIES[kind],
                    english_cue=english,
                    expression=french,
                    anchor=anchor,
                    example=example,
                    note=usage,
                    sources_raw=sources_raw,
                    sources=(source,),
                    order=base_order + len(phrases) + 1,
                )
            )
    return phrases


@dataclass(frozen=True)
class EeTacheThreeCombinaison:
    content_key: str
    combinaison: str
    position: int
    sujet: str
    heading: str
    document1: str
    document2: str
    synthese: str
    point_de_vue: str
    title_missing: bool
    document2_missing: bool
    documents_identical: bool
    document1_invalid: bool

    @property
    def has_source_issue(self) -> bool:
        return any(
            (
                self.title_missing,
                self.document2_missing,
                self.documents_identical,
                self.document1_invalid,
            )
        )


@dataclass(frozen=True)
class EeTacheThreeMonth:
    number: int
    slug: str
    name: str
    combinaisons: Tuple[EeTacheThreeCombinaison, ...]


def ee_tache_three_theme_name(month: EeTacheThreeMonth) -> str:
    return f"EE · Tâche 3 · {month.name}"


def ee_tache_three_family_name(month: EeTacheThreeMonth) -> str:
    return f"EE Tâche 3 · {month.name}"


def ee_subject_theme_name(tache: int, theme: EeSubjectThemeData) -> str:
    return f"EE · Tâche {tache} · {theme.name}"


def ee_subject_family_name(tache: int, theme: EeSubjectThemeData) -> str:
    return f"EE Tâche {tache} · {theme.name}"


def _ee_tache_three_normalize(text: str) -> str:
    return text.lower().replace("\u2019", "'").replace("\u0153", "oe")


def _ee_tache_three_parse_essays(md_text: str) -> List[Dict[str, str]]:
    """Return ordered per-combinaison essay blocks from a responses/*.md file."""
    text = md_text.replace("\r\n", "\n")
    blocks = re.split(r"(?m)^## Combinaison ", text)
    essays: List[Dict[str, str]] = []
    for block in blocks[1:]:
        label_line, _, rest = block.partition("\n")
        label = "Combinaison " + label_line.strip()
        sujet_match = re.search(r"\*\*Sujet\s*:\*\*\s*(.*)", rest)
        heading_match = re.search(r"(?m)^###\s+(.*)", rest)
        synthese_match = re.search(
            r"\*\*Partie 1[^\n]*\*\*\s*\n+(.+?)(?=\n\*\*Partie 2)",
            rest,
            re.S,
        )
        point_match = re.search(
            r"\*\*Partie 2[^\n]*\*\*\s*\n+(.+?)(?=\n\*\*Total)",
            rest,
            re.S,
        )
        heading = heading_match.group(1).strip() if heading_match else ""
        synthese = synthese_match.group(1).strip() if synthese_match else ""
        point_de_vue = point_match.group(1).strip() if point_match else ""
        if not heading:
            raise ValueError(f"{label} is missing its '###' heading")
        if not synthese:
            raise ValueError(f"{label} is missing its Partie 1 (Synthèse)")
        if not point_de_vue:
            raise ValueError(f"{label} is missing its Partie 2 (Point de vue)")
        essays.append(
            {
                "label": label,
                "sujet": sujet_match.group(1).strip() if sujet_match else "",
                "heading": heading,
                "synthese": synthese,
                "point_de_vue": point_de_vue,
            }
        )
    return essays


def load_ee_tache_three_months(
    subjects_dir: Path = EE_TACHE_THREE_SUBJECTS_DIR,
    responses_dir: Path = EE_TACHE_THREE_RESPONSES_DIR,
) -> Tuple[EeTacheThreeMonth, ...]:
    """Load EE Tâche 3 months by zipping subjects, essays and vocab keys.

    Subjects provide the sujet + source documents, the responses/*.md file
    provides the model essay (heading + Partie 1/2), and the vocabulary file
    provides the authoritative ``response_key`` used as the content key.
    All three are verified to be aligned by position for every month.
    """
    months: List[EeTacheThreeMonth] = []
    subject_paths = sorted(subjects_dir.glob("*.json"))
    if not subject_paths:
        raise ValueError("No EE Tâche 3 subject JSON files found")
    for subject_path in subject_paths:
        slug = subject_path.stem
        subjects = json.loads(subject_path.read_text(encoding="utf-8"))
        month_row = subjects.get("month")
        if not isinstance(month_row, dict):
            raise ValueError(f"{subject_path.name} is missing its month block")
        sujets = subjects.get("sujets")
        if not isinstance(sujets, list) or not sujets:
            raise ValueError(f"{subject_path.name} must contain a sujets list")

        vocab_path = EE_TACHE_THREE_VOCABULARY_DIR / f"{slug}.json"
        vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
        vocab_rows = vocab.get("responses")
        if not isinstance(vocab_rows, list):
            raise ValueError(f"{vocab_path.name} must contain a responses list")

        essays = _ee_tache_three_parse_essays(
            (responses_dir / f"{slug}.md").read_text(encoding="utf-8")
        )

        if not (len(sujets) == len(vocab_rows) == len(essays)):
            raise ValueError(
                f"{slug}: misaligned counts — subjects {len(sujets)}, "
                f"vocab {len(vocab_rows)}, essays {len(essays)}"
            )

        combinaisons: List[EeTacheThreeCombinaison] = []
        for position, (subject, vocab_row, essay) in enumerate(
            zip(sujets, vocab_rows, essays), start=1
        ):
            label = subject.get("combinaison", "")
            if not (label == vocab_row.get("combinaison") == essay["label"]):
                raise ValueError(
                    f"{slug} position {position}: combinaison label mismatch "
                    f"({label!r}, {vocab_row.get('combinaison')!r}, "
                    f"{essay['label']!r})"
                )
            content_key = vocab_row.get("response_key", "")
            if not content_key.startswith(EE_TACHE_THREE_CONTENT_PREFIX):
                raise ValueError(
                    f"{slug} position {position}: bad response_key "
                    f"{content_key!r}"
                )
            heading = essay["heading"]
            flags = subject.get("flags") or {}
            deduced_theme = str(flags.get("deduced_theme") or "").strip()
            sujet = (
                (subject.get("sujet") or "").strip()
                or (deduced_theme[:1].upper() + deduced_theme[1:])
                or heading
            )
            combinaisons.append(
                EeTacheThreeCombinaison(
                    content_key=content_key,
                    combinaison=label,
                    position=position,
                    sujet=sujet,
                    heading=heading,
                    document1=(subject.get("document1") or "").strip(),
                    document2=(subject.get("document2") or "").strip(),
                    synthese=essay["synthese"],
                    point_de_vue=essay["point_de_vue"],
                    title_missing=bool(flags.get("title_missing")),
                    document2_missing=bool(flags.get("document2_missing")),
                    documents_identical=bool(flags.get("documents_identical")),
                    document1_invalid=bool(flags.get("document1_invalid")),
                )
            )
        months.append(
            EeTacheThreeMonth(
                number=int(month_row["number"]),
                slug=month_row.get("slug", slug),
                name=month_row["name"],
                combinaisons=tuple(combinaisons),
            )
        )

    months.sort(key=lambda month: month.number)
    numbers = [month.number for month in months]
    if len(numbers) != len(set(numbers)):
        raise ValueError("EE Tâche 3 months must have unique numbers")
    return tuple(months)


def ee_subject_content_key(
    tache: int,
    month_slug: str,
    combinaison: str,
) -> str:
    """Build the stable content key for one EE combinaison.

    ``combinaison`` is the source label ("Combinaison 3"); the optional
    ``-bis`` suffix disambiguates the months where the source published two
    panels under the same number (mai 2025).
    """
    prefix = EE_TACHE_CONTENT_PREFIXES[tache]
    number = combinaison.strip().lower().replace("combinaison ", "")
    return f"{prefix}{month_slug}:combinaison-{number}"


def load_ee_subject_keys(tache: int) -> Tuple[str, ...]:
    """Return every content key for an EE tâche, in published order.

    Tâches 1 and 2 key off their own ``subjects/<mois>.json`` files; Tâche 3
    reuses the authoritative ``response_key`` already stored in its
    vocabulary files so a single subject never gains two identities.
    """
    directory = EE_TACHE_DIRS[tache]
    keys: List[str] = []
    for month_slug in EE_MONTH_ORDER:
        if tache == 3:
            path = EE_TACHE_THREE_VOCABULARY_DIR / f"{month_slug}.json"
            rows = json.loads(path.read_text(encoding="utf-8"))["responses"]
            keys.extend(str(row["response_key"]) for row in rows)
            continue
        path = directory / "subjects" / f"{month_slug}.json"
        rows = json.loads(path.read_text(encoding="utf-8"))["sujets"]
        keys.extend(str(row["key"]) for row in rows)
    if len(keys) != len(set(keys)):
        raise ValueError(f"EE Tâche {tache} content keys must be unique")
    prefix = EE_TACHE_CONTENT_PREFIXES[tache]
    bad = [key for key in keys if not key.startswith(prefix)]
    if bad:
        raise ValueError(
            f"EE Tâche {tache} keys must start with {prefix!r}: "
            + ", ".join(bad[:3])
        )
    return tuple(keys)


def load_ee_subject_themes(
    tache: int,
    path: Optional[Path] = None,
) -> Tuple[Tuple[EeSubjectThemeData, ...], Dict[str, str]]:
    """Load an EE theme taxonomy plus its content_key -> theme-slug map."""
    path = path or EE_TACHE_DIRS[tache] / "subject_themes.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"themes", "subjects"}:
        raise ValueError(f"{path.name} must hold themes and subjects")
    themes = tuple(
        EeSubjectThemeData(
            slug=str(theme["slug"]),
            name=str(theme["name"]),
            icon=str(theme.get("icon", "pen-line")),
            order=int(theme["order"]),
        )
        for theme in data["themes"]
    )
    if not themes:
        raise ValueError(f"{path.name} needs at least one theme")
    slugs = [theme.slug for theme in themes]
    if len(slugs) != len(set(slugs)):
        raise ValueError(f"{path.name} has duplicate theme slugs")
    orders = [theme.order for theme in themes]
    if sorted(orders) != list(range(1, len(themes) + 1)):
        raise ValueError(f"{path.name} theme orders must be 1..n")
    for theme in themes:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", theme.slug):
            raise ValueError(f"{path.name} has an invalid slug {theme.slug!r}")

    mapping = {str(key): str(value) for key, value in data["subjects"].items()}
    unknown = sorted(set(mapping.values()) - set(slugs))
    if unknown:
        raise ValueError(
            f"{path.name} references unknown themes: " + ", ".join(unknown)
        )
    keys = load_ee_subject_keys(tache)
    missing = [key for key in keys if key not in mapping]
    if missing:
        raise ValueError(
            f"{path.name} is missing {len(missing)} subject(s), e.g. "
            + ", ".join(missing[:3])
        )
    extra = sorted(set(mapping) - set(keys))
    if extra:
        raise ValueError(
            f"{path.name} maps unknown subjects: " + ", ".join(extra[:3])
        )
    return themes, mapping


def _ee_subject_signature_text(text: str) -> str:
    """Fold an EE prompt for equivalence checks.

    The source republishes the same sujet with cosmetic drift and a few stable
    editorial artifacts (``week-end``/``weekend``, ``RDV``, a prefixed analysis
    instruction, or an accidentally doubled prompt). Signatures remove only
    those audited variants alongside case, accents, punctuation and whitespace.
    """
    folded = unicodedata.normalize(
        "NFD",
        text.lower().replace("œ", "oe").replace("æ", "ae"),
    )
    folded = "".join(
        char for char in folded if unicodedata.category(char) != "Mn"
    )
    signature = re.sub(r"[^a-z0-9]+", " ", folded).strip()
    signature = re.sub(
        r"^analysez le sujet d examen suivant\s+",
        "",
        signature,
    )
    signature = re.sub(r"\betc\b", "", signature)
    signature = signature.replace("week end", "weekend")
    signature = signature.replace("france televisions", "france television")
    signature = re.sub(r"\brdv\b", "rendez vous", signature)
    signature = " ".join(signature.split())
    words = signature.split()
    midpoint = len(words) // 2
    if len(words) % 2 == 0 and words[:midpoint] == words[midpoint:]:
        signature = " ".join(words[:midpoint])
    return signature


def _ee_subject_signatures(tache: int) -> Dict[str, str]:
    """Map every content key to a normalised copy of its full prompt text."""
    directory = EE_TACHE_DIRS[tache]
    signatures: Dict[str, str] = {}
    for month_slug in EE_MONTH_ORDER:
        if tache == 3:
            subjects = json.loads(
                (EE_TACHE_THREE_SUBJECTS_DIR / f"{month_slug}.json")
                .read_text(encoding="utf-8")
            )["sujets"]
            vocab = json.loads(
                (EE_TACHE_THREE_VOCABULARY_DIR / f"{month_slug}.json")
                .read_text(encoding="utf-8")
            )["responses"]
            for subject, row in zip(subjects, vocab):
                # A Tâche 3 exam item *is* its pair of source documents; the
                # title is editorial and drifts between republications, so it
                # is deliberately excluded from the signature.
                documents = sorted(
                    _ee_subject_signature_text(
                        str(subject.get(field) or "")
                    )
                    for field in ("document1", "document2")
                )
                signatures[str(row["response_key"])] = "|".join(documents)
            continue
        rows = json.loads(
            (directory / "subjects" / f"{month_slug}.json")
            .read_text(encoding="utf-8")
        )["sujets"]
        for row in rows:
            signatures[str(row["key"])] = _ee_subject_signature_text(
                str(row["prompt"])
            )
    return signatures


def load_ee_equivalent_groups(
    tache: int,
    path: Optional[Path] = None,
    *,
    subject_themes_path: Optional[Path] = None,
) -> Tuple[EeEquivalentGroupData, ...]:
    """Load audited EE groups whose sujets the source republished verbatim."""
    path = path or EE_TACHE_DIRS[tache] / "equivalent_groups.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "groups"}
        or data["version"] != 1
    ):
        raise ValueError(f"EE Tâche {tache} equivalent groups must use version 1")
    if not isinstance(data["groups"], list):
        raise ValueError(
            f"EE Tâche {tache} equivalent groups must contain a groups list"
        )

    keys = load_ee_subject_keys(tache)
    subject_order = {key: index for index, key in enumerate(keys)}
    signatures = _ee_subject_signatures(tache)
    _themes, theme_by_key = load_ee_subject_themes(tache, subject_themes_path)

    seen_ids: set = set()
    seen_members: set = set()
    groups: List[EeEquivalentGroupData] = []
    for index, row in enumerate(data["groups"], start=1):
        location = f"EE Tâche {tache} equivalent group {index}"
        if not isinstance(row, dict) or set(row) != {
            "id",
            "theme",
            "canonical",
            "members",
        }:
            raise ValueError(f"{location} has invalid fields")
        if not isinstance(row["members"], list):
            raise ValueError(f"{location} members must be a list")
        group_id = str(row["id"]).strip()
        theme = str(row["theme"]).strip()
        canonical = str(row["canonical"]).strip()
        members = tuple(str(member).strip() for member in row["members"])
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", group_id):
            raise ValueError(f"{location} has an invalid id")
        if group_id in seen_ids:
            raise ValueError(
                f"Duplicate EE Tâche {tache} equivalent group {group_id!r}"
            )
        if len(members) < 2 or len(set(members)) != len(members):
            raise ValueError(f"{location} needs at least two unique members")
        if canonical not in members:
            raise ValueError(f"{location} must include its canonical subject")
        unknown = set(members) - set(subject_order)
        if unknown:
            raise ValueError(
                f"{location} references unknown subjects: "
                + ", ".join(sorted(unknown))
            )
        repeated = set(members) & seen_members
        if repeated:
            raise ValueError(
                f"{location} repeats grouped subjects: "
                + ", ".join(sorted(repeated))
            )
        wrong_theme = [
            member for member in members if theme_by_key.get(member) != theme
        ]
        if wrong_theme:
            raise ValueError(
                f"{location} crosses theme boundaries: " + ", ".join(wrong_theme)
            )
        expected_canonical = min(members, key=subject_order.__getitem__)
        if canonical != expected_canonical:
            raise ValueError(f"{location} canonical must be {expected_canonical!r}")
        drifted = []
        for member in members:
            if signatures[member] == signatures[canonical]:
                continue
            if tache == 3:
                # Tâche 3 republishes the same document pair with occasional
                # typos, dropped speaker credits, or the documents reversed.
                # Groups are explicit and audited; this narrow floor accepts
                # those variants without turning similarity into auto-grouping.
                similarity = difflib.SequenceMatcher(
                    None,
                    signatures[member].split(),
                    signatures[canonical].split(),
                    autojunk=False,
                ).ratio()
                if similarity >= 0.93:
                    continue
            drifted.append(member)
        if drifted:
            raise ValueError(
                f"{location} does not share its canonical wording: "
                + ", ".join(drifted)
            )
        seen_ids.add(group_id)
        seen_members.update(members)
        groups.append(
            EeEquivalentGroupData(
                id=group_id,
                theme=theme,
                canonical=canonical,
                members=members,
            )
        )
    return tuple(groups)


def ee_theme_by_content_key(tache: int) -> Dict[str, EeSubjectThemeData]:
    themes, mapping = load_ee_subject_themes(tache)
    by_slug = {theme.slug: theme for theme in themes}
    return {key: by_slug[slug] for key, slug in mapping.items()}


def ee_canonical_by_content_key(tache: int) -> Dict[str, str]:
    """Map each grouped subject to the canonical sujet that represents it."""
    return {
        member: group.canonical
        for group in load_ee_equivalent_groups(tache)
        for member in group.members
    }


def ee_writing_sujet_slug(content_key: str) -> str:
    """Return the stable WritingSujet slug for a Tâche 1 or 2 source key."""
    prefix = next(
        (
            EE_TACHE_CONTENT_PREFIXES[tache]
            for tache in EE_WRITING_TASKS
            if content_key.startswith(EE_TACHE_CONTENT_PREFIXES[tache])
        ),
        "",
    )
    if not prefix:
        raise ValueError(f"Invalid EE writing content key {content_key!r}")
    slug = content_key.removeprefix(prefix).replace(":", "-")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise ValueError(f"Invalid EE writing sujet slug {slug!r}")
    return slug


@lru_cache(maxsize=2)
def ee_writing_canonical_slug_by_slug(tache: int) -> Dict[str, str]:
    """Map all writing occurrence slugs onto their shared canonical slug."""
    if tache not in EE_WRITING_TASKS:
        raise ValueError("EE writing subjects only exist for Tâches 1 and 2")
    canonical_by_key = ee_canonical_by_content_key(tache)
    return {
        ee_writing_sujet_slug(key): ee_writing_sujet_slug(
            canonical_by_key.get(key, key)
        )
        for key in load_ee_subject_keys(tache)
    }


def load_ee_writing_months(tache: int) -> Tuple[EeWritingMonthData, ...]:
    """Load every dated Tâche 1 or 2 occurrence from the verbatim 2025 corpus."""
    if tache not in EE_WRITING_TASKS:
        raise ValueError("EE writing months only support Tâches 1 and 2")
    directory = EE_TACHE_DIRS[tache] / "subjects"
    months: List[EeWritingMonthData] = []
    seen_keys: set[str] = set()
    ordered_keys: List[str] = []
    for month_slug in EE_MONTH_ORDER:
        path = directory / f"{month_slug}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        month_row = payload.get("month")
        rows = payload.get("sujets")
        if not isinstance(month_row, dict) or not isinstance(rows, list) or not rows:
            raise ValueError(f"{path.name} must contain a month and sujets")
        if month_row.get("slug") != month_slug:
            raise ValueError(f"{path.name} has an inconsistent month slug")
        month_number = int(month_row.get("number", 0))
        month_name = str(month_row.get("name", "")).strip()
        year = int(payload.get("year", payload.get("annee", 0)))
        if month_number < 1 or not month_name or year != 2025:
            raise ValueError(f"{path.name} has invalid month metadata")

        sujets: List[EeWritingSubjectData] = []
        for position, row in enumerate(rows, start=1):
            source_id = row.get("id")
            combinaison = str(row.get("combinaison", "")).strip()
            content_key = str(row.get("key", "")).strip()
            prompt = str(row.get("prompt", "")).strip()
            if not isinstance(source_id, int) or source_id < 1:
                raise ValueError(f"{path.name} sujet {position} has an invalid id")
            if not combinaison or not prompt:
                raise ValueError(
                    f"{path.name} sujet {position} needs a combinaison and prompt"
                )
            if not content_key.startswith(EE_TACHE_CONTENT_PREFIXES[tache]):
                raise ValueError(
                    f"{path.name} sujet {position} has an invalid content key"
                )
            if content_key in seen_keys:
                raise ValueError(f"Duplicate EE writing key {content_key!r}")
            seen_keys.add(content_key)
            ordered_keys.append(content_key)
            sujets.append(
                EeWritingSubjectData(
                    source_id=source_id,
                    content_key=content_key,
                    combinaison=combinaison,
                    position=position,
                    prompt=prompt,
                )
            )
        months.append(
            EeWritingMonthData(
                number=month_number,
                slug=month_slug,
                name=month_name,
                year=year,
                sujets=tuple(sujets),
            )
        )

    if tuple(ordered_keys) != load_ee_subject_keys(tache):
        raise ValueError(f"EE Tâche {tache} writing months are out of order")
    month_numbers = [month.number for month in months]
    if len(month_numbers) != len(set(month_numbers)):
        raise ValueError(f"EE Tâche {tache} month numbers must be unique")
    return tuple(months)


@dataclass(frozen=True)
class WritingVersionData:
    body: str
    origin: str = "original"


@dataclass(frozen=True)
class WritingSujetData:
    category: str
    category_label: str
    slug: str
    order: int
    prompt: str
    versions: Tuple[WritingVersionData, ...]
    source_key: str = ""
    canonical_slug: str = ""
    month_slug: str = ""
    month_name: str = ""
    year: int = 0
    combinaison: str = ""
    position: int = 0


@dataclass(frozen=True)
class WritingCategoryData:
    slug: str
    label: str
    order: int
    sujets: Tuple[WritingSujetData, ...]


def _ee_word_count(text: str) -> int:
    return len(
        re.findall(
            r"[^\W_]+(?:[’'\-][^\W_]+)*",
            text,
            flags=re.UNICODE,
        )
    )


def load_ee_writing_categories(
    tache: int,
    *,
    months: Optional[Tuple[EeWritingMonthData, ...]] = None,
    responses_dir: Optional[Path] = None,
) -> Tuple[WritingCategoryData, ...]:
    """Build the complete themed Tâche 1/2 writing catalogue.

    All 138 dated occurrences are retained. Model versions live only on the
    canonical occurrence, so equivalent republications share one response and
    learner progression while remaining independently discoverable.
    """
    if tache not in EE_WRITING_TASKS:
        raise ValueError("EE writing categories only support Tâches 1 and 2")
    months = months or load_ee_writing_months(tache)
    themes, theme_by_key = load_ee_subject_themes(tache)
    canonical_by_key = ee_canonical_by_content_key(tache)
    occurrence_by_key = {
        sujet.content_key: (month, sujet)
        for month in months
        for sujet in month.sujets
    }
    canonical_keys: List[str] = []
    seen_canonicals: set[str] = set()
    for key in load_ee_subject_keys(tache):
        canonical = canonical_by_key.get(key, key)
        if canonical not in seen_canonicals:
            canonical_keys.append(canonical)
            seen_canonicals.add(canonical)
    expected_by_theme = {
        theme.slug: [
            key for key in canonical_keys if theme_by_key[key] == theme.slug
        ]
        for theme in themes
    }

    responses_dir = responses_dir or EE_WRITING_RESPONSE_DIRS[tache]
    paths = sorted(responses_dir.glob("*.json"))
    expected_names = {f"{theme.slug}.json" for theme in themes}
    actual_names = {path.name for path in paths}
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        unexpected = sorted(actual_names - expected_names)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise ValueError(
            f"EE Tâche {tache} response files do not match its themes: "
            + "; ".join(details)
        )

    minimum, maximum = EE_WRITING_WORD_LIMITS[tache]
    versions_by_key: Dict[str, Tuple[WritingVersionData, ...]] = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or set(payload) != {
            "version",
            "theme",
            "responses",
        }:
            raise ValueError(f"{path.name} has invalid response fields")
        theme_slug = str(payload["theme"])
        if (
            payload["version"] != 1
            or theme_slug not in expected_by_theme
            or path.name != f"{theme_slug}.json"
        ):
            raise ValueError(f"{path.name} has invalid response metadata")
        rows = payload["responses"]
        if not isinstance(rows, list):
            raise ValueError(f"{path.name} responses must be a list")
        actual_keys = []
        for index, row in enumerate(rows, start=1):
            location = f"{path.name} response {index}"
            if not isinstance(row, dict) or set(row) != {
                "content_key",
                "versions",
            }:
                raise ValueError(f"{location} has invalid fields")
            content_key = str(row["content_key"])
            raw_versions = row["versions"]
            if not isinstance(raw_versions, list) or not raw_versions:
                raise ValueError(f"{location} needs at least one version")
            versions: List[WritingVersionData] = []
            seen_bodies: set[str] = set()
            for version_index, version in enumerate(raw_versions, start=1):
                version_location = f"{location} version {version_index}"
                if not isinstance(version, dict) or set(version) != {
                    "body",
                    "origin",
                }:
                    raise ValueError(f"{version_location} has invalid fields")
                body = str(version["body"]).strip()
                origin = str(version["origin"]).strip()
                if not body or origin not in {"author", "original"}:
                    raise ValueError(f"{version_location} has invalid content")
                count = _ee_word_count(body)
                if not minimum <= count <= maximum:
                    raise ValueError(
                        f"{version_location} has {count} words; expected "
                        f"{minimum}-{maximum}"
                    )
                signature = _ee_subject_signature_text(body)
                if signature in seen_bodies:
                    raise ValueError(f"{location} repeats a response version")
                seen_bodies.add(signature)
                versions.append(WritingVersionData(body=body, origin=origin))
            actual_keys.append(content_key)
            versions_by_key[content_key] = tuple(versions)
        if actual_keys != expected_by_theme[theme_slug]:
            raise ValueError(
                f"{path.name} must contain its canonical subjects in "
                "publication order"
            )

    categories: List[WritingCategoryData] = []
    for theme in themes:
        sujets: List[WritingSujetData] = []
        for month in months:
            for occurrence in month.sujets:
                if theme_by_key[occurrence.content_key] != theme.slug:
                    continue
                canonical_key = canonical_by_key.get(
                    occurrence.content_key,
                    occurrence.content_key,
                )
                if canonical_key not in occurrence_by_key:
                    raise ValueError(
                        f"Unknown EE Tâche {tache} canonical {canonical_key!r}"
                    )
                sujets.append(
                    WritingSujetData(
                        category=theme.slug,
                        category_label=theme.name,
                        slug=ee_writing_sujet_slug(occurrence.content_key),
                        order=len(sujets) + 1,
                        prompt=occurrence.prompt,
                        versions=(
                            versions_by_key[canonical_key]
                            if occurrence.content_key == canonical_key
                            else ()
                        ),
                        source_key=occurrence.content_key,
                        canonical_slug=ee_writing_sujet_slug(canonical_key),
                        month_slug=month.slug,
                        month_name=month.name,
                        year=month.year,
                        combinaison=occurrence.combinaison,
                        position=occurrence.position,
                    )
                )
        categories.append(
            WritingCategoryData(
                slug=theme.slug,
                label=theme.name,
                order=theme.order,
                sujets=tuple(sujets),
            )
        )
    return tuple(categories)


def load_ee_tache_one_categories(
    path: Path = EE_TACHE_ONE_SUJETS_PATH,
) -> Tuple[WritingCategoryData, ...]:
    """Load EE Tâche 1 message sujets grouped by theme category.

    The bundled ``sujets.json`` lists ``categories`` (slug + label) each holding
    ordered ``sujets`` (slug + prompt + best-first ``versions``). Slugs are
    verified unique across the whole task so they can key stable URLs.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    categories_raw = data.get("categories")
    if not isinstance(categories_raw, list) or not categories_raw:
        raise ValueError("EE Tâche 1 sujets.json must contain a categories list")

    categories: List[WritingCategoryData] = []
    seen_slugs: set[str] = set()
    for category_order, category in enumerate(categories_raw, start=1):
        slug = (category.get("slug") or "").strip()
        label = (category.get("label") or "").strip()
        if not slug or not label:
            raise ValueError("Every EE Tâche 1 category needs a slug and label")
        sujets_raw = category.get("sujets")
        if not isinstance(sujets_raw, list) or not sujets_raw:
            raise ValueError(f"EE Tâche 1 category {slug!r} has no sujets")

        sujets: List[WritingSujetData] = []
        for sujet in sujets_raw:
            sujet_slug = (sujet.get("slug") or "").strip()
            prompt = (sujet.get("prompt") or "").strip()
            if not sujet_slug or not prompt:
                raise ValueError(
                    f"EE Tâche 1 sujet in {slug!r} needs a slug and prompt"
                )
            if sujet_slug in seen_slugs:
                raise ValueError(
                    f"Duplicate EE Tâche 1 sujet slug {sujet_slug!r}"
                )
            seen_slugs.add(sujet_slug)
            versions = tuple(
                WritingVersionData(body=body)
                for version in (sujet.get("versions") or [])
                if (body := (version.get("body") or "").strip())
            )
            sujets.append(
                WritingSujetData(
                    category=slug,
                    category_label=label,
                    slug=sujet_slug,
                    order=len(sujets) + 1,
                    prompt=prompt,
                    versions=versions,
                )
            )
        categories.append(
            WritingCategoryData(
                slug=slug,
                label=label,
                order=category_order,
                sujets=tuple(sujets),
            )
        )
    return tuple(categories)


def ee_tache_one_sujets(
    categories: Optional[Tuple[WritingCategoryData, ...]] = None,
) -> List[Tuple[int, WritingSujetData]]:
    """Flatten categories into ``(global_order, sujet)`` pairs, category order."""
    categories = categories or load_ee_tache_one_categories()
    ordered: List[Tuple[int, WritingSujetData]] = []
    for category in categories:
        for sujet in category.sujets:
            ordered.append((len(ordered) + 1, sujet))
    return ordered


def ee_tache_three_themes(
    months: Optional[Tuple[EeTacheThreeMonth, ...]] = None,
) -> List[ThemeData]:
    themes, _ = load_ee_subject_themes(3)
    return [
        ThemeData(
            slug=f"ee-tache-3-{theme.slug}",
            name=ee_subject_theme_name(3, theme),
            display=theme.name,
            order=200 + theme.order,
            color="#0f6fc4",
            icon=theme.icon,
            task="ee/tache-3",
        )
        for theme in themes
    ]


def ee_tache_three_families(
    months: Optional[Tuple[EeTacheThreeMonth, ...]] = None,
) -> List[Tuple[str, int]]:
    themes, _ = load_ee_subject_themes(3)
    return [
        (ee_subject_family_name(3, theme), 2000 + theme.order)
        for theme in themes
    ]


def _ee_tache_three_documents_html(documents: Tuple[str, ...]) -> str:
    blocks = []
    for index, doc in enumerate(documents, start=1):
        text = (doc or "").strip()
        if not text:
            continue
        paragraphs = [
            part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()
        ]
        body = "".join(
            "<p>" + html.escape(part).replace("\n", "<br>") + "</p>"
            for part in paragraphs
        )
        blocks.append(
            '<article class="ee-source-doc">'
            f'<h4 class="ee-source-doc__label">Document {index}</h4>'
            f"{body}</article>"
        )
    return "".join(blocks)


@lru_cache(maxsize=2)
def load_ee_tache_three_author_responses(
    path: Path = EE_TACHE_THREE_AUTHOR_RESPONSES_PATH,
) -> Dict[str, Dict[str, str]]:
    """Load the author's Notion responses that override bundled Tâche 3 models."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "responses"}
        or payload["version"] != 1
        or not isinstance(payload["responses"], list)
    ):
        raise ValueError("EE Tâche 3 author responses must use version 1")

    keys = load_ee_subject_keys(3)
    order = {key: index for index, key in enumerate(keys)}
    canonical_by_key = ee_canonical_by_content_key(3)
    canonical_keys = {canonical_by_key.get(key, key) for key in keys}
    responses: Dict[str, Dict[str, str]] = {}
    actual_order: List[int] = []
    for index, row in enumerate(payload["responses"], start=1):
        location = f"EE Tâche 3 author response {index}"
        if not isinstance(row, dict) or set(row) != {
            "content_key",
            "heading",
            "synthese",
            "point_de_vue",
            "origin",
        }:
            raise ValueError(f"{location} has invalid fields")
        values = {
            field: str(row[field]).strip()
            for field in (
                "content_key",
                "heading",
                "synthese",
                "point_de_vue",
                "origin",
            )
        }
        content_key = values["content_key"]
        if (
            content_key not in canonical_keys
            or canonical_by_key.get(content_key, content_key) != content_key
        ):
            raise ValueError(f"{location} must reference a canonical subject")
        if content_key in responses:
            raise ValueError(f"Duplicate author response for {content_key!r}")
        if values["origin"] != "author" or not all(values.values()):
            raise ValueError(f"{location} has invalid content")
        synthese_words = _ee_word_count(values["synthese"])
        point_words = _ee_word_count(values["point_de_vue"])
        if not 40 <= synthese_words <= 60:
            raise ValueError(
                f"{location} synthèse has {synthese_words} words; expected 40-60"
            )
        if not 80 <= point_words <= 120:
            raise ValueError(
                f"{location} point de vue has {point_words} words; expected 80-120"
            )
        responses[content_key] = values
        actual_order.append(order[content_key])
    if actual_order != sorted(actual_order):
        raise ValueError("EE Tâche 3 author responses must be in publication order")
    return responses


def parse_ee_tache_three_responses(
    months: Optional[Tuple[EeTacheThreeMonth, ...]] = None,
) -> List[ResponseData]:
    months = months or load_ee_tache_three_months()
    themes, theme_slug_by_key = load_ee_subject_themes(3)
    theme_by_slug = {theme.slug: theme for theme in themes}
    canonical_by_key = ee_canonical_by_content_key(3)
    author_responses = load_ee_tache_three_author_responses()
    occurrences = [
        combinaison
        for month in months
        for combinaison in month.combinaisons
    ]
    occurrence_by_key = {
        occurrence.content_key: occurrence for occurrence in occurrences
    }
    members_by_canonical: Dict[str, List[EeTacheThreeCombinaison]] = {}
    prompt_number_by_key: Dict[str, int] = {}
    theme_prompt_counts: Dict[str, int] = {}
    for occurrence in occurrences:
        canonical_key = canonical_by_key.get(
            occurrence.content_key,
            occurrence.content_key,
        )
        members_by_canonical.setdefault(canonical_key, []).append(occurrence)
        theme_data = theme_by_slug[theme_slug_by_key[occurrence.content_key]]
        theme_name = ee_subject_theme_name(3, theme_data)
        number = theme_prompt_counts.get(theme_name, 0) + 1
        theme_prompt_counts[theme_name] = number
        prompt_number_by_key[occurrence.content_key] = number

    responses: List[ResponseData] = []
    for combinaison in occurrences:
        canonical_key = canonical_by_key.get(
            combinaison.content_key,
            combinaison.content_key,
        )
        if combinaison.content_key != canonical_key:
            continue
        canonical = occurrence_by_key[canonical_key]
        theme_data = theme_by_slug[theme_slug_by_key[canonical_key]]
        theme = ee_subject_theme_name(3, theme_data)
        family = ee_subject_family_name(3, theme_data)
        authored = author_responses.get(canonical_key)
        heading = authored["heading"] if authored else canonical.heading
        synthese = authored["synthese"] if authored else canonical.synthese
        point_de_vue = (
            authored["point_de_vue"] if authored else canonical.point_de_vue
        )
        body_parts = [
            canonical.sujet,
            canonical.document1,
            canonical.document2,
            synthese,
            point_de_vue,
        ]
        body = "\n\n".join(part for part in body_parts if part)
        responses.append(
            ResponseData(
                content_key=canonical_key,
                body_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
                theme=theme,
                family=family,
                prompt=canonical.sujet,
                reformulation=heading,
                position=synthese,
                position_claire=point_de_vue,
                nuance="",
                conclusion="",
                body=body,
                body_html=_ee_tache_three_documents_html(
                    (canonical.document1, canonical.document2)
                ),
                arguments=[],
                prompts=[
                    PromptData(
                        content_key=member.content_key,
                        theme=theme,
                        number=prompt_number_by_key[member.content_key],
                        text=member.sujet,
                        family=family,
                        is_canonical=(member.content_key == canonical_key),
                    )
                    for member in members_by_canonical[canonical_key]
                ],
            )
        )
    return responses


def parse_ee_tache_three_subject_vocabulary(
    responses: Optional[List[ResponseData]] = None,
    directory: Path = EE_TACHE_THREE_VOCABULARY_DIR,
) -> List[PhraseData]:
    if responses is None:
        responses = parse_ee_tache_three_responses()
    response_by_key = {
        response.content_key: response
        for response in responses
        if response.content_key.startswith(EE_TACHE_THREE_CONTENT_PREFIX)
    }
    if not response_by_key:
        return []
    canonical_by_key = ee_canonical_by_content_key(3)

    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ValueError("No EE Tâche 3 vocabulary JSON files found")

    payloads = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError(
                f"{path.name} must use EE Tâche 3 vocabulary version 1"
            )
        month_row = payload.get("month")
        month_number = (
            int(month_row["number"])
            if isinstance(month_row, dict) and "number" in month_row
            else 0
        )
        response_rows = payload.get("responses")
        if not isinstance(response_rows, list) or not response_rows:
            raise ValueError(f"{path.name} must contain a responses list")
        payloads.append((month_number, path.name, path, response_rows))

    seen_response_keys: set = set()
    seen_raw_response_keys: set = set()
    seen_ids: Dict[str, str] = {}
    phrases: List[PhraseData] = []
    base_order = 900_000
    for _, file_name, path, response_rows in sorted(
        payloads, key=lambda item: (item[0], item[1])
    ):
        for response_row in response_rows:
            if not isinstance(response_row, dict):
                raise ValueError(f"{file_name} has a non-object response")
            response_key = response_row.get("response_key")
            canonical_key = canonical_by_key.get(response_key, response_key)
            if canonical_key not in response_by_key:
                raise ValueError(
                    f"{file_name} references unknown response "
                    f"{response_key!r}"
                )
            if response_key in seen_raw_response_keys:
                raise ValueError(
                    f"Duplicate EE Tâche 3 vocabulary for {response_key!r}"
                )
            seen_raw_response_keys.add(response_key)
            is_canonical = response_key == canonical_key
            if is_canonical:
                seen_response_keys.add(response_key)

            entries = response_row.get("entries")
            if not isinstance(entries, list):
                raise ValueError(
                    f"{response_key} must contain an entries list"
                )
            if len(entries) != EE_TACHE_THREE_VOCABULARY_PER_RESPONSE:
                raise ValueError(
                    f"{response_key} must have "
                    f"{EE_TACHE_THREE_VOCABULARY_PER_RESPONSE} vocabulary entries"
                )

            response = response_by_key[canonical_key]
            sources = tuple(
                (prompt.theme, prompt.number) for prompt in response.prompts
            )
            sources_raw = "; ".join(
                f"{theme} P{number}" for theme, number in sources
            )
            seen_targets: set = set()
            for entry_index, entry in enumerate(entries, start=1):
                location = f"{response_key} entry {entry_index}"
                if not isinstance(entry, dict):
                    raise ValueError(f"{location} must be an object")
                if set(entry) != set(EE_TACHE_THREE_VOCABULARY_FIELDS):
                    raise ValueError(
                        f"{location} fields must be "
                        f"{EE_TACHE_THREE_VOCABULARY_FIELDS}"
                    )
                values = {}
                for field_name in EE_TACHE_THREE_VOCABULARY_FIELDS:
                    value = entry.get(field_name)
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError(
                            f"{location} has an empty {field_name!r} field"
                        )
                    values[field_name] = value.strip()

                if values["kind"] not in EE_TACHE_THREE_VOCABULARY_KINDS:
                    raise ValueError(
                        f"{location} has an unknown kind {values['kind']!r}"
                    )

                phrase_id = values["id"]
                phrase_id_key = phrase_id.casefold()
                if len(phrase_id) > PHRASE_MAX_LENGTHS["id"]:
                    raise ValueError(
                        f"{location} id exceeds "
                        f"{PHRASE_MAX_LENGTHS['id']} characters"
                    )
                if phrase_id_key in seen_ids:
                    raise ValueError(
                        f"Duplicate EE Tâche 3 vocabulary id {phrase_id!r} "
                        f"in {seen_ids[phrase_id_key]} and {location}"
                    )
                seen_ids[phrase_id_key] = location

                french = values["french"]
                english = values["english"]
                example = values["example"]
                if len(french) > PHRASE_MAX_LENGTHS["expression"]:
                    raise ValueError(f"{location} french target is too long")
                if len(english) > PHRASE_MAX_LENGTHS["english_cue"]:
                    raise ValueError(f"{location} english cue is too long")
                target_key = _ee_tache_three_normalize(french)
                if target_key in seen_targets:
                    raise ValueError(
                        f"{response_key} repeats french target {french!r}"
                    )
                seen_targets.add(target_key)
                if target_key not in _ee_tache_three_normalize(example):
                    raise ValueError(
                        f"{location} example must contain its french target "
                        f"{french!r}"
                    )

                if is_canonical:
                    phrases.append(
                        PhraseData(
                            phrase_id=phrase_id,
                            tier="subject",
                            category=EE_TACHE_THREE_VOCABULARY_CATEGORIES[
                                values["kind"]
                            ],
                            english_cue=english,
                            expression=french,
                            anchor=french,
                            example=example,
                            note=values["usage"],
                            sources_raw=sources_raw,
                            sources=sources,
                            order=base_order + len(phrases) + 1,
                        )
                    )

    missing = sorted(set(response_by_key) - seen_response_keys)
    if missing:
        raise ValueError(
            "Missing EE Tâche 3 subject vocabulary for: "
            + ", ".join(missing)
        )
    expected_raw_keys = set(load_ee_subject_keys(3))
    if seen_raw_response_keys != expected_raw_keys:
        missing_raw = sorted(expected_raw_keys - seen_raw_response_keys)
        extra_raw = sorted(seen_raw_response_keys - expected_raw_keys)
        raise ValueError(
            "EE Tâche 3 raw vocabulary coverage mismatch: "
            f"missing {missing_raw[:3]}, extra {extra_raw[:3]}"
        )
    return phrases


def ee_tache_three_phrase_id_merges(
    groups: Optional[Tuple[EeEquivalentGroupData, ...]] = None,
    directory: Path = EE_TACHE_THREE_VOCABULARY_DIR,
) -> Dict[str, str]:
    """Map every retired alias-vocabulary ID onto one canonical vocabulary ID.

    The original monthly decks were generated independently, so exact targets
    overlap only partially. Migration first preserves exact target+kind pairs,
    then exact targets, then stable positions within the same kind, and finally
    the remaining positions. Each 30-card alias deck maps bijectively onto its
    canonical 30-card deck; this carries learner schedules forward without
    changing the active canonical content.
    """
    groups = groups or load_ee_equivalent_groups(3)
    entries_by_response: Dict[str, List[dict]] = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("responses", []):
            if isinstance(row, dict):
                entries_by_response[str(row.get("response_key"))] = row.get(
                    "entries"
                )

    merges: Dict[str, str] = {}
    for group in groups:
        canonical_entries = entries_by_response.get(group.canonical)
        if (
            not isinstance(canonical_entries, list)
            or len(canonical_entries) != EE_TACHE_THREE_VOCABULARY_PER_RESPONSE
        ):
            raise ValueError(
                f"Missing canonical EE Tâche 3 vocabulary for {group.canonical!r}"
            )
        for member in group.members:
            if member == group.canonical:
                continue
            source_entries = entries_by_response.get(member)
            if (
                not isinstance(source_entries, list)
                or len(source_entries)
                != EE_TACHE_THREE_VOCABULARY_PER_RESPONSE
            ):
                raise ValueError(
                    f"Missing alias EE Tâche 3 vocabulary for {member!r}"
                )

            available = set(range(len(canonical_entries)))
            assignments: Dict[int, int] = {}

            def assign_matching(predicate) -> None:
                for source_index, source in enumerate(source_entries):
                    if source_index in assignments:
                        continue
                    target_index = next(
                        (
                            index
                            for index in sorted(available)
                            if predicate(source, canonical_entries[index])
                        ),
                        None,
                    )
                    if target_index is None:
                        continue
                    assignments[source_index] = target_index
                    available.remove(target_index)

            assign_matching(
                lambda source, target: (
                    source.get("kind") == target.get("kind")
                    and _ee_subject_signature_text(
                        str(source.get("french") or "")
                    )
                    == _ee_subject_signature_text(
                        str(target.get("french") or "")
                    )
                )
            )
            assign_matching(
                lambda source, target: _ee_subject_signature_text(
                    str(source.get("french") or "")
                )
                == _ee_subject_signature_text(
                    str(target.get("french") or "")
                )
            )
            assign_matching(
                lambda source, target: source.get("kind") == target.get("kind")
            )
            assign_matching(lambda _source, _target: True)

            if (
                len(assignments) != EE_TACHE_THREE_VOCABULARY_PER_RESPONSE
                or available
            ):
                raise ValueError(
                    f"Could not map all EE Tâche 3 vocabulary for {member!r}"
                )
            for source_index, target_index in assignments.items():
                source_id = source_entries[source_index].get("id")
                target_id = canonical_entries[target_index].get("id")
                if not isinstance(source_id, str) or not source_id:
                    raise ValueError(f"Invalid alias vocabulary id for {member!r}")
                if not isinstance(target_id, str) or not target_id:
                    raise ValueError(
                        f"Invalid canonical vocabulary id for {group.canonical!r}"
                    )
                previous = merges.setdefault(source_id, target_id)
                if previous != target_id:
                    raise ValueError(
                        f"Conflicting EE Tâche 3 phrase merge for {source_id!r}"
                    )
    return merges


def _ce_plain_text(value: str) -> str:
    value = value.replace("\u00a0", " ").replace("**", "")
    value = re.sub(r"\n---\s*$", "", value.strip())
    return re.sub(r"\s+", " ", value).strip()


def _parse_comprehension_source(
    path: Path,
    *,
    slug: str,
    mode: str = "ecrite",
    first_question_number: int = 1,
    allow_missing_passage_translations: bool = False,
) -> Tuple[ComprehensionQuestionData, ...]:
    if mode not in {"ecrite", "orale"}:
        raise ValueError(f"Invalid comprehension mode: {mode!r}")
    if first_question_number < 1:
        raise ValueError("Comprehension question numbering must start above zero")

    text = path.read_text(encoding="utf-8")
    parts = re.split(
        r"(?m)^## \*\*Q(\d+)\*\*\s*$",
        text,
    )[1:]
    if not parts or len(parts) % 2:
        raise ValueError(f"No valid comprehension questions in {path.name}")

    questions: List[ComprehensionQuestionData] = []
    for index in range(0, len(parts), 2):
        number = int(parts[index])
        block = parts[index + 1]
        passage_match = re.search(
            r"### \*\*(?:Passage|Dialogue)\*\*\s*```\s*\n(.*?)\n```",
            block,
            flags=re.DOTALL,
        )
        if not passage_match:
            raise ValueError(f"{path.name} Q{number} has no passage")
        passage = passage_match.group(1).strip()
        translation_match = re.search(
            r"\n\s*\((.+)\)\s*$",
            passage,
            flags=re.DOTALL,
        )
        if translation_match:
            passage_fr = _ce_plain_text(passage[:translation_match.start()])
            passage_en = _ce_plain_text(translation_match.group(1))
        elif allow_missing_passage_translations:
            passage_fr = _ce_plain_text(passage)
            passage_en = ""
        else:
            raise ValueError(f"{path.name} Q{number} has no passage translation")

        prompt_match = re.search(
            r"(?m)^\|\s*\*\*Prompt\*\*\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$",
            block,
        )
        if not prompt_match:
            raise ValueError(f"{path.name} Q{number} has no prompt row")

        choice_rows = re.findall(
            r"(?m)^\|\s*(\*\*)?([A-D])(?:\*\*)?\s*"
            r"\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$",
            block,
        )
        if len(choice_rows) != 4:
            raise ValueError(
                f"{path.name} Q{number} must have four choices, "
                f"found {len(choice_rows)}"
            )
        choice_letters = [letter for _marker, letter, _fr, _en in choice_rows]
        if len(set(choice_letters)) != 4 or set(choice_letters) != set("ABCD"):
            raise ValueError(
                f"{path.name} Q{number} choices must use A, B, C and D exactly once"
            )
        bold_answers = [
            letter for marker, letter, _text_fr, _text_en in choice_rows if marker
        ]
        heading_match = re.search(
            r"### \*\*Correct Answer:\s*([A-D])\s*--.*?\*\*",
            block,
        )
        if heading_match:
            correct_letter = heading_match.group(1)
            if bold_answers and bold_answers != [correct_letter]:
                raise ValueError(
                    f"{path.name} Q{number} has conflicting correct answers"
                )
        elif len(bold_answers) == 1:
            correct_letter = bold_answers[0]
        else:
            raise ValueError(f"{path.name} Q{number} has no correct answer")

        correct_explanation = ""
        if heading_match:
            explanation_end = re.search(
                r"### \*\*Why the others are wrong\*\*",
                block[heading_match.end():],
            )
            raw_explanation = block[heading_match.end():]
            if explanation_end:
                raw_explanation = raw_explanation[:explanation_end.start()]
            correct_explanation = _ce_plain_text(raw_explanation)

        rationales: Dict[str, str] = {}
        why_match = re.search(
            r"### \*\*Why the others are wrong\*\*(.*)$",
            block,
            flags=re.DOTALL,
        )
        if why_match:
            rationale_parts = re.split(
                r"(?m)^\*\*([A-D])\s*--.*?\*\*\s*",
                why_match.group(1),
            )[1:]
            for rationale_index in range(0, len(rationale_parts), 2):
                letter = rationale_parts[rationale_index]
                rationale = rationale_parts[rationale_index + 1]
                rationales[letter] = _ce_plain_text(rationale)

        choices = tuple(
            ComprehensionChoiceData(
                letter=letter,
                text_fr=_ce_plain_text(text_fr),
                text_en=_ce_plain_text(text_en),
                rationale=rationales.get(letter, ""),
                is_correct=(letter == correct_letter),
            )
            for _marker, letter, text_fr, text_en in choice_rows
        )
        if sum(choice.is_correct for choice in choices) != 1:
            raise ValueError(
                f"{path.name} Q{number} must have exactly one correct choice"
            )
        questions.append(
            ComprehensionQuestionData(
                content_key=(
                    f"{'ce' if mode == 'ecrite' else 'co'}:"
                    f"{slug}:q{number:02d}"
                ),
                number=number,
                passage_fr=passage_fr,
                passage_en=passage_en,
                prompt_fr=_ce_plain_text(prompt_match.group(1)),
                prompt_en=_ce_plain_text(prompt_match.group(2)),
                correct_explanation=correct_explanation,
                choices=choices,
            )
        )

    question_numbers = [question.number for question in questions]
    expected_numbers = list(
        range(
            first_question_number,
            first_question_number + len(questions),
        )
    )
    if question_numbers != expected_numbers:
        raise ValueError(
            f"{path.name} question numbers must be consecutive from "
            f"Q{first_question_number}"
        )
    return tuple(questions)


def load_comprehension_tests() -> List[ComprehensionTestData]:
    raw = json.loads(COMPREHENSION_TESTS_PATH.read_text(encoding="utf-8"))
    tests: List[ComprehensionTestData] = []
    seen_slugs = set()
    seen_numbers = set()
    for item in raw.get("tests", []):
        mode = item.get("mode", "ecrite")
        if mode not in {"ecrite", "orale"}:
            raise ValueError(
                f"Invalid comprehension mode for {item.get('slug')!r}: "
                f"{mode!r}"
            )
        source_name = item["source"]
        if Path(source_name).name != source_name:
            raise ValueError(f"Invalid comprehension source path: {source_name!r}")
        path = COMPREHENSION_DIR / source_name
        questions = _parse_comprehension_source(
            path,
            slug=item["slug"],
            mode=mode,
            first_question_number=int(item.get("first_question_number", 1)),
            allow_missing_passage_translations=bool(
                item.get("allow_missing_passage_translations", False)
            ),
        )
        expected_count = int(item.get("expected_question_count", 36))
        is_published = bool(item.get("is_published", False))
        if is_published and len(questions) != expected_count:
            raise ValueError(
                f"Published {item['slug']} needs {expected_count} questions, "
                f"found {len(questions)}"
            )
        number_key = (mode, int(item["number"]))
        if item["slug"] in seen_slugs or number_key in seen_numbers:
            raise ValueError(
                "Comprehension test slugs and mode/number pairs must be unique"
            )
        seen_slugs.add(item["slug"])
        seen_numbers.add(number_key)
        tests.append(
            ComprehensionTestData(
                slug=item["slug"],
                mode=mode,
                number=int(item["number"]),
                title=item.get("title") or f"Test {item['number']}",
                description=item.get("description", ""),
                expected_question_count=expected_count,
                order=int(item.get("order", item["number"])),
                is_published=is_published,
                questions=questions,
            )
        )
    mode_order = {"ecrite": 0, "orale": 1}
    tests.sort(
        key=lambda item: (
            mode_order[item.mode],
            item.order,
            item.number,
        )
    )
    return tests


def theme_order_map() -> Dict[str, int]:
    return {t.name: t.order for t in load_themes()}


def parse_families() -> Tuple[Dict[Tuple[str, int], str], List[Tuple[str, int]]]:
    """Return ((theme, number) -> family name) and ordered [(family, order)]."""
    family_map: Dict[Tuple[str, int], str] = {}
    families: List[Tuple[str, int]] = []
    current_family = ""
    order = 0

    for line in STUDY_SHEETS_PATH.read_text(encoding="utf-8").splitlines():
        header = re.match(r"^## (\d+)\. (.+)$", line)
        if header:
            order = int(header.group(1))
            current_family = header.group(2).strip()
            families.append((current_family, order))
            continue

        card = re.match(r"^\*\*(.+)\*\*$", line)
        if not card or not current_family:
            continue
        for label in card.group(1).split(" = "):
            match = re.fullmatch(r"(.+?) P(\d+)", label.strip())
            if not match:
                raise ValueError(f"Bad study-sheet label: {label!r}")
            display_theme, number = match.groups()
            theme = LABEL_TO_THEME.get(display_theme)
            if theme is None:
                raise ValueError(f"Unknown theme label: {display_theme!r}")
            key = (theme, int(number))
            if key in family_map:
                raise ValueError(f"Prompt in two families: {key}")
            family_map[key] = current_family

    if len(family_map) != EXPECTED_PROMPTS:
        raise ValueError(
            f"Expected {EXPECTED_PROMPTS} family assignments, "
            f"got {len(family_map)}"
        )
    if len(families) != EXPECTED_FAMILIES:
        raise ValueError(
            f"Expected {EXPECTED_FAMILIES} families, got {len(families)}"
        )
    return family_map, families


def _section(block: str, start: str, end: str) -> str:
    match = re.search(
        rf"{re.escape(start)}\n+(.*?)(?=\n+{re.escape(end)})",
        block,
        flags=re.DOTALL,
    )
    if not match:
        raise ValueError(f"Missing section {start!r}")
    return _normalize(match.group(1)).replace("\n", " ")


def _labeled_part(section: str, label: str) -> str:
    match = re.search(
        rf"\*\*{label}\*\*\s*\n+(.*?)"
        rf"(?=\n+\*\*(?:Idée|Développement|Exemple|Conséquence)\*\*|\Z)",
        section,
        flags=re.DOTALL,
    )
    if not match:
        return ""
    return _normalize(match.group(1)).replace("\n", " ")


def _parse_arguments(block: str) -> List[ArgumentData]:
    headers = list(
        re.finditer(r"### \*\*([234])\. Argument \d+ - (.*?)\*\*", block)
    )
    if len(headers) != 3:
        raise ValueError(f"Expected 3 arguments, found {len(headers)}")

    arguments: List[ArgumentData] = []
    for index, header in enumerate(headers):
        idea_title = header.group(2).strip()
        section_start = header.end()
        section_end = (
            headers[index + 1].start()
            if index + 1 < len(headers)
            else re.search(r"### \*\*5\. Nuance\*\*", block).start()
        )
        section = block[section_start:section_end]
        arguments.append(
            ArgumentData(
                order=index + 1,
                idea=_labeled_part(section, "Idée") or idea_title,
                developpement=_labeled_part(section, "Développement"),
                exemple=_labeled_part(section, "Exemple"),
                consequence=_labeled_part(section, "Conséquence"),
            )
        )
    return arguments


def _body_to_html(body: str) -> str:
    out: List[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line == "---":
            continue
        if line.startswith("### "):
            title = re.sub(r"^###\s+\*\*(.*?)\*\*$", r"\1", line)
            out.append(f"<h3>{html.escape(title)}</h3>")
        elif re.fullmatch(r"`[^`]+`", line):
            out.append(
                f'<div class="sec-label">{html.escape(line.strip("`"))}</div>'
            )
        elif re.fullmatch(r"\*\*[^*]+\*\*", line):
            out.append(f"<h4>{html.escape(line.strip('*'))}</h4>")
        else:
            out.append(f"<p>{html.escape(line)}</p>")
    return "".join(out)


@dataclass
class _RawPrompt:
    theme: str
    number: int
    prompt: str
    family: str
    reformulation: str
    position: str
    position_claire: str
    nuance: str
    conclusion: str
    body: str
    body_html: str
    body_hash: str
    arguments: List[ArgumentData]


def _parse_theme_file(path: Path, theme: str, family_map) -> List[_RawPrompt]:
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"(?=^## \*\*Prompt \d+\*\*$)", text, flags=re.MULTILINE)
    raws: List[_RawPrompt] = []
    for block in blocks:
        header = re.match(
            r"^## \*\*Prompt (\d+)\*\*$", block.strip(), flags=re.MULTILINE
        )
        if not header:
            continue
        number = int(header.group(1))

        prompt_match = re.search(r"```markdown\n(.*?)\n```", block, re.DOTALL)
        if not prompt_match:
            raise ValueError(f"Missing prompt text in {path} P{number}")
        prompt = _normalize(prompt_match.group(1)).replace("\n", " ")

        reformulation = _section(block, "`Reformulation`", "`Position`")
        position = _section(block, "`Position`", "### **1. Position claire**")
        position_claire = _section(
            block, "### **1. Position claire**", "### **2. Argument 1"
        )
        arguments = _parse_arguments(block)
        nuance = _section(block, "### **5. Nuance**", "### **6. Conclusion**")
        conclusion = _normalize(
            re.split(r"### \*\*6\. Conclusion\*\*", block)[1]
        )
        conclusion = re.sub(r"\n---\s*$", "", conclusion).strip()
        conclusion = conclusion.replace("\n", " ")

        body_start = block.find("`Reformulation`")
        body = _normalize(block[body_start:])
        body = re.sub(r"\n---\s*$", "", body).strip()
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

        family = family_map.get((theme, number))
        if family is None:
            raise ValueError(f"No family for {theme} P{number}")

        raws.append(
            _RawPrompt(
                theme=theme,
                number=number,
                prompt=prompt,
                family=family,
                reformulation=reformulation,
                position=position,
                position_claire=position_claire,
                nuance=nuance,
                conclusion=conclusion,
                body=body,
                body_html=_body_to_html(body),
                body_hash=body_hash,
                arguments=arguments,
            )
        )
    return raws


def parse_responses() -> List[ResponseData]:
    family_map, _ = parse_families()
    theme_data = load_themes()
    order_map = {theme.name: theme.order for theme in theme_data}
    slug_map = {theme.name: theme.slug for theme in theme_data}
    themes = [theme.name for theme in theme_data]

    raws: List[_RawPrompt] = []
    for theme in themes:
        theme_dir = RESPONSES_DIR / theme
        for path in sorted(theme_dir.glob("batch_*.md"), key=_natural_key):
            raws.extend(_parse_theme_file(path, theme, family_map))

    if len(raws) != EXPECTED_PROMPTS:
        raise ValueError(f"Expected {EXPECTED_PROMPTS} prompts, got {len(raws)}")

    groups: Dict[str, List[_RawPrompt]] = {}
    for raw in raws:
        groups.setdefault(raw.body_hash, []).append(raw)

    if len(groups) != EXPECTED_UNIQUE:
        raise ValueError(
            f"Expected {EXPECTED_UNIQUE} unique responses, got {len(groups)}"
        )

    responses: List[ResponseData] = []
    for body_hash, members in groups.items():
        members.sort(key=lambda r: (order_map[r.theme], r.number))
        canonical = members[0]
        prompts = [
            PromptData(
                content_key=prompt_content_key(
                    slug_map[member.theme],
                    member.number,
                ),
                theme=member.theme,
                number=member.number,
                text=member.prompt,
                family=member.family,
                is_canonical=(member is canonical),
            )
            for member in members
        ]
        responses.append(
            ResponseData(
                content_key=prompt_content_key(
                    slug_map[canonical.theme],
                    canonical.number,
                ),
                body_hash=body_hash,
                theme=canonical.theme,
                family=canonical.family,
                prompt=canonical.prompt,
                reformulation=canonical.reformulation,
                position=canonical.position,
                position_claire=canonical.position_claire,
                nuance=canonical.nuance,
                conclusion=canonical.conclusion,
                body=canonical.body,
                body_html=canonical.body_html,
                arguments=canonical.arguments,
                prompts=prompts,
            )
        )

    responses.sort(key=lambda r: (order_map[r.theme], r.prompts[0].number))
    return responses


def parse_phrases(
    responses: Optional[List[ResponseData]] = None,
) -> List[PhraseData]:
    if responses is None:
        responses = parse_responses()

    prompt_bodies = {
        (prompt.theme, prompt.number): response.body
        for response in responses
        for prompt in response.prompts
    }
    seen_ids: Dict[str, int] = {}
    seen_anchors: Dict[str, int] = {}
    phrases: List[PhraseData] = []
    with PHRASES_PATH.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != PHRASE_FIELDS:
            raise ValueError(
                f"Phrase TSV columns must be {PHRASE_FIELDS}, "
                f"got {tuple(reader.fieldnames or ())}"
            )
        for order, row in enumerate(reader, start=1):
            line_number = order + 1
            if None in row:
                raise ValueError(
                    f"Phrase row {line_number} has extra tab-separated fields"
                )

            values = {field: (row.get(field) or "").strip() for field in PHRASE_FIELDS}
            for field in PHRASE_FIELDS[:-1]:
                if not values[field]:
                    raise ValueError(
                        f"Phrase row {line_number} has an empty {field!r} field"
                    )
            for field, max_length in PHRASE_MAX_LENGTHS.items():
                if len(values[field]) > max_length:
                    raise ValueError(
                        f"Phrase row {line_number} {field!r} exceeds "
                        f"{max_length} characters"
                    )

            phrase_id_key = values["id"].casefold()
            if phrase_id_key in seen_ids:
                raise ValueError(
                    f"Duplicate phrase id {values['id']!r} on rows "
                    f"{seen_ids[phrase_id_key]} and {line_number}"
                )
            seen_ids[phrase_id_key] = line_number

            if values["tier"] not in {"shared", "response"}:
                raise ValueError(
                    f"Phrase {values['id']} has invalid tier "
                    f"{values['tier']!r}"
                )

            anchor_key = values["anchor"].casefold()
            if anchor_key in seen_anchors:
                raise ValueError(
                    f"Duplicate phrase anchor {values['anchor']!r} on rows "
                    f"{seen_anchors[anchor_key]} and {line_number}"
                )
            seen_anchors[anchor_key] = line_number

            anchor_count = values["example"].casefold().count(anchor_key)
            if anchor_count == 0:
                raise ValueError(
                    f"Phrase {values['id']} anchor is not present in its example"
                )
            if anchor_count > 1:
                raise ValueError(
                    f"Phrase {values['id']} anchor occurs more than once in "
                    "its example"
                )
            expression_key = values["expression"].casefold()
            if (
                "[" not in values["expression"]
                and expression_key in values["example"].casefold()
                and anchor_key != expression_key
            ):
                raise ValueError(
                    f"Phrase {values['id']} anchor does not cover its full "
                    "literal expression"
                )

            sources_raw = values["sources"]
            sources: List[Tuple[str, int]] = []
            seen_sources = set()
            for token in sources_raw.split(";"):
                token = token.strip()
                if not token:
                    raise ValueError(
                        f"Phrase {values['id']} has an empty source token"
                    )
                match = re.fullmatch(r"(.+?) P(\d+)", token)
                if not match:
                    raise ValueError(
                        f"Phrase {values['id']} has malformed source {token!r}"
                    )
                display_theme, number = match.groups()
                theme = _display_to_theme(display_theme)
                if theme is None:
                    raise ValueError(
                        f"Phrase {values['id']} has unknown source theme "
                        f"{display_theme!r}"
                    )
                source = (theme, int(number))
                if source not in prompt_bodies:
                    raise ValueError(
                        f"Phrase {values['id']} references unknown prompt "
                        f"{display_theme} P{number}"
                    )
                if source in seen_sources:
                    raise ValueError(
                        f"Phrase {values['id']} repeats source "
                        f"{display_theme} P{number}"
                    )
                seen_sources.add(source)
                sources.append(source)

            matching_bodies = [prompt_bodies[source] for source in sources]
            if not any(values["example"] in body for body in matching_bodies):
                raise ValueError(
                    f"Phrase {values['id']} example is not verbatim in a cited "
                    "response"
                )
            phrases.append(
                PhraseData(
                    phrase_id=values["id"],
                    tier=values["tier"],
                    category=values["category"],
                    english_cue=values["english_cue"],
                    expression=values["expression"],
                    anchor=values["anchor"],
                    example=values["example"],
                    note=values["note"],
                    sources_raw=sources_raw,
                    sources=tuple(sources),
                    order=order,
                )
            )
    if len(phrases) != EXPECTED_PHRASES:
        raise ValueError(
            f"Expected {EXPECTED_PHRASES} phrases, got {len(phrases)}"
        )
    return phrases


def parse_subject_vocabulary(
    responses: Optional[List[ResponseData]] = None,
) -> List[PhraseData]:
    """Load the dedicated 50-entry vocabulary deck for every response."""
    if responses is None:
        responses = parse_responses()

    response_by_key = {response.content_key: response for response in responses}
    seen_response_keys: Dict[str, str] = {}
    seen_ids: Dict[str, str] = {}
    phrases: List[PhraseData] = []
    paths = sorted(SUBJECT_VOCABULARY_DIR.glob("*.json"))
    if not paths:
        raise ValueError("No subject-vocabulary JSON files found")

    expected_kinds = tuple(
        kind
        for kind in SUBJECT_VOCABULARY_KINDS
        for _ in range(SUBJECT_VOCABULARY_PER_KIND)
    )
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError(f"{path.name} must use subject-vocabulary version 1")
        response_rows = payload.get("responses")
        if not isinstance(response_rows, list):
            raise ValueError(f"{path.name} must contain a responses list")

        for response_index, response_row in enumerate(response_rows, start=1):
            location = f"{path.name} response {response_index}"
            if not isinstance(response_row, dict):
                raise ValueError(f"{location} must be an object")
            response_key = response_row.get("response_key")
            if not isinstance(response_key, str) or not response_key.strip():
                raise ValueError(f"{location} has no response_key")
            response_key = response_key.strip()
            if response_key in seen_response_keys:
                raise ValueError(
                    f"Duplicate subject vocabulary for {response_key!r} in "
                    f"{seen_response_keys[response_key]} and {path.name}"
                )
            response = response_by_key.get(response_key)
            if response is None:
                raise ValueError(
                    f"{location} references unknown response {response_key!r}"
                )
            seen_response_keys[response_key] = path.name

            entries = response_row.get("entries")
            if not isinstance(entries, list):
                raise ValueError(f"{location} must contain an entries list")
            if len(entries) != SUBJECT_VOCABULARY_PER_RESPONSE:
                raise ValueError(
                    f"{response_key} must have exactly "
                    f"{SUBJECT_VOCABULARY_PER_RESPONSE} vocabulary entries, "
                    f"got {len(entries)}"
                )
            actual_kinds = tuple(
                entry.get("kind") if isinstance(entry, dict) else None
                for entry in entries
            )
            if actual_kinds != expected_kinds:
                raise ValueError(
                    f"{response_key} must contain ten ordered entries for each "
                    "subject-vocabulary kind"
                )

            seen_targets = set()
            sources = tuple(
                (prompt.theme, prompt.number) for prompt in response.prompts
            )
            sources_raw = "; ".join(
                f"{theme} P{number}" for theme, number in sources
            )
            for entry_index, entry in enumerate(entries, start=1):
                entry_location = f"{response_key} entry {entry_index}"
                if not isinstance(entry, dict):
                    raise ValueError(f"{entry_location} must be an object")
                values = {}
                for field_name in SUBJECT_VOCABULARY_FIELDS:
                    value = entry.get(field_name)
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError(
                            f"{entry_location} has an empty {field_name!r} field"
                        )
                    values[field_name] = value.strip()

                phrase_id = values["id"]
                phrase_id_key = phrase_id.casefold()
                if len(phrase_id) > PHRASE_MAX_LENGTHS["id"]:
                    raise ValueError(
                        f"{entry_location} id exceeds "
                        f"{PHRASE_MAX_LENGTHS['id']} characters"
                    )
                if phrase_id_key in seen_ids:
                    raise ValueError(
                        f"Duplicate subject-vocabulary id {phrase_id!r} in "
                        f"{seen_ids[phrase_id_key]} and {entry_location}"
                    )
                seen_ids[phrase_id_key] = entry_location

                french = values["french"]
                english = values["english"]
                example = values["example"]
                if len(french) > PHRASE_MAX_LENGTHS["expression"]:
                    raise ValueError(
                        f"{entry_location} french target exceeds "
                        f"{PHRASE_MAX_LENGTHS['expression']} characters"
                    )
                if len(english) > PHRASE_MAX_LENGTHS["english_cue"]:
                    raise ValueError(
                        f"{entry_location} english cue exceeds "
                        f"{PHRASE_MAX_LENGTHS['english_cue']} characters"
                    )
                target_key = french.casefold()
                if target_key in seen_targets:
                    raise ValueError(
                        f"{response_key} repeats french target {french!r}"
                    )
                seen_targets.add(target_key)
                if french not in response.body:
                    raise ValueError(
                        f"{entry_location} french target is not verbatim in "
                        "the response"
                    )
                if example not in response.body:
                    raise ValueError(
                        f"{entry_location} example is not verbatim in the response"
                    )
                if example.casefold().count(target_key) != 1:
                    raise ValueError(
                        f"{entry_location} example must contain its french "
                        "target exactly once"
                    )

                phrases.append(
                    PhraseData(
                        phrase_id=phrase_id,
                        tier="subject",
                        category=SUBJECT_VOCABULARY_CATEGORIES[values["kind"]],
                        english_cue=english,
                        expression=french,
                        anchor=french,
                        example=example,
                        note=values["usage"],
                        sources_raw=sources_raw,
                        sources=sources,
                        order=EXPECTED_PHRASES + len(phrases) + 1,
                    )
                )

    missing = sorted(set(response_by_key) - set(seen_response_keys))
    if missing:
        raise ValueError(
            "Missing subject vocabulary for responses: " + ", ".join(missing)
        )
    expected_total = (
        len(response_by_key) * SUBJECT_VOCABULARY_PER_RESPONSE
    )
    if len(phrases) != expected_total:
        raise ValueError(
            f"Expected {expected_total} subject-vocabulary entries, "
            f"got {len(phrases)}"
        )
    return phrases


def parse_comprehension_vocabulary(
    tests: Optional[List[ComprehensionTestData]] = None,
) -> List[ComprehensionVocabularyData]:
    """Load one rich, source-linked vocabulary deck per comprehension test."""
    if tests is None:
        tests = load_comprehension_tests()

    tests_by_slug = {
        test.slug: test for test in tests if test.mode == "ecrite"
    }
    seen_tests: Dict[str, str] = {}
    seen_ids: Dict[str, str] = {}
    vocabulary: List[ComprehensionVocabularyData] = []
    paths = sorted(COMPREHENSION_VOCABULARY_DIR.glob("*.json"))
    if not paths:
        raise ValueError("No comprehension-vocabulary JSON files found")

    expected_kinds = tuple(
        kind
        for kind in COMPREHENSION_VOCABULARY_KINDS
        for _ in range(COMPREHENSION_VOCABULARY_PER_KIND)
    )
    base_order = (
        EXPECTED_PHRASES
        + EXPECTED_UNIQUE * SUBJECT_VOCABULARY_PER_RESPONSE
    )

    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name} must contain a JSON object")
        if set(payload) != {"test_slug", "mode", "entries"}:
            raise ValueError(
                f"{path.name} must contain test_slug, mode and entries"
            )
        test_slug = payload.get("test_slug")
        if not isinstance(test_slug, str) or test_slug not in tests_by_slug:
            raise ValueError(
                f"{path.name} references unknown test {test_slug!r}"
            )
        if test_slug in seen_tests:
            raise ValueError(
                f"Duplicate comprehension vocabulary for {test_slug!r} in "
                f"{seen_tests[test_slug]} and {path.name}"
            )
        seen_tests[test_slug] = path.name
        if payload.get("mode") != "ecrite":
            raise ValueError(f"{path.name} mode must be 'ecrite'")

        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise ValueError(f"{path.name} must contain an entries list")
        if len(entries) != COMPREHENSION_VOCABULARY_PER_TEST:
            raise ValueError(
                f"{test_slug} must have exactly "
                f"{COMPREHENSION_VOCABULARY_PER_TEST} vocabulary entries, "
                f"got {len(entries)}"
            )
        actual_kinds = tuple(
            entry.get("kind") if isinstance(entry, dict) else None
            for entry in entries
        )
        if actual_kinds != expected_kinds:
            raise ValueError(
                f"{test_slug} must contain ten ordered entries for every "
                "comprehension-vocabulary kind"
            )

        test = tests_by_slug[test_slug]
        questions_by_number = {
            question.number: question for question in test.questions
        }
        seen_targets = set()
        for index, entry in enumerate(entries, start=1):
            location = f"{test_slug} entry {index}"
            if not isinstance(entry, dict):
                raise ValueError(f"{location} must be an object")
            if set(entry) != set(COMPREHENSION_VOCABULARY_FIELDS):
                raise ValueError(
                    f"{location} fields must be "
                    f"{COMPREHENSION_VOCABULARY_FIELDS}"
                )
            values = {}
            for field_name in COMPREHENSION_VOCABULARY_FIELDS[:-1]:
                value = entry.get(field_name)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"{location} has an empty {field_name!r} field"
                    )
                values[field_name] = value.strip()

            phrase_id = values["id"]
            expected_id = (
                f"CE{test.number:02d}V{index:03d}"
            )
            if phrase_id != expected_id:
                raise ValueError(
                    f"{location} id must be {expected_id!r}, got "
                    f"{phrase_id!r}"
                )
            phrase_id_key = phrase_id.casefold()
            if phrase_id_key in seen_ids:
                raise ValueError(
                    f"Duplicate comprehension-vocabulary id {phrase_id!r}"
                )
            seen_ids[phrase_id_key] = location

            question_numbers = entry.get("questions")
            if (
                not isinstance(question_numbers, list)
                or not question_numbers
                or any(
                    not isinstance(number, int)
                    or number not in questions_by_number
                    for number in question_numbers
                )
                or len(set(question_numbers)) != len(question_numbers)
            ):
                raise ValueError(
                    f"{location} must cite unique valid question numbers"
                )
            question_numbers = tuple(question_numbers)

            french = values["french"]
            english = values["english"]
            example = values["example"]
            target_key = french.casefold()
            if target_key in seen_targets:
                raise ValueError(
                    f"{test_slug} repeats french target {french!r}"
                )
            seen_targets.add(target_key)
            if len(french) > PHRASE_MAX_LENGTHS["expression"]:
                raise ValueError(f"{location} french target is too long")
            if len(english) > PHRASE_MAX_LENGTHS["english_cue"]:
                raise ValueError(f"{location} english cue is too long")
            if example.casefold().count(target_key) != 1:
                raise ValueError(
                    f"{location} example must contain its french target "
                    "exactly once"
                )

            cited_source = " ".join(
                " ".join(
                    [
                        questions_by_number[number].passage_fr,
                        questions_by_number[number].prompt_fr,
                        *(
                            choice.text_fr
                            for choice in questions_by_number[number].choices
                        ),
                    ]
                )
                for number in question_numbers
            ).casefold()
            if target_key not in cited_source:
                raise ValueError(
                    f"{location} french target is not present in a cited "
                    "source question"
                )

            sources_raw = "; ".join(
                f"CE · {test.title} · Q{number}"
                for number in question_numbers
            )
            phrase = PhraseData(
                phrase_id=phrase_id,
                tier="comprehension",
                category=COMPREHENSION_VOCABULARY_CATEGORIES[
                    values["kind"]
                ],
                english_cue=english,
                expression=french,
                anchor=french,
                example=example,
                note=values["usage"],
                sources_raw=sources_raw,
                sources=(),
                order=base_order + len(vocabulary) + 1,
            )
            vocabulary.append(
                ComprehensionVocabularyData(
                    phrase=phrase,
                    test_slug=test_slug,
                    question_numbers=question_numbers,
                )
            )

    missing_tests = sorted(set(tests_by_slug) - set(seen_tests))
    if missing_tests:
        raise ValueError(
            "Missing comprehension vocabulary for tests: "
            + ", ".join(missing_tests)
        )
    expected_total = len(tests_by_slug) * COMPREHENSION_VOCABULARY_PER_TEST
    if len(vocabulary) != expected_total:
        raise ValueError(
            f"Expected {expected_total} comprehension-vocabulary entries, "
            f"got {len(vocabulary)}"
        )
    return vocabulary


def _display_to_theme(display_theme: str) -> Optional[str]:
    direct = {
        "Culture": "Culture",
        "Famille": "Famille",
        "Education": "Education",
        "Éducation": "Education",
        "Sante": "Sante",
        "Santé": "Sante",
        "Technologie": "Technologie",
        "Techno": "Technologie",
        "Environnement": "Environnement",
        "Environ": "Environnement",
        "Economie": "Economie",
        "Économie": "Economie",
    }
    return direct.get(display_theme)
