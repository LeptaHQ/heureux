"""Entry points and subject selection for the simulation studios."""

import unicodedata

from django.core.paginator import Paginator
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe

from study.models import Task
from study.navigation.routing import subject_selection_url


TRACKS = {
    "ee": {
        "title": "Expression écrite", "icon": "pen-line", "code": "EE",
    },
    "eo": {
        "title": "Expression orale", "icon": "microphone", "code": "EO",
    },
}
TASK_FORMATS = {
    "eo": (
        (2, "Interaction", "2 min + 3 min 30"),
        (3, "Expression d’un point de vue", "4 min 30 · sans préparation"),
    ),
    "ee": (
        (1, "Écrire un message", "60–120 mots"),
        (2, "Raconter une expérience", "120–150 mots"),
        (3, "Comparer deux points de vue", "120–180 mots"),
    ),
}
PICKER_STATUSES = {"new": "Sans séance", "done": "Déjà pratiqués"}
PICKER_ORDERS = {"recent": "Dernière séance", "least": "Moins pratiqués d’abord"}


def _fold(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def subject_picker_context(request, rows):
    query = request.GET.get("q", "").strip()[:120]
    theme = request.GET.get("theme", "")
    status = request.GET.get("etat", "")
    if status not in PICKER_STATUSES:
        status = ""
    order = request.GET.get("tri", "")
    if order not in {"az", "za", *PICKER_ORDERS}:
        order = ""
    needle = _fold(query)
    themes = {row["theme"]: row["theme_label"] for row in rows}
    filtered = [
        row for row in rows if not (
            (theme and row["theme"] != theme)
            or (status == "new" and row["count"])
            or (status == "done" and not row["count"])
            or (needle and needle not in _fold(f'{row["title"]} {row["caption"]}'))
        )
    ]
    if order in {"az", "za"}:
        filtered.sort(key=lambda row: _fold(row["title"]), reverse=order == "za")
    elif order == "recent":
        filtered.sort(key=lambda row: (row["latest"] is not None, row["latest"]), reverse=True)
    elif order == "least":
        filtered.sort(key=lambda row: row["count"])
    return {
        "page": Paginator(filtered, 15).get_page(request.GET.get("page")),
        "total": len(rows),
        "practiced_total": sum(bool(row["count"]) for row in rows),
        "directory_selection": {
            "themes": sorted(themes.items(), key=lambda item: _fold(item[1])),
            "theme": theme, "unavailable_theme": theme and theme not in themes,
            "query": query, "status": status, "order": order,
            "active": bool(theme or query or status or order),
            "status_choices": PICKER_STATUSES.items(), "extra_orders": PICKER_ORDERS.items(),
        },
    }


def render_subject_picker(request, context):
    template = (
        "study/simulation/subject_picker_results.html" if request.headers.get("X-Requested-With") == "fetch"
        else "study/simulation/subject_picker.html"
    )
    return render(request, template, context)


def studio_navigation(request, picker_route, *, theme="", label="", subjects=(), selected=None):
    task_url = reverse(picker_route)
    if not theme:
        return {
            "session_task_url": task_url,
            "session_back_url": task_url,
            "session_back_label": "Choisir un sujet",
        }
    context = {
        "session_task_url": task_url,
        "session_theme_label": label,
        "session_back_url": reverse(picker_route, query={"theme": theme}),
        "session_back_label": label,
    }
    choices = [
        {"label": title, "url": subject_selection_url(url, request), "position": index, "selected": key == selected}
        for index, (key, title, url) in enumerate(subjects, start=1)
    ]
    current = next((choice["position"] for choice in choices if choice["selected"]), None)
    if current is not None:
        context["session_subject_nav"] = {
            "position": current, "total": len(choices), "choices": choices,
            "previous": choices[current - 2] if current > 1 else None,
            "next": choices[current] if current < len(choices) else None,
        }
    return context


@require_safe
def hub(request):
    return render(request, "study/simulation/hub.html", {"tracks": TRACKS})


@require_safe
def track(request, part_slug):
    tasks = {
        task.slug: task for task in Task.objects.select_related("part").filter(
            part__slug=part_slug, part__is_active=True, part__available=True,
            is_active=True, available=True,
        )
    }
    rows = []
    for number, title, format_label in TASK_FORMATS[part_slug]:
        task = tasks.get(f"tache-{number}")
        if task is None:
            continue
        if part_slug == "ee":
            label, url = "Choisir un sujet", reverse(
                f"study:ee{number}_subject_picker"
            )
        elif number == 2:
            label, url = "Choisir un sujet", reverse("study:eo2_topic_picker")
        else:
            label, url = "Choisir un sujet", reverse("study:eo3_topic_picker")
        rows.append({
            "number": number, "title": title, "format": format_label,
            "label": label, "url": url,
            "is_simulation": part_slug == "ee",
        })
    return render(request, "study/simulation/track.html", {
        "track": TRACKS[part_slug], "part_slug": part_slug, "rows": rows,
    })
