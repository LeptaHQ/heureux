"""Per-recording authorization for paid ElevenLabs generation."""

import getpass
import re
import sys

from django.conf import settings
from django.utils.crypto import constant_time_compare
from django.views.debug import SafeExceptionReporterFilter
from django.views.decorators.debug import sensitive_variables


class AudioPinError(Exception):
    def __init__(self, code, message, status=403):
        super().__init__(message)
        self.code = code
        self.status = status


class PinExceptionReporterFilter(SafeExceptionReporterFilter):
    hidden_settings = re.compile(
        SafeExceptionReporterFilter.hidden_settings.pattern + r"|(?:^|_)PIN(?:$|_)",
        re.IGNORECASE,
    )


@sensitive_variables()
def require_generation_pin(pin):
    expected = settings.ELEVENLABS_PIN
    if not expected or len(expected) > 128:
        raise AudioPinError(
            "pin_unconfigured",
            "La génération est bloquée : configurez ELEVENLABS_PIN sur le serveur "
            "(128 caractères maximum). Les enregistrements existants restent disponibles.",
            503,
        )
    if pin is None or pin == "":
        raise AudioPinError(
            "pin_required",
            "Saisissez le code PIN ElevenLabs pour autoriser ce nouvel enregistrement.",
        )
    if not isinstance(pin, str) or len(pin) > 128 or not constant_time_compare(pin, expected):
        raise AudioPinError("pin_invalid", "Code PIN ElevenLabs incorrect.")


@sensitive_variables()
def command_generation_pin():
    if not settings.ELEVENLABS_PIN or len(settings.ELEVENLABS_PIN) > 128:
        require_generation_pin(None)
    if sys.stdin is None or not sys.stdin.isatty():
        raise AudioPinError(
            "pin_required",
            "Utilisez un terminal interactif pour saisir le code PIN ElevenLabs. "
            "Aucune nouvelle génération n'a été lancée.",
        )
    return getpass.getpass("Code PIN ElevenLabs : ")
