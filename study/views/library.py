"""Content browsing, phrase library, detail pages, and stats."""

from __future__ import annotations

from functools import lru_cache


from django.db.models import Count, Prefetch, Q
from django.db.models.functions import TruncDate
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import content_loader as content_module
from .. import queue as queue_module
from ..card_presentation import scope_label
from ..forms import (
    PersonalResponseForm,
    TacheTwoQuestionFormSet,
)
from ..models import (
    Annotation,
    Card,
    CardState,
    CardType,
    ComprehensionAttempt,
    ComprehensionMode,
    ComprehensionQuestion,
    ComprehensionTest,
    ExamPart,
    Family,
    MemoryQuestionProgress,
    PERSONAL_QUESTION_RESPONSE_MAX_LENGTH,
    PersonalQuestionResponse,
    Phrase,
    PhraseCategory,
    PhraseTier,
    PersonalResponse,
    PersonalWritingResponse,
    Prompt,
    Rating,
    Response,
    ReviewLog,
    Task,
    Theme,
    ThemeVocabularyProgress,
    WritingSujet,
    WritingSujetCompletion,
)
from .. import routing
from ..response_personalization import effective_response
from ..progress import (
    card_unit_progress_from_rows,
    combine_progress,
    progress_summary,
    subject_progress_by_response,
    summarize_subject_progress,
    writing_sujet_progress_by_id,
)
from ..routing import (
    comprehension_skill,
    comprehension_vocabulary_url,
    prompt_detail_url,
    review_url,
    vocabulary_url,
)

from .helpers import (
    FUNCTIONAL_PHRASE_CATEGORY_NAMES,
    MATURE_DAYS,
    _memory_progress,
    _review_batches,
    _route_task,
    _task_card,
    _task_cards,
    _task_content_counts,
    _task_phrases,
    _task_scope,
    _tache_two_progress,
    _tache_two_theme_progress,
    batch_rows,
    deck_stats,
    deck_stats_from_rows,
    empty_deck_stats,
    expression_task_summaries,
    grouped_deck_stats,
    recent_review_sessions,
    review_batches_from_rows,
    summarize_review_batches,
)
def _subject_stats_for_themes(themes, user, now=None):
    now = now or timezone.now()
    response_ids_by_theme = {theme.pk: set() for theme in themes}
    for theme_id, response_id in Prompt.objects.filter(
        theme_id__in=response_ids_by_theme,
        is_active=True,
        response__is_active=True,
    ).values_list("theme_id", "response_id"):
        response_ids_by_theme[theme_id].add(response_id)
    response_ids = {
        response_id
        for theme_response_ids in response_ids_by_theme.values()
        for response_id in theme_response_ids
    }
    progress = subject_progress_by_response(user, response_ids)
    due_response_ids = set(
        Card.objects.active()
        .filter(
            user=user,
            card_type=CardType.SPINE,
            response_id__in=response_ids,
            state__in={
                CardState.LEARNING,
                CardState.RELEARNING,
                CardState.REVIEW,
            },
            due__lte=now,
        )
        .values_list("response_id", flat=True)
    )
    stats = {}
    for theme_id, theme_response_ids in response_ids_by_theme.items():
        summary = summarize_subject_progress(
            progress[response_id] for response_id in theme_response_ids
        )
        summary["due"] = len(theme_response_ids & due_response_ids)
        stats[theme_id] = summary
    return stats, progress, due_response_ids


def _distinct_count(qs) -> int:
    """Count matching rows without a DISTINCT over every selected column.

    ``qs.distinct().count()`` becomes ``COUNT(*) FROM (SELECT DISTINCT <every
    column>)``, which makes the database build a temporary index over the whole
    row. Counting distinct primary keys returns the same number for far less
    work.
    """
    return qs.order_by().aggregate(total=Count("pk", distinct=True))["total"]


def _prompt_counts_by_theme(themes=None, *, task=None) -> dict:
    """Active prompt count per theme, grouped once instead of once per theme.

    Passing ``task`` covers every theme of that task, archived ones included,
    so the caller can read both each theme's count and the task total from the
    same query.
    """
    prompts = Prompt.objects.filter(is_active=True)
    if task is not None:
        prompts = prompts.filter(theme__task=task)
    else:
        theme_ids = [theme.pk for theme in themes]
        if not theme_ids:
            return {}
        prompts = prompts.filter(theme_id__in=theme_ids)
    return {
        row["theme_id"]: row["total"]
        for row in (
            prompts.order_by().values("theme_id").annotate(total=Count("id"))
        )
    }


def _vocabulary_deck_progress(progress_items):
    items = list(progress_items)
    return progress_summary(
        total=len(items),
        started=sum(item.vocabulary_activity_started for item in items),
        completed=sum(
            bool(item.vocabulary_total)
            and item.vocabulary_completed == item.vocabulary_total
            for item in items
        ),
    )


def _task_subject_vocabulary_context(
    task,
    user,
    theme=None,
    progress_by_response=None,
):
    prompt_filters = {
        "is_active": True,
        "response__is_active": True,
        "theme__is_active": True,
        "theme__task": task,
    }
    subject_vocabulary = Phrase.objects.filter(
        is_active=True,
        tier=PhraseTier.SUBJECT,
        source_prompts__is_active=True,
        source_prompts__theme__is_active=True,
        source_prompts__theme__task=task,
    )
    if theme is not None:
        prompt_filters["theme"] = theme
        subject_vocabulary = subject_vocabulary.filter(
            source_prompts__theme=theme,
        )

    vocabulary_counts = dict(
        Prompt.objects.filter(**prompt_filters)
        .values_list("pk")
        .annotate(
            vocabulary_count=Count(
                "phrases",
                filter=Q(
                    phrases__is_active=True,
                    phrases__tier=PhraseTier.SUBJECT,
                ),
                distinct=True,
            )
        )
        .filter(vocabulary_count__gt=0)
        .values_list("pk", "vocabulary_count")
    )
    prompts = list(
        Prompt.objects.filter(
            **prompt_filters,
            pk__in=vocabulary_counts,
        )
        .select_related("theme__task__part", "family", "response")
        .order_by("theme__order", "number", "pk")
    )
    for prompt in prompts:
        prompt.vocabulary_count = vocabulary_counts[prompt.pk]

    response_ids = {prompt.response_id for prompt in prompts}
    if progress_by_response is None:
        progress_by_response = subject_progress_by_response(user, response_ids)
    else:
        progress_by_response = {
            response_id: progress_by_response[response_id]
            for response_id in response_ids
        }
    subject_vocabulary_count = _distinct_count(subject_vocabulary)
    phrase_counts_by_theme = (
        {theme.pk: subject_vocabulary_count}
        if theme is not None
        else dict(
            subject_vocabulary.order_by()
            .values("source_prompts__theme_id")
            .annotate(total=Count("pk", distinct=True))
            .values_list("source_prompts__theme_id", "total")
        )
    )
    groups = []
    current_group = None
    for prompt in prompts:
        prompt.detail_url = prompt_detail_url(prompt)
        prompt.review_url = review_url(
            {
                "part": task.part.slug,
                "task": task.slug,
                "kind": "vocab",
                "response": str(prompt.response_id),
                "batch": "1",
            }
        )
        prompt.vocabulary_batch_count = (
            prompt.vocabulary_count + queue_module.PHRASE_BATCH_SIZE - 1
        ) // queue_module.PHRASE_BATCH_SIZE
        prompt.subject_progress = progress_by_response[prompt.response_id]
        prompt.vocabulary_progress = prompt.subject_progress.vocabulary_progress
        if current_group is None or current_group["theme"].pk != prompt.theme_id:
            current_group = {
                "theme": prompt.theme,
                "prompts": [],
                "response_ids": set(),
            }
            groups.append(current_group)
        current_group["prompts"].append(prompt)
        current_group["response_ids"].add(prompt.response_id)

    for group in groups:
        group_response_ids = group.pop("response_ids")
        group_progress = [
            progress_by_response[response_id]
            for response_id in group_response_ids
        ]
        group["deck_count"] = len(group_response_ids)
        group["batch_count"] = sum(
            prompt.vocabulary_batch_count
            for prompt in {
                prompt.response_id: prompt for prompt in group["prompts"]
            }.values()
        )
        group["phrase_count"] = phrase_counts_by_theme.get(
            group["theme"].pk,
            0,
        )
        group["progress"] = _vocabulary_deck_progress(group_progress)
        group["url"] = reverse(
            "study:task_vocabulary_theme",
            args=[task.part.slug, task.slug, group["theme"].slug],
        )
        group["review_url"] = review_url(
            {
                **_task_scope(task),
                "kind": "vocab",
                "theme": group["theme"].slug,
            }
        )

    vocabulary_deck_summary = _vocabulary_deck_progress(
        progress_by_response.values()
    )
    return {
        "subject_theme_groups": groups,
        "subject_prompt_count": len(prompts),
        "subject_response_count": len(response_ids),
        "subject_vocabulary_count": subject_vocabulary_count,
        "vocabulary_deck_summary": vocabulary_deck_summary,
        "vocabulary_directory_summary": {
            "progress": vocabulary_deck_summary,
            "completed": vocabulary_deck_summary.completed,
            "total": vocabulary_deck_summary.total,
            "started_new": max(
                vocabulary_deck_summary.started
                - vocabulary_deck_summary.completed,
                0,
            ),
        },
    }


def _phrase_deck_stats(now, user=None, task=None):
    cards = (
        _task_cards(task, user, "phrase")
        if task
        else queue_module.scoped_cards({"kind": "phrase"}, user=user)
    )
    return deck_stats(cards, now)


def _question_bank_memory_context(user, memories):
    memory_states = _memory_progress(user, memories)
    memory_items = [
        {
            "memory": memory,
            **memory_states[memory.number],
        }
        for memory in memories
    ]
    progress = combine_progress(
        item["progress"] for item in memory_items
    )
    return {
        "memories": memory_items,
        "memory_count": len(memories),
        "category_count": sum(memory.category_count for memory in memories),
        "question_count": sum(memory.question_count for memory in memories),
        "completed_count": progress.completed,
        "memory_summary": {
            "progress": progress,
            "completed": progress.completed,
            "total": progress.total,
            "started_new": max(progress.started - progress.completed, 0),
        },
    }


def _theme_vocabulary_scope(task, theme=None):
    scope = {
        "kind": "theme_vocab",
        "part": task.part.slug,
        "task": task.slug,
    }
    if theme is not None:
        scope["theme"] = theme.slug
    return scope


def _theme_vocabulary_batch_summary(batches):
    progress = summarize_review_batches(batches)
    return {
        "progress": progress,
        "completed": progress.completed,
        "total": progress.total,
        "started_new": max(progress.started - progress.completed, 0),
    }


def _theme_vocabulary_status_counts(themes):
    counts = {"all": len(themes), "new": 0, "active": 0, "done": 0}
    for item in themes:
        counts[item["summary"]["progress"].status] += 1
    return counts


def _theme_vocabulary_directory_batches(task, user, themes):
    """Task-level lots and each theme's lots, from one fetch of the rows.

    A theme-vocabulary card always targets a phrase, so a theme's deck is
    exactly the task's rows whose phrase is sourced from a prompt of that
    theme. The task query already orders the rows down to the card id, so
    filtering that list per theme yields the same lots — and the same lot
    numbers — as running the query once per theme.
    """
    scope = _theme_vocabulary_scope(task)
    rows = batch_rows(scope, user)
    theme_slugs_by_phrase = {}
    phrase_ids = {row["phrase_id"] for row in rows}
    if phrase_ids:
        if _ee_writing_tache(task) is not None:
            phrase_themes = Phrase.objects.filter(
                pk__in=phrase_ids,
            ).values_list("pk", "vocabulary_theme__slug")
        else:
            phrase_themes = (
                Phrase.objects.filter(pk__in=phrase_ids)
                .order_by()
                .values_list("pk", "source_prompts__theme__slug")
                .distinct()
            )
        for phrase_id, theme_slug in phrase_themes:
            if theme_slug:
                theme_slugs_by_phrase.setdefault(phrase_id, set()).add(
                    theme_slug
                )
    batches_by_theme = {}
    for theme in themes:
        batches_by_theme[theme.slug] = review_batches_from_rows(
            [
                row
                for row in rows
                if theme.slug
                in theme_slugs_by_phrase.get(row["phrase_id"], ())
            ],
            _theme_vocabulary_scope(task, theme),
        )
    return review_batches_from_rows(rows, scope), batches_by_theme


def _tache_two_theme_vocabulary_overview_context(user, task):
    scope = _theme_vocabulary_scope(task)
    batches = _review_batches(scope, user)
    phrase_count = _distinct_count(
        Phrase.objects.filter(
            tier=PhraseTier.THEME,
            is_active=True,
            source_prompts__is_active=True,
            source_prompts__theme__task=task,
        )
    )
    next_batch = next(
        (batch for batch in batches if batch["is_next"]),
        None,
    )
    return {
        "theme_count": len(content_module.load_tache_two_subject_themes()[0]),
        "phrase_count": phrase_count,
        "batch_count": len(batches),
        "progress_unit": "lots terminés",
        "summary": _theme_vocabulary_batch_summary(batches),
        "url": reverse("study:tache_two_theme_vocabulary"),
        "review_url": next_batch["review_url"] if next_batch else "",
    }


def part_detail(request, part_slug):
    part = get_object_or_404(
        ExamPart.objects.filter(is_active=True).prefetch_related(
            Prefetch("tasks", queryset=Task.objects.filter(is_active=True))
        ),
        slug=part_slug,
    )
    now = timezone.now()
    part_tasks = list(part.tasks.all())
    content_counts = _task_content_counts(part_tasks)
    # The part page renders subject progress, the catalogue counts and the due
    # response badge — never the vocabulary decks, queue badges or revisit
    # count, each of which costs its own scan of the learner's whole deck. The
    # subject summary itself comes from the same batched pass the expression
    # hub uses, so it costs a fixed handful of queries rather than one set per
    # task.
    summaries = expression_task_summaries(
        now,
        request.user,
        part_tasks,
        content_counts,
    )
    tasks = [
        _task_card(
            task,
            now,
            request.user,
            with_deck_stats=False,
            content_counts=content_counts,
            summaries=summaries,
        )
        for task in part_tasks
    ]
    if not part.available or not tasks:
        return render(
            request,
            "study/coming_soon.html",
            {"part": part, "task": None},
        )
    return render(
        request,
        "study/part_detail.html",
        {
            "part": part,
            "tasks": tasks,
            "available_task_count": sum(
                task["task"].available for task in tasks
            ),
        },
    )


def part_vocabulary(request, part_slug):
    part = get_object_or_404(ExamPart, slug=part_slug, is_active=True)
    return redirect(
        "study:part_detail",
        part_slug=part.slug,
    )


def _has_ee_tache_three_content(task):
    return Prompt.objects.filter(
        content_key__startswith=content_module.EE_TACHE_THREE_CONTENT_PREFIX,
        theme__task=task,
        is_active=True,
        response__is_active=True,
    ).exists()


@lru_cache(maxsize=1)
def _ee_tache_three_source_months():
    return content_module.load_ee_tache_three_months()


@lru_cache(maxsize=3)
def _ee_subject_theme_data(tache):
    return content_module.load_ee_subject_themes(tache)


@lru_cache(maxsize=1)
def _ee_tache_three_sources_by_key():
    return {
        combinaison.content_key: (month, combinaison)
        for month in _ee_tache_three_source_months()
        for combinaison in month.combinaisons
    }


def _ee_tache_three_subject_context(user, task):
    source_months = _ee_tache_three_source_months()
    source_rows = [
        (month, combinaison)
        for month in source_months
        for combinaison in month.combinaisons
    ]
    source_keys = [combinaison.content_key for _month, combinaison in source_rows]
    theme_data, theme_slug_by_key = _ee_subject_theme_data(3)
    theme_names = {
        content_module.ee_subject_theme_name(3, theme) for theme in theme_data
    }
    themes_by_name = {
        theme.name: theme
        for theme in Theme.objects.filter(
            task=task,
            is_active=True,
            name__in=theme_names,
        )
    }
    prompts_by_key = {
        prompt.content_key: prompt
        for prompt in Prompt.objects.filter(
            content_key__in=source_keys,
            theme__task=task,
            is_active=True,
            response__is_active=True,
        ).select_related("response", "theme", "family")
    }
    if (
        set(source_keys) - prompts_by_key.keys()
        or theme_names - themes_by_name.keys()
    ):
        raise RuntimeError("EE Tâche 3 content is not synchronized")

    progress_by_response = subject_progress_by_response(
        user,
        {
            prompt.response_id
            for prompt in prompts_by_key.values()
        },
    )
    response_occurrence_counts = {}
    for prompt in prompts_by_key.values():
        response_occurrence_counts[prompt.response_id] = (
            response_occurrence_counts.get(prompt.response_id, 0) + 1
        )

    sources_by_theme = {theme.slug: [] for theme in theme_data}
    for month, combinaison in source_rows:
        sources_by_theme[theme_slug_by_key[combinaison.content_key]].append(
            (month, combinaison)
        )

    all_progress = []
    subject_themes = []
    for source_theme in theme_data:
        theme = themes_by_name[
            content_module.ee_subject_theme_name(3, source_theme)
        ]
        subjects = []
        theme_progress = []
        for source_month, combinaison in sources_by_theme[source_theme.slug]:
            prompt = prompts_by_key[combinaison.content_key]
            progress = progress_by_response[prompt.response_id]
            theme_progress.append(progress)
            all_progress.append(progress)
            subjects.append(
                {
                    "position": combinaison.position,
                    "combination_label": combinaison.combinaison,
                    "combination_number": (
                        combinaison.combinaison.removeprefix(
                            "Combinaison "
                        ).strip()
                    ),
                    "prompt": prompt,
                    "progress": progress,
                    "month_slug": source_month.slug,
                    "month_name": source_month.name,
                    "month_number": source_month.number,
                    "year": 2025,
                    "is_alias": not prompt.is_canonical,
                    "equivalent_count": (
                        response_occurrence_counts[prompt.response_id] - 1
                    ),
                    "has_source_issue": combinaison.has_source_issue,
                    "document_count": sum(
                        bool(document.strip())
                        for document in (
                            combinaison.document1,
                            combinaison.document2,
                        )
                    ),
                    "vocabulary_count": (
                        content_module.EE_TACHE_THREE_VOCABULARY_PER_RESPONSE
                    ),
                }
            )

        summary = summarize_subject_progress(theme_progress)
        subject_themes.append(
            {
                "slug": source_theme.slug,
                "name": source_theme.name,
                "icon": source_theme.icon,
                "theme": theme,
                "subjects": subjects,
                "subject_count": len(subjects),
                "vocabulary_count": (
                    len({row["prompt"].response_id for row in subjects})
                    * content_module.EE_TACHE_THREE_VOCABULARY_PER_RESPONSE
                ),
                "review_url": review_url(
                    {
                        "kind": "spine",
                        "part": task.part.slug,
                        "task": task.slug,
                        "theme": theme.slug,
                    }
                ),
                **summary,
            }
        )

    summary = summarize_subject_progress(all_progress)
    response_count = len(
        {prompt.response_id for prompt in prompts_by_key.values()}
    )
    return {
        "subject_themes": subject_themes,
        "_progress_by_response": progress_by_response,
        "theme_count": len(subject_themes),
        "month_count": len(source_months),
        "subject_count": len(all_progress),
        "distinct_count": response_count,
        "vocabulary_count": (
            response_count
            * content_module.EE_TACHE_THREE_VOCABULARY_PER_RESPONSE
        ),
        "subject_summary": summary,
    }


