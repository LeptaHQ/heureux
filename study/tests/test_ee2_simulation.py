from datetime import timedelta
from unittest.mock import ANY, patch

from django.test import TestCase, override_settings
from django.urls import reverse

from study.models import WritingSimulationAttempt, WritingSimulationAttemptStatus
from study.views import writing_simulation

from . import factories


class EE2SimulationTests(TestCase):
    def setUp(self):
        self.part = factories.make_part("ee")
        self.task = factories.make_task(self.part, "tache-2")
        self.sujet = factories.make_writing_sujet(
            self.task,
            slug="voyage",
            category="voyages",
            category_label="Voyages",
            prompt="Racontez une expérience de voyage qui vous a particulièrement marqué.",
            order=1,
        )
        self.user = factories.make_user("ee2-simulation-owner")
        self.client.force_login(self.user)

    @override_settings(EE2_SIMULATION_MINUTES=18)
    def test_setup_uses_shared_shell_and_ee2_constraints(self):
        response = self.client.get(reverse("study:ee2_simulation"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Studio écrit · EE Tâche 2")
        self.assertContains(response, "120–150 mots")
        self.assertContains(response, "18 min")
        self.assertContains(response, 'name="sujet_id"')

    def test_subject_picker_uses_the_shared_subject_table(self):
        picker = reverse("study:ee2_subject_picker")
        response = self.client.get(picker)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.sujet.prompt)
        self.assertContains(
            response,
            f'href="{reverse("study:ee2_simulation")}?sujet_id={self.sujet.pk}"',
        )
        self.assertContains(response, 'data-writing-sujet-completion-form')
        self.assertContains(response, f'aria-label="À refaire : {self.sujet.prompt}"')
        self.assertContains(response, '<option value="retry">À refaire</option>', html=True)
        self.assertNotContains(response, ">Choisir</a>")
        self.assertNotContains(response, ">Choisir</button>")
        self.assertNotContains(response, ">Action<")

        endpoint = reverse("study:ee2_subject_retry", args=[self.sujet.pk], query={"etat": "retry", "deduplicate": "0"})
        return_url = f"{picker}?etat=retry&deduplicate=0#sujet-{self.sujet.pk}"
        self.assertEqual(self.client.post(endpoint, {"field": "done", "value": "1"}).status_code, 400)
        self.assertRedirects(self.client.post(endpoint, {"field": "retry", "value": "1"}), return_url)
        marked = self.client.get(return_url)
        self.assertContains(marked, 'class="subject-bookmark is-bookmarked"', count=1)
        self.assertEqual(marked.context["practiced_total"], 0)

    @override_settings(EE2_SIMULATION_MINUTES=9)
    def test_start_freezes_ee2_prompt_and_configured_duration(self):
        response = self.client.post(
            reverse("study:ee2_simulation_start"),
            {"sujet_id": str(self.sujet.pk)},
        )

        attempt = WritingSimulationAttempt.objects.get(user=self.user)
        self.assertRedirects(
            response,
            reverse("study:ee2_simulation_attempt", args=[attempt.pk]),
        )
        self.assertEqual(attempt.snapshot["word_min"], 120)
        self.assertEqual(attempt.snapshot["word_max"], 150)
        self.assertEqual(attempt.snapshot["simulation_minutes"], 9)
        self.assertEqual(
            attempt.deadline_at - attempt.started_at,
            timedelta(minutes=9),
        )
        setup = self.client.get(reverse("study:ee2_simulation"))
        self.assertContains(setup, reverse("study:ee2_simulation_attempt", args=[attempt.pk]))

    @override_settings(GROQ_API_KEY="fixture-groq-key")
    def test_submission_uses_ee2_word_range_and_starts_groq(self):
        self.client.post(
            reverse("study:ee2_simulation_start"),
            {"sujet_id": str(self.sujet.pk)},
        )
        attempt = WritingSimulationAttempt.objects.get(user=self.user)
        url = reverse("study:ee2_simulation_attempt", args=[attempt.pk])
        revision = self.client.get(url).context["draft_revision"]
        response = self.client.post(
            url,
            {"action": "submit", "body": " ".join(["Bonjour"] * 119), "draft_revision": revision},
        )

        self.assertEqual(response.status_code, 400)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, WritingSimulationAttemptStatus.ACTIVE)
        self.assertContains(response, "entre 120 et 150 mots", status_code=400)

        with patch("study.views.writing_simulation.threading.Thread") as thread, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                url,
                {"action": "submit", "body": " ".join(["Bonjour"] * 120), "evaluation_consent": "groq", "draft_revision": revision},
            )
        self.assertRedirects(
            response,
            reverse("study:ee2_simulation_attempt", args=[attempt.pk]),
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, WritingSimulationAttemptStatus.SUBMITTED)
        self.assertEqual(attempt.word_count, 120)
        self.assertEqual(attempt.evaluation_status, "processing")
        self.assertEqual(thread.call_args.kwargs["args"], (attempt.pk, attempt.evaluation_started_at, writing_simulation.SPECS[2], "groq"))

    def test_timer_can_be_updated_from_the_active_attempt(self):
        self.client.post(
            reverse("study:ee2_simulation_start"),
            {"sujet_id": str(self.sujet.pk)},
        )
        attempt = WritingSimulationAttempt.objects.get(user=self.user)
        now = attempt.started_at + timedelta(minutes=1)
        url = reverse("study:ee2_simulation_attempt", args=[attempt.pk])
        revision = self.client.get(url).context["draft_revision"]

        with patch("study.views.writing_simulation.timezone.now", return_value=now):
            response = self.client.post(
                reverse("study:ee2_simulation_timer", args=[attempt.pk]),
                {"timer_minutes": "7", "timer_seconds": "30", "body": "Mon brouillon en cours.", "draft_revision": revision},
            )

        self.assertRedirects(
            response,
            reverse("study:ee2_simulation_attempt", args=[attempt.pk]),
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.deadline_at, now + timedelta(minutes=7, seconds=30))
        self.assertEqual(attempt.body, "Mon brouillon en cours.")
        editor = self.client.get(
            reverse("study:ee2_simulation_attempt", args=[attempt.pk])
        )
        self.assertContains(editor, 'title="Modifier le temps"')
        self.assertContains(editor, 'class="ui-icon" data-icon="clock"')
        self.assertNotContains(editor, "data-writing-word-guidance")

    def test_stale_timer_keeps_the_saved_draft_and_the_other_tabs_text(self):
        self.client.post(reverse("study:ee2_simulation_start"), {"sujet_id": self.sujet.pk})
        attempt = WritingSimulationAttempt.objects.get(user=self.user)
        url = reverse("study:ee2_simulation_attempt", args=[attempt.pk])
        timer = reverse("study:ee2_simulation_timer", args=[attempt.pk])
        old_revision = self.client.get(url).context["draft_revision"]
        newest, stale = "Mon brouillon déjà enregistré.", "Mes changements dans un autre onglet."
        self.assertRedirects(self.client.post(url, {
            "action": "save", "body": newest, "draft_revision": old_revision,
        }), url + "?saved=1")

        rejected = self.client.post(timer, {
            "timer_minutes": "7", "timer_seconds": "30", "body": stale, "draft_revision": old_revision,
        })
        self.assertContains(rejected, stale, status_code=409)
        self.assertContains(rejected, "Recharger le brouillon enregistré", status_code=409)
        self.assertNotContains(rejected, newest, status_code=409)
        deadline = attempt.deadline_at
        attempt.refresh_from_db()
        self.assertEqual((attempt.body, attempt.deadline_at), (newest, deadline))
        self.assertContains(self.client.get(url), newest)

    def test_timer_rejects_invalid_seconds(self):
        self.client.post(
            reverse("study:ee2_simulation_start"),
            {"sujet_id": str(self.sujet.pk)},
        )
        attempt = WritingSimulationAttempt.objects.get(user=self.user)

        response = self.client.post(
            reverse("study:ee2_simulation_timer", args=[attempt.pk]),
            {"timer_minutes": "7", "timer_seconds": "60"},
        )

        self.assertEqual(response.status_code, 400)

    def test_attempt_cannot_be_opened_or_evaluated_under_another_task(self):
        self.client.post(reverse("study:ee2_simulation_start"), {"sujet_id": self.sujet.pk})
        attempt = WritingSimulationAttempt.objects.get(user=self.user)
        url = reverse("study:ee2_simulation_attempt", args=[attempt.pk])
        self.client.post(url, {
            "action": "submit", "body": " ".join(["Bonjour"] * 120),
            "draft_revision": self.client.get(url).context["draft_revision"],
        })
        self.assertContains(self.client.get(url), ">Bilan</p>")
        self.assertEqual(
            self.client.get(reverse("study:ee1_simulation_attempt", args=[attempt.pk])).status_code, 404,
        )
        self.assertEqual(self.client.post(
            reverse("study:ee1_simulation_evaluate", args=[attempt.pk]),
            data={"consent": True}, content_type="application/json",
        ).status_code, 404)

    @override_settings(GROQ_API_KEY="", CLOUDFLARE_WORKERS_API_KEY="fixture-workers",
                       CLOUDFLARE_ACCOUNT_ID="0123456789abcdef" * 2)
    def test_missing_ee2_grader_does_not_offer_or_start_a_bilan(self):
        self.client.post(reverse("study:ee2_simulation_start"), {"sujet_id": self.sujet.pk})
        attempt = WritingSimulationAttempt.objects.get(user=self.user)
        url = reverse("study:ee2_simulation_attempt", args=[attempt.pk])
        page = self.client.get(url)
        self.assertNotContains(page, 'name="evaluation_consent"')
        self.assertRedirects(self.client.post(url, {
            "action": "submit", "body": " ".join(["Bonjour"] * 120), "draft_revision": page.context["draft_revision"],
        }), url)
        self.assertContains(self.client.get(url), "aucun modèle d’évaluation n’est configuré")
        endpoint = reverse("study:ee2_simulation_evaluate", args=[attempt.pk])
        with patch("study.views.writing_simulation.threading.Thread") as thread, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self.client.post(endpoint, {"consent": True}, content_type="application/json").status_code, 409)
        thread.assert_not_called()

    def test_evaluation_worker_uses_ee2_evaluator(self):
        self.client.post(
            reverse("study:ee2_simulation_start"),
            {"sujet_id": str(self.sujet.pk)},
        )
        attempt = WritingSimulationAttempt.objects.get(user=self.user)
        attempt.body = " ".join(["Bonjour"] * 120)
        attempt.word_count = 120
        attempt.status = WritingSimulationAttemptStatus.SUBMITTED
        started_at = attempt.started_at
        attempt.evaluation_status = "processing"
        attempt.evaluation_started_at = started_at
        attempt.save(
            update_fields=[
                "body",
                "word_count",
                "status",
                "evaluation_status",
                "evaluation_started_at",
            ]
        )

        with patch(
            "study.simulation.writing_evaluation.score",
            return_value={"cefr": "B1", "score": 6},
        ) as score:
            writing_simulation.run_evaluation(attempt.pk, started_at, writing_simulation.SPECS[2])

        score.assert_called_once_with(
            task_number=2,
            subject=self.sujet.prompt,
            response=attempt.body,
            word_count=120,
            word_min=120,
            word_max=150,
            timings=ANY,
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation_status, "ready")
        self.assertEqual(attempt.evaluation, {"cefr": "B1", "score": 6})
