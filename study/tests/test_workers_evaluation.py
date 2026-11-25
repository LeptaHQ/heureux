import json
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from study.simulation import evaluation, writing_evaluation


@override_settings(
    CLOUDFLARE_WORKERS_API_KEY="fixture-workers-token",
    CLOUDFLARE_ACCOUNT_ID="0123456789abcdef" * 2,
)
class WorkersEvaluationTests(SimpleTestCase):
    learner_passages = (
        "Bonjour Léa, je t'invite chez moi samedi pour partager un bon repas.",
        "Nous pourrons préparer le repas ensemble, comme la dernière fois.",
        "Je proposerai une soupe de légumes et un gâteau au chocolat.",
        "Tu peux venir vers dix-neuf heures si tu es libre.",
        "Je serai heureux de passer cette soirée avec toi pour discuter tranquillement.",
        "Réponds-moi avant vendredi pour confirmer ta présence, merci et à bientôt.",
    )

    def setUp(self):
        self.transport = self.enterContext(patch.object(evaluation, "HTTPSConnection", autospec=True))
        self.conn = self.transport.return_value
        self.conn.sock = None
        self.upstream = self.conn.getresponse.return_value.__enter__.return_value
        self.backoff = self.enterContext(patch.object(evaluation.time, "sleep"))
        self.enterContext(patch.object(evaluation.random, "random", return_value=0.5))

    @staticmethod
    def _complete(report=None):
        return {
            "success": True,
            "result": {"choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps({"score": 12} if report is None else report),
                    "reasoning_content": "private reasoning",
                },
            }]},
        }

    @staticmethod
    def _writing_report():
        return {
            "verdict": "A clear invitation.",
            "score": 12,
            "scoreRange": {"min": 10, "max": 13},
            "confidence": "Medium",
            "uncertainty": "",
            "taskCompliance": [{
                "item": "Invitation", "status": "Met", "evidenceId": "E1", "evidence": "You invite your friend.",
            }],
            "criteria": {
                key: {"rating": "Adequate", "evidenceIds": refs, "evidence": "These passages support the assessment."}
                for key, refs in (
                    ("linguistic", ["E1", "E2", "E2", "E3"]),
                    ("pragmatic", ["E3", "E4", "E5"]),
                    ("sociolinguistic", ["E1", "E6"]),
                )
            },
            "gradeRationale": "The invitation is understandable and the register suits a friend.",
            "gradeEvidenceIds": [],
            "strengths": [],
            "verbFeedback": [],
            "corrections": [],
            "relevance": [],
            "upgrades": [],
            "improvedResponse": "",
            "priorities": [],
        }

    def _score_writing(self, report, *, passages=None):
        response = "\n\n".join(self.learner_passages if passages is None else passages)
        self._responses([
            (200, self._complete(report), None),
            (200, self._complete({"improvedResponse": response}), None),
        ])
        return writing_evaluation.score(
            task_number=1, subject="Invitez une amie chez vous pour un repas.",
            response=response, word_count=len(response.split()), word_min=60, word_max=120,
            provider="cloudflare",
        )

    @staticmethod
    def _error(code):
        return {"success": False, "errors": [{"code": code, "message": "private upstream detail"}]}

    def _responses(self, responses):
        pending = iter(responses)
        self.conn.request.reset_mock()
        self.backoff.reset_mock()

        def respond(*args, **kwargs):
            status, body, wait = next(pending)
            self.upstream.status = status
            self.upstream.read.return_value = json.dumps(body).encode()
            self.upstream.getheader.return_value = wait

        self.conn.request.side_effect = respond

    def test_completed_report_reuses_verified_criterion_quotes_for_an_empty_grade_summary(self):
        for extra_passage in (False, True):
            with self.subTest(extra_passage=extra_passage):
                passages = self.learner_passages
                report = self._writing_report()
                if extra_passage:
                    passages += ("Tu peux également venir avec ton frère si cela vous convient.",)
                    report["criteria"]["sociolinguistic"]["evidenceIds"].append("E7")
                with (
                    patch.object(evaluation.time, "monotonic", side_effect=[0, 0, 0, 86, 86, 86, 86, 87]),
                    self.assertLogs(evaluation.logger, "WARNING") as logs,
                ):
                    result = self._score_writing(report, passages=passages)

                self.assertEqual(result["score"], 12)
                self.assertEqual(result["gradeEvidence"], list(self.learner_passages))
                self.assertFalse(result["omitted"])
                self.assertIn("finish stop after 86 s", "\n".join(logs.output))
                grade, review = self.conn.request.call_args_list
                payload = json.loads(grade.kwargs["body"])
                self.assertEqual(len(json.loads(payload["messages"][1]["content"])["passages"]), len(passages))
                self.assertNotIn("chat_template_kwargs", payload)
                packet = json.loads(json.loads(review.kwargs["body"])["messages"][1]["content"])
                self.assertEqual(packet["proposal"], "")
                self.assertEqual(result["improvedResponse"], packet["original"])
                self.backoff.assert_not_called()

    def test_empty_grade_summary_cannot_replace_unsupported_criteria(self):
        for key in ("linguistic", "pragmatic", "sociolinguistic"):
            for changes, field, reason in (
                ({"evidenceIds": []}, "evidence", "citations_empty"),
                ({"evidenceIds": ["E999"]}, "evidence", "no_matching_passages"),
                ({"rating": "Unrated"}, "rating", "unknown_rating"),
            ):
                with self.subTest(criterion=key, changes=changes):
                    report = self._writing_report()
                    report["criteria"][key].update(changes)
                    with self.assertRaises(writing_evaluation.UnverifiedReport) as error:
                        self._score_writing(report)

                    self.assertEqual((error.exception.field, error.exception.reason), (f"criteria.{key}.{field}", reason))
                    self.assertEqual(error.exception.passage_count, 6)
                    self.conn.request.assert_called_once()
                    self.backoff.assert_not_called()

    def test_grade_fallback_does_not_bypass_explicit_bad_ids_score_or_compliance(self):
        for changes, field, reason in (
            ({"gradeEvidenceIds": ["E999"]}, "gradeEvidence.evidence", "no_matching_passages"),
            ({"gradeEvidenceIds": None}, "gradeEvidence.evidence", "citations_not_array"),
            ({"score": True}, "score", "not_integer"),
            ({"scoreRange": {"min": 13, "max": 13}}, "scoreRange", "inconsistent_bounds"),
            ({"taskCompliance": []}, "taskCompliance", "no_verifiable_items"),
        ):
            with self.subTest(changes=changes):
                report = self._writing_report()
                report.update(changes)
                with self.assertRaises(writing_evaluation.UnverifiedReport) as error:
                    self._score_writing(report)

                self.assertEqual((error.exception.field, error.exception.reason), (field, reason))
                self.conn.request.assert_called_once()
                self.backoff.assert_not_called()

    def test_empty_choices_becomes_a_safe_evaluation_error(self):
        self._responses([(200, {"success": True, "result": {"choices": []}}, None)])

        with (
            self.assertLogs(evaluation.logger, "WARNING"),
            self.assertRaisesRegex(evaluation.EvaluationError, "illisible") as error,
        ):
            evaluation.request_workers_report("Rubric", {}, {})

        self.assertEqual(error.exception.status, 502)
        self.conn.request.assert_called_once()
        self.backoff.assert_not_called()

    def test_retries_documented_transient_errors_once_with_the_same_deadline(self):
        for status, code, wait in (
            (408, 3007, None),
            (408, "3008", None),
            (429, 3040, None),
            (429, "3040", "4"),
            (503, None, None),
        ):
            for recovered in (True, False):
                with self.subTest(status=status, code=code, recovered=recovered):
                    last = (200, self._complete(), None) if recovered else (status, self._error(code), wait)
                    self._responses([(status, self._error(code), wait), last])
                    with (
                        patch.object(evaluation, "_post", wraps=evaluation._post) as post,
                        self.assertLogs(evaluation.logger, "WARNING") as logs,
                    ):
                        if recovered:
                            self.assertEqual(evaluation.request_workers_report("Rubric", {}, {}), {"score": 12})
                        else:
                            with self.assertRaises(evaluation.EvaluationError):
                                evaluation.request_workers_report("Rubric", {}, {})

                    self.assertEqual(post.call_count, 2)
                    self.assertEqual(post.call_args_list[0], post.call_args_list[1])
                    self.backoff.assert_called_once_with(4 if wait else 1.5)
                    diagnostics = "\n".join(logs.output)
                    if code is not None:
                        self.assertIn(f"provider HTTP {status} {code}", diagnostics)
                    self.assertNotIn("private upstream detail", diagnostics)
                    self.assertNotIn("fixture-workers-token", diagnostics)

    def test_does_not_retry_permanent_errors_or_unusable_retry_after(self):
        for status, code, wait in (
            (429, 3036, None),
            (429, "private_upstream_code", None),
            (429, 9999, None),
            (400, 3040, None),
            (403, 5018, None),
            (429, 3040, "600"),
            (429, 3040, "Wed, 25 Nov 2026 20:00:00 GMT"),
            (429, 3040, "invalid"),
        ):
            with self.subTest(status=status, code=code, wait=wait):
                self._responses([(status, self._error(code), wait)])
                with (
                    self.assertLogs(evaluation.logger, "WARNING") as logs,
                    self.assertRaises(evaluation.EvaluationError),
                ):
                    evaluation.request_workers_report("Rubric", {}, {})

                self.conn.request.assert_called_once()
                self.backoff.assert_not_called()
                diagnostics = "\n".join(logs.output)
                self.assertNotIn("private upstream", diagnostics)
                if code == 3036:
                    self.assertIn("provider HTTP 429 3036", diagnostics)

    def test_skips_backoff_that_leaves_too_little_time_for_a_retry(self):
        self._responses([(429, self._error(3040), "20")])

        with (
            patch.object(evaluation.time, "monotonic", side_effect=[0, 0, 131, 131, 131]),
            self.assertLogs(evaluation.logger, "WARNING"),
            self.assertRaises(evaluation.EvaluationError),
        ):
            evaluation.request_workers_report("Rubric", {}, {})

        self.conn.request.assert_called_once()
        self.backoff.assert_not_called()

    def test_does_not_start_a_retry_after_backoff_exhausts_the_deadline(self):
        self._responses([(408, self._error(3007), None), (200, self._complete(), None)])
        clock = 0

        def oversleep(seconds):
            nonlocal clock
            clock = evaluation.DEADLINE_SECONDS + 1

        self.backoff.side_effect = oversleep
        with (
            patch.object(evaluation.time, "monotonic", side_effect=lambda: clock),
            self.assertLogs(evaluation.logger, "WARNING"),
            self.assertRaises(evaluation.EvaluationError),
        ):
            evaluation.request_workers_report("Rubric", {}, {})

        self.conn.request.assert_called_once()
        self.backoff.assert_called_once()

    def test_workers_error_codes_do_not_change_other_providers_retry_policy(self):
        for service in ("Groq", "Gemini"):
            for status, code in ((408, 3007), (429, 3040)):
                with self.subTest(service=service, status=status):
                    self._responses([(status, self._error(code), None)])
                    with (
                        self.assertLogs(evaluation.logger, "WARNING"),
                        self.assertRaises(evaluation.EvaluationError),
                    ):
                        evaluation._request_with_retry(
                            {}, host="provider.invalid", path="/report", auth={}, service=service,
                        )

                    self.conn.request.assert_called_once()
                    self.backoff.assert_not_called()
