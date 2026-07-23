"""Home dashboard and expression overview."""

from __future__ import annotations

from django.db.models import Prefetch, Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from .. import queue as queue_module
from ..card_presentation import scope_label
from ..models import (
    Annotation,
    Card,
    CardType,
    ExamPart,
    PhraseTier,
    ReviewLog,
    ReviewSession,
    Task,
)
from ..progress import card_unit_progress, combine_progress

from .helpers import (
    FUNCTIONAL_PHRASE_CATEGORY_NAMES,
    _task_card,
    current_streak,
    deck_stats,
)
from .comprehension import _comprehension_summary


DAILY_REVIEW_GOAL = 30

STATUS_LABELS = {
    "new": "À commencer",
    "active": "En cours",
    "done": "Terminé",
}

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


def _vocabulary_cards_for_tasks(task_ids, user):
    return (
        Card.objects.current_content()
        .filter(
            user=user,
            phrase__source_prompts__is_active=True,
            phrase__source_prompts__theme__is_active=True,
            phrase__source_prompts__theme__task_id__in=task_ids,
            phrase__category__is_active=True,
        )
        .filter(
            Q(
                phrase__tier=PhraseTier.SUBJECT,
                card_type=CardType.PHRASE_PRODUCTION,
            )
            | Q(
                phrase__tier=PhraseTier.SHARED,
                phrase__category__name__in=(
                    FUNCTIONAL_PHRASE_CATEGORY_NAMES
                ),
                card_type__in=[
                    CardType.PHRASE_PRODUCTION,
                    CardType.PHRASE_RECOGNITION,
                ],
            )
        )
        .distinct()
    )


def _vocabulary_task_items(part_item, user, *, with_progress=True):
    items = []
    for task_item in part_item["tasks"]:
        vocabulary_count = (
            task_item["functional_phrase_count"]
            + task_item["subject_vocabulary_count"]
        )
        if not task_item["task"].available or not vocabulary_count:
            continue
        item = {
            **task_item,
            "vocabulary_count": vocabulary_count,
            "vocabulary_prompt_count": task_item[
                "subject_vocabulary_prompt_count"
            ],
            "vocabulary_url": (
                reverse(
                    "study:task_phrases",
                    args=[
                        task_item["task"].part.slug,
                        task_item["task"].slug,
                    ],
                )
                + "#vocabulaire-par-sujet"
            ),
        }
        if with_progress:
            progress = card_unit_progress(
                _vocabulary_cards_for_tasks([task_item["task"].pk], user)
            )
            item.update(
                {
                    "vocabulary_progress": progress,
                    "vocabulary_stats": {
                        "total": progress.total,
                        "completed": progress.completed,
                        "started_new": max(
                            progress.started - progress.completed,
                            0,
                        ),
                        "progress": progress,
                    },
                }
            )
        items.append(item)
    return items


