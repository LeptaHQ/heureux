from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from study.models import (
    WritingSimulationAttempt,
    WritingSimulationAttemptStatus,
    WritingSimulationEvaluationStatus,
)

from . import factories
from study.expression.ee.tache_1 import evaluation
from study.views import ee1_simulation


class EE1SimulationTests(TestCase):
    def setUp(self):
        self.part = factories.make_part("ee")
        self.task = factories.make_task(self.part, "tache-1")
        self.sujet = factories.make_writing_sujet(
            self.task,
            slug="invitation",
            prompt="Invitez votre amie à une fête et donnez-lui les informations utiles.",
            order=1,
        )
        self.other_sujet = factories.make_writing_sujet(
            self.task,
            slug="sortie",
            category="sorties",
            category_label="Sorties",
            prompt="Proposez une sortie à votre collègue.",
            order=2,
        )
        self.owner = factories.make_user("ee1-simulation-owner")
        self.other = factories.make_user("ee1-simulation-other")
        self.client.force_login(self.owner)

    def _setup_url(self):
        return reverse("study:ee1_simulation")

    def _start_url(self):
        return reverse("study:ee1_simulation_start")

    def _attempt_url(self, attempt):
        return reverse("study:ee1_simulation_attempt", args=[attempt.pk])

    def test_setup_lists_subjects_and_is_in_simulation_area(self):
        response = self.client.get(self._setup_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_nav_area"], "simulation")
        self.assertContains(response, self.sujet.prompt)
        self.assertContains(response, "60 à 120 mots")
        self.assertContains(response, "20 minutes")

    def test_subject_page_links_to_the_same_subject_in_simulation(self):
        response = self.client.get(
            reverse("study:writing_sujet_detail", args=["ee", "tache-1", self.sujet.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"?sujet_id={self.sujet.pk}")
        self.assertContains(response, "Lancer la simulation écrite")

    def test_start_freezes_selected_prompt_and_keeps_attempt_private(self):
        response = self.client.post(
            self._start_url(),
            {"sujet_id": str(self.sujet.pk)},
        )

        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        self.assertRedirects(response, self._attempt_url(attempt))
        self.assertEqual(attempt.snapshot["prompt"], self.sujet.prompt)
        self.assertEqual(attempt.snapshot["word_min"], 60)
        self.assertEqual(attempt.status, WritingSimulationAttemptStatus.ACTIVE)

        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self._attempt_url(attempt)).status_code, 404)

    def test_attempt_editor_disables_correction_and_exposes_french_character_tools(self):
        self.client.post(self._start_url(), {"sujet_id": str(self.sujet.pk)})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        response = self.client.get(self._attempt_url(attempt))

        self.assertContains(response, 'spellcheck="false"')
        self.assertContains(response, 'autocorrect="off"')
        self.assertContains(response, 'data-gramm="false"')
        self.assertContains(response, "Caractères français")
        self.assertContains(response, 'data-ee1-character="é"')
        self.assertContains(response, 'data-writing-word-count-display')

    def test_submission_requires_word_limit_then_shows_private_bilan(self):
        self.client.post(self._start_url(), {"sujet_id": str(self.sujet.pk)})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        response = self.client.post(
            self._attempt_url(attempt),
            {"action": "submit", "body": "Trop court."},
        )

        self.assertEqual(response.status_code, 400)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, WritingSimulationAttemptStatus.ACTIVE)
        self.assertContains(response, "entre 60 et 120 mots", status_code=400)

        body = " ".join(["Bonjour"] * 60)
        response = self.client.post(
            self._attempt_url(attempt),
            {"action": "submit", "body": body},
        )

        self.assertRedirects(response, self._attempt_url(attempt))
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, WritingSimulationAttemptStatus.SUBMITTED)
        self.assertEqual(attempt.word_count, 60)
        result = self.client.get(self._attempt_url(attempt))
        self.assertContains(result, "Bilan de votre session")
        self.assertContains(result, "Votre message a été remis dans le temps.")
        self.assertContains(result, "60 / 60–120")
        exported = self.client.get(reverse("study:export_account")).json()
        self.assertEqual(len(exported["ee1_simulation_attempts"]), 1)
        self.assertEqual(
            exported["ee1_simulation_attempts"][0]["id"],
            str(attempt.pk),
        )

    def test_save_draft_and_expiry_preserve_the_written_text(self):
        self.client.post(self._start_url(), {"sujet_id": ""})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        draft = "Un brouillon encore incomplet."
        response = self.client.post(
            self._attempt_url(attempt),
            {"action": "save", "body": draft},
        )
        self.assertRedirects(response, self._attempt_url(attempt) + "?saved=1")

        attempt.refresh_from_db()
        attempt.deadline_at = timezone.now() - timedelta(seconds=1)
        attempt.save(update_fields=["deadline_at"])
        response = self.client.post(
            self._attempt_url(attempt),
            {"action": "submit", "body": draft},
        )

        self.assertRedirects(response, self._attempt_url(attempt))
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, WritingSimulationAttemptStatus.EXPIRED)
        self.assertEqual(attempt.body, draft)
        self.assertContains(
            self.client.get(self._attempt_url(attempt)),
            "Le temps est écoulé",
        )

    def test_evaluation_requires_explicit_consent_and_claims_once(self):
        self.client.post(self._start_url(), {"sujet_id": str(self.sujet.pk)})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        body = " ".join(["Bonjour"] * 60)
        self.client.post(self._attempt_url(attempt), {"action": "submit", "body": body})

        evaluation_url = reverse("study:ee1_simulation_evaluate", args=[attempt.pk])
        self.assertEqual(self.client.post(evaluation_url, content_type="application/json", data="{}").status_code, 400)
        with patch("study.views.ee1_simulation.threading.Thread") as thread:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    evaluation_url,
                    data='{"consent": true}',
                    content_type="application/json",
                )
        self.assertEqual(response.status_code, 202)
        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation_status, "processing")
        thread.assert_called_once()

    def test_evaluation_worker_persists_ready_report_only_for_its_claim(self):
        self.client.post(self._start_url(), {"sujet_id": str(self.sujet.pk)})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        attempt.body = " ".join(["Bonjour"] * 60)
        attempt.status = WritingSimulationAttemptStatus.SUBMITTED
        attempt.word_count = 60
        started_at = timezone.now()
        attempt.evaluation_status = WritingSimulationEvaluationStatus.PROCESSING
        attempt.evaluation_started_at = started_at
        attempt.save(
            update_fields=[
                "body",
                "status",
                "word_count",
                "evaluation_status",
                "evaluation_started_at",
            ]
        )

        with patch(
            "study.views.ee1_simulation.evaluation.score",
            return_value={"cefr": "B2", "score": 12},
        ):
            ee1_simulation._run_evaluation(attempt.pk, started_at)

        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation_status, WritingSimulationEvaluationStatus.READY)
        self.assertEqual(attempt.evaluation, {"cefr": "B2", "score": 12})
        self.assertEqual(attempt.evaluation_error, "")
        self.assertIsNotNone(attempt.evaluated_at)

        newer_started_at = started_at + timedelta(seconds=1)
        attempt.evaluation_status = WritingSimulationEvaluationStatus.PROCESSING
        attempt.evaluation_started_at = newer_started_at
        attempt.evaluation = {"new": True}
        attempt.save(update_fields=["evaluation_status", "evaluation_started_at", "evaluation"])
        with patch(
            "study.views.ee1_simulation.evaluation.score",
            return_value={"old": True},
        ):
            ee1_simulation._run_evaluation(attempt.pk, started_at)
        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation_status, WritingSimulationEvaluationStatus.PROCESSING)
        self.assertEqual(attempt.evaluation, {"new": True})

    def test_evaluation_grounding_rejects_a_score_outside_its_cefr_band(self):
        report = {
            "verdict": "Réponse claire.",
            "cefr": "B2",
            "score": 12,
            "scoreRange": {"min": 10, "max": 13},
            "nclc": "NCLC 8",
            "nclcRange": "NCLC 7 à NCLC 8",
            "confidence": "Medium",
            "uncertainty": "Une seule tâche ne suffit pas.",
            "taskCompliance": [{"item": "But", "status": "Met", "quote": "Bonjour", "evidence": "Le message est adressé."}],
            "criteria": {
                key: {"rating": "Adequate", "quotes": ["Bonjour"], "evidence": "Le passage est exploitable."}
                for key in ("linguistic", "pragmatic", "sociolinguistic")
            },
            "gradeRationale": "Le texte montre un contrôle fonctionnel.",
            "gradeEvidence": ["Bonjour"],
            "strengths": [{"quote": "Bonjour", "text": "Ouverture claire."}],
            "corrections": [],
            "relevance": [],
            "upgrades": [],
            "improvedResponse": "",
            "improvedWordCount": 0,
            "priorities": ["Préciser le but.", "Relier les idées.", "Relire les accords."],
        }
        grounded = evaluation.ground(
            report,
            subject=self.sujet.prompt,
            response="Bonjour",
            word_count=1,
        )
        self.assertEqual(grounded["nclc"], "NCLC 8")
        report["score"] = 14
        with self.assertRaises(ValueError):
            evaluation.ground(
                report,
                subject=self.sujet.prompt,
                response="Bonjour",
                word_count=1,
            )
