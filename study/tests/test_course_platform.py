from __future__ import annotations

import json
import tempfile
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from study.course_content import (
    CONTENT_ROOT, CourseLesson, _bundled_course_catalog, build_course_catalog,
    load_course_catalog, normalize_answer, parse_course_lesson, validate_coverage_ledger,
)
from study.course_practice import (
    PracticeError, _answer, _complete, _selected_items, abandon_attempt, evidence_state,
    practice_event, practice_guidance, start_attempt, submit_check,
)
from study.learning_content import load_learning_catalog
from study.models import Annotation, CourseAttempt, CourseProduction, LearningLessonProgress
from study.templatetags.study_markdown import render_markdown_inline

from . import factories
from .course_fixtures import course_catalog, course_lesson, course_payload, sectioned_course_lesson


class CourseSchemaTests(SimpleTestCase):
    def test_complete_typed_contract_and_safe_multiline_examples(self):
        lesson = course_lesson()
        self.assertIsInstance(lesson, CourseLesson)
        self.assertEqual(len(lesson.practice), 16)
        rendered = render_markdown_inline(lesson.sections[0].examples[0].french)
        self.assertIn("<strong>Une</strong>", rendered)
        self.assertIn("<br", rendered)
        self.assertNotIn("<script>", render_markdown_inline(lesson.sections[0].paragraphs[0]))
        self.assertEqual(len(lesson.content_version), 64)

    def test_strict_field_types_and_completeness(self):
        cases = [
            (("version",), True), (("version",), 2), (("order",), True),
            (("order",), 0), (("duration_minutes",), -1), (("cefr_level",), "B2"),
            (("id",), "unprefixed"), (("slug",), "b2-wrong"),
            (("topic",), "unknown"), (("related_legacy_ids",), ["missing"]),
            (("prerequisites",), "a1-lesson"), (("sources",), []),
            (("sources", 0, "url"), "javascript:alert(1)"),
            (("objectives",), []), (("production_task", "rubric"), []),
            (("sections", 0, "examples"), []), (("sections", 0, "mistakes"), []),
            (("practice", 0, "kind"), "translation"), (("practice", 0, "pool"), "test"),
            (("practice", 0, "answers"), []), (("practice", 0, "choices"), ["wrong"]),
            (("practice", 1, "choices"), ["same", "SAME"]),
            (("practice", 1, "answers"), ["not-a-choice"]),
            (("practice", 0, "section_id"), "missing"),
            (("practice", 1, "id"), "practice-01"),
        ]
        for path, value in cases:
            with self.subTest(path=path, value=value):
                payload = course_payload()
                target = payload
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaises(ValueError):
                    parse_course_lesson(payload, directory="a1")
        payload = course_payload()
        payload["unexpected"] = "not allowed"
        with self.assertRaisesRegex(ValueError, "unexpected"):
            parse_course_lesson(payload, directory="a1")

    def test_pool_minimums_text_ratio_and_cross_pool_independence(self):
        for pool in ("practice", "check", "review"):
            payload = course_payload()
            payload["practice"] = [item for item in payload["practice"] if item["id"] != f"{pool}-01"]
            with self.assertRaisesRegex(ValueError, "at least"):
                parse_course_lesson(payload, directory="a1")
        payload = course_payload()
        for item in payload["practice"]:
            if item["pool"] == "review":
                item.update(kind="choice", choices=["école", "maison"], answers=["école"])
        with self.assertRaisesRegex(ValueError, "half"):
            parse_course_lesson(payload, directory="a1")
        payload = course_payload()
        payload["practice"][4]["prompt"] = payload["practice"][0]["prompt"].upper()
        with self.assertRaisesRegex(ValueError, "prompts"):
            parse_course_lesson(payload, directory="a1")

    def test_order_and_prerequisites_across_levels(self):
        first = course_lesson()
        second = replace(course_lesson("A2"), prerequisites=(first.id,))
        self.assertEqual(build_course_catalog([second, first]).lessons, (first, second))
        for lessons in (
            [first, first],
            [first, replace(first, id="a1-second", slug="a1-second")],
            [replace(first, prerequisites=("missing",))],
            [replace(first, prerequisites=(first.id,))],
            [replace(first, prerequisites=(second.id,)), second],
        ):
            with self.assertRaises(ValueError):
                build_course_catalog(lessons)
        third = course_lesson("A1", 2, suffix="later", topic="verbs-tenses-moods")
        self.assertEqual([item.id for item in build_course_catalog([second, third, first]).lessons],
                         [first.id, third.id, second.id])

    def test_missing_course_fallback_and_cached_bundled_load(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_course_catalog(Path(directory)).lessons, ())
            path = Path(directory) / "a1"
            path.mkdir()
            (path / "lesson.json").write_text(json.dumps(course_payload()), encoding="utf-8")
            self.assertEqual(len(load_course_catalog(Path(directory)).lessons), 1)
            _bundled_course_catalog.cache_clear()
            with patch("study.course_content.COURSE_ROOT", Path(directory)):
                self.assertIs(load_course_catalog(), load_course_catalog())
            _bundled_course_catalog.cache_clear()

    def test_loading_reports_exact_file_and_lesson_for_invalid_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "a1"
            path.mkdir()
            payload = course_payload()
            payload["practice"][0]["answers"] = ["", "incorrect"]
            lesson_path = path / "specific-lesson.json"
            lesson_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError) as failure:
                load_course_catalog(Path(directory))
            self.assertIn(str(lesson_path), str(failure.exception))
            self.assertIn("a1-foundations", str(failure.exception))
            self.assertIn("practice[0].answers", str(failure.exception))

    def test_typography_is_normalized_but_accents_and_internal_punctuation_survive(self):
        self.assertEqual(normalize_answer("  L’ÉCOLE \n "), normalize_answer("l'école"))
        self.assertEqual(normalize_answer("e\u0301cole"), "école")
        self.assertEqual(normalize_answer("il   est"), "il est")
        self.assertNotEqual(normalize_answer("école"), normalize_answer("ecole"))
        self.assertNotEqual(normalize_answer("a"), normalize_answer("à"))
        self.assertNotEqual(normalize_answer("est"), normalize_answer("es"))
        self.assertEqual(normalize_answer("école."), normalize_answer("école"))
        self.assertNotEqual(normalize_answer("a-t-il"), normalize_answer("a t il"))
        self.assertNotEqual(normalize_answer("École", case_sensitive=True), normalize_answer("école", case_sensitive=True))
        self.assertNotEqual(normalize_answer("école.", terminal_punctuation_sensitive=True), normalize_answer("école", terminal_punctuation_sensitive=True))

    def test_optional_normalization_flags_are_strict_booleans(self):
        payload = course_payload()
        payload["practice"][0].update(case_sensitive=True, terminal_punctuation_sensitive=True)
        lesson = parse_course_lesson(payload, directory="a1")
        self.assertTrue(lesson.practice[0].case_sensitive)
        self.assertFalse(lesson.practice[1].case_sensitive)
        payload["practice"][0]["case_sensitive"] = "true"
        with self.assertRaisesRegex(ValueError, "booleans"):
            parse_course_lesson(payload, directory="a1")

    def test_grading_respects_explicit_case_and_terminal_punctuation_flags(self):
        item = {
            "kind": "text", "answers": ["École."], "choices": [],
            "case_sensitive": True, "terminal_punctuation_sensitive": True,
        }
        self.assertTrue(_answer(item, " École. "))
        for wrong in ("école.", "École", "Ecole."):
            self.assertFalse(_answer(item, wrong))
        item.update(case_sensitive=False, terminal_punctuation_sensitive=False)
        self.assertTrue(_answer(item, "ÉCOLE"))
        self.assertFalse(_answer(item, "ECOLE"))

    def _ledger(self):
        benchmark = json.loads((CONTENT_ROOT / "benchmarks" / "a1.json").read_text(encoding="utf-8"))
        ledger = {
            "version": 1, "level": "A1", "source_index_url": benchmark["url"],
            "entries": [{
                "source_url": entry["url"], "source_title": entry["title"],
                "lesson_id": "a1-foundations", "section_ids": ["rule"],
                "practice_ids": ["practice-01"], "disposition": "consolidated",
                "evidence": "The explicit rule and paired examples are exercised by the mapped item.",
            } for entry in benchmark["entries"]],
        }
        return ledger, benchmark

    def test_complete_coverage_ledger_is_typed_and_exact(self):
        ledger, benchmark = self._ledger()
        self.assertEqual(len(validate_coverage_ledger(ledger, benchmark, course_catalog())), 134)
        for key, value in (
            ("source_url", "https://example.org/missing"), ("source_title", "near match"),
            ("lesson_id", "a2-foundations"), ("section_ids", ["missing"]),
            ("practice_ids", ["missing"]), ("disposition", "unreviewed"),
            ("evidence", "covered"),
        ):
            invalid = deepcopy(ledger)
            invalid["entries"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_coverage_ledger(invalid, benchmark, course_catalog())
        for entries in (ledger["entries"][:-1], ledger["entries"] + [ledger["entries"][0]]):
            with self.assertRaisesRegex(ValueError, "exactly once"):
                validate_coverage_ledger({**ledger, "entries": entries}, benchmark, course_catalog())


class CoursePlatformTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("course-owner", pin="482731")
        self.other = factories.make_user("course-other", pin="482731")
        self.client.force_login(self.user)
        self.catalog = course_catalog()
        self.lesson = self.catalog.lessons[0]
        for target in ("study.views.learning.load_course_catalog", "study.views.course.load_course_catalog"):
            mocked = patch(target, return_value=self.catalog)
            mocked.start()
            self.addCleanup(mocked.stop)

    def start(self, mode="check"):
        return start_attempt(self.user, self.lesson, mode)

    def answers(self, attempt, correct=True):
        return {
            item["id"]: item["answers"][0] if correct else (
                "maison" if item["kind"] == "choice" else "wrong"
            ) for item in attempt.snapshot["items"]
        }

    def submit(self, attempt, correct=True):
        return submit_check(self.user, attempt.pk, self.answers(attempt, correct))

    def test_hub_defaults_course_and_reference_keeps_every_lesson(self):
        hub = self.client.get(reverse("study:learn"))
        self.assertEqual(hub.context["scope"], "course")
        self.assertContains(hub, 'data-learning-level-filter')
        self.assertContains(hub, 'data-learning-lesson', count=None)
        self.assertContains(hub, 'data-active-area="learn"')
        self.assertNotContains(hub, "Private check feedback")
        self.assertNotContains(hub, self.lesson.production_task.model_answer)
        self.assertEqual(len(hub.context["modules"][0]["lessons"]), 3)
        reference = self.client.get(reverse("study:learn"), {"scope": "reference", "q": "accent"})
        self.assertEqual(reference.context["scope"], "reference")
        self.assertEqual(reference.context["summary"].total, 83)
        self.assertContains(reference, "grammar-articles-gender")
        self.assertNotContains(reference, 'data-learning-level-filter')
        self.assertEqual(self.client.get(reverse("study:learn"), {"scope": "bogus"}).status_code, 400)

    def test_hub_does_not_query_attempt_banks_or_per_lesson_progress(self):
        with CaptureQueriesContext(connection) as queries:
            self.client.get(reverse("study:learn"))
        self.assertEqual(sum("study_learninglessonprogress" in query["sql"] for query in queries), 1)
        self.assertFalse(any("study_courseattempt" in query["sql"] for query in queries))

    def test_lesson_navigation_emphasis_and_reference_annotation_keys(self):
        first = self.client.get(reverse("study:course_lesson", args=[self.lesson.slug]))
        self.assertContains(first, '<strong>Une</strong>')
        self.assertContains(first, 'learn:a1-foundations:rule')
        self.assertNotContains(first, '<script>unsafe()</script>')
        self.assertContains(first, reverse("study:course_lesson", args=[self.catalog.lessons[1].slug]))
        self.assertContains(first, reverse("study:learn_lesson", args=["grammar-articles-gender"]))
        self.assertNotContains(first, "Private practice feedback")
        self.assertNotContains(first, self.lesson.production_task.model_answer)
        filtered = self.client.get(reverse("study:course_lesson", args=[self.lesson.slug]), {"level": "A1"})
        self.assertIsNone(filtered.context["next_lesson"])
        bridge = self.client.get(reverse("study:course_lesson", args=["c1-foundations"]))
        self.assertContains(bridge, reverse("study:part_detail", args=["eo"]))
        legacy = load_learning_catalog().lessons[0]
        response = self.client.get(reverse("study:learn_lesson", args=[legacy.slug]))
        for section in legacy.sections:
            self.assertContains(response, f'learn:{legacy.id}:{section.id}')
        self.assertContains(response, "scope=reference")
        self.assertEqual(self.client.get(reverse("study:learn_lesson", args=[self.lesson.slug])).status_code, 404)

    def test_course_annotations_preserve_legacy_notes_and_user_isolation(self):
        source = reverse("study:course_lesson", args=[self.lesson.slug])
        key = f"learn:{self.lesson.id}:rule"
        annotation = Annotation.objects.create(
            user=self.user, kind="note", body="Private course note", source_path=source,
            source_key=key, source_title=self.lesson.title,
        )
        Annotation.objects.create(
            user=self.user, kind="highlight", quote="Private course quote", source_path=source,
            source_key=key, start_offset=0, end_offset=20,
        )
        Annotation.objects.create(
            user=self.other, kind="highlight", quote="Other secret", source_path=source, source_key=key,
        )
        response = self.client.get(reverse("study:annotations_for_source"), {"source_path": source})
        self.assertContains(response, "Private course quote")
        self.assertNotContains(response, "Other secret")
        self.assertEqual(Annotation.objects.get(pk=annotation.pk).source_key, key)
        self.assertContains(self.client.get(reverse("study:general_notes")), "Private course note")

    def test_manual_reading_completion_does_not_award_evidence(self):
        url = reverse("study:course_lesson_progress", args=[self.lesson.slug])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.post(url, {"completed": "1"})
        original = LearningLessonProgress.objects.get(user=self.user, lesson_id=self.lesson.id).completed_at
        self.client.post(url, {"completed": "1"})
        self.assertEqual(LearningLessonProgress.objects.get(user=self.user, lesson_id=self.lesson.id).completed_at, original)
        self.assertFalse(CourseAttempt.objects.exists())
        self.assertFalse(LearningLessonProgress.objects.filter(user=self.other).exists())
        self.assertIsNone(evidence_state(self.user, self.lesson)["check"])
        dashboard = self.client.get(reverse("study:dashboard"))
        self.assertEqual(dashboard.context["learning"]["progress"].completed, 1)
        self.assertIn("/apprendre/cours/", dashboard.context["learning"]["next_url"])

    def test_annotations_are_shared_across_course_and_reference_navigation_queries(self):
        for route, slug, key in (
            ("course_lesson", self.lesson.slug, f"learn:{self.lesson.id}:rule"),
            ("learn_lesson", "grammar-articles-gender", "learn:grammar-articles-gender:core-concept"),
        ):
            with self.subTest(route=route):
                source = reverse(f"study:{route}", args=[slug])
                old = Annotation.objects.create(
                    user=self.user, kind="highlight", quote="A saved highlight", source_key=key,
                    source_path=source + "?level=A1", start_offset=30, end_offset=47,
                )
                created = self.client.post(reverse("study:annotation_create"), {
                    "kind": "highlight", "quote": "New quote", "source_key": key,
                    "source_path": source + "?level=all", "start_offset": 1, "end_offset": 10,
                })
                self.assertEqual(created.status_code, 201)
                self.assertTrue(Annotation.objects.filter(user=self.user, source_path=source, quote="New quote").exists())
                for query in ("", "?level=A1", "?level=all&q=article"):
                    response = self.client.get(reverse("study:annotations_for_source"), {"source_path": source + query})
                    self.assertEqual({row["id"] for row in response.json()["highlights"]},
                                     {old.pk, Annotation.objects.get(user=self.user, source_path=source, quote="New quote").pk})

    def test_initial_pages_and_exports_never_leak_keys(self):
        attempt = self.start()
        for response in (
            self.client.get(reverse("study:course_practice", args=[self.lesson.slug])),
            self.client.get(reverse("study:course_attempt", args=[attempt.pk])),
            self.client.get(reverse("study:export_account")),
        ):
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Private check feedback")
            self.assertNotContains(response, "Private review feedback")
            self.assertNotContains(response, self.lesson.production_task.model_answer)
        attempt_page = self.client.get(reverse("study:course_attempt", args=[attempt.pk]))
        self.assertIn("no-store", attempt_page["Cache-Control"])
        self.assertNotIn("answers", attempt_page.context["items"][0])
        self.assertNotIn("feedback", attempt_page.context["items"][0])
        self.assertEqual({item["pool"] for item in attempt.snapshot["items"]}, {"check"})
        self.assertTrue(attempt.independent)

    def test_first_submission_is_server_graded_and_idempotent(self):
        attempt = self.start()
        url = reverse("study:course_attempt", args=[attempt.pk])
        data = {f"answer-{key}": value for key, value in self.answers(attempt, False).items()}
        response = self.client.post(url, {**data, "score": "100", "independent": "true", "criterion_met": "1"})
        self.assertEqual(response.status_code, 302)
        attempt.refresh_from_db()
        self.assertEqual(attempt.results["correct"], 0)
        self.assertFalse(attempt.criterion_met)
        original = deepcopy(attempt.events), attempt.submitted_at
        self.submit(attempt, True)
        attempt.refresh_from_db()
        self.assertEqual((attempt.events, attempt.submitted_at), original)
        result = self.client.get(url)
        self.assertContains(result, "Private check feedback")
        self.assertContains(result, "Text 0/4")
        self.assertContains(result, "Choice 0/4")

    def test_tampered_missing_duplicate_and_foreign_answers_rejected(self):
        attempt = self.start()
        for answers in ({}, {**self.answers(attempt), "foreign": "école"}):
            with self.assertRaises(PracticeError):
                submit_check(self.user, attempt.pk, answers)
        responses = self.answers(attempt)
        choice = next(item for item in attempt.snapshot["items"] if item["kind"] == "choice")
        responses[choice["id"]] = "not offered"
        with self.assertRaises(PracticeError):
            submit_check(self.user, attempt.pk, responses)
        url = reverse("study:course_attempt", args=[attempt.pk])
        self.assertEqual(self.client.post(url, {"action": "hint"}).status_code, 400)
        self.assertEqual(self.client.post(url, {"action": ["submit", "hint"]}).status_code, 400)
        attempt.refresh_from_db()
        self.assertEqual(attempt.events, [])

    def test_accents_alternatives_and_text_gate(self):
        attempt = self.start()
        answers = self.answers(attempt)
        text = [item for item in attempt.snapshot["items"] if item["kind"] == "text"]
        answers[text[0]["id"]] = " L’ÉCOLE "
        answers[text[1]["id"]] = "ecole"
        graded = submit_check(self.user, attempt.pk, answers)
        self.assertEqual(graded.results["correct"], 7)
        self.assertEqual(graded.results["text_correct"], 3)
        self.assertTrue(graded.criterion_met)
        sample = SimpleNamespace(
            mode="check", snapshot={"items": [
                {"id": str(index), "kind": "text" if index < 6 else "choice"} for index in range(10)
            ]}, events=[
                {"action": "answer", "item_id": str(index), "correct": index >= 2} for index in range(10)
            ],
        )
        _complete(sample)
        self.assertEqual(sample.results["correct"], 8)
        self.assertFalse(sample.criterion_met)  # 80% overall, but only 4/6 text.

    def test_learning_hints_and_retries_never_become_check_evidence(self):
        attempt = self.start("practice")
        item = attempt.snapshot["items"][0]
        practice_event(self.user, attempt.pk, item["id"], "hint")
        response = self.client.get(reverse("study:course_attempt", args=[attempt.pk]))
        self.assertContains(response, item["explanation"])
        for selected in attempt.snapshot["items"]:
            practice_event(self.user, attempt.pk, selected["id"], "answer", selected["answers"][0])
        attempt.refresh_from_db()
        self.assertFalse(attempt.independent)
        self.assertFalse(attempt.criterion_met)
        self.assertEqual(attempt.results["hinted_items"], 1)
        self.assertTrue(attempt.events[1]["hinted"])
        retry = self.start("practice")
        self.assertNotEqual(attempt.pk, retry.pk)
        self.assertFalse(retry.independent)
        self.assertIsNone(evidence_state(self.user, self.lesson)["check"])
        self.assertTrue(self.start("check").independent)

    def test_resume_and_abandon_do_not_offer_a_fresh_preview_loop(self):
        attempt = self.start()
        self.assertEqual(self.start().pk, attempt.pk)
        abandon_attempt(self.user, attempt.pk)
        retry = self.start()
        self.assertFalse(retry.independent)
        self.assertEqual(CourseAttempt.objects.filter(user=self.user).count(), 2)
        self.assertNotContains(self.client.get(reverse("study:export_account")), "Private check feedback")

    def test_failed_check_recovers_with_labelled_retry_and_delayed_review(self):
        first = self.submit(self.start(), False)
        with self.assertRaises(PracticeError):
            self.start("review")
        retry = self.submit(self.start(), True)
        self.assertFalse(retry.independent)
        self.assertTrue(retry.criterion_met)
        self.assertEqual(first.results["correct"], 0)
        with patch("study.course_practice.timezone.now", return_value=retry.submitted_at + timedelta(days=7) - timedelta(seconds=1)):
            with self.assertRaises(PracticeError):
                self.start("review")
        with patch("study.course_practice.timezone.now", return_value=retry.submitted_at + timedelta(days=7)):
            self.assertTrue(evidence_state(self.user, self.lesson)["review_due"])
            review = self.start("review")
            self.assertTrue(evidence_state(self.user, self.lesson)["fresh_review_available"])
        self.assertTrue(review.independent)
        self.assertEqual(review.review_of_id, retry.pk)
        self.assertEqual({item["pool"] for item in review.snapshot["items"]}, {"review"})
        self.assertTrue(
            {item["id"] for item in retry.snapshot["items"]}.isdisjoint(item["id"] for item in review.snapshot["items"])
        )

    def test_failed_review_remains_due_and_exhaustion_allows_rehearsal(self):
        check = self.submit(self.start())
        with patch("study.course_practice.timezone.now", return_value=check.submitted_at + timedelta(days=8)):
            review = self.submit(self.start("review"), False)
            self.assertTrue(evidence_state(self.user, self.lesson)["review_due"])
            retry = self.submit(self.start("review"))
            self.assertFalse(retry.independent)
            self.assertTrue(retry.criterion_met)
            evidence = evidence_state(self.user, self.lesson)
            self.assertEqual(evidence["rehearsed_review"].pk, retry.pk)
            self.assertIsNone(evidence["review"])
            self.assertTrue(evidence["review_due"])
            self.assertFalse(evidence["fresh_review_available"])
            self.assertTrue(evidence["review_exhausted"])
            page = self.client.get(reverse("study:course_practice", args=[self.lesson.slug]))
            self.assertContains(page, "insufficient unseen review items")
            self.assertContains(page, "Rehearse review")
            self.assertContains(page, "Fresh review unavailable: bank exhausted.")
            self.assertNotContains(page, "Fresh review due.")
        self.assertEqual(review.results["correct"], 0)
        self.assertTrue(CourseAttempt.objects.get(pk=check.pk).criterion_met)
        response = self.client.get(reverse("study:course_attempt", args=[retry.pk]))
        self.assertContains(response, "Rehearsed: not independent evidence")

    def test_content_and_item_versions_are_immutable_across_edits(self):
        attempt = self.start()
        original_snapshot = deepcopy(attempt.snapshot)
        new_item = replace(self.lesson.practice[4], answers=("different",), explanation="Changed")
        updated = replace(self.lesson, practice=(*self.lesson.practice[:4], new_item, *self.lesson.practice[5:]))
        self.assertNotEqual(updated.content_version, self.lesson.content_version)
        self.assertNotEqual(updated.practice[4].item_version, self.lesson.practice[4].item_version)
        self.submit(attempt)
        attempt.refresh_from_db()
        self.assertEqual(attempt.snapshot, original_snapshot)
        self.assertTrue(attempt.criterion_met)
        with patch("study.views.course.load_course_catalog", return_value=build_course_catalog([])):
            self.assertEqual(self.client.get(reverse("study:course_attempt", args=[attempt.pk])).status_code, 200)
        attempt.snapshot["title"] = "rewritten"
        with self.assertRaises(ValidationError):
            attempt.save()
        attempt.refresh_from_db()
        attempt.results["correct"] = 0
        with self.assertRaises(ValidationError):
            attempt.save()
        self.assertFalse(start_attempt(self.user, updated, "check").independent)

    def test_cosmetic_prompt_edits_and_item_renames_cannot_erase_exposure(self):
        self.submit(self.start())
        changed_prompts = replace(self.lesson, practice=tuple(
            replace(item, prompt="Please: " + item.prompt) for item in self.lesson.practice
        ))
        changed = start_attempt(self.user, changed_prompts, "check")
        self.assertFalse(changed.independent)
        abandon_attempt(self.user, changed.pk)
        renamed_items = replace(self.lesson, practice=tuple(
            replace(item, id="renamed-" + item.id) for item in self.lesson.practice
        ))
        self.assertFalse(start_attempt(self.user, renamed_items, "check").independent)

    def test_user_isolation_authentication_and_csrf(self):
        attempt = start_attempt(self.other, self.lesson, "check")
        url = reverse("study:course_attempt", args=[attempt.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {}).status_code, 404)
        self.assertNotContains(self.client.get(reverse("study:export_account")), str(attempt.pk))
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(reverse("study:course_practice", args=[self.lesson.slug]), {"mode": "check"}).status_code, 403)

    def test_production_self_review_is_private_unscored_and_exported(self):
        response = self.client.post(reverse("study:course_production_create", args=[self.lesson.slug]), {
            "body": "<script>unsafe()</script> Une école.", "score": 100,
        })
        production = CourseProduction.objects.get(user=self.user)
        self.assertEqual(response.status_code, 302)
        url = reverse("study:course_production", args=[production.pk])
        rendered = self.client.get(url)
        self.assertNotContains(rendered, "<script>unsafe()</script>")
        self.assertContains(rendered, production.task_snapshot["model_answer"])
        self.assertFalse(CourseAttempt.objects.exists())
        self.client.post(url, {"reviewed": "1"})
        production.refresh_from_db()
        reviewed = production.self_reviewed_at
        self.client.post(url, {"reviewed": "1"})
        production.refresh_from_db()
        self.assertEqual(production.self_reviewed_at, reviewed)
        exported = self.client.get(reverse("study:export_account")).json()
        self.assertEqual(exported["version"], 9)
        self.assertEqual(exported["course_productions"][0]["body"], production.body)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"reviewed": "1"}).status_code, 404)

    def test_export_reset_and_deletion_include_all_new_owned_data(self):
        own = self.submit(self.start())
        other = start_attempt(self.other, self.lesson, "check")
        self.client.post(reverse("study:course_production_create", args=[self.lesson.slug]), {"body": "Une école."})
        production = CourseProduction.objects.get(user=self.user)
        CourseProduction.objects.create(
            user=self.other, lesson_id=self.lesson.id, content_version=self.lesson.content_version,
            task_snapshot=production.task_snapshot, body="Une maison.",
        )
        Annotation.objects.create(user=self.user, body="Keep this note", kind="note")
        exported = self.client.get(reverse("study:export_account")).json()
        self.assertEqual([row["id"] for row in exported["course_attempts"]], [str(own.pk)])
        self.assertIn("answers", exported["course_attempts"][0]["snapshot"]["items"][0])
        result = self.client.post(reverse("study:reset_progress"), {
            "current_pin": "482731", "confirmation": "REINITIALISER",
        })
        self.assertEqual(result.status_code, 302)
        self.assertFalse(CourseAttempt.objects.filter(user=self.user).exists())
        self.assertFalse(CourseProduction.objects.filter(user=self.user).exists())
        self.assertTrue(Annotation.objects.filter(user=self.user).exists())
        self.assertTrue(CourseAttempt.objects.filter(pk=other.pk).exists())
        self.client.force_login(self.other)
        result = self.client.post(reverse("study:delete_account"), {
            "current_pin": "482731", "username_confirmation": self.other.username,
        })
        self.assertEqual(result.status_code, 302)
        self.assertFalse(CourseAttempt.objects.filter(user_id=self.other.pk).exists())
        self.assertFalse(CourseProduction.objects.filter(user_id=self.other.pk).exists())


class CourseGuidanceTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("guidance-owner", pin="482731")
        self.other = factories.make_user("guidance-other", pin="482731")
        self.client.force_login(self.user)
        self.lesson = sectioned_course_lesson()

    def finish_learning(self, attempt, correct=True):
        for item in attempt.snapshot["items"]:
            response = item["answers"][0] if correct else (
                "maison" if item["kind"] == "choice" else ""
            )
            attempt = practice_event(self.user, attempt.pk, item["id"], "answer", response)
        return attempt

    def finish_check(self, attempt, correct=True, user=None):
        return submit_check(user or self.user, attempt.pk, {
            item["id"]: item["answers"][0] if correct else (
                "maison" if item["kind"] == "choice" else ""
            ) for item in attempt.snapshot["items"]
        })

    def one_section_practice(self):
        return replace(self.lesson, practice=tuple(
            item for item in self.lesson.practice
            if item.pool != "practice" or item.section_id == "section-0"
        ))

    def page(self, lesson=None):
        lesson = lesson or self.lesson
        with patch("study.views.course.load_course_catalog", return_value=build_course_catalog([lesson])):
            return self.client.get(reverse("study:course_practice", args=[lesson.slug]))

    def test_weak_section_is_rehearsed_ahead_of_unseen_strong_sections(self):
        original = self.finish_learning(
            start_attempt(self.user, self.one_section_practice(), "practice"), False,
        )
        frozen = deepcopy(original.snapshot), deepcopy(original.events), deepcopy(original.results)
        next_attempt = start_attempt(self.user, self.lesson, "practice")
        self.assertEqual({item["section_id"] for item in next_attempt.snapshot["items"]}, {"section-0"})
        self.assertTrue(next_attempt.snapshot["selection"]["focus"][0]["rehearsed"])
        self.assertIn("incorrect or blank", next_attempt.snapshot["selection"]["focus"][0]["reason"])
        self.assertFalse(next_attempt.independent)
        self.finish_learning(next_attempt)
        next_attempt = start_attempt(self.user, self.lesson, "practice")
        self.assertNotIn("section-0", {item["section_id"] for item in next_attempt.snapshot["items"]})
        original.refresh_from_db()
        self.assertEqual((original.snapshot, original.events, original.results), frozen)
        self.assertTrue(all(row["assessed"] == 0 for row in practice_guidance(self.user, self.lesson)))
        self.assertIsNone(evidence_state(self.user, self.lesson)["check"])

    def test_unseen_questions_are_preferred_within_the_weak_focus(self):
        self.finish_learning(start_attempt(self.user, self.one_section_practice(), "practice"), False)
        added = tuple(
            replace(item, id="new-" + item.id, prompt="Another constrained task: " + item.prompt)
            for item in self.lesson.practice if item.pool == "practice" and item.section_id == "section-0"
        )
        updated = replace(self.lesson, practice=(*self.lesson.practice, *added))
        attempt = start_attempt(self.user, updated, "practice")
        self.assertEqual({item["id"] for item in attempt.snapshot["items"]}, {item.id for item in added})
        self.assertFalse(attempt.snapshot["selection"]["focus"][0]["rehearsed"])

    def test_learning_spreads_untried_sections_and_prefers_most_recent_needs(self):
        self.lesson = sectioned_course_lesson(5)
        unseen = start_attempt(self.user, self.lesson, "practice")
        self.assertEqual(len({item["section_id"] for item in unseen.snapshot["items"]}), 4)
        abandon_attempt(self.user, unseen.pk)
        now = timezone.now()
        for index in range(5):
            focused = replace(self.lesson, practice=tuple(
                item for item in self.lesson.practice
                if item.pool != "practice" or item.section_id == f"section-{index}"
            ))
            with patch("study.course_practice.timezone.now", return_value=now + timedelta(minutes=index)):
                self.finish_learning(start_attempt(self.user, focused, "practice"), False)
        attempt = start_attempt(self.user, self.lesson, "practice")
        self.assertEqual(
            {item["section_id"] for item in attempt.snapshot["items"]},
            {f"section-{index}" for index in range(1, 5)},
        )

    def test_unanswered_and_hinted_learning_never_become_assessment_feedback(self):
        attempt = start_attempt(self.user, self.one_section_practice(), "practice")
        item = attempt.snapshot["items"][0]
        practice_event(self.user, attempt.pk, item["id"], "hint")
        self.assertTrue(all(row["priority"] == 2 for row in practice_guidance(self.user, self.lesson)))
        self.finish_learning(attempt)
        rows = practice_guidance(self.user, self.lesson)
        self.assertEqual(rows[0]["priority"], 1)
        self.assertEqual(rows[0]["assessed"], 0)
        next_attempt = start_attempt(self.user, self.lesson, "practice")
        self.assertEqual({item["section_id"] for item in next_attempt.snapshot["items"]}, {"section-0"})
        self.assertIn("Hint-supported", next_attempt.snapshot["selection"]["focus"][0]["reason"])

    def test_learning_uses_latest_completed_first_answers_not_retries(self):
        attempt = start_attempt(self.user, self.one_section_practice(), "practice")
        first = attempt.snapshot["items"][0]
        wrong = "maison" if first["kind"] == "choice" else ""
        practice_event(self.user, attempt.pk, first["id"], "answer", wrong)
        with self.assertRaises(PracticeError):
            practice_event(self.user, attempt.pk, first["id"], "answer", first["answers"][0])
        self.assertEqual(practice_guidance(self.user, self.lesson)[0]["priority"], 2)
        for item in attempt.snapshot["items"][1:]:
            practice_event(self.user, attempt.pk, item["id"], "answer", item["answers"][0])
        self.assertEqual(practice_guidance(self.user, self.lesson)[0]["priority"], 0)
        self.finish_learning(start_attempt(self.user, self.one_section_practice(), "practice"))
        self.assertEqual(practice_guidance(self.user, self.lesson)[0]["priority"], 3)

    def test_sections_balance_and_text_quota_across_bank_compositions(self):
        for mode, count in (("check", 8), ("review", 4)):
            for section_count in (1, 3, 10):
                lesson = sectioned_course_lesson(section_count)
                bank = [item for item in lesson.practice if item.pool == mode]
                for composition in ("mixed", "text-only", "concentrated-text"):
                    with self.subTest(mode=mode, sections=section_count, composition=composition):
                        if composition == "text-only":
                            items = tuple(replace(item, kind="text", choices=()) for item in bank)
                        elif composition == "concentrated-text":
                            items = tuple(
                                replace(item, kind="text", choices=()) if item.section_id == "section-0"
                                else replace(item, kind="choice", choices=("école", "maison"), answers=("école",))
                                for item in bank
                            )
                        else:
                            items = tuple(bank)
                        changed = replace(lesson, practice=items)
                        for _ in range(12):
                            selected = _selected_items(changed, mode, set(), set())
                            self.assertEqual(len({item.id for item in selected}), count)
                            self.assertGreaterEqual(sum(item.kind == "text" for item in selected), count // 2)
                            spread = Counter(item.section_id for item in selected)
                            maximum_sections = min(section_count, count)
                            if composition == "concentrated-text":
                                maximum_sections = min(section_count, count // 2 + 1)
                            self.assertEqual(len(spread), maximum_sections)
                            if composition != "concentrated-text" and section_count <= count:
                                self.assertLessEqual(max(spread.values()) - min(spread.values()), 1)

    def test_fresh_bank_wins_over_broader_rehearsed_section_coverage(self):
        for mode in ("check", "review"):
            bank = [item for item in self.lesson.practice if item.pool == mode]
            seen = {(self.lesson.id, item.id) for item in bank if item.section_id != "section-0"}
            selected = _selected_items(self.lesson, mode, set(), seen)
            self.assertEqual({item.section_id for item in selected}, {"section-0"})
            text = next(item for item in bank if item.section_id == "section-0" and item.kind == "text")
            seen.add((self.lesson.id, text.id))
            selected = _selected_items(self.lesson, mode, set(), seen)
            self.assertGreater(len({item.section_id for item in selected}), 1)
            self.assertTrue(any((self.lesson.id, item.id) in seen for item in selected))
            self.assertGreaterEqual(sum(item.kind == "text" for item in selected), len(selected) // 2)

    def test_enough_fresh_choices_without_text_quota_cannot_be_independent(self):
        for mode, count in (("check", 8), ("review", 4)):
            seen_items = [
                item for item in self.lesson.practice if item.pool == mode and item.kind == "text"
            ]
            seen = {(self.lesson.id, item.id) for item in seen_items}
            choices = [item for item in self.lesson.practice if item.pool == mode and item.kind == "choice"]
            self.assertGreaterEqual(len(choices), count)
            selected = _selected_items(self.lesson, mode, set(), seen)
            self.assertEqual(len(selected), count)
            self.assertGreaterEqual(sum(item.kind == "text" for item in selected), count // 2)
            self.assertTrue(any((self.lesson.id, item.id) in seen for item in selected))

    def test_assessment_difficulty_and_recency_guide_learning_not_current_check_answers(self):
        initial = self.finish_check(start_attempt(self.user, self.lesson, "check"), False)
        rows = practice_guidance(self.user, self.lesson)
        self.assertTrue(all(row["priority"] == 0 for row in rows))
        self.assertEqual(sum(row["assessed"] for row in rows), 8)
        self.assertEqual(sum(row["correct"] for row in rows), 0)
        active = start_attempt(self.user, self.lesson, "check")
        active.events = [
            {"action": "answer", "item_id": item["id"], "correct": True,
             "response": item["answers"][0], "hinted": False, "at": timezone.now().isoformat()}
            for item in active.snapshot["items"]
        ]
        active.save(update_fields=["events"])
        self.assertEqual(practice_guidance(self.user, self.lesson), rows)
        self.assertEqual(self.page().context["guidance"], rows)
        abandon_attempt(self.user, active.pk)
        self.assertEqual(practice_guidance(self.user, self.lesson), rows)
        initial.refresh_from_db()
        self.assertEqual(initial.results["correct"], 0)

    def test_unchanged_item_history_survives_teaching_edits_without_assessing_new_material(self):
        original = self.finish_check(start_attempt(self.user, self.lesson, "check"))
        old_item = original.snapshot["items"][0]
        new_section = replace(self.lesson.sections[0], id="added", title="New teaching")
        updated = replace(
            self.lesson, sections=(*self.lesson.sections, new_section),
            practice=tuple(
                replace(item, explanation="A corrected explanation.") if item.id == old_item["id"] else item
                for item in self.lesson.practice
            ),
        )
        frozen = deepcopy(original.snapshot), deepcopy(original.results)
        rows = practice_guidance(self.user, updated)
        self.assertEqual(sum(row["assessed"] for row in rows), 7)
        self.assertEqual(sum(row["older_content"] for row in rows), 7)
        self.assertEqual(rows[-1]["assessed"], 0)
        self.assertEqual(rows[-1]["practice_count"], 0)
        self.assertIsNone(evidence_state(self.user, updated)["check"])
        page = self.page(updated)
        self.assertContains(page, "from earlier teaching versions")
        self.assertContains(page, "not evidence for new material")
        self.assertContains(page, "No check items.")
        self.assertContains(page, "No review items.")
        self.assertNotContains(page, "Private check feedback")
        original.refresh_from_db()
        self.assertEqual((original.snapshot, original.results), frozen)

    def test_new_items_are_untested_even_when_all_prior_check_items_were_correct(self):
        self.lesson = course_lesson()
        self.finish_check(start_attempt(self.user, self.lesson, "check"))
        added = replace(
            self.lesson.practice[4], id="new-distinction",
            prompt="A newly taught distinction: supply the requested form.",
        )
        updated = replace(self.lesson, practice=(*self.lesson.practice, added))
        row = practice_guidance(self.user, updated)[0]
        self.assertEqual((row["assessed"], row["correct"], row["untested"]), (8, 8, 5))
        self.assertEqual(row["older_content"], 8)
        self.assertIsNone(evidence_state(self.user, updated)["check"])

    def test_completed_rehearsal_is_labelled_and_latest_not_accumulated(self):
        self.lesson = course_lesson()
        first = self.finish_check(start_attempt(self.user, self.lesson, "check"), False)
        second = self.finish_check(start_attempt(self.user, self.lesson, "check"))
        row = practice_guidance(self.user, self.lesson)[0]
        self.assertEqual((row["assessed"], row["correct"], row["fresh"], row["rehearsed"]), (8, 8, 0, 8))
        self.assertEqual(row["untested"], 4)
        self.assertFalse(second.independent)
        first.refresh_from_db()
        self.assertEqual(first.results["correct"], 0)
        with patch("study.course_practice.timezone.now", return_value=second.submitted_at + timedelta(days=7)):
            review = self.finish_check(start_attempt(self.user, self.lesson, "review"), False)
            row = practice_guidance(self.user, self.lesson)[0]
            self.assertEqual((row["assessed"], row["correct"], row["fresh"], row["rehearsed"]), (12, 8, 4, 8))
            self.assertEqual(row["untested"], 0)
            self.assertEqual(row["last_assessed"], review.submitted_at)
            self.assertTrue(evidence_state(self.user, self.lesson)["review_exhausted"])

    def test_session_scope_is_frozen_and_reports_missing_and_bounded_sections(self):
        lesson = sectioned_course_lesson(10)
        added = replace(lesson.sections[0], id="no-bank", title="No bank section")
        lesson = replace(lesson, sections=(*lesson.sections, added))
        attempt = start_attempt(self.user, lesson, "check")
        notes = deepcopy(attempt.snapshot["selection"])
        self.assertEqual((notes["sampled"], notes["total"]), (8, 11))
        self.assertEqual(len(notes["omitted"]), 3)
        self.assertEqual(notes["unavailable"], ["No bank section"])
        response = self.client.get(reverse("study:course_attempt", args=[attempt.pk]))
        self.assertContains(response, "8/11 teaching sections sampled")
        self.assertContains(response, "No eligible items in this session")
        self.assertNotContains(response, "Private check feedback")
        changed = replace(lesson, sections=tuple(
            replace(section, title="Changed " + section.title) for section in lesson.sections
        ))
        self.assertEqual(start_attempt(self.user, changed, "check").pk, attempt.pk)
        attempt.refresh_from_db()
        self.assertEqual(attempt.snapshot["selection"], notes)
        self.assertNotContains(self.client.get(reverse("study:export_account")), '"selection"')

    def test_published_snapshots_without_selection_metadata_still_render_and_inform_guidance(self):
        original = self.finish_check(start_attempt(self.user, self.lesson, "check"))
        old_snapshot = {key: value for key, value in original.snapshot.items() if key != "selection"}
        historical = CourseAttempt.objects.create(
            user=self.other, lesson_id=self.lesson.id, content_version=self.lesson.content_version,
            mode="check", status="completed", independent=True, criterion_met=True,
            snapshot=old_snapshot, events=original.events, results=original.results,
            submitted_at=original.submitted_at,
        )
        self.client.force_login(self.other)
        page = self.client.get(reverse("study:course_attempt", args=[historical.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "First submitted results")
        self.assertNotContains(page, "Session scope:")
        self.assertEqual(sum(row["assessed"] for row in practice_guidance(self.other, self.lesson)), 8)
        historical.refresh_from_db()
        self.assertNotIn("selection", historical.snapshot)

    def test_guidance_is_single_query_private_and_removed_with_account_history(self):
        self.finish_check(start_attempt(self.other, self.lesson, "check"), user=self.other)
        with self.assertNumQueries(1):
            rows = practice_guidance(self.user, self.lesson)
        self.assertTrue(all(row["assessed"] == 0 for row in rows))
        self.finish_check(start_attempt(self.user, self.lesson, "check"))
        self.assertGreater(sum(row["assessed"] for row in practice_guidance(self.user, self.lesson)), 0)
        page = self.page()
        self.assertContains(page, "Section / item evidence")
        self.assertContains(page, "Sections and practice focus (3)")
        self.assertNotContains(page, "Private check feedback")
        self.assertNotContains(page, '"item_version"')
        for attempt in page.context["attempts"]:
            self.assertIn("snapshot", attempt.get_deferred_fields())
            self.assertIn("events", attempt.get_deferred_fields())
        self.client.post(reverse("study:reset_progress"), {
            "current_pin": "482731", "confirmation": "REINITIALISER",
        })
        self.assertTrue(all(row["assessed"] == 0 for row in practice_guidance(self.user, self.lesson)))
        self.assertEqual(sum(row["assessed"] for row in practice_guidance(self.other, self.lesson)), 8)
