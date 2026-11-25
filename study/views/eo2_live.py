import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import chain

from django.core import signing
from django.db import DatabaseError, transaction
from django.db.models import Count, Max, Q
from django.db.models.fields.json import KT
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.decorators.vary import vary_on_headers

from study.audio.pins import AudioPinError
from study.catalogue import registry as catalogue
from study.catalogue.loader import tache_two_subject_content_key
from study.simulation import live_conversation, oral_evaluation
from study.simulation.evaluation import DEADLINE_SECONDS, PROVIDER_LABELS, EvaluationError, available_providers
from study.models import EO2PracticeAttempt, EO2TopicStatus, LiveSimulation, Prompt
from study.navigation.routing import subject_selection_url
from .eo2_practice import practice_topics
from .helpers import _route_task, tache_two_publication
from .simulation import (
    PickerSubject,
    picker_rows,
    render_subject_picker,
    saved_session_context,
    studio_navigation,
    subject_picker_context,
)


DEFAULT_CONSIGNE = (
    "Je travaille à l’accueil d’un centre culturel. Vous souhaitez participer à un atelier de photographie. "
    "Demandez-moi des renseignements pour choisir une formule qui vous convient."
)
OPINION_CONSIGNE = "Est-il préférable de découvrir une ville à pied plutôt qu’en voiture ? Pourquoi ?"
EO3_KEY_PREFIX = "eo3:"
ORAL_ALTERNATE_PROVIDERS = ("gemini", "cloudflare")
ORAL_AUTOMATIC_PROVIDERS = ("cloudflare", "groq")
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


def _opinion_prompts(task):
    return Prompt.objects.filter(theme__task=task, theme__is_active=True, is_active=True, response__is_active=True)


@require_GET
@vary_on_headers("X-Requested-With")
def opinion_picker(request):
    task = _route_task("eo", "tache-3", request=request)
    if not (task.available and task.part.available):
        raise Http404
    counts = {
        row["subject_key"]: row for row in LiveSimulation.objects.filter(
            user=request.user, subject_key__startswith=EO3_KEY_PREFIX,
        ).values("subject_key").annotate(count=Count("pk"), latest=Max("created_at"))
    }

    prompts = _opinion_prompts(task).order_by("theme__name", "number", "pk").values_list(
        "pk", "text", "theme__slug", "theme__display_name",
    )
    training = PickerSubject(f"{EO3_KEY_PREFIX}default", OPINION_CONSIGNE, "entrainement",
                             "Sujet d’entraînement", "Sujet d’entraînement")
    subjects = chain((training,), (
        PickerSubject(f"{EO3_KEY_PREFIX}{pk}", title, theme, label, label)
        for pk, title, theme, label in prompts.iterator()
    ))
    context = subject_picker_context(request, subjects, counts)

    def row_for(subject):
        token = subject.key.removeprefix(EO3_KEY_PREFIX)
        return {
            "row_id": f"topic-{token}",
            "url": reverse("study:eo_tache_three_live", args=() if token == "default" else (token,)),
        }

    picker_rows(context, counts, row_for)
    context["task"] = task
    context["picker"] = {
        "back_url": reverse("study:simulation_track", args=["eo"]),
        "back_label": "Expression orale", "kicker": "Simulation · EO Tâche 3",
        "title": "Choisir un sujet", "heading_id": "eo3-title",
        "format": "4 min 30 · sans préparation",
        "tone": "sim-tone--eo", "icon": "microphone", "results_id": "eo3-topic-results",
        "show_practice_summary": True,
    }
    return render_subject_picker(request, context)


