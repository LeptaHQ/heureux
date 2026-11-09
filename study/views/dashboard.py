"""Home and expression navigation."""

from django.db.models import Exists, OuterRef
from django.shortcuts import render

from ..models import ExamPart, Task


def dashboard(request):
    return render(request, "study/dashboard/dashboard.html")


def expression_hub(request):
    parts = ExamPart.objects.filter(is_active=True).annotate(
        has_tasks=Exists(Task.objects.filter(part_id=OuterRef("pk"), is_active=True)),
    )
    paths = [
        {
            "part": part,
            "available": bool(part.available and part.has_tasks),
            "title": {"ee": "Écrite", "eo": "Orale"}.get(part.slug, part.name),
            "description": {
                "ee": "Rédiger des messages, des récits et des textes argumentés.",
                "eo": "Se présenter, échanger et défendre un point de vue.",
            }.get(part.slug, part.name),
        }
        for part in parts
    ]
    paths.sort(key=lambda path: (
        {"ee": 0, "eo": 1}.get(path["part"].slug, 2), path["part"].order,
    ))
    return render(request, "study/expression/expression_hub.html", {"paths": paths})
