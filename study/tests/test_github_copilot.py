import base64
import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

import httpx
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from study.accounts import github_copilot
from study.models import (
    GitHubCopilotConnection, LiveSimulation, OralEvaluationJob,
    WritingSimulationAttempt, WritingSimulationEvaluationStatus,
)
from study.simulation import copilot_runtime, evaluation, live_conversation, oral_jobs
from study.views import writing_simulation

from . import factories


@override_settings(
    COPILOT_GITHUB_CLIENT_ID="fixture-client",
    COPILOT_GITHUB_CLIENT_SECRET="fixture-secret",
    COPILOT_GITHUB_CALLBACK_URL="https://testserver/compte/github/retour/",
    COPILOT_TOKEN_ENCRYPTION_KEY=base64.urlsafe_b64encode(b"\x01" * 32).decode(),
    GROQ_API_KEY="fixture-groq",
    CLOUDFLARE_WORKERS_API_KEY="",
    GEMINI_API_KEY="",
)
class GitHubCopilotTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = factories.make_user("copilot-linked-learner")
        cls.other = factories.make_user("copilot-other-learner")
        cls.task = factories.make_task(factories.make_part("ee"), "tache-1")

    def setUp(self):
        self.client.force_login(self.user)
        self.authorize = reverse("study:github_copilot_authorize")
        self.callback = reverse("study:github_copilot_callback")
        self.disconnect = reverse("study:github_copilot_disconnect")
        self.settings_url = reverse("study:settings")

    def _start_link(self, **data):
        response = self.client.post(self.authorize, data, secure=True)
        authorization_url = response.context["authorization_url"]
        self.assertContains(response, f'<a class="btn" href="{authorization_url}">Continuer vers GitHub</a>', html=True)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("no-store", response["Cache-Control"])
        url = urlsplit(authorization_url)
        self.assertEqual((url.hostname, url.path), ("github.com", "/login/oauth/authorize"))
        return {key: values[0] for key, values in parse_qs(url.query).items()}

    @staticmethod
    def _tokens(suffix="first"):
        return {
            "access_token": f"ghu_fixture_{suffix}", "refresh_token": f"ghr_fixture_{suffix}",
            "expires_in": 28800, "refresh_token_expires_in": 15897600,
        }

    def _link(self, github_user_id=123):
        config = github_copilot.configuration()
        fields = github_copilot._encrypted_fields(config, ("ghu_fixture", "ghr_fixture", 28800, 15897600))
        return GitHubCopilotConnection.objects.create(user=self.user, github_user_id=github_user_id, **fields)

    def _attempt(self, *, submitted=True):
        return WritingSimulationAttempt.objects.create(
            user=self.user, task=self.task, deadline_at=timezone.now() + timedelta(minutes=10),
            status="submitted" if submitted else "active",
            snapshot={"prompt": "Invitez un ami."},
            body="Bonjour. " + " ".join(["bonjour"] * 59), word_count=60,
        )

    def test_existing_login_authorizes_with_pkce_and_returns_to_its_bilan(self):
        attempt = self._attempt()
        url = reverse("study:ee1_simulation_attempt", args=[attempt.pk])
        page = self.client.get(url)
        self.assertContains(page, f'action="{self.authorize}"', count=1)
        menu = page.content.decode().split('class="nav__menu"', 1)[1].split("</details>", 1)[0]
        self.assertIn("Connecter GitHub", menu)
        self.assertIn('data-icon="github"', menu)
        self.assertIn(f'name="next" value="{url}"', menu)
        query = self._start_link(next=url)
        self.assertEqual(query["scope"], "offline_access")
        self.assertEqual(query["code_challenge_method"], "S256")
        self.assertNotIn(str(attempt.pk), str(query))
        self.assertNotIn("fixture-secret", str(query))

        identity = httpx.Response(
            200, json={"id": 123, "login": "not-stored"}, request=httpx.Request("GET", "https://api.github.com/user"),
        )
        with (
            patch.object(github_copilot.httpx, "post", return_value=httpx.Response(200, json=self._tokens())) as exchange,
            patch.object(github_copilot.httpx, "get", return_value=identity),
        ):
            result = self.client.get(self.callback, {"code": "fixture-code", "state": query["state"]}, secure=True)
            self.assertRedirects(result, url + "?copilot=connected", fetch_redirect_response=False)
            self.assertEqual(result["Referrer-Policy"], "no-referrer")
            verifier = exchange.call_args.kwargs["data"]["code_verifier"]
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            self.assertEqual(challenge, query["code_challenge"])
            self.client.get(self.callback, {"code": "fixture-code", "state": query["state"]}, secure=True)
            exchange.assert_called_once()

        link = GitHubCopilotConnection.objects.get(user=self.user)
        self.assertEqual(link.github_user_id, 123)
        self.assertNotIn(b"ghu_fixture", bytes(link.encrypted_tokens))
        self.assertEqual(github_copilot.access_token(self.user.pk, link.pk), "ghu_fixture_first")
        settings_page = self.client.get(self.settings_url)
        self.assertContains(settings_page, "Déconnecter GitHub")
        self.assertNotContains(settings_page, f'action="{self.authorize}"')

    def test_connections_started_on_a_subject_list_keep_its_filters_and_show_the_notice(self):
        page = reverse("study:ee1_subject_picker")
        filters = "q=invitation&deduplicate=0"
        origin = f"{page}?{filters}"
        self.assertContains(self.client.get(origin), f'name="next" value="{page}?q=invitation&amp;deduplicate=0"')
        with patch.object(github_copilot, "connect", return_value=True):
            query = self._start_link(next=origin)
            self.assertNotIn("next", query)
            callback = self.client.get(self.callback, {"code": "fixture-code", "state": query["state"]}, secure=True)
        self.assertRedirects(callback, f"{origin}&copilot=connected")
        self.assertContains(self.client.get(callback.url), "Compte GitHub connecté.", count=1)

    def test_off_site_return_paths_fall_back_to_settings(self):
        for target in ("https://example.com/", "//example.com/"):
            with self.subTest(target=target), patch.object(github_copilot, "connect", return_value=True):
                query = self._start_link(next=target)
                callback = self.client.get(self.callback, {"code": "fixture-code", "state": query["state"]}, secure=True)
                self.assertRedirects(callback, self.settings_url + "?copilot=connected", fetch_redirect_response=False)

    def test_forged_and_expired_callbacks_never_exchange_a_code(self):
        with patch.object(github_copilot, "connect") as connect:
            query = self._start_link()
            self.client.get(self.callback, {"code": "bad", "state": "forged"}, secure=True)
            self.client.force_login(self.other)
            self.client.get(self.callback, {"code": "bad", "state": query["state"]}, secure=True)
            with patch("study.views.github_copilot.time.time", return_value=timezone.now().timestamp() - 601):
                expired = self._start_link()
            self.client.get(self.callback, {"code": "bad", "state": expired["state"]}, secure=True)
        connect.assert_not_called()
        self.assertFalse(GitHubCopilotConnection.objects.exists())

    def test_link_and_unlink_require_post_csrf_and_do_not_leak_a_callback_code(self):
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.user)
        self.assertEqual(csrf.get(self.authorize, secure=True).status_code, 405)
        self.assertEqual(csrf.post(self.authorize, secure=True).status_code, 403)
        self.assertEqual(csrf.post(self.disconnect, secure=True).status_code, 403)
        result = Client().get(self.callback, {"code": "must-not-repeat", "state": "state"}, secure=True)
        self.assertEqual(result.status_code, 302)
        self.assertNotIn("must-not-repeat", result.url)

    def test_refresh_rotates_credentials_and_revocation_requires_reconnection(self):
        link = self._link()
        expired = timezone.now() - timedelta(seconds=1)
        GitHubCopilotConnection.objects.filter(pk=link.pk).update(access_expires_at=expired)
        with patch.object(github_copilot.httpx, "post", return_value=httpx.Response(200, json=self._tokens("rotated"))) as refresh:
            self.assertEqual(github_copilot.access_token(self.user.pk, link.pk), "ghu_fixture_rotated")
            self.assertEqual(github_copilot.access_token(self.user.pk, link.pk), "ghu_fixture_rotated")
            refresh.assert_called_once()
            self.assertEqual(refresh.call_args.kwargs["data"]["refresh_token"], "ghr_fixture")
        GitHubCopilotConnection.objects.filter(pk=link.pk).update(access_expires_at=expired)
        with patch.object(github_copilot.httpx, "post", return_value=httpx.Response(200, json={"error": "bad_refresh_token"})):
            with self.assertRaises(github_copilot.ReconnectRequired):
                github_copilot.access_token(self.user.pk, link.pk)
        self.assertFalse(GitHubCopilotConnection.objects.filter(pk=link.pk).exists())

    def test_ee1_submission_starts_mai_once_for_the_link_in_the_editor(self):
        link = self._link()
        attempt = self._attempt(submitted=False)
        page = reverse("study:ee1_simulation_attempt", args=[attempt.pk])
        endpoint = reverse("study:ee1_simulation_evaluate", args=[attempt.pk])
        editor = self.client.get(page)
        self.assertContains(editor, 'name="evaluation_consent" value="copilot-mai"')
        self.assertContains(editor, f'name="evaluation_link" value="{link.pk}"')
        data = {
            "body": attempt.body, "draft_revision": editor.context["draft_revision"],
            "evaluation_consent": editor.context["auto_evaluation"],
            "evaluation_link": editor.context["auto_evaluation_link_id"],
        }
        with patch.object(writing_simulation.threading, "Thread") as thread:
            with self.captureOnCommitCallbacks(execute=True):
                for action in ("save", "expire"):
                    self.assertRedirects(
                        self.client.post(page, {**data, "action": action}), page + "?saved=1",
                        fetch_redirect_response=False,
                    )
                invalid = self.client.post(page, {**data, "action": "submit", "body": "Bonjour."})
                self.assertEqual(invalid.status_code, 400)
            thread.assert_not_called()
            with self.captureOnCommitCallbacks(execute=True):
                for _ in range(2):
                    self.assertRedirects(
                        self.client.post(page, {**data, "action": "submit"}), page, fetch_redirect_response=False,
                    )
        attempt.refresh_from_db()
        thread.assert_called_once_with(
            target=writing_simulation.run_evaluation,
            args=(attempt.pk, attempt.evaluation_started_at, writing_simulation.SPECS[1], "copilot-mai"),
            kwargs={"copilot_link_id": link.pk}, daemon=True,
        )
        thread.return_value.start.assert_called_once()
        self.assertEqual(attempt.body, data["body"])
        with self.assertNumQueries(3):
            polling = self.client.get(endpoint, {"provider": "copilot-mai"})
        self.assertEqual(polling.json()["status"], "processing")
        self.assertEqual(self.client.get(endpoint).json()["status"], "processing")
        self.assertContains(self.client.get(page), 'data-evaluation-provider="copilot-mai"')

    def test_ee1_submission_does_not_send_on_an_unlinked_or_replaced_consent(self):
        for reconnect in (False, True):
            with self.subTest(reconnected=reconnect):
                self._link()
                attempt = self._attempt(submitted=False)
                page = reverse("study:ee1_simulation_attempt", args=[attempt.pk])
                editor = self.client.get(page)
                self.client.post(self.disconnect)
                if reconnect:
                    self._link(github_user_id=456)
                with patch.object(writing_simulation.threading, "Thread") as thread, self.captureOnCommitCallbacks(execute=True):
                    self.assertRedirects(self.client.post(page, {
                        "action": "submit", "body": attempt.body, "draft_revision": editor.context["draft_revision"],
                        "evaluation_consent": editor.context["auto_evaluation"],
                        "evaluation_link": editor.context["auto_evaluation_link_id"],
                    }), page, fetch_redirect_response=False)
                thread.assert_not_called()
                attempt.refresh_from_db()
                self.assertEqual(attempt.status, "submitted")
                self.assertEqual(attempt.evaluation_status, WritingSimulationEvaluationStatus.NOT_REQUESTED)

    def test_linked_bilan_selects_only_three_models_and_keeps_saved_reports_after_unlink(self):
        link = self._link()
        attempt = self._attempt(submitted=False)
        page = reverse("study:ee1_simulation_attempt", args=[attempt.pk])
        endpoint = reverse("study:ee1_simulation_evaluate", args=[attempt.pk])
        editor = self.client.get(page)
        with patch.object(writing_simulation.threading, "Thread") as thread, self.captureOnCommitCallbacks(execute=True):
            self.assertRedirects(self.client.post(page, {
                "body": attempt.body, "action": "submit", "draft_revision": editor.context["draft_revision"],
                "evaluation_consent": "groq",
            }), page, fetch_redirect_response=False)
            thread.assert_not_called()
            result = self.client.get(page)
            self.assertEqual(result.context["evaluation_providers"], list(copilot_runtime.LABELS.items()))
            self.assertEqual(result.context["evaluation_provider"], "copilot-mai")
            self.assertNotContains(result, "utilise vos crédits")
            rejected = self.client.post(endpoint, {"consent": True, "provider": "groq"}, content_type="application/json")
            self.assertEqual(rejected.status_code, 409)
            payload = {"consent": True, "provider": "copilot-astra"}
            self.assertEqual(self.client.post(endpoint, payload, content_type="application/json").status_code, 202)

        thread.assert_called_once()
        selected = thread.call_args.kwargs
        self.assertEqual(selected["kwargs"], {"copilot_link_id": link.pk})
        report = {"score": 9, "scoreRange": {"min": 8, "max": 10}}
        with (
            patch.object(copilot_runtime, "report_transport") as transport,
            patch.object(writing_simulation.writing_evaluation, "score", return_value=report) as score,
            patch.object(writing_simulation, "close_old_connections"),
        ):
            writing_simulation.run_evaluation(*selected["args"], **selected["kwargs"])
            transport.assert_called_once_with("ghu_fixture", "gpt-6.2-astra")
            self.assertIs(score.call_args.kwargs["request_report"], transport.return_value)
        with self.assertNumQueries(3):
            saved = self.client.get(endpoint, {"provider": "copilot-astra"})
        self.assertEqual(saved.json()["report"], report)
        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation_status, WritingSimulationEvaluationStatus.READY)
        self.assertIsNone(attempt.evaluation_lease_until)
        self.client.post(self.disconnect)
        self.assertFalse(GitHubCopilotConnection.objects.exists())
        self.assertEqual(self.client.get(endpoint, {"provider": "copilot-astra"}).json()["report"], report)
        self.assertEqual(self.client.post(endpoint, payload, content_type="application/json").json()["report"], report)
        self.assertEqual(self.client.post(endpoint, {
            "consent": True, "provider": "copilot-opus",
        }, content_type="application/json").status_code, 409)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(endpoint, {"provider": "copilot-astra"}).status_code, 404)

    def test_interrupted_bilan_stops_polling_and_only_retries_after_an_explicit_request(self):
        self._link()
        attempt = self._attempt()
        endpoint = reverse("study:ee1_simulation_evaluate", args=[attempt.pk])
        astra = {"consent": True, "provider": "copilot-astra"}
        mai = {"consent": True, "provider": "copilot-mai"}
        with patch.object(writing_simulation.threading, "Thread") as thread, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(endpoint, astra, content_type="application/json").status_code, 202)
            self.assertEqual(self.client.post(endpoint, mai, content_type="application/json").status_code, 409)
            self.assertEqual(self.client.get(endpoint, {"provider": "copilot-astra"}).json()["status"], "processing")
        thread.assert_called_once()

        WritingSimulationAttempt.objects.filter(pk=attempt.pk).update(evaluation_lease_until=timezone.now())
        with (
            patch.object(copilot_runtime, "linked_report_transport") as transport,
            patch.object(writing_simulation, "close_old_connections"),
        ):
            claim = thread.call_args.kwargs
            writing_simulation.run_evaluation(*claim["args"], **claim["kwargs"])
        transport.assert_not_called()
        with patch.object(writing_simulation.threading, "Thread") as thread, self.captureOnCommitCallbacks(execute=True):
            status = self.client.get(endpoint, {"provider": "copilot-astra"}).json()
            self.assertEqual(status["status"], "unavailable")
            self.assertTrue(status["retryable"])
            thread.assert_not_called()
            self.assertEqual(self.client.post(endpoint, mai, content_type="application/json").status_code, 202)
        thread.assert_called_once()
        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation["provider"], "copilot-mai")
        self.assertGreater(attempt.evaluation_lease_until, timezone.now())

    def test_worker_renews_a_live_claim_but_cannot_revive_an_expired_one(self):
        attempt = self._attempt()
        now = timezone.now()
        claim = {"evaluation_status": "processing", "evaluation_started_at": now - timedelta(seconds=20)}
        attempts = WritingSimulationAttempt.objects.filter(pk=attempt.pk)
        attempts.update(**claim, evaluation_lease_until=now + timedelta(seconds=25))
        with (
            patch.object(writing_simulation.timezone, "now", return_value=now),
            patch.object(writing_simulation.connections, "close_all"),
        ):
            finished = Mock()
            finished.wait.side_effect = [False, True]
            writing_simulation._renew_evaluation_lease({**claim, "pk": attempt.pk}, finished)
            attempt.refresh_from_db()
            self.assertEqual(attempt.evaluation_lease_until, now + writing_simulation.EVALUATION_LEASE)
            attempts.update(evaluation_lease_until=now)
            finished.wait.side_effect = [False, True]
            writing_simulation._renew_evaluation_lease({**claim, "pk": attempt.pk}, finished)
        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation_lease_until, now)

    def test_queued_work_cannot_switch_to_a_different_link(self):
        previous = self._link()
        old_link_id = previous.pk
        previous.delete()
        self._link()
        with patch.object(copilot_runtime, "report_transport") as transport:
            with self.assertRaisesMessage(evaluation.EvaluationError, "Reconnectez votre compte GitHub"):
                copilot_runtime.linked_report_transport(self.user.pk, "copilot-mai", old_link_id)
        transport.assert_not_called()

    def test_copilot_submission_scores_ee2_and_ee3_and_saves_proposals_per_model(self):
        link = self._link()
        for number, body_count, position_count in ((2, 120, 0), (3, 40, 80)):
            with self.subTest(task=number):
                task = factories.make_task(self.task.part, f"tache-{number}")
                body = " ".join(["lecture"] * body_count)
                position = " ".join(["avis"] * position_count)
                snapshot = {"prompt": "Répondez à la consigne."}
                if number == 3:
                    snapshot["documents"] = ["La lecture détend.", "La lecture enrichit le vocabulaire."]
                attempt = WritingSimulationAttempt.objects.create(
                    user=self.user, task=task, deadline_at=timezone.now(), status="active", snapshot=snapshot,
                )
                page = reverse(f"study:ee{number}_simulation_attempt", args=[attempt.pk])
                endpoint = reverse(f"study:ee{number}_simulation_evaluate", args=[attempt.pk])
                editor = self.client.get(page)
                self.assertEqual(editor.context["auto_evaluation"], "copilot-mai")
                with patch.object(writing_simulation.threading, "Thread") as thread, self.captureOnCommitCallbacks(execute=True):
                    submitted = self.client.post(page, {
                        "action": "submit", "body": body, "position_body": position,
                        "draft_revision": editor.context["draft_revision"],
                        "evaluation_consent": "copilot-mai", "evaluation_link": str(link.pk),
                    })
                self.assertRedirects(submitted, page, fetch_redirect_response=False)
                thread.assert_called_once()
                self.assertEqual(thread.call_args.kwargs["kwargs"], {"copilot_link_id": link.pk})
                options = self.client.get(page).context
                self.assertEqual(options["evaluation_providers"], list(copilot_runtime.LABELS.items()))
                self.assertEqual(options["evaluation_provider"], "copilot-mai")
                report = {
                    "score": 12, "scoreRange": {"min": 11, "max": 13}, "gradeEvidenceIds": [],
                    "taskCompliance": [{"item": "But", "status": "Met", "evidenceId": "E1", "evidence": "Réponse présente."}],
                    "criteria": {
                        key: {"rating": "Adequate", "evidenceIds": ["E1"], "evidence": "Réponse claire."}
                        for key in ("linguistic", "pragmatic", "sociolinguistic")
                    },
                    "improvedResponse": body, "improvedPosition": position, "corrections": [], "relevance": [],
                }
                with (
                    patch.object(copilot_runtime, "report_transport", return_value=Mock(return_value=report)) as runtime,
                    patch.object(writing_simulation, "close_old_connections"),
                ):
                    worker = thread.call_args.kwargs
                    worker["target"](*worker["args"], **worker["kwargs"])
                runtime.assert_called_once_with("ghu_fixture", "mai-code-2-flash")
                runtime.return_value.assert_called_once()
                provider, _, packet, schema = runtime.return_value.call_args.args
                self.assertEqual(provider, "copilot-mai")
                if number == 3:
                    self.assertEqual(packet["documents"], snapshot["documents"])
                    self.assertEqual([section["text"] for section in packet["sections"].values()], [body, position])
                    self.assertIn("improvedPosition", schema["required"])
                else:
                    self.assertEqual(packet["response"], body)
                self.assertEqual(packet["subject"], snapshot["prompt"])
                query = {"provider": "copilot-mai"}
                with self.assertNumQueries(3):
                    ready = self.client.get(endpoint, query)
                self.assertEqual(ready.status_code, 200, ready.content)
                self.assertEqual(ready.json()["status"], "ready")
                self.assertEqual(ready.json()["report"]["score"], 12)
                self.assertEqual(ready.json()["report"]["proposalTarget"], "NCLC 7")
                parts = ["Mon exemple révisé."] + (["Mon avis révisé."] if position else [])
                edit = self.client.patch(endpoint, {**query, "parts": parts}, content_type="application/json")
                self.assertEqual(edit.status_code, 200, edit.content)
                self.assertEqual(edit.json()["proposalEdit"]["parts"], parts)
                self.assertEqual(self.client.get(endpoint, query).json()["proposalEdit"]["parts"], parts)

    def test_ee2_preserves_a_flat_groq_report_when_switching_to_copilot(self):
        self._link()
        task = factories.make_task(self.task.part, "tache-2")
        previous = {"score": 10}
        attempt = WritingSimulationAttempt.objects.create(
            user=self.user, task=task, deadline_at=timezone.now(), status="submitted",
            body="Mon texte.", snapshot={"prompt": "Racontez votre visite."},
            evaluation_status="ready", evaluation=previous,
        )
        endpoint = reverse("study:ee2_simulation_evaluate", args=[attempt.pk])
        consent = {"consent": True, "provider": "copilot-opus"}
        with patch.object(writing_simulation.threading, "Thread") as thread, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(endpoint, consent, content_type="application/json").status_code, 202)
        thread.assert_called_once()
        self.client.post(self.disconnect)
        self.assertEqual(self.client.get(endpoint, {"provider": "groq"}).json()["report"], previous)
        self.assertEqual(self.client.get(endpoint, {"provider": "copilot-opus"}).json()["status"], "processing")
        self.assertEqual(self.client.post(endpoint, consent, content_type="application/json").status_code, 409)

    @override_settings(GEMINI_API_KEY="fixture-voice", AI_PIN="fixture-pin")
    def test_copilot_oral_launch_grant_queues_mai_only_for_its_saved_attempt(self):
        link = self._link()
        part = factories.make_part("eo")
        saved_reports = []
        for number, route in ((2, "eo_tache_two_live"), (3, "eo_tache_three_live")):
            with self.subTest(task=number):
                factories.make_task(part, f"tache-{number}")
                page = self.client.get(reverse(f"study:{route}"))
                self.assertContains(page, 'data-auto-evaluation="copilot-mai"')
                self.assertEqual(page.context["evaluation_providers"], list(copilot_runtime.LABELS.items()))
                with patch.object(live_conversation, "_request_token", return_value="auth_tokens/fixture"):
                    launch = self.client.post(page.context["token_url"], {
                        "purpose": "attempt", "consent": True, "pin": "fixture-pin",
                        "reviewProvider": "copilot-mai", "reviewLink": str(link.pk),
                    }, content_type="application/json").json()
                    exchange = self.client.post(page.context["token_url"], {
                        "purpose": "exchange", "consent": True, "exchangeGrant": launch["exchangeGrant"],
                    }, content_type="application/json").json()
                opening = "Je préfère découvrir le quartier à pied parce que les petites rues sont calmes et agréables."
                rows = [{"speaker": "user", "text": opening}]
                transcript = [{"turnIndex": 0, "speaker": "user", "passages": [{"id": "E1", "text": opening}]}]
                if number == 2:
                    reply = "Notre visite se fait à pied."
                    question = "La visite passe-t-elle près du parc ?"
                    rows.extend([{"speaker": "model", "text": reply}, {"speaker": "user", "text": question}])
                    transcript.extend([
                        {"turnIndex": 1, "speaker": "model", "text": reply},
                        {"turnIndex": 2, "speaker": "user", "passages": [{"id": "E2", "text": question}]},
                    ])
                saved = self.client.post(page.context["save_url"], {
                    "elapsed": 1000, "rows": rows, "snapshotGrant": launch["snapshotGrant"],
                }, content_type="application/json")
                self.assertEqual(saved.status_code, 201)
                session = LiveSimulation.objects.get(pk=saved.json()["id"])
                other_session = LiveSimulation.objects.create(
                    user=self.user, subject_key=session.subject_key, rows=rows,
                    snapshot={"prompt": session.snapshot["prompt"]},
                )
                endpoint = page.context["evaluation_url"]
                consent = {
                    "consent": True, "provider": "copilot-mai", "rows": rows,
                    "simulation": str(session.pk), "reviewGrant": exchange["reviewGrant"],
                }
                with patch.object(oral_jobs, "wake"), self.captureOnCommitCallbacks(execute=True):
                    invalid = self.client.post(endpoint, {**consent, "simulation": str(other_session.pk)},
                                               content_type="application/json")
                    self.assertEqual(invalid.status_code, 403)
                    for _ in range(2):
                        self.assertEqual(self.client.post(endpoint, consent, content_type="application/json").status_code, 202)
                job, _ = oral_jobs._claim()
                self.assertEqual((job.simulation_id, job.copilot_link_id), (session.pk, link.pk))
                report = {
                    "reason": "Vous exprimez une préférence.", "criteria": {
                        key: {"points": 3, "evidenceId": "E2" if number == 2 and key == "coherence" else "E1",
                              "why": "Ce passage montre votre intention."}
                        for key in ("task", "coherence", "lexicon", "grammar")
                    },
                    "strengths": [], "corrections": [], "proposal": "" if number == 3 else [],
                    "next": "Donnez une raison à votre choix.",
                }
                with (
                    patch.object(copilot_runtime, "report_transport", return_value=Mock(return_value=report)) as runtime,
                    patch.object(oral_jobs.connections, "close_all"),
                ):
                    oral_jobs._finish(job, *oral_jobs._evaluate(job, oral_jobs._source(job)))
                runtime.assert_called_once_with("ghu_fixture", "mai-code-2-flash")
                runtime.return_value.assert_called_once()
                args = runtime.return_value.call_args
                self.assertEqual(args.kwargs["name"], f"eo{number}_bilan")
                self.assertEqual(args.args[2], {"consigne": session.snapshot["prompt"], "rows": transcript})
                query = {"simulation": str(session.pk), "provider": "copilot-mai"}
                ready = self.client.get(endpoint, query)
                self.assertEqual(ready.status_code, 200, ready.content)
                self.assertEqual((ready.json()["scoreStatus"], ready.json()["score"]), ("scored", 12))
                self.assertEqual(self.client.get(reverse(f"study:{route}"), {"simulation": session.pk}).context[
                    "evaluation_provider"
                ], "copilot-mai")
                self.assertFalse(OralEvaluationJob.objects.filter(simulation=other_session).exists())
                saved_reports.append((endpoint, query, ready.json()))
        self.client.post(self.disconnect)
        for endpoint, query, report in saved_reports:
            self.assertEqual(self.client.get(endpoint, query).json(), report)
        self.client.force_login(self.other)
        for endpoint, query, _ in saved_reports:
            self.assertEqual(self.client.get(endpoint, query).status_code, 404)

    @override_settings(GEMINI_API_KEY="fixture-voice", AI_PIN="fixture-pin")
    def test_oral_launch_with_a_stale_link_does_not_authorize_an_automatic_bilan(self):
        previous = self._link()
        old_link_id = previous.pk
        previous.delete()
        self._link(github_user_id=456)
        factories.make_task(factories.make_part("eo"), "tache-2")
        endpoint = reverse("study:eo_tache_two_live_token")
        with patch.object(live_conversation, "_request_token", return_value="auth_tokens/fixture"):
            launch = self.client.post(endpoint, {
                "purpose": "attempt", "consent": True, "pin": "fixture-pin",
                "reviewProvider": "copilot-mai", "reviewLink": str(old_link_id),
            }, content_type="application/json")
            self.assertEqual(launch.status_code, 200, launch.content)
            exchange = self.client.post(endpoint, {
                "purpose": "exchange", "consent": True, "exchangeGrant": launch.json()["exchangeGrant"],
            }, content_type="application/json")
        self.assertEqual(exchange.status_code, 200, exchange.content)
        self.assertNotIn("reviewGrant", exchange.json())

    @override_settings(AI_PIN="fixture-pin")
    def test_oral_manual_job_cannot_switch_links_after_queueing(self):
        link = self._link()
        factories.make_task(factories.make_part("eo"), "tache-2")
        session = LiveSimulation.objects.create(
            user=self.user, rows=[{"speaker": "user", "text": "Combien coûte le cours ?"}],
            snapshot={"prompt": "Renseignez-vous sur un cours."},
        )
        endpoint = reverse("study:eo_tache_two_live_evaluation")
        query = {"provider": "copilot-opus", "simulation": str(session.pk)}
        with patch.object(oral_jobs, "wake"), self.captureOnCommitCallbacks(execute=True):
            queued = self.client.post(endpoint, {**query, "consent": True, "pin": "fixture-pin", "rows": session.rows},
                                      content_type="application/json")
        self.assertEqual(queued.status_code, 202)
        self.client.post(self.disconnect)
        self._link(github_user_id=456)
        job, _ = oral_jobs._claim()
        self.assertEqual(job.copilot_link_id, link.pk)
        with patch.object(copilot_runtime, "report_transport") as runtime, patch.object(oral_jobs.connections, "close_all"):
            oral_jobs._finish(job, *oral_jobs._evaluate(job, oral_jobs._source(job)))
        runtime.assert_not_called()
        failed = self.client.get(endpoint, query)
        self.assertEqual(failed.status_code, 403)
        self.assertIn("Reconnectez votre compte GitHub", failed.json()["error"])

    def test_oral_copilot_claim_expires_without_a_second_execution(self):
        link = self._link()
        factories.make_task(factories.make_part("eo"), "tache-2")
        session = LiveSimulation.objects.create(
            user=self.user, rows=[{"speaker": "user", "text": "Combien coûte le cours ?"}],
            snapshot={"prompt": "Renseignez-vous sur un cours."},
        )
        session.evaluation_jobs.create(provider="copilot-mai", copilot_link_id=link.pk)
        started, _ = oral_jobs._claim()
        OralEvaluationJob.objects.filter(pk=started.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
        recovered, _ = oral_jobs._claim()
        self.assertIsNone(recovered)
        oral_jobs._finish(started, {"score": 12, "scoreStatus": "scored"}, 200)
        failed = self.client.get(reverse("study:eo_tache_two_live_evaluation"), {
            "simulation": str(session.pk), "provider": "copilot-mai",
        })
        self.assertEqual(failed.status_code, 504, failed.content)
        self.assertEqual(failed.json()["status"], "unavailable")

    def test_revoked_link_does_not_hide_the_failed_bilan_status(self):
        link = self._link()
        attempt = self._attempt()
        endpoint = reverse("study:ee1_simulation_evaluate", args=[attempt.pk])
        query = {"provider": "copilot-mai"}
        consent = {"consent": True, **query}
        with patch.object(writing_simulation.threading, "Thread") as thread, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(endpoint, consent, content_type="application/json").status_code, 202)
        self.assertEqual(self.client.get(endpoint, query).json()["status"], "processing")

        GitHubCopilotConnection.objects.filter(pk=link.pk).update(access_expires_at=timezone.now() - timedelta(seconds=1))
        queued = thread.call_args.kwargs
        revoked = httpx.Response(200, json={"error": "bad_refresh_token"})
        with (
            patch.object(github_copilot.httpx, "post", return_value=revoked),
            patch.object(copilot_runtime, "report_transport") as transport,
            patch.object(writing_simulation, "close_old_connections"),
        ):
            writing_simulation.run_evaluation(*queued["args"], **queued["kwargs"])
        transport.assert_not_called()
        self.assertFalse(GitHubCopilotConnection.objects.filter(pk=link.pk).exists())

        status = self.client.get(endpoint, query)
        self.assertEqual(status.status_code, 200, status.content)
        self.assertEqual(status.json(), {
            "status": "unavailable",
            "report": None,
            "error": "Reconnectez votre compte GitHub pour utiliser Copilot.",
            "retryable": True,
        })
        self.assertEqual(self.client.get(endpoint).json(), status.json())
        page = self.client.get(reverse("study:ee1_simulation_attempt", args=[attempt.pk]))
        self.assertContains(page, 'data-evaluation-provider="copilot-mai"')
        self.assertContains(page, "Choisir le modèle d’évaluation")
        self.assertContains(page, "Évaluer avec Groq")
        self.assertNotContains(page, "Évaluer avec MAI")
        for provider in ("copilot-opus", "not-a-model"):
            self.assertEqual(self.client.get(endpoint, {"provider": provider}).status_code, 400)
        self.assertEqual(self.client.post(endpoint, consent, content_type="application/json").status_code, 409)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(endpoint, query).status_code, 404)
