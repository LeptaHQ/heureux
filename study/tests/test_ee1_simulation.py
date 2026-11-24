import json
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from study.catalogue.loader import load_ee_ai_examiner_prompt
from study.models import (
    WritingSimulationAttempt,
    WritingSimulationAttemptStatus,
    WritingSimulationEvaluationStatus,
    WritingSujetCompletion,
)
from study.simulation import evaluation, writing_evaluation
from study.simulation.evidence import number_passages
from study.views import writing_simulation

from . import factories


class EE1SimulationTests(TestCase):
    spec = writing_simulation.SPECS[1]

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

    def test_subject_picker_reuses_directory_controls_and_filters_private_sessions(self):
        response = self.client.get(reverse("study:ee1_subject_picker"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_nav_area"], "simulation")
        self.assertContains(response, "Choisir un sujet")
        self.assertContains(response, "Rechercher un sujet ou un thème")
        self.assertContains(response, "Sans séance")
        self.assertContains(response, self.sujet.prompt)
        self.assertContains(
            response,
            f'href="{reverse("study:ee1_simulation")}?sujet_id={self.sujet.pk}"',
        )
        self.assertContains(response, 'aria-label="Pratiquer :')
        self.assertContains(response, 'data-writing-sujet-completion-form')
        self.assertContains(response, "subject-progress.js")
        self.assertContains(response, 'name="theme" data-custom-select data-auto-submit')
        self.assertContains(response, 'name="etat" data-custom-select data-auto-submit')
        self.assertContains(response, 'name="tri" data-custom-select data-auto-submit')
        self.assertNotContains(response, ">Choisir</a>")
        self.assertNotContains(response, ">Choisir</button>")
        self.assertNotContains(response, ">Action<")
        fragment = self.client.get(
            reverse("study:ee1_subject_picker"),
            headers={"x-requested-with": "fetch"},
        )
        self.assertContains(fragment, 'id="ee1-topic-results"')
        self.assertNotContains(fragment, "<html")

        self.client.post(self._start_url(), {"sujet_id": str(self.sujet.pk)})
        response = self.client.get(
            reverse("study:ee1_subject_picker") + "?etat=new"
        )
        self.assertNotContains(response, self.sujet.prompt)
        self.assertContains(response, self.other_sujet.prompt)

        response = self.client.get(
            reverse("study:ee1_subject_picker") + "?q=SORTIES&tri=az"
        )
        self.assertContains(response, self.other_sujet.prompt)
        self.assertNotContains(response, self.sujet.prompt)
        self.assertEqual(response.context["directory_selection"]["order"], "az")

        self.client.force_login(self.other)
        response = self.client.get(reverse("study:ee1_subject_picker"))
        self.assertTrue(all(row["count"] == 0 for row in response.context["page"]))

    def test_subject_picker_uses_canonical_completion_for_equivalent_subjects(self):
        WritingSujetCompletion.objects.create(user=self.owner, sujet=self.sujet)
        with patch(
            "study.views.writing_simulation.content_module.ee_writing_canonical_slug_by_slug",
            return_value={
                self.sujet.slug: self.sujet.slug,
                self.other_sujet.slug: self.sujet.slug,
            },
        ):
            response = self.client.get(reverse("study:ee1_subject_picker"))

        self.assertContains(response, 'aria-checked="true"', count=2)
        self.assertContains(
            response,
            f'data-writing-sujet-id="{self.sujet.pk}"',
            count=2,
        )

    @override_settings(EE1_SIMULATION_MINUTES=12)
    def test_setup_reuses_the_shared_session_page(self):
        response = self.client.get(self._setup_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_nav_area"], "simulation")
        self.assertContains(response, 'class="lv-studio ee1-session"')
        self.assertContains(response, "Studio écrit · EE Tâche 1")
        self.assertContains(response, "Expression écrite")
        self.assertContains(response, 'data-step="live"')
        self.assertContains(response, "Rédaction")
        self.assertContains(response, "60 à 120 mots")
        self.assertContains(response, "12 minutes")
        self.assertContains(response, 'name="sujet_id"')

    @override_settings(EE1_SIMULATION_MINUTES=7)
    def test_duration_is_configurable_for_new_sessions(self):
        response = self.client.get(self._setup_url())
        self.assertContains(response, "7 minutes")
        self.assertContains(response, "7 min")

        self.client.post(self._start_url(), {"sujet_id": str(self.sujet.pk)})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        self.assertEqual(attempt.snapshot["simulation_minutes"], 7)
        self.assertEqual(
            attempt.deadline_at - attempt.started_at,
            timedelta(minutes=7),
        )

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
        self.assertEqual(
            attempt.snapshot["simulation_minutes"],
            settings.EE1_SIMULATION_MINUTES,
        )
        self.assertEqual(attempt.status, WritingSimulationAttemptStatus.ACTIVE)

        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self._attempt_url(attempt)).status_code, 404)

    def test_attempt_editor_disables_correction_and_exposes_french_character_tools(self):
        self.client.post(self._start_url(), {"sujet_id": str(self.sujet.pk)})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        response = self.client.get(self._attempt_url(attempt))

        self.assertContains(response, 'class="lv-studio ee1-session ee1-simulation ee1-simulation--attempt"')
        self.assertContains(response, "Studio écrit · EE Tâche 1")
        self.assertContains(response, 'data-step="live"')
        self.assertContains(response, 'spellcheck="false"')
        self.assertContains(response, 'autocorrect="off"')
        self.assertContains(response, 'data-gramm="false"')
        self.assertContains(response, 'class="ee1-writing-textarea"')
        self.assertContains(response, 'maxlength="20000"')
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
        self.assertContains(result, 'class="lv-studio ee1-session"')
        self.assertContains(result, 'class="lv-track"')
        self.assertContains(result, 'data-icon="target"')
        self.assertContains(result, 'data-icon="arrow-right"')
        self.assertContains(result, 'data-icon="book-open"')
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
        with patch("study.views.writing_simulation.threading.Thread") as thread:
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
            "study.simulation.writing_evaluation.score",
            return_value={"cefr": "B2", "score": 12},
        ):
            writing_simulation.run_evaluation(attempt.pk, started_at, self.spec)

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
            "study.simulation.writing_evaluation.score",
            return_value={"old": True},
        ):
            writing_simulation.run_evaluation(attempt.pk, started_at, self.spec)
        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation_status, WritingSimulationEvaluationStatus.PROCESSING)
        self.assertEqual(attempt.evaluation, {"new": True})

    def _provider_report(self):
        return {
            "verdict": "Réponse claire.",
            "score": 12,
            "scoreRange": {"min": 10, "max": 13},
            "confidence": "Medium",
            "uncertainty": "Une seule tâche ne suffit pas.",
            "taskCompliance": [{"item": "But", "status": "Met", "evidenceId": "E1", "evidence": "Le message est adressé."}],
            "criteria": {
                key: {"rating": "Adequate", "evidenceIds": ["E1"], "evidence": "Le passage est exploitable."}
                for key in ("linguistic", "pragmatic", "sociolinguistic")
            },
            "gradeRationale": "Le texte montre un contrôle fonctionnel.",
            "gradeEvidenceIds": ["E99", "E1"],
            "strengths": [{"evidenceId": "E1", "text": "Ouverture claire."}],
            "corrections": [],
            "relevance": [],
            "upgrades": [],
            "improvedResponse": "",
            "priorities": ["Préciser le but.", "Relier les idées.", "Relire les accords."],
        }

    def test_evaluation_grounding_requires_evidence_and_a_valid_score_range(self):
        self.assertIsNotNone(
            writing_evaluation._locate(
                "J’ai déjà visité Montréal.\u00a0",
                "J'ai déjà visité Montréal.",
            )
        )
        evidence = {}
        number_passages("Bonjour", evidence)
        packet = dict(subject=self.sujet.prompt, response="Bonjour", evidence=evidence, word_count=1, word_min=60, word_max=120)
        report = self._provider_report()
        grounded = writing_evaluation.ground(report, **packet)

        self.assertEqual(grounded["cefr"], "B2")
        self.assertEqual(grounded["nclc"], "NCLC 8")
        self.assertEqual(grounded["gradeEvidence"], ["Bonjour"])
        self.assertIn("gradeEvidence", grounded["omittedSections"])
        report["gradeEvidenceIds"] = ["E99"]
        with self.assertRaisesRegex(writing_evaluation.ReportError, r"gradeEvidence\.evidence"):
            writing_evaluation.ground(report, **packet)
        report["gradeEvidenceIds"] = ["E1"]
        report["criteria"]["linguistic"]["evidenceIds"] = [None, "E99"]
        with self.assertRaisesRegex(writing_evaluation.ReportError, r"criteria\.linguistic\.evidence"):
            writing_evaluation.ground(report, **packet)
        report["criteria"]["linguistic"]["evidenceIds"] = ["E1"]
        report["score"] = 14
        with self.assertRaisesRegex(writing_evaluation.ReportError, "scoreRange"):
            writing_evaluation.ground(report, **packet)

    def test_unusable_optional_feedback_does_not_discard_a_supported_score(self):
        report = self._provider_report()
        report["criteria"]["linguistic"].update(
            evidence="Observation détaillée. " * 40,
            evidenceIds=[42, "E1"],
        )
        report.update(
            verdict="Avis détaillé. " * 80,
            confidence="Moyenne",
            uncertainty=None,
            gradeRationale="Justification détaillée. " * 100,
            strengths=[{"evidenceId": "E1"}],
            corrections=[
                {"before": "Bonjour", "after": None, "type": "Registre", "why": "Salutation."},
                {"before": "salu!", "after": "salut !", "type": "Orthographe", "why": "Il manque le t."},
            ],
            improvedResponse=None,
            upgrades={"unexpected": True},
            priorities=[None, "Relire les accords."],
        )
        response = "Bonjour, salu!"
        evidence = {}
        number_passages(response, evidence)
        result = writing_evaluation.ground(
            report, subject=self.sujet.prompt, response=response, evidence=evidence,
            word_count=2, word_min=60, word_max=120,
        )
        self.assertEqual(result["score"], 12)
        self.assertEqual(result["confidence"], "")
        self.assertEqual(result["uncertainty"], "")
        self.assertEqual(result["strengths"], [])
        self.assertEqual(result["upgrades"], [])
        self.assertEqual([item["after"] for item in result["corrections"]], ["salut !"])
        self.assertEqual(result["priorities"], ["Relire les accords."])
        self.assertEqual(result["improvedResponse"], "")
        self.assertEqual(result["criteria"][0]["quotes"], [response])
        for prose, phrase, limit in (
            (result["verdict"], "Avis détaillé.", 900),
            (result["gradeRationale"], "Justification détaillée.", 1800),
            (result["criteria"][0]["evidence"], "Observation détaillée.", 700),
        ):
            self.assertTrue(prose.startswith(phrase))
            self.assertTrue(prose.endswith("…"))
            self.assertLessEqual(len(prose), limit)
        self.assertTrue({"strengths", "corrections", "improvedResponse"} <= set(result["omittedSections"]))

    def test_groq_reports_ground_evidence_in_strict_mode_and_after_schema_retry(self):
        greeting = "Bonjour, j’ai trouvé une salle de sport près de chez moi."
        original = f"{greeting}\n\nÀ bientôt !"
        valid = {**self._provider_report(), "strengths": ["Not a structured strength"]}
        invalid = {**valid, "score": True}
        rejected = b'{"error":{"code":"json_validate_failed"}}'

        def completion(report):
            return json.dumps({"choices": [{
                "finish_reason": "stop", "message": {"content": json.dumps(report)},
            }]}).encode()

        for responses, expected in (
            ([(200, completion(valid))], "ready"),
            ([(400, rejected), (200, completion(valid))], "ready"),
            ([(400, rejected), (200, completion(invalid))], "n’a pas pu être vérifié"),
            ([(400, rejected), (400, rejected)], "json_validate_failed"),
            ([(400, b'{"error":{"code":"invalid_request_error"}}')], "invalid_request_error"),
        ):
            with self.subTest(expected=expected), patch.object(
                evaluation, "HTTPSConnection", autospec=True,
            ) as transport:
                conn = transport.return_value
                conn.sock = None
                response = conn.getresponse.return_value.__enter__.return_value
                remaining = iter(responses)

                def respond(*args, **kwargs):
                    response.status, response.read.return_value = next(remaining)

                conn.request.side_effect = respond

                def score():
                    return writing_evaluation.score(
                        task_number=1, subject=self.sujet.prompt, response=original,
                        word_count=13, word_min=60, word_max=120,
                    )

                if expected == "ready":
                    report = score()
                    self.assertEqual(report["gradeEvidence"], [greeting])
                    self.assertEqual(report["criteria"][0]["quotes"], [greeting])
                    self.assertEqual(report["taskCompliance"][0]["quote"], greeting)
                    self.assertEqual(report["strengths"], [])
                else:
                    with self.assertLogs(level="WARNING"):
                        with self.assertRaisesRegex(evaluation.EvaluationError, expected):
                            score()
                requests = [json.loads(call.kwargs["body"]) for call in conn.request.call_args_list]
                self.assertEqual([request["response_format"]["type"] for request in requests],
                                 ["json_schema", "json_object"][:len(responses)])
                system, user = requests[0]["messages"]
                self.assertIn(load_ee_ai_examiner_prompt(1), system["content"])
                self.assertEqual(json.loads(user["content"]), {
                    "subject": self.sujet.prompt, "response": original,
                    "passages": [{"id": "E1", "text": greeting}, {"id": "E2", "text": "À bientôt !"}],
                    "wordCount": 13, "wordMin": 60, "wordMax": 120,
                })
                if len(responses) == 2:
                    self.assertEqual(requests[0]["messages"][1], requests[1]["messages"][1])
