from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EffectiveArgument:
    order: int
    idea: str
    developpement: str
    exemple: str
    consequence: str


@dataclass(frozen=True)
class AnnotationArgument(EffectiveArgument):
    annotation_id: int


@dataclass(frozen=True)
class EffectiveResponse:
    reformulation: str
    position: str
    position_claire: str
    arguments: tuple[EffectiveArgument, ...]
    nuance: str
    conclusion: str
    is_personal: bool


def effective_response(response, user, *, prompt=None, model_only=False, personal=None) -> EffectiveResponse:
    if not model_only and personal is None and user is not None and getattr(user, "is_authenticated", False):
        from .oral_history import preferred_personal
        personal = preferred_personal(response, user)
    if model_only:
        personal = None

    if personal is None:
        from .tache_three_models import reviewed_model

        reviewed = reviewed_model(response, prompt)
        if reviewed is not None:
            return reviewed.response
        model = prompt.model_content if prompt is not None else {}
        if model:
            from .tache_two_dialogues import dialogue_response, published_dialogue
            dialogue = published_dialogue(prompt)
            if dialogue is not None:
                return dialogue_response(dialogue)
            return EffectiveResponse(
                **{name: model[name] for name in (
                    "reformulation", "position", "position_claire", "nuance", "conclusion",
                )},
                arguments=tuple(EffectiveArgument(**argument) for argument in model["arguments"]),
                is_personal=False,
            )
        arguments = tuple(
            EffectiveArgument(
                order=argument.order,
                idea=argument.idea,
                developpement=argument.developpement,
                exemple=argument.exemple,
                consequence=argument.consequence,
            )
            for argument in response.arguments.all()
        )
        return EffectiveResponse(
            reformulation=response.reformulation,
            position=response.position,
            position_claire=response.position_claire,
            arguments=arguments,
            nuance=response.nuance,
            conclusion=response.conclusion,
            is_personal=False,
        )

    if not isinstance(personal.arguments, list):
        raise ValueError("Personal response arguments must be a list.")
    arguments = []
    identities = set()
    for argument in personal.arguments:
        value = EffectiveArgument(
            order=int(argument["order"]),
            idea=str(argument["idea"]),
            developpement=str(argument["developpement"]),
            exemple=str(argument["exemple"]),
            consequence=str(argument["consequence"]),
        )
        if "annotation_id" in argument:
            identity = argument["annotation_id"]
            if type(identity) is not int or identity <= 0 or identity in identities:
                raise ValueError("Personal response argument identities must be distinct positive integers.")
            identities.add(identity)
            value = AnnotationArgument(**asdict(value), annotation_id=identity)
        arguments.append(value)
    if identities and len(identities) != len(arguments):
        raise ValueError("Personal response argument identities must cover every argument.")
    return EffectiveResponse(
        reformulation=personal.reformulation,
        position=personal.position,
        position_claire=personal.position_claire,
        arguments=tuple(arguments),
        nuance=personal.nuance,
        conclusion=personal.conclusion,
        is_personal=True,
    )