def _ee_tache_three_overview_context(user, task):
    source_months = _ee_tache_three_source_months()
    source_keys = [
        combinaison.content_key
        for month in source_months
        for combinaison in month.combinaisons
    ]
    response_id_by_key = dict(
        Prompt.objects.filter(
            content_key__in=source_keys,
            theme__task=task,
            is_active=True,
            response__is_active=True,
        ).values_list("content_key", "response_id")
    )
    if set(response_id_by_key) != set(source_keys):
        raise RuntimeError("EE Tâche 3 content is not synchronized")
    progress_by_response = subject_progress_by_response(
        user,
        set(response_id_by_key.values()),
    )
    all_progress = [
        progress_by_response[response_id_by_key[source_key]]
        for source_key in source_keys
    ]
    response_count = len(progress_by_response)
    return {
        "_progress_by_response": progress_by_response,
        "theme_count": len(_ee_subject_theme_data(3)[0]),
        "month_count": len(source_months),
        "subject_count": len(all_progress),
        "distinct_count": response_count,
        "vocabulary_count": (
            response_count
            * content_module.EE_TACHE_THREE_VOCABULARY_PER_RESPONSE
        ),
        "subject_summary": summarize_subject_progress(all_progress),
    }


def _has_ee_tache_one_content(task):
    return WritingSujet.objects.filter(task=task, is_active=True).exists()


def _ee_tache_one_subject_context(user, task):
    """Group EE Tâche 1 message sujets by theme, best model version first."""
    sujets = list(
        WritingSujet.objects.filter(task=task, is_active=True).order_by(
            "order",
            "id",
        )
    )
    progress_by_sujet = writing_sujet_progress_by_id(
        user,
        (sujet.pk for sujet in sujets),
        task_id=task.pk,
    )
    categories = []
    current = None
    response_count = 0
    for sujet in sujets:
        model_versions = sujet.model_versions
        if model_versions:
            response_count += 1
        progress = progress_by_sujet[sujet.pk]
        is_personalized = progress.is_personalized
        explicitly_completed = progress.explicitly_completed
        row = {
            "sujet": sujet,
            "prompt": sujet.prompt,
            "version_count": len(model_versions),
            "has_model_response": bool(model_versions),
            "is_personalized": is_personalized,
            "explicitly_completed": explicitly_completed,
            "progress": progress,
        }
        if current is None or current["slug"] != sujet.category:
            current = {
                "slug": sujet.category,
                "label": sujet.category_label,
                "sujets": [],
            }
            categories.append(current)
        current["sujets"].append(row)

    for category in categories:
        category["count"] = len(category["sujets"])
        category["personalized_count"] = sum(
            row["is_personalized"] for row in category["sujets"]
        )
        category["progress"] = progress_summary(
            total=category["count"],
            started=sum(row["progress"].started for row in category["sujets"]),
            completed=sum(
                row["progress"].completed for row in category["sujets"]
            ),
        )
        category["to_write_count"] = sum(
            not row["has_model_response"] for row in category["sujets"]
        )

    total = len(sujets)
    personalized = sum(
        progress.is_personalized for progress in progress_by_sujet.values()
    )
    completed = sum(
        progress.explicitly_completed for progress in progress_by_sujet.values()
    )
    return {
        "categories": categories,
        "category_count": len(categories),
        "sujet_count": total,
        "response_count": response_count,
        "personalized_count": personalized,
        "completed_count": completed,
        "subject_progress": progress_summary(
            total=total,
            started=sum(
                progress.started for progress in progress_by_sujet.values()
            ),
            completed=completed,
        ),
    }


def _ee_writing_tache(task):
    return {
        content_module.EE_TACHE_ONE_TASK: 1,
        content_module.EE_TACHE_TWO_TASK: 2,
    }.get((task.part.slug, task.slug))


def _ee_writing_sujet_ids_by_slug(task, tache):
    expected = {
        source.slug
        for category in _ee_writing_source_categories(tache)
        for source in category.sujets
    }
    actual = dict(
        WritingSujet.objects.filter(
            task=task,
            is_active=True,
            slug__in=expected,
        ).values_list("slug", "pk")
    )
    return actual if set(actual) == expected else None


@lru_cache(maxsize=2)
def _ee_writing_source_categories(tache):
    return content_module.load_ee_writing_categories(tache)


def _ee_writing_subject_context(
    user,
    task,
    tache,
    *,
    allow_unsynchronized=False,
):
    """Build the themed 2025 writing directory with shared canonical progress."""
    source_categories = _ee_writing_source_categories(tache)
    theme_data, _ = _ee_subject_theme_data(tache)
    icon_by_slug = {theme.slug: theme.icon for theme in theme_data}
    canonical_slug_by_slug = (
        content_module.ee_writing_canonical_slug_by_slug(tache)
    )
    source_by_slug = {
        source.slug: source
        for category in source_categories
        for source in category.sujets
    }
    sujets_by_slug = {
        sujet.slug: sujet
        for sujet in WritingSujet.objects.filter(
            task=task,
            is_active=True,
            slug__in=source_by_slug,
        ).order_by("order", "pk")
    }
    if set(source_by_slug) != set(sujets_by_slug):
        if allow_unsynchronized:
            return None
        raise RuntimeError(f"EE Tâche {tache} writing content is not synchronized")

    canonical_by_slug = {
        slug: sujets_by_slug[canonical_slug_by_slug[slug]]
        for slug in source_by_slug
    }
    canonical_ids = {
        sujet.pk for sujet in canonical_by_slug.values()
    }
    progress_by_canonical = writing_sujet_progress_by_id(
        user,
        canonical_ids,
        task_id=task.pk,
    )
    equivalent_count_by_id = {}
    for canonical in canonical_by_slug.values():
        equivalent_count_by_id[canonical.pk] = (
            equivalent_count_by_id.get(canonical.pk, 0) + 1
        )

    categories = []
    all_progress = []
    for source_category in source_categories:
        rows = []
        category_progress = []
        for source in source_category.sujets:
            sujet = sujets_by_slug[source.slug]
            canonical = canonical_by_slug[source.slug]
            progress = progress_by_canonical[canonical.pk]
            category_progress.append(progress)
            all_progress.append(progress)
            model_versions = canonical.model_versions
            rows.append(
                {
                    "sujet": sujet,
                    "progress_sujet": canonical,
                    "prompt": source.prompt,
                    "source": source,
                    "source_url": (
                        content_module.EE_2025_SOURCE_URL.format(
                            month=source.month_slug
                        )
                        if source
                        else ""
                    ),
                    "version_count": len(model_versions),
                    "has_model_response": bool(model_versions),
                    "is_personalized": progress.is_personalized,
                    "explicitly_completed": progress.explicitly_completed,
                    "progress": progress,
                    "is_alias": sujet.pk != canonical.pk,
                    "equivalent_count": (
                        equivalent_count_by_id[canonical.pk] - 1
                    ),
                }
            )
        category_summary = progress_summary(
            total=len(category_progress),
            started=sum(item.started for item in category_progress),
            completed=sum(item.completed for item in category_progress),
        )
        categories.append(
            {
                "slug": source_category.slug,
                "label": source_category.label,
                "icon": icon_by_slug[source_category.slug],
                "sujets": rows,
                "count": len(rows),
                "progress": category_summary,
                "personalized_count": len(
                    {
                        row["progress_sujet"].pk
                        for row in rows
                        if row["is_personalized"]
                    }
                ),
            }
        )

    distinct_progress = list(progress_by_canonical.values())
    minimum, maximum = content_module.EE_WRITING_WORD_LIMITS[tache]
    return {
        "categories": categories,
        "category_count": len(categories),
        "sujet_count": len(source_by_slug),
        "distinct_count": len(canonical_ids),
        "response_count": sum(
            bool(sujet.model_versions)
            for sujet in {
                item.pk: item for item in canonical_by_slug.values()
            }.values()
        ),
        "personalized_count": sum(
            item.is_personalized for item in distinct_progress
        ),
        "completed_count": sum(
            item.explicitly_completed for item in distinct_progress
        ),
        "subject_progress": progress_summary(
            total=len(all_progress),
            started=sum(item.started for item in all_progress),
            completed=sum(item.completed for item in all_progress),
        ),
        "distinct_progress": progress_summary(
            total=len(distinct_progress),
            started=sum(item.started for item in distinct_progress),
            completed=sum(item.completed for item in distinct_progress),
        ),
        "writing_tache": tache,
        "word_limit_min": minimum,
        "word_limit_max": maximum,
        "methodology_url": content_module.EE_ASTUCES_URL,
        "subject_prompt_map": {
            source.source_key: source.prompt
            for source in source_by_slug.values()
        },
    }


def _ee_writing_overview_context(user, task, tache, sujet_ids_by_slug):
    source_categories = _ee_writing_source_categories(tache)
    canonical_slug_by_slug = (
        content_module.ee_writing_canonical_slug_by_slug(tache)
    )
    canonical_ids = {
        sujet_ids_by_slug[canonical_slug_by_slug[source.slug]]
        for category in source_categories
        for source in category.sujets
    }
    progress_by_canonical = writing_sujet_progress_by_id(
        user,
        canonical_ids,
        task_id=task.pk,
    )
    occurrence_progress = [
        progress_by_canonical[
            sujet_ids_by_slug[canonical_slug_by_slug[source.slug]]
        ]
        for category in source_categories
        for source in category.sujets
    ]
    distinct_progress = list(progress_by_canonical.values())
    return {
        "category_count": len(source_categories),
        "sujet_count": len(occurrence_progress),
        "distinct_count": len(canonical_ids),
        "response_count": len(canonical_ids),
        "personalized_count": sum(
            item.is_personalized for item in distinct_progress
        ),
        "completed_count": sum(
            item.explicitly_completed for item in distinct_progress
        ),
        "subject_progress": progress_summary(
            total=len(occurrence_progress),
            started=sum(item.started for item in occurrence_progress),
            completed=sum(item.completed for item in occurrence_progress),
        ),
        "writing_tache": tache,
    }


def task_detail(request, part_slug, task_slug):
    task = _route_task(part_slug, task_slug, request=request)
    now = timezone.now()
    if not task.available:
        return render(
            request,
            "study/coming_soon.html",
            {"part": task.part, "task": task},
        )
    if (task.part.slug, task.slug) == content_module.EO_TACHE_ONE_TASK:
        question_bank = _load_task_memoires(task)[0]
        return render(
            request,
            "study/question_bank.html",
            _question_bank_page_context(
                request.user,
                task,
                question_bank,
            ),
        )
    if (task.part.slug, task.slug) == content_module.QUESTION_BANK_TASK:
        theme_vocabulary = _tache_two_theme_vocabulary_overview_context(
            request.user,
            task,
        )
        subject_state = _tache_two_theme_progress(request.user)
        return render(
            request,
            "study/tache_two_overview.html",
            {
                "part": task.part,
                "task": task,
                "subject_summary": subject_state,
                "subject_count": subject_state["total"],
                "subject_theme_count": subject_state["theme_count"],
                "theme_vocabulary": theme_vocabulary,
                "ai_practice_prompt": content_module.load_ai_examiner_prompt(),
            },
        )
    writing_tache = _ee_writing_tache(task)
    writing_sujet_ids = (
        _ee_writing_sujet_ids_by_slug(task, writing_tache)
        if writing_tache is not None
        else None
    )
    if writing_tache is not None and writing_sujet_ids is not None:
        subject_context = _ee_writing_overview_context(
            request.user,
            task,
            writing_tache,
            writing_sujet_ids,
        )
        vocabulary_context = _ee_writing_theme_vocabulary_overview_context(
            request.user,
            task,
            writing_tache,
        )
        return render(
            request,
            "study/ee_writing_overview.html",
            {
                "part": task.part,
                "task": task,
                **subject_context,
                "subject_summary": {
                    "progress": subject_context["subject_progress"],
                    "completed": subject_context[
                        "subject_progress"
                    ].completed,
                    "total": subject_context["subject_progress"].total,
                    "started_new": max(
                        subject_context["subject_progress"].started
                        - subject_context["subject_progress"].completed,
                        0,
                    ),
                },
                "theme_vocabulary": vocabulary_context,
                "ai_practice_prompt": (
                    content_module.load_ee_ai_examiner_prompt(writing_tache)
                ),
            },
        )
    if (
        (task.part.slug, task.slug) == content_module.EE_TACHE_THREE_TASK
        and _has_ee_tache_three_content(task)
    ):
        subject_context = _ee_tache_three_overview_context(request.user, task)
        memory_context = _question_bank_memory_context(
            request.user,
            _load_task_memoires(task),
        )
        vocabulary_progress = _vocabulary_deck_progress(
            subject_context["_progress_by_response"].values()
        )
        return render(
            request,
            "study/ee_tache_three_overview.html",
            {
                "part": task.part,
                "task": task,
                **subject_context,
                **memory_context,
                "vocabulary_theme_count": subject_context["theme_count"],
                "vocabulary_entry_count": (
                    subject_context["distinct_count"]
                    * content_module.EE_TACHE_THREE_VOCABULARY_PER_RESPONSE
                ),
                "vocabulary_deck_count": subject_context["distinct_count"],
                "vocabulary_summary": {
                    "progress": vocabulary_progress,
                    "completed": vocabulary_progress.completed,
                    "total": vocabulary_progress.total,
                    "started_new": max(
                        vocabulary_progress.started
                        - vocabulary_progress.completed,
                        0,
                    ),
                },
                "ai_practice_prompt": (
                    content_module.load_ee_ai_examiner_prompt(3)
                ),
                "methodology_url": content_module.EE_ASTUCES_URL,
            },
        )

    if (
        (task.part.slug, task.slug) == content_module.EE_TACHE_ONE_TASK
        and _has_ee_tache_one_content(task)
    ):
        return render(
            request,
            "study/ee_tache_one_subjects.html",
            {
                "part": task.part,
                "task": task,
                **_ee_tache_one_subject_context(request.user, task),
            },
        )

    active_themes = list(Theme.objects.filter(task=task, is_active=True))
    theme_stats, response_progress, due_response_ids = _subject_stats_for_themes(
        active_themes,
        request.user,
        now,
    )
    prompt_counts = _prompt_counts_by_theme(task=task)
    themes = [
        {
            "theme": theme,
            "stats": theme_stats[theme.pk],
            "prompt_count": prompt_counts.get(theme.pk, 0),
        }
        for theme in active_themes
    ]
    response_stats = summarize_subject_progress(response_progress.values())
    response_stats["due"] = len(due_response_ids)
    # The catalogue counts this page shows all read the same phrase and prompt
    # tables, so they are one grouped scan each instead of four.
    task_phrase_counts = _task_phrases(task).aggregate(
        functional=Count(
            "pk",
            distinct=True,
            filter=Q(category__name__in=FUNCTIONAL_PHRASE_CATEGORY_NAMES),
        ),
        functional_categories=Count(
            "category_id",
            distinct=True,
            filter=Q(category__name__in=FUNCTIONAL_PHRASE_CATEGORY_NAMES),
        ),
    )
    phrase_count = task_phrase_counts["functional"]
    is_eo_tache_three = (
        task.part.slug,
        task.slug,
    ) == content_module.EO_TACHE_THREE_TASK
    subject_vocabulary_count = 0
    if not is_eo_tache_three:
        subject_vocabulary_count = _distinct_count(
            Phrase.objects.filter(
                is_active=True,
                tier=PhraseTier.SUBJECT,
                source_prompts__is_active=True,
                source_prompts__theme__is_active=True,
                source_prompts__theme__task=task,
            )
        )
    context = {
        "part": task.part,
        "task": task,
        "themes": themes,
        "stats": response_stats,
        "response_stats": response_stats,
        "prompt_count": sum(prompt_counts.values()),
        "phrase_count": phrase_count,
        "phrase_category_count": task_phrase_counts["functional_categories"],
        "vocabulary_entry_count": phrase_count + subject_vocabulary_count,
    }
    if is_eo_tache_three:
        vocabulary_context = (
            _eo_tache_three_theme_vocabulary_context(
                request.user,
                task,
            )
        )
        context["vocabulary_theme_count"] = vocabulary_context["theme_count"]
        context["vocabulary_entry_count"] = vocabulary_context["phrase_count"]
        context["vocabulary_batch_count"] = vocabulary_context["batch_count"]
        context["vocabulary_overview_summary"] = vocabulary_context["summary"]
        context["subject_summary"] = response_stats
        return render(
            request,
            "study/eo_tache_three_overview.html",
            context,
        )
    return render(request, "study/task_detail.html", context)


def _scope_filters(request, forced_task=None, forced_part_slug=None):
    """Build canonical path-based part/task filters for progression pages."""
    if "part" in request.GET or "task" in request.GET:
        raise Http404

    selected_task = forced_task
    selected_part = None
    part_slug = ""
    task_slug = ""
    if selected_task:
        part_slug = forced_task.part.slug
        task_slug = forced_task.slug
        selected_part = forced_task.part
    elif forced_part_slug:
        selected_part = get_object_or_404(
            ExamPart,
            slug=forced_part_slug,
            is_active=True,
        )
        part_slug = selected_part.slug

    active = Card.objects.active().filter(
        user=request.user,
        card_type=CardType.SPINE,
    )
    # One grouped count for every part and task on the page: the filter strip
    # used to run a count per part plus one per task of the open part, each a
    # full scan of the learner's response cards.
    active_counts_by_task = {}
    active_counts_by_part = {}
    for row in (
        active.select_related(None)
        .order_by()
        .values("response__theme__task_id", "response__theme__task__part_id")
        .annotate(total=Count("id", distinct=True))
    ):
        task_id = row["response__theme__task_id"]
        part_id = row["response__theme__task__part_id"]
        if task_id is not None:
            active_counts_by_task[task_id] = (
                active_counts_by_task.get(task_id, 0) + row["total"]
            )
        if part_id is not None:
            active_counts_by_part[part_id] = (
                active_counts_by_part.get(part_id, 0) + row["total"]
            )
    filter_parts = []
    active_part_tasks = []
    for part in ExamPart.objects.filter(
        is_active=True,
        slug__in={"eo", "ee"},
    ).prefetch_related(
        Prefetch("tasks", queryset=Task.objects.filter(is_active=True))
    ):
        filter_parts.append(
            {
                "slug": part.slug,
                "short_name": part.short_name,
                "count": active_counts_by_part.get(part.pk, 0),
                "active": part_slug == part.slug,
                "url": reverse("study:part_stats", args=[part.slug]),
            }
        )
        if part_slug == part.slug:
            for task in part.tasks.all():
                active_part_tasks.append(
                    {
                        "slug": task.slug,
                        "name": task.name,
                        "count": active_counts_by_task.get(task.pk, 0),
                        "active": task_slug == task.slug,
                        "url": reverse(
                            "study:task_stats",
                            args=[part.slug, task.slug],
                        ),
                    }
                )

    if task_slug:
        scope = {"part": part_slug, "task": task_slug}
    elif part_slug:
        scope = {"part": part_slug}
    else:
        scope = {}

    return {
        "filter_base": reverse("study:stats"),
        "filter_parts": filter_parts,
        "active_part": part_slug,
        "active_task": task_slug,
        "active_part_tasks": active_part_tasks,
        "active_part_url": (
            reverse("study:part_stats", args=[part_slug])
            if part_slug
            else ""
        ),
        "scope_review_url": (
            review_url({**scope, "kind": "spine"}) if scope else ""
        ),
        "scope_label": scope_label(scope),
        "scope": scope,
        "task": selected_task,
        "part": selected_part,
        "task_locked": forced_task is not None,
    }


