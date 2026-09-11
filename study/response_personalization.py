from __future__ import annotations

from dataclasses import dataclass

from .models import PersonalResponse


@dataclass(frozen=True)
class EffectiveArgument:
    order: int
    idea: str
    developpement: str
    exemple: str
    consequence: str


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
        model = prompt.model_content if prompt is not None else {}
        if model:
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
    arguments = tuple(
        EffectiveArgument(
            order=int(argument["order"]),
            idea=str(argument["idea"]),
            developpement=str(argument["developpement"]),
            exemple=str(argument["exemple"]),
            consequence=str(argument["consequence"]),
        )
        for argument in personal.arguments
    )
    return EffectiveResponse(
        reformulation=personal.reformulation,
        position=personal.position,
        position_claire=personal.position_claire,
        arguments=arguments,
        nuance=personal.nuance,
        conclusion=personal.conclusion,
        is_personal=True,
    )
