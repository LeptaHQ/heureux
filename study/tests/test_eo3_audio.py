from dataclasses import replace
from email.message import Message
from http.client import IncompleteRead
from io import BytesIO, StringIO
import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from django.core.management import call_command
from django.core.management.base import CommandError
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from study import catalogue
from study.account_services import provision_user_study_data
from study.card_presentation import card_payload
from study.eo3_audio import (
    MAX_AUDIO_BYTES, NarrationError, _NoRedirect, generate_narration,
    narration_presentation, narration_spec, synthesize,
)
from study.models import Card, CardType, EO3Narration, PersonalResponse, Prompt
from study.oral_highlights import AnnotationRootText
from study.routing import prompt_detail_url
from study.tache_three_models import spoken_text

from . import factories


AUDIO = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb" + b"\x00" * 200
AUDIO_SETTINGS = {
    "EO3_AUDIO_ENABLED": True,
    "ELEVENLABS_API_KEY": "test-secret-do-not-render",
    "ELEVENLABS_VOICE_ID": "FrenchFemaleVoice",
    "ELEVENLABS_MODEL_ID": "eleven_multilingual_v2",
}


def upstream(audio=AUDIO, content_type="audio/mpeg"):
    response = MagicMock()
    response.headers = Message()
    response.headers["Content-Type"] = content_type
    response.read.return_value = audio
    response.__enter__.return_value = response
    return response


@override_settings(**AUDIO_SETTINGS)
class EO3AudioSpecTests(SimpleTestCase):
    def setUp(self):
        self.model = catalogue.tache_three_models()["eo/tache-3/culture-p1"]

    def test_every_model_uses_exact_spoken_words_in_six_paragraphs(self):
        for model in catalogue.tache_three_models().values():
            with self.subTest(group=model.group):
                spec = narration_spec(model)
                self.assertEqual(" ".join(spec.text.split()), spoken_text(model.response))
                self.assertEqual(len(spec.text.split("\n\n")), 6)
                self.assertNotIn("Introduction\n", spec.text)
                self.assertEqual(len(spec.fingerprint), 64)

    def test_cache_identity_changes_with_text_voice_model_or_prosody(self):
        original = narration_spec(self.model)
        edited = replace(self.model, response=replace(
            self.model.response, conclusion="Une autre conclusion.",
        ))
        self.assertNotEqual(original.fingerprint, narration_spec(edited).fingerprint)
        for setting in (
            {"ELEVENLABS_VOICE_ID": "OtherFrenchVoice"},
            {"ELEVENLABS_MODEL_ID": "eleven_v3"},
        ):
            with self.settings(**setting):
                self.assertNotEqual(original.fingerprint, narration_spec(self.model).fingerprint)
        with patch("study.eo3_audio.VOICE_SETTINGS", {"speed": 0.9}):
            self.assertNotEqual(original.fingerprint, narration_spec(self.model).fingerprint)
        self.assertEqual(original.fingerprint, narration_spec(self.model).fingerprint)

    def test_private_responses_and_invalid_configuration_are_rejected(self):
        private = replace(self.model, response=replace(self.model.response, is_personal=True))
        with self.assertRaisesMessage(NarrationError, "public EO3"):
            narration_spec(private)
        for voice in ("", "../voice", "voice?key=bad"):
            with self.settings(ELEVENLABS_VOICE_ID=voice):
                with self.assertRaisesMessage(NarrationError, "VOICE_ID"):
                    narration_spec(self.model)

    def test_disabled_player_performs_no_database_lookup(self):
        with self.settings(EO3_AUDIO_ENABLED=False):
            self.assertIsNone(narration_presentation(self.model))
        self.assertIsNone(narration_presentation(None))

    @patch("study.eo3_audio.build_opener")
    def test_provider_request_is_server_only_normal_speed_and_bounded(self, opener):
        audio = upstream()
        opener.return_value.open.return_value = audio
        spec = narration_spec(self.model)
        self.assertEqual(synthesize(spec), AUDIO)
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertTrue(request.full_url.startswith("https://api.elevenlabs.io/v1/text-to-speech/"))
        self.assertEqual(request.get_header("Xi-api-key"), AUDIO_SETTINGS["ELEVENLABS_API_KEY"])
        payload = json.loads(request.data)
        self.assertEqual(payload["text"], spec.text)
        self.assertEqual(payload["voice_settings"]["speed"], 1.0)
        self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], 90)
        audio.read.assert_called_once_with(MAX_AUDIO_BYTES + 1)
        self.assertIsInstance(opener.call_args.args[0], _NoRedirect)

    @patch("study.eo3_audio.build_opener")
    def test_missing_key_makes_no_request(self, opener):
        with self.settings(ELEVENLABS_API_KEY=""):
            with self.assertRaisesMessage(NarrationError, "API_KEY"):
                synthesize(narration_spec(self.model))
        opener.assert_not_called()

    @patch("study.eo3_audio.build_opener")
    def test_provider_errors_are_explicit_sanitized_and_never_retried(self, opener):
        for error in (
            HTTPError("https://example.invalid", 429, "private provider detail", {}, BytesIO()),
            URLError("private provider detail"),
            TimeoutError("private provider detail"),
            IncompleteRead(b"private provider detail"),
        ):
            with self.subTest(error=type(error)):
                opener.reset_mock()
                opener.return_value.open.side_effect = error
                with self.assertRaises(NarrationError) as caught:
                    synthesize(narration_spec(self.model))
                self.assertNotIn("private provider detail", str(caught.exception))
                self.assertNotIn(AUDIO_SETTINGS["ELEVENLABS_API_KEY"], str(caught.exception))
                opener.return_value.open.assert_called_once()

    @patch("study.eo3_audio.build_opener")
    def test_non_audio_empty_corrupt_and_oversized_responses_fail(self, opener):
        for data, content_type in (
            (b'{"error":"quota"}', "application/json"),
            (b"", "audio/mpeg"), (b"not an MP3", "audio/mpeg"),
            (b"ID3" + b"\x00" * MAX_AUDIO_BYTES, "audio/mpeg"),
        ):
            with self.subTest(size=len(data), content_type=content_type):
                opener.return_value.open.return_value = upstream(data, content_type)
                with self.assertRaisesMessage(NarrationError, "invalid or oversized"):
                    synthesize(narration_spec(self.model))

    def test_provider_redirects_are_not_followed_with_credentials(self):
        self.assertIsNone(_NoRedirect().redirect_request(
            None, None, 302, "", {}, "https://another-host.invalid",
        ))


