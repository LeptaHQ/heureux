import base64
from dataclasses import replace
from http.client import IncompleteRead
from io import StringIO
import json
from unittest.mock import patch

import httpx
from elevenlabs.text_to_speech.raw_client import RawTextToSpeechClient

from django.core.management import call_command
from django.core.management.base import CommandError
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from study import catalogue
from study.account_services import provision_user_study_data
from study.card_presentation import card_payload
from study.eo3_audio import (
    MAX_AUDIO_BYTES, MAX_ERROR_BYTES, NarrationError, PreSynthesisRejection, VOICE_SETTINGS,
    _check_provider_request, generate_narration, narration_presentation, narration_spec, synthesize,
    word_timings,
)
from study.models import (
    Card, CardType, EO3Narration, FrenchNarration, PersonalResponse, Prompt, Response,
)
from study.response_personalization import effective_response
from study.oral_highlights import AnnotationRootText
from study.routing import prompt_detail_url
from study.tache_three_models import spoken_text

from . import factories


AUDIO = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb" + b"\x00" * 200
TIMING = [[["Bonjour", 0, 400]], [["Merci", 500, 900]]]
AUDIO_PIN = "test-audio-pin"
AUDIO_SETTINGS = {
    "EO3_AUDIO_ENABLED": True,
    "ELEVENLABS_API_KEY": "test-secret-do-not-render",
    "ELEVENLABS_PIN": AUDIO_PIN,
    "ELEVENLABS_VOICE_ID": "FrenchFemaleVoice",
    "ELEVENLABS_MODEL_ID": "eleven_multilingual_v2",
}


def upstream(audio=AUDIO, content_type="audio/mpeg", status=200, headers=None):
    return httpx.Response(
        status, headers={"Content-Type": content_type, **(headers or {})}, stream=httpx.ByteStream(audio),
    )


def timed_upstream(text):
    characters = list(text)
    body = json.dumps({
        "audio_base64": base64.b64encode(AUDIO).decode(),
        "alignment": {
            "characters": characters,
            "character_start_times_seconds": [index * 0.05 for index in range(len(characters))],
            "character_end_times_seconds": [(index + 1) * 0.05 for index in range(len(characters))],
        },
    }).encode()
    return upstream(body, "application/json", headers={"Content-Length": str(len(body))})


class BrokenStream(httpx.SyncByteStream):
    def __iter__(self):
        raise IncompleteRead(b"private provider detail")
        yield b""  # pragma: no cover


