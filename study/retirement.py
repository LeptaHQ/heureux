"""Read-time retirement of removed EO3 and replaced EE1/EE3 vocabulary.

Historical phrases, cards, schedules, logs, and review sessions stay untouched.
"""

from django.db.models import Exists, OuterRef, Q

from .models import CardType, ComprehensionQuestion, Phrase, Prompt, Response, Theme


RETIRED_EE_TASKS = ("tache-1", "tache-3")
RETIRED_VOCABULARY_TASKS = {
    ("ee", task) for task in RETIRED_EE_TASKS
} | {("eo", "tache-3")}


def is_retired_vocabulary_task(part, task):
    return (part, task) in RETIRED_VOCABULARY_TASKS


def retired_task_filter(prefix):
    return Q(**{
        f"{prefix}part__slug": "ee",
        f"{prefix}slug__in": RETIRED_EE_TASKS,
    }) | Q(**{
        f"{prefix}part__slug": "eo",
        f"{prefix}slug": "tache-3",
    })


def _retired_task_query():
    return retired_task_filter("theme__task__")


def _direct_retired_task_query():
    return retired_task_filter("vocabulary_theme__task__")


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


def _retired_scope_sources(scope):
    task_filter = _retired_task_query()
    if scope.get("part"):
        task_filter &= Q(theme__task__part__slug=scope["part"])
    if scope.get("task"):
        task_filter &= Q(theme__task__slug=scope["task"])
    if scope.get("response"):
        yield Response.objects.filter(
            Q(pk=scope["response"]) | Q(historical_sources__pk=scope["response"]),
            task_filter,
        )
    if scope.get("prompt"):
        yield Prompt.objects.filter(
            task_filter, pk=scope["prompt"],
        )
    if scope.get("theme"):
        theme_task_filter = retired_task_filter("task__")
        if scope.get("part"):
            theme_task_filter &= Q(task__part__slug=scope["part"])
        if scope.get("task"):
            theme_task_filter &= Q(task__slug=scope["task"])
        yield Theme.objects.filter(
            theme_task_filter, slug=scope["theme"],
        )


def exclude_retired_vocabulary_in_scope(cards, scope):
    """Shared phrases stay active elsewhere, but not in a retired task scope."""
    if is_retired_vocabulary_task(scope.get("part"), scope.get("task")):
        return cards.filter(card_type=CardType.SPINE)
    if scope.get("part") in {"ee", "eo"} and not scope.get("task"):
        active_sources = Prompt.objects.filter(
            phrases=OuterRef("phrase_id"),
            is_active=True,
            theme__is_active=True,
            theme__task__is_active=True,
            theme__task__part__is_active=True,
            theme__task__part__slug=scope["part"],
        ).exclude(retired_task_filter("theme__task__"))
        active_direct = Theme.objects.filter(
            direct_vocabulary_phrases=OuterRef("phrase_id"),
            is_active=True,
            task__is_active=True,
            task__part__is_active=True,
            task__part__slug=scope["part"],
        ).exclude(retired_task_filter("task__"))
        cards = cards.filter(
            Q(card_type=CardType.SPINE)
            | Exists(active_sources)
            | Exists(active_direct)
        )
    for sources in _retired_scope_sources(scope):
        # Resolve inferred task ownership in the card query, not extra queries.
        cards = cards.filter(Q(card_type=CardType.SPINE) | ~Exists(sources))
    return cards


def _scope_has_retired_vocabulary(scope):
    part, task = scope.get("part"), scope.get("task")
    if part and task:
        return is_retired_vocabulary_task(part, task)
    if scope.get("theme") and not scope.get("response") and not scope.get("prompt"):
        owners = Theme.objects.filter(slug=scope["theme"])
        if part:
            owners = owners.filter(task__part__slug=part)
        if task:
            owners = owners.filter(task__slug=task)
        if owners.exclude(retired_task_filter("task__")).exists():
            return False
    return any(sources.exists() for sources in _retired_scope_sources(scope))


def is_retired_vocabulary_scope(scope):
    """Return whether a scope targets removed task vocabulary."""
    vocabulary = (
        scope.get("kind") in {"vocab", "phrase", "theme_vocab"}
        or scope.get("content") in {"vocabulary", "theme_vocabulary"}
        or bool(scope.get("category"))
    )
    if not vocabulary or scope.get("test"):
        return False
    return _scope_has_retired_vocabulary(scope)
