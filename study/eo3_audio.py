"""Explicit, cached narration of reviewed public EO3 models only."""

from dataclasses import dataclass
import hashlib
from http.client import HTTPException
import json
import re

import httpx
from elevenlabs.client import ElevenLabs
from elevenlabs.core.api_error import ApiError
from elevenlabs.types import VoiceSettings

from django.conf import settings
from django.db import transaction
from django.urls import reverse

from .models import EO3Narration, FrenchNarration, FrenchNarrationBudget


OUTPUT_FORMAT = "mp3_44100_64"
MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_ERROR_BYTES = 4096
SAMPLE_GROUP = "eo/tache-3/culture-p1"
SAMPLE_REJECTION_LIMIT = 3
VOICE_SETTINGS = {
    "stability": 0.65,
    "similarity_boost": 0.75,
    "style": 0,
    "use_speaker_boost": True,
    "speed": 1.0,
}


class NarrationError(Exception):
    """An actionable, credential-safe configuration or synthesis failure."""


class PreSynthesisRejection(NarrationError):
    """Only the exact free-tier voice restriction proves no synthesis started."""

    code = "free_users_not_allowed"

    def __init__(self):
        super().__init__(
            "ElevenLabs a refusé cette voix avant la synthèse : le forfait gratuit "
            "n’autorise que les voix par défaut via l’API. Aucune voix n’a été remplacée. "
            "Demandez à l’administrateur de configurer une voix par défaut autorisée "
            "(ELEVENLABS_VOICE_ID), puis rechargez la page et confirmez un nouvel essai. "
            "Conserver cette voix nécessite de vérifier son accès avec ElevenLabs ; "
            "aucun changement de forfait ne sera effectué par l’application."
        )


def sample_rejection_message(voice_id):
    rejected = FrenchNarration.objects.filter(target_group=SAMPLE_GROUP, status="plan_denied")
    if rejected.filter(voice_id=voice_id).exists():
        return str(PreSynthesisRejection())
    if rejected.count() >= SAMPLE_REJECTION_LIMIT:
        return (
            "Trois voix ont déjà été refusées avant synthèse. Contactez l’administrateur "
            "pour vérifier les accès ElevenLabs ; aucun nouvel essai automatique."
        )
    return ""


def _is_plan_rejection(response):
    if response.status_code not in (401, 403):
        return False
    try:
        body = bytearray()
        for chunk in response.iter_raw(chunk_size=MAX_ERROR_BYTES + 1):
            body.extend(chunk)
            if len(body) > MAX_ERROR_BYTES:
                return False
        length = response.headers.get("Content-Length")
        if length is not None and (
            not re.fullmatch(r"[0-9]{1,10}", length) or int(length) != len(body)
        ):
            return False
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError, httpx.HTTPError, OSError, HTTPException):
        return False
    if not isinstance(payload, dict) or not isinstance(payload.get("detail"), dict):
        return False
    detail = payload["detail"]
    # Prefer the documented code; accept legacy status only when code is absent.
    code = detail.get("code") if "code" in detail else detail.get("status")
    return code == PreSynthesisRejection.code


def _check_provider_request(request):
    if (
        request.method != "POST" or request.url.scheme != "https"
        or request.url.host != "api.elevenlabs.io" or request.url.port not in (None, 443)
        or not re.fullmatch(r"/v1/text-to-speech/[A-Za-z0-9_-]{1,128}", request.url.path)
    ):
        raise NarrationError("The narration request must use the fixed ElevenLabs HTTPS endpoint.")


def _check_provider_response(response):
    # Run before the SDK's error handler, which otherwise reads an unbounded error body.
    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
        raise NarrationError("ElevenLabs returned an unexpected encoding. Check provider usage before retrying.")
    if response.status_code != 200:
        if _is_plan_rejection(response):
            raise PreSynthesisRejection()
        raise NarrationError(
            f"ElevenLabs returned HTTP {response.status_code}. Check the key, voice access and quota. "
            "No automatic retry was made."
        )
    content_type = response.headers.get("Content-Type", "").partition(";")[0].strip().lower()
    if content_type not in {"audio/mpeg", "audio/mp3"}:
        raise NarrationError("ElevenLabs returned invalid or oversized MP3 audio. Check provider usage before retrying.")


@dataclass(frozen=True)
class NarrationSpec:
    group: str
    text: str
    voice_id: str
    model_id: str
    fingerprint: str


