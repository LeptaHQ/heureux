import base64
import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import httpx
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from study.accounts import github_copilot
from study.models import GitHubCopilotConnection, WritingSimulationAttempt, WritingSimulationEvaluationStatus
from study.simulation import copilot_runtime, evaluation
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

    def _link(self):
        config = github_copilot.configuration()
        fields = github_copilot._encrypted_fields(config, ("ghu_fixture", "ghr_fixture", 28800, 15897600))
        return GitHubCopilotConnection.objects.create(user=self.user, github_user_id=123, **fields)

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
        self.assertIn(f'name="attempt_id" value="{attempt.pk}"', menu)
        query = self._start_link(attempt_id=attempt.pk)
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

    def test_linked_bilan_selects_only_three_models_and_keeps_saved_reports_after_unlink(self):
        link = self._link()
        attempt = self._attempt(submitted=False)
        page = reverse("study:ee1_simulation_attempt", args=[attempt.pk])
        endpoint = reverse("study:ee1_simulation_evaluate", args=[attempt.pk])
        editor = self.client.get(page)
        self.assertNotContains(editor, 'name="evaluation_consent"')
        with patch.object(writing_simulation.threading, "Thread") as thread, self.captureOnCommitCallbacks(execute=True):
            self.assertRedirects(self.client.post(page, {
                "body": attempt.body, "action": "submit", "draft_revision": editor.context["draft_revision"],
                "evaluation_consent": "groq",
            }), page, fetch_redirect_response=False)
            thread.assert_not_called()
            result = self.client.get(page)
            self.assertEqual(result.context["evaluation_providers"], list(copilot_runtime.LABELS.items()))
            self.assertEqual(result.context["evaluation_provider"], "copilot-mai")
            self.assertContains(result, "utilise vos crédits")
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
        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation_status, WritingSimulationEvaluationStatus.READY)
        self.client.post(self.disconnect)
        self.assertFalse(GitHubCopilotConnection.objects.exists())
        self.assertEqual(self.client.get(endpoint, {"provider": "copilot-astra"}).json()["report"], report)
        self.assertEqual(self.client.post(endpoint, payload, content_type="application/json").json()["report"], report)
        self.assertEqual(self.client.post(endpoint, {
            "consent": True, "provider": "copilot-opus",
        }, content_type="application/json").status_code, 409)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(endpoint, {"provider": "copilot-astra"}).status_code, 404)

    def test_queued_work_cannot_switch_to_a_different_link(self):
        previous = self._link()
        old_link_id = previous.pk
        previous.delete()
        self._link()
        with patch.object(copilot_runtime, "report_transport") as transport:
            with self.assertRaisesMessage(evaluation.EvaluationError, "Reconnectez votre compte GitHub"):
                writing_simulation._copilot_transport(self.user.pk, "copilot-mai", old_link_id)
        transport.assert_not_called()
