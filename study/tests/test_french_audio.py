from dataclasses import replace
from datetime import timedelta
from html.parser import HTMLParser
from io import StringIO
from unittest.mock import patch

from django.core import signing
from django.core.management import call_command
from django.core.management.base import CommandError
from django.template import Context, Template
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from study.eo3_audio import NarrationError, PreSynthesisRejection, SAMPLE_REJECTION_LIMIT
from study import catalogue
from study.eo3_audio import SAMPLE_GROUP, narration_presentation, narration_spec
from study.french_audio import (
    MAX_TEXT, SALT, SpeechError, enqueue, generate_prepared, resolve_sources,
    source_grant, speech_spec,
)
from study.models import EO3Narration, FrenchNarration, FrenchNarrationBudget, WritingResponseOverride
from study.oral_highlights import AnnotationRootText

from . import factories
from .test_eo3_audio import AUDIO, AUDIO_PIN, AUDIO_SETTINGS, TIMING


SETTINGS = {
    **AUDIO_SETTINGS, "FRENCH_AUDIO_ENABLED": True,
    "FRENCH_AUDIO_GENERATION_ENABLED": False, "FRENCH_AUDIO_CHARACTER_BUDGET": 0,
}


class Sources(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.sources = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if "data-speech-grant" in data:
            self.sources.append(data)


@override_settings(**SETTINGS)
class FrenchSourceTests(SimpleTestCase):
    def test_grants_bind_user_exact_source_privacy_and_substring(self):
        token = source_grant("Bonjour !\n\nUn exemple français.", 7, private=False)
        self.assertEqual(resolve_sources([{"grant": token}], 7), (
            "Bonjour ! Un exemple français.", None,
        ))
        self.assertEqual(resolve_sources([{"grant": token, "text": "Un exemple"}], 7), (
            "Un exemple", None,
        ))
        for source, user in (
            ({"grant": token}, 8), ({"grant": token + "x"}, 7),
            ({"grant": token, "text": "Un autre texte"}, 7),
            ({"grant": token, "text": ""}, 7),
        ):
            with self.subTest(source=source, user=user), self.assertRaises(SpeechError):
                resolve_sources([source], user)

    def test_private_consent_is_explicit_not_truthy(self):
        source = {"grant": source_grant("Mon texte privé.", 7)}
        for consent in (False, None, "true", 1):
            with self.subTest(consent=consent), self.assertRaisesMessage(SpeechError, "accord explicite"):
                resolve_sources([source], 7, consent=consent)
        self.assertEqual(resolve_sources([source], 7, consent=True), ("Mon texte privé.", 7))

    def test_expired_grants_are_not_sources(self):
        with patch("django.core.signing.time.time", return_value=1000):
            source = {"grant": source_grant("Bonjour.", 7, private=False)}
        with patch("django.core.signing.time.time", return_value=4601):
            with self.assertRaisesMessage(SpeechError, "expirée"):
                resolve_sources([source], 7)

    def test_size_shape_and_aggregate_limits(self):
        self.assertEqual(source_grant("x" * (MAX_TEXT + 1), 7), "")
        self.assertEqual(source_grant("Bonjour.", None), "")
        source = {"grant": source_grant("x" * 6000, 7, private=False)}
        other = {"grant": source_grant("y" * 6000, 7, private=False)}
        for sources in (None, [], {}, ["bad"], [{}], [source, other], [source] * 33):
            with self.subTest(sources=str(sources)[:30]), self.assertRaises(SpeechError):
                resolve_sources(sources, 7)

    def test_identity_covers_text_voice_model_owner_and_prosody(self):
        original = speech_spec("Bonjour.")
        self.assertEqual(original, speech_spec("Bonjour."))
        self.assertNotEqual(original.fingerprint, speech_spec("Bonsoir.").fingerprint)
        self.assertNotEqual(original.fingerprint, speech_spec("Bonjour.", 7).fingerprint)
        for settings in (
            {"ELEVENLABS_VOICE_ID": "OtherVoice"},
            {"ELEVENLABS_MODEL_ID": "eleven_v3"},
        ):
            with self.settings(**settings):
                self.assertNotEqual(original.fingerprint, speech_spec("Bonjour.").fingerprint)
        with patch("study.french_audio.VOICE_SETTINGS", {"speed": 0.9}):
            self.assertNotEqual(original.fingerprint, speech_spec("Bonjour.").fingerprint)

    def test_template_issues_only_bounded_french_source_without_text_changes(self):
        html = Template(
            '{% load study_speech %}<p {% speech_attrs text private=False user_id=7 %}>{{ text|safe }}</p>'
        ).render(Context({"text": "Bonjour <strong>à tous</strong>&nbsp;!"}))
        source = Sources(html).sources[0]
        self.assertEqual(source["data-speech-text"], "Bonjour à tous !")
        payload = signing.loads(source["data-speech-grant"], salt=SALT)
        self.assertEqual(payload["text"], "Bonjour à tous !")
        self.assertFalse(payload["private"])
        self.assertNotIn(AUDIO_SETTINGS["ELEVENLABS_API_KEY"], html)


@override_settings(**SETTINGS)
class FrenchAudioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = factories.make_user("shared-reader")
        cls.other = factories.make_user("other-reader")

    def setUp(self):
        self.client.force_login(self.user)
        self.endpoint = reverse("study:french_audio_resolve")
        self.text = "Bonjour, voici un exemple français."
        self.source = {"grant": source_grant(self.text, self.user.pk, private=False)}
        self.spec = speech_spec(self.text)

    def post(self, **kwargs):
        return self.client.post(
            self.endpoint, {"sources": [self.source], "pin": AUDIO_PIN, **kwargs}, content_type="application/json",
        )

    def ready(self, private=False):
        spec = speech_spec(self.text, self.user.pk if private else None)
        return FrenchNarration.objects.create(
            fingerprint=spec.fingerprint, text=self.text, owner=self.user if private else None,
            requested_by=self.user, voice_id=spec.voice_id, model_id=spec.model_id,
            audio=AUDIO * 10, status="ready",
        )

    @patch("study.french_audio.synthesize")
    def test_http_only_resolves_cache_never_generates_or_enqueues_implicitly(self, provider):
        response = self.post()
        self.assertEqual(response.json()["state"], "missing")
        self.assertFalse(response.json()["can_request"])
        self.assertFalse(FrenchNarration.objects.exists())
        recording = self.ready()
        response = self.post()
        self.assertEqual(response.json()["state"], "ready")
        self.assertEqual(response.json()["url"], reverse("study:french_audio", args=[recording.pk]))
        self.assertEqual(self.post(prepare=True, pin=None).status_code, 200)
        self.assertEqual(self.client.get(response.json()["url"]).status_code, 200)
        provider.assert_not_called()

    def test_disabled_feature_invalid_configuration_and_bad_input_are_explicit(self):
        with self.settings(FRENCH_AUDIO_ENABLED=False):
            self.assertEqual(self.post().status_code, 503)
        with self.settings(ELEVENLABS_VOICE_ID=""):
            self.assertEqual(self.post().json()["error"], "configuration")
        for data in ('not JSON', '[]', '"text"'):
            self.assertEqual(self.client.post(
                self.endpoint, data, content_type="application/json",
            ).status_code, 400)
        self.assertEqual(self.client.post(
            self.endpoint, "x" * 150001, content_type="application/json",
        ).status_code, 413)
        self.assertEqual(self.post(sources=[]).json()["error"], "source")
        self.assertEqual(self.client.get(self.endpoint).status_code, 405)

    def test_login_csrf_and_grant_ownership_are_required(self):
        self.client.logout()
        self.assertEqual(self.post().status_code, 302)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post(
            self.endpoint, {"sources": [self.source]}, content_type="application/json",
        ).status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.post().status_code, 403)

    @patch("study.french_audio.synthesize")
    def test_private_resolve_requires_new_explicit_consent_even_when_cached(self, provider):
        recording = self.ready(private=True)
        self.source = {"grant": source_grant(self.text, self.user.pk)}
        self.assertEqual(self.post().json()["error"], "consent")
        self.assertEqual(self.post(consent="true").status_code, 403)
        url = self.post(consent=True).json()["url"]
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.user.delete()
        self.assertFalse(FrenchNarration.objects.filter(pk=recording.pk).exists())
        provider.assert_not_called()

    def test_byte_ranges_head_gzip_and_stale_config(self):
        recording = self.ready()
        url = reverse("study:french_audio", args=[recording.pk])
        data = bytes(recording.audio)
        for method, headers, expected in (
            ("get", {}, data),
            ("get", {"HTTP_RANGE": "bytes=1-700"}, data[1:701]),
            ("get", {"HTTP_RANGE": "bytes=-10"}, data[-10:]),
            ("head", {}, b""),
        ):
            response = getattr(self.client, method)(url, HTTP_ACCEPT_ENCODING="gzip", **headers)
            self.assertEqual(response.content, expected)
            self.assertEqual(response["Content-Encoding"], "identity")
            self.assertEqual(response["Cache-Control"], "private, no-store")
        for value in ("bytes=999999-", "bytes=2-1", "bytes=-0", "bytes=0-1,2-3"):
            self.assertEqual(self.client.get(url, HTTP_RANGE=value).status_code, 416)
        self.assertEqual(self.client.post(url).status_code, 405)
        with self.settings(ELEVENLABS_VOICE_ID="OtherVoice"):
            self.assertEqual(self.client.get(url).status_code, 404)
        with self.settings(FRENCH_AUDIO_ENABLED=False):
            self.assertEqual(self.client.get(url).status_code, 404)

    @override_settings(FRENCH_AUDIO_GENERATION_ENABLED=True, FRENCH_AUDIO_CHARACTER_BUDGET=500)
    @patch("study.french_audio.synthesize", return_value=AUDIO)
    def test_preparation_needs_confirmation_and_is_deduplicated_and_bounded(self, provider):
        self.assertEqual(self.post().json()["state"], "missing")
        self.assertEqual(self.post(prepare=True).status_code, 400)
        provider.assert_not_called()
        first = self.post(prepare=True, confirm_cost=True).json()
        self.assertEqual(first["state"], "ready")
        self.assertEqual(self.post(prepare=True, confirm_cost=True).json()["url"], first["url"])
        for index in range(3):
            enqueue(speech_spec(f"Autre exemple {index}."), self.user.pk, None)
        self.source = {"grant": source_grant("Encore un exemple.", self.user.pk, private=False)}
        self.assertEqual(self.post(prepare=True, confirm_cost=True).status_code, 429)
        self.assertEqual(FrenchNarration.objects.count(), 4)
        self.assertEqual(FrenchNarrationBudget.objects.get().reserved_characters, len(self.text))
        provider.assert_called_once()

    @override_settings(FRENCH_AUDIO_GENERATION_ENABLED=True, FRENCH_AUDIO_CHARACTER_BUDGET=500)
    def test_daily_queue_limit_includes_completed_requests(self):
        for index in range(10):
            enqueue(speech_spec(f"Exemple numéro {index}."), self.user.pk, None)
            FrenchNarration.objects.update(status="ready")
        with self.assertRaisesMessage(SpeechError, "Limite"):
            enqueue(self.spec, self.user.pk, None)

    @patch("study.french_audio.synthesize", return_value=AUDIO)
    @patch("study.management.commands.prepare_french_audio.command_generation_pin", return_value=AUDIO_PIN)
    def test_operator_requires_exact_id_confirmation_feature_gate_and_budget(self, pin_prompt, provider):
        recording = enqueue(self.spec, self.user.pk, None)
        call_command("prepare_french_audio", id=recording.pk, dry_run=True, stdout=StringIO())
        with self.assertRaisesMessage(CommandError, "--confirm-cost"):
            call_command("prepare_french_audio", id=recording.pk, stdout=StringIO())
        with self.assertRaisesMessage(CommandError, "explicitly enabled"):
            call_command("prepare_french_audio", id=recording.pk, confirm_cost=True, stdout=StringIO())
        with self.settings(FRENCH_AUDIO_GENERATION_ENABLED=True):
            with self.assertRaisesMessage(NarrationError, "ceiling"):
                generate_prepared(recording.pk, pin=AUDIO_PIN)
        provider.assert_not_called()

    @override_settings(FRENCH_AUDIO_GENERATION_ENABLED=True, FRENCH_AUDIO_CHARACTER_BUDGET=500)
    @patch("study.french_audio.synthesize", return_value=AUDIO)
    def test_operator_reserves_once_persists_audio_and_reuses_without_key(self, provider):
        recording = enqueue(self.spec, self.user.pk, None)
        self.assertTrue(generate_prepared(recording.pk, pin=AUDIO_PIN))
        with self.settings(ELEVENLABS_API_KEY=""):
            self.assertFalse(generate_prepared(recording.pk))
        recording.refresh_from_db()
        self.assertEqual(recording.status, "ready")
        self.assertEqual(bytes(recording.audio), AUDIO)
        self.assertEqual(FrenchNarrationBudget.objects.get().reserved_characters, len(self.text))
        provider.assert_called_once_with(self.spec)

    @override_settings(FRENCH_AUDIO_GENERATION_ENABLED=True, FRENCH_AUDIO_CHARACTER_BUDGET=500)
    @patch("study.french_audio.synthesize", side_effect=NarrationError("Provider failed; inspect usage."))
    def test_uncertain_failure_is_not_refunded_or_automatically_retried(self, provider):
        recording = enqueue(self.spec, self.user.pk, None)
        with self.assertRaisesMessage(NarrationError, "Provider failed"):
            generate_prepared(recording.pk, pin=AUDIO_PIN)
        self.assertEqual(FrenchNarration.objects.get().status, "failed")
        self.assertEqual(FrenchNarrationBudget.objects.get().reserved_characters, len(self.text))
        with self.assertRaisesMessage(NarrationError, "already attempted"):
            generate_prepared(recording.pk, pin=AUDIO_PIN)
        provider.assert_called_once()

    @override_settings(FRENCH_AUDIO_GENERATION_ENABLED=True, FRENCH_AUDIO_CHARACTER_BUDGET=500)
    @patch("study.french_audio.synthesize")
    def test_stale_requests_configuration_and_concurrent_work_fail_before_spend(self, provider):
        recording = enqueue(self.spec, self.user.pk, None)
        with self.settings(ELEVENLABS_VOICE_ID="OtherVoice"):
            with self.assertRaisesMessage(NarrationError, "changed"):
                generate_prepared(recording.pk, pin=AUDIO_PIN)
        FrenchNarration.objects.filter(pk=recording.pk).update(created_at=timezone.now() - timedelta(days=2))
        with self.assertRaisesMessage(NarrationError, "expired"):
            generate_prepared(recording.pk, pin=AUDIO_PIN)
        FrenchNarration.objects.filter(pk=recording.pk).update(created_at=timezone.now())
        busy = enqueue(speech_spec("En cours."), self.user.pk, None)
        FrenchNarration.objects.filter(pk=busy.pk).update(status="working")
        with self.assertRaisesMessage(NarrationError, "in progress"):
            generate_prepared(recording.pk, pin=AUDIO_PIN)
        provider.assert_not_called()
        self.assertEqual(FrenchNarrationBudget.objects.get().reserved_characters, 0)

    def test_private_and_public_identical_text_never_share_a_recording(self):
        public = self.ready()
        private = self.ready(private=True)
        self.assertNotEqual(public.pk, private.pk)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("study:french_audio", args=[public.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("study:french_audio", args=[private.pk])).status_code, 404)


