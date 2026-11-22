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
from study.expression.eo.tache_2 import gemini_evaluation, gemini_live
from study.models import LiveSimulation, LoginThrottle, Prompt
from study.views import eo2_live
from . import factories


PILOT_PIN = "test-audio-pin"


@override_settings(GEMINI_LIVE_API_KEY="test-pilot-key", GROQ_API_KEY="test-groq-key", AI_PIN=PILOT_PIN)
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
            {"GEMINI_LIVE_API_KEY": ""},
            {"AI_PIN": ""},
            {"AI_PIN": "x" * 129},
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
        with self.settings(GEMINI_LIVE_API_KEY=""):
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
        transport = self.enterContext(patch.object(gemini_evaluation, "HTTPSConnection", autospec=True))
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
                           "task": {"points": 4, "turnIndex": 0, "why": "La demande de prix est claire."},
                           "coherence": {"points": 3, "turnIndex": 2, "why": "La relance précise la quantité."},
                           "lexicon": {"points": 3, "turnIndex": 2, "why": "Le terme « appareils » est précis."},
                           "grammar": {"points": 2, "turnIndex": 2, "why": "Le second verbe doit rester à l’infinitif."}},
                       "reason": "Vous adaptez votre demande au tarif annoncé.",
                       "strengths": [{"turnIndex": 0, "why": "Le prix est ciblé."},
                                     {"turnIndex": 2, "why": "Vous explorez une autre possibilité."}],
                       "corrections": [{"turnIndex": 2, "before": "veux prend", "after": "veux prendre",
                                        "why": "Après vouloir, le deuxième verbe reste à l’infinitif."}],
                       "proposal": ["Bonjour, combien coûte le prêt d’un appareil photo ?",
                                    "Et si je veux prendre deux appareils, le tarif change-t-il ?"],
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
        self.assertEqual([item["quote"] for item in report["evidence"]], [self.rows[0]["text"], self.rows[2]["text"]])
        self.assertEqual(report["proposal"], self.report["proposal"])
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
        self.assertEqual(json.loads(user["content"]),
                         {"consigne": page.context["subject"].prompt, "rows": [dict(row, turnIndex=i) for i, row in enumerate(self.rows)]})
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
        self.assert_private(self.post(url=self.eval_url, body=" " * (gemini_evaluation.MAX_BODY + 1)), 400)
        self.assert_private(self.evaluate(pin=""), 403)
        self.assert_private(self.client.post(self.eval_url, {"consent": True}, content_type="application/json"), 403)
        for key in ("GEMINI_LIVE_API_KEY", "GROQ_API_KEY"):
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
                result = gemini_evaluation._ground(self.report, self.rows)
                self.assertEqual((result["cefr"], result["nclc"]), (cefr, nclc))

    def test_unverifiable_detail_does_not_destroy_a_supported_score(self):
        self.evaluation_fixture()
        self.report["strengths"][0]["turnIndex"] = 1  # The partner never earns marks for the learner.
        self.rows[-1]["text"] += " veux prend"
        self.report["corrections"].append({"turnIndex": 0, "before": "inventé", "after": "mot", "why": "Correction."})
        report = self.evaluate().json()
        self.assertEqual((report["score"], report["omitted"], report["annotations"]), (12, True, []))
        self.assertEqual([item["quote"] for item in report["evidence"]], [self.rows[2]["text"]])
        self.eval_connection.request.assert_called_once()

    def test_corrections_ignore_apostrophe_style_case_punctuation_and_fillers(self):
        self.evaluation_fixture()
        self.rows[0]["text"] = "Bonjour, euh je voudrais savoir qu'est-ce que le prêt comprend."
        self.report["corrections"][:0] = [
            {"turnIndex": 0, "before": "Savoir qu’est-ce que", "after": "savoir ce que",
             "why": "Dans une question indirecte, « ce que » remplace « qu’est-ce que »."},
            {"turnIndex": 0, "before": "euh je", "after": "je", "why": "Hésitation."},
            {"turnIndex": 0, "before": "bonjour,", "after": "Bonjour !", "why": "Ponctuation."},
        ]
        result = gemini_evaluation._ground(self.report, self.rows)
        self.assertTrue(result["omitted"])
        self.assertEqual([(mark["turnIndex"], mark["before"], mark["after"]) for mark in result["annotations"]],
                         [(0, "savoir qu'est-ce que", "savoir ce que"), (2, "veux prend", "veux prendre")])
        mark = result["annotations"][0]
        self.assertEqual(self.rows[0]["text"][mark["start"]:mark["end"]], mark["before"])

    def test_malformed_proposal_is_dropped_without_losing_the_score(self):
        self.evaluation_fixture()
        for proposal in (None, "Bonjour.", ["Bonjour.", " "], ["x" * 401], [3]):
            with self.subTest(proposal=proposal):
                self.report["proposal"] = proposal
                result = gemini_evaluation._ground(self.report, self.rows)
                self.assertEqual((result["score"], result["omitted"], result["proposal"]), (12, True, []))

    def test_overlong_lists_keep_their_first_items_and_the_schema_has_no_bounds(self):
        self.evaluation_fixture()
        self.report["proposal"] = [f"Réplique {n}." for n in range(17)]
        self.report["strengths"] *= 2
        report = self.evaluate().json()
        self.assertEqual((report["score"], report["omitted"], len(report["evidence"])), (12, True, 3))
        self.assertEqual(report["proposal"], self.report["proposal"][:16])
        payload = json.loads(self.eval_connection.request.call_args.kwargs["body"])
        schema = json.dumps(payload["response_format"])
        for bound in ("minItems", "maxItems", "minimum", "maximum"):
            self.assertNotIn(bound, schema)  # Strict decoding would compile every bound into its grammar.

    def test_transient_provider_failure_retries_once_and_errors_name_the_provider_code(self):
        self.evaluation_fixture()
        sleep = self.enterContext(patch.object(gemini_evaluation.time, "sleep"))
        body = json.dumps({"rows": self.rows, "pin": PILOT_PIN, "consent": True})
        self.complete()
        unavailable = b'{"error":{"message":"The model is overloaded.","type":"internal_server_error"}}'
        replies = iter([(503, unavailable), (200, self.eval_response.read.return_value)])

        def reply(*args, **kwargs):
            self.eval_response.status, self.eval_response.read.return_value = next(replies)
        self.eval_connection.request.side_effect = reply
        self.assertEqual(self.post(url=self.eval_url, body=body).json()["score"], 12)
        replies = iter([(503, unavailable)] * 2)
        with self.assertLogs(gemini_evaluation.logger, "WARNING") as logs:
            failed = self.post(url=self.eval_url, body=body)
        self.assert_private(failed, 502)
        self.assertIn("HTTP 503 internal_server_error", failed.json()["error"])
        self.assertIn("The model is overloaded.", logs.output[0])
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
        with self.settings(GEMINI_LIVE_API_KEY=""):
            self.assert_private(self.post(url=save_url, body=json.dumps({"rows": rows, "elapsed": 0})), 403)
        saved = self.post(url=save_url, body=json.dumps({"rows": rows, "elapsed": 95_000}))
        self.assert_private(saved, 201)
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
        self.assertEqual(page.context["saved_simulation"],
                         {"id": simulation.pk, "rows": rows, "elapsed": 95_000, "report": simulation.report})
        self.assertEqual([(row["id"], row["status"]) for row in page.context["saved_simulations"]],
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
        exported = account.get(reverse("study:export_account")).json()["live_simulations"]
        self.assertEqual({row["id"] for row in exported}, set(map(str, kept)))
        account.post(reverse("study:reset_progress"), {"current_pin": "123456", "confirmation": "REINITIALISER"})
        self.assertFalse(LiveSimulation.objects.filter(user=self.reviewer).exists())
        self.assertTrue(LiveSimulation.objects.filter(pk=other.pk).exists())

    def test_no_total_for_partial_unobserved_or_unsupported_rubric(self):
        self.evaluation_fixture()
        self.report["criteria"]["grammar"]["turnIndex"] = 1
        partial = self.evaluate().json()
        self.assertIsNone(partial["score"])
        self.assertEqual(partial["scoreStatus"], "incomplete")
        self.assertIsNone(partial["criteria"][-1]["score"])
        self.assertEqual(partial["criteria"][0]["score"], 4)
        self.assertTrue(partial["evidence"])
        self.assertTrue(partial["annotations"])
        for item in self.report["criteria"].values():
            item.update(points=None, turnIndex=None, why="Échantillon trop bref.")
        too_short = self.evaluate().json()
        self.assertEqual((too_short["score"], too_short["nclc"], too_short["scoreStatus"]), (None, None, "insufficient"))
        self.assertFalse(too_short["omitted"])
        for item in self.report["criteria"].values():
            item.update(points=4, turnIndex=1)
        greeting_only = self.evaluate(rows=[{"speaker": "model", "text": "Bonjour !"},
                                            {"speaker": "user", "text": "Bonjour !"}]).json()
        self.assertEqual(greeting_only["scoreStatus"], "insufficient")
        self.assertTrue(all(row["score"] is None for row in greeting_only["criteria"]))

    def test_unreadable_unfinished_or_refused_reports_do_not_retry(self):
        self.evaluation_fixture()
        body = json.dumps({"rows": self.rows, "pin": PILOT_PIN, "consent": True})
        self.complete(json.dumps(self.report)[:70])
        malformed = self.post(url=self.eval_url, body=body)
        self.assert_private(malformed, 502)
        self.assertIn("grille lisible", malformed.json()["error"])
        self.eval_response.read.return_value = b'{"choices": []}'
        self.assert_private(self.post(url=self.eval_url, body=body), 502)
        self.complete("", finish="length")
        with self.assertLogs(gemini_evaluation.logger, "WARNING") as logs:
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
        with patch.object(gemini_evaluation, "_MAX_RESPONSE", 100):
            self.assertIn("grille lisible", self.post(url=self.eval_url, body=body).json()["error"])
        near, far = socket.socketpair()
        self.addCleanup(far.close)
        self.addCleanup(near.close)
        self.eval_connection.sock = near

        def read(limit):
            near.settimeout(5)  # Each fragment that arrives in time renews the read timeout.
            return near.recv(limit)
        self.eval_response.read = read
        with patch.object(gemini_evaluation, "_DEADLINE_SECONDS", 0.2), self.assertLogs(gemini_evaluation.logger, "WARNING"):
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
        self.assertIn("Groq", failed["error"])
        self.assertEqual(late["status"], 504)