def browse(request, part_slug=None, task_slug=None):
    forced_task = _route_task(part_slug, task_slug, request=request)
    if forced_task and not forced_task.available:
        return render(
            request,
            "study/coming_soon.html",
            {"part": forced_task.part, "task": forced_task},
        )
    if forced_task and (
        forced_task.part.slug,
        forced_task.slug,
    ) == content_module.QUESTION_BANK_TASK:
        subject_state = _tache_two_theme_progress(request.user)
        themes = subject_state["themes"]
        subject_prompt_map = {
            subject["content_key"]: subject["prompt"]
            for theme in themes
            for subject in theme["subjects"]
        }
        return render(
            request,
            "study/tache_two_subjects.html",
            {
                "part": forced_task.part,
                "task": forced_task,
                "subject_themes": themes,
                "subject_prompt_map": subject_prompt_map,
                "subject_summary": subject_state,
                "theme_count": subject_state["theme_count"],
                "subject_count": subject_state["total"],
                "question_count": sum(
                    theme["question_count"] for theme in themes
                ),
            },
        )
    writing_tache = _ee_writing_tache(forced_task) if forced_task else None
    writing_context = (
        _ee_writing_subject_context(
            request.user,
            forced_task,
            writing_tache,
            allow_unsynchronized=True,
        )
        if forced_task and writing_tache is not None
        else None
    )
    if writing_context is not None:
        return render(
            request,
            "study/ee_writing_subjects.html",
            {
                "part": forced_task.part,
                "task": forced_task,
                **writing_context,
            },
        )
    if (
        forced_task
        and (
            forced_task.part.slug,
            forced_task.slug,
        )
        == content_module.EE_TACHE_THREE_TASK
        and _has_ee_tache_three_content(forced_task)
    ):
        return render(
            request,
            "study/ee_tache_three_subjects.html",
            {
                "part": forced_task.part,
                "task": forced_task,
                **_ee_tache_three_subject_context(
                    request.user,
                    forced_task,
                ),
            },
        )
    if (
        forced_task
        and (
            forced_task.part.slug,
            forced_task.slug,
        )
        == content_module.EE_TACHE_ONE_TASK
        and _has_ee_tache_one_content(forced_task)
    ):
        return render(
            request,
            "study/ee_tache_one_subjects.html",
            {
                "part": forced_task.part,
                "task": forced_task,
                **_ee_tache_one_subject_context(
                    request.user,
                    forced_task,
                ),
            },
        )
    filters = _scope_filters(request, forced_task)
    scope = filters["scope"]

    theme_qs = Theme.objects.select_related("task__part").filter(is_active=True)
    if scope.get("task"):
        theme_qs = theme_qs.filter(
            task__slug=scope["task"],
            task__part__slug=scope["part"],
        )
    elif scope.get("part"):
        theme_qs = theme_qs.filter(task__part__slug=scope["part"])

    theme_rows = list(theme_qs)
    theme_stats, response_progress, _due_response_ids = _subject_stats_for_themes(
        theme_rows,
        request.user,
    )
    prompt_counts = _prompt_counts_by_theme(theme_rows)
    themes = [
        {
            "theme": theme,
            "stats": theme_stats[theme.pk],
            "prompt_count": prompt_counts.get(theme.pk, 0),
        }
        for theme in theme_rows
    ]
    family_qs = Family.objects.filter(is_active=True)
    if scope.get("task"):
        family_qs = family_qs.filter(
            prompts__is_active=True,
            prompts__theme__task__slug=scope["task"],
            prompts__theme__task__part__slug=scope["part"],
        )
    elif scope.get("part"):
        family_qs = family_qs.filter(
            prompts__is_active=True,
            prompts__theme__task__part__slug=scope["part"]
        )
    families = list(
        family_qs.annotate(
            n=Count(
                "prompts",
                filter=Q(prompts__is_active=True),
                distinct=True,
            )
        ).order_by("order")
    )
    response_ids_by_family = {family.pk: set() for family in families}
    family_prompts = Prompt.objects.filter(
        family_id__in=response_ids_by_family,
        is_active=True,
        response__is_active=True,
        theme__is_active=True,
    )
    if scope.get("task"):
        family_prompts = family_prompts.filter(
            theme__task__slug=scope["task"],
            theme__task__part__slug=scope["part"],
        )
    elif scope.get("part"):
        family_prompts = family_prompts.filter(
            theme__task__part__slug=scope["part"],
        )
    for family_id, response_id in family_prompts.values_list(
        "family_id",
        "response_id",
    ):
        response_ids_by_family[family_id].add(response_id)
    for family in families:
        family.progress = summarize_subject_progress(
            response_progress[response_id]
            for response_id in response_ids_by_family[family.pk]
        )["progress"]
    prompt_qs = Prompt.objects.filter(is_active=True)
    response_qs = Response.objects.filter(is_active=True)
    phrase_qs = Phrase.objects.filter(is_active=True)
    if scope.get("task"):
        prompt_qs = prompt_qs.filter(
            theme__task__slug=scope["task"],
            theme__task__part__slug=scope["part"],
        )
        response_qs = response_qs.filter(
            theme__task__slug=scope["task"],
            theme__task__part__slug=scope["part"],
        )
        phrase_qs = phrase_qs.filter(
            source_prompts__theme__task__slug=scope["task"],
            source_prompts__theme__task__part__slug=scope["part"],
        ).distinct()
    elif scope.get("part"):
        prompt_qs = prompt_qs.filter(theme__task__part__slug=scope["part"])
        response_qs = response_qs.filter(
            theme__task__part__slug=scope["part"]
        )
        phrase_qs = phrase_qs.filter(
            source_prompts__theme__task__part__slug=scope["part"]
        ).distinct()
    context = {
        "themes": themes,
        "families": families,
        "theme_count": len(themes),
        "prompt_count": prompt_qs.count(),
        "response_count": response_qs.count(),
        "phrase_count": _distinct_count(phrase_qs),
        **filters,
    }
    return render(request, "study/browse.html", context)


def _canonical_numbers_by_response(response_ids) -> dict:
    """Map response id -> canonical prompt number in a single query.

    Avoids an N+1 from calling ``Response.canonical_prompt`` per row.
    """
    ids = list(response_ids)
    if not ids:
        return {}
    return dict(
        Prompt.objects.filter(
            response_id__in=ids,
            is_active=True,
            is_canonical=True,
        ).values_list("response_id", "number")
    )


def theme_detail(request, part_slug, task_slug, slug):
    task = _route_task(part_slug, task_slug, request=request)
    theme = (
        Theme.objects.select_related("task__part")
        .filter(
            slug=slug,
            task=task,
            is_active=True,
        )
        .first()
    )
    if theme is None and (
        (task.part.slug, task.slug) == content_module.EE_TACHE_THREE_TASK
        and slug.removeprefix("ee-tache-3-") in content_module.EE_MONTH_ORDER
    ):
        return redirect(
            "study:task_browse",
            task.part.slug,
            task.slug,
        )
    if theme is None:
        raise Http404
    prompts = list(
        Prompt.objects.filter(theme=theme, is_active=True)
        .select_related("response", "response__theme", "family")
        .order_by("number")
    )
    canonical_numbers = _canonical_numbers_by_response(
        prompt.response_id for prompt in prompts
    )
    subject_progress = subject_progress_by_response(
        request.user,
        {prompt.response_id for prompt in prompts},
    )
    rows = [
        {
            "prompt": prompt,
            "progress": subject_progress[prompt.response_id],
            "is_alias": not prompt.is_canonical,
            "canonical_number": canonical_numbers.get(prompt.response_id),
        }
        for prompt in prompts
    ]
    stats = summarize_subject_progress(
        subject_progress[prompt.response_id] for prompt in prompts
    )
    review_scope = {
        "kind": "spine",
        "part": task.part.slug,
        "task": task.slug,
        "theme": theme.slug,
    }
    if (task.part.slug, task.slug) == content_module.EE_TACHE_THREE_TASK:
        source_by_key = _ee_tache_three_sources_by_key()
        occurrence_count_by_response = {}
        for row in rows:
            response_id = row["prompt"].response_id
            occurrence_count_by_response[response_id] = (
                occurrence_count_by_response.get(response_id, 0) + 1
            )
        for row in rows:
            source_row = source_by_key.get(row["prompt"].content_key)
            if source_row is None:
                raise RuntimeError("EE Tâche 3 content is not synchronized")
            source_month, source = source_row
            row.update(
                {
                    "position": source.position,
                    "combination_label": source.combinaison,
                    "combination_number": (
                        source.combinaison.removeprefix(
                            "Combinaison "
                        ).strip()
                    ),
                    "month_slug": source_month.slug,
                    "month_name": source_month.name,
                    "month_number": source_month.number,
                    "year": 2025,
                    "document_count": sum(
                        bool(document.strip())
                        for document in (
                            source.document1,
                            source.document2,
                        )
                    ),
                    "vocabulary_count": (
                        content_module.EE_TACHE_THREE_VOCABULARY_PER_RESPONSE
                    ),
                    "equivalent_count": (
                        occurrence_count_by_response[row["prompt"].response_id]
                        - 1
                    ),
                    "has_source_issue": source.has_source_issue,
                }
            )
        return render(
            request,
            "study/ee_tache_three_month.html",
            {
                "theme": theme,
                "task": task,
                "part": task.part,
                "subjects": rows,
                "subject_theme": {
                    "slug": theme.slug,
                    "name": theme.display_name,
                    "icon": theme.icon,
                    "subject_count": len(rows),
                    "distinct_count": len(subject_progress),
                    "vocabulary_count": (
                        len(subject_progress)
                        * content_module.EE_TACHE_THREE_VOCABULARY_PER_RESPONSE
                    ),
                    **stats,
                },
                "review_url": review_url(review_scope),
            },
        )
    return render(
        request,
        "study/theme_detail.html",
        {
            "theme": theme,
            "task": task,
            "part": task.part,
            "rows": rows,
            "stats": stats,
            "review_batches": _review_batches(review_scope, request.user),
            "review_url": review_url(review_scope),
        },
    )


def _memory_task(part_slug, task_slug):
    task = get_object_or_404(
        Task.objects.select_related("part"),
        slug=task_slug,
        part__slug=part_slug,
        is_active=True,
        part__is_active=True,
        available=True,
    )
    if (task.part.slug, task.slug) != content_module.QUESTION_BANK_TASK:
        raise Http404
    return task


def _memoire_task(request, part_slug, task_slug):
    """Gate routes backed by reusable question-bank content."""
    task = _route_task(part_slug, task_slug, request=request)
    if (
        not task.available
        or (task.part.slug, task.slug) not in content_module.MEMOIRE_TASKS
    ):
        raise Http404
    return task


def _load_task_memoires(task):
    return _load_task_memoires_by_key(task.part.slug, task.slug)


@lru_cache(maxsize=8)
def _load_task_memoires_by_key(part_slug, task_slug):
    directory, namespace = content_module.MEMOIRE_TASKS[
        (part_slug, task_slug)
    ]
    return content_module.load_question_banks(
        directory,
        key_namespace=namespace,
    )


def _memory_by_number(memories, memory_number):
    memory = next(
        (
            memory
            for memory in memories
            if memory.number == memory_number
        ),
        None,
    )
    if memory is None:
        raise Http404
    return memory


def task_memories(request, part_slug, task_slug):
    task = _memoire_task(request, part_slug, task_slug)
    if (task.part.slug, task.slug) == content_module.EO_TACHE_ONE_TASK:
        return redirect(
            "study:task_detail",
            part_slug=task.part.slug,
            task_slug=task.slug,
        )
    if (task.part.slug, task.slug) == content_module.QUESTION_BANK_TASK:
        return redirect("study:tache_two_theme_vocabulary")
    memories = _load_task_memoires(task)
    return render(
        request,
        "study/tache_two_memories.html",
        {
            "part": task.part,
            "task": task,
            "memory_task": (
                (task.part.slug, task.slug)
                == content_module.QUESTION_BANK_TASK
            ),
            **_question_bank_memory_context(request.user, memories),
        },
    )


TACHE_TWO_THEME_VOCABULARY_SECTIONS = (
    {
        "category": "Thème · Mots clés",
        "title": "Mots clés",
        "description": (
            "Le vocabulaire concret pour comprendre la situation et nommer "
            "précisément ce dont vous avez besoin."
        ),
        "icon": "book-open",
    },
    {
        "category": "Thème · Expressions utiles",
        "title": "Expressions utiles",
        "description": (
            "Des tournures naturelles pour demander des détails, "
            "comparer les options et préciser vos critères."
        ),
        "icon": "messages",
    },
    {
        "category": "Thème · Fragments de phrase",
        "title": "Fragments de phrase",
        "description": (
            "Des débuts et morceaux de questions réutilisables pour relancer, "
            "clarifier et garder l’échange fluide."
        ),
        "icon": "sparkles",
    },
)

EO_TACHE_THREE_THEME_VOCABULARY_SECTIONS = (
    {
        "category": "EO Tâche 3 · Notions clés",
        "title": "Notions clés",
        "short_title": "notions",
        "description": (
            "Le lexique précis pour nommer les enjeux, les acteurs et les "
            "réalités propres à ce thème."
        ),
        "icon": "book-open",
    },
    {
        "category": "EO Tâche 3 · Verbes et collocations",
        "title": "Verbes et collocations",
        "short_title": "verbes",
        "description": (
            "Des verbes avec leurs constructions et des associations "
            "naturelles pour développer vos arguments."
        ),
        "icon": "pen-line",
    },
    {
        "category": "EO Tâche 3 · Expressions et locutions",
        "title": "Expressions et locutions",
        "short_title": "expressions",
        "description": (
            "Des formulations idiomatiques et nuancées pour gagner en "
            "précision sans sonner récité."
        ),
        "icon": "messages",
    },
    {
        "category": "EO Tâche 3 · Constructions argumentatives",
        "title": "Constructions argumentatives",
        "short_title": "constructions",
        "description": (
            "Des cadres thématiques pour concéder, opposer, expliquer et "
            "tirer une conclusion à l’oral."
        ),
        "icon": "sparkles",
    },
)

EE_WRITING_THEME_VOCABULARY_SECTIONS = {
    1: (
        {
            "category": "EE Tâche 1 · Formules adaptées",
            "title": "Formules adaptées",
            "short_title": "formules",
            "description": (
                "Des ouvertures, demandes et conclusions adaptées au "
                "destinataire et à la situation."
            ),
            "icon": "mail",
        },
        {
            "category": "EE Tâche 1 · Informations précises",
            "title": "Informations précises",
            "short_title": "détails",
            "description": (
                "Des formulations concises pour communiquer les lieux, "
                "horaires, conditions et informations demandées."
            ),
            "icon": "file-text",
        },
        {
            "category": "EE Tâche 1 · Verbes et collocations",
            "title": "Verbes et collocations",
            "short_title": "verbes",
            "description": (
                "Des associations naturelles pour inviter, décrire, demander "
                "et expliquer clairement."
            ),
            "icon": "pen-line",
        },
        {
            "category": "EE Tâche 1 · Phrases modèles",
            "title": "Phrases modèles",
            "short_title": "phrases",
            "description": (
                "Des constructions complètes et adaptables pour rédiger un "
                "message efficace sans réciter."
            ),
            "icon": "sparkles",
        },
    ),
    2: (
        {
            "category": "EE Tâche 2 · Repères temporels",
            "title": "Repères temporels",
            "short_title": "repères",
            "description": (
                "Des transitions pour situer les événements et faire avancer "
                "le récit avec clarté."
            ),
            "icon": "arrow-right",
        },
        {
            "category": "EE Tâche 2 · Verbes du récit",
            "title": "Verbes du récit",
            "short_title": "verbes",
            "description": (
                "Des verbes et collocations pour raconter des actions avec "
                "des temps du passé bien maîtrisés."
            ),
            "icon": "pen-line",
        },
        {
            "category": "EE Tâche 2 · Détails et impressions",
            "title": "Détails et impressions",
            "short_title": "impressions",
            "description": (
                "Des formulations concrètes pour décrire une ambiance, une "
                "réaction et ce qui vous a marqué."
            ),
            "icon": "target",
        },
        {
            "category": "EE Tâche 2 · Commentaires et recommandations",
            "title": "Commentaires et recommandations",
            "short_title": "commentaires",
            "description": (
                "Des constructions pour expliquer une leçon, donner un avis "
                "ou formuler un conseil pertinent."
            ),
            "icon": "messages",
        },
    ),
}


def _theme_vocabulary_phrases(task, theme=None):
    if _ee_writing_tache(task) is not None:
        phrases = Phrase.objects.filter(
            tier=PhraseTier.THEME,
            is_active=True,
            vocabulary_theme__is_active=True,
            vocabulary_theme__task=task,
        )
        if theme is not None:
            phrases = phrases.filter(vocabulary_theme=theme)
        return phrases

    phrases = Phrase.objects.filter(
        tier=PhraseTier.THEME,
        is_active=True,
    ).filter(
        Q(
            source_prompts__is_active=True,
            source_prompts__theme__task=task,
        )
        | Q(
            vocabulary_theme__is_active=True,
            vocabulary_theme__task=task,
        )
    )
    if theme is not None:
        phrases = phrases.filter(
            Q(source_prompts__theme=theme) | Q(vocabulary_theme=theme)
        )
    return phrases.distinct()


