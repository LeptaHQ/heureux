"""Known published revisions for narrowly scoped EO2 geography corrections."""

from dataclasses import dataclass
import json

from . import content_loader as content
from .tache_two_dialogues import DialogueQuestion, TacheTwoDialogue, QUESTION_COUNT, _text


LOCATION_HISTORY_PATH = content.QUESTION_BANK_DIR / "dialogue_history" / "locations.json"


@dataclass(frozen=True)
class LocationHistory:
    replacements: tuple[tuple[str, str], ...]
    revisions: tuple[TacheTwoDialogue, ...]


def load_location_history(path=LOCATION_HISTORY_PATH):
    data = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=content._unique_json_fields,
    )
    if (
        not isinstance(data, dict) or set(data) != {"version", "groups"}
        or type(data["version"]) is not int or data["version"] != 1
        or not isinstance(data["groups"], dict)
    ):
        raise ValueError("EO2 location history needs version 1 groups")
    result = {}
    for group, row in data["groups"].items():
        label = f"EO2 location history {group}"
        if (
            not isinstance(row, dict) or set(row) != {"replacements", "revisions"}
            or not isinstance(row["replacements"], list) or not row["replacements"]
            or not isinstance(row["revisions"], list) or not row["revisions"]
        ):
            raise ValueError(f"{label} needs replacements and revisions")
        replacements = []
        for pair in row["replacements"]:
            if (
                not isinstance(pair, list) or len(pair) != 2
                or any(not isinstance(value, str) or not value for value in pair)
                or pair[0] == pair[1]
            ):
                raise ValueError(f"{label} has an invalid replacement")
            replacements.append(tuple(pair))
        revisions = []
        for revision in row["revisions"]:
            if (
                not isinstance(revision, dict)
                or set(revision) != {"group", "opening", "closing", "questions"}
                or revision["group"] != group
                or not isinstance(revision["questions"], list)
                or len(revision["questions"]) != QUESTION_COUNT
            ):
                raise ValueError(f"{label} has an invalid revision")
            questions = []
            for number, question in enumerate(revision["questions"], 1):
                if (
                    not isinstance(question, dict)
                    or not {"topic", "question", "follow_up_to"} <= set(question)
                    or set(question) - {"topic", "question", "follow_up_to", "condition"}
                ):
                    raise ValueError(f"{label} has invalid question fields")
                topic = _text(question["topic"], label, max_words=8)
                text = _text(question["question"], label, max_words=45)
                parent = question["follow_up_to"]
                if parent is not None and (
                    type(parent) is not int or not 1 <= parent < number
                    or questions[parent - 1].topic != topic
                ):
                    raise ValueError(f"{label} has an invalid follow-up")
                condition = (
                    _text(question.get("condition"), label, max_words=14)
                    if parent is not None else ""
                )
                if parent is None and "condition" in question:
                    raise ValueError(f"{label} has a condition without a follow-up")
                questions.append(DialogueQuestion(topic, text, "", parent, condition))
            revisions.append(TacheTwoDialogue(
                group, "vous", "",
                _text(revision["opening"], label, max_words=40),
                _text(revision["closing"], label, max_words=35),
                tuple(questions),
            ))
        result[group] = LocationHistory(tuple(replacements), tuple(revisions))
    return result
