import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass

from django.db import DatabaseError, transaction
from django.db.models import Q
from django.db.models.fields.json import KT
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_POST

from study.audio.pins import AudioPinError
from study.catalogue import registry as catalogue
from study.catalogue.loader import tache_two_subject_content_key
from study.simulation import live_conversation, oral_evaluation
from study.simulation.evaluation import DEADLINE_SECONDS, EvaluationError
from study.models import EO2PracticeAttempt, EO2TopicStatus, LiveSimulation, Prompt
from study.navigation.routing import subject_selection_url
from .helpers import _route_task, tache_two_publication


DEFAULT_CONSIGNE = (
    "Je travaille à l’accueil d’un centre culturel. Vous souhaitez participer à un atelier de photographie. "
    "Demandez-moi des renseignements pour choisir une formule qui vous convient."
)
OPINION_CONSIGNE = "Est-il préférable de découvrir une ville à pied plutôt qu’en voiture ? Pourquoi ?"
EO3_KEY_PREFIX = "eo3:"
# A quick report keeps its real HTTP status; a slower one streams keep-alive spaces first.
EVALUATION_GRACE_SECONDS = 20
EVALUATION_KEEPALIVE_SECONDS = 10
# The final keep-alive tick must still end before Gunicorn's 210 s worker timeout.
EVALUATION_DEADLINE_SECONDS = DEADLINE_SECONDS + 10
_EVALUATION_FAILED = {"error": "Le bilan a échoué. Votre transcription reste disponible."}
_EVALUATION_LATE = {"error": "Le bilan n’est pas arrivé à temps. Votre transcription reste disponible."}
# Each learner keeps their most recent exchanges, across subjects; older ones are deleted on save.
SAVED_SIMULATIONS = 30

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveSubject:
    key: str
    title: str
    prompt: str
    detail_url: str = ""
    role: object = None


def _live_subject(task, publication):
    if task.slug == "tache-3":
        if not publication:
            return LiveSubject(EO3_KEY_PREFIX + "default", "Découvrir une ville", OPINION_CONSIGNE)
        prompt = get_object_or_404(
            Prompt.objects.only("id", "text"), pk=publication["prompt_id"], theme__task=task,
            theme__is_active=True, is_active=True, response__is_active=True,
        )
        return LiveSubject(f"{EO3_KEY_PREFIX}{prompt.pk}", " ".join(prompt.text.split()), prompt.text,
                           reverse("study:response_detail", args=["eo", task.slug, prompt.pk]))
    if not publication:
        return LiveSubject("", "Choisir un atelier photo", DEFAULT_CONSIGNE)
    month_slug, batch_number, subject_number = (publication[k] for k in ("month_slug", "batch_number", "subject_number"))
    _, _, subject = tache_two_publication(month_slug, batch_number, subject_number)
    key = tache_two_subject_content_key(month_slug, batch_number, subject_number)
    if not Prompt.objects.filter(
        theme__task=task, content_key=key, is_active=True, response__is_active=True,
    ).exists():
        raise Http404
    return LiveSubject(key, subject.title, subject.prompt, reverse("study:task_subject_detail", kwargs={
        "part_slug": "eo", "task_slug": task.slug, **publication,
    }), subject)


def _route_name(task):
    return "study:eo_tache_three_live" if task.slug == "tache-3" else "study:eo_tache_two_live"


