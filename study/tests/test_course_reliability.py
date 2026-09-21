"""Regression coverage for recoverable course and reading-progress requests."""

import json
import tempfile
from copy import deepcopy
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.html import escape

from study.course_content import CONTENT_ROOT, validate_coverage_ledger, validate_depth_report
from study.course_practice import evidence_state, start_attempt, submit_check
from study.learning_content import load_learning_catalog
from study.models import CourseAttempt, CourseProduction, LearningLessonProgress

from . import factories
from .course_fixtures import course_catalog
from .test_course_depth import depth_fixture
from .test_learning import _catalog_payload


class LearningSchemaReliabilityTests(SimpleTestCase):
    def test_reference_schema_version_requires_an_integer(self):
        for version in (True, 1.0, "1", None):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as directory:
                payload = _catalog_payload()
                payload["version"] = version
                path = Path(directory) / "curriculum.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "version 1"):
                    load_learning_catalog(path)

    def test_malformed_benchmark_metadata_is_a_validation_error(self):
        benchmark = json.loads(
            (CONTENT_ROOT / "benchmarks" / "a1.json").read_text(encoding="utf-8")
        )
        catalog = course_catalog()
        coverage = {
            "version": 1, "level": "A1", "source_index_url": benchmark["url"],
            "entries": [{
                "source_url": row["url"], "source_title": row["title"],
                "lesson_id": "a1-foundations", "section_ids": ["rule"],
                "practice_ids": ["practice-01"], "disposition": "consolidated",
                "evidence": "The rule has examples and an explicitly mapped exercise.",
            } for row in benchmark["entries"]],
        }
        invalid_benchmarks = [None, [], {}, {**benchmark, "entries": None}]
        for invalid_row in (None, {}, {"url": [], "title": "Invalid"}, {"url": "bad"}):
            invalid = deepcopy(benchmark)
            invalid["entries"][0] = invalid_row
            invalid_benchmarks.append(invalid)
        for validator, report in (
            (validate_coverage_ledger, coverage),
            (validate_depth_report, depth_fixture(benchmark)),
        ):
            for index, invalid in enumerate(invalid_benchmarks):
                with self.subTest(validator=validator.__name__, case=index):
                    with self.assertRaises(ValueError):
                        validator(report, invalid, catalog)

    def test_course_command_reports_malformed_benchmarks_without_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "depth").mkdir()
            (root / "benchmarks").mkdir()
            benchmark = json.loads(
                (CONTENT_ROOT / "benchmarks" / "a1.json").read_text(encoding="utf-8")
            )
            (root / "depth" / "a1.json").write_text(
                json.dumps(depth_fixture(benchmark)), encoding="utf-8",
            )
            (root / "benchmarks" / "a1.json").write_text("{}", encoding="utf-8")
            output = StringIO()
            with (
                patch("study.management.commands.validate_courses.CONTENT_ROOT", root),
                patch("study.management.commands.validate_courses.load_course_catalog",
                      return_value=course_catalog()),
                self.assertRaisesRegex(CommandError, "benchmark.level"),
            ):
                call_command("validate_courses", depth=True, stdout=output)
            self.assertEqual(output.getvalue(), "")


class CourseRequestReliabilityTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("course-reliability")
        self.client.force_login(self.user)
        self.catalog = course_catalog()
        self.lesson = self.catalog.lessons[0]
        for target in (
            "study.views.learning.load_course_catalog",
            "study.views.course.load_course_catalog",
        ):
            loader = patch(target, return_value=self.catalog)
            loader.start()
            self.addCleanup(loader.stop)

    def test_invalid_check_preserves_unambiguous_answers_without_grading(self):
        attempt = start_attempt(self.user, self.lesson, "check")
        items = attempt.snapshot["items"]
        draft = '<script>keep my draft</script> "école"'
        data = {
            f"answer-{item['id']}": item["choices"][0] if item["kind"] == "choice" else draft
            for item in items
        }
        response = self.client.post(
            reverse("study:course_attempt", args=[attempt.pk]),
            {**data, "answer-unknown": "not a selected item"},
        )
        self.assertEqual(response.status_code, 400)
        for item in response.context["items"]:
            value = data[f"answer-{item['id']}"]
            self.assertEqual(item["response"], value)
            if item["kind"] == "choice":
                self.assertContains(response, f'value="{escape(value)}" required checked', status_code=400)
            else:
                self.assertContains(response, f'value="{escape(value)}"', status_code=400)
            self.assertNotIn("feedback", item)
        self.assertNotContains(response, "<script>", status_code=400)
        attempt.refresh_from_db()
        self.assertEqual(attempt.events, [])
        self.assertEqual(attempt.status, "active")
        corrected = {
            f"answer-{item['id']}": item["answers"][0] for item in items
        }
        self.assertEqual(
            self.client.post(reverse("study:course_attempt", args=[attempt.pk]), corrected).status_code,
            302,
        )
        attempt.refresh_from_db()
        self.assertTrue(attempt.criterion_met)

    def test_practice_hint_keeps_the_draft_without_recording_an_answer(self):
        attempt = start_attempt(self.user, self.lesson, "practice")
        item = next(item for item in attempt.snapshot["items"] if item["kind"] == "text")
        url = reverse("study:course_attempt", args=[attempt.pk])
        draft = 'Mon brouillon "école"'
        response = self.client.post(url, {
            "action": "hint", "item_id": item["id"], "response": draft,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{escape(draft)}"')
        self.assertContains(response, item["explanation"])
        attempt.refresh_from_db()
        self.assertEqual([event["action"] for event in attempt.events], ["hint"])
        original_hint = deepcopy(attempt.events)
        self.assertEqual(self.client.post(url, {
            "action": "hint", "item_id": item["id"], "response": draft,
        }).status_code, 200)
        attempt.refresh_from_db()
        self.assertEqual(attempt.events, original_hint)
        response = self.client.post(url, {
            "action": "answer", "item_id": item["id"], "response": item["answers"][0],
        })
        self.assertRedirects(response, url + "#item-" + item["id"])
        attempt.refresh_from_db()
        self.assertTrue(attempt.events[-1]["hinted"])
        for remaining in attempt.snapshot["items"]:
            if remaining["id"] != item["id"]:
                response = self.client.post(url, {
                    "action": "answer", "item_id": remaining["id"],
                    "response": remaining["answers"][0],
                })
        self.assertRedirects(response, url)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, "completed")
        self.assertFalse(attempt.criterion_met)

    def test_duplicate_attempt_fields_do_not_consume_or_mutate_attempts(self):
        overview = reverse("study:course_practice", args=[self.lesson.slug])
        self.assertEqual(self.client.post(overview, {"mode": ["practice", "check"]}).status_code, 400)
        self.assertFalse(CourseAttempt.objects.exists())
        attempt = start_attempt(self.user, self.lesson, "practice")
        item = attempt.snapshot["items"][0]
        url = reverse("study:course_attempt", args=[attempt.pk])
        valid = {"action": "answer", "item_id": item["id"], "response": item["answers"][0]}
        for data in (
            {**valid, "response": ["wrong", item["answers"][0]]},
            {**valid, "item_id": ["unknown", item["id"]]},
            {**valid, "action": ["answer", "abandon"]},
        ):
            with self.subTest(data=data):
                self.assertEqual(self.client.post(url, data).status_code, 400)
                attempt.refresh_from_db()
                self.assertEqual(attempt.events, [])
                self.assertEqual(attempt.status, "active")

    def test_duplicate_check_action_cannot_bypass_validation_via_abandon(self):
        attempt = start_attempt(self.user, self.lesson, "check")
        response = self.client.post(
            reverse("study:course_attempt", args=[attempt.pk]),
            {"action": ["submit", "abandon"]},
        )
        self.assertEqual(response.status_code, 400)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, "active")

    def test_invalid_production_keeps_full_draft_and_usable_form_routes(self):
        url = reverse("study:course_production_create", args=[self.lesson.slug])
        body = '<textarea>mon brouillon</textarea>' + "é" * 20001
        response = self.client.post(url, {"body": body})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, escape(body), status_code=400)
        self.assertContains(response, 'aria-invalid="true"', status_code=400)
        self.assertContains(response, 'aria-describedby="production-error"', status_code=400)
        self.assertContains(
            response,
            f'action="{reverse("study:course_practice", args=[self.lesson.slug])}"',
            count=2, status_code=400,
        )
        self.assertNotContains(response, self.lesson.production_task.model_answer, status_code=400)
        self.assertFalse(CourseProduction.objects.exists())
        self.assertFalse(CourseAttempt.objects.exists())
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.post(url, {"body": "Une école."}).status_code, 302)
        self.assertEqual(CourseProduction.objects.get().body, "Une école.")

    def test_duplicate_production_and_review_fields_are_not_saved(self):
        url = reverse("study:course_production_create", args=[self.lesson.slug])
        self.assertEqual(self.client.post(url, {"body": ["first", "second"]}).status_code, 400)
        self.assertFalse(CourseProduction.objects.exists())
        self.client.post(url, {"body": "Une école."})
        production = CourseProduction.objects.get()
        response = self.client.post(
            reverse("study:course_production", args=[production.pk]),
            {"reviewed": ["0", "1"]},
        )
        self.assertEqual(response.status_code, 400)
        production.refresh_from_db()
        self.assertIsNone(production.self_reviewed_at)

    def test_duplicate_reading_state_does_not_change_progress(self):
        reference = load_learning_catalog().lessons[0]
        for route, lesson in (
            ("course_lesson_progress", self.lesson),
            ("learn_lesson_progress", reference),
        ):
            url = reverse(f"study:{route}", args=[lesson.slug])
            self.client.post(url, {"completed": "1"})
            progress = LearningLessonProgress.objects.get(user=self.user, lesson_id=lesson.id)
            original = progress.completed_at
            response = self.client.post(
                url, {"completed": ["1", "0"]}, HTTP_X_REQUESTED_WITH="fetch",
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("error", response.json())
            progress.refresh_from_db()
            self.assertEqual(progress.completed_at, original)

    def test_mismatched_lesson_level_does_not_link_back_to_a_hidden_lesson(self):
        url = reverse("study:course_lesson", args=[self.lesson.slug])
        response = self.client.get(url, {"level": "A2"})
        self.assertNotIn("level=A2", response.context["hub_url"])
        self.assertNotIn("level=A2", response.context["next_url"])
        self.assertEqual(self.client.get(url, {"level": "unknown"}).status_code, 400)

    def test_evidence_overview_does_not_load_completed_answer_banks(self):
        attempt = start_attempt(self.user, self.lesson, "check")
        check = submit_check(self.user, attempt.pk, {
            item["id"]: item["answers"][0] for item in attempt.snapshot["items"]
        })
        with patch("study.course_practice.timezone.now",
                   return_value=check.submitted_at + timedelta(days=8)):
            for _ in range(2):
                review = start_attempt(self.user, self.lesson, "review")
                submit_check(self.user, review.pk, {
                    item["id"]: item["answers"][0] for item in review.snapshot["items"]
                })
        with CaptureQueriesContext(connection) as queries:
            state = evidence_state(self.user, self.lesson)
        self.assertIsNotNone(state["check"])
        self.assertIsNotNone(state["review"])
        self.assertIsNotNone(state["rehearsed_review"])
        for query in queries:
            self.assertNotIn('"snapshot"', query["sql"])
            self.assertNotIn('"events"', query["sql"])
