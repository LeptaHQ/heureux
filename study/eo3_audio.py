"""Explicit, cached narration of reviewed EO3 models and their owners' edited copies."""

from dataclasses import dataclass
import base64
import binascii
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
from django.views.decorators.debug import sensitive_variables
from django.urls import reverse

from .models import EO3Narration, FrenchNarration, FrenchNarrationBudget


OUTPUT_FORMAT = "mp3_44100_64"
MAX_AUDIO_BYTES = 8 * 1024 * 1024
# Base64 audio plus per-character alignment for at most 10,000 characters.
MAX_TIMED_RESPONSE_BYTES = 16 * 1024 * 1024
WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*")
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
        or not re.fullmatch(r"/v1/text-to-speech/[A-Za-z0-9_-]{1,128}(?:/with-timestamps)?", request.url.path)
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
    if response.request.url.path.endswith("/with-timestamps"):
        length = response.headers.get("Content-Length")
        if content_type != "application/json" or (length is not None and (
            not re.fullmatch(r"[0-9]{1,10}", length) or int(length) > MAX_TIMED_RESPONSE_BYTES
        )):
            raise NarrationError("ElevenLabs returned an invalid timed recording. Check provider usage before retrying.")
        return
    if content_type not in {"audio/mpeg", "audio/mp3"}:
        raise NarrationError("ElevenLabs returned invalid or oversized MP3 audio. Check provider usage before retrying.")


@dataclass(frozen=True)
class NarrationSpec:
    group: str
    text: str
    voice_id: str
    model_id: str
    fingerprint: str


def narration_spec(model, personal=None, owner_id=None):
    """Spec for the reviewed model, or for ``owner_id``'s edited copy of it."""
    response = model.response
    if personal is not None:
        if not personal.is_personal or owner_id is None:
            raise NarrationError("An edited response needs its owner.")
        response = personal
    elif response.is_personal:
        raise NarrationError("Only reviewed public EO3 models can be narrated.")
    # Published texts keep their exact joins so existing recordings stay valid;
    # edited copies may leave fields empty.
    join = (lambda parts: " ".join(filter(None, parts))) if personal is not None else " ".join
    # The consigne shown by « Dédupliquer » is read first, as an examiner would.
    paragraphs = (
        model.source_prompts[0][1],
        response.position_claire,
        *(join((arg.idea, arg.developpement, arg.exemple, arg.consequence))
          for arg in response.arguments),
        response.nuance,
        response.conclusion,
    )
    if personal is not None:
        paragraphs = tuple(filter(None, paragraphs))
    return text_narration_spec(model.group, "\n\n".join(paragraphs), owner_id)


def text_narration_spec(group, text, owner_id=None):
    voice = settings.ELEVENLABS_VOICE_ID
    model_id = settings.ELEVENLABS_MODEL_ID
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", voice):
        raise NarrationError("Set ELEVENLABS_VOICE_ID to the selected French voice ID.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", model_id):
        raise NarrationError("Set ELEVENLABS_MODEL_ID to a supported text-to-speech model ID.")
    if not text.strip() or len(text) > 10000:
        raise NarrationError("The response exceeds the 10,000-character narration limit.")
    identity = {
        "version": 2, "group": group, "text": text,
        "voice_id": voice, "model_id": model_id,
        "output_format": OUTPUT_FORMAT, "voice_settings": VOICE_SETTINGS,
    }
    if owner_id is not None:
        # Edited copies are private: the owner is part of the recording's identity.
        identity["owner"] = owner_id
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return NarrationSpec(group, text, voice, model_id, fingerprint)


def personal_narrations(model, user):
    """``(spec, response)`` for every edited copy ``user`` keeps of ``model``."""
    from .models import Response
    from .oral_history import preferred_personal
    from .response_personalization import effective_response

    if user is None or not getattr(user, "is_authenticated", False):
        return []
    found = []
    for response in Response.objects.filter(semantic_group=model.group):
        personal = preferred_personal(response, user)
        if personal is not None:
            value = effective_response(response, user, personal=personal)
            found.append((narration_spec(model, value, user.pk), value))
    return found


def on_demand_enabled():
    return (
        settings.FRENCH_AUDIO_GENERATION_ENABLED
        and settings.FRENCH_AUDIO_CHARACTER_BUDGET > 0
        and bool(settings.ELEVENLABS_API_KEY)
        and not settings.ON_VERCEL
    )


