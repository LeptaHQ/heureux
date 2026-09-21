from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from study.models import (
    ComprehensionAttempt,
    ComprehensionAttemptStatus,
    ComprehensionChoice,
    ComprehensionMode,
    ComprehensionQuestion,
    ComprehensionTestCompletion,
)
from study.views.comprehension import _comprehension_attempt_questions

from . import factories


class ComprehensionReliabilityTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("comprehension-reliability")
        self.client.force_login(self.user)

    def start_url(self, test):
        route = (
            "study:comprehension_oral_start"
            if test.mode == ComprehensionMode.ORALE
            else "study:comprehension_start"
        )
        return reverse(route, args=[test.slug])

    def add_question(self, test, number):
        question = ComprehensionQuestion.objects.create(
            test=test,
            content_key=f"{test.slug}:added:{number}",
            number=number,
            passage_fr="Nouveau passage.",
            prompt_fr="Nouvelle question ?",
        )
        for letter in "ABCD":
            ComprehensionChoice.objects.create(
                question=question,
                letter=letter,
                text_fr=f"Nouveau choix {letter}",
                is_correct=letter == "A",
            )
        return question

    def test_failed_restart_preserves_the_resumable_attempt(self):
        for mode, first_number in (
            (ComprehensionMode.ECRITE, 1),
            (ComprehensionMode.ORALE, 9),
        ):
            with self.subTest(mode=mode):
                test = factories.make_comprehension_test(
                    mode=mode,
                    question_count=2,
                    first_question_number=first_number,
                )
                self.assertEqual(
                    self.client.post(self.start_url(test)).status_code,
                    302,
                )
                attempt = ComprehensionAttempt.objects.get(
                    user=self.user, test=test
                )
                question = test.questions.get(number=first_number)
                question_route = (
                    "study:comprehension_oral_question"
                    if mode == ComprehensionMode.ORALE
                    else "study:comprehension_question"
                )
                submitted = self.client.post(
                    reverse(
                        question_route,
                        args=[test.slug, attempt.pk, first_number],
                    ),
                    {"choice": question.choices.get(letter="B").pk},
                )
                self.assertEqual(submitted.status_code, 302)
                before = ComprehensionAttempt.objects.values().get(pk=attempt.pk)
                original_answers = list(attempt.answers.values())
                test.questions.update(is_active=False)

                response = self.client.post(
                    self.start_url(test), {"action": "restart"}
                )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    ComprehensionAttempt.objects.values().get(pk=attempt.pk),
                    before,
                )
                self.assertEqual(test.attempts.count(), 1)
                self.assertEqual(
                    list(attempt.answers.values()), original_answers
                )
                resumed = self.client.post(self.start_url(test))
                self.assertEqual(resumed.status_code, 302)
                self.assertEqual(self.client.get(resumed.url).status_code, 200)
                self.assertFalse(
                    ComprehensionTestCompletion.objects.filter(
                        user=self.user, test=test
                    ).exists()
                )

    def test_hub_keeps_archived_explicit_completion_without_practice(self):
        for mode in ComprehensionMode:
            with self.subTest(mode=mode):
                test = factories.make_comprehension_test(mode=mode)
                completion = ComprehensionTestCompletion.objects.create(
                    user=self.user, test=test
                )
                test.is_active = False
                test.is_published = False
                test.save(update_fields=["is_active", "is_published"])

                response = self.client.get(reverse("study:comprehension_hub"))

                summary = response.context["comprehension"][mode]
                self.assertTrue(summary["path_available"])
                self.assertEqual(summary["test_count"], 1)
                self.assertEqual(summary["completed_test_count"], 1)
                self.assertEqual(summary["progress"].status, "done")
                self.assertIsNone(summary["active_attempt"])
                self.assertFalse(test.attempts.exists())
                completion.refresh_from_db()

    def test_hub_does_not_include_another_users_archived_completion(self):
        other_user = factories.make_user("other-comprehension-reliability")
        test = factories.make_comprehension_test()
        ComprehensionTestCompletion.objects.create(user=other_user, test=test)
        test.is_active = False
        test.is_published = False
        test.save(update_fields=["is_active", "is_published"])

        response = self.client.get(reverse("study:comprehension_hub"))

        summary = response.context["comprehension"]["ecrite"]
        self.assertFalse(summary["path_available"])
        self.assertEqual(summary["completed_test_count"], 0)

    def test_legacy_results_do_not_change_historical_totals(self):
        test = factories.make_comprehension_test(question_count=3)
        attempt = factories.make_comprehension_attempt(
            user=self.user,
            test=test,
            status=ComprehensionAttemptStatus.COMPLETED,
            answered_questions=3,
        )
        original_question_ids = list(
            test.questions.values_list("pk", flat=True)
        )
        original_completed_at = attempt.completed_at
        original_answers = list(attempt.answers.values())
        self.add_question(test, 4)
        url = reverse(
            "study:comprehension_results", args=[test.slug, attempt.pk]
        )

        for _ in range(2):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            attempt.refresh_from_db()
            self.assertEqual(attempt.total_questions, 3)
            self.assertEqual(attempt.score, 3)
            self.assertEqual(attempt.percentage, 100)
            self.assertEqual(attempt.completed_at, original_completed_at)
            self.assertEqual(list(attempt.answers.values()), original_answers)
            self.assertEqual(
                [
                    question["id"]
                    for question in _comprehension_attempt_questions(attempt)
                ],
                original_question_ids,
            )

    def test_stale_legacy_reader_does_not_overwrite_a_pinned_snapshot(self):
        test = factories.make_comprehension_test(question_count=2)
        attempt = factories.make_comprehension_attempt(user=self.user, test=test)
        stale_attempt = ComprehensionAttempt.objects.get(pk=attempt.pk)
        pinned_questions = copy.deepcopy(
            _comprehension_attempt_questions(attempt)
        )
        pinned_snapshot = copy.deepcopy(attempt.content_snapshot)
        test.questions.update(passage_fr="Changed after snapshot was pinned.")
        self.add_question(test, 3)

        questions = _comprehension_attempt_questions(stale_attempt)

        self.assertEqual(questions, pinned_questions)
        stale_attempt.refresh_from_db()
        self.assertEqual(stale_attempt.content_snapshot, pinned_snapshot)
        self.assertEqual(stale_attempt.total_questions, 2)

    def test_unparseable_error_practice_id_returns_bad_request(self):
        for mode in ComprehensionMode:
            with self.subTest(mode=mode):
                test = factories.make_comprehension_test(mode=mode)

                response = self.client.post(
                    self.start_url(test),
                    {"action": "errors", "attempt_id": "9" * 5000},
                )

                self.assertEqual(response.status_code, 400)
                self.assertFalse(test.attempts.exists())

    def test_error_practice_rejects_foreign_history_without_changing_it(self):
        other_user = factories.make_user("foreign-comprehension-history")
        for mode in ComprehensionMode:
            with self.subTest(mode=mode):
                test = factories.make_comprehension_test(mode=mode)
                source = factories.make_comprehension_attempt(
                    user=other_user,
                    test=test,
                    status=ComprehensionAttemptStatus.COMPLETED,
                    answered_questions=3,
                )
                original_source = ComprehensionAttempt.objects.values().get(
                    pk=source.pk
                )
                original_answers = list(source.answers.values())

                response = self.client.post(
                    self.start_url(test),
                    {"action": "errors", "attempt_id": source.pk},
                )

                self.assertEqual(response.status_code, 404)
                self.assertEqual(
                    ComprehensionAttempt.objects.values().get(pk=source.pk),
                    original_source,
                )
                self.assertEqual(list(source.answers.values()), original_answers)
                self.assertFalse(test.attempts.filter(user=self.user).exists())

    def test_legacy_error_practice_preserves_the_completed_source(self):
        test = factories.make_comprehension_test()
        source = factories.make_comprehension_attempt(
            user=self.user,
            test=test,
            status=ComprehensionAttemptStatus.COMPLETED,
            answered_questions=3,
        )
        wrong_question = test.questions.get(number=2)
        wrong_choice = wrong_question.choices.get(letter="B")
        source.answers.filter(question=wrong_question).update(
            selected_choice=wrong_choice, is_correct=False
        )
        source.score = 2
        source.save(update_fields=["score"])
        completion = ComprehensionTestCompletion.objects.create(
            user=self.user, test=test
        )
        original_answers = list(source.answers.values())
        self.add_question(test, 4)

        response = self.client.post(
            self.start_url(test),
            {"action": "errors", "attempt_id": source.pk},
        )

        self.assertEqual(response.status_code, 302)
        source.refresh_from_db()
        self.assertEqual(source.score, 2)
        self.assertEqual(source.total_questions, 3)
        self.assertEqual(source.status, ComprehensionAttemptStatus.COMPLETED)
        self.assertEqual(list(source.answers.values()), original_answers)
        focused = test.attempts.get(status=ComprehensionAttemptStatus.IN_PROGRESS)
        self.assertEqual(focused.total_questions, 1)
        self.assertEqual(
            [question["id"] for question in focused.content_snapshot["questions"]],
            [wrong_question.pk],
        )
        completion.refresh_from_db()