@override_settings(**SETTINGS)
class FrenchReaderTemplateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = factories.make_user("template-reader")
        cls.task = factories.make_task(factories.make_part("ee"), "tache-1")
        cls.sujet = factories.make_writing_sujet(cls.task, versions=("Bonjour, voici mon modèle.",))

    def setUp(self):
        self.client.force_login(self.user)

    def page(self):
        return self.client.get(reverse("study:writing_sujet_detail", args=["ee", "tache-1", self.sujet.pk]))

    def test_public_ee_model_has_source_and_reader_without_annotation_text_change(self):
        response = self.page()
        self.assertContains(response, "data-read-aloud")
        source = Sources(response.content.decode()).sources[0]
        self.assertEqual(source["data-speech-private"], "false")
        self.assertEqual(source["data-speech-text"], "Bonjour, voici mon modèle.")
        with self.settings(FRENCH_AUDIO_ENABLED=False):
            before = self.page()
        self.assertEqual(
            AnnotationRootText(before.content.decode()).text,
            AnnotationRootText(response.content.decode()).text,
        )

    def test_private_override_of_shared_ee_model_does_not_receive_public_grant(self):
        from study.writing_responses import model_version_keys

        WritingResponseOverride.objects.create(
            user=self.user, sujet=self.sujet,
            version_key=model_version_keys(self.sujet.model_versions)[0],
            body="Mon contenu strictement privé.",
        )
        source = Sources(self.page().content.decode()).sources[0]
        self.assertEqual(source["data-speech-private"], "true")
        self.assertEqual(source["data-speech-text"], "Mon contenu strictement privé.")


