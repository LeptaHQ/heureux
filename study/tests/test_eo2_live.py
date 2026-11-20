import json
from datetime import datetime, timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from study.catalogue import registry as catalogue
from study.catalogue.loader import tache_two_subject_content_key
from study.expression.eo.tache_2 import gemini_live
from study.models import LoginThrottle, Prompt
from . import factories


PILOT_PIN = "test-audio-pin"


@override_settings(GEMINI_LIVE_API_KEY="test-pilot-key", GEMINI_LIVE_FREE_TIER_CONFIRMED=True, ELEVENLABS_PIN=PILOT_PIN)
class GeminiLiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.task = factories.make_task(factories.make_part("eo"), "tache-2")
        cls.reviewer = factories.make_user("fictional-reviewer")
        cls.other = factories.make_user("other-reviewer")

    def setUp(self):
        # Patch the TLS boundary, not the mint logic. Even an unexpected mint
        # must not reach the network.
        self.transport = self.enterContext(patch.object(gemini_live, "HTTPSConnection", autospec=True))
        self.connection = self.transport.return_value
        self.upstream = self.connection.getresponse.return_value.__enter__.return_value
        self.upstream.status = 200
        self.upstream.read.return_value = b'{"name":"auth_tokens/test.token","ignored":"provider-only"}'
        self.live = reverse("study:eo_tache_two_live")
        self.studio = reverse("study:eo_tache_two_interaction")
        self.token_url = reverse("study:eo_tache_two_live_token")
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.reviewer)

    def post(self, body=None, content_type="application/json", *, url=None, **extra):
        if settings.CSRF_COOKIE_NAME not in self.client.cookies:
            self.client.get(self.live)
        return self.client.post(
            url or self.token_url, body if body is not None else json.dumps({"consent": True, "pin": PILOT_PIN}), content_type=content_type,
            HTTP_X_CSRFTOKEN=self.client.cookies[settings.CSRF_COOKIE_NAME].value, **extra,
        )

    def assert_private(self, response, status):
        self.assertEqual(response.status_code, status)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("private", response["Cache-Control"])

    def assert_no_live_policy(self, response):
        self.assertEqual(response["Content-Security-Policy"], settings.CONTENT_SECURITY_POLICY)
        self.assertIn("microphone=()", response["Permissions-Policy"])

    def test_only_eligible_live_get_allows_google_wss_and_microphone(self):
        page = self.client.get(self.live)
        self.assert_private(page, 200)
        self.assertTemplateUsed(page, "study/expression/eo/tache_2/live.html")
        self.assertIs(page.context["gemini_live_available"], True)
        self.assertEqual((page.context["part"], page.context["task"]), (self.task.part, self.task))
        google_wss = "wss://generativelanguage.googleapis.com"
        policy = page["Content-Security-Policy"]
        self.assertIn(f"connect-src 'self' {google_wss}", policy.split("; "))
        self.assertEqual(policy.replace(" " + google_wss, ""), settings.CONTENT_SECURITY_POLICY)
        self.assertIn("microphone=(self)", page["Permissions-Policy"])
        self.assertIn("camera=()", page["Permissions-Policy"])
        self.assertNotContains(page, settings.GEMINI_LIVE_API_KEY)
        self.assertNotContains(page, PILOT_PIN)

        studio = self.client.get(self.studio)
        self.assertIs(studio.context["gemini_live_available"], True)
        self.assertEqual(studio["Content-Security-Policy"], settings.CONTENT_SECURITY_POLICY)
        self.assertIn("microphone=(self)", studio["Permissions-Policy"])
        self.transport.assert_not_called()

    def test_pilot_gates_apply_to_both_pages_and_direct_mint(self):
        for gate in (
            {"GEMINI_LIVE_API_KEY": "", "GEMINI_API_KEY": "not-a-fallback"},
            {"GEMINI_LIVE_FREE_TIER_CONFIRMED": False},
            {"ELEVENLABS_PIN": ""},
            {"ELEVENLABS_PIN": "x" * 129},
        ):
            with self.subTest(gate=next(iter(gate))), self.settings(**gate):
                page = self.client.get(self.live)
                self.assertIs(page.context["gemini_live_available"], False)
                self.assert_no_live_policy(page)
                self.assertIs(self.client.get(self.studio).context["gemini_live_available"], False)
                self.assert_private(self.post(), 403)
        self.task.available = False
        self.task.save(update_fields=["available"])
        self.assertIs(self.client.get(self.live).context["gemini_live_available"], False)
        self.assert_private(self.post(), 403)
        self.assertFalse(LoginThrottle.objects.exists())
        self.transport.assert_not_called()

    def test_auth_csrf_and_method_failures_never_mint_or_open_csp(self):
        for response, status in (
            (self.client.post(self.token_url, {"consent": True}, content_type="application/json"), 403),
            (self.post(HTTP_ORIGIN="https://other.invalid"), 403),
            (self.client.get(self.token_url), 405),
            (self.client.post(self.live, HTTP_X_CSRFTOKEN=self.client.cookies[settings.CSRF_COOKIE_NAME].value), 405),
        ):
            self.assert_private(response, status)
            self.assert_no_live_policy(response)
        self.client.logout()
        for response, status in (
            (self.client.get(self.live), 302),
            (self.client.post(self.token_url, {"consent": True}, content_type="application/json"), 401),
        ):
            self.assert_private(response, status)
            self.assert_no_live_policy(response)
        self.transport.assert_not_called()

    def test_mint_accepts_only_explicit_json_consent(self):
        for body in (
            " ", "{", "{}", "[]", "true", '[["consent",true]]', '{"consent":false}', '{"consent":1}',
            '{"consent":"true"}', '{"consent":false,"consent":true}', '{"consent":true,"text":"bonjour"}',
            '{"consent":false,"pin":"test-audio-pin"}', '{"consent":true,"pin":7}',
            '{"consent":true,"pin":"one","pin":"two"}', '{"consent":true,"pin":"\\ud800"}',
            '{"consent":true}' + " " * 2048,
        ):
            with self.subTest(body=body):
                self.assert_private(self.post(body), 400)
        self.assert_private(self.post("consent=true", "application/x-www-form-urlencoded"), 415)
        self.assertFalse(LoginThrottle.objects.exists())
        self.transport.assert_not_called()

    def test_mint_uses_locked_rest_setup_and_returns_only_token_and_model(self):
        before = timezone.now()
        response = self.post(HTTP_X_REQUEST_ID="never-forward-this")
        after = timezone.now()
        self.assert_private(response, 200)
        self.assert_no_live_policy(response)
        self.assertEqual(response.json(), {"token": "auth_tokens/test.token", "model": "models/gemini-3.8-live"})
        self.transport.assert_called_once_with("generativelanguage.googleapis.com", timeout=5)
        call = self.connection.request.call_args
        self.assertEqual(call.args, ("POST", "/v1beta/auth_tokens"))
        self.assertEqual(call.kwargs["headers"], {
            "Content-Type": "application/json", "x-goog-api-key": "test-pilot-key",
        })
        payload = json.loads(call.kwargs["body"])
        # No fieldMask (whole setup locked), SDK wrappers, identity or learner input.
        self.assertEqual(set(payload), {"uses", "expireTime", "newSessionExpireTime", "bidiGenerateContentSetup"})
        self.assertEqual(payload["uses"], 1)
        for key, minutes in (("newSessionExpireTime", 1), ("expireTime", 6)):
            expiry = datetime.fromisoformat(payload[key])
            self.assertLessEqual(before + timedelta(minutes=minutes), expiry)
            self.assertLessEqual(expiry, after + timedelta(minutes=minutes))
        setup = payload["bidiGenerateContentSetup"]
        instruction = setup.pop("systemInstruction")["parts"][0]["text"]
        self.assertEqual(setup, {
            "model": "models/gemini-3.8-live", "generationConfig": {"responseModalities": ["AUDIO"]},
            "inputAudioTranscription": {}, "outputAudioTranscription": {},
        })
        for fact in (
            "samedi de 10 h à 11 h 30", "mercredi de 18 h à 20 h", "téléphone ou un appareil",
            "aucun prêt au parc", "sans supplément sur réservation", "ni note",
        ):
            self.assertIn(fact, " ".join(instruction.split()))
        self.assertNotIn(self.reviewer.username.encode(), call.kwargs["body"])
        self.assertNotIn(PILOT_PIN, repr(call))
        self.connection.close.assert_called_once()
        denied = self.post('{"consent":true}')
        self.assert_private(denied, 403)
        self.assertEqual(denied.json()["error"], "pin_required")
        self.transport.assert_called_once()

    def test_incorrect_shared_pin_is_throttled_before_any_provider_request(self):
        for _ in range(5):
            response = self.post('{"consent":true,"pin":"incorrect"}')
            self.assert_private(response, 403)
            self.assertEqual(response.json()["error"], "pin_invalid")
        locked = self.post()
        self.assert_private(locked, 429)
        self.assertEqual(locked.json()["error"], "pin_locked")
        self.transport.assert_not_called()

    def test_selected_publication_supplies_the_situation_register_and_grounded_replies(self):
        theme = factories.make_theme("subject-live", task=self.task)
        for args in (("mai", 2, 8), ("octobre", 5, 21), ("janvier", 1, 5)):
            with self.subTest(args=args):
                key = tache_two_subject_content_key(*args)
                response = factories.make_response(theme=theme)
                Prompt.objects.filter(response=response).update(content_key=key, text="DB-only sentinel")
                live_url = reverse("study:eo_tache_two_live", args=args)
                token_url = reverse("study:eo_tache_two_live_token", args=args)
                page = self.client.get(live_url, {"deduplicate": "0"})
                self.assert_private(page, 200)
                self.assertEqual(page.context["token_url"], token_url)
                self.assertEqual(page.context["subject_url"],
                                 reverse("study:task_subject_detail", args=("eo", "tache-2", *args)) + "?deduplicate=0")
                dialogue = catalogue.tache_two_dialogues()[key]
                self.assertNotContains(page, dialogue.questions[0].answer)
                self.assertEqual(self.post(url=token_url, body='{"consent":true}').json()["error"], "pin_required")
                self.assert_private(self.post(url=token_url), 200)
                payload = json.loads(self.connection.request.call_args.kwargs["body"])
                instruction = payload["bidiGenerateContentSetup"]["systemInstruction"]["parts"][0]["text"]
                self.assertNotIn("DB-only sentinel", instruction)
                self.assertNotIn("parc des Saules", instruction)
                self.assertIn(page.context["subject"].prompt, instruction)
                self.assertIn(dialogue.questions[0].answer, instruction)
                self.assertIn(f'"registre": "{dialogue.register}"', instruction)

    def test_missing_or_unpublished_subject_never_uses_default_workshop(self):
        args = ("mai", 2, 8)
        live_url = reverse("study:eo_tache_two_live", args=args)
        token_url = reverse("study:eo_tache_two_live_token", args=args)
        response = factories.make_response(theme=factories.make_theme("subject-live", task=self.task))
        Prompt.objects.filter(response=response).update(content_key=tache_two_subject_content_key(*args), is_active=False)
        self.assertEqual(self.client.get(live_url).status_code, 404)
        self.assertEqual(self.post(url=token_url).status_code, 404)
        self.assertEqual(self.post(url=reverse("study:eo_tache_two_live_token", args=("mai", 2, 999))).status_code, 404)
        self.transport.assert_not_called()

    def test_per_account_limit_counts_provider_failures_before_mint(self):
        self.upstream.status = 429  # Provider quota: never switch to a paid service.
        self.assert_private(self.post(), 503)
        self.upstream.status = 200
        for _ in range(4):
            self.assert_private(self.post(), 200)
        self.assert_private(self.post(REMOTE_ADDR="192.0.2.1"), 429)
        self.assertEqual(self.transport.call_count, 5)
        self.client.force_login(self.other)
        self.assert_private(self.post(), 200)

    def test_upstream_errors_are_bounded_and_do_not_disclose_secrets(self):
        for status, body, error in (
            (307, b"private-location", None),
            (403, b"private-provider-message", None),
            (200, b'{"name":"unexpected/provider-secret"}', None),
            (200, b"x" * 17_000, None),
            (200, None, TimeoutError("private-provider-error")),
        ):
            with self.subTest(status=status, error=error):
                self.upstream.status = status
                self.upstream.read.return_value = body
                self.connection.getresponse.side_effect = error
                response = self.post()
                self.assert_private(response, 503)
                self.assert_no_live_policy(response)
                self.assertEqual(response.json(), {"error": "Le service vocal est indisponible pour le moment."})
        # Exactly once per valid request, with no redirects or retries.
        self.assertEqual(self.transport.call_count, 5)
        self.assertEqual(self.upstream.read.call_count, 2)
