"""Entry points and subject selection for the simulation studios."""

import unicodedata
from dataclasses import dataclass
from operator import attrgetter, itemgetter

from django.core.paginator import Paginator
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe

from study.models import Task
from study.navigation.routing import subject_representatives, subject_selection_url


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
MARKER_STATUSES = {"new": "Sans séance", "done": "Terminés", "not-done": "Non terminés", "retry": "À refaire"}
PICKER_ORDERS = {"recent": "Dernière séance", "least": "Moins pratiqués d’abord"}


@dataclass(frozen=True)
class PickerSubject:
    key: str | int
    title: str
    theme: str
    theme_label: str
    caption: str
    group: str | int


def _fold(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def subject_picker_context(request, subjects, attempts, *, markers=None):
    query = request.GET.get("q", "").strip()[:120]
    theme = request.GET.get("theme", "")
    status = request.GET.get("etat", request.GET.get("status", "") if markers is not None else "")
    statuses = MARKER_STATUSES if markers is not None else PICKER_STATUSES
    if status not in statuses:
        status = ""
    order = request.GET.get("tri", "")
    if order not in {"az", "za", *PICKER_ORDERS}:
        order = ""
    needle = _fold(query)
    deduplicate = request.GET.get("deduplicate", "1") == "1"
    themes, filtered = {}, []
    total, practiced_total, done_total, retry_total = set(), set(), set(), set()
    for subject in subjects:
        key = subject.group if deduplicate else subject.key
        themes[subject.theme] = subject.theme_label
        total.add(key)
        practiced = subject.key in attempts
        mark = markers.get(subject.group, ()) if markers is not None else ()
        done, retry = "done" in mark, "retry" in mark
        if practiced:
            practiced_total.add(key)
        if done:
            done_total.add(key)
        if retry:
            retry_total.add(key)
        complete = done if markers is not None else practiced
        if ((theme and subject.theme != theme)
                or (status == "new" and practiced)
                or (status == "done" and not complete)
                or (status == "not-done" and done)
                or (status == "retry" and not retry)
                or (needle and needle not in _fold(f"{subject.title} {subject.caption}"))):
            continue
        filtered.append(subject)
    if deduplicate:
        filtered = list(subject_representatives(filtered, key=attrgetter("group")).values())
    if order in {"az", "za"}:
        filtered.sort(key=lambda subject: _fold(subject.title), reverse=order == "za")
    elif order == "recent":
        def recency(subject):
            latest = attempts.get(subject.key, {}).get("latest")
            return latest is not None, latest
        filtered.sort(key=recency, reverse=True)
    elif order == "least":
        filtered.sort(key=lambda subject: attempts.get(subject.key, {}).get("count", 0))
    return {
        "page": Paginator(filtered, 15).get_page(request.GET.get("page")),
        "total": len(total),
        "practiced_total": len(practiced_total), "done_total": len(done_total), "retry_total": len(retry_total),
        "directory_selection": {
            "themes": sorted(themes.items(), key=lambda item: _fold(item[1])),
            "theme": theme, "unavailable_theme": theme and theme not in themes,
            "query": query, "status": status, "order": order,
            "active": bool(theme or query or status or order),
            "status_choices": statuses.items(), "extra_orders": PICKER_ORDERS.items(),
        },
    }


def picker_rows(context, attempts, row_for):
    page = context["page"]
    page.object_list = [
        {
            "title": subject.title, "caption": subject.caption,
            "count": attempts.get(subject.key, {}).get("count", 0),
            **row_for(subject),
        }
        for subject in page.object_list
    ]


def saved_session_context(request, sessions, row_for):
    page = Paginator(sessions, 8).get_page(request.GET.get("seances"))
    page.object_list = [row_for(session) for session in page.object_list]
    return {"saved_sessions": page.object_list, "saved_sessions_page": page}


def render_subject_picker(request, context):
    template = (
        "study/simulation/subject_picker_results.html" if request.headers.get("X-Requested-With") == "fetch"
        else "study/simulation/subject_picker.html"
    )
    return render(request, template, {
        **context,
        "subject_deduplication_available": True,
        "deduplicate_subjects": request.GET.get("deduplicate", "1") == "1",
    })


def studio_navigation(request, picker_route, *, theme="", label="", subjects=(), selected=None):
    task_url = subject_selection_url(reverse(picker_route), request)
    if not theme:
        return {
            "session_task_url": task_url,
            "session_back_url": task_url,
            "session_back_label": "Choisir un sujet",
        }
    context = {
        "session_task_url": task_url,
        "session_theme_label": label,
        "session_back_url": subject_selection_url(reverse(picker_route, query={"theme": theme}), request),
        "session_back_label": label,
    }
    subjects = list(subjects)
    if request.GET.get("deduplicate", "1") == "1":
        representatives = subject_representatives(subjects, key=itemgetter(1))
        current_subject = next((row for row in subjects if row[0] == selected), None)
        if current_subject is not None:
            representatives[current_subject[1]] = current_subject
        subjects = representatives.values()
    choices = [
        {"label": title, "url": subject_selection_url(url, request), "position": index, "selected": key == selected}
        for index, (key, _, title, url) in enumerate(subjects, start=1)
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