def tache_two_theme_vocabulary(request):
    task = _route_task("eo", "tache-2", request=request)
    taxonomy, _subject_mapping = (
        content_module.load_tache_two_subject_themes()
    )
    theme_slugs = [f"tache-2-{item.slug}" for item in taxonomy]
    theme_models = Theme.objects.filter(
        task=task,
        is_active=True,
        slug__in=theme_slugs,
    ).in_bulk(field_name="slug")
    phrase_counts = {
        (row["source_prompts__theme__slug"], row["category__name"]): (
            row["total"]
        )
        for row in _theme_vocabulary_phrases(task)
        .order_by()
        .values("source_prompts__theme__slug", "category__name")
        .annotate(total=Count("pk", distinct=True))
    }

    themes = []
    ordered_themes = [
        (theme_data, theme_models[f"tache-2-{theme_data.slug}"])
        for theme_data in taxonomy
        if f"tache-2-{theme_data.slug}" in theme_models
    ]
    task_batches, batches_by_theme = _theme_vocabulary_directory_batches(
        task,
        request.user,
        [theme for _theme_data, theme in ordered_themes],
    )
    for theme_data, theme in ordered_themes:
        batches = batches_by_theme[theme.slug]
        next_batch = next(
            (batch for batch in batches if batch["is_next"]),
            None,
        )
        counts = {
            section["category"]: phrase_counts.get(
                (theme.slug, section["category"]),
                0,
            )
            for section in TACHE_TWO_THEME_VOCABULARY_SECTIONS
        }
        themes.append(
            {
                "data": theme_data,
                "theme": theme,
                "phrase_count": sum(counts.values()),
                "word_count": counts["Thème · Mots clés"],
                "expression_count": counts[
                    "Thème · Expressions utiles"
                ],
                "fragment_count": counts[
                    "Thème · Fragments de phrase"
                ],
                "batch_count": len(batches),
                "progress_unit": "lots terminés",
                "summary": _theme_vocabulary_batch_summary(batches),
                "url": reverse(
                    "study:tache_two_theme_vocabulary_detail",
                    args=[theme_data.slug],
                ),
                "review_url": (
                    next_batch["review_url"] if next_batch else ""
                ),
            }
        )

    scope = _theme_vocabulary_scope(task)
    batches = task_batches
    next_batch = next(
        (batch for batch in batches if batch["is_next"]),
        None,
    )
    return render(
        request,
        "study/tache_two_theme_vocabulary.html",
        {
            "part": task.part,
            "task": task,
            "section": "theme-vocabulary",
            "themes": themes,
            "theme_count": len(themes),
            "phrase_count": sum(item["phrase_count"] for item in themes),
            "batch_count": len(batches),
            "summary": _theme_vocabulary_batch_summary(batches),
            "theme_status_counts": _theme_vocabulary_status_counts(themes),
            "review_url": (
                next_batch["review_url"] if next_batch else ""
            ),
            "mixed_review_url": review_url(scope),
        },
    )


def _theme_vocabulary_detail_context(
    request,
    *,
    task,
    theme,
    theme_data,
    sections,
    section,
    directory_url,
    back_label,
    vocabulary_label,
    hero_description,
    pathways_title,
    pathways_description,
):
    phrases = list(
        _theme_vocabulary_phrases(task, theme)
        .select_related("category")
        .order_by("order", "pk")
    )
    learned_phrase_ids = set(
        ThemeVocabularyProgress.objects.filter(
            user=request.user,
            phrase_id__in=[phrase.pk for phrase in phrases],
        ).values_list("phrase_id", flat=True)
    )
    for phrase in phrases:
        phrase.is_explicitly_learned = phrase.pk in learned_phrase_ids
        if (task.part.slug, task.slug) == content_module.QUESTION_BANK_TASK:
            phrase.progress_url = reverse(
                "study:tache_two_theme_vocabulary_progress",
                args=[theme_data.slug, phrase.pk],
            )
        else:
            phrase.progress_url = reverse(
                "study:theme_vocabulary_progress",
                args=[
                    task.part.slug,
                    task.slug,
                    theme.slug,
                    phrase.pk,
                ],
            )
    phrases_by_category = {
        section_data["category"]: [] for section_data in sections
    }
    for phrase in phrases:
        phrases_by_category.setdefault(phrase.category.name, []).append(phrase)
    phrase_sections = [
        {
            **section_data,
            "phrases": phrases_by_category[section_data["category"]],
        }
        for section_data in sections
    ]

    scope = _theme_vocabulary_scope(task, theme)
    batches = _review_batches(scope, request.user)
    for batch, section_data in zip(batches, sections):
        batch["title"] = section_data["title"]
    next_batch = next(
        (batch for batch in batches if batch["is_next"]),
        None,
    )
    return {
        "part": task.part,
        "task": task,
        "section": section,
        "theme": theme,
        "theme_data": theme_data,
        "theme_title": (
            theme_data.name
            if hasattr(theme_data, "name")
            and (task.part.slug, task.slug)
            == content_module.QUESTION_BANK_TASK
            else theme.display_name
        ),
        "theme_icon": theme_data.icon,
        "directory_url": directory_url,
        "back_label": back_label,
        "vocabulary_label": vocabulary_label,
        "hero_description": hero_description,
        "pathways_title": pathways_title,
        "pathways_description": pathways_description,
        "phrase_count": len(phrases),
        "learned_summary": progress_summary(
            total=len(phrases),
            started=len(learned_phrase_ids),
            completed=len(learned_phrase_ids),
        ),
        "unlearned_count": len(phrases) - len(learned_phrase_ids),
        "phrase_sections": phrase_sections,
        "review_batches": batches,
        "summary": _theme_vocabulary_batch_summary(batches),
        "review_url": next_batch["review_url"] if next_batch else "",
        "mixed_review_url": review_url(scope),
    }


def tache_two_theme_vocabulary_detail(request, theme_slug):
    task = _route_task("eo", "tache-2", request=request)
    taxonomy, _subject_mapping = (
        content_module.load_tache_two_subject_themes()
    )
    theme_data = next(
        (item for item in taxonomy if item.slug == theme_slug),
        None,
    )
    if theme_data is None:
        raise Http404
    theme = get_object_or_404(
        Theme,
        task=task,
        slug=f"tache-2-{theme_slug}",
        is_active=True,
    )
    return render(
        request,
        "study/theme_vocabulary_detail.html",
        _theme_vocabulary_detail_context(
            request,
            task=task,
            theme=theme,
            theme_data=theme_data,
            sections=TACHE_TWO_THEME_VOCABULARY_SECTIONS,
            section="theme-vocabulary",
            directory_url=reverse("study:tache_two_theme_vocabulary"),
            back_label="Tous les thèmes",
            vocabulary_label="Vocabulaire par thème",
            hero_description=(
                "Apprenez les éléments utiles, puis combinez-les pour mener "
                "une interaction souple plutôt que réciter une liste de "
                "questions."
            ),
            pathways_title="Trois parcours complémentaires",
            pathways_description=(
                "Commencez par les mots, passez aux expressions, puis "
                "entraînez-vous à produire des fragments de questions."
            ),
        ),
    )


def _update_theme_vocabulary_progress(
    request,
    *,
    task,
    theme,
    phrase,
    return_url,
):
    completed = request.POST.get("completed")
    if completed not in {"0", "1"}:
        message = "État d’apprentissage invalide."
        if request.headers.get("X-Requested-With") == "fetch":
            return JsonResponse({"error": message}, status=400)
        return HttpResponseBadRequest(message)

    if completed == "1":
        ThemeVocabularyProgress.objects.get_or_create(
            user=request.user,
            phrase=phrase,
        )
    else:
        ThemeVocabularyProgress.objects.filter(
            user=request.user,
            phrase=phrase,
        ).delete()

    phrase_ids = _theme_vocabulary_phrases(
        task,
        theme,
    ).values_list("pk", flat=True)
    total = phrase_ids.count()
    learned = ThemeVocabularyProgress.objects.filter(
        user=request.user,
        phrase_id__in=phrase_ids,
    ).count()
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse(
            {
                "completed": completed == "1",
                "phrase_id": phrase.phrase_id,
                "learned": learned,
                "total": total,
            }
        )
    return redirect(return_url + f"#phrase-{phrase.phrase_id}")


@require_POST
def tache_two_theme_vocabulary_progress(request, theme_slug, phrase_pk):
    task = _route_task("eo", "tache-2", request=request)
    theme = get_object_or_404(
        Theme,
        task=task,
        slug=f"tache-2-{theme_slug}",
        is_active=True,
    )
    phrase = get_object_or_404(
        _theme_vocabulary_phrases(task, theme),
        pk=phrase_pk,
    )
    return _update_theme_vocabulary_progress(
        request,
        task=task,
        theme=theme,
        phrase=phrase,
        return_url=reverse(
            "study:tache_two_theme_vocabulary_detail",
            args=[theme_slug],
        ),
    )


@require_POST
def theme_vocabulary_progress(
    request,
    part_slug,
    task_slug,
    vocabulary_theme_slug,
    phrase_pk,
):
    task = _route_task(part_slug, task_slug, request=request)
    if (task.part.slug, task.slug) == content_module.QUESTION_BANK_TASK:
        raise Http404
    theme = get_object_or_404(
        Theme,
        task=task,
        slug=vocabulary_theme_slug,
        is_active=True,
    )
    phrase = get_object_or_404(
        _theme_vocabulary_phrases(task, theme),
        pk=phrase_pk,
    )
    return _update_theme_vocabulary_progress(
        request,
        task=task,
        theme=theme,
        phrase=phrase,
        return_url=reverse(
            "study:task_vocabulary_theme",
            args=[task.part.slug, task.slug, theme.slug],
        ),
    )


def _eo_tache_three_theme_data():
    return tuple(
        theme
        for theme in content_module.load_themes()
        if theme.task == "/".join(content_module.EO_TACHE_THREE_TASK)
    )


def _eo_tache_three_theme_vocabulary_context(user, task):
    taxonomy = _eo_tache_three_theme_data()
    theme_models = Theme.objects.filter(
        task=task,
        is_active=True,
        slug__in=[item.slug for item in taxonomy],
    ).in_bulk(field_name="slug")
    phrase_counts = {
        (row["source_prompts__theme__slug"], row["category__name"]): (
            row["total"]
        )
        for row in _theme_vocabulary_phrases(task)
        .order_by()
        .values("source_prompts__theme__slug", "category__name")
        .annotate(total=Count("pk", distinct=True))
    }

    themes = []
    ordered_themes = [
        (theme_data, theme_models[theme_data.slug])
        for theme_data in taxonomy
        if theme_data.slug in theme_models
    ]
    task_batches, batches_by_theme = _theme_vocabulary_directory_batches(
        task,
        user,
        [theme for _theme_data, theme in ordered_themes],
    )
    for theme_data, theme in ordered_themes:
        section_counts = [
            {
                **section_data,
                "count": phrase_counts.get(
                    (theme.slug, section_data["category"]),
                    0,
                ),
            }
            for section_data in EO_TACHE_THREE_THEME_VOCABULARY_SECTIONS
        ]
        batches = batches_by_theme[theme.slug]
        next_batch = next(
            (batch for batch in batches if batch["is_next"]),
            None,
        )
        themes.append(
            {
                "data": theme_data,
                "theme": theme,
                "phrase_count": sum(
                    section_data["count"]
                    for section_data in section_counts
                ),
                "section_counts": section_counts,
                "batch_count": len(batches),
                "summary": _theme_vocabulary_batch_summary(batches),
                "url": reverse(
                    "study:task_vocabulary_theme",
                    args=[task.part.slug, task.slug, theme.slug],
                ),
                "review_url": (
                    next_batch["review_url"] if next_batch else ""
                ),
            }
        )

    scope = _theme_vocabulary_scope(task)
    batches = task_batches
    next_batch = next(
        (batch for batch in batches if batch["is_next"]),
        None,
    )
    return {
        "themes": themes,
        "theme_count": len(themes),
        "phrase_count": sum(item["phrase_count"] for item in themes),
        "batch_count": len(batches),
        "summary": _theme_vocabulary_batch_summary(batches),
        "theme_status_counts": _theme_vocabulary_status_counts(themes),
        "review_url": next_batch["review_url"] if next_batch else "",
        "mixed_review_url": review_url(scope),
        "vocabulary_description": (
            "Construisez un vocabulaire argumentatif solide pour les grands "
            "thèmes de la Tâche 3. Chaque collection réunit les notions, "
            "verbes, locutions et constructions utiles."
        ),
        "vocabulary_pathways_description": (
            "Les quatre lots de chaque thème forment un parcours complet : "
            "nommer l’enjeu, choisir le verbe juste, enrichir l’expression, "
            "puis construire l’argument."
        ),
    }


def _eo_tache_three_theme_vocabulary_directory(request, task):
    return render(
        request,
        "study/task_vocabulary.html",
        {
            "part": task.part,
            "task": task,
            "section": "vocabulary",
            **_eo_tache_three_theme_vocabulary_context(
                request.user,
                task,
            ),
        },
    )


def _eo_tache_three_theme_vocabulary_detail(request, task, theme):
    theme_data = next(
        (
            item
            for item in _eo_tache_three_theme_data()
            if item.slug == theme.slug
        ),
        None,
    )
    if theme_data is None:
        raise Http404
    return render(
        request,
        "study/theme_vocabulary_detail.html",
        _theme_vocabulary_detail_context(
            request,
            task=task,
            theme=theme,
            theme_data=theme_data,
            sections=EO_TACHE_THREE_THEME_VOCABULARY_SECTIONS,
            section="vocabulary",
            directory_url=reverse(
                "study:task_phrases",
                args=[task.part.slug, task.slug],
            ),
            back_label="Tous les thèmes",
            vocabulary_label="Vocabulaire",
            hero_description=(
                "Appropriez-vous un lexique transversal à tout le thème : "
                "des notions précises, des associations naturelles et des "
                "constructions prêtes à porter votre argumentation."
            ),
            pathways_title="Quatre parcours complémentaires",
            pathways_description=(
                "Passez des notions aux verbes, enrichissez votre expression "
                "avec des locutions, puis assemblez le tout dans des "
                "constructions argumentatives."
            ),
        ),
    )


def _ee_writing_theme_vocabulary_context(user, task, tache):
    taxonomy, _subject_mapping = _ee_subject_theme_data(tache)
    model_slug_by_source = {
        item.slug: f"ee-tache-{tache}-{item.slug}" for item in taxonomy
    }
    theme_models = Theme.objects.filter(
        task=task,
        is_active=True,
        slug__in=model_slug_by_source.values(),
    ).in_bulk(field_name="slug")
    phrase_counts = {
        (row["vocabulary_theme__slug"], row["category__name"]): row["total"]
        for row in _theme_vocabulary_phrases(task)
        .filter(vocabulary_theme__isnull=False)
        .order_by()
        .values("vocabulary_theme__slug", "category__name")
        .annotate(total=Count("pk", distinct=True))
    }
    sections = EE_WRITING_THEME_VOCABULARY_SECTIONS[tache]
    ordered_themes = [
        (theme_data, theme_models[model_slug_by_source[theme_data.slug]])
        for theme_data in taxonomy
        if model_slug_by_source[theme_data.slug] in theme_models
    ]
    task_batches, batches_by_theme = _theme_vocabulary_directory_batches(
        task,
        user,
        [theme for _theme_data, theme in ordered_themes],
    )
    themes = []
    for theme_data, theme in ordered_themes:
        section_counts = [
            {
                **section_data,
                "count": phrase_counts.get(
                    (theme.slug, section_data["category"]),
                    0,
                ),
            }
            for section_data in sections
        ]
        batches = batches_by_theme[theme.slug]
        next_batch = next(
            (batch for batch in batches if batch["is_next"]),
            None,
        )
        themes.append(
            {
                "data": theme_data,
                "theme": theme,
                "phrase_count": sum(
                    section_data["count"]
                    for section_data in section_counts
                ),
                "section_counts": section_counts,
                "batch_count": len(batches),
                "summary": _theme_vocabulary_batch_summary(batches),
                "url": reverse(
                    "study:task_vocabulary_theme",
                    args=[task.part.slug, task.slug, theme.slug],
                ),
                "review_url": (
                    next_batch["review_url"] if next_batch else ""
                ),
            }
        )

    next_batch = next(
        (batch for batch in task_batches if batch["is_next"]),
        None,
    )
    return {
        "themes": themes,
        "theme_count": len(themes),
        "phrase_count": sum(item["phrase_count"] for item in themes),
        "batch_count": len(task_batches),
        "summary": _theme_vocabulary_batch_summary(task_batches),
        "theme_status_counts": _theme_vocabulary_status_counts(themes),
        "review_url": next_batch["review_url"] if next_batch else "",
        "mixed_review_url": review_url(_theme_vocabulary_scope(task)),
        "vocabulary_description": (
            "Des formules, précisions et constructions réutilisables pour "
            "rédiger des messages clairs et adaptés au destinataire."
            if tache == 1
            else (
                "Des repères, verbes et formulations pour raconter une "
                "expérience avec précision et ajouter un commentaire pertinent."
            )
        ),
        "vocabulary_pathways_description": (
            "Chaque thème rassemble des formules adaptées, des informations "
            "précises, des verbes naturels et des phrases modèles."
            if tache == 1
            else (
                "Chaque thème rassemble des repères temporels, des verbes du "
                "récit, des impressions et des recommandations."
            )
        ),
    }


def _ee_writing_theme_vocabulary_overview_context(user, task, tache):
    batches = _review_batches(_theme_vocabulary_scope(task), user)
    next_batch = next(
        (batch for batch in batches if batch["is_next"]),
        None,
    )
    return {
        "theme_count": len(_ee_subject_theme_data(tache)[0]),
        "phrase_count": _theme_vocabulary_phrases(task).count(),
        "batch_count": len(batches),
        "summary": _theme_vocabulary_batch_summary(batches),
        "review_url": next_batch["review_url"] if next_batch else "",
    }


def _ee_writing_theme_vocabulary_directory(request, task, tache):
    return render(
        request,
        "study/task_vocabulary.html",
        {
            "part": task.part,
            "task": task,
            "section": "vocabulary",
            **_ee_writing_theme_vocabulary_context(
                request.user,
                task,
                tache,
            ),
        },
    )


def _ee_writing_theme_vocabulary_detail(request, task, theme, tache):
    theme_data = next(
        (
            item
            for item in _ee_subject_theme_data(tache)[0]
            if f"ee-tache-{tache}-{item.slug}" == theme.slug
        ),
        None,
    )
    if theme_data is None:
        raise Http404
    return render(
        request,
        "study/theme_vocabulary_detail.html",
        _theme_vocabulary_detail_context(
            request,
            task=task,
            theme=theme,
            theme_data=theme_data,
            sections=EE_WRITING_THEME_VOCABULARY_SECTIONS[tache],
            section="vocabulary",
            directory_url=reverse(
                "study:task_phrases",
                args=[task.part.slug, task.slug],
            ),
            back_label="Tous les thèmes",
            vocabulary_label="Vocabulaire",
            hero_description=(
                "Mémorisez des formulations directement réutilisables dans "
                "vos messages, en respectant le destinataire et l’objectif."
                if tache == 1
                else (
                    "Mémorisez des formulations pour structurer un récit, "
                    "préciser vos impressions et commenter votre expérience."
                )
            ),
            pathways_title="Quatre parcours complémentaires",
            pathways_description=(
                "Progressez des formules et détails précis vers les verbes "
                "naturels et les phrases modèles."
                if tache == 1
                else (
                    "Progressez des repères temporels vers les verbes du "
                    "récit, les impressions et les recommandations."
                )
            ),
        ),
    )


