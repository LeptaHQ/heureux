"""Source-pinned explanations of bundled oral task three prompts."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from . import content_loader as content


NOTES_PATH = content.CONTENT_DIR / "tache_3" / "prompt_notes.json"


@dataclass(frozen=True)
class TacheThreePromptNote:
    note: str
    source_prompts: tuple[tuple[str, str], ...]


def load_tache_three_prompt_notes(
    path: Path = NOTES_PATH, *, responses=None,
) -> dict[str, TacheThreePromptNote]:
    sources = content.parse_responses() if responses is None else responses
    data = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=content._unique_json_fields,
    )
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "task", "groups"}
        or type(data["version"]) is not int or data["version"] != 1
        or data["task"] != "eo/tache-3"
        or not isinstance(data["groups"], dict)
    ):
        raise ValueError("Invalid EO3 prompt-note catalogue")
    by_group = {
        source.semantic_group.removeprefix("eo/tache-3/"): source
        for source in sources
    }
    if not by_group or set(data["groups"]) != set(by_group):
        raise ValueError("EO3 prompt-note coverage differs from source groups")
    notes = {}
    for group, source in by_group.items():
        row = data["groups"][group]
        if not isinstance(row, dict) or set(row) != {"note", "prompt_signatures"}:
            raise ValueError(f"Invalid EO3 prompt-note fields: {group}")
        signatures = {
            prompt.content_key: hashlib.sha256(prompt.text.encode("utf-8")).hexdigest()
            for prompt in source.prompts
        }
        if row["prompt_signatures"] != signatures:
            raise ValueError(f"EO3 consignes changed; re-audit prompt note: {group}")
        note = row["note"]
        if (
            not isinstance(note, str) or note != note.strip()
            or any(char in note for char in "\n\r\t")
            or not 40 <= len(note.split()) <= 160
        ):
            raise ValueError(f"Invalid EO3 prompt-note text: {group}")
        notes[source.semantic_group] = TacheThreePromptNote(
            note=note,
            source_prompts=tuple(
                (prompt.content_key, prompt.text) for prompt in source.prompts
            ),
        )
    return notes


def prompt_note_for_response(response, prompt=None) -> TacheThreePromptNote | None:
    from . import catalogue

    if not response.semantic_group.startswith("eo/tache-3/"):
        return None
    note = catalogue.tache_three_prompt_notes().get(response.semantic_group)
    if note is not None and prompt is not None:
        if (prompt.content_key, prompt.text) not in note.source_prompts:
            raise RuntimeError("EO3 prompt-note consignes are not synchronized")
    return note
