import json
import logging
import threading
import time
import uuid

from django.db import DatabaseError
from django.db.models.fields.json import KT
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_POST

from study.audio.pins import AudioPinError
from study.catalogue import registry as catalogue
from study.catalogue.loader import tache_two_subject_content_key
from study.expression.eo.tache_2 import gemini_evaluation, gemini_live
from study.models import LiveSimulation, Prompt
from study.navigation.routing import subject_selection_url
from .helpers import _route_task, active_task_for_request, tache_two_publication


DEFAULT_CONSIGNE = (
    "Je travaille à l’accueil d’un centre culturel. Vous souhaitez participer à un atelier de photographie. "
    "Demandez-moi des renseignements pour choisir une formule qui vous convient."
)
# A quick report keeps its real HTTP status; a slower one streams keep-alive spaces first.
EVALUATION_GRACE_SECONDS = 20
EVALUATION_KEEPALIVE_SECONDS = 10
# The final keep-alive tick must still end before Gunicorn's 210 s worker timeout.
EVALUATION_DEADLINE_SECONDS = 190
_EVALUATION_FAILED = {"error": "Le bilan a échoué. Votre transcription reste disponible."}
_EVALUATION_LATE = {"error": "Groq n’a pas répondu à temps. Votre transcription reste disponible."}
# Each learner keeps their most recent exchanges, across subjects; older ones are deleted on save.
SAVED_SIMULATIONS = 30

logger = logging.getLogger(__name__)


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
    subject, key = None, ""
    subject_url = ""
    if publication:
        subject, key = _live_publication(task, **publication)
        subject_url = subject_selection_url(reverse("study:task_subject_detail", kwargs={
            "part_slug": "eo", "task_slug": "tache-2", **publication,
        }), request)
    available = gemini_live.available_to(request.user, task)
    saved, reopened = [], None
    if available:
        simulations = LiveSimulation.objects.filter(user=request.user, subject_key=key)
        # Only the figures the list shows, not each stored transcript and report.
        saved = list(simulations.values(
            "id", "created_at", score=KT("report__score"), nclc=KT("report__nclc"), status=KT("report__scoreStatus"),
        )[:5])
        try:
            pk = uuid.UUID(request.GET.get("simulation", ""))
        except ValueError:
            pk = None
        if pk:
            reopened = simulations.filter(pk=pk).values("id", "rows", "elapsed_ms", "report").first()
    return TemplateResponse(request, "study/expression/eo/tache_2/live.html", {
        "part": task.part,
        "task": task,
        "gemini_live_available": available,
        "token_url": reverse("study:eo_tache_two_live_token", kwargs=publication),
        "save_url": reverse("study:eo_tache_two_live_save", kwargs=publication),
        "evaluation_url": reverse("study:eo_tache_two_live_evaluation", kwargs=publication),
        "saved_simulations": saved,
        "saved_simulation": reopened and {
            "id": reopened["id"], "rows": reopened["rows"], "elapsed": reopened["elapsed_ms"], "report": reopened["report"],
        },
        "scenario_prompt": subject.prompt if subject else DEFAULT_CONSIGNE,
        "subject": subject,
        "subject_url": subject_url,
    })


@sensitive_variables()
def _session_request(request):
    # Only small authorization payloads, never learner content.
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
    if (len(data) != len(pairs) or data.keys() - {"consent", "pin", "purpose", "exchangeGrant"} or data.get("consent") is not True
            or ("purpose" in data and data["purpose"] not in ("attempt", "exchange", "read_prompt"))):
        return None
    if data.get("purpose") == "exchange":
        grant = data.get("exchangeGrant")
        if "pin" in data or not isinstance(grant, str) or not grant.isascii() or not 1 <= len(grant) <= 256:
            return None
    elif "exchangeGrant" in data:
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
@sensitive_variables()
def eo_tache_two_live_token(request, **publication):
    if request.content_type != "application/json":
        return JsonResponse({"error": "Un objet JSON est requis."}, status=415)
    data = _session_request(request)
    if data is None:
        return JsonResponse({"error": "Un consentement explicite est requis."}, status=400)
    task = active_task_for_request(request, "eo", "tache-2")
    instruction = None
    purpose = data.get("purpose")
    subject, key = _live_publication(task, **publication) if publication else (None, "")
    if purpose in ("attempt", "read_prompt"):
        instruction = (
            "Vous êtes le lecteur d’une consigne de français, pas l’interlocuteur. "
            "À la demande de lecture, lisez uniquement le passage suivant en français, "
            "mot pour mot, sans introduction, commentaire, réponse ni suggestion. Puis taisez-vous.\n"
            + (subject.prompt if subject else DEFAULT_CONSIGNE)
        )
    elif subject:
        instruction = gemini_live.subject_instruction(subject, catalogue.tache_two_dialogues()[key])
    try:
        token = gemini_live.mint_token(request, task, data.get("pin"), instruction=instruction,
                                      exchange_grant=data.get("exchangeGrant"), subject_key=key)
    except AudioPinError as exc:
        return JsonResponse({"error": exc.code, "message": str(exc)}, status=exc.status)
    except gemini_live.LiveTokenError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    result = {"token": token, "model": gemini_live.MODEL}
    if purpose == "attempt":
        result["exchangeGrant"] = gemini_live.issue_grant(request, key, purpose="exchange")
    elif purpose == "exchange":
        result["reviewGrant"] = gemini_live.issue_grant(request, key, purpose="review")
    return JsonResponse(result)


