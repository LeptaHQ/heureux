"""Entry points for the oral studios and written preparation."""

from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe

from study.models import Task


TRACKS = {
    "eo": {
        "title": "Expression orale", "icon": "microphone", "code": "EO",
        "intro": "Menez un échange ou défendez votre point de vue à voix haute.",
        "action": "Choisir une tâche orale",
    },
    "ee": {
        "title": "Expression écrite", "icon": "pen-line", "code": "EE",
        "intro": "Rédigez un message, racontez une expérience et comparez deux points de vue.",
        "action": "Préparer une tâche écrite",
    },
}
TASK_FORMATS = {
    "eo": (
        (2, "Interaction", "2 min + 3 min 30", "Préparez vos questions, puis menez l’échange."),
        (3, "Expression d’un point de vue", "4 min 30", "Développez votre opinion sans temps de préparation."),
    ),
    "ee": (
        (1, "Écrire un message", "60–120 mots", "Adressez votre message à la personne indiquée dans la consigne."),
        (2, "Raconter une expérience", "120–150 mots", "Rédigez un récit pour les lecteurs auxquels vous vous adressez."),
        (3, "Comparer deux points de vue", "120–180 mots", "Présentez les deux opinions, puis défendez la vôtre."),
    ),
}


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
    for number, title, format_label, description in TASK_FORMATS[part_slug]:
        task = tasks.get(f"tache-{number}")
        if task is None:
            continue
        if part_slug == "ee":
            label, url = "Parcourir les sujets", reverse("study:task_browse", args=[part_slug, task.slug])
        elif number == 2:
            label, url = "Choisir un sujet", reverse("study:eo2_topic_picker")
        else:
            label, url = "Ouvrir la simulation", reverse("study:eo_tache_three_live")
        rows.append({
            "number": number, "title": title, "format": format_label,
            "description": description, "label": label, "url": url,
        })
    return render(request, "study/simulation/track.html", {
        "track": TRACKS[part_slug], "part_slug": part_slug, "rows": rows,
    })
