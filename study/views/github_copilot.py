"""Connect Copilot to the signed-in Heureux account, not to the login flow."""

import base64
import hashlib
import logging
import secrets
import time
from urllib.parse import urlencode
from uuid import UUID

from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_GET, require_POST

from study.accounts import github_copilot
from study.models import WritingSimulationAttempt, WritingSimulationAttemptStatus

logger = logging.getLogger(__name__)
_FLOW = "github_copilot_authorization"
_NOTICES = {
    "connected": "Compte GitHub connecté.",
    "disconnected": "Compte GitHub déconnecté. Vos bilans restent disponibles.",
    "failed": "La connexion à GitHub n’a pas abouti. Veuillez réessayer.",
    "other": "Déconnectez d’abord le compte GitHub déjà lié.",
    "origin": "Ouvrez Heureux à son adresse configurée pour connecter GitHub.",
}


def notice(request):
    return _NOTICES.get(request.GET.get("copilot", ""), "")


def _return(attempt_id, status):
    route = "study:ee1_simulation_attempt" if attempt_id else "study:settings"
    response = redirect(reverse(route, args=[attempt_id] if attempt_id else (), query={"copilot": status}))
    response["Referrer-Policy"] = "no-referrer"
    return response


@never_cache
@require_POST
@csrf_protect
@sensitive_variables()
def authorize(request):
    config = github_copilot.configuration()
    if config is None:
        raise Http404
    attempt_id = request.POST.get("attempt_id", "")
    if attempt_id:
        try:
            attempt_id = str(UUID(attempt_id))
        except ValueError:
            raise Http404 from None
        if not WritingSimulationAttempt.objects.filter(
            pk=attempt_id, user=request.user, task__part__slug="ee", task__slug="tache-1",
            status=WritingSimulationAttemptStatus.SUBMITTED,
        ).exists():
            raise Http404
    if request.build_absolute_uri(reverse("study:github_copilot_callback")) != config.callback_url:
        return _return(attempt_id, "origin")
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    request.session[_FLOW] = {
        "state": state, "verifier": verifier, "user": request.user.pk,
        "started": int(time.time()), "attempt": attempt_id,
    }
    query = urlencode({
        "client_id": config.client_id, "redirect_uri": config.callback_url,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "scope": "offline_access", "allow_signup": "false",
    })
    response = redirect(f"{github_copilot.AUTHORIZE_URL}?{query}")
    response["Referrer-Policy"] = "no-referrer"
    return response


@never_cache
@require_GET
@sensitive_variables()
def callback(request):
    config = github_copilot.configuration()
    if config is None:
        raise Http404
    flow = request.session.get(_FLOW)
    state = request.GET.getlist("state")
    if (
        not flow or flow["user"] != request.user.pk or not 0 <= time.time() - flow["started"] < 600
        or len(state) != 1 or not constant_time_compare(flow["state"], state[0])
    ):
        return _return("", "failed")
    del request.session[_FLOW]
    code = request.GET.getlist("code")
    if "error" in request.GET or len(code) != 1 or not 0 < len(code[0]) <= 1024:
        return _return(flow["attempt"], "failed")
    try:
        linked = github_copilot.connect(request.user, config, code[0], flow["verifier"])
    except github_copilot.ConnectionError:
        logger.warning("GitHub Copilot authorization could not be completed")
        return _return(flow["attempt"], "failed")
    return _return(flow["attempt"], "connected" if linked else "other")


@never_cache
@require_POST
@csrf_protect
def disconnect(request):
    request.session.pop(_FLOW, None)
    github_copilot.links_for(request.user).delete()
    return _return("", "disconnected")