@never_cache
@require_POST
@csrf_protect
@sensitive_post_parameters()
@sensitive_variables()
def eo_tache_two_live_save(request, **publication):
    if request.content_type != "application/json":
        return JsonResponse({"error": "Un objet JSON est requis."}, status=415)
    task = active_task_for_request(request, "eo", "tache-2")
    _, key = _live_publication(task, **publication) if publication else (None, "")
    if not gemini_live.available_to(request.user, task):
        return JsonResponse({"error": "L’enregistrement n’est pas disponible."}, status=403)
    try:
        data = gemini_evaluation.simulation_data(request.read(gemini_evaluation.MAX_BODY + 1))
    except gemini_evaluation.EvaluationError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    simulation = LiveSimulation.objects.create(
        user=request.user, subject_key=key, rows=data["rows"], elapsed_ms=data["elapsed"],
    )
    stale = list(LiveSimulation.objects.filter(user=request.user).values_list("pk", flat=True)[SAVED_SIMULATIONS:])
    if stale:
        LiveSimulation.objects.filter(pk__in=stale).delete()
    return JsonResponse({"id": str(simulation.pk)}, status=201)


@never_cache
@require_POST
@csrf_protect
@sensitive_post_parameters()
@sensitive_variables()
def eo_tache_two_live_evaluation(request, **publication):
    if request.content_type != "application/json":
        return JsonResponse({"error": "Un objet JSON est requis."}, status=415)
    task = active_task_for_request(request, "eo", "tache-2")
    subject, key = _live_publication(task, **publication) if publication else (None, "")
    try:
        data = gemini_evaluation.request_data(request.read(gemini_evaluation.MAX_BODY + 1))
        gemini_evaluation.authorize(request, task, data.get("pin"), grant=data.get("reviewGrant"), subject_key=key)
    except AudioPinError as exc:
        return JsonResponse({"error": exc.code, "message": str(exc)}, status=exc.status)
    except gemini_evaluation.EvaluationError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    prompt, rows = subject.prompt if subject else DEFAULT_CONSIGNE, data["rows"]
    simulation = None
    if "simulation" in data:
        saved = LiveSimulation.objects.filter(pk=data["simulation"], user=request.user, subject_key=key).values_list(
            "rows", flat=True).first()
        # Only the exchange that was saved may carry this report.
        if saved and [{"speaker": row["speaker"], "text": row["text"]} for row in saved] == rows:
            simulation = data["simulation"]
    outcome, done = [], threading.Event()

    def keep(body, status):
        # Runs on the request thread, which owns the database connection.
        if status == 200 and simulation:
            try:
                LiveSimulation.objects.filter(pk=simulation).update(report=body)
            except DatabaseError:
                logger.exception("EO2 evaluation: report not saved")

    def score():
        try:
            outcome.append((gemini_evaluation.score(prompt, rows), 200))
        except gemini_evaluation.EvaluationError as exc:
            outcome.append(({"error": str(exc)}, exc.status))
        finally:
            done.set()

    deadline = time.monotonic() + EVALUATION_DEADLINE_SECONDS
    threading.Thread(target=score, daemon=True).start()
    if done.wait(EVALUATION_GRACE_SECONDS):
        body, status = outcome[0] if outcome else (_EVALUATION_FAILED, 500)
        keep(body, status)
        return JsonResponse(body, status=status)

    # Render's Cloudflare edge drops a request that sends nothing for 100 s (HTTP 524).
    # Send the headers now, then JSON-insignificant spaces until Groq answers.
    def keep_alive():
        try:
            yield b" "
            while not done.wait(EVALUATION_KEEPALIVE_SECONDS) and time.monotonic() < deadline:
                yield b" "
        except GeneratorExit:
            # The learner left mid-report; its saved exchange still receives Groq's answer.
            if simulation and done.wait(max(0, deadline - time.monotonic())) and outcome:
                keep(*outcome[0])
            raise
        if not done.is_set():
            body, status = _EVALUATION_LATE, 504
        else:
            body, status = outcome[0] if outcome else (_EVALUATION_FAILED, 500)
            keep(body, status)
        yield json.dumps(body if status == 200 else {**body, "status": status}).encode()

    request.META.pop("HTTP_ACCEPT_ENCODING", None)  # GZipMiddleware would hold the spaces back.
    return StreamingHttpResponse(keep_alive(), content_type="application/json")