@override_settings(**{**SETTINGS, "ELEVENLABS_VOICE_ID": "kENkNtk0xyzG09WW40xE"})
class InAppSampleTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("sample-listener")
        self.client.force_login(self.user)
        self.model = catalogue.tache_three_models()[SAMPLE_GROUP]
        self.spec = narration_spec(self.model)
        self.url = reverse("study:eo3_audio_prepare", args=["culture-p1", self.spec.fingerprint])

    def prepare(self, **kwargs):
        return self.client.post(self.url, {"confirm_cost": True, "pin": AUDIO_PIN, **kwargs}, content_type="application/json")

    @patch("study.french_audio.synthesize", return_value=(AUDIO, TIMING))
    def test_one_authorized_public_sample_writes_current_eo3_cache_and_reuses(self, provider):
        self.assertEqual(narration_presentation(self.model)["prepare_url"], self.url)
        response = self.prepare()
        self.assertEqual(response.status_code, 200)
        self.assertIn("data-eo3-audio", response.json()["html"])
        self.assertEqual(bytes(EO3Narration.objects.get().audio), AUDIO)
        self.assertEqual(FrenchNarration.objects.get().status, "ready")
        budget = FrenchNarrationBudget.objects.get()
        self.assertTrue(budget.sample_claimed)
        self.assertEqual(budget.reserved_characters, len(self.spec.text))
        self.assertEqual(self.prepare().status_code, 200)
        self.client.force_login(factories.make_user("second-listener"))
        self.assertEqual(self.prepare().status_code, 200)
        self.assertEqual(self.client.get(narration_presentation(self.model)["url"]).content, AUDIO)
        provider.assert_called_once_with(self.spec, timing=True)

    @patch("study.french_audio.synthesize")
    def test_confirmation_csrf_login_group_voice_and_feature_gate(self, provider):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.prepare(confirm_cost=False).status_code, 400)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.post(self.url, {"confirm_cost": True}, content_type="application/json").status_code, 403)
        self.assertEqual(self.client.post(reverse(
            "study:eo3_audio_prepare", args=["culture-p2", self.spec.fingerprint],
        ), {"confirm_cost": True}, content_type="application/json").status_code, 404)
        with self.settings(EO3_AUDIO_SAMPLE_ENABLED=False):
            self.assertEqual(self.prepare().status_code, 403)
        with self.settings(ELEVENLABS_VOICE_ID="OtherVoice"):
            self.assertEqual(self.prepare().status_code, 409)
        with self.settings(ON_VERCEL=True):
            self.assertEqual(self.prepare().status_code, 503)
        self.client.logout()
        self.assertEqual(self.prepare().status_code, 302)
        provider.assert_not_called()
        self.assertFalse(EO3Narration.objects.exists())
        self.assertFalse(FrenchNarrationBudget.objects.exists())

    @patch("study.french_audio.synthesize", side_effect=NarrationError("Provider timeout; inspect usage."))
    def test_ambiguous_sample_failure_claim_is_durable_and_never_retried(self, provider):
        self.assertEqual(self.prepare().status_code, 409)
        self.assertEqual(self.prepare().status_code, 409)
        self.assertTrue(FrenchNarrationBudget.objects.get().sample_claimed)
        self.assertEqual(FrenchNarration.objects.get().status, "failed")
        presentation = narration_presentation(self.model)
        self.assertEqual(presentation["prepare_url"], "")
        self.assertTrue(presentation["sample_attempted"])
        provider.assert_called_once()

    @patch("study.french_audio.synthesize", return_value=(AUDIO, TIMING))
    def test_claim_is_global_even_after_text_or_model_changes(self, provider):
        self.assertEqual(self.prepare().status_code, 200)
        edited = replace(self.model, response=replace(self.model.response, conclusion="Autre conclusion."))
        with patch.object(catalogue, "tache_three_models", return_value={SAMPLE_GROUP: edited}):
            self.url = reverse("study:eo3_audio_prepare", args=["culture-p1", narration_spec(edited).fingerprint])
            self.assertEqual(self.prepare().status_code, 409)
        provider.assert_called_once()

    @patch("study.french_audio.synthesize", return_value=(AUDIO, TIMING))
    def test_missing_key_does_not_consume_the_single_attempt(self, provider):
        with self.settings(ELEVENLABS_API_KEY=""):
            self.assertEqual(self.prepare().status_code, 409)
            self.assertFalse(FrenchNarrationBudget.objects.exists())
        self.assertEqual(self.prepare().status_code, 200)
        provider.assert_called_once()

    @patch("study.french_audio.synthesize", side_effect=PreSynthesisRejection())
    def test_verified_plan_denial_keeps_proof_and_requires_a_different_voice(self, provider):
        response = self.prepare()
        self.assertEqual(response.status_code, 409)
        self.assertIn("voix par défaut", response.json()["message"])
        self.assertEqual(FrenchNarration.objects.get().status, "plan_denied")
        self.assertFalse(FrenchNarrationBudget.objects.get().sample_claimed)
        self.assertEqual(FrenchNarrationBudget.objects.get().reserved_characters, len(self.spec.text))
        self.assertFalse(narration_presentation(self.model)["prepare_url"])
        for _ in range(10):
            self.assertEqual(self.prepare().status_code, 409)
        self.client.force_login(factories.make_user("other-retry-listener"))
        self.assertEqual(self.prepare().status_code, 409)
        with self.settings(ELEVENLABS_MODEL_ID="other_model"):
            spec = narration_spec(self.model)
            self.url = reverse("study:eo3_audio_prepare", args=["culture-p1", spec.fingerprint])
            self.assertEqual(self.prepare().status_code, 409)
        provider.assert_called_once()
        with self.settings(ELEVENLABS_VOICE_ID="DefaultVoice"):
            spec = narration_spec(self.model)
            self.url = reverse("study:eo3_audio_prepare", args=["culture-p1", spec.fingerprint])
            self.assertTrue(narration_presentation(self.model)["prepare_url"])
            self.assertEqual(self.prepare(confirm_cost=False).status_code, 400)
            provider.side_effect = None
            provider.return_value = (AUDIO, TIMING)
            self.assertEqual(self.prepare(player_id="eo3-response-player").status_code, 200)
            self.assertEqual(bytes(EO3Narration.objects.get().audio), AUDIO)
            self.assertTrue(FrenchNarrationBudget.objects.get().sample_claimed)
            self.assertEqual(self.prepare().status_code, 200)
        self.assertEqual(provider.call_count, 2)

    @patch("study.french_audio.synthesize", side_effect=PreSynthesisRejection())
    def test_verified_denials_are_globally_bounded_across_voices(self, provider):
        for index in range(SAMPLE_REJECTION_LIMIT + 1):
            with self.settings(ELEVENLABS_VOICE_ID=f"RestrictedVoice{index}"):
                spec = narration_spec(self.model)
                self.url = reverse("study:eo3_audio_prepare", args=["culture-p1", spec.fingerprint])
                self.assertEqual(self.prepare().status_code, 409)
        self.assertEqual(provider.call_count, SAMPLE_REJECTION_LIMIT)
        self.assertEqual(FrenchNarration.objects.filter(status="plan_denied").count(), SAMPLE_REJECTION_LIMIT)
        self.assertFalse(FrenchNarrationBudget.objects.get().sample_claimed)
        self.assertFalse(narration_presentation(self.model)["prepare_url"])

    @patch("study.french_audio.synthesize", side_effect=NarrationError("HTTP 403 without proof."))
    def test_unclassified_legacy_failure_stays_locked_after_voice_change(self, provider):
        self.assertEqual(self.prepare().status_code, 409)
        self.assertEqual(FrenchNarration.objects.get().status, "failed")
        self.assertTrue(FrenchNarrationBudget.objects.get().sample_claimed)
        with self.settings(ELEVENLABS_VOICE_ID="DefaultVoice"):
            spec = narration_spec(self.model)
            self.url = reverse("study:eo3_audio_prepare", args=["culture-p1", spec.fingerprint])
            self.assertEqual(self.prepare().status_code, 409)
            presentation = narration_presentation(self.model)
            self.assertFalse(presentation["prepare_url"])
            self.assertIn("motif exact n’a pas été conservé", presentation["sample_issue"])
        provider.assert_called_once()