def narration_spec(model):
    voice = settings.ELEVENLABS_VOICE_ID
    model_id = settings.ELEVENLABS_MODEL_ID
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", voice):
        raise NarrationError("Set ELEVENLABS_VOICE_ID to the selected French voice ID.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", model_id):
        raise NarrationError("Set ELEVENLABS_MODEL_ID to a supported text-to-speech model ID.")
    response = model.response
    if response.is_personal:
        raise NarrationError("Only reviewed public EO3 models can be narrated.")
    paragraphs = (
        response.position_claire,
        *(" ".join((arg.idea, arg.developpement, arg.exemple, arg.consequence))
          for arg in response.arguments),
        response.nuance,
        response.conclusion,
    )
    text = "\n\n".join(paragraphs)
    if not text.strip() or len(text) > 10000:
        raise NarrationError("The response exceeds the 10,000-character narration limit.")
    identity = {
        "version": 1, "group": model.group, "text": text,
        "voice_id": voice, "model_id": model_id,
        "output_format": OUTPUT_FORMAT, "voice_settings": VOICE_SETTINGS,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return NarrationSpec(model.group, text, voice, model_id, fingerprint)


def on_demand_enabled():
    return (
        settings.FRENCH_AUDIO_GENERATION_ENABLED
        and settings.FRENCH_AUDIO_CHARACTER_BUDGET > 0
        and bool(settings.ELEVENLABS_API_KEY)
        and not settings.ON_VERCEL
    )


def narration_presentation(model):
    if not settings.EO3_AUDIO_ENABLED or model is None:
        return None
    try:
        spec = narration_spec(model)
    except NarrationError:
        return {"ready": False, "unconfigured": True}
    ready = EO3Narration.objects.filter(fingerprint=spec.fingerprint).exists()
    group_slug = model.group.removeprefix("eo/tache-3/")
    if on_demand_enabled():
        return {
            "ready": ready, "on_demand": not ready,
            "prepare_url": "" if ready else reverse(
                "study:eo3_audio_prepare", args=[group_slug, spec.fingerprint],
            ),
            "sample_issue": "", "sample_attempted": False, "sample_status": "",
            "characters": len(spec.text), "sample_voice": "",
            "url": reverse("study:eo3_audio", args=[group_slug, spec.fingerprint]) if ready else "",
        }
    sample_claimed = (
        model.group == SAMPLE_GROUP
        and FrenchNarrationBudget.objects.filter(pk=1, sample_claimed=True).exists()
    )
    sample_issue = sample_rejection_message(spec.voice_id) if model.group == SAMPLE_GROUP else ""
    if sample_claimed:
        sample_issue = (
            "Un essai a déjà été lancé et peut avoir été facturé. Si ce refus est antérieur "
            "à la détection des erreurs de forfait, son motif exact n’a pas été conservé. "
            "L’administrateur doit faire vérifier cette requête et sa facturation par "
            "ElevenLabs avant toute récupération explicite ; changer de voix ne débloque pas cet essai."
        )
    return {
        "ready": ready,
        "prepare_url": reverse("study:eo3_audio_prepare", args=[
            "culture-p1", spec.fingerprint,
        ]) if (
            not ready and model.group == SAMPLE_GROUP
            and settings.EO3_AUDIO_SAMPLE_ENABLED and not settings.ON_VERCEL
            and not sample_claimed and not sample_issue
        ) else "",
        "sample_issue": sample_issue,
        "sample_attempted": not ready and sample_claimed,
        "sample_status": FrenchNarration.objects.filter(
            pk=spec.fingerprint,
        ).values_list("status", flat=True).first() if sample_claimed else "",
        "characters": len(spec.text),
        "sample_voice": spec.voice_id if model.group == SAMPLE_GROUP else "",
        "url": reverse("study:eo3_audio", args=[
            model.group.removeprefix("eo/tache-3/"), spec.fingerprint,
        ]) if ready else "",
    }


def synthesize(spec):
    if not settings.ELEVENLABS_API_KEY:
        raise NarrationError("Set ELEVENLABS_API_KEY on the server; never put it in browser code.")
    if (
        not spec.text.strip() or len(spec.text) > 10000
        or not all(re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) for value in (spec.voice_id, spec.model_id))
    ):
        raise NarrationError("Invalid narration source, voice or model; no provider request was made.")
    try:
        with httpx.Client(
            transport=httpx.HTTPTransport(retries=0),
            timeout=90, follow_redirects=False, trust_env=False,
            headers={"Accept": "audio/mpeg", "Accept-Encoding": "identity"},
            event_hooks={"request": [_check_provider_request], "response": [_check_provider_response]},
        ) as transport:
            client = ElevenLabs(
                api_key=settings.ELEVENLABS_API_KEY, base_url="https://api.elevenlabs.io",
                timeout=90, follow_redirects=False, httpx_client=transport,
            )
            with client.text_to_speech.with_raw_response.convert(
                voice_id=spec.voice_id, text=spec.text, model_id=spec.model_id,
                output_format=OUTPUT_FORMAT, voice_settings=VoiceSettings(**VOICE_SETTINGS),
                request_options={"max_retries": 0, "timeout_in_seconds": 90, "chunk_size": 8192},
            ) as response:
                audio = bytearray()
                for chunk in response.data:
                    audio.extend(chunk)
                    if len(audio) > MAX_AUDIO_BYTES:
                        raise NarrationError(
                            "ElevenLabs returned invalid or oversized MP3 audio. Check provider usage before retrying."
                        )
                length = response.headers.get("content-length")
                if length is not None and (
                    not re.fullmatch(r"[0-9]{1,10}", length) or int(length) != len(audio)
                ):
                    raise NarrationError("ElevenLabs returned incomplete MP3 audio. Check provider usage before retrying.")
    except (httpx.HTTPError, ApiError, TimeoutError, OSError, HTTPException):
        raise NarrationError(
            "ElevenLabs could not complete the recording. Check connectivity and provider "
            "usage before retrying: a timed-out request may still have been billed."
        ) from None
    if (
        not 4 <= len(audio) <= MAX_AUDIO_BYTES
        or not (audio.startswith(b"ID3") or (audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0))
    ):
        raise NarrationError(
            "ElevenLabs returned invalid or oversized MP3 audio. Nothing was saved; "
            "check provider usage before retrying."
        )
    return bytes(audio)


@transaction.atomic
def generate_narration(spec):
    # The unique reservation serializes concurrent generators before a paid call.
    recording, created = EO3Narration.objects.select_for_update().get_or_create(
        fingerprint=spec.fingerprint,
        defaults={
            "group": spec.group, "voice_id": spec.voice_id,
            "model_id": spec.model_id, "audio": b"",
        },
    )
    if not created:
        if not recording.audio:
            raise NarrationError("The cached recording is empty; inspect it before regenerating.")
        return False
    recording.audio = synthesize(spec)
    recording.save(update_fields=["audio"])
    return True
