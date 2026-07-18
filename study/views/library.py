"""Content browsing, phrase library, detail pages, and stats."""

from __future__ import annotations


from django.db.models import Count, Prefetch, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .. import queue as queue_module
from ..cards import scope_label
from ..forms import (
    PersonalResponseForm,
)
from ..models import (
    Card,
    CardState,
    CardType,
    ComprehensionMode,
    ComprehensionQuestion,
    ComprehensionTest,
    ExamPart,
    Family,
    Phrase,
    PhraseCategory,
    PhraseTier,
    PersonalResponse,
    Prompt,
    Rating,
    Response,
    ReviewLog,
    Task,
    Theme,
)
from ..personalization import effective_response
from ..progress import mark_response_started

from .common import (
    FUNCTIONAL_PHRASE_CATEGORY_NAMES,
    MATURE_DAYS,
    _review_batches,
    _route_task,
    _task_card,
    _task_cards,
    _task_phrases,
    _task_scope,
    current_streak,
    deck_stats,
    recent_review_sessions,
)
from .dashboard import _vocabulary_expression_paths

def _spine_theme_stats(theme, now, user):
    return deck_stats(
        Card.objects.active().filter(
            user=user,
            card_type=CardType.SPINE, response__theme=theme
        ),
        now,
    )


def _phrase_deck_stats(now, user=None, task=None):
    cards = (
        _task_cards(task, user, "phrase")
        if task
        else queue_module.scoped_cards({"kind": "phrase"}, user=user)
    )
    return deck_stats(cards, now)


