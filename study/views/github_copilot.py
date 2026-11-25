"""Connect Copilot to the signed-in Heureux account, not to the login flow."""

import base64
import hashlib
import logging
import secrets
import time
from urllib.parse import parse_qsl, urlencode, urlsplit
from uuid import UUID

from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from django.utils.http import url_has_allowed_host_and_scheme
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


def _local_return_path(value):
    if (
        len(value) <= 4096 and value.startswith("/") and not value.startswith("//")
        and url_has_allowed_host_and_scheme(value, allowed_hosts=set())
    ):
        return value
    return reverse("study:settings")


def _return(path, status):
    parts = urlsplit(_local_return_path(path))
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "copilot"]
    response = redirect(parts._replace(query=urlencode([*query, ("copilot", status)])).geturl())
    response["Referrer-Policy"] = "no-referrer"
    return response


def _legacy_attempt_path(attempt_id):
    return reverse("study:ee1_simulation_attempt", args=[attempt_id]) if attempt_id else ""


@never_cache
@require_POST
@csrf_protect
@sensitive_variables()
def authorize(request):
    config = github_copilot.configuration()
    if config is None:
        raise Http404
    next_path = request.POST.get("next", "")
    if not next_path and (attempt_id := request.POST.get("attempt_id")):
        # A page opened before the deploy still submits its attempt ID.
        try:
            attempt_id = str(UUID(attempt_id))
        except ValueError:
            raise Http404 from None
        if not WritingSimulationAttempt.objects.filter(
            pk=attempt_id, user=request.user, task__part__slug="ee", task__slug="tache-1",
            status=WritingSimulationAttemptStatus.SUBMITTED,
        ).exists():
            raise Http404
        next_path = _legacy_attempt_path(attempt_id)
    next_path = _local_return_path(next_path)
    if request.build_absolute_uri(reverse("study:github_copilot_callback")) != config.callback_url:
        return _return(next_path, "origin")
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    request.session[_FLOW] = {
        "state": state, "verifier": verifier, "user": request.user.pk,
        "started": int(time.time()), "next": next_path,
    }
    query = urlencode({
        "client_id": config.client_id, "redirect_uri": config.callback_url,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "scope": "offline_access", "allow_signup": "false",
    })
    # End the same-origin form submission before navigating to GitHub.
    response = render(request, "study/account/github_copilot_authorize.html", {
        "authorization_url": f"{github_copilot.AUTHORIZE_URL}?{query}",
    })
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
    next_path = flow.get("next") or _legacy_attempt_path(flow.get("attempt"))
    code = request.GET.getlist("code")
    if "error" in request.GET or len(code) != 1 or not 0 < len(code[0]) <= 1024:
        return _return(next_path, "failed")
    try:
        linked = github_copilot.connect(request.user, config, code[0], flow["verifier"])
    except github_copilot.ConnectionError:
        logger.warning("GitHub Copilot authorization could not be completed")
        return _return(next_path, "failed")
    return _return(next_path, "connected" if linked else "other")


@never_cache
@require_POST
@csrf_protect
def disconnect(request):
    request.session.pop(_FLOW, None)
    github_copilot.links_for(request.user).delete()
    return _return("", "disconnected")
