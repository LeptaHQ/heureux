"""A learner's EO2 simulation checklist and topic-specific history."""

import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from django.core.paginator import Paginator
from django.db.models import Count, Max
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.vary import vary_on_headers

from study.catalogue import registry as catalogue
from study.catalogue.loader import tache_two_subject_content_key
from study.models import EO2PracticeAttempt, EO2TopicStatus, Prompt
from study.navigation.routing import subject_selection_url
from study.simulation import live_conversation

from .helpers import _route_task
from .simulation import picker_subjects, render_subject_picker


@dataclass(frozen=True)
class Topic:
    key: str
    title: str
    args: tuple
    source: str
    theme: str
    theme_slug: str

    @property
    def simulation_url(self):
        return reverse("study:eo_tache_two_live", args=self.args)


PHOTO = Topic("", "Choisir un atelier photo", (), "Sujet d’entraînement", "Loisirs, clubs & jeux", "loisirs-clubs-jeux")
PHOTO_TOKEN = "atelier-photo"
PICKER_STATUSES = {"new": "Sans séance", "done": "Terminés", "not-done": "Non terminés", "retry": "À refaire"}
PICKER_ORDERS = {"recent": "Dernière séance", "least": "Moins pratiqués d’abord"}


@lru_cache(maxsize=1)
def practice_topics():
    # Only publication metadata is shared; visibility and practice are read per request.
    themes, mapping = catalogue.tache_two_subject_themes()
    names = {theme.slug: theme.name for theme in themes}
    topics = {}
    for month in catalogue.tache_two_subject_months():
        for batch in month.batches:
            for subject in batch.subjects:
                args = (month.slug, batch.number, subject.number)
                key = tache_two_subject_content_key(*args)
                topics[key] = Topic(key, subject.title, args,
                                    f"{month.name} · Lot {batch.number} · Sujet {subject.number}",
                                    names[mapping[key]], mapping[key])
    return topics


def _task(request):
    task = _route_task("eo", "tache-2", request=request)
    if not (task.available and task.part.available):
        raise Http404
    return task


def topic_prompts(task):
    return Prompt.objects.filter(theme__task=task, theme__is_active=True,
                                 is_active=True, response__is_active=True)


def write_topic_status(user, task, subject_key, *, field, value):
    keys = [subject_key]
    if subject_key:
        group = topic_prompts(task).filter(content_key=subject_key).values("response_id")
        keys = Prompt.objects.filter(
            theme__task=task, response_id__in=group, content_key__startswith="tache2:",
        ).order_by("content_key").values_list("content_key", flat=True)
    EO2TopicStatus.objects.bulk_create(
        [EO2TopicStatus(user=user, subject_key=key, **{field: value}) for key in keys],
        update_conflicts=True, unique_fields=["user", "subject_key"], update_fields=[field],
    )


def resolve_topic(request, token):
    task = _task(request)
    if token == PHOTO_TOKEN:
        return task, PHOTO
    if not token or len(token) > 18 or not token.isascii() or not token.isdecimal():
        raise Http404
    key = get_object_or_404(topic_prompts(task).only("content_key"), pk=int(token)).content_key
    topic = practice_topics().get(key)
    if not topic:
        raise Http404
    return task, topic


