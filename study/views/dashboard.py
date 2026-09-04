"""Home dashboard and expression overview."""

from __future__ import annotations

from django.db.models import Prefetch
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from .. import queue as queue_module
from ..card_presentation import scope_label
from ..models import (
    Annotation,
    Card,
    ExamPart,
    ReviewSession,
    Task,
)
from ..progress import combine_progress

from .helpers import (
    current_streak,
    deck_stats,
    expression_task_summaries,
    review_day_counts,
)
from .comprehension import _comprehension_summary


DAILY_REVIEW_GOAL = 30

STATUS_LABELS = {
    "new": "À commencer",
    "active": "En cours",
    "done": "Terminé",
}

def _parts_with_task_summaries(now, user):
    """Every part with the light per-task rows these two pages render.

    The home page and the expression hub only show aggregate progress, so the
    tasks carry the batched summary instead of a full task card: the same
    numbers, at a fixed handful of queries for the page rather than about nine
    per task.
    """
    parts = list(
        ExamPart.objects.filter(is_active=True).prefetch_related(
            Prefetch("tasks", queryset=Task.objects.filter(is_active=True))
        )
    )
    tasks_by_part = [(part, list(part.tasks.all())) for part in parts]
    summaries = expression_task_summaries(
        now,
        user,
        [task for _, tasks in tasks_by_part for task in tasks],
    )
    return [
        {
            "part": part,
            "tasks": [
                {"task": task, **summaries[task.pk]}
                for task in tasks
            ],
        }
        for part, tasks in tasks_by_part
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
        path_progress = combine_progress(
            task["stats"]["progress"] for task in available_tasks
        )
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
                "progress": path_progress,
                "title": {
                    "ee": "Écrite",
                    "eo": "Orale",
                }.get(item["part"].slug, item["part"].name),
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


def _fr_plural(count):
    return "s" if count > 1 else ""


def _reviews_today(day_counts, now):
    """Reviews recorded since local midnight, from the per-day mapping."""
    today = timezone.localtime(now).date()
    return sum(
        count for day, count in day_counts.items() if day >= today
    )


def _skill_rings(expression_paths, comprehension):
    """Progress rings for the expression and comprehension study areas."""
    rings = []
    paths_by_slug = {path["part"].slug: path for path in expression_paths}

    for slug, icon in (("eo", "microphone"), ("ee", "pencil")):
        path = paths_by_slug.get(slug)
        if path is None:
            continue
        progress = path["progress"]
        rings.append(
            {
                "key": slug,
                "icon": icon,
                "label": path["title"],
                "sublabel": path["part"].name,
                "accent": path["part"].color or "var(--primary)",
                "available": bool(path["available"] and path["has_content"]),
                "percent": progress.percent,
                "detail": (
                    f"{progress.completed}/{progress.total} éléments"
                    if progress.total
                    else "Bientôt disponible"
                ),
                "status": progress.status,
                "status_label": progress.label,
                "url": reverse("study:part_detail", args=[slug]),
                "is_new": bool(
                    slug == "ee"
                    and path["available"]
                    and path["has_content"]
                    and progress.started == 0
                ),
            }
        )

    comp_progress = comprehension["progress"]
    comp_total = comprehension.get("test_count", 0)
    rings.append(
        {
            "key": "comprehension",
            "icon": "book-open",
            "label": "Compréhension",
            "sublabel": "Écrite & orale",
            "accent": "var(--success)",
            "available": bool(comp_total),
            "percent": comp_progress.percent,
            "detail": (
                f"{comprehension.get('completed_test_count', 0)}/{comp_total} tests"
                if comp_total
                else "Bientôt disponible"
            ),
            "status": comp_progress.status,
            "status_label": comp_progress.label,
            "url": reverse("study:comprehension_hub"),
            "is_new": False,
        }
    )

    return rings


def _next_action(*, expression_counts, comprehension, notes_to_study):
    """The single most useful next step, chosen by a fixed priority order."""
    review_url = reverse("study:review")

    expression_due = expression_counts.get("due_reviews", 0)
    if expression_due:
        return {
            "tone": "expression",
            "icon": "target",
            "eyebrow": "À réviser maintenant",
            "title": f"Réviser {expression_due} réponse{_fr_plural(expression_due)}",
            "detail": "Consolide tes réponses d’expression pendant qu’elles sont fraîches.",
            "cta": "Réviser",
            "url": f"{review_url}?kind=spine",
        }

    if comprehension.get("active_attempt"):
        next_test = comprehension.get("next_test")
        answered = comprehension.get("active_answered_count", 0)
        question_count = comprehension.get("active_question_count", 0)
        return {
            "tone": "comprehension",
            "icon": "book-open",
            "eyebrow": "À continuer",
            "title": (
                f"Continuer {next_test.title}"
                if next_test
                else "Continuer le test en cours"
            ),
            "detail": f"{answered}/{question_count} questions déjà répondues.",
            "cta": "Continuer",
            "url": (
                comprehension.get("active_attempt_url")
                or reverse("study:comprehension_hub")
            ),
        }

    expression_new = expression_counts.get("new_available", 0)
    if expression_new:
        return {
            "tone": "expression",
            "icon": "target",
            "eyebrow": "À découvrir",
            "title": (
                f"Ajouter {expression_new} nouvelle{_fr_plural(expression_new)} "
                f"réponse{_fr_plural(expression_new)}"
            ),
            "detail": "Enrichis ta pratique avec de nouvelles réponses d’expression.",
            "cta": "Commencer",
            "url": f"{review_url}?kind=spine",
        }

    if comprehension.get("next_test"):
        next_test = comprehension["next_test"]
        completed = comprehension.get("completed_test_count", 0)
        total_tests = comprehension.get("test_count", 0)
        return {
            "tone": "comprehension",
            "icon": "book-open",
            "eyebrow": "À faire",
            "title": f"Faire {next_test.title}",
            "detail": f"{completed}/{total_tests} tests de compréhension terminés.",
            "cta": "Ouvrir le test",
            "url": (
                comprehension.get("next_test_url")
                or reverse("study:comprehension_hub")
            ),
        }

    if notes_to_study:
        return {
            "tone": "notes",
            "icon": "pen-line",
            "eyebrow": "À étudier",
            "title": f"Revoir {notes_to_study} note{_fr_plural(notes_to_study)}",
            "detail": "Reprends tes notes et surlignages mis de côté.",
            "cta": "Étudier",
            "url": reverse("study:annotation_study"),
        }

    return {
        "tone": "done",
        "icon": "sparkles",
        "eyebrow": "Tout est à jour",
        "title": "Tu es à jour pour aujourd’hui",
        "detail": "Explore de nouveaux sujets ou renforce tes points faibles.",
        "cta": "Explorer les sujets",
        "url": reverse("study:expression"),
        "caught_up": True,
    }


def dashboard(request):
    now = timezone.now()
    # Only what is available to study is rendered, so the today and revisit
    # scans of the full queue summary are not paid for here.
    expression_counts = queue_module.available_counts(
        {"content": "spine"},
        now=now,
        user=request.user,
    )
    user_cards = Card.objects.current_content().filter(
        user=request.user,
        suspended=False,
    )
    overall = deck_stats(user_cards, now)
    # Only aggregate expression progress is rendered on the home page.
    parts = _parts_with_task_summaries(now, request.user)
    expression_paths = _home_expression_paths(parts)
    comprehension = _comprehension_summary(request.user)
    notes_to_study = Annotation.objects.filter(
        user=request.user,
        study_later=True,
    ).count()
    session = ReviewSession.load(request.user)

    skills = _skill_rings(expression_paths, comprehension)
    ee_spotlight = next(
        (skill for skill in skills if skill["key"] == "ee" and skill["is_new"]),
        None,
    )
    # One grouped pass over the review log serves both the streak and today's
    # count, instead of a full history fetch plus a separate count.
    review_days = review_day_counts(user=request.user)
    reviews_today = _reviews_today(review_days, now)
    daily_goal_pct = (
        min(100, round(100 * reviews_today / DAILY_REVIEW_GOAL))
        if DAILY_REVIEW_GOAL
        else 0
    )

    context = {
        "expression_counts": expression_counts,
        "parts": parts,
        "expression_paths": expression_paths,
        "overall": overall,
        "streak": current_streak(now, day_counts=review_days),
        "comprehension": comprehension,
        "notes_to_study": notes_to_study,
        "can_resume_review": bool(session.current_card_id),
        "resume_scope_label": (
            scope_label(session.scope)
            if session.current_card_id and isinstance(session.scope, dict)
            else ""
        ),
        "skills": skills,
        "ee_spotlight": ee_spotlight,
        "next_action": _next_action(
            expression_counts=expression_counts,
            comprehension=comprehension,
            notes_to_study=notes_to_study,
        ),
        "reviews_today": reviews_today,
        "daily_goal": DAILY_REVIEW_GOAL,
        "daily_goal_remaining": max(
            DAILY_REVIEW_GOAL - reviews_today,
            0,
        ),
        "daily_goal_pct": daily_goal_pct,
        "daily_goal_met": reviews_today >= DAILY_REVIEW_GOAL,
    }
    return render(request, "study/dashboard.html", context)


def expression_hub(request):
    now = timezone.now()
    parts = _parts_with_task_summaries(now, request.user)
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
            "response_due": sum(path["due"] for path in available_paths),
        },
    )
