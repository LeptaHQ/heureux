"""Read-time retirement of replaced EE1/EE3 vocabulary.

Historical phrases, cards, schedules, logs, and review sessions stay untouched.
"""

from django.db.models import Exists, OuterRef, Q
from django.urls import reverse

from .models import CardType, ComprehensionQuestion, Phrase, Prompt, Response, Theme


RETIRED_EE_TASKS = ("tache-1", "tache-3")


def _retired_task_query():
    return Q(
        theme__task__part__slug="ee",
        theme__task__slug__in=RETIRED_EE_TASKS,
    )


def _direct_retired_task_query():
    return Q(
        vocabulary_theme__task__part__slug="ee",
        vocabulary_theme__task__slug__in=RETIRED_EE_TASKS,
    )


def retired_vocabulary():
    sources = Prompt.objects.filter(phrases=OuterRef("pk"))
    prompts = sources.filter(
        is_active=True, theme__is_active=True,
        theme__task__is_active=True, theme__task__part__is_active=True,
    )
    retired = _retired_task_query()
    direct_retired = _direct_retired_task_query()
    questions = ComprehensionQuestion.objects.filter(
        vocabulary=OuterRef("pk"), test__is_active=True,
    )
    return Phrase.objects.alias(
        _retired=Exists(sources.filter(retired)),
        _other=Exists(prompts.exclude(retired)),
        _comprehension=Exists(questions),
    ).filter(
        Q(_retired=True) | direct_retired,
    ).exclude(
        Q(_other=True) | Q(_comprehension=True)
        | (
            Q(vocabulary_theme__is_active=True, vocabulary_theme__task__is_active=True)
            & ~direct_retired
        ),
    ).order_by().values("pk")


def active_phrases(queryset=None):
    queryset = Phrase.objects.all() if queryset is None else queryset
    return queryset.exclude(pk__in=retired_vocabulary())


def _retired_scope_sources(scope, task_slug=None):
    task_filter = (
        {"theme__task__slug": task_slug}
        if task_slug else {"theme__task__slug__in": RETIRED_EE_TASKS}
    )
    if scope.get("response"):
        yield Response.objects.filter(
            Q(pk=scope["response"]) | Q(historical_sources__pk=scope["response"]),
            theme__task__part__slug="ee", **task_filter,
        )
    if scope.get("prompt"):
        yield Prompt.objects.filter(
            pk=scope["prompt"], theme__task__part__slug="ee", **task_filter,
        )
    if scope.get("theme"):
        theme_task_filter = {
            key.removeprefix("theme__"): value
            for key, value in task_filter.items()
        }
        yield Theme.objects.filter(
            slug=scope["theme"], task__part__slug="ee", **theme_task_filter,
        )


def exclude_retired_vocabulary_in_scope(cards, scope):
    """Shared phrases stay active elsewhere, but not in a retired EE scope."""
    if (
        scope.get("part") == "ee"
        and scope.get("task") in RETIRED_EE_TASKS
    ):
        return cards.filter(card_type=CardType.SPINE)
    if scope.get("part") == "ee" and not scope.get("task"):
        active_sources = Prompt.objects.filter(
            phrases=OuterRef("phrase_id"),
            is_active=True,
            theme__is_active=True,
            theme__task__is_active=True,
            theme__task__part__is_active=True,
            theme__task__part__slug="ee",
        ).exclude(theme__task__slug__in=RETIRED_EE_TASKS)
        active_direct = Theme.objects.filter(
            direct_vocabulary_phrases=OuterRef("phrase_id"),
            is_active=True,
            task__is_active=True,
            task__part__is_active=True,
            task__part__slug="ee",
        ).exclude(task__slug__in=RETIRED_EE_TASKS)
        cards = cards.filter(
            Q(card_type=CardType.SPINE)
            | Exists(active_sources)
            | Exists(active_direct)
        )
    for sources in _retired_scope_sources(scope):
        # Resolve inferred task ownership in the card query, not extra queries.
        cards = cards.filter(Q(card_type=CardType.SPINE) | ~Exists(sources))
    return cards


def exclude_ee3_vocabulary_in_scope(cards, scope):
    """Compatibility alias for callers predating EE1 vocabulary retirement."""
    return exclude_retired_vocabulary_in_scope(cards, scope)


def formulations_replacement(theme="", *, tache=3):
    from .ee_formulations import get_ee_formulations

    routes = {
        1: (
            "study:ee_tache_one_formulations",
            "study:ee_tache_one_formulation_theme",
        ),
        3: ("study:ee_formulations", "study:ee_formulation_theme"),
    }
    directory_route, theme_route = routes[tache]
    url = reverse(directory_route)
    slug = theme.removeprefix(f"ee-tache-{tache}-")
    if slug and any(
        category.kind == "theme" and category.slug == slug
        for category in get_ee_formulations(tache).categories
    ):
        url = reverse(theme_route, args=[slug])
    return url


def _scope_retired_tache(scope):
    part, task = scope.get("part"), scope.get("task")
    if part == "ee" and task in RETIRED_EE_TASKS:
        return int(task.removeprefix("tache-"))
    if part and part != "ee":
        return None
    if task and task not in RETIRED_EE_TASKS:
        return None
    for tache in (1, 3):
        task_slug = f"tache-{tache}"
        if any(
            sources.exists()
            for sources in _retired_scope_sources(scope, task_slug)
        ):
            return tache
    return None


def retired_scope_url(scope):
    """Only explicit vocabulary scopes redirect; response and mixed study remain."""
    vocabulary = (
        scope.get("kind") in {"vocab", "phrase", "theme_vocab"}
        or scope.get("content") in {"vocabulary", "theme_vocabulary"}
        or bool(scope.get("category"))
    )
    if not vocabulary or scope.get("test"):
        return None
    tache = _scope_retired_tache(scope)
    return (
        formulations_replacement(scope.get("theme", ""), tache=tache)
        if tache else None
    )
