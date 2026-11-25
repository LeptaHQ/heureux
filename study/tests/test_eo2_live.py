import json
import socket
import threading
import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from study.catalogue import registry as catalogue
from study.catalogue.loader import tache_two_subject_content_key
from study.simulation import evaluation, live_conversation, oral_evaluation
from study.models import EO2PracticeAttempt, EO2TopicStatus, LiveSimulation, LoginThrottle, Prompt
from study.views import eo2_live
from . import factories


PILOT_PIN = "test-audio-pin"


@override_settings(GEMINI_API_KEY="test-pilot-key", GROQ_API_KEY="test-groq-key", AI_PIN=PILOT_PIN)
class GeminiLiveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.task = factories.make_task(factories.make_part("eo"), "tache-2")
        cls.reviewer = factories.make_user("fictional-reviewer")
        cls.other = factories.make_user("other-reviewer")

    def setUp(self):
        # Patch the TLS boundary, not the mint logic. Even an unexpected mint
        # must not reach the network.
        self.transport = self.enterContext(patch.object(live_conversation, "HTTPSConnection", autospec=True))
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
        self.assertTemplateUsed(page, "study/simulation/oral_session.html")
        self.assertIs(page.context["gemini_live_available"], True)
        self.assertEqual((page.context["part"], page.context["task"]), (self.task.part, self.task))
        google_wss = "wss://generativelanguage.googleapis.com"
        policy = page["Content-Security-Policy"]
        self.assertIn(f"connect-src 'self' {google_wss}", policy.split("; "))
        self.assertEqual(policy.replace(" " + google_wss, ""), settings.CONTENT_SECURITY_POLICY)
        self.assertIn("microphone=(self)", page["Permissions-Policy"])
        self.assertIn("camera=()", page["Permissions-Policy"])
        self.assertNotContains(page, settings.GEMINI_API_KEY)
        self.assertNotContains(page, PILOT_PIN)

        studio = self.client.get(self.studio)
        self.assertRedirects(studio, self.live, fetch_redirect_response=False)
        self.assert_no_live_policy(studio)
        self.transport.assert_not_called()

    def test_unavailable_simulation_has_no_fallback_or_microphone_access(self):
        for gate in (
            {"GEMINI_API_KEY": ""},
            {"AI_PIN": ""},
            {"AI_PIN": "x" * 129},
        ):
            with self.subTest(gate=next(iter(gate))), self.settings(**gate):
                page = self.client.get(self.live)
                self.assertIs(page.context["gemini_live_available"], False)
                self.assert_no_live_policy(page)
                self.assertContains(page, "La simulation est indisponible")
                self.assertNotContains(page, 'id="lv-start"')
                self.assertNotContains(page, f'href="{self.studio}"')
                self.assertNotContains(page, "Gemini")
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
        self.assertIn(live_conversation._TURN_RULE, instruction)
        self.assertEqual(setup, {
            "model": "models/gemini-3.8-live", "generationConfig": {"responseModalities": ["AUDIO"]},
            "inputAudioTranscription": {"languageCodes": ["fr-FR"]}, "outputAudioTranscription": {},
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
                self.assertIn(live_conversation._TURN_RULE, instruction)
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

    def test_heureux_sets_no_per_account_limit_on_mints(self):
        self.upstream.status = 429  # Provider quota: never switch to a paid service.
        self.assert_private(self.post(), 503)
        self.upstream.status = 200
        for _ in range(6):
            self.assert_private(self.post(), 200)
        self.assertEqual(self.transport.call_count, 7)

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

    def test_reading_token_only_receives_the_selected_public_consigne(self):
        args = ("mai", 2, 8)
        key = tache_two_subject_content_key(*args)
        entry = factories.make_response(theme=factories.make_theme("speaker", task=self.task))
        Prompt.objects.filter(response=entry).update(content_key=key)
        page = self.client.get(reverse("study:eo_tache_two_live", args=args))
        self.assert_private(self.post(url=page.context["token_url"], body=json.dumps({
            "consent": True, "purpose": "read_prompt", "pin": PILOT_PIN,
        })), 200)
        payload = json.loads(self.connection.request.call_args.kwargs["body"])
        instruction = payload["bidiGenerateContentSetup"]["systemInstruction"]["parts"][0]["text"]
        self.assertIn(page.context["subject"].prompt, instruction)
        self.assertNotIn(catalogue.tache_two_dialogues()[key].questions[0].answer, instruction)

    def test_one_pin_authorizes_the_exact_reading_then_one_fresh_exchange_and_opt_in_review(self):
        args = ("mai", 2, 8)
        key = tache_two_subject_content_key(*args)
        entry = factories.make_response(theme=factories.make_theme("studio-attempt", task=self.task))
        Prompt.objects.filter(response=entry).update(content_key=key)
        page = self.client.get(reverse("study:eo_tache_two_live", args=args))
        url = page.context["token_url"]
        response = self.post(url=url, body=json.dumps({"purpose": "attempt", "pin": PILOT_PIN, "consent": True}))
        self.assert_private(response, 200)
        result = response.json()
        self.assertEqual(set(result), {"token", "model", "exchangeGrant"})
        self.transport.assert_called_once()  # No speaking token while the subject is read.
        def instruction():
            return json.loads(self.connection.request.call_args.kwargs["body"])["bidiGenerateContentSetup"]["systemInstruction"]["parts"][0]["text"]
        answer = catalogue.tache_two_dialogues()[key].questions[0].answer
        self.assertIn(page.context["scenario_prompt"], instruction())
        self.assertNotIn(answer, instruction())

        exchange = {"purpose": "exchange", "exchangeGrant": result["exchangeGrant"], "consent": True}
        self.assert_private(self.post(body=json.dumps(exchange)), 403)  # Not the generic workshop.
        self.assert_private(self.post(url=url, body=json.dumps({**exchange, "pin": PILOT_PIN})), 400)
        with self.settings(GEMINI_API_KEY=""):
            self.assert_private(self.post(url=url, body=json.dumps(exchange)), 403)
        with patch("django.core.signing.time.time", return_value=timezone.now().timestamp() + 601):
            self.assert_private(self.post(url=url, body=json.dumps(exchange)), 403)
        response = self.post(url=url, body=json.dumps(exchange))
        self.assert_private(response, 200)
        self.assertIn(answer, instruction())
        self.assertNotIn(exchange["exchangeGrant"], repr(self.connection.request.call_args))
        self.assert_private(self.post(url=url, body=json.dumps(exchange)), 403)  # Already redeemed.
        self.assertEqual(self.transport.call_count, 2)

        transport = self.evaluation_fixture()
        review = {"consent": True, "rows": self.rows, "reviewGrant": response.json()["reviewGrant"]}
        review_url = page.context["evaluation_url"]
        self.assert_private(self.post(url=self.eval_url, body=json.dumps(review)), 403)
        self.assert_private(self.post(url=review_url, body=json.dumps({**review, "consent": False})), 400)
        self.assert_private(self.post(url=review_url, body=json.dumps({**review, "reviewGrant": exchange["exchangeGrant"]})), 403)
        with patch("django.core.signing.time.time", return_value=timezone.now().timestamp() + 3601):
            self.assert_private(self.post(url=review_url, body=json.dumps(review)), 403)
        transport.assert_not_called()
        self.complete()
        self.assert_private(self.post(url=review_url, body=json.dumps(review)), 200)
        self.assertNotIn(review["reviewGrant"], repr(self.eval_connection.request.call_args))
        self.client.logout()
        self.client.force_login(self.reviewer)
        self.assert_private(self.post(url=review_url, body=json.dumps(review)), 403)
        transport.assert_called_once()

    def evaluation_fixture(self):
        transport = self.enterContext(patch.object(evaluation, "HTTPSConnection", autospec=True))
        self.eval_connection = transport.return_value
        self.eval_connection.sock = Mock()
        self.eval_response = self.eval_connection.getresponse.return_value.__enter__.return_value
        self.eval_response.status = 200
        self.eval_response.getheader.return_value = None
        self.eval_url = reverse("study:eo_tache_two_live_evaluation")
        self.rows = [
            {"speaker": "user", "text": "Bonjour, combien coûte le prêt ?"},
            {"speaker": "model", "text": "Cinq dollars."},
            {"speaker": "user", "text": "📷 Et si je veux prend deux appareils ?"},
        ]
        self.report = {"criteria": {
                           "task": {"points": 4, "evidenceId": "E1", "why": "La demande de prix est claire."},
                           "coherence": {"points": 3, "evidenceId": "E2", "why": "La relance précise la quantité."},
                           "lexicon": {"points": 3, "evidenceId": "E2", "why": "Le terme « appareils » est précis."},
                           "grammar": {"points": 2, "evidenceId": "E2", "why": "Le second verbe doit rester à l’infinitif."}},
                       "reason": "Vous adaptez votre demande au tarif annoncé.",
                       "strengths": [{"evidenceId": "E1", "why": "Le prix est ciblé."},
                                     {"evidenceId": "E2", "why": "Vous explorez une autre possibilité."}],
                       "corrections": [{"turnIndex": 2, "before": "veux prend", "after": "veux prendre",
                                        "why": "Après vouloir, le deuxième verbe reste à l’infinitif."}],
                       "proposal": [{"turnIndex": 0, "text": "Bonjour, combien coûte le prêt d’un appareil photo ?"},
                                    {"turnIndex": 2, "text": "Et si je veux prendre deux appareils, le tarif change-t-il ?"}],
                       "next": "Précisez la durée du prêt : « Et si je les garde deux jours ? »"}
        return transport

    def complete(self, content=None, finish="stop", **message):
        self.eval_response.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps(self.report) if content is None else content, **message},
                         "finish_reason": finish}],
            "usage": {"prompt_tokens": 3900, "completion_tokens": 1200},
        }).encode()

    def evaluate(self, *, url=None, **changes):
        self.complete()
        return self.post(url=url or self.eval_url, body=json.dumps({
            "consent": True, "pin": PILOT_PIN, "rows": self.rows, **changes,
        }))

    def ground(self, rows=None, *, monologue=False):
        rows = self.rows if rows is None else rows
        return oral_evaluation._ground(self.report, rows, oral_evaluation._evidence_rows(rows)[1], monologue=monologue)

    def test_review_uses_only_exact_publication_and_reviewed_text_and_maps_score(self):
        self.evaluation_fixture()
        args = ("mai", 2, 8)
        key = tache_two_subject_content_key(*args)
        entry = factories.make_response(theme=factories.make_theme("speaker", task=self.task))
        Prompt.objects.filter(response=entry).update(content_key=key)
        page = self.client.get(reverse("study:eo_tache_two_live", args=args))
        url = page.context["evaluation_url"]
        response = self.evaluate(url=url)
        self.assert_private(response, 200)
        self.assert_no_live_policy(response)
        report = response.json()
        self.assertEqual((report["score"], report["cefr"], report["nclc"]), (12, "B2", "8"))
        self.assertEqual([item["score"] for item in report["criteria"]], [4, 3, 3, 2])
        first, last = self.rows[0]["text"], self.rows[2]["text"]
        self.assertEqual([item["quote"] for item in report["evidence"]], [first, last])
        self.assertEqual([(row["turnIndex"], row["quote"]) for row in report["criteria"]],
                         [(0, first), (2, last), (2, last), (2, last)])
        self.assertEqual(report["proposal"], [line["text"] for line in self.report["proposal"]])
        mark, = report["annotations"]
        encoded = self.rows[mark["turnIndex"]]["text"].encode("utf-16-le")
        self.assertEqual(encoded[2*mark["start"]:2*mark["end"]].decode("utf-16-le"), "veux prend")
        call = self.eval_connection.request.call_args
        self.assertEqual(call.args, ("POST", "/openai/v1/chat/completions"))
        payload = json.loads(call.kwargs["body"])
        self.assertEqual(payload["model"], "openai/gpt-oss-120b")
        fmt = payload["response_format"]["json_schema"]
        self.assertTrue(fmt["strict"])
        self.assertEqual(set(fmt["schema"]["properties"]["criteria"]["required"]), set(self.report["criteria"]))
        schema = json.dumps(fmt["schema"])
        self.assertEqual(schema.count('"type": "object"'), schema.count('"additionalProperties": false'))  # Strict mode.
        system, user = payload["messages"]
        self.assertEqual(system["role"], "system")
        self.assertEqual(json.loads(user["content"]), {"consigne": page.context["subject"].prompt, "rows": [
            {"turnIndex": 0, "speaker": "user", "passages": [{"id": "E1", "text": first}]},
            {"turnIndex": 1, **self.rows[1]},
            {"turnIndex": 2, "speaker": "user", "passages": [{"id": "E2", "text": last}]},
        ]})
        self.assertNotIn(PILOT_PIN, repr(call))
        self.assertNotIn(self.reviewer.username, repr(call))
        self.assertNotIn(catalogue.tache_two_dialogues()[key].questions[0].answer, json.dumps(payload, ensure_ascii=False))
        Prompt.objects.filter(response=entry).update(is_active=False)
        self.assertEqual(self.evaluate(url=url).status_code, 404)
        self.eval_connection.request.assert_called_once()

    def test_review_gates_invalid_input_quota_and_auth(self):
        transport = self.evaluation_fixture()
        for changes in ({"consent": False}, {"notes": "private"}, {"rows": [self.rows[1]]},
                        {"rows": [{**self.rows[0], "original": "misheard"}]}, {"rows": self.rows * 100}):
            self.assert_private(self.evaluate(**changes), 400)
        self.assert_private(self.post(url=self.eval_url, body=" " * (oral_evaluation.MAX_BODY + 1)), 400)
        self.assert_private(self.evaluate(pin=""), 403)
        self.assert_private(self.client.post(self.eval_url, {"consent": True}, content_type="application/json"), 403)
        for key in ("GEMINI_API_KEY", "GROQ_API_KEY"):
            with self.settings(**{key: ""}):
                self.assert_private(self.evaluate(), 403)
        transport.assert_not_called()
        self.eval_response.status = 429
        for _ in range(5):
            self.assert_private(self.evaluate(), 429)  # Groq's quota, passed on; Heureux adds none.
        self.eval_response.getheader.return_value = "7"
        self.assertIn("Réessayez dans 7 s.", self.evaluate().json()["error"])
        self.eval_response.status = 200
        self.assert_private(self.evaluate(), 200)
        self.assertEqual(transport.call_count, 7)
        self.client.logout()
        self.assert_private(self.client.post(self.eval_url, content_type="application/json"), 401)

    def test_scored_transcript_uses_speaking_conversions_not_independent_model_levels(self):
        self.evaluation_fixture()
        for score, cefr, nclc in (
            (0, "A1 non atteint", "< 4"), (1, "A1", "< 4"), (2, "A2", "< 4"), (4, "A2", "4"),
            (6, "B1", "5"), (7, "B1", "6"), (10, "B2", "7"), (12, "B2", "8"),
            (14, "C1", "9"), (16, "C1", "10+"), (18, "C2", "10+"), (20, "C2", "10+"),
        ):
            with self.subTest(score=score):
                for i, row in enumerate(self.report["criteria"].values()):
                    row["points"] = score // 4 + (i < score % 4)
                result = self.ground()
                self.assertEqual((result["cefr"], result["nclc"]), (cefr, nclc))

    def test_unverifiable_detail_does_not_destroy_a_supported_score(self):
        self.evaluation_fixture()
        self.report["strengths"][0]["evidenceId"] = "Cinq dollars."  # Partner text is not an evidence ID.
        self.rows[-1]["text"] += " veux prend"
        self.report["corrections"].append({"turnIndex": 0, "before": "inventé", "after": "mot", "why": "Correction."})
        report = self.evaluate().json()
        self.assertEqual((report["score"], report["omitted"], report["annotations"]), (12, True, []))
        self.assertEqual([item["quote"] for item in report["evidence"]], [self.rows[-1]["text"].removesuffix(" veux prend")])
        self.eval_connection.request.assert_called_once()

    def test_only_issued_learner_passages_support_a_mark(self):
        self.evaluation_fixture()
        criterion = self.report["criteria"]["lexicon"]
        for ref in ("E0", "E3", "deux appareils", "Cinq dollars.", 1, False, None, ["E1"]):
            with self.subTest(ref=ref):
                criterion.update(evidenceId=ref)
                self.report["strengths"] = [dict(criterion)]
                result = self.ground()
                self.assertEqual((result["scoreStatus"], result["score"], result["evidence"]), ("incomplete", None, []))
                self.assertEqual([row["score"] for row in result["criteria"]], [4, 3, None, 2])
                self.assertNotIn("quote", result["criteria"][2])

        # A point fort is not one of the four marks, so it cannot supply missing EO2 coverage.
        for item in self.report["criteria"].values():
            item.update(evidenceId="E2")
        self.report["strengths"] = [{"evidenceId": "E1", "why": "Vous saluez."}]
        result = self.ground()
        self.assertTrue(result["evidence"])
        self.assertEqual((result["scoreStatus"], result["score"]), ("incomplete", None))

    def test_opinion_quotes_preserve_original_french_without_repeating_the_monologue(self):
        self.evaluation_fixture()
        original = "Je trouve que l’ide\u0301e\u00a0de marcher est bonne."
        rows = [{"speaker": "user", "text": f"{original} On peut regarder les bâtiments et discuter avec les habitants."}]
        for item in (*self.report["criteria"].values(), *self.report["strengths"]):
            item.update(evidenceId="E1")
        self.report.update(proposal="", corrections=[])
        result = self.ground(rows, monologue=True)
        self.assertEqual(result["score"], 12)
        for item in result["evidence"] + result["criteria"]:
            self.assertEqual(item["quote"], original)
        self.report["strengths"][0]["evidenceId"] = "l'idée de marcher"
        result = self.ground(rows, monologue=True)
        self.assertEqual((result["omitted"], result["score"], len(result["evidence"])), (True, 12, 1))

    def test_passages_preserve_uncitable_text_and_never_split_a_word_to_make_evidence(self):
        long_word = "x" * 161
        rows = [{"speaker": "user", "text": f"   {long_word}   euh, à quelle heure ?"},
                {"speaker": "model", "text": "E1 : à midi."},
                {"speaker": "user", "text": "???"},
                {"speaker": "user", "text": "Et si je ne peux passer qu’après midi ?"}]
        sent, evidence = oral_evaluation._evidence_rows(rows)
        self.assertEqual(sent[0]["passages"][0], {"id": None, "text": long_word})
        self.assertEqual(sent[1], {"turnIndex": 1, **rows[1]})
        self.assertEqual(sent[2]["passages"], [{"id": None, "text": "???"}])
        self.assertEqual(list(evidence.values()), [{"turnIndex": 0, "quote": "euh, à quelle heure ?"},
                                                   {"turnIndex": 3, "quote": rows[3]["text"]}])

    def test_partner_fluency_does_not_turn_acknowledgements_into_a_score(self):
        self.evaluation_fixture()
        for row, text in zip(self.rows, ("Bonjour !", "Nous proposons plusieurs tarifs selon la durée de votre séjour.", "Euh, oui, merci.")):
            row["text"] = text
        result = self.evaluate().json()
        self.assertEqual((result["scoreStatus"], result["score"]), ("insufficient", None))
        self.assertTrue(all(row["score"] is None for row in result["criteria"]))

    def test_corrections_ignore_apostrophe_style_case_punctuation_and_fillers(self):
        self.evaluation_fixture()
        self.rows[0]["text"] = "Bonjour, euh je voudrais savoir qu'est-ce que le prêt comprend."
        self.report["corrections"][:0] = [
            {"turnIndex": 0, "before": "Savoir qu’est-ce que", "after": "savoir ce que",
             "why": "Dans une question indirecte, « ce que » remplace « qu’est-ce que »."},
            {"turnIndex": 0, "before": "euh je", "after": "je", "why": "Hésitation."},
            {"turnIndex": 0, "before": "bonjour,", "after": "Bonjour !", "why": "Ponctuation."},
        ]
        result = self.ground()
        self.assertTrue(result["omitted"])
        self.assertEqual([(mark["turnIndex"], mark["before"], mark["after"]) for mark in result["annotations"]],
                         [(0, "savoir qu'est-ce que", "savoir ce que"), (2, "veux prend", "veux prendre")])
        mark = result["annotations"][0]
        self.assertEqual(self.rows[0]["text"][mark["start"]:mark["end"]], mark["before"])

    def test_corrections_require_one_whole_word_span_in_the_cited_turn(self):
        self.evaluation_fixture()
        self.rows[0]["text"] = "Je veux comprendre. C’est réserve\u0301, ou c'est libre ?"
        self.rows[2]["text"] = "📷 Je veux comprendre. Et si je veux prend le train ?"
        self.report["corrections"] = [
            {"turnIndex": 0, "before": "prend", "after": "prendre", "why": "Infinitif."},
            {"turnIndex": 0, "before": "c'est", "after": "c’était", "why": "Temps."},
            {"turnIndex": 0, "before": "réserve", "after": "réserver", "why": "Infinitif."},
            {"turnIndex": 2, "before": "prend", "after": "prendre", "why": "Infinitif après vouloir."},
        ]
        result = self.ground()
        self.assertTrue(result["omitted"])
        mark, = result["annotations"]
        self.assertEqual((mark["turnIndex"], mark["before"], mark["after"]), (2, "prend", "prendre"))
        original = self.rows[2]["text"].encode("utf-16-le")
        self.assertEqual(original[:2 * mark["start"]].decode("utf-16-le"), "📷 Je veux comprendre. Et si je veux ")
        self.assertEqual(original[2 * mark["start"]:2 * mark["end"]].decode("utf-16-le"), "prend")

    def test_malformed_proposal_is_dropped_without_losing_the_score(self):
        self.evaluation_fixture()
        first, last = self.report["proposal"]
        for proposal in (None, "Bonjour.", [first, {**last, "text": " "}], [first, {**last, "text": "x" * 401}],
                         [3], [last, first], [first, first], [first], [{**first, "turnIndex": False}, last]):
            with self.subTest(proposal=proposal):
                self.report["proposal"] = proposal
                result = self.ground()
                self.assertEqual((result["score"], result["omitted"], result["proposal"]), (12, True, []))

    def test_proposal_keeps_a_personal_answer_on_the_learners_turn(self):
        self.evaluation_fixture()
        self.rows = [
            {"speaker": "user", "text": "Vous avez déjà visité Nantes ?"},
            {"speaker": "model", "text": "Pas encore. Et vous, qu’avez-vous fait là-bas ?"},
            {"speaker": "user", "text": "Moi, j’ai visité mon frère à Nantes."},
            {"speaker": "model", "text": "Ça a dû lui faire plaisir !"},
        ]
        first, answer = self.report["proposal"]
        first["text"], answer["text"] = "Avez-vous déjà visité Nantes ?", "J’ai rendu visite à mon frère à Nantes."
        result = self.evaluate().json()
        self.assertEqual(result["proposal"], [first["text"], answer["text"]])
        system, conversation = json.loads(self.eval_connection.request.call_args.kwargs["body"])["messages"]
        self.assertIn("une réponse personnelle reste une réponse", system["content"])
        self.assertEqual(json.loads(conversation["content"])["rows"][2]["passages"],
                         [{"id": "E2", "text": self.rows[2]["text"]}])

        self.report["proposal"][1] = {"turnIndex": 1, "text": "Qu’avez-vous fait à Nantes ?"}
        result = self.evaluate().json()
        self.assertEqual((result["score"], result["proposal"], result["omitted"]), (12, [], True))

    def test_overlong_lists_keep_their_first_items_and_the_schema_has_no_bounds(self):
        self.evaluation_fixture()
        self.rows.extend([{"speaker": "user", "text": f"Réplique {n}."} for n in range(15)])
        self.report["proposal"] = [dict(turnIndex=i, text=row["text"]) for i, row in enumerate(self.rows)
                                   if row["speaker"] == "user"]
        self.report["strengths"] *= 2
        report = self.evaluate().json()
        self.assertEqual((report["score"], report["omitted"], len(report["evidence"])), (12, True, 3))
        self.assertEqual(report["proposal"], [line["text"] for line in self.report["proposal"][:16]])
        payload = json.loads(self.eval_connection.request.call_args.kwargs["body"])
        schema = json.dumps(payload["response_format"])
        for bound in ("minItems", "maxItems", "minimum", "maximum"):
            self.assertNotIn(bound, schema)  # Strict decoding would compile every bound into its grammar.

    def test_transient_provider_failure_retries_once_and_errors_name_the_provider_code(self):
        self.evaluation_fixture()
        sleep = self.enterContext(patch.object(evaluation.time, "sleep"))
        body = json.dumps({"rows": self.rows, "pin": PILOT_PIN, "consent": True})
        self.complete()
        unavailable = b'{"error":{"message":"The model is overloaded.","type":"internal_server_error"}}'
        replies = iter([(503, unavailable), (200, self.eval_response.read.return_value)])

        def reply(*args, **kwargs):
            self.eval_response.status, self.eval_response.read.return_value = next(replies)
        self.eval_connection.request.side_effect = reply
        self.assertEqual(self.post(url=self.eval_url, body=body).json()["score"], 12)
        replies = iter([(503, unavailable)] * 2)
        with self.assertLogs(evaluation.logger, "WARNING") as logs:
            failed = self.post(url=self.eval_url, body=body)
        self.assert_private(failed, 502)
        self.assertIn("HTTP 503 internal_server_error", failed.json()["error"])
        self.assertIn("provider HTTP 503 internal_server_error", logs.output[0])
        self.assertNotIn("The model is overloaded.", "\n".join(logs.output))
        replies = iter([(400, b'{"error":{"message":"Invalid schema.","type":"invalid_request_error",'
                              b'"code":"json_validate_failed"}}')])
        rejected = self.post(url=self.eval_url, body=body)
        self.assert_private(rejected, 502)
        self.assertIn("HTTP 400 json_validate_failed", rejected.json()["error"])
        self.assertEqual((self.eval_connection.request.call_count, sleep.call_count), (5, 2))

    def test_saved_exchange_keeps_its_report_and_reopens_only_for_its_owner(self):
        self.evaluation_fixture()
        save_url = reverse("study:eo_tache_two_live_save")
        rows = [self.rows[0], {**self.rows[1], "interrupted": True}, self.rows[2]]
        for invalid in ({"rows": rows}, {"rows": rows, "elapsed": -1}, {"rows": rows, "elapsed": 1.5},
                        {"rows": [{**self.rows[0], "interrupted": False}], "elapsed": 1}, {"rows": [self.rows[1]], "elapsed": 1}):
            self.assert_private(self.post(url=save_url, body=json.dumps(invalid)), 400)
        with self.settings(GEMINI_API_KEY=""):
            self.assert_private(self.post(url=save_url, body=json.dumps({"rows": rows, "elapsed": 0})), 403)
        save_options = dict(url=save_url, body=json.dumps({"rows": rows, "elapsed": 95_000}),
                            HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        saved = self.post(**save_options)
        self.assert_private(saved, 201)
        self.assertEqual(self.post(**save_options).json(), saved.json())
        self.assertEqual(EO2PracticeAttempt.objects.filter(user=self.reviewer).count(), 1)
        simulation = LiveSimulation.objects.get(pk=saved.json()["id"])
        self.assertEqual((simulation.user, simulation.subject_key, simulation.rows, simulation.elapsed_ms, simulation.report),
                         (self.reviewer, "", rows, 95_000, None))
        other = LiveSimulation.objects.create(user=self.other, rows=rows)
        # Neither another learner's exchange nor a different transcript can receive this report.
        self.evaluate(simulation=str(other.pk))
        self.evaluate(simulation=str(simulation.pk), rows=[*self.rows[:2], {"speaker": "user", "text": "Et le samedi ?"}])
        self.assertFalse(LiveSimulation.objects.exclude(report=None).exists())
        self.assertEqual(self.evaluate(simulation=str(simulation.pk)).json()["score"], 12)
        simulation.refresh_from_db()
        self.assertEqual(simulation.report["score"], 12)
        unscored = LiveSimulation.objects.create(user=self.reviewer, rows=rows,
                                                 report={"score": None, "nclc": None, "scoreStatus": "insufficient"})

        page = self.client.get(self.live, {"simulation": simulation.pk})
        self.assertContains(page, f"<title>Simulation · {self.task.short_label} · Choisir un atelier photo · Séance enregistrée · Heureux</title>")
        self.assertEqual(page.context["saved_simulation"],
                         {"id": simulation.pk, "rows": rows, "elapsed": 95_000, "report": simulation.report})
        self.assertEqual([(row["id"], row["status"]) for row in page.context["saved_sessions"]],
                         [(unscored.pk, "insufficient"), (simulation.pk, "scored")])
        self.assertContains(page, 'id="lv-saved-simulation"')
        self.assertContains(page, "12/20 · NCLC 8")
        self.assertContains(page, "Bilan sans note")
        self.assertNotContains(page, "null/20")
        for value in ("not-a-uuid", other.pk, uuid.uuid4()):
            self.assertIsNone(self.client.get(self.live, {"simulation": value}).context["saved_simulation"])

        LiveSimulation.objects.filter(pk=simulation.pk).update(created_at=timezone.now() - timedelta(days=1))
        with patch.object(eo2_live, "SAVED_SIMULATIONS", 2):
            kept = {uuid.UUID(self.post(url=save_url, body=json.dumps({"rows": rows, "elapsed": 0})).json()["id"]) for _ in range(2)}
        self.assertEqual(set(LiveSimulation.objects.filter(user=self.reviewer).values_list("pk", flat=True)), kept)
        account = Client()
        account.force_login(self.reviewer)
        export = account.get(reverse("study:export_account")).json()
        exported = export["live_simulations"]
        self.assertEqual({row["id"] for row in exported}, set(map(str, kept)))
        self.assertEqual(len(export["eo2_simulation_history"]), 3)
        self.assertEqual(EO2PracticeAttempt.objects.filter(user=self.reviewer, live_simulation=None).count(), 1)
        self.assertEqual(self.post(**save_options).status_code, 410)
        EO2TopicStatus.objects.filter(user=self.reviewer).update(retry=True)
        account.post(reverse("study:reset_progress"), {"current_pin": "123456", "confirmation": "REINITIALISER"})
        self.assertFalse(LiveSimulation.objects.filter(user=self.reviewer).exists())
        self.assertFalse(EO2PracticeAttempt.objects.filter(user=self.reviewer).exists())
        self.assertTrue(EO2TopicStatus.objects.filter(user=self.reviewer, retry=True, done=False).exists())
        self.assertTrue(LiveSimulation.objects.filter(pk=other.pk).exists())

    @override_settings(CLOUDFLARE_WORKERS_API_KEY="fixture-workers", CLOUDFLARE_ACCOUNT_ID="0123456789abcdef" * 2)
    def test_alternate_oral_reports_require_separate_consent_and_do_not_replace_groq(self):
        self.evaluation_fixture()
        simulation = LiveSimulation.objects.create(user=self.reviewer, rows=self.rows)
        default = self.evaluate(simulation=str(simulation.pk)).json()
        page = self.client.get(self.live, {"simulation": simulation.pk})
        self.assertTemplateUsed(page, "study/simulation/partials/assessment_action.html")
        self.assertEqual(page.context["evaluation_providers"], [
            ("groq", "Groq"), ("gemini", "Gemini"), ("cloudflare", "Workers"),
        ])
        grant = live_conversation.issue_grant(page.wsgi_request, "", purpose="review")
        body = {"consent": True, "provider": "gemini", "rows": self.rows, "simulation": str(simulation.pk)}
        reports = {}
        with patch.object(evaluation, "request_gemini_report", return_value=self.report) as gemini:
            self.assert_private(self.post(url=self.eval_url, body=json.dumps({**body, "reviewGrant": grant})), 403)
            self.assert_private(self.post(url=self.eval_url, body=json.dumps({**body, "consent": False, "pin": PILOT_PIN})), 400)
            gemini.assert_not_called()
            response = self.post(url=self.eval_url, body=json.dumps({**body, "pin": PILOT_PIN}))
            self.assert_private(response, 200)
            reports["gemini"] = response.json()
            gemini.assert_called_once()
            self.assertEqual(gemini.call_args.args[2], oral_evaluation._DIALOGUE_SCHEMA)
        workers_report = {**self.report, "reason": "Bilan Workers gardé à part."}
        with patch.object(evaluation, "request_workers_report", return_value=workers_report) as workers:
            response = self.evaluate(provider="cloudflare", simulation=str(simulation.pk))
            self.assert_private(response, 200)
            reports["cloudflare"] = response.json()
            workers.assert_called_once()
        simulation.refresh_from_db()
        self.assertEqual(simulation.report, default)
        self.assertEqual(simulation.provider_reports, reports)

        for provider, report in {"groq": default, **reports}.items():
            saved = self.client.get(self.eval_url, {"simulation": simulation.pk, "provider": provider})
            self.assert_private(saved, 200)
            self.assertEqual(saved.json(), report)
        self.client.force_login(self.other)
        self.assert_private(self.client.get(self.eval_url, {"simulation": simulation.pk, "provider": "gemini"}), 404)

    def test_learner_deletes_only_their_own_saved_exchange_of_this_subject(self):
        args = ("mai", 2, 8)
        key = tache_two_subject_content_key(*args)
        response = factories.make_response(theme=factories.make_theme("subject-live", task=self.task))
        Prompt.objects.filter(response=response).update(content_key=key)
        rows = [{"speaker": "user", "text": "Bonjour."}]
        mine = LiveSimulation.objects.create(user=self.reviewer, rows=rows)
        EO2PracticeAttempt.objects.create(user=self.reviewer, attempt=mine.pk, vocal=True, live_simulation=mine)
        subject = LiveSimulation.objects.create(user=self.reviewer, subject_key=key, rows=rows)
        other = LiveSimulation.objects.create(user=self.other, rows=rows)
        delete_url = reverse("study:eo_tache_two_live_delete")
        page = self.client.get(self.live)
        self.assertEqual(page.context["delete_url"], delete_url)
        self.assertTemplateUsed(page, "study/simulation/partials/saved_sessions.html")
        self.assertContains(page, f'name="simulation" value="{mine.pk}"')

        def delete(pk, url=delete_url):
            return self.post(f"simulation={pk}", "application/x-www-form-urlencoded", url=url)

        self.assert_private(self.client.get(delete_url), 405)
        self.assertEqual(self.client.post(delete_url, {"simulation": mine.pk}).status_code, 403)
        for pk in ("not-a-uuid", uuid.uuid4(), other.pk, subject.pk):
            self.assert_private(delete(pk), 404)
        self.assertEqual(LiveSimulation.objects.count(), 3)
        self.assertRedirects(delete(mine.pk), self.live, fetch_redirect_response=False)
        self.assertFalse(EO2PracticeAttempt.objects.filter(attempt=mine.pk).exists())
        self.assertRedirects(delete(subject.pk, reverse("study:eo_tache_two_live_delete", args=args)),
                             reverse("study:eo_tache_two_live", args=args), fetch_redirect_response=False)
        self.assertEqual(list(LiveSimulation.objects.values_list("pk", flat=True)), [other.pk])
        self.assertNotContains(self.client.get(self.live), "lv-saved")

    def test_opinion_studio_uses_the_exact_subject_and_separate_grants(self):
        task = factories.make_task(self.task.part, "tache-3")
        theme = factories.make_theme("debats", task=task)
        response = factories.make_response(theme=theme)
        canonical = response.prompts.get()
        variant = Prompt.objects.create(theme=theme, response=response, family=canonical.family, number=canonical.number + 1,
                                        content_key="opinion-variant", text="La marche est-elle le meilleur moyen de découvrir une ville ?")
        url = reverse("study:eo_tache_three_live", args=[variant.pk])
        picker = reverse("study:eo3_topic_picker")
        LiveSimulation.objects.create(
            user=self.reviewer, subject_key=f"eo3:{variant.pk}", rows=[{"speaker": "user", "text": "Je préfère marcher."}],
        )
        catalogue_page = self.client.get(picker)
        self.assertTemplateUsed(catalogue_page, "study/simulation/subject_picker_table.html")
        self.assertEqual(catalogue_page.context["total"], 2)  # Training subject plus one publication for the pair.
        self.assertNotContains(catalogue_page, url)
        practiced = self.client.get(picker, {"etat": "done"}, headers={"x-requested-with": "fetch"})
        self.assertContains(practiced, url)
        self.assertNotContains(practiced, reverse("study:eo_tache_three_live", args=[canonical.pk]))
        default = self.client.get(url).context["session_subject_nav"]
        self.assertEqual((default["position"], default["total"], default["choices"][0]["label"]), (1, 1, variant.text))
        page = self.client.get(url, {"deduplicate": "0"})
        self.assert_private(page, 200)
        self.assertEqual(page.context["scenario_prompt"], variant.text)
        self.assertTemplateUsed(page, "study/expression/partials/subject_navigation.html")
        nav = page.context["session_subject_nav"]
        self.assertEqual((nav["position"], nav["total"]), (2, 2))
        self.assertEqual(nav["previous"]["url"], reverse("study:eo_tache_three_live", args=[canonical.pk]) + "?deduplicate=0")
        self.assertEqual(page.context["subject_url"], reverse("study:response_detail", args=["eo", task.slug, variant.pk]) + "?deduplicate=0")
        self.assertIn("microphone=(self)", page["Permissions-Policy"])
        self.assertIn("wss://generativelanguage.googleapis.com", page["Content-Security-Policy"])
        self.assertNotContains(page, response.body)
        with self.settings(GEMINI_API_KEY=""):
            self.assert_no_live_policy(self.client.get(url))
        token = page.context["token_url"]
        first = self.post(url=token, body=json.dumps({"consent": True, "pin": PILOT_PIN, "purpose": "attempt"}))
        def instruction():
            return json.loads(self.connection.request.call_args.kwargs["body"])["bidiGenerateContentSetup"]["systemInstruction"]["parts"][0]["text"]
        self.assertIn(variant.text, instruction())
        self.assertNotIn(canonical.text, instruction())
        grant = json.dumps({"consent": True, "purpose": "exchange", "exchangeGrant": first.json()["exchangeGrant"]})
        for wrong in (self.token_url, reverse("study:eo_tache_three_live_token", args=[canonical.pk])):
            self.assert_private(self.post(grant, url=wrong), 403)
        self.assert_private(self.post(grant, url=token), 200)
        self.assertIn("Gardez le silence", instruction())
        self.assertNotIn(live_conversation._TURN_RULE, instruction())
        theme.is_active = False
        theme.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.post(grant, url=token).status_code, 404)

    def test_single_opinion_can_be_saved_scored_and_reopened_without_a_partner(self):
        factories.make_task(self.task.part, "tache-3")
        self.evaluation_fixture()
        page = self.client.get(reverse("study:eo_tache_three_live"))
        sentence = "À pied, on peut observer les bâtiments et prendre le temps de discuter avec les habitants. "
        rows = [{"speaker": "user", "text": (sentence * 48).strip()}]
        self.assertGreater(len(rows[0]["text"]), 4000)
        previous = LiveSimulation.objects.create(user=self.reviewer, rows=self.rows)
        save = page.context["save_url"]
        with patch.object(eo2_live, "SAVED_SIMULATIONS", 1):
            saved = self.post(url=save, body=json.dumps({"rows": rows, "elapsed": 270000}))
        self.assert_private(saved, 201)
        self.assertTrue(LiveSimulation.objects.filter(pk=previous.pk).exists())
        pk = saved.json()["id"]
        self.assertIsNone(self.client.get(self.live, {"simulation": pk}).context["saved_simulation"])
        self.assert_private(self.post(url=save, body=json.dumps({"rows": self.rows, "elapsed": 1000})), 400)
        for mark in self.report["criteria"].values():
            mark.update(evidenceId="E1", why="Votre exemple explique l’intérêt de la marche.")
        paragraph = (sentence * 5).strip()  # One developed paragraph can exceed the old per-turn limit.
        conclusion = "C’est pour cela que je préfère marcher."
        self.report.update(proposal=paragraph + "\r\n\r\n" + conclusion, corrections=[], strengths=[])
        result = self.evaluate(url=page.context["evaluation_url"], rows=rows, simulation=pk)
        self.assert_private(result, 200)
        self.assertEqual(result.json()["scoreStatus"], "scored")
        self.assertEqual(result.json()["proposal"], [paragraph, conclusion])
        payload = json.loads(self.eval_connection.request.call_args.kwargs["body"])
        self.assertEqual(payload["response_format"]["json_schema"]["schema"]["properties"]["proposal"], {"type": "string"})
        system, user = payload["messages"]
        self.assertIn("tâche 3", system["content"])
        sent = json.loads(user["content"])
        self.assertEqual(sent["consigne"], page.context["scenario_prompt"])
        only_row, = sent["rows"]
        self.assertEqual(" ".join(p["text"] for p in only_row["passages"]), rows[0]["text"])
        self.assertEqual(result.json()["criteria"][0]["quote"], sentence.strip())
        reopened = self.client.get(reverse("study:eo_tache_three_live"), {"simulation": pk})
        self.assertEqual(reopened.context["saved_simulation"]["report"], result.json())
        self.report["proposal"] = " "
        brief = self.evaluate(url=page.context["evaluation_url"], rows=[{"speaker": "user", "text": "Oui, bien sûr."}])
        self.assertEqual(brief.json()["proposal"], [])
        self.assertIsNone(brief.json()["score"])
        self.assertNotIn("interaction", brief.json()["reason"])
        self.report["proposal"] = {"paragraph": "Format invalide."}
        invalid = self.ground(rows, monologue=True)
        self.assertEqual((invalid["scoreStatus"], invalid["proposal"], invalid["omitted"]), ("scored", [], True))

    def test_no_total_for_partial_unobserved_or_unsupported_rubric(self):
        self.evaluation_fixture()
        self.report["criteria"]["grammar"]["evidenceId"] = "E999"
        partial = self.evaluate().json()
        self.assertIsNone(partial["score"])
        self.assertEqual(partial["scoreStatus"], "incomplete")
        self.assertIsNone(partial["criteria"][-1]["score"])
        self.assertEqual(partial["criteria"][0]["score"], 4)
        self.assertTrue(partial["evidence"])
        self.assertTrue(partial["annotations"])
        for item in self.report["criteria"].values():
            item.update(points=None, evidenceId=None, why="Échantillon trop bref.")
        too_short = self.evaluate().json()
        self.assertEqual((too_short["score"], too_short["nclc"], too_short["scoreStatus"]), (None, None, "insufficient"))
        self.assertFalse(too_short["omitted"])
        for item in self.report["criteria"].values():
            item.update(points=4, evidenceId="E1")
        greeting_only = self.evaluate(rows=[{"speaker": "model", "text": "Bonjour !"},
                                            {"speaker": "user", "text": "Bonjour !"}]).json()
        self.assertEqual(greeting_only["scoreStatus"], "insufficient")
        self.assertTrue(all(row["score"] is None for row in greeting_only["criteria"]))

    def test_only_a_complete_reassessment_replaces_the_saved_partial_report(self):
        self.evaluation_fixture()
        session = LiveSimulation.objects.create(user=self.reviewer, rows=self.rows)
        params = {"simulation": str(session.pk)}
        lexicon = self.report["criteria"]["lexicon"]
        lexicon["evidenceId"] = "E999"
        partial = self.evaluate(**params).json()
        self.assertIsNone(partial["criteria"][2]["score"])

        self.report["criteria"]["grammar"]["evidenceId"] = "E999"
        lexicon["evidenceId"] = "E2"
        self.assertEqual(self.evaluate(**params).json(), {**partial, "previousReportKept": True})
        session.refresh_from_db()
        self.assertEqual(session.report, partial)  # The two incomplete sets of marks are not merged.

        self.eval_response.status = 429
        self.assert_private(self.evaluate(**params), 429)
        session.refresh_from_db()
        self.assertEqual(session.report, partial)
        self.eval_response.status = 200
        self.report["criteria"]["grammar"]["evidenceId"] = "E2"
        completed = self.evaluate(**params).json()
        session.refresh_from_db()
        self.assertEqual((completed["score"], completed), (12, session.report))
        lexicon["evidenceId"] = "E999"
        self.assertEqual(self.evaluate(**params).json(), {**completed, "previousReportKept": True})

    def test_unreadable_unfinished_or_refused_reports_do_not_retry(self):
        self.evaluation_fixture()
        body = json.dumps({"rows": self.rows, "pin": PILOT_PIN, "consent": True})
        self.complete(json.dumps(self.report)[:70])
        malformed = self.post(url=self.eval_url, body=body)
        self.assert_private(malformed, 502)
        self.assertIn("illisible", malformed.json()["error"])
        self.eval_response.read.return_value = b'{"choices": []}'
        self.assert_private(self.post(url=self.eval_url, body=body), 502)
        self.complete("", finish="length")
        with self.assertLogs(evaluation.logger, "WARNING") as logs:
            self.assert_private(self.post(url=self.eval_url, body=body), 422)
        self.assertIn("finish length", logs.output[0])
        self.assertIn("'prompt_tokens': 3900", logs.output[0])
        self.complete("", refusal="Je ne peux pas évaluer ce texte.")
        self.assert_private(self.post(url=self.eval_url, body=body), 422)
        self.eval_response.status = 400
        self.assert_private(self.post(url=self.eval_url, body=body), 502)
        self.eval_connection.request.side_effect = TimeoutError("private-provider-details")
        timeout = self.post(url=self.eval_url, body=body)
        self.assert_private(timeout, 504)
        self.assertIn("à temps", timeout.json()["error"])
        self.assertNotIn("private-provider-details", timeout.json()["error"])
        self.assertEqual(self.eval_connection.request.call_count, 6)

    def test_trickling_or_oversized_reply_stops_at_one_deadline(self):
        self.evaluation_fixture()
        body = json.dumps({"rows": self.rows, "pin": PILOT_PIN, "consent": True})
        self.complete()
        with patch.object(evaluation, "_MAX_RESPONSE", 100):
            self.assertIn("illisible", self.post(url=self.eval_url, body=body).json()["error"])
        near, far = socket.socketpair()
        self.addCleanup(far.close)
        self.addCleanup(near.close)
        self.eval_connection.sock = near

        def read(limit):
            near.settimeout(5)  # Each fragment that arrives in time renews the read timeout.
            return near.recv(limit)
        self.eval_response.read = read
        with patch.object(evaluation, "DEADLINE_SECONDS", 0.2), self.assertLogs(evaluation.logger, "WARNING"):
            late = self.post(url=self.eval_url, body=body)
        self.assert_private(late, 504)
        self.assertIn("arrêt à 0 s", late.json()["error"])
        self.assertEqual(self.eval_connection.request.call_count, 2)

    def test_slow_review_streams_keep_alive_before_the_report_or_its_error(self):
        self.evaluation_fixture()
        body = json.dumps({"rows": self.rows, "pin": PILOT_PIN, "consent": True})
        self.complete()
        release = threading.Event()
        self.eval_connection.request.side_effect = lambda *args, **kwargs: release.wait(5)
        with patch.multiple(eo2_live, EVALUATION_GRACE_SECONDS=0, EVALUATION_KEEPALIVE_SECONDS=0.01):
            response = self.post(url=self.eval_url, body=body, HTTP_ACCEPT_ENCODING="gzip")
            self.assert_private(response, 200)
            self.assertFalse(response.has_header("Content-Encoding"))
            chunks = iter(response.streaming_content)
            self.assertEqual(next(chunks), b" ")  # Sent before Groq answers, so the proxy sees activity.
            release.set()
            self.assertEqual(json.loads(b"".join(chunks))["score"], 12)
            simulation = LiveSimulation.objects.create(user=self.reviewer, rows=self.rows)
            release.clear()
            left = self.post(url=self.eval_url, body=json.dumps({**json.loads(body), "simulation": str(simulation.pk)}))
            self.assertEqual(next(iter(left.streaming_content)), b" ")
            threading.Timer(0.05, release.set).start()
            left.close()  # The learner leaves before the report arrives.
            simulation.refresh_from_db()
            self.assertEqual(simulation.report["score"], 12)
            release.clear()
            self.eval_response.status = 400
            chunks = iter(self.post(url=self.eval_url, body=body).streaming_content)
            self.assertEqual(next(chunks), b" ")
            release.set()
            failed = json.loads(b"".join(chunks))
            release.clear()
            with patch.object(eo2_live, "EVALUATION_DEADLINE_SECONDS", 0):
                late = json.loads(b"".join(self.post(url=self.eval_url, body=body).streaming_content))
            release.set()  # Groq is still pending, but the stream ended before Gunicorn's timeout.
        self.assertEqual(failed["status"], 502)
        self.assertIn("HTTP 400", failed["error"])
        self.assertEqual(late["status"], 504)
