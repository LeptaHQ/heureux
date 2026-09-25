"""Read-time retirement of EE3 vocabulary; historical records stay untouched."""

from urllib.parse import urlencode

from django.db.models import Exists, OuterRef, Q
from django.urls import reverse

from .models import CardType, ComprehensionQuestion, Phrase, Prompt, Response, Theme


def retired_vocabulary():
    sources = Prompt.objects.filter(phrases=OuterRef("pk"))
    prompts = sources.filter(
        is_active=True, theme__is_active=True,
        theme__task__is_active=True, theme__task__part__is_active=True,
    )
    ee3 = Q(theme__task__part__slug="ee", theme__task__slug="tache-3")
    direct_ee3 = Q(
        vocabulary_theme__task__part__slug="ee",
        vocabulary_theme__task__slug="tache-3",
    )
    questions = ComprehensionQuestion.objects.filter(
        vocabulary=OuterRef("pk"), test__is_active=True,
    )
    return Phrase.objects.alias(
        _ee3=Exists(sources.filter(ee3)),
        _other=Exists(prompts.exclude(ee3)),
        _comprehension=Exists(questions),
    ).filter(
        Q(_ee3=True) | direct_ee3,
    ).exclude(
        Q(_other=True) | Q(_comprehension=True)
        | (
            Q(vocabulary_theme__is_active=True, vocabulary_theme__task__is_active=True)
            & ~direct_ee3
        ),
    ).order_by().values("pk")


def active_phrases(queryset=None):
    queryset = Phrase.objects.all() if queryset is None else queryset
    return queryset.exclude(pk__in=retired_vocabulary())


def _ee3_scope_sources(scope):
    if scope.get("response"):
        yield Response.objects.filter(
            Q(pk=scope["response"]) | Q(historical_sources__pk=scope["response"]),
            theme__task__part__slug="ee", theme__task__slug="tache-3",
        )
    if scope.get("prompt"):
        yield Prompt.objects.filter(
            pk=scope["prompt"], theme__task__part__slug="ee",
            theme__task__slug="tache-3",
        )
    if scope.get("theme"):
        yield Theme.objects.filter(
            slug=scope["theme"], task__part__slug="ee", task__slug="tache-3",
        )


def exclude_ee3_vocabulary_in_scope(cards, scope):
    """Shared phrases stay active elsewhere, but never inside an EE3 scope."""
    if scope.get("part") == "ee" and scope.get("task") == "tache-3":
        return cards.filter(card_type=CardType.SPINE)
    for sources in _ee3_scope_sources(scope):
        # Resolve inferred task ownership in the card query, not extra queries.
        cards = cards.filter(Q(card_type=CardType.SPINE) | ~Exists(sources))
    return cards


def formulations_replacement(theme=""):
    from .ee_formulations import get_ee_formulations

    url = reverse("study:ee_formulations")
    slug = theme.removeprefix("ee-tache-3-")
    if slug and any(
        category.kind == "theme" and category.slug == slug
        for category in get_ee_formulations().categories
    ):
        url += "?" + urlencode({"theme": slug})
    return url


def retired_scope_url(scope):
    """Only explicit vocabulary scopes redirect; response and mixed study remain."""
    vocabulary = (
        scope.get("kind") in {"vocab", "phrase", "theme_vocab"}
        or scope.get("content") in {"vocabulary", "theme_vocabulary"}
        or bool(scope.get("category"))
    )
    if not vocabulary or scope.get("test"):
        return None
    part, task = scope.get("part"), scope.get("task")
    if part and part != "ee":
        return None
    if task and task != "tache-3":
        return None
    ee3 = part == "ee" and task == "tache-3"
    if not ee3:
        ee3 = any(sources.exists() for sources in _ee3_scope_sources(scope))
    return formulations_replacement(scope.get("theme", "")) if ee3 else None
