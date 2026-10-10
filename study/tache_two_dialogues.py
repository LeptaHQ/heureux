"""Reviewed EO2 conversations, separate from immutable import/vocabulary sources."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from . import content_loader as content
from .response_personalization import EffectiveArgument, EffectiveResponse


DIALOGUES_DIR = content.QUESTION_BANK_DIR / "dialogues"
QUESTION_COUNT = 8


@dataclass(frozen=True)
class DialogueQuestion:
    topic: str
    question: str
    answer: str
    follow_up_to: int | None
    condition: str


@dataclass(frozen=True)
class TacheTwoDialogue:
    group: str
    register: str
    note: str
    opening: str
    closing: str
    questions: tuple[DialogueQuestion, ...]


def _text(value, label, *, max_words):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    value = value.strip()
    if len(value.split()) > max_words:
        raise ValueError(f"{label} exceeds {max_words} words")
    return value


def load_tache_two_dialogues(
    directory: Path = DIALOGUES_DIR, *, months=None, semantic_path=None,
) -> dict[str, TacheTwoDialogue]:
    months = months if months is not None else content.load_tache_two_subject_months()
    keys = [
        content.tache_two_subject_content_key(month.slug, batch.number, subject.number)
        for month in months for batch in month.batches for subject in batch.subjects
    ]
    groups = content.load_oral_semantic_groups("eo/tache-2", keys, path=semantic_path)
    groups_by_id = {group.id: group for group in groups}
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ValueError("EO2 needs a reviewed dialogue corpus")
    by_group = {}
    notes_by_group = {}
    required_fields = {"group", "register", "note", "opening", "closing", "questions"}
    for path in paths:
        data = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=content._unique_json_fields,
        )
        if (
            not isinstance(data, dict)
            or set(data) != {"version", "dialogues"}
            or type(data["version"]) is not int
            or data["version"] != 1
            or not isinstance(data["dialogues"], list)
            or not data["dialogues"]
        ):
            raise ValueError(f"{path.name} must contain version 1 EO2 dialogues")
        for row in data["dialogues"]:
            if (
                not isinstance(row, dict)
                or not required_fields <= set(row)
                or set(row) - required_fields - {"notes"}
            ):
                raise ValueError(f"{path.name} has invalid dialogue fields")
            group_id = row["group"]
            if (
                not isinstance(group_id, str)
                or group_id not in groups_by_id
                or group_id in by_group
            ):
                raise ValueError(f"{path.name} has an unknown or duplicate EO2 group")
            label = f"EO2 {group_id}"
            if row["register"] not in ("tu", "vous"):
                raise ValueError(f"{label} must choose tu or vous")
            note = _text(row["note"], f"{label} note", max_words=80)
            opening = _text(row["opening"], f"{label} opening", max_words=40)
            closing = _text(row["closing"], f"{label} closing", max_words=35)
            if "?" in opening or "?" in closing or not re.search(r"\bmerci\b", closing, re.I):
                raise ValueError(f"{label} needs a separate opening and final thanks, not extra questions")
            raw_questions = row["questions"]
            if not isinstance(raw_questions, list) or len(raw_questions) != QUESTION_COUNT:
                raise ValueError(f"{label} needs exactly eight questions, including follow-ups")
            questions = []
            seen_questions, seen_topics = set(), set()
            previous_topic = None
            for number, raw in enumerate(raw_questions, 1):
                question_fields = {"topic", "question", "answer", "follow_up_to"}
                if (
                    not isinstance(raw, dict)
                    or not question_fields <= set(raw)
                    or set(raw) - question_fields - {"condition"}
                ):
                    raise ValueError(f"{label} question {number} has invalid fields")
                topic = _text(raw["topic"], f"{label} topic {number}", max_words=8)
                question = _text(raw["question"], f"{label} question {number}", max_words=45)
                answer = _text(raw["answer"], f"{label} answer {number}", max_words=35)
                if question.count("?") != 1 or not question.endswith("?"):
                    raise ValueError(f"{label} question {number} must ask one complete question")
                if "?" in answer or len(re.findall(r"[.!](?:\s|$)", answer)) > 2:
                    raise ValueError(f"{label} answer {number} must be a short reply, not a question")
                normalized = " ".join(question.casefold().split())
                if normalized in seen_questions:
                    raise ValueError(f"{label} repeats a question")
                seen_questions.add(normalized)
                if topic != previous_topic:
                    if topic in seen_topics:
                        raise ValueError(f"{label} topics must form contiguous priority-ordered blocks")
                    seen_topics.add(topic)
                follow_up_to = raw["follow_up_to"]
                if follow_up_to is not None and (
                    type(follow_up_to) is not int
                    or not 1 <= follow_up_to < number
                    or questions[follow_up_to - 1].topic != topic
                ):
                    raise ValueError(f"{label} question {number} has an invalid follow-up reference")
                condition = (
                    _text(raw.get("condition"), f"{label} follow-up condition {number}", max_words=14)
                    if follow_up_to is not None else ""
                )
                if follow_up_to is None and "condition" in raw:
                    raise ValueError(f"{label} question {number} has a condition without a follow-up")
                questions.append(DialogueQuestion(topic, question, answer, follow_up_to, condition))
                previous_topic = topic
            if not 2 <= len(seen_topics) <= 4:
                raise ValueError(f"{label} needs two to four relevant topic headings")
            if not any(question.follow_up_to is not None for question in questions):
                raise ValueError(f"{label} needs a response-grounded follow-up")
            notes = row.get("notes", {})
            if (
                not isinstance(notes, dict)
                or set(notes) - set(groups_by_id[group_id].members)
            ):
                raise ValueError(f"{label} notes must belong to its own prompt publications")
            notes_by_group[group_id] = {
                key: _text(value, f"{label} note for {key}", max_words=80)
                for key, value in notes.items()
            }
            by_group[group_id] = TacheTwoDialogue(
                group_id, row["register"], note, opening, closing, tuple(questions),
            )
    missing = set(groups_by_id) - set(by_group)
    if missing:
        raise ValueError(f"Missing reviewed EO2 dialogues: {', '.join(sorted(missing))}")
    return {
        key: replace(dialogue, note=notes[key]) if key in notes else dialogue
        for group in groups
        for dialogue in (by_group[group.id],)
        for notes in (notes_by_group[group.id],)
        for key in group.members
    }


def published_dialogue(prompt) -> TacheTwoDialogue | None:
    if prompt is None or not prompt.model_content or not prompt.content_key.startswith("tache2:"):
        return None
    from . import catalogue
    try:
        return catalogue.tache_two_dialogues()[prompt.content_key]
    except KeyError as exc:
        raise ValueError(f"No reviewed EO2 dialogue for {prompt.content_key}") from exc


def dialogue_response(dialogue: TacheTwoDialogue) -> EffectiveResponse:
    return EffectiveResponse(
        reformulation=dialogue.opening,
        position="",
        position_claire="",
        arguments=tuple(
            EffectiveArgument(number, question.question, "", "", "")
            for number, question in enumerate(dialogue.questions, 1)
        ),
        nuance="",
        conclusion=dialogue.closing,
        is_personal=False,
    )


def matching_dialogue(prompt, value: EffectiveResponse) -> TacheTwoDialogue | None:
    dialogue = published_dialogue(prompt)
    questions_only = replace(
        value,
        arguments=tuple(
            EffectiveArgument(argument.order, argument.idea, "", "", "")
            for argument in value.arguments
        ),
        is_personal=False,
        nuance="",
    )
    return (
        dialogue
        if dialogue is not None and questions_only == dialogue_response(dialogue)
        else None
    )


def prompt_note_presentation(prompt, value: EffectiveResponse) -> dict[str, str] | None:
    """EO2 personal explanations use the otherwise unused nuance section."""
    dialogue = published_dialogue(prompt)
    note = value.nuance.strip() if value.is_personal else ""
    if not note and dialogue is not None:
        note = dialogue.note
    if not note:
        return None
    return {"note": note, "register": dialogue.register if dialogue is not None else ""}


def hint_section_presentation(dialogue, hints) -> tuple[dict, ...]:
    """Group aligned EO2 pistes under the dialogue's question topics."""
    if dialogue is None or len(hints) != len(dialogue.questions):
        return ()
    sections = []
    for question, hint in zip(dialogue.questions, hints):
        if not sections or sections[-1]["topic"] != question.topic:
            sections.append({"topic": question.topic, "hints": []})
        sections[-1]["hints"].append(hint)
    return tuple(
        {"topic": section["topic"], "hints": tuple(section["hints"])}
        for section in sections
    )


def question_presentation(prompt, value: EffectiveResponse, *, dialogue=None) -> dict:
    dialogue = dialogue or matching_dialogue(prompt, value)
    if dialogue is None:
        published = published_dialogue(prompt)
        if published is not None and len(published.questions) == len(value.arguments):
            dialogue = published
    questions = []
    previous_topic = None
    for number, argument in enumerate(value.arguments, 1):
        row = {"number": number, "text": argument.idea}
        if dialogue is not None:
            question = dialogue.questions[number - 1]
            row.update(
                topic=question.topic,
                starts_topic=question.topic != previous_topic,
            )
            if argument.idea == question.question:
                row.update(
                    follow_up_to=question.follow_up_to,
                    condition=question.condition,
                )
            previous_topic = question.topic
        questions.append(row)
    return {"subject_questions": questions, "tache_two_dialogue": dialogue}