def _ee_tache_three_vocabulary_directory(request, task):
    taxonomy = _ee_subject_theme_data(3)[0]
    theme_names = {
        content_module.ee_subject_theme_name(3, theme) for theme in taxonomy
    }
    themes_by_name = {
        theme.name: theme
        for theme in Theme.objects.filter(
            task=task,
            is_active=True,
            name__in=theme_names,
        )
    }
    prompt_rows = list(
        Prompt.objects.filter(
            content_key__startswith=(
                content_module.EE_TACHE_THREE_CONTENT_PREFIX
            ),
            theme__task=task,
            theme__is_active=True,
            response__is_active=True,
            is_active=True,
        )
        .order_by()
        .values_list("theme_id", "response_id")
    )
    response_ids = {response_id for _theme_id, response_id in prompt_rows}
    progress_by_response = subject_progress_by_response(
        request.user,
        response_ids,
    )
    directory_progress = _vocabulary_deck_progress(
        progress_by_response.values()
    )
    response_ids_by_theme = {}
    prompt_count_by_theme = {}
    for theme_id, response_id in prompt_rows:
        response_ids_by_theme.setdefault(theme_id, set()).add(response_id)
        prompt_count_by_theme[theme_id] = (
            prompt_count_by_theme.get(theme_id, 0) + 1
        )
    themes = [
        {
            "theme": theme,
            "phrase_count": (
                len(response_ids_by_theme.get(theme.pk, ()))
                * content_module.EE_TACHE_THREE_VOCABULARY_PER_RESPONSE
            ),
            "section_counts": [
                {
                    "count": prompt_count_by_theme.get(theme.pk, 0),
                    "short_title": "sujets",
                },
                {
                    "count": len(response_ids_by_theme.get(theme.pk, ())),
                    "short_title": "decks",
                },
                {
                    "count": (
                        len(response_ids_by_theme.get(theme.pk, ()))
                        * content_module.EE_TACHE_THREE_VOCABULARY_PER_RESPONSE
                    ),
                    "short_title": "fiches",
                },
            ],
            "batch_count": (
                len(response_ids_by_theme.get(theme.pk, ()))
                * (
                    content_module.EE_TACHE_THREE_VOCABULARY_PER_RESPONSE
                    // queue_module.PHRASE_BATCH_SIZE
                )
            ),
            "progress_unit": "decks terminés",
            "summary": {
                "progress": _vocabulary_deck_progress(
                    progress_by_response[response_id]
                    for response_id in response_ids_by_theme.get(
                        theme.pk,
                        (),
                    )
                )
            },
            "url": reverse(
                "study:task_vocabulary_theme",
                args=[task.part.slug, task.slug, theme.slug],
            ),
            "review_url": review_url(
                {
                    **_task_scope(task),
                    "kind": "vocab",
                    "theme": theme.slug,
                }
            ),
        }
        for source_theme in taxonomy
        if (
            theme := themes_by_name.get(
                content_module.ee_subject_theme_name(3, source_theme)
            )
        )
    ]
    scope = {**_task_scope(task), "kind": "vocab"}
    review_batches = _review_batches(scope, request.user)
    next_batch = next(
        (batch for batch in review_batches if batch["is_next"]),
        None,
    )
    return render(
        request,
        "study/task_vocabulary.html",
        {
            "part": task.part,
            "task": task,
            "section": "vocabulary",
            "themes": themes,
            "theme_count": len(themes),
            "phrase_count": (
                len(response_ids)
                * content_module.EE_TACHE_THREE_VOCABULARY_PER_RESPONSE
            ),
            "batch_count": len(review_batches),
            "summary": {
                "progress": directory_progress,
                "completed": directory_progress.completed,
                "total": directory_progress.total,
                "started_new": max(
                    directory_progress.started
                    - directory_progress.completed,
                    0,
                ),
            },
            "theme_status_counts": _theme_vocabulary_status_counts(themes),
            "review_url": (
                next_batch["review_url"] if next_batch else ""
            ),
            "mixed_review_url": review_url(scope),
            "vocabulary_description": (
                "Les mots, collocations, tournures et phrases modèles de "
                "chaque sujet, regroupés par grand thème."
            ),
            "vocabulary_pathways_description": (
                "Ouvrez un thème, choisissez un sujet, puis travaillez ses "
                "lots de vocabulaire directement liés aux documents."
            ),
            "vocabulary_progress_unit": "decks terminés",
        },
    )


def _ee_tache_three_vocabulary_theme_detail(request, task, theme):
    subject_context = _task_subject_vocabulary_context(
        task,
        request.user,
        theme,
    )
    theme_group = (
        subject_context["subject_theme_groups"][0]
        if subject_context["subject_theme_groups"]
        else None
    )
    return render(
        request,
        "study/task_vocabulary_theme.html",
        {
            "part": task.part,
            "task": task,
            **subject_context,
            "vocabulary_theme": theme,
            "vocabulary_theme_group": theme_group,
            "vocabulary_review_url": (
                theme_group["review_url"] if theme_group else ""
            ),
        },
    )


def _tache_two_subject_month(month_slug):
    month = next(
        (
            month
            for month in content_module.load_tache_two_subject_months()
            if month.slug == month_slug
        ),
        None,
    )
    if month is None:
        raise Http404
    return month


def _tache_two_subject_batch(month, batch_number):
    batch = next(
        (
            batch
            for batch in month.batches
            if batch.number == batch_number
        ),
        None,
    )
    if batch is None:
        raise Http404
    return batch


def _tache_two_theme_neighbors(month_slug, batch_number, subject_number):
    """Locate a subject inside its theme.

    Returns ``(theme, position, total, previous, next)`` where the
    neighbours are dicts carrying the routing fields needed to build a
    subject-detail URL.
    """
    themes, mapping = content_module.load_tache_two_subject_themes()
    theme_by_slug = {theme.slug: theme for theme in themes}
    target_key = content_module.tache_two_subject_content_key(
        month_slug,
        batch_number,
        subject_number,
    )
    theme_slug = mapping.get(target_key)
    theme = theme_by_slug.get(theme_slug)
    ordered = [
        {
            "month_slug": month.slug,
            "batch_number": batch.number,
            "number": subject.number,
            "title": subject.title,
        }
        for month in content_module.load_tache_two_subject_months()
        for batch in month.batches
        for subject in batch.subjects
        if mapping.get(
            content_module.tache_two_subject_content_key(
                month.slug,
                batch.number,
                subject.number,
            )
        )
        == theme_slug
    ]
    index = next(
        (
            position
            for position, item in enumerate(ordered)
            if item["month_slug"] == month_slug
            and item["batch_number"] == batch_number
            and item["number"] == subject_number
        ),
        None,
    )
    if index is None:
        return theme, 0, len(ordered), None, None
    previous_item = ordered[index - 1] if index > 0 else None
    next_item = ordered[index + 1] if index + 1 < len(ordered) else None
    return theme, index + 1, len(ordered), previous_item, next_item


def task_subject_batch(request, part_slug, task_slug, month_slug, batch_number):
    task = _memory_task(part_slug, task_slug)
    month = _tache_two_subject_month(month_slug)
    _tache_two_subject_batch(month, batch_number)
    month = _tache_two_progress(request.user, (month,))["months"][0]
    batch = next(
        batch
        for batch in month["batches"]
        if batch["number"] == batch_number
    )
    subject_prompt_map = {
        subject["content_key"]: subject["prompt"]
        for subject in batch["subjects"]
    }
    return render(
        request,
        "study/tache_two_subject_batch.html",
        {
            "part": task.part,
            "task": task,
            "subject_month": month,
            "subject_batch": batch,
            "subject_prompt_map": subject_prompt_map,
        },
    )


def tache_two_annotation_source_key(subject_content_key: str) -> str:
    """Annotation root key for a Tâche 2 subject, shared by equivalents."""
    match = routing.TACHE_TWO_PROMPT_KEY.fullmatch(subject_content_key)
    if match is None:
        raise ValueError(
            "A Tâche 2 annotation key needs a subject content key."
        )
    return (
        f"tache-two:{match['month']}:batch-{int(match['batch'])}:"
        f"subject-{int(match['subject'])}"
    )


def _tache_two_equivalent_subjects(response, selected_prompt):
    """List the other subjects that reuse this exact set of questions."""
    others = [
        prompt
        for prompt in response.prompts.filter(is_active=True).select_related(
            "theme__task__part",
        )
        if prompt.pk != selected_prompt.pk
    ]
    if not others:
        return []

    subject_rows = {}
    for month in content_module.load_tache_two_subject_months():
        for batch in month.batches:
            for subject in batch.subjects:
                subject_rows[
                    content_module.tache_two_subject_content_key(
                        month.slug,
                        batch.number,
                        subject.number,
                    )
                ] = (month, batch, subject)

    equivalents = []
    for prompt in others:
        row = subject_rows.get(prompt.content_key)
        if row is None:
            continue
        month, batch, subject = row
        equivalents.append(
            {
                "month_number": month.number,
                "month_slug": month.slug,
                "month_name": month.name,
                "batch_number": batch.number,
                "number": subject.number,
                "number_label": subject.number_label,
                "title": subject.title,
                "prompt": prompt.text,
                "url": prompt_detail_url(prompt),
            }
        )
    equivalents.sort(key=lambda item: (item["month_number"], item["number"]))
    return equivalents


def task_subject_detail(
    request,
    part_slug,
    task_slug,
    month_slug,
    batch_number,
    subject_number,
):
    task = _memory_task(part_slug, task_slug)
    month = _tache_two_subject_month(month_slug)
    batch = _tache_two_subject_batch(month, batch_number)
    subject = next(
        (
            subject
            for subject in batch.subjects
            if subject.number == subject_number
        ),
        None,
    )
    if subject is None:
        raise Http404

    response = get_object_or_404(
        Response.objects.select_related(
            "theme__task__part",
            "family",
        ),
        prompts__content_key=content_module.tache_two_subject_content_key(
            month.slug,
            batch.number,
            subject.number,
        ),
        prompts__is_active=True,
        prompts__theme__task=task,
        is_active=True,
    )
    selected_prompt = get_object_or_404(
        Prompt.objects.select_related(
            "theme__task__part",
            "family",
            "response",
        ),
        response=response,
        content_key=content_module.tache_two_subject_content_key(
            month.slug,
            batch.number,
            subject.number,
        ),
        is_active=True,
    )
    equivalent_subjects = _tache_two_equivalent_subjects(
        response,
        selected_prompt,
    )
    subject_annotation_key = tache_two_annotation_source_key(
        response.content_key
    )
    subject_progress = subject_progress_by_response(
        request.user,
        {response.pk},
    )[response.pk]
    card = Card.objects.filter(
        user=request.user,
        card_type=CardType.SPINE,
        response=response,
    ).first()
    task_scope = {"part": task.part.slug, "task": task.slug}
    vocabulary_context = _subject_vocabulary_context(
        response,
        task_scope,
        request.user,
    )
    response_content = effective_response(response, request.user)
    questions = [
        {
            "number": index,
            "text": argument.idea,
            "response": argument.developpement,
        }
        for index, argument in enumerate(
            response_content.arguments,
            start=1,
        )
    ]
    (
        subject_theme,
        subject_position,
        subject_total,
        previous_subject,
        next_subject,
    ) = _tache_two_theme_neighbors(
        month.slug,
        batch.number,
        subject.number,
    )
    return render(
        request,
        "study/tache_two_subject_detail.html",
        {
            "part": task.part,
            "task": task,
            "subject_month": month,
            "subject_batch": batch,
            "subject": subject,
            "subject_questions": questions,
            "response_content": response_content,
            "subject_theme_name": (
                subject_theme.name if subject_theme else ""
            ),
            "subject_theme_slug": (
                subject_theme.slug if subject_theme else ""
            ),
            "previous_subject": previous_subject,
            "next_subject": next_subject,
            "subject_position": subject_position,
            "subject_total": subject_total,
            "selected_prompt": selected_prompt,
            "equivalent_subjects": equivalent_subjects,
            "subject_annotation_key": subject_annotation_key,
            "response": response,
            "card": card,
            "subject_progress": subject_progress,
            "response_review_url": review_url(
                {
                    **task_scope,
                    "kind": "spine",
                    "response": str(response.pk),
                }
            ),
            "theme_review_url": review_url(
                {
                    **task_scope,
                    "kind": "spine",
                    "theme": response.theme.slug,
                }
            ),
            "personal_saved": request.GET.get("saved") == "1",
            "personal_reset": request.GET.get("reset") == "1",
            **vocabulary_context,
        },
    )


def _memory_sections(memory, completed_keys, personal_responses=None):
    personal_responses = personal_responses or {}
    sections = []
    for section in memory.sections:
        completed_count = len(set(section.question_keys) & completed_keys)
        sections.append(
            {
                "number": section.number,
                "number_label": section.number_label,
                "title": section.title,
                "anchor": section.anchor,
                "question_count": section.question_count,
                "progress": progress_summary(
                    total=section.question_count,
                    started=completed_count,
                    completed=completed_count,
                ),
                "groups": [
                    {
                        "title": group.title,
                        "guidance": group.guidance,
                        "questions": [
                            {
                                "content_key": question.content_key,
                                "text": question.text,
                                "note": question.note,
                                "completed": (
                                    question.content_key in completed_keys
                                ),
                                "response": personal_responses.get(
                                    question.content_key,
                                    "",
                                ),
                            }
                            for question in group.questions
                        ],
                    }
                    for group in section.groups
                ],
            }
        )
    return sections


def _question_bank_page_context(user, task, question_bank):
    task_key = (task.part.slug, task.slug)
    question_responses_enabled = (
        task_key == content_module.EO_TACHE_ONE_TASK
    )
    personal_responses = {}
    if question_responses_enabled:
        personal_responses = dict(
            PersonalQuestionResponse.objects.filter(
                user=user,
                task=task,
                question_key__in=question_bank.question_keys,
            ).values_list("question_key", "body")
        )
    memory_state = _memory_progress(
        user,
        (question_bank,),
    )[question_bank.number]
    return {
        "part": task.part,
        "task": task,
        "memory_task": (
            (task.part.slug, task.slug)
            == content_module.QUESTION_BANK_TASK
        ),
        "question_bank": question_bank,
        "memory_progress": memory_state["progress"],
        "memory_sections": _memory_sections(
            question_bank,
            memory_state["completed_keys"],
            personal_responses,
        ),
        "question_responses_enabled": question_responses_enabled,
        "question_response_max_length": (
            PERSONAL_QUESTION_RESPONSE_MAX_LENGTH
        ),
    }


def _memory_progress_error(request, message):
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"error": message}, status=400)
    return HttpResponseBadRequest(message)


@require_POST
def task_question_response(request, part_slug, task_slug, memory_number):
    task = _memoire_task(request, part_slug, task_slug)
    if (task.part.slug, task.slug) != content_module.EO_TACHE_ONE_TASK:
        raise Http404

    memory = _memory_by_number(_load_task_memoires(task), memory_number)
    question_key = request.POST.get("question_key", "").strip()
    section = next(
        (
            section
            for section in memory.sections
            if question_key in section.question_keys
        ),
        None,
    )
    if section is None:
        return _memory_progress_error(
            request,
            "Cette question ne fait pas partie de la banque.",
        )

    action = request.POST.get("action", "save")
    if action == "delete":
        PersonalQuestionResponse.objects.filter(
            user=request.user,
            task=task,
            question_key=question_key,
        ).delete()
        body = ""
    elif action == "save":
        body = (request.POST.get("body") or "").strip()
        if not body:
            return _memory_progress_error(
                request,
                "Votre réponse ne peut pas être vide.",
            )
        if len(body) > PERSONAL_QUESTION_RESPONSE_MAX_LENGTH:
            return _memory_progress_error(
                request,
                "Votre réponse ne peut pas dépasser 10 000 caractères.",
            )
        PersonalQuestionResponse.objects.update_or_create(
            user=request.user,
            task=task,
            question_key=question_key,
            defaults={"body": body},
        )
    else:
        return _memory_progress_error(request, "Action invalide.")

    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse(
            {
                "question_key": question_key,
                "body": body,
                "has_response": bool(body),
            }
        )
    return redirect(
        reverse(
            "study:task_detail",
            args=[task.part.slug, task.slug],
        )
        + f"#{section.anchor}"
    )


def task_memory_detail(request, part_slug, task_slug, memory_number):
    task = _memoire_task(request, part_slug, task_slug)
    if (task.part.slug, task.slug) == content_module.EO_TACHE_ONE_TASK:
        return redirect(
            "study:task_detail",
            part_slug=task.part.slug,
            task_slug=task.slug,
        )
    if (task.part.slug, task.slug) == content_module.QUESTION_BANK_TASK:
        return redirect("study:tache_two_theme_vocabulary")
    memories = _load_task_memoires(task)
    question_bank = _memory_by_number(memories, memory_number)
    return render(
        request,
        "study/question_bank.html",
        _question_bank_page_context(
            request.user,
            task,
            question_bank,
        ),
    )


@require_POST
def task_memory_progress(request, part_slug, task_slug, memory_number):
    task = _memoire_task(request, part_slug, task_slug)
    if (task.part.slug, task.slug) == content_module.QUESTION_BANK_TASK:
        return redirect("study:tache_two_theme_vocabulary")
    memories = _load_task_memoires(task)
    memory = _memory_by_number(memories, memory_number)
    question_key = request.POST.get("question_key", "").strip()
    completed = request.POST.get("completed")
    if completed not in {"0", "1"}:
        return _memory_progress_error(
            request,
            "État de progression invalide.",
        )

    section = next(
        (
            section
            for section in memory.sections
            if question_key in section.question_keys
        ),
        None,
    )
    if section is None:
        return _memory_progress_error(
            request,
            "Cette question ne fait pas partie de la mémoire.",
        )

    if completed == "1":
        MemoryQuestionProgress.objects.get_or_create(
            user=request.user,
            memory_number=memory.number,
            question_key=question_key,
        )
    else:
        MemoryQuestionProgress.objects.filter(
            user=request.user,
            memory_number=memory.number,
            question_key=question_key,
        ).delete()

    memory_state = _memory_progress(
        request.user,
        (memory,),
    )[memory.number]
    memory_summary = memory_state["progress"]
    section_completed = len(
        set(section.question_keys) & memory_state["completed_keys"]
    )
    section_summary = progress_summary(
        total=section.question_count,
        started=section_completed,
        completed=section_completed,
    )
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse(
            {
                "completed": completed == "1",
                "question_key": question_key,
                "memory": {
                    "completed": memory_summary.completed,
                    "total": memory_summary.total,
                    "percent": memory_summary.percent,
                    "status": memory_summary.status,
                    "label": memory_summary.label,
                },
                "section": {
                    "number": section.number,
                    "completed": section_summary.completed,
                    "total": section_summary.total,
                    "percent": section_summary.percent,
                    "status": section_summary.status,
                    "label": section_summary.label,
                },
            }
        )
    if (task.part.slug, task.slug) == content_module.EO_TACHE_ONE_TASK:
        return redirect(
            "study:task_detail",
            part_slug=task.part.slug,
            task_slug=task.slug,
        )
    return redirect(
        reverse(
            "study:task_memory_detail",
            args=[task.part.slug, task.slug, memory.number],
        )
        + f"#{section.anchor}"
    )