@never_cache
@require_GET
@ensure_csrf_cookie
def oral_live(request, task_slug, **publication):
    task = _route_task("eo", task_slug, request=request)
    subject = _live_subject(task, publication)
    route = _route_name(task)
    available = live_conversation.available_to(request.user, task)
    monologue = task.slug == "tache-3"
    subject_url = subject_selection_url(subject.detail_url, request) if subject.detail_url else ""
    saved, reopened = [], None
    if available:
        simulations = LiveSimulation.objects.filter(user=request.user, subject_key=subject.key)
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
    if monologue:
        session_back_url = reverse("study:task_browse", args=[task.part.slug, task.slug])
        session_back_label = "Sujets de la tâche 3"
        session_kicker = "Expression d’un point de vue"
        session_prompt = (
            "La simulation est indisponible pour le moment."
            if not available
            else "Écoutez la question, puis expliquez votre point de vue."
        )
        session_steps = [
            {"key": "reading", "name": "Consigne", "meta": "sans préparation", "about": "Écoutez la question, micro coupé."},
            {"key": "live", "name": "Point de vue", "meta": "4 min 30", "about": "Défendez votre opinion sans interruption."},
            {"key": "done", "name": "Bilan", "meta": "à chaud", "about": "Transcription et repères tirés de vos paroles."},
        ]
    else:
        session_back_url = subject_url or reverse("study:eo2_topic_picker")
        session_back_label = "Fiche du sujet" if subject_url else "Choisir un sujet"
        session_kicker = "Interaction"
        session_prompt = (
            "La simulation est indisponible pour le moment."
            if not available
            else "Écoutez la consigne, préparez vos questions, puis menez l’échange."
        )
        session_steps = [
            {"key": "prep", "name": "Préparation", "meta": "2 min", "about": "Le chrono part une fois le sujet lu, micro coupé."},
            {"key": "live", "name": "Échange", "meta": "3 min 30", "about": "Vous menez la conversation à voix haute."},
            {"key": "done", "name": "Bilan", "meta": "à chaud", "about": "Transcription et repères tirés de vos paroles."},
        ]
    return TemplateResponse(request, "study/simulation/oral_session.html", {
        "part": task.part,
        "task": task,
        "gemini_live_available": available,
        "monologue": task.slug == "tache-3",
        "token_url": reverse(route + "_token", kwargs=publication),
        "save_url": reverse(route + "_save", kwargs=publication),
        "evaluation_url": reverse(route + "_evaluation", kwargs=publication),
        "delete_url": subject_selection_url(reverse(route + "_delete", kwargs=publication), request),
        "saved_simulations": saved,
        "saved_simulation": reopened and {
            "id": reopened["id"], "rows": reopened["rows"], "elapsed": reopened["elapsed_ms"], "report": reopened["report"],
        },
        "scenario_prompt": subject.prompt,
        "subject": subject,
        "subject_url": subject_url,
        "debrief_back_url": session_back_url if monologue else reverse("study:eo2_topic_picker"),
        "debrief_back_label": "Choisir un autre sujet",
        "session_back_url": session_back_url,
        "session_back_label": session_back_label,
        "session_brand_icon": "headphones",
        "session_brand": f"Studio oral · {task.short_label}",
        "session_kicker": session_kicker,
        "session_title": "Simulation",
        "session_prompt": session_prompt,
        "session_selected_subject": subject.title if subject_url and not monologue else "",
        "session_steps": session_steps,
        "session_show_clock": True,
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
def oral_live_token(request, task_slug, **publication):
    if request.content_type != "application/json":
        return JsonResponse({"error": "Un objet JSON est requis."}, status=415)
    data = _session_request(request)
    if data is None:
        return JsonResponse({"error": "Un consentement explicite est requis."}, status=400)
    task = _route_task("eo", task_slug, request=request)
    instruction = None
    purpose = data.get("purpose")
    subject = _live_subject(task, publication)
    key = subject.key
    if purpose in ("attempt", "read_prompt"):
        instruction = (
            "Vous êtes le lecteur d’une consigne de français, pas l’interlocuteur. "
            "À la demande de lecture, lisez uniquement le passage suivant en français, "
            "mot pour mot, sans introduction, commentaire, réponse ni suggestion. Puis taisez-vous.\n"
            + subject.prompt
        )
    elif task.slug == "tache-3":
        instruction = ("Vous écoutez une prise de position en français, en continu. Gardez le silence, "
                       "même pendant les pauses. Ne posez pas de questions et ne corrigez pas le candidat.\n"
                       "Question posée : " + subject.prompt)
    elif subject.role:
        instruction = live_conversation.subject_instruction(subject.role, catalogue.tache_two_dialogues()[key])
    try:
        token = live_conversation.mint_token(request, task, data.get("pin"), instruction=instruction,
                                      exchange_grant=data.get("exchangeGrant"), subject_key=key)
    except AudioPinError as exc:
        return JsonResponse({"error": exc.code, "message": str(exc)}, status=exc.status)
    except live_conversation.LiveTokenError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    result = {"token": token, "model": live_conversation.MODEL}
    if purpose == "attempt":
        result["exchangeGrant"] = live_conversation.issue_grant(request, key, purpose="exchange")
    elif purpose == "exchange":
        result["reviewGrant"] = live_conversation.issue_grant(request, key, purpose="review")
    return JsonResponse(result)


@never_cache
@require_POST
@csrf_protect
@sensitive_post_parameters()
@sensitive_variables()
@transaction.atomic
def oral_live_save(request, task_slug, **publication):
    if request.content_type != "application/json":
        return JsonResponse({"error": "Un objet JSON est requis."}, status=415)
    task = _route_task("eo", task_slug, request=request)
    subject = _live_subject(task, publication)
    monologue = task_slug == "tache-3"
    if not live_conversation.available_to(request.user, task):
        return JsonResponse({"error": "L’enregistrement n’est pas disponible."}, status=403)
    try:
        data = oral_evaluation.simulation_data(request.read(oral_evaluation.MAX_BODY + 1), monologue=monologue)
    except EvaluationError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    if not monologue:
        key = request.headers.get("Idempotency-Key")
        try:
            attempt_id = uuid.uuid4() if key is None else uuid.UUID(key)
        except ValueError:
            return JsonResponse({"error": "Identifiant de séance invalide."}, status=400)
        attempt, created = EO2PracticeAttempt.objects.get_or_create(
            user=request.user, attempt=attempt_id, defaults={"subject_key": subject.key, "vocal": True},
        )
        if not created:
            if not attempt.vocal or attempt.subject_key != subject.key:
                return JsonResponse({"error": "Cette séance appartient à un autre exercice."}, status=409)
            if not attempt.live_simulation_id:
                return JsonResponse({"error": "Cette transcription n’est plus conservée."}, status=410)
            return JsonResponse({"id": str(attempt.live_simulation_id)}, status=201)
    simulation = LiveSimulation.objects.create(
        user=request.user, subject_key=subject.key, rows=data["rows"], elapsed_ms=data["elapsed"],
    )
    if not monologue:
        attempt.live_simulation = simulation
        attempt.save(update_fields=["live_simulation"])
        EO2TopicStatus.objects.update_or_create(user=request.user, subject_key=subject.key, defaults={"done": True})
    history = LiveSimulation.objects.filter(user=request.user)
    scope = {"subject_key__startswith": EO3_KEY_PREFIX}
    history = history.filter(**scope) if monologue else history.exclude(**scope)
    stale = list(history.values_list("pk", flat=True)[SAVED_SIMULATIONS:])
    if stale:
        LiveSimulation.objects.filter(pk__in=stale).delete()
    return JsonResponse({"id": str(simulation.pk)}, status=201)


@never_cache
@require_POST
@csrf_protect
@transaction.atomic
def oral_live_delete(request, task_slug, **publication):
    task = _route_task("eo", task_slug, request=request)
    subject = _live_subject(task, publication)
    try:
        pk = uuid.UUID(request.POST.get("simulation", ""))
    except ValueError:
        raise Http404
    # Explicit deletion also forgets the occurrence; automatic transcript expiry does not.
    EO2PracticeAttempt.objects.filter(user=request.user, subject_key=subject.key, live_simulation_id=pk).delete()
    deleted, _ = LiveSimulation.objects.filter(pk=pk, user=request.user, subject_key=subject.key).delete()
    if not deleted:
        raise Http404
    return redirect(subject_selection_url(reverse(_route_name(task), kwargs=publication), request))


@never_cache
@require_POST
@csrf_protect
@sensitive_post_parameters()
@sensitive_variables()
def oral_live_evaluation(request, task_slug, **publication):
    if request.content_type != "application/json":
        return JsonResponse({"error": "Un objet JSON est requis."}, status=415)
    task = _route_task("eo", task_slug, request=request)
    subject = _live_subject(task, publication)
    monologue = task_slug == "tache-3"
    try:
        data = oral_evaluation.request_data(request.read(oral_evaluation.MAX_BODY + 1), monologue=monologue)
        oral_evaluation.authorize(request, task, data.get("pin"), grant=data.get("reviewGrant"), subject_key=subject.key)
    except AudioPinError as exc:
        return JsonResponse({"error": exc.code, "message": str(exc)}, status=exc.status)
    except EvaluationError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    rows = data["rows"]
    simulation = None
    if "simulation" in data:
        saved = LiveSimulation.objects.filter(pk=data["simulation"], user=request.user, subject_key=subject.key).values_list(
            "rows", flat=True).first()
        # Only the exchange that was saved may carry this report.
        if saved and [{"speaker": row["speaker"], "text": row["text"]} for row in saved] == rows:
            simulation = data["simulation"]
    outcome, done = [], threading.Event()

    def keep(body, status):
        # Runs on the request thread, which owns the database connection.
        if status == 200 and simulation:
            try:
                sessions = LiveSimulation.objects.filter(pk=simulation)
                writable = Q(report__isnull=True)
                if body.get("scoreStatus") == "scored":
                    writable |= Q(report__scoreStatus="incomplete")
                if not sessions.filter(writable).update(report=body):
                    # Never mix marks from two assessments or replace a better saved report.
                    saved = sessions.values_list("report", flat=True).first()
                    if saved:
                        return {**saved, "previousReportKept": True}
            except DatabaseError:
                logger.exception("Oral evaluation: report not saved")
        return body

    def score():
        try:
            outcome.append((oral_evaluation.score(subject.prompt, rows, monologue=monologue), 200))
        except EvaluationError as exc:
            outcome.append(({"error": str(exc)}, exc.status))
        finally:
            done.set()

    deadline = time.monotonic() + EVALUATION_DEADLINE_SECONDS
    threading.Thread(target=score, daemon=True).start()
    if done.wait(EVALUATION_GRACE_SECONDS):
        body, status = outcome[0] if outcome else (_EVALUATION_FAILED, 500)
        return JsonResponse(keep(body, status), status=status)

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
            body = keep(body, status)
        yield json.dumps(body if status == 200 else {**body, "status": status}).encode()

    request.META.pop("HTTP_ACCEPT_ENCODING", None)  # GZipMiddleware would hold the spaces back.
    return StreamingHttpResponse(keep_alive(), content_type="application/json")