def part_detail(request, part_slug):
    part = get_object_or_404(
        ExamPart.objects.filter(is_active=True).prefetch_related(
            Prefetch("tasks", queryset=Task.objects.filter(is_active=True))
        ),
        slug=part_slug,
    )
    now = timezone.now()
    tasks = [
        _task_card(task, now, request.user)
        for task in part.tasks.all()
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


def task_detail(request, part_slug, task_slug):
    task = get_object_or_404(
        Task.objects.select_related("part"),
        slug=task_slug,
        part__slug=part_slug,
        is_active=True,
        part__is_active=True,
    )
    now = timezone.now()
    if not task.available:
        return render(
            request,
            "study/coming_soon.html",
            {"part": task.part, "task": task},
        )

    themes = []
    for theme in Theme.objects.filter(task=task, is_active=True):
        themes.append(
            {
                "theme": theme,
                "stats": _spine_theme_stats(theme, now, request.user),
                "prompt_count": Prompt.objects.filter(
                    theme=theme,
                    is_active=True,
                ).count(),
            }
        )
    scope = _task_scope(task)
    task_stats = deck_stats(_task_cards(task, request.user), now)
    response_stats = deck_stats(
        _task_cards(task, request.user, "spine"),
        now,
    )
    phrase_stats = _phrase_deck_stats(now, request.user, task)
    context = {
        "part": task.part,
        "task": task,
        "themes": themes,
        "stats": task_stats,
        "response_stats": response_stats,
        "phrase_stats": phrase_stats,
        "counts": queue_module.queue_counts(
            {**scope, "kind": "spine"},
            now,
            user=request.user,
        ),
        "prompt_count": Prompt.objects.filter(
            theme__task=task,
            is_active=True,
        ).count(),
        "phrase_count": _task_phrases(task).count(),
        "phrase_category_count": _task_phrases(task)
        .values("category_id")
        .distinct()
        .count(),
    }
    return render(request, "study/task_detail.html", context)


def _scope_filters(request, forced_task=None):
    """Shared part/task filter context for Browse and Stats.

    Parses ``?part=`` / ``?task=`` (a task implies its part), builds the chip
    data with per-part/task card counts, and returns the effective scope so the
    page can offer a scoped review.
    """
    part_slug = (request.GET.get("part") or "").strip()
    task_slug = (request.GET.get("task") or "").strip()
    selected_task = forced_task
    if forced_task:
        part_slug = forced_task.part.slug
        task_slug = forced_task.slug

    if task_slug and not forced_task:
        task_qs = Task.objects.select_related("part").filter(
            slug=task_slug,
            is_active=True,
            part__is_active=True,
        )
        if part_slug:
            task_qs = task_qs.filter(part__slug=part_slug)
        selected_task = task_qs.first()
        if selected_task:
            part_slug = selected_task.part.slug
        else:
            task_slug = ""

    active = Card.objects.active().filter(
        user=request.user,
        card_type=CardType.SPINE,
    )
    filter_parts = []
    active_part_tasks = []
    for part in ExamPart.objects.filter(is_active=True).prefetch_related(
        Prefetch("tasks", queryset=Task.objects.filter(is_active=True))
    ):
        filter_parts.append(
            {
                "slug": part.slug,
                "short_name": part.short_name,
                "count": active.filter(response__theme__task__part=part).count(),
                "active": part_slug == part.slug,
            }
        )
        if part_slug == part.slug:
            for task in part.tasks.all():
                active_part_tasks.append(
                    {
                        "slug": task.slug,
                        "name": task.name,
                        "count": active.filter(response__theme__task=task).count(),
                        "active": task_slug == task.slug,
                    }
                )

    if task_slug:
        scope = {"part": part_slug, "task": task_slug}
        review_qs = f"part={part_slug}&task={task_slug}"
    elif part_slug:
        scope = {"part": part_slug}
        review_qs = f"part={part_slug}"
    else:
        scope = {}
        review_qs = ""

    return {
        "filter_base": request.path,
        "filter_parts": filter_parts,
        "active_part": part_slug,
        "active_task": task_slug,
        "active_part_tasks": active_part_tasks,
        "review_scope_qs": review_qs,
        "scope_label": scope_label(scope),
        "scope": scope,
        "task": selected_task,
        "part": selected_task.part if selected_task else None,
        "task_locked": forced_task is not None,
    }


def browse(request, part_slug=None, task_slug=None):
    now = timezone.now()
    forced_task = (
        _route_task(part_slug, task_slug)
        if part_slug is not None and task_slug is not None
        else None
    )
    if forced_task and not forced_task.available:
        return render(
            request,
            "study/coming_soon.html",
            {"part": forced_task.part, "task": forced_task},
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

    themes = []
    for theme in theme_qs:
        stats = deck_stats(
            Card.objects.active().filter(
                user=request.user,
                card_type=CardType.SPINE, response__theme=theme
            ),
            now,
        )
        themes.append(
            {
                "theme": theme,
                "stats": stats,
                "prompt_count": Prompt.objects.filter(
                    theme=theme,
                    is_active=True,
                ).count(),
            }
        )
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
    families = family_qs.annotate(
        n=Count(
            "prompts",
            filter=Q(prompts__is_active=True),
            distinct=True,
        )
    ).order_by("order")
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
        "phrase_count": phrase_qs.count(),
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


def theme_detail(request, slug):
    theme = get_object_or_404(
        Theme.objects.select_related("task__part"),
        slug=slug,
        is_active=True,
    )
    now = timezone.now()
    prompts = list(
        Prompt.objects.filter(theme=theme, is_active=True)
        .select_related("response", "response__theme", "family")
        .order_by("number")
    )
    canonical_numbers = _canonical_numbers_by_response(
        prompt.response_id for prompt in prompts
    )
    spine_cards = {
        card.response_id: card
        for card in Card.objects.filter(
            user=request.user,
            card_type=CardType.SPINE, response__theme=theme
        )
    }
    rows = [
        {
            "prompt": prompt,
            "card": spine_cards.get(prompt.response_id),
            "is_alias": not prompt.is_canonical,
            "canonical_number": canonical_numbers.get(prompt.response_id),
        }
        for prompt in prompts
    ]
    stats = deck_stats(
        Card.objects.active().filter(
            user=request.user,
            card_type=CardType.SPINE, response__theme=theme
        ),
        now,
    )
    review_scope = {"kind": "spine", "theme": theme.slug}
    if theme.task:
        review_scope.update(
            {
                "part": theme.task.part.slug,
                "task": theme.task.slug,
            }
        )
    return render(
        request,
        "study/theme_detail.html",
        {
            "theme": theme,
            "task": theme.task,
            "part": theme.task.part if theme.task else None,
            "rows": rows,
            "stats": stats,
            "review_batches": _review_batches(review_scope, request.user),
        },
    )


def family_detail(
    request,
    slug,
    part_slug=None,
    task_slug=None,
):
    family = get_object_or_404(Family, slug=slug, is_active=True)
    task = (
        _route_task(part_slug, task_slug)
        if part_slug is not None and task_slug is not None
        else Task.objects.select_related("part")
        .filter(
            is_active=True,
            themes__is_active=True,
            themes__prompts__is_active=True,
            themes__prompts__family=family,
        )
        .distinct()
        .order_by("part__order", "order")
        .first()
    )
    prompt_qs = Prompt.objects.filter(family=family, is_active=True)
    if part_slug is not None and task_slug is not None:
        prompt_qs = prompt_qs.filter(theme__task=task)
    prompts = list(
        prompt_qs
        .select_related("response", "theme", "family")
        .order_by("theme__order", "number")
    )
    response_ids = [prompt.response_id for prompt in prompts]
    canonical_numbers = _canonical_numbers_by_response(response_ids)
    spine_cards = {
        card.response_id: card
        for card in Card.objects.filter(
            user=request.user,
            card_type=CardType.SPINE,
            response_id__in=response_ids,
        )
    }
    rows = [
        {
            "prompt": prompt,
            "card": spine_cards.get(prompt.response_id),
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
            "part": task.part if task else None,
            "rows": rows,
        },
    )


def response_detail(request, pk):
    response = get_object_or_404(
        Response.objects.select_related(
            "theme__task__part",
            "family",
        ),
        pk=pk,
    )
    response_content = effective_response(response, request.user)
    prompts = list(
        response.prompts.filter(
            is_active=True,
            theme__is_active=True,
        ).select_related(
            "theme__task__part",
            "family",
        )
    )
    prompt_id = (request.GET.get("prompt") or "").strip()
    if prompt_id:
        if not prompt_id.isdigit():
            return HttpResponseBadRequest("Invalid prompt.")
        selected_prompt = next(
            (prompt for prompt in prompts if prompt.pk == int(prompt_id)),
            None,
        )
        if selected_prompt is None:
            return HttpResponseBadRequest(
                "Prompt does not belong to this response."
            )
    else:
        selected_prompt = next(
            (prompt for prompt in prompts if prompt.is_canonical),
            prompts[0] if prompts else None,
        )
    if selected_prompt is None:
        return HttpResponseBadRequest("Response has no active prompt.")

    navigation_prompts = Prompt.objects.filter(
        is_active=True,
        theme__is_active=True,
        theme_id=selected_prompt.theme_id,
    ).select_related("theme")
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
    phrase_batches = _review_batches(
        {"kind": "phrase", "response": str(response.pk)},
        request.user,
    )
    subject_vocabulary = (
        Phrase.objects.filter(
            source_prompts__response=response,
            is_active=True,
            tier=PhraseTier.SUBJECT,
        )
        .distinct()
        .select_related("category")
        .order_by("lot_order", "phrase_id")
    )
    vocabulary_count = subject_vocabulary.count()
    vocabulary_batches = _review_batches(
        {"kind": "vocab", "response": str(response.pk)},
        request.user,
    )
    vocabulary_lot_labels = (
        "Mots clés",
        "Collocations",
        "Expressions et idiomes",
        "Tournures pour l'oral",
        "Phrases modèles",
    )
    for batch, label in zip(vocabulary_batches, vocabulary_lot_labels):
        batch["label"] = label
    first_vocabulary_batch = next(
        (batch for batch in vocabulary_batches if batch["can_review"]),
        vocabulary_batches[0] if vocabulary_batches else None,
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
            "task": selected_prompt.theme.task,
            "part": (
                selected_prompt.theme.task.part
                if selected_prompt.theme.task
                else None
            ),
            "response_content": response_content,
            "arguments": response_content.arguments,
            "prompts": prompts,
            "card": card,
            "related_phrases": related_phrases,
            "phrase_batches": phrase_batches,
            "subject_vocabulary": list(subject_vocabulary[:10]),
            "vocabulary_count": vocabulary_count,
            "vocabulary_batches": vocabulary_batches,
            "vocabulary_review_url": (
                first_vocabulary_batch["review_url"]
                if first_vocabulary_batch
                else None
            ),
            "can_edit_response": response.prompts.filter(
                is_active=True,
                theme__task__slug="tache-3",
                theme__task__part__slug="eo",
            ).exists(),
            "personal_saved": request.GET.get("saved") == "1",
            "personal_reset": request.GET.get("reset") == "1",
        },
    )


def edit_response(request, pk):
    response = get_object_or_404(
        Response.objects.filter(
            is_active=True,
            prompts__is_active=True,
            prompts__theme__task__slug="tache-3",
            prompts__theme__task__part__slug="eo",
        )
        .select_related("theme__task__part", "family")
        .prefetch_related("arguments")
        .distinct(),
        pk=pk,
    )
    personal = PersonalResponse.objects.filter(
        user=request.user,
        response=response,
    ).first()
    if request.method == "POST" and request.POST.get("action") == "reset":
        if personal is not None:
            personal.delete()
        return redirect(
            reverse("study:response_detail", args=[response.pk]) + "?reset=1"
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
        mark_response_started(request.user, {response.pk})
        return redirect(
            reverse("study:response_detail", args=[response.pk]) + "?saved=1"
        )

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
            "task": response.theme.task,
            "part": response.theme.task.part,
            "form": form,
            "argument_fields": argument_fields,
            "has_personal_response": personal is not None,
        },
    )


