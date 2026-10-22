"""Reviewed oral viewpoints, layered over immutable published source models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

from . import content_loader as content
from .response_personalization import AnnotationArgument, EffectiveArgument, EffectiveResponse


MODELS_DIR = content.CONTENT_DIR / "tache_3" / "responses"


@dataclass(frozen=True)
class TacheThreeModel:
    group: str
    source_prompts: tuple[tuple[str, str], ...]
    response: EffectiveResponse
    argument_ids: tuple[int, ...] = (1, 2, 3)


def annotation_arguments(prompt, response):
    if response.is_personal and all(
        isinstance(argument, AnnotationArgument) for argument in response.arguments
    ):
        return response.arguments
    model = reviewed_model(prompt.response, prompt) if prompt is not None else None
    if model is None or (not response.is_personal and model.response != response) or (
        tuple(argument.order for argument in response.arguments)
        != tuple(argument.order for argument in model.response.arguments)
    ):
        return response.arguments
    return tuple(
        AnnotationArgument(**asdict(argument), annotation_id=identity)
        for argument, identity in zip(response.arguments, model.argument_ids)
    )


def _text(value, label):
    if (
        not isinstance(value, str) or not value.strip()
        or value != value.strip() or any(char in value for char in "\n\r\t")
    ):
        raise ValueError(f"Invalid EO3 {label}")
    return value


def spoken_text(response):
    return " ".join((
        response.position_claire,
        *(text for argument in response.arguments for text in (
            argument.idea, argument.developpement, argument.exemple,
            argument.consequence,
        )),
        response.nuance, response.conclusion,
    ))


def response_text(response):
    return "\n\n".join(filter(None, (
        response.position_claire,
        *(
            " ".join(filter(None, (
                argument.idea, argument.developpement, argument.exemple, argument.consequence,
            )))
            for argument in response.arguments
        ),
        response.nuance, response.conclusion,
    )))


def load_tache_three_models(
    directory: Path = MODELS_DIR, *, responses=None,
) -> dict[str, TacheThreeModel]:
    sources = content.parse_responses() if responses is None else responses
    by_group = {source.semantic_group: source for source in sources}
    themes = {theme.slug: theme.name for theme in content.load_themes()}
    result = {}
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ValueError("EO3 reviewed model catalogue is empty")
    for path in paths:
        data = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=content._unique_json_fields,
        )
        theme = path.stem
        if (
            not isinstance(data, dict)
            or set(data) != {"version", "task", "theme", "responses"}
            or type(data["version"]) is not int or data["version"] != 1
            or data["task"] != "eo/tache-3"
            or theme not in themes or data["theme"] != theme
            or not isinstance(data["responses"], dict)
        ):
            raise ValueError(f"Invalid EO3 reviewed theme: {path.name}")
        expected = {
            source.semantic_group.removeprefix("eo/tache-3/")
            for source in sources if source.theme == themes[theme]
        }
        if set(data["responses"]) != expected:
            raise ValueError(f"EO3 reviewed theme coverage differs: {theme}")
        for group, row in data["responses"].items():
            identity = f"eo/tache-3/{group}"
            source = by_group[identity]
            required = {
                "prompt_signatures", "reformulation", "position",
                "position_claire", "arguments", "nuance", "conclusion",
            }
            if not isinstance(row, dict) or not (
                required <= set(row) <= required | {"argument_ids"}
            ):
                raise ValueError(f"Invalid EO3 model fields: {group}")
            argument_ids = row.get("argument_ids", [1, 2, 3])
            if (
                not isinstance(argument_ids, list) or len(argument_ids) != 3
                or any(type(identity) is not int or not 1 <= identity <= 9999 for identity in argument_ids)
                or len(set(argument_ids)) != 3
            ):
                raise ValueError(f"Invalid EO3 argument identities: {group}")
            signatures = {
                prompt.content_key: hashlib.sha256(
                    prompt.text.encode("utf-8")
                ).hexdigest()
                for prompt in source.prompts
            }
            if row["prompt_signatures"] != signatures:
                raise ValueError(f"EO3 consignes changed; re-audit every variant: {group}")
            if not isinstance(row["arguments"], list) or len(row["arguments"]) != 3:
                raise ValueError(f"EO3 needs exactly three supported arguments: {group}")
            arguments = []
            for order, argument in enumerate(row["arguments"], 1):
                if not isinstance(argument, dict) or set(argument) != {
                    "idea", "developpement", "exemple", "consequence",
                }:
                    raise ValueError(f"Invalid EO3 argument: {group}/{order}")
                arguments.append(EffectiveArgument(
                    order=order,
                    **{name: _text(value, f"{group}/{order}/{name}")
                       for name, value in argument.items()},
                ))
            for field in ("idea", "developpement", "exemple"):
                values = [getattr(argument, field).casefold() for argument in arguments]
                if len(set(values)) != 3:
                    raise ValueError(f"EO3 arguments need distinct {field}: {group}")
            if any(
                argument.exemple.casefold() in {
                    argument.idea.casefold(), argument.developpement.casefold(),
                }
                for argument in arguments
            ):
                raise ValueError(f"EO3 example only repeats its claim: {group}")
            response = EffectiveResponse(
                **{name: _text(row[name], f"{group}/{name}") for name in (
                    "reformulation", "position", "position_claire",
                    "nuance", "conclusion",
                )},
                arguments=tuple(arguments), is_personal=False,
            )
            # A rehearsal envelope, not an official examination word limit.
            if not 300 <= len(spoken_text(response).split()) <= 430:
                raise ValueError(f"EO3 model exceeds its spoken rehearsal envelope: {group}")
            result[identity] = TacheThreeModel(
                group=identity,
                source_prompts=tuple(
                    (prompt.content_key, prompt.text) for prompt in source.prompts
                ),
                response=response,
                argument_ids=tuple(argument_ids),
            )
    return result


def reviewed_model(response, prompt=None):
    from . import catalogue

    if not response.semantic_group.startswith("eo/tache-3/"):
        return None
    model = catalogue.tache_three_models().get(response.semantic_group)
    if model is not None and prompt is not None:
        if (prompt.content_key, prompt.text) not in model.source_prompts:
            raise RuntimeError("EO3 reviewed consignes are not synchronized")
    return model
