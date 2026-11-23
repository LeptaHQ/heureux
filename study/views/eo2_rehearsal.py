"""Publication-specific rehearsal, with one reviewed interlocutor reply per turn."""

import hashlib
import json
from dataclasses import asdict

from django.core import signing
from django.http import Http404, JsonResponse
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from study.catalogue import registry as catalogue
from study.expression.eo.tache_2 import gemini_live
from study.navigation.routing import subject_selection_url
from .eo2_practice import resolve_topic


CURSOR_SALT = "study.eo2.rehearsal.turn"
CURSOR_MAX_AGE = 2 * 60 * 60


def _material(request, prompt_id):
    task, topic = resolve_topic(request, str(prompt_id))
    dialogue = catalogue.tache_two_dialogues().get(topic.key)
    hints = catalogue.tache_two_subject_hints().get(topic.key, ())
    if dialogue is None or len(hints) != len(dialogue.questions):
        raise Http404("Ce sujet n’a pas de parcours guidé publié.")
    return task, topic, dialogue, hints


def _identity(request, prompt_id, topic, dialogue):
    revision = hashlib.sha256(
        json.dumps(asdict(dialogue), sort_keys=True).encode()
    ).hexdigest()
    return {
        "prompt": str(prompt_id),
        "publication": topic.key,
        "user": request.user.pk,
        "revision": revision,
    }


def _turn(dialogue, hints, identity, index):
    if index >= len(dialogue.questions):
        return None
    question, hint = dialogue.questions[index], hints[index]
    return {
        "number": index + 1,
        "topic": question.topic,
        "question": question.question,
        "hintEnglish": hint.english,
        "hintFrench": hint.french,
        "followUpTo": question.follow_up_to,
        "cursor": signing.dumps({**identity, "turn": index}, salt=CURSOR_SALT),
    }


@never_cache
@require_GET
@ensure_csrf_cookie
def rehearsal(request, prompt_id):
    task, topic, dialogue, hints = _material(request, prompt_id)
    identity = _identity(request, prompt_id, topic, dialogue)
    return TemplateResponse(request, "study/expression/eo/tache_2/rehearsal.html", {
        "part": task.part,
        "task": task,
        "topic": topic,
        "practice_topic": str(prompt_id),
        "subject_url": subject_selection_url(reverse(
            "study:task_subject_detail", args=["eo", "tache-2", *topic.args],
        ), request),
        "live_url": subject_selection_url(reverse(
            "study:eo_tache_two_live", args=topic.args,
        ), request),
        "gemini_live_available": gemini_live.available_to(request.user, task),
        "reply_url": reverse("study:eo2_rehearsal_reply", args=[prompt_id]),
        "opening": dialogue.opening,
        "question_count": len(dialogue.questions),
        "initial_turn": _turn(dialogue, hints, identity, 0),
    })


@never_cache
@require_POST
@csrf_protect
def rehearsal_reply(request, prompt_id):
    _, topic, dialogue, hints = _material(request, prompt_id)
    if (
        request.content_type != "application/x-www-form-urlencoded"
        or len(request.body) > 4096
        or set(request.POST) - {"cursor", "action", "csrfmiddlewaretoken"}
        or any(len(values) != 1 for _, values in request.POST.lists())
        or request.POST.get("action") not in {"reply", "skip"}
    ):
        return JsonResponse({"error": "Une étape du parcours est requise."}, status=400)
    identity = _identity(request, prompt_id, topic, dialogue)
    try:
        data = signing.loads(
            request.POST.get("cursor", ""), salt=CURSOR_SALT, max_age=CURSOR_MAX_AGE,
        )
    except signing.BadSignature:
        return JsonResponse(
            {"error": "Cette séance a expiré. Rechargez la page pour recommencer."},
            status=400,
        )
    index = data.get("turn") if isinstance(data, dict) else None
    if (
        type(index) is not int
        or not 0 <= index < len(dialogue.questions)
        or data != {**identity, "turn": index}
    ):
        return JsonResponse({"error": "Cette étape ne correspond pas au sujet."}, status=400)
    question = dialogue.questions[index]
    skipped = request.POST["action"] == "skip"
    if skipped and question.follow_up_to is None:
        return JsonResponse({"error": "Seule une relance peut être passée."}, status=400)
    return JsonResponse({
        "answer": "" if skipped else question.answer,
        "next": _turn(dialogue, hints, identity, index + 1),
        "closing": dialogue.closing if index + 1 == len(dialogue.questions) else "",
    })
