"""Subject progress queries stay target-specific without changing activity."""

from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from study.models import Card, CardState, CardType, PhraseTier, Prompt
from study.review.progress import subject_progress_by_response

from . import factories


class SubjectProgressQueryTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("targeted-subject-progress")
        self.other = factories.make_user("other-targeted-subject-progress")
        part = factories.make_part("eo")
        self.current = factories.make_response(theme=factories.make_theme(
            "current-progress", task=factories.make_task(part, "tache-2"),
        ))
        self.retired = factories.make_response(theme=factories.make_theme(
            "retired-progress", task=factories.make_task(part, "tache-3"),
        ))
        self.ids = {self.current.pk, self.retired.pk}
        self.now = timezone.now()

    def progress(self, summary_only=False):
        return subject_progress_by_response(
            self.user, self.ids, summary_only=summary_only,
        )

    def phrase(self, **overrides):
        phrase = factories.make_phrase(tier=PhraseTier.SUBJECT, **overrides)
        phrase.source_prompts.add(self.current.prompts.get(is_canonical=True))
        return phrase

    def test_response_cards_keep_completion_reset_suspension_and_user_isolation(self):
        card = Card.objects.create(
            user=self.user, response=self.current, card_type=CardType.SPINE,
            suspended=True, state=CardState.REVIEW,
            response_practice_started_at=self.now - timedelta(days=2),
        )
        Card.objects.create(
            user=self.other, response=self.retired, card_type=CardType.SPINE,
            subject_completed_at=self.now,
        )
        for summary_only in (False, True):
            with self.subTest(summary_only=summary_only):
                result = self.progress(summary_only)
                self.assertEqual(result[self.current.pk].status, "active")
                self.assertEqual(result[self.retired.pk].status, "new")
                self.assertEqual(
                    result[self.current.pk].started_at,
                    card.response_practice_started_at,
                )
        card.subject_status_reset_at = self.now
        card.save(update_fields=["subject_status_reset_at"])
        for summary_only in (False, True):
            self.assertEqual(self.progress(summary_only)[self.current.pk].status, "new")
        card.subject_completed_at = self.now
        card.save(update_fields=["subject_completed_at"])
        for summary_only in (False, True):
            self.assertEqual(self.progress(summary_only)[self.current.pk].status, "done")
        self.current.is_active = False
        self.current.save(update_fields=["is_active"])
        for summary_only in (False, True):
            self.assertEqual(self.progress(summary_only)[self.current.pk].status, "new")

    def test_shared_vocabulary_counts_distinct_cards_only_for_current_owners(self):
        phrase = self.phrase()
        phrase.source_prompts.add(self.retired.prompts.get())
        Prompt.objects.create(
            content_key="test-prompt:second-current-publication",
            response=self.current, theme=self.current.theme,
            family=self.current.family, number=999, text="Another publication.",
        ).phrases.add(phrase)
        for card_type in (CardType.PHRASE_PRODUCTION, CardType.PHRASE_RECOGNITION):
            factories.make_phrase_card(
                phrase=phrase, user=self.user, card_type=card_type,
                state=CardState.REVIEW, started_at=self.now,
                interval_days=30, due=self.now - timedelta(days=1),
            )
        factories.make_phrase_card(
            phrase=phrase, user=self.other, state=CardState.REVIEW,
        )
        detailed = self.progress()
        current = detailed[self.current.pk]
        self.assertEqual(
            (
                current.vocabulary_total, current.vocabulary_started,
                current.vocabulary_completed, current.vocabulary_mastered,
                current.vocabulary_due,
            ),
            (2, 2, 2, 2, 2),
        )
        self.assertEqual(current.started_at, self.now)
        self.assertEqual(detailed[self.retired.pk].vocabulary_total, 0)
        for result in (detailed, self.progress(summary_only=True)):
            self.assertTrue(result[self.current.pk].vocabulary_activity_started)
            self.assertFalse(result[self.retired.pk].vocabulary_activity_started)

    def test_suspended_vocabulary_keeps_activity_but_not_counts(self):
        factories.make_phrase_card(
            phrase=self.phrase(), user=self.user,
            suspended=True, started_at=self.now,
        )
        for summary_only in (False, True):
            with self.subTest(summary_only=summary_only):
                current = self.progress(summary_only)[self.current.pk]
                self.assertEqual(current.status, "active")
                self.assertTrue(current.vocabulary_activity_started)
                self.assertEqual(current.vocabulary_total, 0)
                self.assertEqual(current.vocabulary_started, 0)

    def test_inactive_and_other_user_vocabulary_do_not_start_subjects(self):
        inactive_phrase = self.phrase(is_active=False)
        inactive_source = self.phrase()
        inactive_source.source_prompts.set([Prompt.objects.create(
            content_key="test-prompt:inactive-current-publication",
            response=self.current, theme=self.current.theme,
            family=self.current.family, number=998, text="Inactive publication.",
            is_active=False,
        )])
        for phrase in (inactive_phrase, inactive_source):
            factories.make_phrase_card(
                phrase=phrase, user=self.user, started_at=self.now,
            )
        factories.make_phrase_card(
            phrase=self.phrase(), user=self.other, started_at=self.now,
        )
        for summary_only in (False, True):
            self.assertTrue(all(
                result.status == "new"
                for result in self.progress(summary_only).values()
            ))

    def test_retirement_still_checks_shared_source_ancestry(self):
        phrase = self.phrase()
        phrase.source_prompts.add(self.retired.prompts.get())
        factories.make_phrase_card(
            phrase=phrase, user=self.user, started_at=self.now,
        )
        self.current.theme.is_active = False
        self.current.theme.save(update_fields=["is_active"])
        for summary_only in (False, True):
            self.assertFalse(
                self.progress(summary_only)[self.current.pk].vocabulary_activity_started,
            )
        comprehension = factories.make_comprehension_test(question_count=1)
        comprehension.questions.get().vocabulary.add(phrase)
        for summary_only in (False, True):
            self.assertTrue(
                self.progress(summary_only)[self.current.pk].vocabulary_activity_started,
            )

    def test_response_and_vocabulary_queries_do_not_join_the_other_target(self):
        for summary_only in (False, True):
            with self.subTest(summary_only=summary_only):
                with CaptureQueriesContext(connection) as queries:
                    self.progress(summary_only)
                card_queries = [
                    query["sql"] for query in queries
                    if 'FROM "study_card"' in query["sql"]
                ]
                self.assertEqual(len(card_queries), 2)
                response_sql, vocabulary_sql = card_queries
                self.assertNotIn('"study_phrase"', response_sql)
                self.assertNotIn('"study_phrase_source_prompts"', response_sql)
                self.assertNotIn('"study_response"."is_active"', vocabulary_sql)
                self.assertNotIn('LEFT OUTER JOIN "study_response"', vocabulary_sql)