@require_POST
def subject_completion(request, part_slug, task_slug, response_id):
    task = _route_task(part_slug, task_slug, request=request)
    route_prompt = (
        Prompt.objects.select_related("response")
        .filter(
            response_id=response_id,
            response__is_active=True,
            is_active=True,
            theme__is_active=True,
            theme__task=task,
        )
        .order_by("-is_canonical", "number", "pk")
        .first()
    )
    if route_prompt is None:
        raise Http404
    response = route_prompt.response
    completed = request.POST.get("completed")
    if completed not in {"0", "1"}:
        if request.headers.get("X-Requested-With") == "fetch":
            return JsonResponse(
                {"error": "État de progression invalide."},
                status=400,
            )
        return HttpResponseBadRequest("État de progression invalide.")

    card, _created = Card.objects.get_or_create(
        user=request.user,
        card_type=CardType.SPINE,
        response=response,
    )
    completed_at = timezone.now() if completed == "1" else None
    Card.objects.filter(pk=card.pk).update(
        subject_completed_at=completed_at,
    )
    progress = subject_progress_by_response(
        request.user,
        {response.pk},
    )[response.pk]

    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse(
            {
                "response_id": response.pk,
                "completed": progress.explicitly_completed,
                "subject": {
                    "status": progress.status,
                    "label": progress.label,
                },
            }
        )

    return redirect(prompt_detail_url(route_prompt))


def family_detail(request, part_slug, task_slug, slug):
    task = _route_task(part_slug, task_slug, request=request)
    if (
        (task.part.slug, task.slug) == content_module.EE_TACHE_THREE_TASK
        and slug.removeprefix("ee-tache-3-") in content_module.EE_MONTH_ORDER
    ):
        return redirect(
            "study:task_browse",
            task.part.slug,
            task.slug,
        )
    family = get_object_or_404(
        Family.objects.filter(
            prompts__is_active=True,
            prompts__theme__task=task,
        ).distinct(),
        slug=slug,
        is_active=True,
    )
    prompts = list(
        Prompt.objects.filter(
            family=family,
            theme__task=task,
            is_active=True,
        )
        .select_related("response__theme", "theme", "family")
        .order_by("theme__order", "number")
    )
    if (
        (task.part.slug, task.slug) == content_module.EE_TACHE_THREE_TASK
        and prompts
        and all(
            prompt.content_key.startswith(
                content_module.EE_TACHE_THREE_CONTENT_PREFIX
            )
            for prompt in prompts
        )
    ):
        return redirect(
            "study:theme_detail",
            task.part.slug,
            task.slug,
            prompts[0].theme.slug,
        )
    response_ids = [prompt.response_id for prompt in prompts]
    canonical_numbers = _canonical_numbers_by_response(response_ids)
    subject_progress = subject_progress_by_response(
        request.user,
        response_ids,
    )
    rows = [
        {
            "prompt": prompt,
            "progress": subject_progress[prompt.response_id],
            "is_alias": not prompt.is_canonical,
            "canonical_number": canonical_numbers.get(prompt.response_id),
        }
        for prompt in prompts
    ]
    return render(
        request,
        "study/family_detail.html",
        {
            "family": family,
            "task": task,
            "part": task.part,
            "rows": rows,
            "family_progress": summarize_subject_progress(
                subject_progress.values()
            )["progress"],
            "review_url": review_url(
                {
                    "kind": "spine",
                    "part": task.part.slug,
                    "task": task.slug,
                    "family": family.slug,
                }
            ),
        },
    )


def _subject_vocabulary_context(response, task_scope, user):
    subject_vocabulary = list(
        Phrase.objects.filter(
            source_prompts__response=response,
            is_active=True,
            tier=PhraseTier.SUBJECT,
        )
        .distinct()
        .select_related("category")
        .order_by("lot_order", "phrase_id")
    )
    vocabulary_count = len(subject_vocabulary)
    vocabulary_batches = _review_batches(
        {
            **task_scope,
            "kind": "vocab",
            "response": str(response.pk),
        },
        user,
    )
    vocabulary_batch_progress = summarize_review_batches(
        vocabulary_batches
    )
    vocabulary_lot_labels = {
        "Mots clés du sujet": "Mots clés",
        "Collocations du sujet": "Collocations",
        "Expressions du sujet": "Expressions et idiomes",
        "Tournures pour l'oral": "Tournures pour l'oral",
        "Phrases modèles": "Phrases modèles",
    }
    for batch in vocabulary_batches:
        start = (batch["number"] - 1) * queue_module.PHRASE_BATCH_SIZE
        if start < vocabulary_count:
            category_name = subject_vocabulary[start].category.name
            batch["label"] = vocabulary_lot_labels.get(
                category_name,
                category_name,
            )
    first_vocabulary_batch = next(
        (batch for batch in vocabulary_batches if batch["can_review"]),
        vocabulary_batches[0] if vocabulary_batches else None,
    )
    return {
        "subject_vocabulary": subject_vocabulary[:10],
        "vocabulary_count": vocabulary_count,
        "vocabulary_batches": vocabulary_batches,
        "vocabulary_batch_progress": vocabulary_batch_progress,
        "vocabulary_review_url": (
            first_vocabulary_batch["review_url"]
            if first_vocabulary_batch
            else None
        ),
    }


def response_detail(request, part_slug, task_slug, prompt_id):
    task = _route_task(part_slug, task_slug, request=request)
    selected_prompt = get_object_or_404(
        Prompt.objects.select_related(
            "response__theme__task__part",
            "response__family",
            "theme__task__part",
            "family",
        ),
        pk=prompt_id,
        is_active=True,
        response__is_active=True,
        theme__is_active=True,
        theme__task=task,
    )
    if (task.part.slug, task.slug) == content_module.QUESTION_BANK_TASK:
        return redirect(prompt_detail_url(selected_prompt))
    response = selected_prompt.response
    response_content = effective_response(response, request.user)
    subject_progress = subject_progress_by_response(
        request.user,
        {response.pk},
    )[response.pk]
    prompts = list(
        response.prompts.filter(
            is_active=True,
            theme__is_active=True,
        ).select_related(
            "theme__task__part",
            "family",
        )
    )

    navigation_prompts = Prompt.objects.filter(
        is_active=True,
        theme__is_active=True,
        theme_id=selected_prompt.theme_id,
    ).select_related("theme__task__part")
    navigation_prompts = list(
        navigation_prompts.order_by("number", "pk")
    )
    prompt_index = next(
        index
        for index, prompt in enumerate(navigation_prompts)
        if prompt.pk == selected_prompt.pk
    )
    previous_prompt = (
        navigation_prompts[prompt_index - 1] if prompt_index > 0 else None
    )
    next_prompt = (
        navigation_prompts[prompt_index + 1]
        if prompt_index + 1 < len(navigation_prompts)
        else None
    )

    card = Card.objects.filter(
        user=request.user,
        card_type=CardType.SPINE,
        response=response,
    ).first()
    related_phrases = (
        Phrase.objects.filter(
            source_prompts__response=response,
            is_active=True,
        )
        .exclude(tier=PhraseTier.SUBJECT)
        .distinct()
        .select_related("category")
    )
    task_scope = {"part": task.part.slug, "task": task.slug}
    # The phrase lots only ever cover shared and response-level phrases of this
    # sujet, all of which appear in the related list, so an empty list means
    # there is nothing to partition and no reason to scan the deck. Evaluating
    # the queryset once serves both the check and the template.
    related_phrase_list = list(related_phrases)
    phrase_batches = (
        _review_batches(
            {
                **task_scope,
                "kind": "phrase",
                "response": str(response.pk),
            },
            request.user,
        )
        if related_phrase_list
        else []
    )
    phrase_batch_progress = summarize_review_batches(phrase_batches)
    vocabulary_context = _subject_vocabulary_context(
        response,
        task_scope,
        request.user,
    )
    ee_response = (
        (task.part.slug, task.slug)
        == content_module.EE_TACHE_THREE_TASK
        and response.content_key.startswith(
            content_module.EE_TACHE_THREE_CONTENT_PREFIX
        )
    )
    ee_combination_label = ""
    ee_source_month = None
    ee_source_url = ""
    ee_equivalent_subjects = []
    ee_source_warnings = []
    ee_response_origin = "original"
    ee_subject_instruction = ""
    ee_subject_copy_text = ""
    source_documents_html = response.body_html
    if ee_response:
        if response.content_key in (
            content_module.load_ee_tache_three_author_responses()
        ):
            ee_response_origin = "author"
        source_row = _ee_tache_three_sources_by_key().get(
            selected_prompt.content_key
        )
        if source_row is None:
            raise RuntimeError("EE Tâche 3 content is not synchronized")
        ee_source_month, source = source_row
        ee_combination_label = source.combinaison
        ee_source_url = content_module.EE_2025_SOURCE_URL.format(
            month=ee_source_month.slug
        )
        source_documents_html = content_module._ee_tache_three_documents_html(
            (source.document1, source.document2)
        )
        if source.document1_invalid:
            ee_source_warnings.append(
                "Le premier document publié est hors sujet ; la réponse "
                "s’appuie uniquement sur le document valide."
            )
        if source.document2_missing:
            ee_source_warnings.append(
                "La source publique ne fournit pas de deuxième document."
            )
        if source.documents_identical:
            ee_source_warnings.append(
                "La source publique a publié deux documents identiques."
            )
        if source.title_missing:
            ee_source_warnings.append(
                "Le titre affiché a été déduit des documents, car la source "
                "n’en publie aucun."
            )
        ee_subject_instruction = content_module.ee_tache_three_instruction(
            selected_prompt.text
        )
        copied_document2 = (
            source.document2
            if source.document2
            else "(document non fourni par la source publiée)"
        )
        source_note = " ".join(ee_source_warnings)
        ee_subject_copy_text = content_module.ee_exam_subject_packet(
            3,
            selected_prompt.text,
            document1=source.document1,
            document2=copied_document2,
            source_note=source_note,
        )
        for prompt in prompts:
            if prompt.pk == selected_prompt.pk:
                continue
            equivalent_row = _ee_tache_three_sources_by_key().get(
                prompt.content_key
            )
            if equivalent_row is None:
                raise RuntimeError("EE Tâche 3 content is not synchronized")
            equivalent_month, equivalent = equivalent_row
            ee_equivalent_subjects.append(
                {
                    "prompt": prompt,
                    "month": equivalent_month,
                    "combinaison": equivalent.combinaison,
                }
            )
    return render(
        request,
        "study/response_detail.html",
        {
            "response": response,
            "selected_prompt": selected_prompt,
            "previous_prompt": previous_prompt,
            "next_prompt": next_prompt,
            "prompt_position": prompt_index + 1,
            "prompt_total": len(navigation_prompts),
            "task": task,
            "part": task.part,
            "response_content": response_content,
            "arguments": response_content.arguments,
            "ee_response": ee_response,
            "ee_combination_label": ee_combination_label,
            "ee_source_month": ee_source_month,
            "ee_source_url": ee_source_url,
            "ee_equivalent_subjects": ee_equivalent_subjects,
            "ee_source_warnings": ee_source_warnings,
            "ee_response_origin": ee_response_origin,
            "ee_subject_instruction": ee_subject_instruction,
            "ee_subject_copy_text": ee_subject_copy_text,
            "source_documents_html": source_documents_html,
            "prompts": prompts,
            "card": card,
            "subject_progress": subject_progress,
            "related_phrases": related_phrase_list,
            "phrase_batches": phrase_batches,
            "phrase_batch_progress": phrase_batch_progress,
            **vocabulary_context,
            "can_edit_response": response.prompts.filter(
                is_active=True,
                theme__task__slug="tache-3",
                theme__task__part__slug="eo",
            ).exists(),
            "response_review_url": review_url(
                {
                    **task_scope,
                    "kind": "spine",
                    "response": str(response.pk),
                }
            ),
            "theme_review_url": review_url(
                {
                    **task_scope,
                    "kind": "spine",
                    "theme": selected_prompt.theme.slug,
                }
            ),
            "personal_saved": request.GET.get("saved") == "1",
            "personal_reset": request.GET.get("reset") == "1",
        },
    )


def edit_response(request, part_slug, task_slug, prompt_id):
    task = _route_task(part_slug, task_slug, request=request)
    task_key = (task.part.slug, task.slug)
    is_tache_two = task_key == content_module.QUESTION_BANK_TASK
    if not (
        is_tache_two
        or task_key == ("eo", "tache-3")
    ):
        raise Http404
    selected_prompt = get_object_or_404(
        Prompt.objects.filter(
            pk=prompt_id,
            is_active=True,
            response__is_active=True,
            theme__is_active=True,
            theme__task=task,
        )
        .select_related(
            "response__theme__task__part",
            "response__family",
            "theme__task__part",
            "family",
        )
    )
    response = selected_prompt.response
    personal = PersonalResponse.objects.filter(
        user=request.user,
        response=response,
    ).first()
    detail_url = prompt_detail_url(selected_prompt)
    if request.method == "POST" and request.POST.get("action") == "reset":
        if personal is not None:
            personal.delete()
        return redirect(f"{detail_url}?reset=1")

    if is_tache_two:
        response_content = effective_response(response, request.user)
        initial_questions = [
            {
                "question": argument.idea,
                "response": argument.developpement,
            }
            for argument in response_content.arguments
        ]
        if not initial_questions:
            initial_questions = [{"question": "", "response": ""}]
        question_formset = TacheTwoQuestionFormSet(
            request.POST or None,
            initial=initial_questions,
            prefix="questions",
        )
        if request.method == "POST" and question_formset.is_valid():
            arguments = []
            for question_form in question_formset:
                if (
                    not question_form.cleaned_data
                    or question_form.cleaned_data.get("DELETE")
                ):
                    continue
                arguments.append(
                    {
                        "order": len(arguments) + 1,
                        "idea": question_form.cleaned_data["question"],
                        "developpement": question_form.cleaned_data[
                            "response"
                        ],
                        "exemple": "",
                        "consequence": "",
                    }
                )
            PersonalResponse.objects.update_or_create(
                user=request.user,
                response=response,
                defaults={
                    "reformulation": "",
                    "position": "",
                    "position_claire": "",
                    "arguments": arguments,
                    "nuance": "",
                    "conclusion": "",
                },
            )
            return redirect(f"{detail_url}?saved=1")
        return render(
            request,
            "study/response_edit.html",
            {
                "response": response,
                "selected_prompt": selected_prompt,
                "task": task,
                "part": task.part,
                "is_tache_two": True,
                "question_formset": question_formset,
                "has_personal_response": personal is not None,
                "detail_url": detail_url,
            },
        )

    form = PersonalResponseForm(
        response,
        request.user,
        request.POST or None,
    )
    if request.method == "POST" and form.is_valid():
        PersonalResponse.objects.update_or_create(
            user=request.user,
            response=response,
            defaults=form.personal_defaults(),
        )
        return redirect(f"{detail_url}?saved=1")

    argument_fields = []
    for order in form.argument_orders:
        argument_fields.append(
            {
                "order": order,
                "fields": [
                    form[f"argument_{order}_{key}"]
                    for key, _label, _rows in form.argument_parts
                ],
            }
        )
    return render(
        request,
        "study/response_edit.html",
        {
            "response": response,
            "selected_prompt": selected_prompt,
            "task": task,
            "part": task.part,
            "form": form,
            "argument_fields": argument_fields,
            "has_personal_response": personal is not None,
            "detail_url": detail_url,
        },
    )


def _route_writing_sujet(request, part_slug, task_slug, sujet_id):
    task = _route_task(part_slug, task_slug, request=request)
    tache = _ee_writing_tache(task)
    if tache is None:
        raise Http404
    sujet = get_object_or_404(
        WritingSujet.objects.select_related("task__part"),
        pk=sujet_id,
        is_active=True,
        task=task,
    )
    return task, sujet, tache


def _canonical_writing_sujet(task, sujet, tache):
    canonical_slug = content_module.ee_writing_canonical_slug_by_slug(
        tache
    ).get(sujet.slug, sujet.slug)
    if canonical_slug == sujet.slug:
        return sujet
    return get_object_or_404(
        WritingSujet.objects.select_related("task__part"),
        task=task,
        slug=canonical_slug,
        is_active=True,
    )


@lru_cache(maxsize=2)
def _ee_writing_sources_by_slug(tache):
    return {
        source.slug: source
        for category in _ee_writing_source_categories(tache)
        for source in category.sujets
    }


def writing_sujet_detail(request, part_slug, task_slug, sujet_id):
    task, sujet, tache = _route_writing_sujet(
        request,
        part_slug,
        task_slug,
        sujet_id,
    )
    canonical = _canonical_writing_sujet(task, sujet, tache)
    personal = PersonalWritingResponse.objects.filter(
        user=request.user,
        sujet=canonical,
    ).first()
    writing_progress = writing_sujet_progress_by_id(
        request.user,
        [canonical.pk],
        task_id=task.pk,
    )[canonical.pk]
    explicitly_completed = writing_progress.explicitly_completed
    model_versions = canonical.model_versions
    siblings = list(
        WritingSujet.objects.filter(
            task=task,
            is_active=True,
            category=sujet.category,
        ).order_by("order", "id")
    )
    index = next(
        (i for i, item in enumerate(siblings) if item.pk == sujet.pk),
        0,
    )
    sources_by_slug = _ee_writing_sources_by_slug(tache)
    source = sources_by_slug.get(sujet.slug)
    canonical_slug_by_slug = (
        content_module.ee_writing_canonical_slug_by_slug(tache)
    )
    equivalent_sujets = [
        {
            "sujet": candidate,
            "source": sources_by_slug[candidate.slug],
        }
        for candidate in WritingSujet.objects.filter(
            task=task,
            is_active=True,
            slug__in=[
                slug
                for slug, canonical_slug in canonical_slug_by_slug.items()
                if canonical_slug == canonical.slug
            ],
        ).order_by("order", "pk")
        if candidate.pk != sujet.pk
    ]
    minimum, maximum = content_module.EE_WRITING_WORD_LIMITS[tache]
    return render(
        request,
        "study/writing_sujet_detail.html",
        {
            "part": task.part,
            "task": task,
            "sujet": sujet,
            "progress_sujet": canonical,
            "prompt": sujet.prompt,
            "category_label": sujet.category_label,
            "source": source,
            "source_url": (
                content_module.EE_2025_SOURCE_URL.format(
                    month=source.month_slug
                )
                if source
                else ""
            ),
            "equivalent_sujets": equivalent_sujets,
            "writing_tache": tache,
            "word_limit_min": minimum,
            "word_limit_max": maximum,
            "personal": personal,
            "has_personal": personal is not None,
            "writing_progress": writing_progress,
            "explicitly_completed": explicitly_completed,
            "model_versions": model_versions,
            "primary_version": model_versions[0] if model_versions else None,
            "other_versions": model_versions[1:],
            "other_version_count": max(len(model_versions) - 1, 0),
            "previous_sujet": siblings[index - 1] if index > 0 else None,
            "next_sujet": (
                siblings[index + 1]
                if index + 1 < len(siblings)
                else None
            ),
            "position": index + 1,
            "total": len(siblings),
            "personal_saved": request.GET.get("saved") == "1",
            "personal_reset": request.GET.get("reset") == "1",
        },
    )


