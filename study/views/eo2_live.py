import json

from django.http import Http404, JsonResponse
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_POST

from study.audio.pins import AudioPinError
from study.catalogue import registry as catalogue
from study.catalogue.loader import tache_two_subject_content_key
from study.expression.eo.tache_2 import gemini_live
from study.models import Prompt
from study.navigation.routing import subject_selection_url
from .helpers import _route_task, active_task_for_request, tache_two_publication


def _live_publication(task, month_slug, batch_number, subject_number):
    _, _, subject = tache_two_publication(month_slug, batch_number, subject_number)
    key = tache_two_subject_content_key(month_slug, batch_number, subject_number)
    if not Prompt.objects.filter(
        theme__task=task, content_key=key, is_active=True, response__is_active=True,
    ).exists():
        raise Http404
    return subject, key


@never_cache
@require_GET
@ensure_csrf_cookie
def eo_tache_two_live(request, **publication):
    task = _route_task("eo", "tache-2", request=request)
    subject = None
    subject_url = ""
    if publication:
        subject, _ = _live_publication(task, **publication)
        subject_url = subject_selection_url(reverse("study:task_subject_detail", kwargs={
            "part_slug": "eo", "task_slug": "tache-2", **publication,
        }), request)
    return TemplateResponse(request, "study/expression/eo/tache_2/live.html", {
        "part": task.part,
        "task": task,
        "gemini_live_available": gemini_live.available_to(request.user, task),
        "token_url": reverse("study:eo_tache_two_live_token", kwargs=publication),
        "subject": subject,
        "subject_url": subject_url,
    })


@sensitive_variables()
def _session_request(request):
    # Allow space for a 128-character JSON-escaped PIN, but no other payload.
    body = request.read(2049)
    if len(body) > 2048:
        return None
    try:
        pairs = json.loads(body, object_pairs_hook=tuple)
    except (ValueError, RecursionError):
        return None
    if not isinstance(pairs, tuple):
        return None
    data = dict(pairs)
    if len(data) != len(pairs) or data.keys() - {"consent", "pin"} or data.get("consent") is not True:
        return None
    if "pin" in data:
        if not isinstance(data["pin"], str):
            return None
        try:
            data["pin"].encode("utf-8")
        except UnicodeEncodeError:
            return None
    return data


@never_cache
@require_POST
@csrf_protect
@sensitive_post_parameters("pin")
@sensitive_variables("data")
def eo_tache_two_live_token(request, **publication):
    if request.content_type != "application/json":
        return JsonResponse({"error": "Un objet JSON est requis."}, status=415)
    data = _session_request(request)
    if data is None:
        return JsonResponse({"error": "Un consentement explicite est requis."}, status=400)
    task = active_task_for_request(request, "eo", "tache-2")
    instruction = None
    if publication:
        subject, key = _live_publication(task, **publication)
        instruction = gemini_live.subject_instruction(subject, catalogue.tache_two_dialogues()[key])
    try:
        token = gemini_live.mint_token(request, task, data.get("pin"), instruction=instruction)
    except AudioPinError as exc:
        return JsonResponse({"error": exc.code, "message": str(exc)}, status=exc.status)
    except gemini_live.LiveTokenError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    return JsonResponse({"token": token, "model": gemini_live.MODEL})