@skipUnlessDBFeature("has_select_for_update")
class ComprehensionSnapshotConcurrencyTests(TransactionTestCase):
    def test_concurrent_legacy_readers_preserve_the_first_pinned_snapshot(self):
        user = factories.make_user("concurrent-comprehension")
        test = factories.make_comprehension_test(question_count=1)
        attempt = factories.make_comprehension_attempt(user=user, test=test)
        first_reader = ComprehensionAttempt.objects.get(pk=attempt.pk)
        second_reader = ComprehensionAttempt.objects.get(pk=attempt.pk)
        first_pinned = Event()
        second_reading = Event()
        release_first = Event()

        def pin_first():
            close_old_connections()
            try:
                with transaction.atomic():
                    questions = copy.deepcopy(
                        _comprehension_attempt_questions(first_reader)
                    )
                    first_pinned.set()
                    if not release_first.wait(10):
                        raise AssertionError("First snapshot reader was not released.")
                    return questions
            finally:
                connection.close()

        def read_second():
            close_old_connections()
            try:
                def observe_attempt_read(execute, sql, params, many, context):
                    if (
                        sql.lstrip().upper().startswith("SELECT")
                        and ComprehensionAttempt._meta.db_table in sql
                        and "FOR UPDATE" in sql.upper()
                    ):
                        second_reading.set()
                    return execute(sql, params, many, context)

                with connection.execute_wrapper(observe_attempt_read):
                    return _comprehension_attempt_questions(second_reader)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(pin_first)
            try:
                self.assertTrue(first_pinned.wait(10))
                test.questions.update(passage_fr="Changed after first pinning.")
                second = pool.submit(read_second)
                self.assertTrue(second_reading.wait(10))
            finally:
                release_first.set()
            first_questions = first.result(timeout=10)
            second_questions = second.result(timeout=10)

        self.assertEqual(second_questions, first_questions)
        attempt.refresh_from_db()
        self.assertEqual(attempt.content_snapshot["questions"], first_questions)
        self.assertEqual(attempt.total_questions, 1)