def _live_subject(task, publication):
    if task.slug == "tache-3":
        if not publication:
            return LiveSubject(EO3_KEY_PREFIX + "default", "Découvrir une ville", OPINION_CONSIGNE)
        prompt = get_object_or_404(
            _opinion_prompts(task).only("text"), pk=publication["prompt_id"],
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


def _subject_key(task_slug, publication):
    if task_slug == "tache-3":
        return f"{EO3_KEY_PREFIX}{publication.get('prompt_id', 'default')}"
    if publication:
        return tache_two_subject_content_key(
            publication["month_slug"], publication["batch_number"], publication["subject_number"],
        )
    return ""


def _studio_navigation(request, task, subject, publication):
    if task.slug == "tache-3":
        picker = "study:eo3_topic_picker"
        selected = publication.get("prompt_id")
        if not selected:
            return studio_navigation(request, picker)
        prompts = _opinion_prompts(task)
        group = prompts.filter(pk=selected).values_list(
            "theme_id", "theme__slug", "theme__display_name",
        ).first()
        if group is None:
            return studio_navigation(request, picker)
        theme_id, theme, label = group
        siblings = prompts.filter(theme_id=theme_id).order_by("family__order", "family__name", "number", "pk")
        return studio_navigation(
            request, picker, theme=theme, label=label, selected=selected,
            subjects=((pk, title, reverse(_route_name(task), args=[pk])) for pk, title in siblings.values_list("pk", "text")),
        )
    picker = "study:eo2_topic_picker"
    topics = practice_topics() if publication else {}
    topic = topics.get(subject.key)
    if not topic:
        return studio_navigation(request, picker)
    siblings = [item for item in topics.values() if item.theme_slug == topic.theme_slug]
    active = set(Prompt.objects.filter(
        theme__task=task, is_active=True, response__is_active=True,
        content_key__in=[item.key for item in siblings],
    ).values_list("content_key", flat=True))
    return studio_navigation(
        request, picker, theme=topic.theme_slug, label=topic.theme, selected=topic.key,
        subjects=((item.key, item.title, item.simulation_url) for item in siblings if item.key in active),
    )


def _oral_history_url(request, route, publication, **query):
    if "seances" in request.GET:
        query["seances"] = request.GET["seances"]
    return subject_selection_url(reverse(route, kwargs=publication, query=query), request)


@never_cache
@require_GET
@ensure_csrf_cookie
def oral_live(request, task_slug, **publication):
    task = _route_task("eo", task_slug, request=request)
    key = _subject_key(task_slug, publication)
    simulations = LiveSimulation.objects.filter(user=request.user, subject_key=key)
    try:
        pk = uuid.UUID(request.GET.get("simulation", ""))
    except ValueError:
        pk = None
    reopened = None
    if pk:
        selected = simulations.filter(pk=pk)
        reopened = selected.values(
            "id", "rows", "elapsed_ms", "report", "snapshot",
            **{f"has_{provider}": Q(provider_reports__has_key=provider) for provider in ORAL_ALTERNATE_PROVIDERS},
        ).first()
    try:
        subject = _live_subject(task, publication)
    except Http404:
        if not reopened:
            raise
        subject = LiveSubject(key, "Sujet enregistré", "")
        available = False
    else:
        available = live_conversation.available_to(request.user, task)
    route = _route_name(task)
    monologue = task.slug == "tache-3"
    subject_url = subject_selection_url(subject.detail_url, request) if subject.detail_url else ""
    configured = available_providers() if live_conversation.pin_available_to(request.user, task) else set()
    auto_provider = next((provider for provider in ORAL_AUTOMATIC_PROVIDERS if provider in configured), "")
    selected_provider = auto_provider or next((provider for provider in PROVIDER_LABELS if provider in configured), "groq")
    can_assess = bool(configured) and (not reopened or bool(reopened["snapshot"].get("prompt")))
    providers = set(configured) if can_assess else set()
    if reopened:
        cached = {provider for provider in ORAL_ALTERNATE_PROVIDERS if reopened[f"has_{provider}"]}
        if reopened["report"]:
            cached.add("groq")
        providers.update(cached)
        selected_provider = next((provider for provider in PROVIDER_LABELS if provider in cached), selected_provider)
        if selected_provider in cached and selected_provider != "groq":
            reopened["report"] = _oral_report(selected, selected_provider)
        saved_prompt = reopened["snapshot"].get("prompt") or "Consigne d’origine non enregistrée."
        subject = LiveSubject(key, reopened["snapshot"].get("title", subject.title),
                              saved_prompt, subject.detail_url)

    def saved_row(item):
        if item["status"] == "scored":
            item["summary"] = f'{item["score"]}/20 · NCLC {item["nclc"]}'
        elif item["has_alternate"]:
            item["summary"] = "Bilan disponible"
        else:
            item["summary"] = "Bilan sans note" if item["status"] else "Sans bilan"
        item["url"] = _oral_history_url(request, route, publication, simulation=item["id"])
        return item

    history = saved_session_context(request, simulations.values(
        "id", "created_at", score=KT("report__score"), nclc=KT("report__nclc"), status=KT("report__scoreStatus"),
        has_alternate=Q(provider_reports__has_any_keys=ORAL_ALTERNATE_PROVIDERS),
    ), saved_row)
    if monologue:
        session_kicker = "Expression d’un point de vue"
        session_steps = [
            {"key": "reading", "name": "Consigne", "meta": "sans préparation"},
            {"key": "live", "name": "Point de vue", "meta": "4 min 30"},
            {"key": "done", "name": "Bilan", "meta": ""},
        ]
    else:
        session_kicker = "Interaction"
        session_steps = [
            {"key": "prep", "name": "Préparation", "meta": "2 min", "about": "Le chrono part une fois le sujet lu, micro coupé."},
            {"key": "live", "name": "Échange", "meta": "3 min 30"},
            {"key": "done", "name": "Bilan", "meta": ""},
        ]
    navigation = _studio_navigation(request, task, subject, publication)
    return TemplateResponse(request, "study/simulation/oral_session.html", {
        **navigation,
        "part": task.part,
        "task": task,
        "gemini_live_available": available,
        "monologue": task.slug == "tache-3",
        "token_url": reverse(route + "_token", kwargs=publication),
        "save_url": reverse(route + "_save", kwargs=publication),
        "evaluation_url": reverse(route + "_evaluation", kwargs=publication),
        "evaluation_provider": selected_provider,
        "evaluation_provider_label": PROVIDER_LABELS[selected_provider],
        "evaluation_providers": [(key, label) for key, label in PROVIDER_LABELS.items() if key in providers],
        "evaluation_enabled": can_assess,
        "auto_evaluation": auto_provider,
        "auto_evaluation_label": PROVIDER_LABELS.get(auto_provider, ""),
        "session_title_assessment": bool(available or reopened) and len(providers) > 1,
        "assessment_action_hidden": True,
        "delete_url": _oral_history_url(request, route + "_delete", publication),
        **history,
        "saved_simulation": reopened and {
            "id": reopened["id"], "rows": reopened["rows"], "elapsed": reopened["elapsed_ms"], "report": reopened["report"],
        },
        "scenario_prompt": subject.prompt,
        "subject": subject,
        "subject_url": subject_url,
        "debrief_back_url": navigation["session_task_url"],
        "debrief_back_label": "Choisir un autre sujet",
        "session_brand_icon": "headphones",
        "session_brand": f"Studio oral · {task.short_label}",
        "session_kicker": session_kicker,
        "session_prompt": "" if available else "La simulation est indisponible pour le moment.",
        "session_debrief_prompt": subject.prompt,
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
    if (len(data) != len(pairs) or data.keys() - {"consent", "pin", "purpose", "exchangeGrant", "reviewProvider"} or data.get("consent") is not True
            or ("purpose" in data and data["purpose"] not in ("attempt", "exchange", "read_prompt"))):
        return None
    if "reviewProvider" in data and (data.get("purpose") != "attempt" or data["reviewProvider"] not in ORAL_AUTOMATIC_PROVIDERS):
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
        token, review_provider = live_conversation.mint_token(
            request, task, data.get("pin"), instruction=instruction,
            exchange_grant=data.get("exchangeGrant"), subject_key=key,
        )
    except AudioPinError as exc:
        return JsonResponse({"error": exc.code, "message": str(exc)}, status=exc.status)
    except live_conversation.LiveTokenError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    result = {"token": token, "model": live_conversation.MODEL}
    if purpose == "attempt":
        requested_provider = data.get("reviewProvider", "")
        result["exchangeGrant"] = live_conversation.issue_grant(
            request, key, purpose="exchange",
            review_provider=requested_provider if requested_provider in available_providers() else "",
        )
        result["snapshot"] = {"prompt": subject.prompt, "title": subject.title}
        result["snapshotGrant"] = live_conversation.grant_signer(request, key, purpose="snapshot").sign_object(
            result["snapshot"], compress=True,
        )
    elif review_provider:
        result["reviewGrant"] = live_conversation.issue_grant(request, key, purpose=f"review:{review_provider}")
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
    _route_task("eo", task_slug, request=request)
    key = _subject_key(task_slug, publication)
    monologue = task_slug == "tache-3"
    try:
        data = oral_evaluation.simulation_data(request.read(oral_evaluation.MAX_BODY + 1), monologue=monologue)
        snapshot = live_conversation.grant_signer(request, key, purpose="snapshot").unsign_object(
            data["snapshotGrant"], max_age=3600,
        )
    except EvaluationError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    except signing.BadSignature:
        return JsonResponse({"error": "L’autorisation de cette séance n’est plus valide."}, status=403)
    if not monologue:
        idempotency_key = request.headers.get("Idempotency-Key")
        try:
            attempt_id = uuid.uuid4() if idempotency_key is None else uuid.UUID(idempotency_key)
        except ValueError:
            return JsonResponse({"error": "Identifiant de séance invalide."}, status=400)
        attempt, created = EO2PracticeAttempt.objects.get_or_create(
            user=request.user, attempt=attempt_id, defaults={"subject_key": key, "vocal": True},
        )
        if not created:
            if not attempt.vocal or attempt.subject_key != key:
                return JsonResponse({"error": "Cette séance appartient à un autre exercice."}, status=409)
            if not attempt.live_simulation_id:
                return JsonResponse({"error": "Cette transcription n’est plus conservée."}, status=410)
            return JsonResponse({"id": str(attempt.live_simulation_id)}, status=201)
    simulation = LiveSimulation.objects.create(
        user=request.user, subject_key=key, snapshot=snapshot, rows=data["rows"], elapsed_ms=data["elapsed"],
    )
    if not monologue:
        attempt.live_simulation = simulation
        attempt.save(update_fields=["live_simulation"])
        EO2TopicStatus.objects.update_or_create(user=request.user, subject_key=key, defaults={"done": True})
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
    key = _subject_key(task_slug, publication)
    try:
        pk = uuid.UUID(request.POST.get("simulation", ""))
    except ValueError:
        raise Http404
    # Explicit deletion also forgets the occurrence; automatic transcript expiry does not.
    EO2PracticeAttempt.objects.filter(user=request.user, subject_key=key, live_simulation_id=pk).delete()
    deleted, _ = LiveSimulation.objects.filter(pk=pk, user=request.user, subject_key=key).delete()
    if not deleted:
        raise Http404
    return redirect(_oral_history_url(request, _route_name(task), publication))


@never_cache
@require_http_methods(["GET", "POST"])
@csrf_protect
@sensitive_post_parameters()
@sensitive_variables()
def oral_live_evaluation(request, task_slug, **publication):
    task = _route_task("eo", task_slug, request=request)
    key = _subject_key(task_slug, publication)
    sessions = LiveSimulation.objects.filter(user=request.user, subject_key=key)
    if request.method == "GET":
        provider = request.GET.get("provider", "groq")
        try:
            pk = uuid.UUID(request.GET.get("simulation", ""))
        except ValueError:
            return JsonResponse({"error": "Identifiant de séance invalide."}, status=400)
        if provider not in PROVIDER_LABELS:
            return JsonResponse({"error": "Modèle d’évaluation invalide."}, status=400)
        selected = sessions.filter(pk=pk)
        report = _oral_report(selected, provider)
        if (not report or report.get("scoreStatus") == "incomplete") and _claim_active(
            selected.values_list(f"evaluation_claims__{provider}", flat=True).first(), timezone.now(),
        ):
            return JsonResponse({"status": "processing"}, status=202)
        if report is None:
            return JsonResponse({"error": "Aucun bilan enregistré pour ce modèle."}, status=404)
        return JsonResponse(report)
    if request.content_type != "application/json":
        return JsonResponse({"error": "Un objet JSON est requis."}, status=415)
    monologue = task_slug == "tache-3"
    try:
        data = oral_evaluation.request_data(request.read(oral_evaluation.MAX_BODY + 1), monologue=monologue)
        provider = data.get("provider", "groq")
        rows = data["rows"]
        scored_session = None
        claim = None

        def authorization_error():
            try:
                oral_evaluation.authorize(
                    request, task, data.get("pin"), grant=data.get("reviewGrant"), subject_key=key, provider=provider,
                )
            except AudioPinError as exc:
                return JsonResponse({"error": exc.code, "message": str(exc)}, status=exc.status)
            except EvaluationError as exc:
                return JsonResponse({"error": str(exc)}, status=exc.status)

        if "simulation" in data:
            scored_session = sessions.filter(pk=data["simulation"])
            with transaction.atomic():
                session = get_object_or_404(scored_session.select_for_update())
                original = [{"speaker": row["speaker"], "text": row["text"]} for row in session.rows]
                if original != rows:
                    return JsonResponse({"error": "Cette transcription ne correspond pas à la séance enregistrée."}, status=400)
                previous = _stored_report(session, provider)
                if previous and previous.get("scoreStatus") != "incomplete":
                    return JsonResponse(previous)
                if _claim_active(session.evaluation_claims.get(provider), timezone.now()):
                    return JsonResponse({"status": "processing"}, status=202)
                prompt = session.snapshot.get("prompt")
                if not prompt:
                    return JsonResponse({"error": "La consigne d’origine n’a pas été conservée."}, status=409)
                if error := authorization_error():
                    return error
                claim = timezone.now().isoformat()
                session.evaluation_claims[provider] = claim
                session.save(update_fields=["evaluation_claims"])
        else:
            prompt = _live_subject(task, publication).prompt
            if not live_conversation.available_to(request.user, task):
                raise EvaluationError(403, "Le bilan n’est pas disponible.")
            if error := authorization_error():
                return error
    except EvaluationError as exc:
        return JsonResponse({"error": str(exc)}, status=exc.status)
    outcome, done = [], threading.Event()

    def keep(body, status):
        # Runs on the request thread, which owns the database connection.
        if scored_session is not None:
            try:
                with transaction.atomic():
                    field = "report" if provider == "groq" else "provider_reports"
                    session = scored_session.select_for_update().only(field, "evaluation_claims").first()
                    if session is None or session.evaluation_claims.get(provider) != claim:
                        return body
                    del session.evaluation_claims[provider]
                    fields = ["evaluation_claims"]
                    if status == 200:
                        saved = _stored_report(session, provider)
                        if saved and body.get("scoreStatus") != "scored":
                            body = {**saved, "previousReportKept": True}
                        else:
                            if provider == "groq":
                                session.report = body
                            else:
                                session.provider_reports[provider] = body
                            fields.append(field)
                    session.save(update_fields=fields)
            except DatabaseError:
                logger.exception("Oral evaluation: report not saved")
        return body

    def score():
        try:
            outcome.append((oral_evaluation.score(prompt, rows, monologue=monologue, provider=provider), 200))
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
    # Send the headers now, then JSON-insignificant spaces until the grader answers.
    def keep_alive():
        try:
            yield b" "
            while not done.wait(EVALUATION_KEEPALIVE_SECONDS) and time.monotonic() < deadline:
                yield b" "
        except GeneratorExit:
            # The learner left mid-report; its saved exchange still receives the answer.
            if scored_session is not None and done.wait(max(0, deadline - time.monotonic())) and outcome:
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


def _oral_report(sessions, provider):
    field = "report" if provider == "groq" else f"provider_reports__{provider}"
    return sessions.values_list(field, flat=True).first()


def _stored_report(session, provider):
    return session.report if provider == "groq" else session.provider_reports.get(provider)


def _claim_active(claim, now):
    return bool(claim and now - datetime.fromisoformat(claim) < timedelta(seconds=EVALUATION_DEADLINE_SECONDS))
