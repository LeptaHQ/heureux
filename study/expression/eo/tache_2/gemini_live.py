"""Provision a single constrained voice session; never proxy learner content."""

import json
import re
from contextlib import closing
from datetime import timedelta
from http.client import HTTPException, HTTPSConnection

from django.conf import settings
from django.core import signing
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.views.decorators.debug import sensitive_variables

from study.accounts.services import account_throttle_key, authorize_audio_generation, reserve_throttled_action
from study.catalogue.loader import TacheTwoSubjectData
from study.expression.eo.tache_2.dialogues import TacheTwoDialogue

MODEL = "models/gemini-3.8-live"
_HOST = "generativelanguage.googleapis.com"
_MAX_RESPONSE_BYTES = 16_384

# Fictional facts from the Tâche 2 studio's roleplay-engine.js.
_RECEPTION = """Vous êtes à l’accueil du centre culturel. Vous répondez en français à une
personne qui se renseigne sur deux ateliers photo pour débutants. Vouvoyez-la.
Laissez-la mener l’échange. Parlez comme à un comptoir au Canada : une ou
deux phrases, un débit naturel, sans réciter une fiche ni terminer chaque
réponse par une question. Suivez le fil : « et l’autre ? » reprend le dernier
point comparé. Si la personne se reprend, partez de sa dernière précision.
Pour conseiller, tenez compte ensemble de ses disponibilités, de son budget
et de son matériel. Si aucune formule ne convient, dites pourquoi ; ne créez
pas de troisième option. Demandez une précision seulement si le contexte ne
suffit pas. Pour un détail inconnu, dites que vous ne pouvez pas le confirmer.
Restez à l’accueil : ni cours de langue, ni correction,
ni note, ni estimation de niveau. Ne demandez aucune donnée personnelle et ne
prenez aucune réservation réelle. N’inventez pas de renseignements.

Balade : cadrage dans le parc des Saules, le samedi de 10 h à 11 h 30. Trois
places restent. 20 dollars par personne, conseils de la photographe compris.
Il faut apporter un téléphone ou un appareil photo ; aucun prêt au parc.
Rendez-vous à l’entrée devant le kiosque, arrêt « Parc des Saules ». En cas de
forte pluie, report au samedi suivant ou remboursement si la date ne convient pas.

Studio : éclairage d’un portrait, le mercredi de 18 h à 20 h. Deux places
restent. 35 dollars par personne. Un appareil photo est nécessaire : le prêt
est inclus sans supplément sur réservation. Salle deux du centre culturel,
arrêt « Centre culturel ». La pluie ne change rien à cette séance en intérieur.

Pour les deux : réservation à l’accueil ou par téléphone en indiquant la formule.
Règlement à l’accueil avant la séance, par carte ou en espèces ; pas d’acompte
ni de tarif réduit. Déplacement ou annulation sans frais jusqu’à la veille à
17 h. Après, il faut prévenir l’accueil pour libérer la place."""


def subject_instruction(subject: TacheTwoSubjectData, dialogue: TacheTwoDialogue) -> str:
    # Only the selected publication's editorial material, never a learner's version.
    references = {
        "consigne": subject.prompt,
        "registre": dialogue.register,
        "rôles et limites": dialogue.note,
        "repères fictifs": [{"question possible": q.question, "réponse": q.answer} for q in dialogue.questions],
    }
    return (
        "Simulation de la Tâche 2 du TCF Canada. Jouez uniquement l’interlocuteur "
        "auquel le candidat doit s’adresser dans cette consigne. Le candidat mène "
        "l’échange et pose ses propres questions. Parlez en français dans le registre "
        "indiqué. Répondez brièvement, comme dans la vie courante, en tenant compte "
        "des précisions, corrections et relances du candidat. Les exemples ci-dessous "
        "sont des repères, pas un dialogue à réciter ni des questions à poser. "
        "La consigne de cette publication prime sur les exemples. N’ajoutez pas de "
        "faits incompatibles ; si une information manque, dites-le en restant dans "
        "votre rôle. Ne corrigez pas le candidat, ne le notez pas, ne demandez pas "
        "de coordonnées réelles et ne promettez aucune action réelle.\n"
        + json.dumps(references, ensure_ascii=False)
    )


def available_to(user, task):
    return bool(
        settings.GEMINI_LIVE_FREE_TIER_CONFIRMED is True
        and settings.GEMINI_LIVE_API_KEY
        and user.is_authenticated and user.is_active
        and 0 < len(settings.ELEVENLABS_PIN) <= 128
        and task and task.available and task.part.available
    )


class LiveTokenError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def grant_signer(request, subject_key, *, purpose):
    # Scope the signature without exposing the session cookie or identity in the grant.
    return signing.TimestampSigner(salt=f"eo2:{purpose}:{request.user.pk}:{request.session.session_key}:{subject_key}")


def issue_grant(request, subject_key, *, purpose):
    return grant_signer(request, subject_key, purpose=purpose).sign(get_random_string(24))


@sensitive_variables("pin", "exchange_grant")
def mint_token(request, task, pin, *, instruction=None, exchange_grant=None, subject_key=""):
    if not available_to(request.user, task):
        raise LiveTokenError(403, "Le mode vocal pilote n’est pas disponible.")
    if exchange_grant is None:
        authorize_audio_generation(request, pin)
    else:
        try:
            nonce = grant_signer(request, subject_key, purpose="exchange").unsign(exchange_grant, max_age=600)
        except signing.BadSignature:
            raise LiveTokenError(403, "L’autorisation de cet échange n’est plus valide.") from None
        # A single atomic redemption; the 15-minute lock outlives the 10-minute grant.
        if reserve_throttled_action(account_throttle_key(nonce, purpose="eo2-exchange-grant"), limit=1):
            raise LiveTokenError(403, "Cette autorisation a déjà été utilisée.")
    token = _request_token(_RECEPTION if instruction is None else instruction)
    if token is None:
        raise LiveTokenError(503, "Le service vocal est indisponible pour le moment.")
    return token


def _request_token(instruction: str) -> str | None:
    now = timezone.now()
    # Raw AuthToken REST schema, not the SDK's liveConnectConstraints:
    # https://aistudio.google.com/api-reference/generate-content/create-token
    # Present setup + absent fieldMask replaces the ENTIRE client setup.
    payload = {
        "uses": 1,
        "newSessionExpireTime": (now + timedelta(minutes=1)).isoformat(),
        "expireTime": (now + timedelta(minutes=6)).isoformat(),
        "bidiGenerateContentSetup": {
            "model": MODEL,
            "generationConfig": {"responseModalities": ["AUDIO"]},
            "systemInstruction": {"parts": [{"text": instruction}]},
            # A hint, not a lock: without it, accented French can be captioned as Spanish.
            "inputAudioTranscription": {"languageCodes": ["fr-FR"]},
            "outputAudioTranscription": {},
        },
    }
    # One direct TLS request. Do not retry, follow redirects, forward browser
    # headers, log provider bodies, or attach provider exceptions to a report.
    try:
        with closing(HTTPSConnection(_HOST, timeout=5)) as connection:
            connection.request(
                "POST", "/v1beta/auth_tokens", body=json.dumps(payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": settings.GEMINI_LIVE_API_KEY,
                },
            )
            with connection.getresponse() as response:
                if response.status != 200:
                    return None
                body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            return None
        result = json.loads(body)
        name = result.get("name") if isinstance(result, dict) else None
        if isinstance(name, str) and re.fullmatch(r"auth_tokens/[A-Za-z0-9._~+/-]+=*", name):
            return name
    except (OSError, HTTPException, ValueError, RecursionError):
        pass
    return None