@require_POST
def writing_sujet_completion(request, part_slug, task_slug, sujet_id):
    task, sujet, tache = _route_writing_sujet(
        request,
        part_slug,
        task_slug,
        sujet_id,
    )
    canonical = _canonical_writing_sujet(task, sujet, tache)
    completed = request.POST.get("completed")
    if completed not in {"0", "1"}:
        if request.headers.get("X-Requested-With") == "fetch":
            return JsonResponse(
                {"error": "État de progression invalide."},
                status=400,
            )
        return HttpResponseBadRequest("État de progression invalide.")

    completion = WritingSujetCompletion.objects.filter(
        user=request.user,
        sujet=canonical,
    )
    if completed == "1":
        WritingSujetCompletion.objects.get_or_create(
            user=request.user,
            sujet=canonical,
        )
        explicitly_completed = True
    else:
        completion.delete()
        explicitly_completed = False

    progress = writing_sujet_progress_by_id(
        request.user,
        [canonical.pk],
        task_id=task.pk,
    )[canonical.pk]
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse(
            {
                "sujet_id": canonical.pk,
                "completed": explicitly_completed,
                "sujet": {
                    "status": progress.status,
                    "label": progress.label,
                },
            }
        )

    return redirect(
        reverse(
            "study:writing_sujet_detail",
            args=[task.part.slug, task.slug, sujet.pk],
        )
    )


def writing_sujet_edit(request, part_slug, task_slug, sujet_id):
    task, sujet, tache = _route_writing_sujet(
        request,
        part_slug,
        task_slug,
        sujet_id,
    )
    canonical = _canonical_writing_sujet(task, sujet, tache)
    personal = PersonalWritingResponse.objects.filter(
        user=request.user,
        sujet=canonical,
    ).first()
    detail_url = reverse(
        "study:writing_sujet_detail",
        args=[part_slug, task_slug, sujet.pk],
    )
    if request.method == "POST" and request.POST.get("action") == "reset":
        if personal is not None:
            personal.delete()
        return redirect(f"{detail_url}?reset=1")

    body_value = personal.body if personal else ""
    error = ""
    if request.method == "POST":
        body_value = request.POST.get("body") or ""
        cleaned = body_value.strip()
        if not cleaned:
            error = "Votre message ne peut pas être vide."
        else:
            PersonalWritingResponse.objects.update_or_create(
                user=request.user,
                sujet=canonical,
                defaults={"body": cleaned},
            )
            return redirect(f"{detail_url}?saved=1")

    source = _ee_writing_sources_by_slug(tache).get(sujet.slug)
    return render(
        request,
        "study/writing_sujet_edit.html",
        {
            "part": task.part,
            "task": task,
            "sujet": sujet,
            "progress_sujet": canonical,
            "prompt": sujet.prompt,
            "category_label": sujet.category_label,
            "source": source,
            "source_url": (
                content_module.EE_2025_SOURCE_URL.format(
                    month=source.month_slug
                )
                if source
                else ""
            ),
            "writing_tache": tache,
            "word_limit_min": content_module.EE_WRITING_WORD_LIMITS[tache][0],
            "word_limit_max": content_module.EE_WRITING_WORD_LIMITS[tache][1],
            "body_value": body_value,
            "error": error,
            "has_personal": personal is not None,
            "model_versions": canonical.model_versions,
            "detail_url": detail_url,
        },
    )


def _category_review_batches(phrase_scope, user, categories) -> dict:
    """Stable lots for several phrase categories, from one fetch of the rows.

    A phrase card's category is its phrase's category, so the scope's rows
    partition cleanly by category, and the ordering runs down to the card id,
    so filtering the ordered list per category yields the same lots — and the
    same lot numbers — as one query per category.
    """
    rows = batch_rows(phrase_scope, user, extra_fields=("phrase__category_id",))
    rows_by_category = {}
    for row in rows:
        rows_by_category.setdefault(row["phrase__category_id"], []).append(row)
    return {
        category.pk: review_batches_from_rows(
            rows_by_category.get(category.pk, []),
            {**phrase_scope, "category": category.slug},
        )
        for category in categories
    }


def _comprehension_vocabulary_decks(tests, user, now) -> list[dict]:
    """The vocabulary deck row of every comprehension test, batched.

    A test's deck used to cost about seven queries — the scoped cards, the
    stable lots, the unit progress, the deck summary and the queue counts —
    which a directory listing multiplied by every published test. All of them
    read the same card rows, so this fetches them once for every test on the
    page and splits them by test in Python.

    A comprehension-vocabulary card always targets a phrase, and a phrase
    belongs to a test through the questions that source it, so a phrase shared
    by two tests lands in both decks exactly as ``scoped_cards(test=...)``
    placed it.
    """
    if not tests:
        return []
    test_slugs = [test.slug for test in tests]
    deck_scope = {"kind": "vocab", "test": test_slugs}
    rows = batch_rows(
        deck_scope,
        user,
        extra_fields=("interval_days",),
    )
    test_ids_by_phrase = {}
    for phrase_id, test_id in (
        Phrase.objects.filter(
            source_questions__test__slug__in=test_slugs,
            source_questions__test__is_active=True,
        )
        .order_by()
        .values_list("pk", "source_questions__test_id")
        .distinct()
    ):
        test_ids_by_phrase.setdefault(phrase_id, set()).add(test_id)

    revisit_totals = _scoped_totals_by_test(
        queue_module.scoped_cards(
            {"kind": "revisit", "test": test_slugs},
            user=user,
        ),
        test_ids_by_phrase,
    )
    decks = []
    for test in tests:
        test_rows = [
            row
            for row in rows
            if test.pk in test_ids_by_phrase.get(row["phrase_id"], ())
        ]
        active_rows = [row for row in test_rows if not row["suspended"]]
        test_scope = {"kind": "vocab", "test": test.slug}
        batches = review_batches_from_rows(test_rows, test_scope, now)
        decks.append(
            {
                "test": test,
                "vocabulary_count": test.vocabulary_count,
                "batch_count": len(batches),
                "completed_batch_count": sum(
                    batch["status"] == "complete" for batch in batches
                ),
                "progress": card_unit_progress_from_rows(test_rows),
                "stats": deck_stats_from_rows(active_rows, now),
                "counts": _vocabulary_queue_counts(
                    active_rows,
                    now,
                    revisit_total=revisit_totals.get(test.pk, 0),
                ),
                "skill_code": comprehension_skill(test.mode),
                "detail_url": comprehension_vocabulary_url(test=test),
                "review_url": review_url({**test_scope, "batch": "1"}),
            }
        )
    return decks


def _scoped_totals_by_test(cards, test_ids_by_phrase) -> dict:
    """Count a scoped card queryset per test, from one pass over its rows.

    Counts cards, not phrases: a phrase can own both a production and a
    recognition card, and the scoped count the directory replaces counts each
    of them.
    """
    totals: dict = {}
    for _card_id, phrase_id in (
        queue_module.narrow(cards).values_list("id", "phrase_id").distinct()
    ):
        for test_id in test_ids_by_phrase.get(phrase_id, ()):
            totals[test_id] = totals.get(test_id, 0) + 1
    return totals




def _vocabulary_queue_counts(rows, now, *, revisit_total) -> dict:
    """The queue numbers a vocabulary deck row renders, from its own rows.

    ``new_done_today`` and ``reviews_done_today`` are the only members of
    :func:`queue_counts` left out: they need today's review log matched against
    the deck, and no directory row shows them.
    """
    learning_due = 0
    review_due = 0
    new_total = 0
    for row in rows:
        state = row["state"]
        if state == CardState.NEW:
            new_total += 1
            continue
        if row["due"] is None or row["due"] > now:
            continue
        if state in (CardState.LEARNING, CardState.RELEARNING):
            learning_due += 1
        elif state == CardState.REVIEW:
            review_due += 1
    due_reviews = learning_due + review_due
    return {
        "due_reviews": due_reviews,
        "learning_due": learning_due,
        "review_due": review_due,
        "review_due_total": review_due,
        "new_available": new_total,
        "new_total": new_total,
        "total_due": due_reviews + new_total,
        "scoped_total": len(rows),
        "revisit_total": revisit_total,
    }


def phrases(
    request,
    part_slug=None,
    task_slug=None,
    category_slug=None,
    vocabulary_theme_slug=None,
    comprehension_mode=None,
    test_slug=None,
):
    legacy_scope_keys = {"part", "task", "domain", "mode", "category", "test"}
    if legacy_scope_keys.intersection(request.GET):
        raise Http404
    if bool(part_slug) != bool(task_slug):
        raise Http404
    if comprehension_mode not in {
        None,
        ComprehensionMode.ECRITE,
        ComprehensionMode.ORALE,
    }:
        raise Http404
    if comprehension_mode and (
        task_slug or category_slug or vocabulary_theme_slug
    ):
        raise Http404
    if test_slug and not comprehension_mode:
        raise Http404
    if not any(
        (
            part_slug,
            category_slug,
            vocabulary_theme_slug,
            comprehension_mode,
            test_slug,
        )
    ):
        return redirect("study:dashboard")
    if category_slug and not task_slug:
        category = get_object_or_404(
            PhraseCategory,
            slug=category_slug,
            is_active=True,
        )
        source_prompt = (
            Prompt.objects.filter(
                is_active=True,
                theme__is_active=True,
                theme__task__is_active=True,
                phrases__is_active=True,
                phrases__tier=PhraseTier.SHARED,
                phrases__category=category,
            )
            .select_related("theme__task__part")
            .order_by("theme__task__part__order", "theme__task__order", "pk")
            .first()
        )
        if source_prompt is None:
            return redirect("study:dashboard")
        return redirect(
            vocabulary_url(
                task=source_prompt.theme.task,
                category=category,
            )
        )
    task = (
        _route_task(part_slug, task_slug, request=request)
        if part_slug and task_slug
        else None
    )
    if task and not task.available:
        return render(
            request,
            "study/coming_soon.html",
            {"part": task.part, "task": task},
        )
    if task and (
        task.part.slug,
        task.slug,
    ) == content_module.QUESTION_BANK_TASK:
        return redirect("study:tache_two_theme_vocabulary")
    if vocabulary_theme_slug and task is None:
        raise Http404
    if vocabulary_theme_slug and category_slug:
        raise Http404
    vocabulary_theme = (
        get_object_or_404(
            Theme,
            task=task,
            slug=vocabulary_theme_slug,
            is_active=True,
        )
        if vocabulary_theme_slug
        else None
    )
    writing_tache = _ee_writing_tache(task) if task else None
    if (
        task
        and writing_tache is not None
        and category_slug is None
        and test_slug is None
    ):
        if vocabulary_theme is not None:
            return _ee_writing_theme_vocabulary_detail(
                request,
                task,
                vocabulary_theme,
                writing_tache,
            )
        return _ee_writing_theme_vocabulary_directory(
            request,
            task,
            writing_tache,
        )
    if (
        task
        and (task.part.slug, task.slug)
        == content_module.EE_TACHE_THREE_TASK
        and category_slug is None
        and test_slug is None
    ):
        if vocabulary_theme is not None:
            return _ee_tache_three_vocabulary_theme_detail(
                request,
                task,
                vocabulary_theme,
            )
        return _ee_tache_three_vocabulary_directory(request, task)
    if (
        task
        and (task.part.slug, task.slug)
        == content_module.EO_TACHE_THREE_TASK
        and category_slug is None
        and test_slug is None
    ):
        if vocabulary_theme is not None:
            return _eo_tache_three_theme_vocabulary_detail(
                request,
                task,
                vocabulary_theme,
            )
        return _eo_tache_three_theme_vocabulary_directory(request, task)
    functional_names = FUNCTIONAL_PHRASE_CATEGORY_NAMES
    category_descriptions = {
        "Structurer et prendre position": (
            "Reformuler le sujet, annoncer ton avis et guider clairement "
            "l'examinateur."
        ),
        "Nuancer et comparer": (
            "Éviter les réponses trop absolues et confronter plusieurs "
            "points de vue."
        ),
        "Cause, conséquence et évaluation": (
            "Expliquer pourquoi, montrer les effets et porter un jugement "
            "précis."
        ),
        "Schémas d'argumentation": (
            "Construire des arguments complets avec des tournures "
            "réutilisables."
        ),
    }
    if category_slug and test_slug:
        raise Http404
    selected = None
    selected_test = None
    all_phrases = (
        Phrase.objects.filter(
            is_active=True,
            tier=PhraseTier.SHARED,
        )
        .select_related("category")
        .prefetch_related(
            "source_prompts__theme__task__part",
            "source_questions__test",
        )
    )
    if task:
        all_phrases = all_phrases.filter(
            source_prompts__theme__task=task
        ).distinct()
    categories = list(
        PhraseCategory.objects.filter(
            is_active=True,
            phrases__in=all_phrases
        ).distinct().order_by("order")
    )
    phrase_scope = {"kind": "phrase"}
    if task:
        phrase_scope.update({"part": task.part.slug, "task": task.slug})
    category_card_counts = dict(
        queue_module.scoped_cards(
            phrase_scope,
            user=request.user,
            include_suspended=True,
        )
        .order_by()
        .values("phrase__category_id")
        .annotate(total=Count("id", distinct=True))
        .values_list("phrase__category_id", "total")
    )
    # One grouped count for every category instead of a count per category.
    category_phrase_counts = dict(
        all_phrases.select_related(None)
        .prefetch_related(None)
        .order_by()
        .values("category_id")
        .annotate(total=Count("pk", distinct=True))
        .values_list("category_id", "total")
    )
    functional_categories = [
        category
        for category in categories
        if category.name in functional_names
    ]
    # The stable lots of the functional categories only feed the page a learner
    # opened one of them on: everywhere else they are four scans of the shared
    # phrase deck whose result is never rendered. When they are needed, one
    # ordered fetch covers every category at once.
    functional_batches = (
        _category_review_batches(
            phrase_scope,
            request.user,
            functional_categories,
        )
        if category_slug and functional_categories
        else {}
    )
    for category in categories:
        category.phrase_count = category_phrase_counts.get(category.id, 0)
        category.card_count = category_card_counts.get(category.id, 0)
        category.batch_count = (
            category.phrase_count + queue_module.PHRASE_BATCH_SIZE - 1
        ) // queue_module.PHRASE_BATCH_SIZE
        category.is_functional = category.name in functional_names
        category.learning_description = category_descriptions.get(
            category.name,
            "Expressions réutilisables dans plusieurs réponses.",
        )
        category.url = vocabulary_url(task=task, category=category)
        if category.id in functional_batches:
            category.review_batches = functional_batches[category.id]
            category.progress = summarize_review_batches(
                category.review_batches
            )
            category.completed_batch_count = category.progress.completed

    phrase_qs = all_phrases.none()
    if category_slug:
        selected = next(
            (
                category
                for category in categories
                if category.slug == category_slug
            ),
            None,
        )
        if selected is None:
            raise Http404
        phrase_qs = all_phrases.filter(category=selected)
    elif test_slug:
        selected_test = get_object_or_404(
            ComprehensionTest,
            slug=test_slug,
            mode=comprehension_mode,
            is_active=True,
            is_published=True,
        )
        phrase_qs = (
            Phrase.objects.filter(
                is_active=True,
                tier=PhraseTier.COMPREHENSION,
                source_questions__test=selected_test,
                source_questions__is_active=True,
            )
            .select_related("category")
            .prefetch_related(
                "source_questions__test",
                # The catalogue prints the prompts an entry comes from, so
                # they are fetched with the page rather than one query per
                # entry as the template walked the list.
                "source_prompts__theme__task__part",
            )
            .distinct()
            .order_by("category__order", "lot_order", "phrase_id")
        )

    grouped = []
    review_batches = []
    first_review_batch = None
    selected_test_phrase_count = 0
    if selected:
        grouped.append(
            {
                "category": selected,
                "phrases": list(phrase_qs),
            }
        )
        review_batches = getattr(selected, "review_batches", None)
        if review_batches is None:
            review_batches = _review_batches(
                {**phrase_scope, "category": selected.slug},
                request.user,
            )
        first_review_batch = next(
            (batch for batch in review_batches if batch["can_review"]),
            None,
        )
    elif selected_test:
        # The entries arrive already ordered by category, so grouping the one
        # fetched list beats re-querying it once per category.
        test_phrases = list(phrase_qs)
        phrases_by_category = {}
        for phrase in test_phrases:
            phrases_by_category.setdefault(phrase.category_id, []).append(
                phrase
            )
        for category in PhraseCategory.objects.filter(
            pk__in=phrases_by_category,
            is_active=True,
        ).order_by("order"):
            grouped.append(
                {
                    "category": category,
                    "phrases": phrases_by_category[category.pk],
                }
            )
        selected_test_phrase_count = len(test_phrases)
        review_batches = _review_batches(
            {"kind": "vocab", "test": selected_test.slug},
            request.user,
        )
        first_review_batch = next(
            (batch for batch in review_batches if batch["can_review"]),
            review_batches[0] if review_batches else None,
        )

    collection_progress = (
        summarize_review_batches(review_batches)
        if review_batches
        else None
    )
    comprehension_directory = comprehension_mode is not None
    subject_context = {
        "subject_theme_groups": [],
        "subject_prompt_count": 0,
        "subject_response_count": 0,
        "subject_vocabulary_count": 0,
        "vocabulary_deck_summary": progress_summary(
            total=0,
            started=0,
            completed=0,
        ),
    }
    comprehension_decks = []
    comprehension_vocabulary_count = 0
    comprehension_batch_count = 0
    if (
        task
        and not selected
        and not selected_test
        and not comprehension_directory
    ):
        subject_context = _task_subject_vocabulary_context(
            task,
            request.user,
            vocabulary_theme,
        )

    if comprehension_directory:
        tests = (
            ComprehensionTest.objects.filter(
                is_active=True,
                is_published=True,
            )
            .annotate(
                vocabulary_count=Count(
                    "questions__vocabulary",
                    filter=Q(
                        questions__vocabulary__is_active=True,
                        questions__vocabulary__tier=PhraseTier.COMPREHENSION,
                    ),
                    distinct=True,
                )
            )
            .filter(vocabulary_count__gt=0)
            .order_by("mode", "number")
        )
        if comprehension_mode:
            tests = tests.filter(mode=comprehension_mode)
        tests = list(tests)
        comprehension_decks = _comprehension_vocabulary_decks(
            tests,
            request.user,
            timezone.now(),
        )
        comprehension_vocabulary_count = sum(
            deck["vocabulary_count"] for deck in comprehension_decks
        )
        comprehension_batch_count = sum(
            deck["batch_count"] for deck in comprehension_decks
        )
    vocabulary_stats = None
    vocabulary_counts = None
    vocabulary_revisit_count = 0
    vocabulary_weak_count = 0
    vocabulary_review_url = ""
    vocabulary_revisit_url = ""
    vocabulary_weak_url = ""
    if task:
        vocabulary_scope = {
            **_task_scope(task),
            "content": "vocabulary",
        }
        if not selected:
            vocabulary_scope = {
                **_task_scope(task),
                "kind": "vocab",
            }
            if vocabulary_theme:
                vocabulary_scope["theme"] = vocabulary_theme.slug
        # The vocabulary pages link to the review, revisit and weak queues but
        # never print their sizes, so only the links are built here. Counting
        # them meant eight scans of the learner's vocabulary deck — including
        # the weak query, which joins the whole review log — for numbers no
        # template reads.
        vocabulary_review_url = review_url(vocabulary_scope)
        vocabulary_revisit_url = (
            reverse(
                "study:task_revisit_list",
                args=[task.part.slug, task.slug],
            )
            + "?content=vocabulary"
        )
        vocabulary_weak_url = review_url(
            {
                **vocabulary_scope,
                "kind": "weak",
            }
        )
    selected_review_url = ""
    if selected_test:
        selected_review_url = review_url(
            {"kind": "vocab", "test": selected_test.slug}
        )
    elif selected:
        selected_review_url = review_url(
            {**phrase_scope, "category": selected.slug}
        )
    vocabulary_root_url = (
        comprehension_vocabulary_url(mode=selected_test.mode)
        if selected_test
        else vocabulary_url(task=task)
    )

    template_name = "study/phrases.html"
    if task and not selected:
        template_name = (
            "study/task_vocabulary_theme.html"
            if vocabulary_theme
            else "study/task_vocabulary.html"
        )
    return render(
        request,
        template_name,
        {
            "part": task.part if task else None,
            "task": task,
            "categories": categories,
            "functional_categories": functional_categories,
            "comprehension_directory": comprehension_directory,
            "comprehension_mode": comprehension_mode,
            "comprehension_skill_code": (
                comprehension_skill(comprehension_mode)
                if comprehension_mode
                else ""
            ),
            "functional_phrase_count": sum(
                category.phrase_count
                for category in functional_categories
            ),
            "first_category": (
                functional_categories[0]
                if functional_categories
                else None
            ),
            **subject_context,
            "vocabulary_theme": vocabulary_theme,
            "vocabulary_theme_group": (
                subject_context["subject_theme_groups"][0]
                if vocabulary_theme
                and subject_context["subject_theme_groups"]
                else None
            ),
            "comprehension_decks": comprehension_decks,
            "comprehension_vocabulary_count": (
                comprehension_vocabulary_count
            ),
            "comprehension_batch_count": comprehension_batch_count,
            "vocabulary_stats": vocabulary_stats,
            "vocabulary_counts": vocabulary_counts,
            "vocabulary_revisit_count": vocabulary_revisit_count,
            "vocabulary_weak_count": vocabulary_weak_count,
            "vocabulary_review_url": vocabulary_review_url,
            "vocabulary_revisit_url": vocabulary_revisit_url,
            "vocabulary_weak_url": vocabulary_weak_url,
            "grouped": grouped,
            "review_batches": review_batches,
            "collection_progress": collection_progress,
            "first_review_batch": first_review_batch,
            "batch_size": queue_module.PHRASE_BATCH_SIZE,
            "selected": selected,
            "selected_test": selected_test,
            "selected_review_url": selected_review_url,
            "vocabulary_root_url": vocabulary_root_url,
            "phrase_count": (
                selected.phrase_count
                if selected
                else (
                    selected_test_phrase_count
                    if selected_test
                    else sum(
                    category.phrase_count
                    for category in functional_categories
                    )
                )
            ),
        },
    )


