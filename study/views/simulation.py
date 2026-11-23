"""Entry points for the oral studios and written preparation."""

from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_safe

from study.expression.eo.tache_2 import gemini_live
from study.models import Task


TRACKS = {
    "eo": {
        "title": "Expression orale", "icon": "microphone", "code": "EO",
        "intro": "Présentez-vous, menez un échange et défendez votre point de vue.",
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
        ("Entretien dirigé", "2 min", "Répondez aux questions sur votre parcours et votre quotidien."),
        ("Interaction", "2 min + 3 min 30", "Préparez vos questions, puis menez le jeu de rôle."),
        ("Expression d’un point de vue", "4 min 30", "Développez votre opinion sans temps de préparation."),
    ),
    "ee": (
        ("Écrire un message", "60–120 mots", "Adressez votre message à la personne indiquée dans la consigne."),
        ("Raconter une expérience", "120–150 mots", "Rédigez un récit pour les lecteurs auxquels vous vous adressez."),
        ("Comparer deux points de vue", "120–180 mots", "Présentez les deux opinions, puis défendez la vôtre."),
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
    for number, (title, format_label, description) in enumerate(TASK_FORMATS[part_slug], start=1):
        task = tasks.get(f"tache-{number}")
        if task is None:
            continue
        links = []
        hint = ""
        if part_slug == "eo":
            if number == 1:
                links.append(("Ouvrir l’entretien", reverse("study:eo_tache_one_interview")))
            else:
                if number == 2:
                    links.append(("Choisir un sujet", reverse("study:eo2_topic_picker")))
                if gemini_live.available_to(request.user, task):
                    studio = "study:eo_tache_two_live" if number == 2 else "study:eo_tache_three_live"
                    links.append(("Ouvrir le studio vocal", reverse(studio)))
                elif number == 3:
                    hint = "Studio vocal indisponible. Les sujets restent accessibles."
                if number == 2:
                    links.append(("Jeu de rôle guidé", reverse("study:eo_tache_two_interaction")))
        if part_slug == "ee" or number == 3:
            links.append(("Parcourir les sujets", reverse("study:task_browse", args=[part_slug, task.slug])))
        rows.append({
            "number": number, "title": title, "format": format_label,
            "description": description, "links": links, "hint": hint,
        })
    return render(request, "study/simulation/track.html", {
        "track": TRACKS[part_slug], "part_slug": part_slug, "rows": rows,
    })