def _vocabulary_expression_paths(now, user):
    part_items = _parts_with_task_cards(now, user)
    path_specs = (
        {
            "title": "Écrite",
            "short_name": "EE",
            "slugs": {"ee"},
            "fallback_icon": "pen-line",
        },
        {
            "title": "Orale",
            "short_name": "EO",
            "slugs": {"eo"},
            "fallback_icon": "microphone",
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
        vocabulary_tasks = (
            _vocabulary_task_items(item, user, with_progress=False)
            if item
            else []
        )
        available = bool(
            item and item["part"].available and vocabulary_tasks
        )
        url = ""
        vocabulary_progress = None
        if available:
            task_ids = [
                task_item["task"].pk for task_item in vocabulary_tasks
            ]
            vocabulary_cards = _vocabulary_cards_for_tasks(
                task_ids,
                user,
            )
            vocabulary_progress = card_unit_progress(vocabulary_cards)
            url = reverse(
                "study:part_vocabulary",
                args=[item["part"].slug],
            )
        paths.append(
            {
                "title": spec["title"],
                "short_name": spec["short_name"],
                "icon": (
                    item["part"].icon
                    if item
                    else spec["fallback_icon"]
                ),
                "available": available,
                "url": url,
                "task_count": len(vocabulary_tasks),
                "prompt_count": sum(
                    task_item["vocabulary_prompt_count"]
                    for task_item in vocabulary_tasks
                ),
                "vocabulary_count": (
                    vocabulary_progress.total if vocabulary_progress else 0
                ),
                "progress": vocabulary_progress,
            }
        )
    return paths


def _fr_plural(count):
    return "s" if count > 1 else ""


def _reviews_today(user, now):
    start = timezone.localtime(now).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return ReviewLog.objects.filter(
        user=user,
        reviewed_at__gte=start,
    ).count()


def _skill_rings(expression_paths, comprehension, vocabulary_stats):
    """Four progress rings summarizing each study skill for the home page."""
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
                    f"{progress.completed}/{progress.total} sujets"
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

    vocab_total = vocabulary_stats["total"]
    if vocab_total and vocabulary_stats["mature"] >= vocab_total:
        vocab_status = "done"
    elif vocabulary_stats["seen"]:
        vocab_status = "active"
    else:
        vocab_status = "new"
    rings.append(
        {
            "key": "vocabulaire",
            "icon": "messages",
            "label": "Vocabulaire",
            "sublabel": "Mots & tournures",
            "accent": "var(--accent)",
            "available": bool(vocab_total),
            "percent": vocabulary_stats["mature_pct"],
            "detail": (
                f"{vocabulary_stats['mature']}/{vocab_total} maîtrisées"
                if vocab_total
                else "Bientôt disponible"
            ),
            "status": vocab_status,
            "status_label": STATUS_LABELS[vocab_status],
            "url": reverse("study:vocabulary"),
            "is_new": False,
        }
    )
    return rings


def _next_action(*, expression_counts, vocabulary_counts, comprehension, notes_to_study):
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

    vocabulary_due = vocabulary_counts.get("due_reviews", 0)
    if vocabulary_due:
        return {
            "tone": "vocabulary",
            "icon": "messages",
            "eyebrow": "À réviser maintenant",
            "title": f"Réviser {vocabulary_due} carte{_fr_plural(vocabulary_due)} de vocabulaire",
            "detail": "Réactive les mots et tournures à revoir aujourd’hui.",
            "cta": "Réviser",
            "url": f"{review_url}?content=vocabulary",
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

    vocabulary_new = vocabulary_counts.get("new_available", 0)
    if vocabulary_new:
        return {
            "tone": "vocabulary",
            "icon": "messages",
            "eyebrow": "À découvrir",
            "title": (
                f"Activer {vocabulary_new} nouvelle{_fr_plural(vocabulary_new)} "
                f"carte{_fr_plural(vocabulary_new)}"
            ),
            "detail": "Ajoute de nouveaux mots et tournures à ton deck.",
            "cta": "Choisir un deck",
            "url": reverse("study:vocabulary"),
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
    vocabulary_stats = deck_stats(
        queue_module.scoped_cards({"content": "vocabulary"}, user=request.user),
        now,
    )
    parts = _parts_with_task_cards(now, request.user)
    expression_paths = _home_expression_paths(parts)
    comprehension = _comprehension_summary(request.user)
    notes_to_study = Annotation.objects.filter(
        user=request.user,
        study_later=True,
    ).count()
    session = ReviewSession.load(request.user)

    skills = _skill_rings(expression_paths, comprehension, vocabulary_stats)
    ee_spotlight = next(
        (skill for skill in skills if skill["key"] == "ee" and skill["is_new"]),
        None,
    )
    reviews_today = _reviews_today(request.user, now)
    daily_goal_pct = (
        min(100, round(100 * reviews_today / DAILY_REVIEW_GOAL))
        if DAILY_REVIEW_GOAL
        else 0
    )

    context = {
        "expression_counts": expression_counts,
        "vocabulary_counts": vocabulary_counts,
        "parts": parts,
        "expression_paths": expression_paths,
        "overall": overall,
        "streak": current_streak(now, user=request.user),
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
            vocabulary_counts=vocabulary_counts,
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
            "response_due": sum(path["due"] for path in available_paths),
        },
    )
