"""Reviewed oral viewpoints, layered over immutable published source models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import re

from study.catalogue import loader as content
from study.expression.personalization import AnnotationArgument, EffectiveArgument, EffectiveResponse


MODELS_DIR = content.EO_TACHE_THREE_THEMES_DIR
ARCHIVE_DEFAULTS_PATH = content.EO_TACHE_THREE_DIR / "archive_defaults.json"


@dataclass(frozen=True)
class TacheThreeModel:
    group: str
    source_prompts: tuple[tuple[str, str], ...]
    response: EffectiveResponse
    argument_ids: tuple[int, ...] = (1, 2, 3)
    alternate_pistes: bool = False
    variants: tuple[tuple[str, TacheThreeModel], ...] = ()

    def for_prompt(self, key):
        return next((model for source, model in self.variants if source == key), self)

    def editions(self):
        return (self, *(model for _, model in self.variants))


def annotation_arguments(prompt, response):
    if response.is_personal and all(
        isinstance(argument, AnnotationArgument) for argument in response.arguments
    ):
        return response.arguments
    model = reviewed_model(prompt.response, prompt) if prompt is not None else None
    if model is not None and response.is_personal:
        from study.catalogue import registry as catalogue

        # Personal copies saved before explicit argument IDs used the reviewed IDs.
        model = catalogue.tache_three_models()[model.group]
    if model is None or (not response.is_personal and model.response != response) or (
        tuple(argument.order for argument in response.arguments)
        != tuple(argument.order for argument in model.response.arguments)
    ):
        return response.arguments
    return tuple(
        AnnotationArgument(**asdict(argument), annotation_id=identity)
        for argument, identity in zip(response.arguments, model.argument_ids)
    )


def _text(value, label, *, allow_paragraphs=False):
    paragraphs = value.split("\n\n") if allow_paragraphs and isinstance(value, str) else (value,)
    if any(
        not isinstance(part, str) or not part or part != part.strip()
        or any(char in part for char in "\n\r\t")
        for part in paragraphs
    ):
        raise ValueError(f"Invalid EO3 {label}")
    return value


def _argument_ids(ids, label):
    if (
        not isinstance(ids, list) or len(ids) != 3
        or any(type(identity) is not int or not 1 <= identity <= 9999 for identity in ids)
        or len(set(ids)) != 3
    ):
        raise ValueError(f"Invalid EO3 argument identities: {label}")
    return tuple(ids)


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
    from study.expression.eo.tache_3.taxonomy import load_eo_tache_three_taxonomy

    taxonomy = load_eo_tache_three_taxonomy(responses=sources)
    themes = {theme.slug for theme in taxonomy.themes}
    result = {}
    if directory.is_dir() and not any(directory.iterdir()):
        raise ValueError("EO3 reviewed model catalogue is empty")
    paths = (directory,) if directory.is_file() else content.eo3_theme_paths(
        "responses.json", directory, responses=sources, taxonomy=taxonomy,
    )[0]
    for path in paths:
        data = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=content._unique_json_fields,
        )
        theme = path.parent.name if directory.is_dir() else path.stem
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
            for source in sources if taxonomy.by_group[source.semantic_group].theme.slug == theme
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
            argument_ids = _argument_ids(row.get("argument_ids", [1, 2, 3]), group)
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
                    **{
                        name: _text(
                            value, f"{group}/{order}/{name}",
                            allow_paragraphs=name == "developpement",
                        )
                        for name, value in argument.items()
                    },
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
            result[identity] = TacheThreeModel(
                group=identity,
                source_prompts=tuple(
                    (prompt.content_key, prompt.text) for prompt in source.prompts
                ),
                response=response,
                argument_ids=argument_ids,
            )
    return result


def archive_response(body):
    """Read the archive prose without the legacy spoken-field whitespace joins."""
    preparation, intro, first, second, third, nuance, conclusion = re.split(
        r"\n+### \*\*[1-6]\. [^\n]+\*\*\n+", body,
    )
    reformulation, position = preparation.removeprefix("`Reformulation`\n\n").split(
        "\n\n`Position`\n\n",
    )
    arguments = []
    for order, section in enumerate((first, second, third), 1):
        idea, development, example, consequence = re.split(
            r"\n\n\*\*(?:Développement|Exemple|Conséquence)\*\*\n\n",
            section.removeprefix("**Idée**\n\n"),
        )
        arguments.append(EffectiveArgument(order, idea, development, example, consequence))
    return EffectiveResponse(
        reformulation, position, intro, tuple(arguments), nuance, conclusion, False,
    )


def load_archive_defaults(sources, path=ARCHIVE_DEFAULTS_PATH):
    """Publish selected archive occurrences without replacing their reviewed editions."""
    selected = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=content._unique_json_fields)
    if not isinstance(selected, dict) or not selected:
        raise ValueError("Invalid EO3 archive defaults")
    models = {}
    used = set()
    for source in sources:
        if source.content_key not in selected:
            continue
        signatures = tuple((prompt.content_key, prompt.text) for prompt in source.prompts)

        def edition(key, body):
            used.add(key)
            return TacheThreeModel(
                group=source.semantic_group, source_prompts=signatures,
                response=archive_response(body),
                argument_ids=_argument_ids(selected.get(key), key),
            )

        model = edition(source.content_key, source.body)
        variants = []
        for prompt in source.prompts:
            body = prompt.model_content["body"]
            if prompt.content_key == source.content_key or body == source.body:
                continue
            other = edition(prompt.content_key, body)
            if spoken_text(other.response) != spoken_text(model.response):
                prompts = ((prompt.content_key, prompt.text), *(
                    signature for signature in signatures if signature[0] != prompt.content_key
                ))
                other = replace(other, source_prompts=prompts)
            variants.append((prompt.content_key, other))
        models[model.group] = replace(model, variants=tuple(variants))
    if used != set(selected):
        raise ValueError(f"Unmatched EO3 archive defaults: {', '.join(sorted(set(selected) - used))}")
    return models


def publish_archive_defaults(reviewed, archived):
    def with_pistes(model, reviewed_speech):
        return replace(
            model, alternate_pistes=spoken_text(model.response) != reviewed_speech,
            variants=tuple(
                (key, with_pistes(variant, reviewed_speech)) for key, variant in model.variants
            ),
        )

    return {
        group: with_pistes(archived[group], spoken_text(model.response)) if group in archived else model
        for group, model in reviewed.items()
    }


def reviewed_model(response, prompt=None):
    from study.catalogue import registry as catalogue

    if not response.semantic_group.startswith("eo/tache-3/"):
        return None
    model = catalogue.tache_three_public_models().get(response.semantic_group)
    if model is not None and prompt is not None:
        if (prompt.content_key, prompt.text) not in model.source_prompts:
            raise RuntimeError("EO3 reviewed consignes are not synchronized")
        return model.for_prompt(prompt.content_key)
    return model
