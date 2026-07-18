"""Home dashboard, section overviews, and redirect shims."""

from __future__ import annotations

from urllib.parse import urlencode

from django.db.models import Prefetch
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .. import queue as queue_module
from ..cards import scope_label
from ..models import (
    Annotation,
    Card,
    ExamPart,
    Phrase,
    PhraseTier,
    ReviewSession,
    Task,
)

from .common import (
    FUNCTIONAL_PHRASE_CATEGORY_NAMES,
    _route_task,
    _task_card,
    current_streak,
    deck_stats,
)
from .comprehension import _comprehension_summary

def _parts_with_task_cards(now, user):
    return [
        {
            "part": part,
            "tasks": [
                _task_card(task, now, user)
                for task in part.tasks.all()
            ],
        }
        for part in ExamPart.objects.filter(is_active=True).prefetch_related(
            Prefetch("tasks", queryset=Task.objects.filter(is_active=True))
        )
    ]


def _home_expression_paths(parts):
    paths = []
    for item in parts:
        all_tasks = item["tasks"]
        available_tasks = [
            task
            for task in all_tasks
            if task["task"].available
        ]
        paths.append(
            {
                **item,
                "available": bool(item["part"].available and all_tasks),
                "task_count": len(all_tasks),
                "has_content": bool(available_tasks),
                "prompt_count": sum(
                    task["prompt_count"] for task in available_tasks
                ),
                "seen": sum(
                    task["stats"]["seen"] for task in available_tasks
                ),
                "total": sum(
                    task["stats"]["total"] for task in available_tasks
                ),
                "due": sum(
                    task["stats"]["due"] for task in available_tasks
                ),
            }
        )
    paths.sort(
        key=lambda item: (
            {"ee": 0, "eo": 1}.get(
                item["part"].slug,
                2,
            ),
            item["part"].order,
        )
    )
    return paths


def _vocabulary_expression_paths(now, user):
    part_items = _parts_with_task_cards(now, user)
    path_specs = (
        {
            "title": "Écrite",
            "short_name": "EE",
            "slugs": {"ee"},
            "fallback_emoji": "✍️",
        },
        {
            "title": "Orale",
            "short_name": "EO",
            "slugs": {"eo"},
            "fallback_emoji": "🎙️",
        },
    )
    paths = []
    for spec in path_specs:
        item = next(
            (
                candidate
                for candidate in part_items
                if candidate["part"].slug in spec["slugs"]
            ),
            None,
        )
        vocabulary_tasks = []
        if item:
            vocabulary_tasks = [
                task_item
                for task_item in item["tasks"]
                if task_item["task"].available
                and (
                    task_item["functional_phrase_count"]
                    + task_item["subject_vocabulary_count"]
                )
            ]
        available = bool(
            item and item["part"].available and vocabulary_tasks
        )
        url = ""
        if available:
            if len(vocabulary_tasks) == 1:
                task = vocabulary_tasks[0]["task"]
                url = reverse("study:vocabulary") + "?" + urlencode(
                    {"part": task.part.slug, "task": task.slug}
                )
            else:
                url = reverse(
                    "study:part_detail",
                    args=[item["part"].slug],
                )
        paths.append(
            {
                "title": spec["title"],
                "short_name": spec["short_name"],
                "emoji": (
                    item["part"].emoji
                    if item
                    else spec["fallback_emoji"]
                ),
                "available": available,
                "url": url,
                "task_count": len(vocabulary_tasks),
                "prompt_count": sum(
                    task_item["prompt_count"]
                    for task_item in vocabulary_tasks
                ),
                "vocabulary_count": sum(
                    task_item["functional_phrase_count"]
                    + task_item["subject_vocabulary_count"]
                    for task_item in vocabulary_tasks
                ),
            }
        )
    return paths


def dashboard(request):
    now = timezone.now()
    expression_counts = queue_module.queue_counts(
        {"content": "spine"},
        now=now,
        user=request.user,
    )
    vocabulary_counts = queue_module.queue_counts(
        {"content": "vocabulary"},
        now=now,
        user=request.user,
    )
    user_cards = Card.objects.current_content().filter(
        user=request.user,
        suspended=False,
    )
    overall = deck_stats(user_cards, now)
    parts = _parts_with_task_cards(now, request.user)
    session = ReviewSession.load(request.user)

    context = {
        "expression_counts": expression_counts,
        "vocabulary_counts": vocabulary_counts,
        "parts": parts,
        "expression_paths": _home_expression_paths(parts),
        "overall": overall,
        "streak": current_streak(now, user=request.user),
        "comprehension": _comprehension_summary(request.user),
        "notes_to_study": Annotation.objects.filter(
            user=request.user,
            study_later=True,
        ).count(),
        "can_resume_review": bool(session.current_card_id),
        "resume_scope_label": (
            scope_label(session.scope)
            if session.current_card_id and isinstance(session.scope, dict)
            else ""
        ),
    }
    return render(request, "study/dashboard.html", context)


