"""Explicit, cached narration of reviewed public EO3 models only."""

from dataclasses import dataclass
import hashlib
from http.client import HTTPException
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings
from django.db import transaction
from django.urls import reverse

from .models import EO3Narration


OUTPUT_FORMAT = "mp3_44100_64"
MAX_AUDIO_BYTES = 8 * 1024 * 1024
VOICE_SETTINGS = {
    "stability": 0.65,
    "similarity_boost": 0.75,
    "style": 0,
    "use_speaker_boost": True,
    "speed": 1.0,
}


class NarrationError(Exception):
    """An actionable, credential-safe configuration or synthesis failure."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


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


def narration_presentation(model):
    if not settings.EO3_AUDIO_ENABLED or model is None:
        return None
    try:
        spec = narration_spec(model)
    except NarrationError:
        return {"ready": False, "unconfigured": True}
    ready = EO3Narration.objects.filter(fingerprint=spec.fingerprint).exists()
    return {
        "ready": ready,
        "url": reverse("study:eo3_audio", args=[
            model.group.removeprefix("eo/tache-3/"), spec.fingerprint,
        ]) if ready else "",
    }


def synthesize(spec):
    if not settings.ELEVENLABS_API_KEY:
        raise NarrationError("Set ELEVENLABS_API_KEY on the server; never put it in browser code.")
    request = Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{spec.voice_id}"
        f"?output_format={OUTPUT_FORMAT}",
        data=json.dumps({
            "text": spec.text, "model_id": spec.model_id,
            "voice_settings": VOICE_SETTINGS,
        }, ensure_ascii=False).encode("utf-8"),
        headers={
            "xi-api-key": settings.ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=90) as response:
            content_type = response.headers.get_content_type()
            audio = response.read(MAX_AUDIO_BYTES + 1)
    except HTTPError as exc:
        code = exc.code
        exc.close()
        raise NarrationError(
            f"ElevenLabs returned HTTP {code}. Check the key, voice access and quota. "
            "No automatic retry was made."
        ) from None
    except (URLError, TimeoutError, OSError, HTTPException):
        raise NarrationError(
            "ElevenLabs could not complete the recording. Check connectivity and provider "
            "usage before retrying: a timed-out request may still have been billed."
        ) from None
    if (
        content_type not in {"audio/mpeg", "audio/mp3"}
        or not 4 <= len(audio) <= MAX_AUDIO_BYTES
        or not (audio.startswith(b"ID3") or (audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0))
    ):
        raise NarrationError(
            "ElevenLabs returned invalid or oversized MP3 audio. Nothing was saved; "
            "check provider usage before retrying."
        )
    return audio


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
