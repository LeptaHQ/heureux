from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from study.catalogue import registry as catalogue
from study.models import WritingSimulationAttempt, WritingSimulationAttemptStatus, WritingSimulationEvaluationStatus
from study.simulation import evaluation, writing_evaluation

from . import factories


class EE3SimulationTests(TestCase):
    def setUp(self):
        task = factories.make_task(factories.make_part("ee"), "tache-3")
        theme = factories.make_theme("debats-ee3", task=task)
        sources = catalogue.ee_tache_three_sources_by_key()
        self.valid = next(source for _, source in sources.values() if source.has_usable_documents)
        self.invalid = next(source for _, source in sources.values() if not source.has_usable_documents)
        self.prompt, self.invalid_prompt = [
            self.make_prompt(theme, source) for source in (self.valid, self.invalid)
        ]
        self.user = factories.make_user("ee3-simulation-owner")
        self.client.force_login(self.user)
        self.start_url = reverse("study:ee3_simulation_start")

    @staticmethod
    def make_prompt(theme, source):
        prompt = factories.make_response(theme=theme).prompts.get()
        prompt.content_key = source.content_key
        prompt.text = source.sujet
        prompt.save(update_fields=["content_key", "text"])
        return prompt

    def start(self):
        self.client.post(self.start_url, {"sujet_id": self.prompt.pk})
        attempt = WritingSimulationAttempt.objects.get(user=self.user)
        return attempt, reverse("study:ee3_simulation_attempt", args=[attempt.pk])

    @override_settings(EE3_SIMULATION_MINUTES=30, GROQ_API_KEY="fixture-groq-key")
    def test_selected_sources_and_each_section_are_frozen_submitted_and_graded(self):
        picker = self.client.get(reverse("study:ee3_subject_picker"))
        self.assertTemplateUsed(picker, "study/simulation/subject_picker_table.html")
        self.assertContains(picker, reverse("study:ee3_simulation", query={"sujet_id": self.prompt.pk}))
        self.assertNotContains(picker, reverse("study:ee3_simulation", query={"sujet_id": self.invalid_prompt.pk}))
        self.assertEqual(self.client.post(self.start_url, {"sujet_id": self.invalid_prompt.pk}).status_code, 404)
        attempt, url = self.start()
        self.assertEqual(attempt.deadline_at - attempt.started_at, timedelta(minutes=30))
        self.assertEqual(attempt.prompt_id, self.prompt.pk)
        self.assertEqual(attempt.snapshot["documents"], [self.valid.document1, self.valid.document2])
        self.prompt.text = "Nouveau sujet"
        self.prompt.save(update_fields=["text"])
        page = self.client.get(url)
        self.assertTemplateUsed(page, "study/simulation/writing_simulation_attempt.html")
        self.assertContains(page, self.valid.sujet)
        self.assertContains(page, "Document 1")
        self.assertContains(page, "Document 2")
        self.assertContains(page, "40–60")
        self.assertContains(page, "80–120")
        self.assertNotContains(page, "Nouveau sujet")
        revision = page.context["draft_revision"]

        synthesis = " ".join(["synthèse"] * 40)
        position = " ".join(["opinion"] * 80)
        for data, error in (
            ({"body": synthesis.rsplit(maxsplit=1)[0], "position_body": position + " opinion"}, "entre 40 et 60 mots"),
            ({"body": synthesis + " synthèse", "position_body": position.rsplit(maxsplit=1)[0]}, "entre 80 et 120 mots"),
        ):
            rejected = self.client.post(url, {"action": "submit", "draft_revision": revision, **data})
            self.assertContains(rejected, error, status_code=400)

        with patch("study.views.writing_simulation.threading.Thread") as thread, self.captureOnCommitCallbacks(execute=True):
            submitted = self.client.post(url, {
                "action": "submit", "body": synthesis, "position_body": position, "evaluation_consent": "groq",
                "draft_revision": revision,
            })
        self.assertRedirects(submitted, url)
        attempt.refresh_from_db()
        self.assertEqual((attempt.body, attempt.position_body, attempt.word_count), (synthesis, position, 120))
        self.assertEqual(attempt.evaluation_status, WritingSimulationEvaluationStatus.PROCESSING)
        with patch.object(writing_evaluation, "score", return_value={"score": 12}) as score:
            worker = thread.call_args.kwargs
            worker["target"](*worker["args"])
        score.assert_called_once_with(
            task_number=3, subject=self.valid.sujet, response=synthesis, position=position,
            documents=[self.valid.document1, self.valid.document2], word_count=120, word_min=120, word_max=180,
        )
        result = self.client.get(url)
        self.assertContains(result, position)
        self.assertContains(result, self.valid.sujet)
        self.assertContains(result, "Dans une première partie de 40 à 60 mots")
        self.assertEqual(result.context["session_subject_nav"]["total"], 1)
        self.assertEqual(self.client.get(reverse("study:export_account")).json()["writing_simulation_attempts"][0]["position_body"], position)

    @override_settings(GROQ_API_KEY="fixture-groq-key")
    def test_overtime_saves_both_sections_without_automatically_grading(self):
        attempt, url = self.start()
        WritingSimulationAttempt.objects.filter(pk=attempt.pk).update(deadline_at=timezone.now() - timedelta(seconds=1))
        revision = self.client.get(url).context["draft_revision"]
        with patch("study.views.writing_simulation.threading.Thread") as thread, self.captureOnCommitCallbacks(execute=True):
            self.assertRedirects(self.client.post(url, {
                "action": "save", "body": "Le premier document oppose deux idées.",
                "position_body": "Je défends cette idée.",
                "evaluation_consent": "groq",
                "draft_revision": revision,
            }), url + "?saved=1")
        thread.assert_not_called()
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, WritingSimulationAttemptStatus.ACTIVE)
        self.assertEqual(attempt.body, "Le premier document oppose deux idées.")
        self.assertEqual(attempt.position_body, "Je défends cette idée.")
        timer = reverse("study:ee3_simulation_timer", args=[attempt.pk])
        self.assertRedirects(self.client.post(timer, {"timer_minutes": "1", "timer_seconds": "30"}), url)
        editor = self.client.get(url)
        self.assertGreater(editor.context["remaining_seconds"], 0)
        self.assertContains(editor, attempt.position_body)

    def test_history_is_specific_to_the_selected_comparison_prompt(self):
        attempt, _ = self.start()
        other_source = next(
            source for _, source in catalogue.ee_tache_three_sources_by_key().values()
            if source.has_usable_documents and source.content_key != self.prompt.content_key
        )
        other = self.make_prompt(self.prompt.theme, other_source)
        self.client.post(self.start_url, {"sujet_id": other.pk})
        page = self.client.get(reverse("study:ee3_simulation"), {"sujet_id": self.prompt.pk})
        self.assertEqual([item["id"] for item in page.context["saved_sessions"]], [attempt.pk])
        for _ in range(8):
            self.client.post(self.start_url, {"sujet_id": self.prompt.pk})
        query = {"sujet_id": self.prompt.pk, "seances": 2}
        older_url = reverse("study:ee3_simulation", query=query)
        older = self.client.get(older_url)
        self.assertEqual([item["id"] for item in older.context["saved_sessions"]], [attempt.pk])
        delete = reverse("study:ee3_simulation_delete", query=query)
        self.assertEqual(older.context["delete_url"], delete)
        self.assertRedirects(self.client.post(delete, {"simulation": attempt.pk}), older_url)

    def test_grading_cannot_cite_documents_and_checks_both_proposal_lengths(self):
        synthesis = "Les deux auteurs comparent les avantages de la lecture."
        position = "Je préfère lire un livre dans le train."
        documents = ("Une affirmation réservée au premier document.", "Une autre opinion figure dans le second.")
        report = {
            "score": 12, "scoreRange": {"min": 11, "max": 13},
            "gradeEvidenceIds": ["E1", "E2"],
            "taskCompliance": [{"item": "Neutralité", "status": "Met", "evidenceId": "E1", "evidence": "Neutre."}],
            "criteria": {
                key: {"rating": "Adequate", "evidenceIds": ["E1", "E2"], "evidence": "Clair."}
                for key in ("linguistic", "pragmatic", "sociolinguistic")
            },
            "corrections": [{
                "before": documents[0], "after": "Une phrase modifiée.",
                "type": "Style", "why": "Ce passage n’appartient pas à la réponse.",
            }],
            "improvedResponse": " ".join(["comparaison"] * 39),
            "improvedPosition": " ".join(["argument"] * 81),
        }
        inputs = dict(task_number=3, subject="La lecture", response=synthesis, position=position,
                      documents=documents, word_count=17, word_min=120, word_max=180)
        with patch.object(evaluation, "request_report", return_value=report) as request:
            result = writing_evaluation.score(**inputs)
            instruction, packet, schema = request.call_args.args
            self.assertIn("assess fidelity to document 1 and document 2 separately", instruction)
            self.assertEqual(packet["documents"], list(documents))
            self.assertEqual(packet["sections"]["synthesis"]["passages"], [{"id": "E1", "text": synthesis}])
            self.assertEqual(packet["sections"]["position"]["passages"], [{"id": "E2", "text": position}])
            self.assertIn("improvedPosition", schema["required"])
            self.assertEqual(result["gradeEvidence"], [synthesis, position])
            self.assertEqual(result["corrections"], [])
            self.assertEqual(result["improvedResponse"], "")
            report["improvedResponse"] += " comparaison"
            accepted = writing_evaluation.score(**inputs)
            self.assertEqual(accepted["improvedParts"], [report["improvedResponse"], report["improvedPosition"]])
            self.assertEqual(accepted["improvedWordCount"], 121)
