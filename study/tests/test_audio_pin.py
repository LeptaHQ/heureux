"""A fresh PIN is required before any new paid recording, never for playback."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from study import catalogue
from study.audio_pin import (
    AudioPinError, PinExceptionReporterFilter, command_generation_pin,
    require_generation_pin,
)
from study.eo3_audio import generate_narration, narration_spec
from study.french_audio import enqueue, generate_prepared, source_grant, speech_spec
from study.models import EO3Narration, FrenchNarration, FrenchNarrationBudget, LoginThrottle
from . import factories
from .test_eo3_audio import AUDIO, AUDIO_PIN, AUDIO_SETTINGS, TIMING


PIN_SETTINGS = {
    **AUDIO_SETTINGS,
    "FRENCH_AUDIO_ENABLED": True,
    "FRENCH_AUDIO_GENERATION_ENABLED": True,
    "FRENCH_AUDIO_CHARACTER_BUDGET": 100000,
    "ON_VERCEL": False,
}


@override_settings(**PIN_SETTINGS)
class AudioPinTests(SimpleTestCase):
    def test_missing_and_wrong_pin_fail_without_exposing_the_secret(self):
        for value, code in ((None, "pin_required"), ("", "pin_required"),
                            ("incorrect", "pin_invalid"), (123456, "pin_invalid")):
            with self.subTest(value=value):
                with self.assertRaises(AudioPinError) as caught:
                    require_generation_pin(value)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn(AUDIO_PIN, str(caught.exception))
        require_generation_pin(AUDIO_PIN)

    @override_settings(ELEVENLABS_PIN="")
    def test_unconfigured_pin_blocks_new_generation(self):
        with self.assertRaises(AudioPinError) as caught:
            require_generation_pin(AUDIO_PIN)
        self.assertEqual(caught.exception.code, "pin_unconfigured")
        self.assertEqual(caught.exception.status, 503)

    def test_exception_reports_redact_the_environment_pin(self):
        filtered = PinExceptionReporterFilter().get_safe_settings()
        self.assertNotEqual(filtered["ELEVENLABS_PIN"], AUDIO_PIN)
        self.assertNotIn(AUDIO_PIN, repr(filtered))

    @patch("study.audio_pin.sys.stdin.isatty", return_value=False)
    @patch("study.audio_pin.getpass.getpass")
    def test_operator_commands_cannot_silently_use_the_environment_pin(self, prompt, isatty):
        with self.assertRaises(AudioPinError):
            command_generation_pin()
        prompt.assert_not_called()

    @patch("study.audio_pin.sys.stdin.isatty", return_value=True)
    @patch("study.audio_pin.getpass.getpass", return_value=AUDIO_PIN)
    def test_operator_prompt_uses_masked_terminal_input(self, prompt, isatty):
        self.assertEqual(command_generation_pin(), AUDIO_PIN)
        prompt.assert_called_once()


@override_settings(**PIN_SETTINGS)
class AudioPinRequestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = factories.make_user("audio-pin-reader")

    def setUp(self):
        self.client.force_login(self.user)
        self.model = catalogue.tache_three_models()["eo/tache-3/culture-p1"]
        self.spec = narration_spec(self.model)
        self.eo3_url = reverse(
            "study:eo3_audio_prepare", args=["culture-p1", self.spec.fingerprint],
        )
        self.text = "Voici une lecture française à préparer."
        self.source = {"grant": source_grant(self.text, self.user.pk, private=False)}
        self.french_url = reverse("study:french_audio_resolve")

    def eo3(self, **values):
        return self.client.post(
            self.eo3_url, {"confirm_cost": True, **values}, content_type="application/json",
        )

    def french(self, **values):
        return self.client.post(self.french_url, {
            "sources": [self.source], "prepare": True, "confirm_cost": True, **values,
        }, content_type="application/json")

    @patch("study.french_audio.synthesize")
    def test_missing_or_wrong_pin_cannot_enqueue_reserve_or_call_elevenlabs(self, provider):
        for request in (self.eo3, self.french):
            self.assertEqual(request().json()["error"], "pin_required")
            wrong = request(pin="incorrect")
            self.assertEqual(wrong.status_code, 403)
            self.assertEqual(wrong.json()["error"], "pin_invalid")
        self.assertFalse(FrenchNarration.objects.exists())
        self.assertFalse(EO3Narration.objects.exists())
        self.assertFalse(FrenchNarrationBudget.objects.exists())
        provider.assert_not_called()

    @override_settings(ELEVENLABS_PIN="")
    @patch("study.french_audio.synthesize")
    def test_unconfigured_pin_returns_explicit_error_for_both_generation_paths(self, provider):
        for request in (self.eo3, self.french):
            reply = request(pin=AUDIO_PIN)
            self.assertEqual(reply.status_code, 503)
            self.assertEqual(reply.json()["error"], "pin_unconfigured")
        provider.assert_not_called()
        self.assertFalse(FrenchNarration.objects.exists())

    @patch("study.french_audio.synthesize", return_value=AUDIO)
    def test_valid_pin_generates_once_and_cached_audio_needs_no_pin(self, provider):
        ready = self.french(pin=AUDIO_PIN)
        self.assertEqual(ready.status_code, 200, ready.content)
        self.assertEqual(ready.json()["state"], "ready")
        with self.settings(ELEVENLABS_PIN="", FRENCH_AUDIO_GENERATION_ENABLED=False):
            cached = self.french()
            self.assertEqual(cached.status_code, 200)
            self.assertEqual(cached.json()["url"], ready.json()["url"])
            self.assertEqual(self.client.get(cached.json()["url"]).status_code, 200)
        provider.assert_called_once()
        self.assertNotIn(AUDIO_PIN, repr(provider.call_args))

    @patch("study.french_audio.synthesize", return_value=(AUDIO, TIMING))
    def test_eo3_cached_audio_needs_no_pin_even_if_environment_pin_is_removed(self, provider):
        self.assertEqual(self.eo3(pin=AUDIO_PIN).status_code, 200)
        with self.settings(ELEVENLABS_PIN=""):
            self.assertEqual(self.eo3().status_code, 200)
            url = reverse("study:eo3_audio", args=["culture-p1", self.spec.fingerprint])
            self.assertEqual(self.client.get(url).status_code, 200)
        provider.assert_called_once()

    @patch("study.french_audio.synthesize", return_value=AUDIO)
    def test_correct_pin_does_not_unlock_later_recordings(self, provider):
        self.assertEqual(self.french(pin=AUDIO_PIN).status_code, 200)
        self.source = {
            "grant": source_grant("Une deuxième lecture.", self.user.pk, private=False),
        }
        denied = self.french()
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error"], "pin_required")
        self.assertEqual(FrenchNarration.objects.count(), 1)
        provider.assert_called_once()

    @patch("study.french_audio.synthesize")
    def test_wrong_pin_attempts_are_limited_without_storing_the_pin(self, provider):
        for _ in range(5):
            self.assertEqual(self.eo3(pin="incorrect").status_code, 403)
        blocked = self.french(pin=AUDIO_PIN)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["error"], "pin_locked")
        self.assertTrue(LoginThrottle.objects.exists())
        self.assertNotIn(AUDIO_PIN, repr(list(LoginThrottle.objects.values())))
        self.assertFalse(FrenchNarration.objects.exists())
        provider.assert_not_called()

    @patch("study.french_audio.synthesize")
    @patch("study.eo3_audio.synthesize")
    def test_generation_services_also_enforce_pin_before_any_paid_call(self, eo3_provider, french_provider):
        recording = enqueue(speech_spec(self.text), self.user.pk, None)
        with self.assertRaises(AudioPinError):
            generate_prepared(recording.pk)
        with self.assertRaises(AudioPinError):
            generate_narration(self.spec)
        recording.refresh_from_db()
        self.assertEqual(recording.status, "pending")
        self.assertFalse(FrenchNarrationBudget.objects.filter(reserved_characters__gt=0).exists())
        self.assertFalse(EO3Narration.objects.exists())
        eo3_provider.assert_not_called()
        french_provider.assert_not_called()

    @override_settings(ELEVENLABS_PIN="")
    @patch("study.eo3_audio.synthesize")
    def test_operator_dry_run_does_not_need_a_pin(self, provider):
        output = StringIO()
        call_command("generate_eo3_audio", group="culture-p1", dry_run=True, stdout=output)
        self.assertIn("1 to generate", output.getvalue())
        provider.assert_not_called()

    @override_settings(ELEVENLABS_PIN="")
    @patch("study.french_audio.synthesize")
    @patch("study.eo3_audio.synthesize")
    def test_confirm_cost_cannot_bypass_pin_for_operator_commands(self, eo3_provider, french_provider):
        recording = enqueue(speech_spec(self.text), self.user.pk, None)
        for name, values in (
            ("prepare_french_audio", {"id": recording.pk}),
            ("generate_eo3_audio", {"group": "culture-p1"}),
        ):
            with self.subTest(command=name):
                with self.assertRaisesMessage(CommandError, "ELEVENLABS_PIN"):
                    call_command(name, confirm_cost=True, stdout=StringIO(), **values)
        eo3_provider.assert_not_called()
        french_provider.assert_not_called()

    def test_html_does_not_contain_the_server_pin(self):
        page = self.client.get(reverse("study:notes_overview"))
        self.assertContains(page, "data-audio-pin-dialog")
        self.assertNotContains(page, AUDIO_PIN)