def search(request, part_slug=None, task_slug=None):
    if "part" in request.GET or "task" in request.GET:
        raise Http404
    if bool(part_slug) != bool(task_slug):
        raise Http404
    task = (
        _route_task(part_slug, task_slug, request=request)
        if part_slug and task_slug
        else None
    )
    query = request.GET.get("q", "").strip()
    subjects_only = request.GET.get("scope") == "subjects"
    prompt_results = []
    writing_sujet_results = []
    phrase_results = []
    comprehension_results = []
    prompt_result_count = 0
    writing_sujet_result_count = 0
    phrase_result_count = 0
    comprehension_result_count = 0
    result_limit = 12
    if query:
        prompt_query = Q(text__icontains=query)
        if not subjects_only:
            prompt_query |= Q(response__body__icontains=query)
        prompt_qs = Prompt.objects.filter(is_active=True).filter(prompt_query)
        phrase_qs = Phrase.objects.filter(
            Q(is_active=True),
            Q(expression__icontains=query)
            | Q(english_cue__icontains=query)
            | Q(example__icontains=query)
            | Q(note__icontains=query)
        )
        if task:
            prompt_qs = prompt_qs.filter(theme__task=task)
            phrase_qs = phrase_qs.filter(
                source_prompts__theme__task=task
            ).distinct()
        prompt_result_count = prompt_qs.count()
        if not subjects_only:
            phrase_result_count = _distinct_count(phrase_qs)
        prompt_results = list(
            prompt_qs
            .select_related("response", "theme__task__part", "family")
            .order_by("theme__order", "number")[:result_limit]
        )
        prompt_progress = subject_progress_by_response(
            request.user,
            {prompt.response_id for prompt in prompt_results},
        )
        for prompt in prompt_results:
            prompt.subject_progress = prompt_progress[prompt.response_id]
        if subjects_only:
            writing_sujet_qs = WritingSujet.objects.filter(
                is_active=True,
                prompt__icontains=query,
            )
            if task:
                writing_sujet_qs = writing_sujet_qs.filter(task=task)
            writing_sujet_result_count = writing_sujet_qs.count()
            writing_sujet_results = list(
                writing_sujet_qs.select_related("task__part").order_by(
                    "order",
                    "id",
                )[:result_limit]
            )
            writing_progress = writing_sujet_progress_by_id(
                request.user,
                (sujet.pk for sujet in writing_sujet_results),
            )
            for sujet in writing_sujet_results:
                sujet.subject_progress = writing_progress[sujet.pk]
        else:
            phrase_results = list(
                phrase_qs
                .select_related("category")
                .order_by("order")[:result_limit]
            )
        if not task and not subjects_only:
            comprehension_qs = (
                ComprehensionQuestion.objects.filter(
                    test__is_active=True,
                    test__is_published=True,
                    is_active=True,
                )
                .filter(
                    Q(passage_fr__icontains=query)
                    | Q(prompt_fr__icontains=query)
                    | Q(passage_en__icontains=query)
                    | Q(prompt_en__icontains=query)
                    | Q(choices__text_fr__icontains=query)
                    | Q(choices__text_en__icontains=query)
                )
                .select_related("test")
                .distinct()
                .order_by("test__number", "number")
            )
            comprehension_result_count = comprehension_qs.count()
            comprehension_results = list(
                comprehension_qs[:result_limit]
            )
    subject_result_count = prompt_result_count + writing_sujet_result_count
    result_count = (
        subject_result_count
        + phrase_result_count
        + comprehension_result_count
    )
    visible_result_count = (
        len(prompt_results)
        + len(writing_sujet_results)
        + len(phrase_results)
        + len(comprehension_results)
    )
    prompt_total_qs = Prompt.objects.filter(is_active=True)
    if task:
        prompt_total_qs = prompt_total_qs.filter(theme__task=task)
    prompt_total = prompt_total_qs.count()
    if subjects_only:
        writing_sujet_total_qs = WritingSujet.objects.filter(is_active=True)
        if task:
            writing_sujet_total_qs = writing_sujet_total_qs.filter(task=task)
        prompt_total += writing_sujet_total_qs.count()
    return render(
        request,
        "study/search.html",
        {
            "part": task.part if task else None,
            "task": task,
            "search_url": request.path,
            "query": query,
            "subjects_only": subjects_only,
            "prompt_results": prompt_results,
            "writing_sujet_results": writing_sujet_results,
            "phrase_results": phrase_results,
            "comprehension_results": comprehension_results,
            "prompt_result_count": prompt_result_count,
            "writing_sujet_result_count": writing_sujet_result_count,
            "subject_result_count": subject_result_count,
            "phrase_result_count": phrase_result_count,
            "comprehension_result_count": comprehension_result_count,
            "result_count": result_count,
            "visible_result_count": visible_result_count,
            "results_truncated": result_count > visible_result_count,
            "prompt_total": prompt_total,
            "phrase_total": (
                _task_phrases(task).count()
                if task
                else Phrase.objects.filter(is_active=True).count()
            ),
        },
    )


def _stats_scope_cards(scope, user):
    cards = Card.objects.current_content().filter(user=user)
    if not scope:
        return cards

    response_ids = queue_module.scoped_cards(
        {**scope, "content": "spine"},
        user=user,
        include_suspended=True,
    ).values("pk")
    vocabulary_ids = queue_module.scoped_cards(
        {**scope, "content": "vocabulary"},
        user=user,
        include_suspended=True,
    ).values("pk")
    return cards.filter(
        Q(pk__in=response_ids) | Q(pk__in=vocabulary_ids)
    ).distinct()


def _activity_streak(active_days, today):
    """Consecutive-day streak (ending today or yesterday) from a set of dates."""
    if not active_days:
        return 0
    cursor = today
    if cursor not in active_days:
        cursor = today - timezone.timedelta(days=1)
        if cursor not in active_days:
            return 0
    streak = 0
    while cursor in active_days:
        streak += 1
        cursor -= timezone.timedelta(days=1)
    return streak


def _learning_activity(scope, user, scoped_cards, logs_base, now):
    """Every learning action, not only flashcard reviews.

    Returns a per-day activity map (last 365 days), the set of active days,
    an all-time per-type breakdown and the grand total. Comprehension quizzes
    and mémoires live outside the EO/EE expression scope, so they only count
    in the global (unscoped) view.
    """
    part = scope.get("part")
    task = scope.get("task")
    since_year = now - timezone.timedelta(days=365)

    responses = PersonalResponse.objects.filter(user=user)
    notes = Annotation.objects.filter(user=user)
    if task:
        responses = responses.filter(
            response__theme__task__slug=task,
            response__theme__task__part__slug=part,
        )
        notes = notes.filter(task__slug=task, task__part__slug=part)
    elif part:
        responses = responses.filter(response__theme__task__part__slug=part)
        notes = notes.filter(task__part__slug=part)

    sources = [
        ("reviews", "Révisions", logs_base, "reviewed_at"),
        (
            "subjects",
            "Sujets terminés",
            scoped_cards.filter(subject_completed_at__isnull=False),
            "subject_completed_at",
        ),
        ("responses", "Réponses rédigées", responses, "updated_at"),
        ("notes", "Notes & surlignages", notes, "created_at"),
    ]
    if not scope:
        sources.append(
            (
                "comprehension",
                "Quiz de compréhension",
                ComprehensionAttempt.objects.filter(
                    user=user, completed_at__isnull=False
                ),
                "completed_at",
            )
        )
        sources.append(
            (
                "memories",
                "Mémoires apprises",
                MemoryQuestionProgress.objects.filter(user=user),
                "completed_at",
            )
        )

    per_day: dict = {}
    active_days: set = set()
    breakdown = []
    for key, label, qs, field in sources:
        # One grouped pass per source: the database folds the year's activity
        # into a row per local day and reports the all-time total alongside it,
        # instead of a COUNT plus every single timestamp of the last year.
        total = 0
        for row in (
            qs.annotate(activity_day=TruncDate(field))
            .order_by()
            .values("activity_day")
            .annotate(
                all_time=Count("id", distinct=True),
                recent=Count(
                    "id",
                    distinct=True,
                    filter=Q(**{f"{field}__gte": since_year}),
                ),
            )
        ):
            total += row["all_time"]
            day = row["activity_day"]
            if day is None or not row["recent"]:
                continue
            per_day[day] = per_day.get(day, 0) + row["recent"]
            active_days.add(day)
        breakdown.append({"key": key, "label": label, "count": total})

    return {
        "per_day": per_day,
        "active_days": active_days,
        "breakdown": breakdown,
        "total_activity": sum(item["count"] for item in breakdown),
    }


def stats(request, part_slug=None, task_slug=None):
    now = timezone.now()
    today = timezone.localtime(now).date()
    if bool(task_slug) and not part_slug:
        raise Http404
    forced_task = (
        _route_task(part_slug, task_slug, request=request)
        if part_slug is not None and task_slug is not None
        else None
    )
    filters = _scope_filters(
        request,
        forced_task,
        forced_part_slug=part_slug if forced_task is None else None,
    )
    scope = filters["scope"]

    scoped_history_cards = _stats_scope_cards(scope, request.user)
    active_cards = scoped_history_cards.filter(suspended=False)
    logs_base = ReviewLog.objects.filter(user=request.user)
    if scope:
        logs_base = logs_base.filter(
            card_id__in=scoped_history_cards.values("pk")
        )

    activity = _learning_activity(
        scope, request.user, scoped_history_cards, logs_base, now
    )
    per_day = activity["per_day"]

    daily = []
    for offset in range(29, -1, -1):
        day = today - timezone.timedelta(days=offset)
        daily.append({"date": day, "count": per_day.get(day, 0)})
    max_daily = max((d["count"] for d in daily), default=0) or 1
    activity_30_days = sum(d["count"] for d in daily)

    heat = []
    for offset in range(89, -1, -1):
        day = today - timezone.timedelta(days=offset)
        count = per_day.get(day, 0)
        level = min(4, 1 + count // 15) if count else 0
        heat.append({"date": day, "count": count, "level": level})

    mature_logs = logs_base.filter(
        reviewed_at__gte=now - timezone.timedelta(days=30),
        interval_before__gte=MATURE_DAYS,
    )
    mature_counts = mature_logs.aggregate(
        total=Count("id"),
        passed=Count("id", filter=~Q(rating=Rating.AGAIN)),
    )
    mature_total = mature_counts["total"]
    mature_pass = mature_counts["passed"]
    retention = round(100 * mature_pass / mature_total) if mature_total else None

    forecast = []
    active = active_cards.filter(
        state__in=[CardState.REVIEW, CardState.LEARNING, CardState.RELEARNING]
    )
    # One pass over the scheduled cards instead of a count per day: the scoped
    # queryset is a DISTINCT join, so fourteen counts meant fourteen scans.
    forecast_days = [
        today + timezone.timedelta(days=offset) for offset in range(0, 14)
    ]
    day_bounds = [
        timezone.make_aware(
            timezone.datetime.combine(day, timezone.datetime.min.time())
        )
        for day in forecast_days
    ]
    forecast_counts = queue_module.narrow(active).aggregate(
        **{
            f"day_{offset}": Count(
                "id",
                distinct=True,
                filter=(
                    Q(due__lt=day_bounds[offset] + timezone.timedelta(days=1))
                    if offset == 0
                    else Q(
                        due__gte=day_bounds[offset],
                        due__lt=day_bounds[offset]
                        + timezone.timedelta(days=1),
                    )
                ),
            )
            for offset in range(len(forecast_days))
        }
    )
    forecast = [
        {"date": day, "count": forecast_counts[f"day_{offset}"]}
        for offset, day in enumerate(forecast_days)
    ]
    max_forecast = max((f["count"] for f in forecast), default=0) or 1

    overall = deck_stats(active_cards, now)
    mastery_percentage = (
        round(100 * overall["mature"] / overall["total"])
        if overall["total"]
        else 0
    )

    theme_qs = Theme.objects.select_related("task__part").filter(
        is_active=True,
        task__isnull=False,
    )
    if scope.get("task"):
        theme_qs = theme_qs.filter(
            task__slug=scope["task"],
            task__part__slug=scope["part"],
        )
    elif scope.get("part"):
        theme_qs = theme_qs.filter(task__part__slug=scope["part"])
    theme_rows = list(theme_qs)
    # One grouped aggregate for every theme on the page: a response card always
    # targets one response, so grouping the learner's response cards by that
    # response's theme selects exactly the cards the per-theme filter did.
    theme_stats_by_theme = grouped_deck_stats(
        Card.objects.active().filter(
            user=request.user,
            card_type=CardType.SPINE,
            response__theme_id__in=[theme.pk for theme in theme_rows],
        ),
        "response__theme_id",
        now,
    )
    themes = [
        {
            "theme": theme,
            "stats": theme_stats_by_theme.get(theme.pk, empty_deck_stats()),
            "review_url": review_url(
                {
                    "kind": "spine",
                    "part": theme.task.part.slug,
                    "task": theme.task.slug,
                    "theme": theme.slug,
                }
            ),
        }
        for theme in theme_rows
    ]

    context = {
        "daily": daily,
        "max_daily": max_daily,
        "activity_30_days": activity_30_days,
        "heat": heat,
        "activity_90_days": sum(cell["count"] for cell in heat),
        "retention": retention,
        "mature_total": mature_total,
        "forecast": forecast,
        "max_forecast": max_forecast,
        "forecast_total": sum(item["count"] for item in forecast),
        "overall": overall,
        "mastery_percentage": mastery_percentage,
        "themes": themes,
        "streak": _activity_streak(activity["active_days"], today),
        # The activity breakdown already counted this learner's reviews for the
        # same scope, so the header reuses it instead of counting them again.
        "total_reviews": next(
            item["count"]
            for item in activity["breakdown"]
            if item["key"] == "reviews"
        ),
        "total_activity": activity["total_activity"],
        "breakdown": activity["breakdown"],
        "activity_today": per_day.get(today, 0),
        "recent_sessions": recent_review_sessions(logs_base),
        # Only the weak totals are shown, so count those cards directly rather
        # than running the whole queue summary, which also scans today's
        # reviews and the revisit list for scopes that never render them.
        "expression_weak_count": queue_module.scoped_count(
            queue_module.scoped_cards(
                {**scope, "kind": "weak", "content": "spine"},
                user=request.user,
            )
        ),
        "vocabulary_weak_count": queue_module.scoped_count(
            queue_module.scoped_cards(
                {
                    **scope,
                    "kind": "weak",
                    "content": "vocabulary",
                },
                user=request.user,
            )
        ),
        "expression_weak_url": review_url(
            {**scope, "kind": "weak", "content": "spine"}
        ),
        "vocabulary_weak_url": review_url(
            {**scope, "kind": "weak", "content": "vocabulary"}
        ),
        **filters,
    }
    return render(request, "study/stats.html", context)
