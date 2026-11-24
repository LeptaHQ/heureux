from datetime import timedelta
from unittest.mock import patch

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

    def test_setup_uses_shared_shell_and_ee2_constraints(self):
        response = self.client.get(reverse("study:ee2_simulation"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Studio écrit · EE Tâche 2")
        self.assertContains(response, "120 à 150 mots")
        self.assertContains(response, "20 minutes")
        self.assertContains(response, 'name="sujet_id"')

    def test_subject_picker_uses_the_shared_subject_table(self):
        response = self.client.get(reverse("study:ee2_subject_picker"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.sujet.prompt)
        self.assertContains(
            response,
            f'href="{reverse("study:ee2_simulation")}?sujet_id={self.sujet.pk}"',
        )
        self.assertContains(response, 'data-writing-sujet-completion-form')
        self.assertNotContains(response, ">Choisir</a>")
        self.assertNotContains(response, ">Choisir</button>")
        self.assertNotContains(response, ">Action<")

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
        response = self.client.post(
            reverse("study:ee2_simulation_attempt", args=[attempt.pk]),
            {"action": "submit", "body": " ".join(["Bonjour"] * 119)},
        )

        self.assertEqual(response.status_code, 400)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, WritingSimulationAttemptStatus.ACTIVE)
        self.assertContains(response, "entre 120 et 150 mots", status_code=400)

        with patch("study.views.writing_simulation.threading.Thread") as thread, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("study:ee2_simulation_attempt", args=[attempt.pk]),
                {"action": "submit", "body": " ".join(["Bonjour"] * 120), "evaluation_consent": "groq"},
            )
        self.assertRedirects(
            response,
            reverse("study:ee2_simulation_attempt", args=[attempt.pk]),
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, WritingSimulationAttemptStatus.SUBMITTED)
        self.assertEqual(attempt.word_count, 120)
        self.assertEqual(attempt.evaluation_status, "processing")
        self.assertEqual(thread.call_args.kwargs["args"], (attempt.pk, attempt.evaluation_started_at, writing_simulation.SPECS[2], None))

    def test_timer_can_be_updated_from_the_active_attempt(self):
        self.client.post(
            reverse("study:ee2_simulation_start"),
            {"sujet_id": str(self.sujet.pk)},
        )
        attempt = WritingSimulationAttempt.objects.get(user=self.user)
        now = attempt.started_at + timedelta(minutes=1)

        with patch("study.views.writing_simulation.timezone.now", return_value=now):
            response = self.client.post(
                reverse("study:ee2_simulation_timer", args=[attempt.pk]),
                {"timer_minutes": "7", "timer_seconds": "30"},
            )

        self.assertRedirects(
            response,
            reverse("study:ee2_simulation_attempt", args=[attempt.pk]),
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.deadline_at, now + timedelta(minutes=7, seconds=30))
        editor = self.client.get(
            reverse("study:ee2_simulation_attempt", args=[attempt.pk])
        )
        self.assertContains(editor, 'title="Modifier le temps"')
        self.assertContains(editor, 'class="ui-icon" data-icon="clock"')
        self.assertNotContains(editor, "data-writing-word-guidance")

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
        self.client.post(url, {"action": "submit", "body": " ".join(["Bonjour"] * 120)})
        self.assertContains(self.client.get(url), "Bilan de votre session")
        self.assertEqual(
            self.client.get(reverse("study:ee1_simulation_attempt", args=[attempt.pk])).status_code, 404,
        )
        self.assertEqual(self.client.post(
            reverse("study:ee1_simulation_evaluate", args=[attempt.pk]),
            data={"consent": True}, content_type="application/json",
        ).status_code, 404)

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
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation_status, "ready")
        self.assertEqual(attempt.evaluation, {"cefr": "B1", "score": 6})