@override_settings(**AUDIO_SETTINGS)
class EO3AudioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("narration-listener")
        provision_user_study_data(cls.user)

    def setUp(self):
        self.client.force_login(self.user)
        self.model = catalogue.tache_three_models()["eo/tache-3/culture-p1"]
        self.spec = narration_spec(self.model)
        self.prompt = Prompt.objects.select_related(
            "response__theme__task__part", "theme__task__part", "family",
        ).get(content_key="culture:p1")
        self.url = reverse("study:eo3_audio", args=["culture-p1", self.spec.fingerprint])

    def save_recording(self):
        return EO3Narration.objects.create(
            fingerprint=self.spec.fingerprint, group=self.spec.group,
            voice_id=self.spec.voice_id, model_id=self.spec.model_id, audio=AUDIO,
        )

    @patch("study.eo3_audio.synthesize", return_value=AUDIO)
    def test_generation_is_persistent_and_reuses_without_another_paid_call(self, provider):
        self.assertTrue(generate_narration(self.spec))
        self.assertFalse(generate_narration(self.spec))
        self.assertEqual(bytes(EO3Narration.objects.get().audio), AUDIO)
        provider.assert_called_once()

    @patch("study.eo3_audio.synthesize", side_effect=NarrationError("Provider failed."))
    def test_failure_rolls_back_the_reservation(self, provider):
        with self.assertRaisesMessage(NarrationError, "Provider failed"):
            generate_narration(self.spec)
        self.assertFalse(EO3Narration.objects.exists())

    @patch("study.eo3_audio.synthesize")
    def test_command_estimate_and_confirmation_prevent_unintended_spend(self, provider):
        output = StringIO()
        call_command("generate_eo3_audio", group="culture-p1", dry_run=True, stdout=output)
        self.assertIn("1 to generate", output.getvalue())
        self.assertIn(str(len(self.spec.text)), output.getvalue())
        with self.assertRaisesMessage(CommandError, "--confirm-cost"):
            call_command("generate_eo3_audio", group="culture-p1", stdout=StringIO())
        with self.assertRaisesMessage(CommandError, "Unknown"):
            call_command("generate_eo3_audio", group="not-a-subject", dry_run=True)
        with self.assertRaisesMessage(CommandError, "not allowed with argument"):
            call_command("generate_eo3_audio", "--all", "--group", "culture-p1")
        provider.assert_not_called()
        self.assertFalse(EO3Narration.objects.exists())

    @patch("study.eo3_audio.synthesize", return_value=AUDIO)
    def test_confirmed_command_generates_one_and_skips_cached_audio_without_key(self, provider):
        call_command("generate_eo3_audio", group="culture-p1", confirm_cost=True, stdout=StringIO())
        with self.settings(ELEVENLABS_API_KEY=""):
            call_command("generate_eo3_audio", group="culture-p1", confirm_cost=True, stdout=StringIO())
        provider.assert_called_once()
        self.assertEqual(EO3Narration.objects.count(), 1)

    @patch("study.eo3_audio.synthesize")
    def test_playback_never_generates_and_requires_login(self, provider):
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.save_recording()
        response = self.client.get(self.url)
        self.assertEqual(response.content, AUDIO)
        self.assertEqual(response["Content-Type"], "audio/mpeg")
        self.assertEqual(response["Accept-Ranges"], "bytes")
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-cache", response["Cache-Control"])
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        provider.assert_not_called()

    def test_range_seeking_head_and_conditional_requests(self):
        self.save_recording()
        for value, start, end in (
            ("bytes=5-15", 5, 15), ("bytes=10-", 10, len(AUDIO) - 1),
            ("bytes=-10", len(AUDIO) - 10, len(AUDIO) - 1),
            ("bytes=0-99999", 0, len(AUDIO) - 1),
        ):
            with self.subTest(range=value):
                response = self.client.get(self.url, HTTP_RANGE=value)
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response.content, AUDIO[start:end + 1])
                self.assertEqual(response["Content-Range"], f"bytes {start}-{end}/{len(AUDIO)}")
        head = self.client.head(self.url)
        self.assertEqual(head.content, b"")
        self.assertEqual(head["Content-Length"], str(len(AUDIO)))
        etag = self.client.get(self.url)["ETag"]
        self.assertEqual(self.client.get(self.url, HTTP_IF_NONE_MATCH=etag).status_code, 304)
        self.assertEqual(self.client.get(self.url, HTTP_RANGE="bytes=0-5", HTTP_IF_RANGE='"other"').status_code, 200)
        for value in (
            "bytes=-0", "bytes=-", "bytes=99999-", "bytes=15-5",
            "bytes=0-5,10-15", "bytes=invalid", "bytes=" + "9" * 5000 + "-",
        ):
            with self.subTest(invalid_range=value):
                response = self.client.get(self.url, HTTP_RANGE=value)
                self.assertEqual(response.status_code, 416)
                self.assertEqual(response["Content-Range"], f"bytes */{len(AUDIO)}")
        self.assertEqual(self.client.post(self.url).status_code, 405)

    def test_stale_text_voice_model_and_disabled_feature_do_not_serve_old_audio(self):
        self.save_recording()
        updated = replace(self.model, response=replace(self.model.response, conclusion="Autre réponse."))
        with patch.object(catalogue, "tache_three_models", return_value={self.model.group: updated}):
            self.assertEqual(self.client.get(self.url).status_code, 404)
        for change in (
            {"ELEVENLABS_VOICE_ID": "DifferentVoice"},
            {"ELEVENLABS_MODEL_ID": "eleven_v3"},
            {"EO3_AUDIO_ENABLED": False},
        ):
            with self.settings(**change):
                self.assertEqual(self.client.get(self.url).status_code, 404)
        unknown = reverse("study:eo3_audio", args=["not-a-group", self.spec.fingerprint])
        self.assertEqual(self.client.get(unknown).status_code, 404)

    def test_player_on_detail_and_back_preserves_exact_annotation_text(self):
        self.save_recording()
        card = Card.objects.get(user=self.user, response=self.prompt.response, card_type=CardType.SPINE)
        with self.settings(EO3_AUDIO_ENABLED=False):
            before = self.client.get(prompt_detail_url(self.prompt))
            before_back = render_to_string("study/partials/card_back.html", card_payload(card, prompt=self.prompt))
        after = self.client.get(prompt_detail_url(self.prompt))
        payload = card_payload(card, prompt=self.prompt)
        after_back = render_to_string("study/partials/card_back.html", payload)
        self.assertEqual(payload["eo3_audio"]["url"], self.url)
        self.assertContains(after, 'value="0.85" selected')
        self.assertContains(after, 'preload="none"')
        self.assertContains(after, "Voix française de synthèse")
        self.assertNotContains(after, AUDIO_SETTINGS["ELEVENLABS_API_KEY"])
        self.assertNotContains(after, AUDIO_SETTINGS["ELEVENLABS_VOICE_ID"])
        self.assertEqual(AnnotationRootText(before.content.decode()).text, AnnotationRootText(after.content.decode()).text)
        self.assertEqual(
            AnnotationRootText("<div data-annotation-root>" + before_back + "</div>").text,
            AnnotationRootText("<div data-annotation-root>" + after_back + "</div>").text,
        )
        self.assertNotIn('class="answer" data-read-aloud-text', after_back)
        front = render_to_string("study/partials/card_front.html", payload)
        self.assertNotIn("data-eo3-player", front)

    def test_pending_and_unconfigured_states_are_explicit_without_generation(self):
        self.assertContains(self.client.get(prompt_detail_url(self.prompt)), "n'est pas encore prête")
        with self.settings(ELEVENLABS_VOICE_ID=""):
            self.assertContains(self.client.get(prompt_detail_url(self.prompt)), "n'est pas encore configurée")

    def test_equivalent_publications_share_the_same_canonical_recording(self):
        model = catalogue.tache_three_models()["eo/tache-3/culture-p3"]
        spec = narration_spec(model)
        EO3Narration.objects.create(
            fingerprint=spec.fingerprint, group=spec.group,
            voice_id=spec.voice_id, model_id=spec.model_id, audio=AUDIO,
        )
        urls = []
        for key in ("culture:p3", "economie:p5"):
            prompt = Prompt.objects.select_related("theme__task__part").get(content_key=key)
            page = self.client.get(prompt_detail_url(prompt))
            urls.append(page.context["eo3_audio"]["url"])
        self.assertEqual(urls[0], urls[1])
        self.assertEqual(self.client.get(urls[0]).content, AUDIO)

    def test_personal_response_does_not_offer_or_send_public_narration(self):
        self.save_recording()
        PersonalResponse.objects.create(
            user=self.user, response=self.prompt.response, position_claire="Mon introduction privée.",
            arguments=[{
                "order": 1, "idea": "Mon idée privée.", "developpement": "Ma raison.",
                "exemple": "Mon exemple.", "consequence": "Ma conséquence.",
            }],
            nuance="Ma nuance.", conclusion="Ma conclusion.",
        )
        page = self.client.get(prompt_detail_url(self.prompt))
        self.assertNotContains(page, "data-eo3-player")
        card = Card.objects.get(user=self.user, response=self.prompt.response, card_type=CardType.SPINE)
        self.assertIsNone(card_payload(card, prompt=self.prompt)["eo3_audio"])