def narration_presentation(model, personal=None, owner_id=None):
    if not settings.EO3_AUDIO_ENABLED or model is None:
        return None
    try:
        spec = narration_spec(model, personal, owner_id)
    except NarrationError:
        return {"ready": False, "unconfigured": True}
    timing = EO3Narration.objects.filter(
        fingerprint=spec.fingerprint,
    ).values_list("timing", flat=True).first()
    ready = timing is not None
    timing_json = json.dumps(timing, ensure_ascii=False, separators=(",", ":")) if timing else ""
    group_slug = model.group.removeprefix("eo/tache-3/")
    if on_demand_enabled():
        return {
            "ready": ready, "on_demand": not ready, "timing": timing_json,
            "prepare_url": "" if ready else reverse(
                "study:eo3_audio_prepare", args=[group_slug, spec.fingerprint],
            ),
            "sample_issue": "", "sample_attempted": False, "sample_status": "",
            "characters": len(spec.text), "sample_voice": "",
            "url": reverse("study:eo3_audio", args=[group_slug, spec.fingerprint]) if ready else "",
        }
    if personal is not None:
        # The one-off audition sample only ever covers the published model.
        return {
            "ready": ready, "timing": timing_json, "prepare_url": "",
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
        "ready": ready, "timing": timing_json,
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


def word_timings(text, characters, starts, ends):
    """Map each spoken word of ``text`` to its provider start and end time in ms."""
    if not (
        isinstance(characters, list) and isinstance(starts, list) and isinstance(ends, list)
        and len(characters) == len(starts) == len(ends)
        and all(isinstance(value, (int, float)) for value in (*starts, *ends))
    ):
        return []
    positions, cursor = [], 0
    for char in text:
        while cursor < len(characters) and characters[cursor] != char and characters[cursor].isspace():
            cursor += 1
        if cursor < len(characters) and characters[cursor] == char:
            positions.append(cursor)
            cursor += 1
        elif char.isspace():
            positions.append(None)
        else:
            return []
    paragraphs, offset = [], 0
    for paragraph in text.split("\n\n"):
        words = []
        for match in WORD.finditer(text, offset, offset + len(paragraph)):
            first, last = positions[match.start()], positions[match.end() - 1]
            words.append([match.group(), round(starts[first] * 1000), round(ends[last] * 1000)])
        paragraphs.append(words)
        offset += len(paragraph) + 2
    return paragraphs


def synthesize(spec, *, timing=False):
    """Return MP3 bytes, or ``(bytes, word_timings)`` when ``timing`` is requested."""
    if not settings.ELEVENLABS_API_KEY:
        raise NarrationError("Set ELEVENLABS_API_KEY on the server; never put it in browser code.")
    if (
        not spec.text.strip() or len(spec.text) > 10000
        or not all(re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) for value in (spec.voice_id, spec.model_id))
    ):
        raise NarrationError("Invalid narration source, voice or model; no provider request was made.")
    words = []
    try:
        with httpx.Client(
            transport=httpx.HTTPTransport(retries=0),
            timeout=90, follow_redirects=False, trust_env=False,
            headers={
                "Accept": "application/json" if timing else "audio/mpeg",
                "Accept-Encoding": "identity",
            },
            event_hooks={"request": [_check_provider_request], "response": [_check_provider_response]},
        ) as transport:
            client = ElevenLabs(
                api_key=settings.ELEVENLABS_API_KEY, base_url="https://api.elevenlabs.io",
                timeout=90, follow_redirects=False, httpx_client=transport,
            )
            if timing:
                response = client.text_to_speech.with_raw_response.convert_with_timestamps(
                    voice_id=spec.voice_id, text=spec.text, model_id=spec.model_id,
                    output_format=OUTPUT_FORMAT, voice_settings=VoiceSettings(**VOICE_SETTINGS),
                    request_options={"max_retries": 0, "timeout_in_seconds": 90},
                )
                encoded = response.data.audio_base_64
                if not isinstance(encoded, str) or len(encoded) > MAX_AUDIO_BYTES * 4 // 3 + 4:
                    raise NarrationError(
                        "ElevenLabs returned invalid or oversized MP3 audio. Check provider usage before retrying."
                    )
                try:
                    audio = bytearray(base64.b64decode(encoded, validate=True))
                except (binascii.Error, ValueError):
                    raise NarrationError(
                        "ElevenLabs returned invalid or oversized MP3 audio. Check provider usage before retrying."
                    ) from None
                alignment = response.data.alignment
                if alignment is not None:
                    words = word_timings(
                        spec.text, alignment.characters,
                        alignment.character_start_times_seconds, alignment.character_end_times_seconds,
                    )
            else:
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
    except (httpx.HTTPError, ApiError, TimeoutError, OSError, HTTPException, ValueError):
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
    return (bytes(audio), words) if timing else bytes(audio)


@transaction.atomic
@sensitive_variables("pin")
def generate_narration(spec, *, pin=None):
    from .audio_pin import require_generation_pin

    recording = EO3Narration.objects.select_for_update().filter(
        fingerprint=spec.fingerprint,
    ).first()
    if recording is None:
        require_generation_pin(pin)
        # The unique reservation serializes concurrent generators before a paid call.
        recording, created = EO3Narration.objects.select_for_update().get_or_create(
            fingerprint=spec.fingerprint,
            defaults={
                "group": spec.group, "voice_id": spec.voice_id,
                "model_id": spec.model_id, "audio": b"",
            },
        )
    else:
        created = False
    if not created:
        if not recording.audio:
            raise NarrationError("The cached recording is empty; inspect it before regenerating.")
        return False
    recording.audio, recording.timing = synthesize(spec, timing=True)
    recording.save(update_fields=["audio", "timing"])
    return True
