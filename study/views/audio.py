import json
import re

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseNotModified, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST, require_safe

from .. import catalogue
from ..eo3_audio import (
    NarrationError, SAMPLE_GROUP, narration_presentation, narration_spec,
)
from ..models import EO3Narration, FrenchNarration
from ..french_audio import (
    SpeechError, accessible_recordings, enqueue, generate_prepared, media_url,
    resolve_sources, speech_spec,
)


def _audio_json(data, status=200):
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def eo3_audio_prepare(request, group, fingerprint):
    if not settings.EO3_AUDIO_ENABLED or group != "culture-p1":
        raise Http404
    if settings.ON_VERCEL:
        return _audio_json({"message": "La préparation est disponible sur le déploiement Render."}, 503)
    try:
        if len(request.body) > 1000:
            raise ValueError
        data = json.loads(request.body)
        if not isinstance(data, dict) or data.get("confirm_cost") is not True:
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        return _audio_json({"message": "Confirmez explicitement le coût de préparation de cet unique extrait."}, 400)
    model = catalogue.tache_three_models()[SAMPLE_GROUP]
    try:
        spec = narration_spec(model)
        if spec.fingerprint != fingerprint:
            return _audio_json({"message": "La voix ou le texte a changé. Rechargez la page."}, 409)
        if not EO3Narration.objects.filter(pk=fingerprint).exists():
            if not settings.EO3_AUDIO_SAMPLE_ENABLED:
                return _audio_json({"message": "La préparation du premier extrait est désactivée."}, 403)
            FrenchNarration.objects.get_or_create(
                fingerprint=fingerprint,
                defaults={
                    "text": spec.text, "voice_id": spec.voice_id, "model_id": spec.model_id,
                    "target_group": SAMPLE_GROUP, "requested_by": request.user,
                },
            )
            generate_prepared(fingerprint)
    except NarrationError as exc:
        return _audio_json({
            "message": f"Préparation non terminée : {exc} Aucune nouvelle tentative automatique.",
        }, 409)
    return _audio_json({
        "state": "ready",
        "html": render_to_string(
            "study/partials/eo3_audio.html", {
                "audio": narration_presentation(model),
                "player_id": "eo3-response-player" if data.get("player_id") == "eo3-response-player" else "",
            }, request,
        ),
    })


@login_required
@require_POST
def french_audio_resolve(request):
    reply = _audio_json

    if not settings.FRENCH_AUDIO_ENABLED:
        return reply({"error": "disabled", "message": "La voix naturelle est désactivée."}, 503)
    if len(request.body) > 150000:
        return reply({"error": "length", "message": "Demande de lecture trop longue."}, 413)
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        return reply({"error": "input", "message": "Demande de lecture invalide."}, 400)
    try:
        text, owner = resolve_sources(
            data.get("sources"), request.user.pk, consent=data.get("consent") is True,
        )
        spec = speech_spec(text, owner)
        recording = accessible_recordings(request.user.pk).filter(pk=spec.fingerprint).first()
        can_request = (
            settings.FRENCH_AUDIO_GENERATION_ENABLED
            and settings.FRENCH_AUDIO_CHARACTER_BUDGET > 0
        )
        if data.get("prepare") is True:
            if not can_request:
                raise SpeechError(
                    "disabled", "La préparation est désactivée en attendant l’approbation du premier extrait.", 403,
                )
            if settings.ON_VERCEL:
                raise SpeechError("host", "La préparation est disponible sur le déploiement Render.", 503)
            if data.get("confirm_cost") is not True:
                raise SpeechError("confirmation", "Confirmez explicitement le coût avant la préparation.", 400)
            recording = enqueue(spec, request.user.pk, owner)
            try:
                generate_prepared(recording.pk)
            except NarrationError as exc:
                raise SpeechError("preparation", f"Préparation non terminée : {exc}", 409) from None
            recording.refresh_from_db()
        if recording:
            if recording.status == "ready":
                return reply({"state": "ready", "url": media_url(recording)})
            messages = {
                "pending": "Cet enregistrement attend votre confirmation explicite de préparation.",
                "working": "Cet enregistrement est en cours de préparation. Aucune nouvelle génération n’a été lancée.",
                "failed": "La préparation a échoué. Un opérateur doit vérifier la consommation avant toute nouvelle tentative.",
            }
            return reply({
                "state": recording.status,
                "message": messages[recording.status],
                "request_id": recording.pk,
                "can_request": can_request and recording.status == "pending",
            })
        return reply({
            "state": "missing", "can_request": can_request, "characters": len(text),
            "message": "Enregistrement non préparé. La voix de l’appareil reste disponible.",
        })
    except SpeechError as exc:
        return reply({"error": exc.code, "message": str(exc)}, exc.status)


@login_required
@require_safe
def french_audio(request, fingerprint):
    if not settings.FRENCH_AUDIO_ENABLED:
        raise Http404
    recording = get_object_or_404(
        accessible_recordings(request.user.pk), pk=fingerprint, status="ready",
    )
    try:
        current = speech_spec(recording.text, recording.owner_id)
    except SpeechError:
        raise Http404 from None
    if current.fingerprint != fingerprint:
        raise Http404
    response = audio_response(request, bytes(recording.audio), fingerprint)
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_safe
def eo3_audio(request, group, fingerprint):
    if not settings.EO3_AUDIO_ENABLED:
        raise Http404
    model = catalogue.tache_three_models().get(f"eo/tache-3/{group}")
    if model is None:
        raise Http404
    try:
        spec = narration_spec(model)
    except NarrationError:
        raise Http404 from None
    if fingerprint != spec.fingerprint:
        raise Http404
    recording = get_object_or_404(EO3Narration, fingerprint=fingerprint, group=model.group)
    return audio_response(request, bytes(recording.audio), fingerprint)


def audio_response(request, audio, fingerprint):
    size = len(audio)
    etag = f'"{fingerprint}"'
    start, end, status = 0, size - 1, 200
    requested_range = request.headers.get("Range")
    if request.method == "HEAD":
        requested_range = None
    if request.headers.get("If-Range", etag) != etag:
        requested_range = None
    if requested_range:
        match = re.fullmatch(r"bytes=([0-9]{0,20})-([0-9]{0,20})", requested_range)
        if match and any(match.groups()):
            first, last = match.groups()
            if first:
                start = int(first)
                end = min(int(last), size - 1) if last else size - 1
            elif int(last):
                start = max(0, size - int(last))
            else:
                start = size
        else:
            start = size
        if not 0 <= start <= end < size:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            response["Cache-Control"] = "private, no-store"
            return response
        status = 206
    if status == 200 and request.headers.get("If-None-Match") == etag:
        response = HttpResponseNotModified()
    else:
        response = HttpResponse(
            b"" if request.method == "HEAD" else audio[start:end + 1],
            content_type="audio/mpeg", status=status,
        )
        response["Content-Length"] = str(end - start + 1)
        # Ranges use MP3 byte offsets; middleware must not add another encoding.
        response["Content-Encoding"] = "identity"
        if status == 206:
            response["Content-Range"] = f"bytes {start}-{end}/{size}"
    response["ETag"] = etag
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, no-cache"
    response["Content-Encoding"] = "identity"
    return response