@override_settings(**AUDIO_SETTINGS)
class EO3AudioSpecTests(SimpleTestCase):
    def setUp(self):
        self.model = catalogue.tache_three_models()["eo/tache-3/culture-p1"]

    def provider(self, factory, response=None, error=None):
        requests = []

        def handle(request):
            requests.append(request)
            if error:
                raise error
            return response

        factory.return_value = httpx.MockTransport(handle)
        return requests

    def test_every_model_reads_prompt_then_exact_spoken_words(self):
        for model in catalogue.tache_three_models().values():
            with self.subTest(group=model.group):
                spec = narration_spec(model)
                prompt, _, answer = spec.text.partition("\n\n")
                self.assertEqual(prompt, model.source_prompts[0][1])
                self.assertEqual(" ".join(answer.split()), spoken_text(model.response))
                self.assertEqual(len(spec.text.split("\n\n")), 7)
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

    def test_word_timings_follow_exact_text_by_paragraph(self):
        text = "Faut-il partir ?\n\nOui, l’été à 20 ans."
        characters = list(text.replace("\n\n", " "))
        starts = [index / 10 for index in range(len(characters))]
        ends = [value + 0.1 for value in starts]
        self.assertEqual(word_timings(text, characters, starts, ends), [
            [["Faut-il", 0, 700], ["partir", 800, 1400]],
            [["Oui", 1700, 2000], ["l’été", 2200, 2700], ["à", 2800, 2900],
             ["20", 3000, 3200], ["ans", 3300, 3600]],
        ])
        self.assertEqual(word_timings(text, list("Autre texte"), starts[:11], ends[:11]), [])
        self.assertEqual(word_timings(text, characters, starts, ends[:-1]), [])

    @patch("study.eo3_audio.httpx.HTTPTransport")
    def test_timed_provider_request_returns_audio_and_word_timings(self, factory):
        spec = narration_spec(self.model)
        requests = self.provider(factory, timed_upstream(spec.text))
        audio, timing = synthesize(spec, timing=True)
        self.assertEqual(audio, AUDIO)
        self.assertEqual(len(timing), 7)
        self.assertEqual(timing[0][0][0], spec.text.split()[0])
        self.assertEqual(timing[0][0][1], 0)
        self.assertEqual(
            str(requests[0].url),
            f"https://api.elevenlabs.io/v1/text-to-speech/{spec.voice_id}/with-timestamps?output_format=mp3_44100_64",
        )
        self.assertEqual(requests[0].headers["accept"], "application/json")
        self.assertEqual(json.loads(requests[0].content)["text"], spec.text)
        for response in (
            httpx.Response(200, headers={"Content-Type": "audio/mpeg"}, content=AUDIO),
            httpx.Response(200, headers={"Content-Type": "application/json"}, content=b'{"audio_base64": "!!"}'),
            httpx.Response(200, headers={"Content-Type": "application/json", "Content-Length": str(17 * 1024 * 1024)}, content=b"{}"),
        ):
            with self.subTest(response=response.headers), self.assertRaises(NarrationError):
                self.provider(factory, response)
                synthesize(spec, timing=True)

    @patch("study.eo3_audio.httpx.HTTPTransport")
    def test_provider_request_is_server_only_normal_speed_and_bounded(self, factory):
        requests = self.provider(factory, upstream())
        spec = narration_spec(self.model)
        with patch.object(
            RawTextToSpeechClient, "convert", autospec=True, side_effect=RawTextToSpeechClient.convert,
        ) as convert, patch("study.eo3_audio.httpx.Client", wraps=httpx.Client) as client:
            self.assertEqual(synthesize(spec), AUDIO)
        self.assertEqual(convert.call_args.kwargs["request_options"], {
            "max_retries": 0, "timeout_in_seconds": 90, "chunk_size": 8192,
        })
        self.assertFalse(client.call_args.kwargs["follow_redirects"])
        self.assertFalse(client.call_args.kwargs["trust_env"])
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(str(request.url), f"https://api.elevenlabs.io/v1/text-to-speech/{spec.voice_id}?output_format=mp3_44100_64")
        self.assertEqual(request.headers["xi-api-key"], AUDIO_SETTINGS["ELEVENLABS_API_KEY"])
        self.assertEqual(request.headers["accept-encoding"], "identity")
        self.assertTrue(request.headers["user-agent"].startswith("elevenlabs/"))
        payload = json.loads(request.content)
        self.assertEqual(payload["text"], spec.text)
        self.assertEqual(payload["voice_settings"], VOICE_SETTINGS)
        self.assertEqual(payload["model_id"], spec.model_id)
        self.assertTrue(all(value == 90 for value in request.extensions["timeout"].values()))
        factory.assert_called_once_with(retries=0)

    @patch("study.eo3_audio.httpx.HTTPTransport")
    def test_missing_key_makes_no_request(self, factory):
        with self.settings(ELEVENLABS_API_KEY=""):
            with self.assertRaisesMessage(NarrationError, "API_KEY"):
                synthesize(narration_spec(self.model))
        factory.assert_not_called()

    @patch("study.eo3_audio.httpx.HTTPTransport")
    def test_provider_errors_are_explicit_sanitized_and_never_retried(self, factory):
        for error in (
            httpx.ConnectError("private provider detail"),
            httpx.ReadTimeout("private provider detail"),
            TimeoutError("private provider detail"),
            IncompleteRead(b"private provider detail"),
        ):
            with self.subTest(error=type(error)):
                requests = self.provider(factory, error=error)
                with self.assertRaises(NarrationError) as caught:
                    synthesize(narration_spec(self.model))
                self.assertNotIn("private provider detail", str(caught.exception))
                self.assertNotIn(AUDIO_SETTINGS["ELEVENLABS_API_KEY"], str(caught.exception))
                self.assertEqual(len(requests), 1)

    @patch("study.eo3_audio.httpx.HTTPTransport")
    def test_only_exact_structured_free_tier_rejection_is_definitive(self, factory):
        for http_code in (401, 403):
            for field in ("code", "status"):
                body = json.dumps({"detail": {
                    field: "free_users_not_allowed", "message": "private provider detail",
                }}).encode()
                self.provider(factory, upstream(body, "application/json", http_code))
                with self.subTest(http=http_code, field=field), self.assertRaises(PreSynthesisRejection) as caught:
                    synthesize(narration_spec(self.model))
                self.assertIn("voix par défaut", str(caught.exception))
                self.assertNotIn("private provider detail", str(caught.exception))
                self.assertEqual(caught.exception.code, "free_users_not_allowed")

    @patch("study.eo3_audio.httpx.HTTPTransport")
    def test_unknown_malformed_conflicting_and_server_errors_stay_ambiguous(self, factory):
        for http_code, body in (
            (403, b'{"detail":{"code":"voice_access_denied"}}'),
            (401, b'{"detail":{"code":"invalid_api_key"}}'),
            (403, b'{"detail":{"message":"free_users_not_allowed"}}'),
            (403, b'{"detail":{"code":null,"status":"free_users_not_allowed"}}'),
            (403, b'{"detail":{"code":"other","status":"free_users_not_allowed"}}'),
            (403, b'{"detail":{"code":["free_users_not_allowed"]}}'),
            (403, b'{"detail":"free_users_not_allowed"}'),
            (403, b'[]'),
            (403, b'\xff'),
            (403, b'{"detail":{"status":"free_users_not_allowed"'),
            (403, b'{"detail":{"code":"free_users_not_allowed","extra":"' + b"x" * MAX_ERROR_BYTES + b'"}}'),
            (500, b'{"detail":{"code":"free_users_not_allowed"}}'),
            (429, b'{"detail":{"code":"free_users_not_allowed"}}'),
        ):
            requests = self.provider(factory, upstream(body, "application/json", http_code))
            with self.subTest(http=http_code, body=body[:60]), self.assertRaises(NarrationError) as caught:
                synthesize(narration_spec(self.model))
            self.assertNotIsInstance(caught.exception, PreSynthesisRejection)
            self.assertNotIn("private detail", str(caught.exception))
            self.assertEqual(len(requests), 1)

    @patch("study.eo3_audio.httpx.HTTPTransport")
    def test_incomplete_error_body_does_not_prove_nonbillable_rejection(self, factory):
        self.provider(factory, httpx.Response(403, stream=BrokenStream()))
        with self.assertRaises(NarrationError) as caught:
            synthesize(narration_spec(self.model))
        self.assertNotIsInstance(caught.exception, PreSynthesisRejection)
        for declared_length in ("1", "999", "bad", "-1"):
            self.provider(factory, upstream(
                b'{"detail":{"code":"free_users_not_allowed"}}', "application/json", 403,
                {"Content-Length": declared_length},
            ))
            with self.subTest(length=declared_length), self.assertRaises(NarrationError) as caught:
                synthesize(narration_spec(self.model))
            self.assertNotIsInstance(caught.exception, PreSynthesisRejection)

    @patch("study.eo3_audio.httpx.HTTPTransport")
    def test_non_audio_empty_corrupt_and_oversized_responses_fail(self, factory):
        for data, content_type in (
            (b'{"error":"quota"}', "application/json"),
            (b"", "audio/mpeg"), (b"not an MP3", "audio/mpeg"),
            (b"ID3" + b"\x00" * MAX_AUDIO_BYTES, "audio/mpeg"),
        ):
            with self.subTest(size=len(data), content_type=content_type):
                self.provider(factory, upstream(data, content_type))
                with self.assertRaisesMessage(NarrationError, "invalid or oversized"):
                    synthesize(narration_spec(self.model))

    @patch("study.eo3_audio.httpx.HTTPTransport")
    def test_provider_redirects_are_not_followed_with_credentials(self, factory):
        requests = self.provider(factory, upstream(status=302, headers={"Location": "https://another-host.invalid"}))
        with self.assertRaisesMessage(NarrationError, "HTTP 302"):
            synthesize(narration_spec(self.model))
        self.assertEqual(len(requests), 1)
        for url in ("http://api.elevenlabs.io/v1/text-to-speech/Voice", "https://another-host.invalid/v1/text-to-speech/Voice"):
            with self.assertRaisesMessage(NarrationError, "fixed ElevenLabs"):
                _check_provider_request(httpx.Request("POST", url))

    @patch("study.eo3_audio.httpx.HTTPTransport")
    def test_adapter_rejects_invalid_sources_before_networking(self, factory):
        for changes in ({"voice_id": "../voice"}, {"text": "x" * 10001}, {"text": ""}, {"model_id": "model?bad"}):
            with self.subTest(changes=changes), self.assertRaisesMessage(NarrationError, "Invalid narration"):
                synthesize(replace(narration_spec(self.model), **changes))
        factory.assert_not_called()

    @patch("study.eo3_audio.httpx.HTTPTransport")
    def test_sdk_audio_stream_stops_at_limit_and_rejects_truncation_and_encoding(self, factory):
        chunks = []

        class LargeStream(httpx.SyncByteStream):
            def __iter__(self):
                for _ in range(MAX_AUDIO_BYTES // 8192 + 10):
                    chunks.append(1)
                    yield b"x" * 8192

        self.provider(factory, httpx.Response(200, headers={"Content-Type": "audio/mpeg"}, stream=LargeStream()))
        with self.assertRaisesMessage(NarrationError, "oversized"):
            synthesize(narration_spec(self.model))
        self.assertEqual(len(chunks), MAX_AUDIO_BYTES // 8192 + 1)
        for response in (
            upstream(headers={"Content-Length": str(len(AUDIO) + 1)}),
            upstream(headers={"Content-Encoding": "gzip"}),
            httpx.Response(200, headers={"Content-Type": "audio/mpeg"}, stream=BrokenStream()),
        ):
            self.provider(factory, response)
            with self.assertRaises(NarrationError):
                synthesize(narration_spec(self.model))

    @patch("study.eo3_audio.httpx.HTTPTransport")
    def test_error_hook_stops_before_sdk_can_buffer_unbounded_error_body(self, factory):
        chunks = []

        class LargeErrorStream(httpx.SyncByteStream):
            def __iter__(self):
                for _ in range(100):
                    chunks.append(1)
                    yield b" " * 1024

        self.provider(factory, httpx.Response(403, stream=LargeErrorStream()))
        with self.assertRaises(NarrationError) as caught:
            synthesize(narration_spec(self.model))
        self.assertNotIsInstance(caught.exception, PreSynthesisRejection)
        self.assertEqual(len(chunks), 5)


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

    @patch("study.eo3_audio.synthesize", return_value=(AUDIO, TIMING))
    def test_generation_is_persistent_and_reuses_without_another_paid_call(self, provider):
        self.assertTrue(generate_narration(self.spec, pin=AUDIO_PIN))
        self.assertFalse(generate_narration(self.spec))
        self.assertEqual(bytes(EO3Narration.objects.get().audio), AUDIO)
        self.assertEqual(EO3Narration.objects.get().timing, TIMING)
        provider.assert_called_once_with(self.spec, timing=True)

    @patch("study.eo3_audio.synthesize", side_effect=NarrationError("Provider failed."))
    def test_failure_rolls_back_the_reservation(self, provider):
        with self.assertRaisesMessage(NarrationError, "Provider failed"):
            generate_narration(self.spec, pin=AUDIO_PIN)
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

    @patch("study.eo3_audio.synthesize", return_value=(AUDIO, TIMING))
    @patch("study.management.commands.generate_eo3_audio.command_generation_pin", return_value=AUDIO_PIN)
    def test_confirmed_command_generates_one_and_skips_cached_audio_without_key(self, pin_prompt, provider):
        call_command("generate_eo3_audio", group="culture-p1", confirm_cost=True, stdout=StringIO())
        with self.settings(ELEVENLABS_API_KEY="", ELEVENLABS_PIN=""):
            call_command("generate_eo3_audio", group="culture-p1", confirm_cost=True, stdout=StringIO())
        provider.assert_called_once()
        pin_prompt.assert_called_once()
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

    def test_gzip_middleware_does_not_transform_mp3_byte_ranges(self):
        self.save_recording()
        for headers, expected in (
            ({"HTTP_ACCEPT_ENCODING": "gzip"}, AUDIO),
            ({"HTTP_ACCEPT_ENCODING": "gzip", "HTTP_RANGE": "bytes=0-210"}, AUDIO[:211]),
        ):
            with self.subTest(headers=headers):
                response = self.client.get(self.url, **headers)
                self.assertEqual(response.content, expected)
                self.assertEqual(response["Content-Encoding"], "identity")
                self.assertEqual(response["Content-Length"], str(len(expected)))

    def test_compact_progress_controls_preserve_legacy_annotation_text(self):
        context = {
            "response": self.prompt.response,
            "subject_progress": {
                "explicitly_completed": False, "status": "in_progress", "label": "En cours",
            },
            "subject_label": self.prompt.text,
            "part": self.prompt.theme.task.part,
            "task": self.prompt.theme.task,
            "hide_help": True,
            "csrf_token": "test-token",
        }
        legacy = render_to_string("study/partials/subject_progress_control.html", context)
        compact = render_to_string("study/partials/subject_progress_control.html", {
            **context, "compact_audio_control": True, "read_audio": {"ready": True},
        })
        self.assertEqual(
            AnnotationRootText("<div data-annotation-root>" + legacy + "</div>").text,
            AnnotationRootText("<div data-annotation-root>" + compact + "</div>").text,
        )
        self.assertIn('class="sr-only">J’ai terminé ce sujet</span>', compact)
        self.assertNotIn("data-eo3-toggle", compact)

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
        self.assertContains(after, 'aria-checked="true" data-eo3-speed="0.85"')
        self.assertContains(after, 'data-eo3-speed="2">2×</button>')
        self.assertContains(after, 'preload="metadata"')
        self.assertContains(after, 'data-eo3-toggle="eo3-response-player"')
        self.assertContains(after, 'data-eo3-speed="0.5">0,5×</button>')
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

    @override_settings(FRENCH_AUDIO_GENERATION_ENABLED=False)
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
        public = self.save_recording()
        PersonalResponse.objects.create(
            user=self.user, response=self.prompt.response, position_claire="Mon introduction privée.",
            arguments=[{
                "order": 1, "idea": "Mon idée privée.", "developpement": "Ma raison.",
                "exemple": "Mon exemple.", "consequence": "Ma conséquence.",
            }],
            nuance="Ma nuance.", conclusion="Ma conclusion.",
        )
        page = self.client.get(prompt_detail_url(self.prompt))
        self.assertNotContains(page, public.fingerprint)
        self.assertFalse(page.context["eo3_audio"]["ready"])
        self.assertContains(page, 'data-eo3-player data-flashcard-ignore-toggle aria-label="Écouter la réponse"')
        self.assertContains(page, " hidden data-eo3-player")
        card = Card.objects.get(user=self.user, response=self.prompt.response, card_type=CardType.SPINE)
        audio = card_payload(card, prompt=self.prompt)["eo3_audio"]
        self.assertFalse(audio["ready"])
        self.assertEqual(audio["url"], "")
        self.assertEqual(audio["prepare_url"], "")


ON_DEMAND_SETTINGS = {
    **AUDIO_SETTINGS, "FRENCH_AUDIO_GENERATION_ENABLED": True,
    "FRENCH_AUDIO_CHARACTER_BUDGET": 1_000_000, "ON_VERCEL": False,
}


@override_settings(**ON_DEMAND_SETTINGS)
class EO3OnDemandNarrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("on-demand-listener")

    def setUp(self):
        self.client.force_login(self.user)
        self.group = next(
            group for group in catalogue.tache_three_models()
            if group.startswith("eo/tache-3/") and group != "eo/tache-3/culture-p1"
        )
        self.model = catalogue.tache_three_models()[self.group]
        self.spec = narration_spec(self.model)
        self.url = reverse("study:eo3_audio_prepare", args=[
            self.group.removeprefix("eo/tache-3/"), self.spec.fingerprint,
        ])

    def prepare(self):
        return self.client.post(
            self.url, data=json.dumps({"confirm_cost": True, "player_id": "eo3-response-player", "pin": AUDIO_PIN}),
            content_type="application/json",
        )

    def test_any_response_is_generated_once_then_reused(self):
        from study.eo3_audio import narration_presentation
        presentation = narration_presentation(self.model)
        self.assertTrue(presentation["on_demand"])
        self.assertEqual(presentation["prepare_url"], self.url)
        with patch("study.french_audio.synthesize", return_value=(AUDIO, TIMING)) as provider:
            first = self.prepare()
            second = self.prepare()
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(second.status_code, 200)
        self.assertIn("data-eo3-audio", first.json()["html"])
        self.assertIn("data-eo3-timing=", first.json()["html"])
        provider.assert_called_once_with(self.spec, timing=True)
        self.assertEqual(EO3Narration.objects.get().group, self.group)
        self.assertEqual(EO3Narration.objects.get().timing, TIMING)
        ready = narration_presentation(self.model)
        self.assertTrue(ready["ready"])
        self.assertFalse(ready["on_demand"])
        self.assertEqual(json.loads(ready["timing"]), TIMING)

    def test_failed_generation_can_be_retried_by_clicking_again(self):
        with patch("study.french_audio.synthesize", side_effect=NarrationError("Provider failed.")):
            self.assertEqual(self.prepare().status_code, 409)
        with patch("study.french_audio.synthesize", return_value=(AUDIO, TIMING)) as provider:
            self.assertEqual(self.prepare().status_code, 200)
        provider.assert_called_once()
        self.assertTrue(EO3Narration.objects.filter(pk=self.spec.fingerprint).exists())

    def edit(self, user, introduction):
        response = Response.objects.filter(semantic_group=self.group).first()
        PersonalResponse.objects.update_or_create(
            user=user, response=response, defaults={
                "position_claire": introduction,
                "arguments": [{
                    "order": 1, "idea": "Mon idée privée.", "developpement": "Ma raison.",
                    "exemple": "", "consequence": "Ma conséquence.",
                }],
                "nuance": "Ma nuance.", "conclusion": "Ma conclusion.",
            },
        )
        response = Response.objects.filter(semantic_group=self.group).first()
        return response, narration_presentation(
            self.model, effective_response(response, user), user.pk,
        )

    def test_an_edited_response_gets_its_own_private_recording(self):
        response, presentation = self.edit(self.user, "Mon introduction privée.")
        self.assertTrue(presentation["on_demand"])
        self.assertNotEqual(presentation["prepare_url"], self.url)
        fingerprint = presentation["prepare_url"].rstrip("/").rsplit("/", 2)[-2]
        self.assertNotEqual(fingerprint, self.spec.fingerprint)
        prompt = Prompt.objects.filter(response=response, is_active=True).first()
        page = self.client.get(prompt_detail_url(prompt))
        self.assertContains(page, presentation["prepare_url"])
        self.assertNotContains(page, self.url)

        with patch("study.french_audio.synthesize", return_value=(AUDIO, TIMING)) as provider:
            prepared = self.client.post(
                presentation["prepare_url"], data=json.dumps({"confirm_cost": True, "pin": AUDIO_PIN}),
                content_type="application/json",
            )
        self.assertEqual(prepared.status_code, 200, prepared.content)
        self.assertIn("data-eo3-audio", prepared.json()["html"])
        spec = provider.call_args.args[0]
        self.assertEqual(spec.fingerprint, fingerprint)
        self.assertEqual(spec.text, "\n\n".join((
            self.model.source_prompts[0][1], "Mon introduction privée.",
            "Mon idée privée. Ma raison. Ma conséquence.", "Ma nuance.", "Ma conclusion.",
        )))
        self.assertEqual(FrenchNarration.objects.get(pk=fingerprint).owner, self.user)
        self.assertFalse(EO3Narration.objects.filter(pk=self.spec.fingerprint).exists())

        ready = self.edit(self.user, "Mon introduction privée.")[1]
        self.assertTrue(ready["ready"])
        self.assertEqual(self.client.get(ready["url"]).content, AUDIO)
        stranger = factories.make_user("eavesdropper")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(ready["url"]).status_code, 404)
        self.edit(stranger, "Mon introduction privée.")
        self.assertEqual(self.client.get(ready["url"]).status_code, 404)

    def test_a_new_edit_frees_the_previous_private_recording(self):
        first = self.edit(self.user, "Première version.")[1]
        with patch("study.french_audio.synthesize", return_value=(AUDIO, TIMING)):
            self.client.post(first["prepare_url"], data=json.dumps({"confirm_cost": True, "pin": AUDIO_PIN}),
                             content_type="application/json")
            second = self.edit(self.user, "Deuxième version.")[1]
            self.assertFalse(second["ready"])
            self.assertEqual(self.client.post(
                first["prepare_url"], data=json.dumps({"confirm_cost": True, "pin": AUDIO_PIN}),
                content_type="application/json",
            ).status_code, 409)
            self.client.post(second["prepare_url"], data=json.dumps({"confirm_cost": True, "pin": AUDIO_PIN}),
                             content_type="application/json")
        self.assertEqual(EO3Narration.objects.count(), 1)
        self.assertTrue(self.edit(self.user, "Deuxième version.")[1]["ready"])
        old = first["prepare_url"].rstrip("/").rsplit("/", 2)[-2]
        self.assertEqual(FrenchNarration.objects.get(pk=old).status, "superseded")

    def test_disabled_generation_keeps_edited_responses_closed(self):
        presentation = self.edit(self.user, "Mon introduction privée.")[1]
        with self.settings(FRENCH_AUDIO_GENERATION_ENABLED=False):
            closed = self.edit(self.user, "Mon introduction privée.")[1]
            self.assertEqual(closed["prepare_url"], "")
            self.assertEqual(self.client.post(
                presentation["prepare_url"], data=json.dumps({"confirm_cost": True, "pin": AUDIO_PIN}),
                content_type="application/json",
            ).status_code, 404)

    def test_disabled_generation_keeps_non_sample_responses_closed(self):
        with self.settings(FRENCH_AUDIO_GENERATION_ENABLED=False):
            self.assertEqual(self.prepare().status_code, 404)