def _fold(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


@require_GET
@vary_on_headers("X-Requested-With")
def picker(request):
    task = _task(request)
    publications = {
        key: (pk, response_id)
        for key, pk, response_id in topic_prompts(task).order_by().values_list("content_key", "pk", "response_id")
    }
    publications[""] = (PHOTO_TOKEN, PHOTO_TOKEN)
    done_groups, retry_groups = set(), set()
    for key, done, retry in EO2TopicStatus.objects.filter(user=request.user).values_list("subject_key", "done", "retry"):
        if key in publications:
            group = publications[key][1]
            if done:
                done_groups.add(group)
            if retry:
                retry_groups.add(group)
    attempts = {
        row["subject_key"]: row for row in EO2PracticeAttempt.objects.filter(user=request.user)
        .values("subject_key").annotate(count=Count("pk"), latest=Max("created_at"))
    }
    query = request.GET.get("q", "").strip()[:120]
    theme = request.GET.get("theme", "")
    status = request.GET.get("etat", request.GET.get("status", ""))
    if status not in PICKER_STATUSES:
        status = ""
    order = request.GET.get("tri", "")
    if order not in ("az", "za") and order not in PICKER_ORDERS:
        order = ""
    themes = {}
    rows = []
    needle = _fold(query)
    for topic in (PHOTO, *practice_topics().values()):
        publication = publications.get(topic.key)
        if publication is None:
            continue
        token, group = publication
        done, retry = group in done_groups, group in retry_groups
        themes[topic.theme_slug] = topic.theme
        summary = attempts.get(topic.key, {})
        rows.append({"topic": topic, "token": token, "done": done, "retry": retry,
                     "subject_group": group,
                     "count": summary.get("count", 0), "latest": summary.get("latest"),
                     "row_id": f"topic-{token}", "title": topic.title, "url": topic.simulation_url,
                     "caption": f"{topic.theme} · {topic.source}"})
    total = len(picker_subjects(request, rows))
    done_total = len(picker_subjects(request, (row for row in rows if row["done"])))
    retry_total = len(picker_subjects(request, (row for row in rows if row["retry"])))
    rows = picker_subjects(request, (
        row for row in rows if not (
            (theme and row["topic"].theme_slug != theme) or (status == "new" and row["count"])
            or (status == "done" and not row["done"]) or (status == "not-done" and row["done"])
            or (status == "retry" and not row["retry"]) or (needle and needle not in _fold(f'{row["title"]} {row["caption"]}'))
        )
    ))
    if order in ("az", "za"):
        rows.sort(key=lambda r: _fold(r["topic"].title), reverse=order == "za")
    elif order == "recent":
        rows.sort(key=lambda r: (r["latest"] is not None, r["latest"]), reverse=True)
    elif order == "least":
        rows.sort(key=lambda r: r["count"])
    page = Paginator(rows, 15).get_page(request.GET.get("page"))
    return render_subject_picker(request, {
        "task": task, "page": page, "total": total,
        "picker": {
            "back_url": reverse("study:simulation_track", args=["eo"]),
            "back_label": "Expression orale",
            "kicker": "Simulation · EO Tâche 2",
            "title": "Choisir un sujet",
            "heading_id": "eo2-title",
            "tone": "sim-tone--eo",
            "kind": "eo2",
            "topic_markers": True,
            "results_id": "eo2-topic-results",
            "show_status_summary": True,
        },
        "directory_selection": {
            "themes": sorted(themes.items(), key=lambda item: _fold(item[1])), "theme": theme,
            "unavailable_theme": theme and theme not in themes, "query": query, "status": status, "order": order,
            "active": bool(theme or query or status or order),
            "status_choices": PICKER_STATUSES.items(), "extra_orders": PICKER_ORDERS.items(),
        },
        "done_total": done_total, "retry_total": retry_total,
    })


@require_POST
def set_status(request, token):
    task, topic = resolve_topic(request, token)
    field = request.POST.get("field")
    background = request.headers.get("X-Requested-With") == "fetch"
    if field not in ("done", "retry") or request.POST.get("value") not in ("0", "1"):
        if background:
            return JsonResponse({"error": "Statut non reconnu."}, status=400)
        return HttpResponseBadRequest("Statut non reconnu.")
    value = request.POST["value"] == "1"
    write_topic_status(request.user, task, topic.key, field=field, value=value)
    if background:
        return JsonResponse({"field": field, "value": value})
    # Keep only picker filters rather than accepting an arbitrary return URL.
    url = reverse("study:eo2_topic_picker")
    params = request.GET.copy()
    return redirect((url + "?" + params.urlencode() if params else url) + f"#topic-{token}")


@require_GET
def legacy_rehearsal(request, prompt_id):
    _, topic = resolve_topic(request, str(prompt_id))
    return redirect(subject_selection_url(topic.simulation_url, request))


@require_GET
def history(request, token):
    task, topic = resolve_topic(request, token)
    rows = EO2PracticeAttempt.objects.filter(user=request.user, subject_key=topic.key).order_by(
        "-created_at", "-pk").values("created_at", "vocal", "live_simulation_id")
    page = Paginator(rows, 20).get_page(request.GET.get("page"))
    url = topic.simulation_url
    for row in page:
        if row["live_simulation_id"]:
            row["simulation_url"] = f'{url}?simulation={row["live_simulation_id"]}'
    return render(request, "study/simulation/eo2_history.html", {
        "topic": topic, "page": page,
        "can_reopen": live_conversation.available_to(request.user, task),
    })