def phrases(request, part_slug=None, task_slug=None):
    part_slug = part_slug or (request.GET.get("part") or "").strip()
    task_slug = task_slug or (request.GET.get("task") or "").strip()
    vocabulary_domain = (request.GET.get("domain") or "").strip()
    vocabulary_mode = (request.GET.get("mode") or "").strip()
    if bool(part_slug) != bool(task_slug):
        return HttpResponseBadRequest("Choose both a part and a task.")
    if vocabulary_domain not in {"", "comprehension"}:
        return HttpResponseBadRequest("Unknown vocabulary domain.")
    if vocabulary_mode not in {"", "ce"}:
        return HttpResponseBadRequest("Unknown vocabulary mode.")
    if vocabulary_mode and vocabulary_domain != "comprehension":
        return HttpResponseBadRequest(
            "A vocabulary mode requires a domain."
        )
    task = (
        _route_task(part_slug, task_slug)
        if part_slug and task_slug
        else None
    )
    if task and not task.available:
        return render(
            request,
            "study/coming_soon.html",
            {"part": task.part, "task": task},
        )
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
    category_slug = request.GET.get("category", "").strip()
    test_slug = request.GET.get("test", "").strip()
    if vocabulary_domain and (
        task or category_slug or test_slug
    ):
        return HttpResponseBadRequest(
            "Choose either a vocabulary domain or a deck."
        )
    if category_slug and test_slug:
        return HttpResponseBadRequest(
            "Choose either a category or a comprehension test."
        )
    selected = None
    selected_test = None
    all_phrases = (
        Phrase.objects.filter(
            is_active=True,
            tier=PhraseTier.SHARED,
        )
        .select_related("category")
        .prefetch_related("source_prompts__theme")
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
    for category in categories:
        category.phrase_count = all_phrases.filter(
            category=category
        ).count()
        category.card_count = category_card_counts.get(category.id, 0)
        category.batch_count = (
            category.phrase_count + queue_module.PHRASE_BATCH_SIZE - 1
        ) // queue_module.PHRASE_BATCH_SIZE
        category.is_functional = category.name in functional_names
        category.learning_description = category_descriptions.get(
            category.name,
            "Expressions réutilisables dans plusieurs réponses.",
        )

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
            return HttpResponseBadRequest("Unknown phrase category.")
        phrase_qs = all_phrases.filter(category=selected)
    elif test_slug:
        selected_test = get_object_or_404(
            ComprehensionTest,
            slug=test_slug,
            mode=ComprehensionMode.ECRITE,
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
            .prefetch_related("source_questions__test")
            .distinct()
            .order_by("category__order", "lot_order", "phrase_id")
        )

    grouped = []
    review_batches = []
    first_review_batch = None
    if selected:
        grouped.append(
            {
                "category": selected,
                "phrases": list(phrase_qs),
            }
        )
        review_batches = _review_batches(
            {**phrase_scope, "category": selected.slug},
            request.user,
        )
        first_review_batch = next(
            (batch for batch in review_batches if batch["can_review"]),
            None,
        )
    elif selected_test:
        for category in PhraseCategory.objects.filter(
            phrases__in=phrase_qs,
            is_active=True,
        ).distinct().order_by("order"):
            grouped.append(
                {
                    "category": category,
                    "phrases": list(phrase_qs.filter(category=category)),
                }
            )
        review_batches = _review_batches(
            {"kind": "vocab", "test": selected_test.slug},
            request.user,
        )
        first_review_batch = next(
            (batch for batch in review_batches if batch["can_review"]),
            review_batches[0] if review_batches else None,
        )

    functional_categories = [
        category
        for category in categories
        if category.is_functional
    ]
    comprehension_directory = vocabulary_domain == "comprehension"
    vocabulary_landing = not (
        selected
        or selected_test
        or task
        or comprehension_directory
    )
    subject_theme_groups = []
    subject_prompt_count = 0
    subject_response_count = 0
    subject_vocabulary_count = 0
    comprehension_decks = []
    comprehension_vocabulary_count = 0
    if not selected and not selected_test:
        subject_prompts = (
            Prompt.objects.filter(
                is_active=True,
                response__is_active=True,
                theme__is_active=True,
            )
            .select_related("theme", "family", "response")
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
        )
        subject_vocabulary = Phrase.objects.filter(
            is_active=True,
            tier=PhraseTier.SUBJECT,
            source_prompts__is_active=True,
            source_prompts__theme__is_active=True,
        )
        if task:
            subject_prompts = subject_prompts.filter(theme__task=task)
            subject_vocabulary = subject_vocabulary.filter(
                source_prompts__theme__task=task
            )
        subject_prompts = list(
            subject_prompts.order_by("theme__order", "number", "pk")
        )
        subject_prompt_count = len(subject_prompts)
        subject_response_ids = {
            prompt.response_id for prompt in subject_prompts
        }
        subject_progress_cards = {
            card.response_id: card
            for card in Card.objects.filter(
                user=request.user,
                card_type=CardType.SPINE,
                response_id__in=subject_response_ids,
            )
        }
        current_group = None
        for prompt in subject_prompts:
            prompt.vocabulary_batch_count = (
                prompt.vocabulary_count
                + queue_module.PHRASE_BATCH_SIZE
                - 1
            ) // queue_module.PHRASE_BATCH_SIZE
            prompt.progress_card = subject_progress_cards.get(
                prompt.response_id
            )
            if (
                current_group is None
                or current_group["theme"].pk != prompt.theme_id
            ):
                current_group = {
                    "theme": prompt.theme,
                    "prompts": [],
                    "response_ids": set(),
                }
                subject_theme_groups.append(current_group)
            current_group["prompts"].append(prompt)
            current_group["response_ids"].add(prompt.response_id)
        for group in subject_theme_groups:
            group["deck_count"] = len(group.pop("response_ids"))
        subject_response_count = len(subject_response_ids)
        subject_vocabulary_count = subject_vocabulary.distinct().count()

        tests = (
            ComprehensionTest.objects.filter(
                mode=ComprehensionMode.ECRITE,
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
            .order_by("number")
        )
        for test in tests:
            deck_scope = {"kind": "vocab", "test": test.slug}
            cards = queue_module.scoped_cards(
                deck_scope,
                user=request.user,
            )
            comprehension_decks.append(
                {
                    "test": test,
                    "vocabulary_count": test.vocabulary_count,
                    "batch_count": (
                        test.vocabulary_count
                        + queue_module.PHRASE_BATCH_SIZE
                        - 1
                    )
                    // queue_module.PHRASE_BATCH_SIZE,
                    "stats": deck_stats(cards, timezone.now()),
                    "counts": queue_module.queue_counts(
                        deck_scope,
                        user=request.user,
                    ),
                }
            )
            comprehension_vocabulary_count += test.vocabulary_count

    expression_vocabulary_paths = (
        _vocabulary_expression_paths(timezone.now(), request.user)
        if vocabulary_landing
        else []
    )

    vocabulary_scope = {"content": "vocabulary"}
    vocabulary_cards = queue_module.scoped_cards(
        vocabulary_scope,
        user=request.user,
    )
    vocabulary_counts = queue_module.queue_counts(
        vocabulary_scope,
        user=request.user,
    )
    vocabulary_revisit_count = queue_module.scoped_cards(
        {"kind": "revisit", "content": "vocabulary"},
        user=request.user,
    ).count()
    vocabulary_weak_count = queue_module.queue_counts(
        {"kind": "weak", "content": "vocabulary"},
        user=request.user,
    )["weak_total"]

    return render(
        request,
        "study/phrases.html",
        {
            "part": task.part if task else None,
            "task": task,
            "categories": categories,
            "functional_categories": functional_categories,
            "vocabulary_landing": vocabulary_landing,
            "comprehension_directory": comprehension_directory,
            "expression_vocabulary_paths": expression_vocabulary_paths,
            "functional_phrase_count": sum(
                category.phrase_count
                for category in functional_categories
            ),
            "first_category": (
                functional_categories[0]
                if functional_categories
                else None
            ),
            "subject_theme_groups": subject_theme_groups,
            "subject_prompt_count": subject_prompt_count,
            "subject_response_count": subject_response_count,
            "subject_vocabulary_count": subject_vocabulary_count,
            "comprehension_decks": comprehension_decks,
            "comprehension_vocabulary_count": (
                comprehension_vocabulary_count
            ),
            "vocabulary_stats": deck_stats(
                vocabulary_cards,
                timezone.now(),
            ),
            "vocabulary_counts": vocabulary_counts,
            "vocabulary_revisit_count": vocabulary_revisit_count,
            "vocabulary_weak_count": vocabulary_weak_count,
            "grouped": grouped,
            "review_batches": review_batches,
            "first_review_batch": first_review_batch,
            "batch_size": queue_module.PHRASE_BATCH_SIZE,
            "selected": selected,
            "selected_test": selected_test,
            "phrase_count": (
                selected.phrase_count
                if selected
                else (
                    phrase_qs.count()
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
    part_slug = part_slug or (request.GET.get("part") or "").strip()
    task_slug = task_slug or (request.GET.get("task") or "").strip()
    task = (
        _route_task(part_slug, task_slug)
        if part_slug and task_slug
        else None
    )
    query = request.GET.get("q", "").strip()
    prompt_results = []
    phrase_results = []
    comprehension_results = []
    prompt_result_count = 0
    phrase_result_count = 0
    comprehension_result_count = 0
    result_limit = 12
    if query:
        prompt_qs = Prompt.objects.filter(is_active=True).filter(
            Q(text__icontains=query) | Q(response__body__icontains=query)
        )
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
        phrase_result_count = phrase_qs.count()
        prompt_results = list(
            prompt_qs
            .select_related("response", "theme", "family")
            .order_by("theme__order", "number")[:result_limit]
        )
        prompt_progress_cards = {
            card.response_id: card
            for card in Card.objects.filter(
                user=request.user,
                card_type=CardType.SPINE,
                response_id__in={
                    prompt.response_id for prompt in prompt_results
                },
            )
        }
        for prompt in prompt_results:
            prompt.progress_card = prompt_progress_cards.get(
                prompt.response_id
            )
        phrase_results = list(
            phrase_qs
            .select_related("category")
            .order_by("order")[:result_limit]
        )
        if not task:
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
    result_count = (
        prompt_result_count
        + phrase_result_count
        + comprehension_result_count
    )
    visible_result_count = (
        len(prompt_results)
        + len(phrase_results)
        + len(comprehension_results)
    )
    return render(
        request,
        "study/search.html",
        {
            "part": task.part if task else None,
            "task": task,
            "query": query,
            "prompt_results": prompt_results,
            "phrase_results": phrase_results,
            "comprehension_results": comprehension_results,
            "prompt_result_count": prompt_result_count,
            "phrase_result_count": phrase_result_count,
            "comprehension_result_count": comprehension_result_count,
            "result_count": result_count,
            "visible_result_count": visible_result_count,
            "results_truncated": result_count > visible_result_count,
            "prompt_total": (
                Prompt.objects.filter(
                    theme__task=task,
                    is_active=True,
                ).count()
                if task
                else Prompt.objects.filter(is_active=True).count()
            ),
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


def stats(request, part_slug=None, task_slug=None):
    now = timezone.now()
    today = timezone.localtime(now).date()
    forced_task = (
        _route_task(part_slug, task_slug)
        if part_slug is not None and task_slug is not None
        else None
    )
    filters = _scope_filters(request, forced_task)
    scope = filters["scope"]

    scoped_history_cards = _stats_scope_cards(scope, request.user)
    active_cards = scoped_history_cards.filter(suspended=False)
    logs_base = ReviewLog.objects.filter(user=request.user)
    if scope:
        logs_base = logs_base.filter(
            card_id__in=scoped_history_cards.values("pk")
        )

    since = now - timezone.timedelta(days=90)
    logs = logs_base.filter(reviewed_at__gte=since)
    per_day: dict = {}
    for reviewed_at in logs.values_list("reviewed_at", flat=True):
        day = timezone.localtime(reviewed_at).date()
        per_day[day] = per_day.get(day, 0) + 1

    daily = []
    for offset in range(29, -1, -1):
        day = today - timezone.timedelta(days=offset)
        daily.append({"date": day, "count": per_day.get(day, 0)})
    max_daily = max((d["count"] for d in daily), default=0) or 1
    reviews_30_days = sum(d["count"] for d in daily)

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
    mature_total = mature_logs.count()
    mature_pass = mature_logs.exclude(rating=Rating.AGAIN).count()
    retention = round(100 * mature_pass / mature_total) if mature_total else None

    forecast = []
    active = active_cards.filter(
        state__in=[CardState.REVIEW, CardState.LEARNING, CardState.RELEARNING]
    )
    for offset in range(0, 14):
        day = today + timezone.timedelta(days=offset)
        start = timezone.make_aware(
            timezone.datetime.combine(day, timezone.datetime.min.time())
        )
        end = start + timezone.timedelta(days=1)
        if offset == 0:
            count = active.filter(due__lt=end).count()
        else:
            count = active.filter(due__gte=start, due__lt=end).count()
        forecast.append({"date": day, "count": count})
    max_forecast = max((f["count"] for f in forecast), default=0) or 1

    overall = deck_stats(active_cards, now)
    mastery_percentage = (
        round(100 * overall["mature"] / overall["total"])
        if overall["total"]
        else 0
    )

    theme_qs = Theme.objects.select_related("task__part").filter(is_active=True)
    if scope.get("task"):
        theme_qs = theme_qs.filter(
            task__slug=scope["task"],
            task__part__slug=scope["part"],
        )
    elif scope.get("part"):
        theme_qs = theme_qs.filter(task__part__slug=scope["part"])
    themes = [
        {
            "theme": theme,
            "stats": deck_stats(
                Card.objects.active().filter(
                    user=request.user,
                    card_type=CardType.SPINE, response__theme=theme
                ),
                now,
            ),
        }
        for theme in theme_qs
    ]

    context = {
        "daily": daily,
        "max_daily": max_daily,
        "reviews_30_days": reviews_30_days,
        "heat": heat,
        "reviews_90_days": sum(cell["count"] for cell in heat),
        "retention": retention,
        "mature_total": mature_total,
        "forecast": forecast,
        "max_forecast": max_forecast,
        "forecast_total": sum(item["count"] for item in forecast),
        "overall": overall,
        "mastery_percentage": mastery_percentage,
        "themes": themes,
        "streak": current_streak(now, logs_base, request.user),
        "total_reviews": logs_base.count(),
        "reviews_today": per_day.get(today, 0),
        "recent_sessions": recent_review_sessions(logs_base),
        "expression_weak_count": queue_module.queue_counts(
            {**scope, "kind": "weak", "content": "spine"},
            now,
            user=request.user,
        )["weak_total"],
        "vocabulary_weak_count": queue_module.queue_counts(
            {
                **scope,
                "kind": "weak",
                "content": "vocabulary",
            },
            now,
            user=request.user,
        )["weak_total"],
        **filters,
    }
    return render(request, "study/stats.html", context)