def _redirect_to(request, route_name, **scope):
    query = request.GET.copy()
    for key, value in scope.items():
        if value:
            query[key] = value
    target = reverse(route_name)
    if query:
        target = f"{target}?{query.urlencode()}"
    return redirect(target)


@require_GET
def redirect_home(request):
    return _redirect_to(request, "study:dashboard")


@require_GET
def redirect_expression(request):
    return _redirect_to(request, "study:expression")


@require_GET
def redirect_vocabulary(request, part_slug=None, task_slug=None):
    if part_slug is not None or task_slug is not None:
        task = _route_task(part_slug, task_slug)
        part_slug = task.part.slug
        task_slug = task.slug
    return _redirect_to(
        request,
        "study:vocabulary",
        part=part_slug,
        task=task_slug,
    )


@require_GET
def redirect_search(request, part_slug=None, task_slug=None):
    if part_slug is not None or task_slug is not None:
        task = _route_task(part_slug, task_slug)
        part_slug = task.part.slug
        task_slug = task.slug
    return _redirect_to(
        request,
        "study:search",
        part=part_slug,
        task=task_slug,
    )


@require_GET
def redirect_notes(request, part_slug=None, task_slug=None):
    scope = {}
    if part_slug and task_slug:
        task = _route_task(part_slug, task_slug)
        scope = {"part": task.part.slug, "task": task.slug}
    elif part_slug or task_slug:
        return HttpResponseBadRequest("Incomplete notes scope.")
    else:
        scope = {"scope": "general"}
    return _redirect_to(request, "study:notes_overview", **scope)


@require_GET
def redirect_stats(request, part_slug=None, task_slug=None):
    if part_slug is not None or task_slug is not None:
        task = _route_task(part_slug, task_slug)
        part_slug = task.part.slug
        task_slug = task.slug
    return _redirect_to(
        request,
        "study:stats",
        part=part_slug,
        task=task_slug,
    )


@require_GET
def expression_hub(request):
    now = timezone.now()
    parts = _parts_with_task_cards(now, request.user)
    paths = _home_expression_paths(parts)
    available_paths = [path for path in paths if path["available"]]
    return render(
        request,
        "study/expression_hub.html",
        {
            "paths": paths,
            "prompt_count": sum(
                path["prompt_count"] for path in available_paths
            ),
            "card_total": sum(path["total"] for path in available_paths),
            "card_seen": sum(path["seen"] for path in available_paths),
            "card_due": sum(path["due"] for path in available_paths),
        },
    )


def _grouped_overview(request, area):
    now = timezone.now()
    user_cards = queue_module.scoped_cards(user=request.user)
    context = {
        "area": area,
        "parts": _parts_with_task_cards(now, request.user),
        "overall": deck_stats(user_cards, now),
        "streak": current_streak(now, user=request.user),
    }
    if area == "review":
        session = ReviewSession.load(request.user)
        context.update(
            {
                "title": "Réviser",
                "eyebrow": "Mémoire active",
                "description": (
                    "Choisissez d'abord votre épreuve et votre tâche, "
                    "puis le type de cartes à travailler."
                ),
                "counts": queue_module.queue_counts(
                    now=now,
                    user=request.user,
                ),
                "revisit_count": queue_module.scoped_cards(
                    {"kind": "revisit"},
                    user=request.user,
                ).count(),
                "weak_count": queue_module.queue_counts(
                    {"kind": "weak"},
                    now,
                    user=request.user,
                )["weak_total"],
                "can_resume": bool(session.current_card_id),
            }
        )
    elif area == "expressions":
        functional_cards = queue_module.scoped_cards(
            {"kind": "phrase"},
            user=request.user,
        ).filter(
            phrase__tier=PhraseTier.SHARED,
            phrase__category__name__in=FUNCTIONAL_PHRASE_CATEGORY_NAMES,
        )
        context.update(
            {
                "title": "Expressions",
                "eyebrow": "Précision lexicale",
                "description": (
                    "Choisissez une tâche pour retrouver ses expressions "
                    "transversales et les 50 vocabs de chaque sujet."
                ),
                "phrase_count": Phrase.objects.filter(
                    is_active=True,
                    tier=PhraseTier.SHARED,
                    category__name__in=FUNCTIONAL_PHRASE_CATEGORY_NAMES,
                ).count(),
                "subject_phrase_count": Phrase.objects.filter(
                    is_active=True,
                    tier=PhraseTier.SUBJECT,
                ).count(),
                "phrase_stats": deck_stats(functional_cards, now),
                "phrase_counts": queue_module.queue_counts(
                    {"kind": "phrase"},
                    now,
                    user=request.user,
                ),
            }
        )
    else:
        context.update(
            {
                "title": "Stats",
                "eyebrow": "Progression",
                "description": (
                    "Choisissez une tâche pour consulter sa maîtrise, "
                    "son activité et ses prochaines révisions."
                ),
            }
        )
    return render(request, "study/grouped_overview.html", context)


@require_GET
def review_overview(request):
    return _grouped_overview(request, "review")


@require_GET
def expressions_overview(request):
    return _grouped_overview(request, "expressions")


@require_GET
def stats_overview(request):
    return _grouped_overview(request, "stats")
