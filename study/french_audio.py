"""Source-bound narration with durable, nonrefundable paid-call reservations."""

from datetime import timedelta
import hashlib
import json
import re

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .eo3_audio import (
    NarrationError, NarrationSpec, OUTPUT_FORMAT, PreSynthesisRejection, SAMPLE_GROUP,
    VOICE_SETTINGS, narration_spec, on_demand_enabled, sample_rejection_message, synthesize,
)
from .models import EO3Narration, FrenchNarration, FrenchNarrationBudget


MAX_TEXT = 10000
MAX_SOURCES = 32
GRANT_AGE = 3600
SALT = "study.french-audio.source.v1"


class SpeechError(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def normalize_text(value):
    return " ".join(str(value or "").split())


def source_grant(text, user_id, *, private=True):
    text = normalize_text(text)
    if not user_id or not 0 < len(text) <= MAX_TEXT:
        return ""
    return signing.dumps(
        {"version": 1, "user": user_id, "private": bool(private), "text": text},
        salt=SALT, compress=True,
    )


def resolve_sources(sources, user_id, *, consent=False):
    if not isinstance(sources, list) or not 0 < len(sources) <= MAX_SOURCES:
        raise SpeechError("source", "Sélectionnez un texte français autorisé.")
    texts = []
    private = False
    for source in sources:
        if not isinstance(source, dict):
            raise SpeechError("source", "Source de lecture invalide.")
        token = source.get("grant")
        if not isinstance(token, str) or len(token) > 30000:
            raise SpeechError("source", "Source de lecture invalide.")
        try:
            payload = signing.loads(token, salt=SALT, max_age=GRANT_AGE)
        except signing.BadSignature:
            raise SpeechError("expired", "Source expirée ou modifiée. Rechargez la page.", 403) from None
        if payload.get("version") != 1 or payload.get("user") != user_id:
            raise SpeechError("source", "Cette source ne vous est pas autorisée.", 403)
        text = payload["text"]
        if "text" in source:
            if not isinstance(source["text"], str):
                raise SpeechError("source", "Sélection invalide.")
            selected = normalize_text(source["text"])
            if not selected or selected not in text:
                raise SpeechError("source", "La sélection ne correspond plus à sa source.", 403)
            text = selected
        private = private or payload["private"]
        if text not in texts:
            texts.append(text)
    text = "\n\n".join(texts)
    if not 0 < len(text) <= MAX_TEXT:
        raise SpeechError("length", "La lecture naturelle est limitée à 10 000 caractères.")
    if private and consent is not True:
        raise SpeechError(
            "consent",
            "Votre accord explicite est nécessaire avant de transmettre ce texte privé à ElevenLabs.",
            403,
        )
    return text, user_id if private else None


def speech_spec(text, owner_id=None):
    voice = settings.ELEVENLABS_VOICE_ID
    model = settings.ELEVENLABS_MODEL_ID
    if not all(re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) for value in (voice, model)):
        raise SpeechError("configuration", "La voix naturelle n’est pas encore configurée.", 503)
    identity = {
        "version": 1, "text": text, "owner": owner_id,
        "voice_id": voice, "model_id": model,
        "output_format": OUTPUT_FORMAT, "voice_settings": VOICE_SETTINGS,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return NarrationSpec("", text, voice, model, fingerprint)


def media_url(recording):
    return reverse("study:french_audio", args=[recording.fingerprint])


def accessible_recordings(user_id):
    return FrenchNarration.objects.filter(Q(owner_id=user_id) | Q(owner__isnull=True))


@transaction.atomic
def enqueue(spec, user_id, owner_id):
    # The same DB lock serializes queue limits and operator budget reservations.
    FrenchNarrationBudget.objects.get_or_create(pk=1)
    FrenchNarrationBudget.objects.select_for_update().get(pk=1)
    existing = accessible_recordings(user_id).filter(pk=spec.fingerprint).first()
    if existing:
        return existing
    recent = FrenchNarration.objects.filter(
        requested_by_id=user_id, created_at__gte=timezone.now() - timedelta(days=1),
    )
    if recent.count() >= 10 or recent.filter(status="pending").count() >= 3:
        raise SpeechError("quota", "Limite atteinte : 3 demandes en attente et 10 par jour.", 429)
    if FrenchNarration.objects.filter(status__in=["pending", "working"]).count() >= 100:
        raise SpeechError("quota", "La file de préparation est pleine. Réessayez plus tard.", 429)
    return FrenchNarration.objects.create(
        fingerprint=spec.fingerprint, owner_id=owner_id, requested_by_id=user_id,
        text=spec.text, voice_id=spec.voice_id, model_id=spec.model_id,
    )


def generate_prepared(fingerprint):
    with transaction.atomic():
        budget, _ = FrenchNarrationBudget.objects.get_or_create(pk=1)
        budget = FrenchNarrationBudget.objects.select_for_update().get(pk=budget.pk)
        recording = FrenchNarration.objects.select_for_update().get(pk=fingerprint)
        if recording.status == "ready":
            return False
        on_demand = bool(recording.target_group) and on_demand_enabled()
        if on_demand:
            if not settings.EO3_AUDIO_ENABLED:
                raise NarrationError("EO3 narration is disabled.")
            from . import catalogue
            model = catalogue.tache_three_models().get(recording.target_group)
            if model is None:
                raise NarrationError("This response is no longer available.")
            spec = narration_spec(model)
        elif recording.target_group:
            if (
                not settings.EO3_AUDIO_ENABLED or not settings.EO3_AUDIO_SAMPLE_ENABLED
                or recording.target_group != SAMPLE_GROUP
            ):
                raise NarrationError("Only the authorized Culture p1 sample may be prepared before audition.")
            from . import catalogue
            spec = narration_spec(catalogue.tache_three_models()[SAMPLE_GROUP])
            if budget.sample_claimed:
                raise NarrationError(
                    "The single authorized sample was already attempted. Inspect provider usage. "
                    "Sans preuve structurée du refus avant synthèse, l’administrateur doit "
                    "faire vérifier cette requête et sa facturation par ElevenLabs avant "
                    "toute récupération explicite. Un changement de voix ne suffit pas."
                )
            rejection = sample_rejection_message(spec.voice_id)
            if rejection:
                raise NarrationError(rejection)
        else:
            if not settings.FRENCH_AUDIO_GENERATION_ENABLED:
                raise NarrationError("FRENCH_AUDIO_GENERATION_ENABLED must be explicitly enabled after audition.")
            spec = speech_spec(recording.text, recording.owner_id)
        if recording.status != "pending":
            raise NarrationError("This request was already attempted. Inspect provider usage; no automatic retry.")
        if recording.created_at < timezone.now() - timedelta(days=1):
            raise NarrationError("This preparation request expired after 24 hours.")
        if spec.fingerprint != fingerprint:
            raise NarrationError("The voice, model or synthesis settings changed. Request a new recording.")
        if not settings.ELEVENLABS_API_KEY:
            raise NarrationError("Set ELEVENLABS_API_KEY on the server.")
        if (on_demand or not recording.target_group) and (
            budget.reserved_characters + len(spec.text) > settings.FRENCH_AUDIO_CHARACTER_BUDGET
        ):
            raise NarrationError("The lifetime character ceiling is exhausted or zero.")
        if FrenchNarration.objects.filter(status="working").exists():
            raise NarrationError("Another recording is in progress. No concurrent paid calls are allowed.")
        budget.reserved_characters += len(spec.text)
        if recording.target_group and not on_demand:
            budget.sample_claimed = True
        budget.save(update_fields=["reserved_characters", "sample_claimed"])
        recording.status = "working"
        recording.save(update_fields=["status"])
    # Commit the spend reservation before networking: a crash must not refund it.
    timing = []
    try:
        if recording.target_group:
            audio, timing = synthesize(spec, timing=True)
        else:
            audio = synthesize(spec)
    except PreSynthesisRejection:
        if recording.target_group and not on_demand:
            with transaction.atomic():
                budget = FrenchNarrationBudget.objects.select_for_update().get(pk=1)
                # Persist the proof and release its unbilled slot together, never on generic failures.
                changed = FrenchNarration.objects.filter(
                    pk=fingerprint, status="working", target_group=SAMPLE_GROUP,
                ).update(status="plan_denied")
                if changed:
                    budget.sample_claimed = False
                    budget.save(update_fields=["sample_claimed"])
        else:
            FrenchNarration.objects.filter(pk=fingerprint).update(status="failed")
        raise
    except NarrationError:
        FrenchNarration.objects.filter(pk=fingerprint).update(status="failed")
        raise
    if recording.target_group:
        with transaction.atomic():
            EO3Narration.objects.update_or_create(
                fingerprint=spec.fingerprint,
                defaults={
                    "group": recording.target_group, "voice_id": spec.voice_id,
                    "model_id": spec.model_id, "audio": audio, "timing": timing,
                },
            )
            FrenchNarration.objects.filter(pk=fingerprint).update(status="ready")
        return True
    # A deleted account must not resurrect a private recording.
    if not FrenchNarration.objects.filter(pk=fingerprint, status="working").update(
        audio=audio, status="ready",
    ):
        raise NarrationError("The request was deleted during generation; no recording was saved.")
    return True
