"""Home and expression overview."""

from __future__ import annotations

from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone

from ..models import (
    ExamPart,
    Task,
)
from ..progress import combine_progress

from .helpers import expression_task_summaries


def _parts_with_task_summaries(now, user, *, with_stats=True):
    """Every expression part with the light per-task rows the hub renders.

    The expression hub only shows aggregate progress, so the tasks carry the
    batched summary instead of a full task card: the same numbers, at a fixed
    handful of queries for the page rather than about nine per task.
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
    ) if with_stats else {}
    return [
        {
            "part": part,
            "tasks": [
                {"task": task, **summaries.get(task.pk, {})}
                for task in tasks
            ],
        }
        for part, tasks in tasks_by_part
    ]


def _home_expression_paths(parts, *, with_stats=True):
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
        ) if with_stats else None
        paths.append(
            {
                **item,
                "available": bool(item["part"].available and all_tasks),
                "task_count": len(all_tasks),
                "has_content": bool(available_tasks),
                "prompt_count": sum(
                    task["prompt_count"] for task in available_tasks
                ) if with_stats else None,
                "seen": sum(
                    task["stats"]["seen"] for task in available_tasks
                ) if with_stats else None,
                "total": sum(
                    task["stats"]["total"] for task in available_tasks
                ) if with_stats else None,
                "due": sum(
                    task["stats"]["due"] for task in available_tasks
                ) if with_stats else None,
                "progress": path_progress,
                "content_unit": (
                    "contenus" if item["part"].slug == "eo" else "sujets"
                ),
                "progress_unit": "contenus",
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


def dashboard(request):
    return render(request, "study/dashboard.html")


def expression_hub(request):
    now = timezone.now()
    with_stats = request.GET.get("stats") == "1"
    parts = _parts_with_task_summaries(now, request.user, with_stats=with_stats)
    paths = _home_expression_paths(parts, with_stats=with_stats)
    available_paths = [path for path in paths if path["available"]]
    context = {
        "paths": paths,
        "deferred_stats": not with_stats,
        "stats_url": f"{request.path}?stats=1",
    }
    if with_stats:
        context.update(
            prompt_count=sum(path["prompt_count"] for path in available_paths),
            card_total=sum(path["total"] for path in available_paths),
            card_seen=sum(path["seen"] for path in available_paths),
            response_due=sum(path["due"] for path in available_paths),
        )
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({
                "html": render_to_string("study/partials/expression_paths.html", context, request=request),
                "metrics": render_to_string("study/partials/expression_metrics.html", context, request=request),
            })
    return render(
        request,
        "study/expression_hub.html",
        context,
    )
