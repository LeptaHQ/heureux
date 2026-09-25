"""Regression coverage for study state and scoped progress."""

from datetime import timedelta
import threading
from unittest.mock import patch

from django.db import IntegrityError, connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature, tag
from django.urls import reverse
from django.utils import timezone

from study import queue, srs
from study.models import (
    Card,
    CardState,
    Rating,
    ReviewLog,
    ReviewSession,
    WritingResponseOverride,
)
from study.progress import writing_sujet_progress_by_id
from study.views.helpers import (
    _ee_writing_task_card,
    expression_task_summaries,
    recent_review_sessions,
)

from . import factories


class SchedulingReliabilityTests(TestCase):
    def test_failed_log_write_rolls_back_the_schedule(self):
        card = factories.make_spine_card()
        before = srs._snapshot(card)

        with patch.object(
            ReviewLog.objects, "create", side_effect=IntegrityError("log unavailable")
        ):
            with self.assertRaises(IntegrityError):
                srs.review(card, Rating.GOOD)

        card.refresh_from_db()
        self.assertEqual(srs._snapshot(card), before)
        self.assertFalse(ReviewLog.objects.exists())

    def test_stale_card_instance_uses_the_persisted_schedule_and_snapshot(self):
        card = factories.make_spine_card()
        stale = Card.objects.get(pk=card.pk)
        srs.review(card, Rating.GOOD)
        before_second_review = srs._snapshot(card)

        _, second_log = srs.review(stale, Rating.GOOD, return_log=True)

        card.refresh_from_db()
        self.assertEqual(card.reps, 2)
        self.assertEqual(card.state, CardState.REVIEW)
        self.assertEqual(second_log.card_before, before_second_review)
        restored = srs.undo_last(log_id=second_log.pk, card_id=card.pk)
        self.assertEqual(srs._snapshot(restored), before_second_review)

    def test_invalid_rating_does_not_mutate_the_schedule(self):
        card = factories.make_spine_card()
        before = srs._snapshot(card)

        with self.assertRaises(ValueError):
            srs.review(card, 9)

        card.refresh_from_db()
        self.assertEqual(srs._snapshot(card), before)
        self.assertFalse(ReviewLog.objects.exists())


@skipUnlessDBFeature("has_select_for_update")
@tag("database-locking")
class SchedulingConcurrencyTests(TransactionTestCase):
    def test_reviews_lock_and_refresh_before_computing(self):
        user = factories.make_user()
        card = factories.make_spine_card(user=user)
        stale_card = Card.objects.get(pk=card.pk)
        first_computing = threading.Event()
        second_started = threading.Event()
        second_computing = threading.Event()
        release_first = threading.Event()
        failures = []
        original_compute = srs.compute

        def observed_compute(**kwargs):
            if threading.current_thread().name == "first-review":
                first_computing.set()
                if not release_first.wait(timeout=10):
                    raise TimeoutError("First review was not released")
            else:
                second_computing.set()
            return original_compute(**kwargs)

        def run_review(instance, *, second=False):
            try:
                if second:
                    second_started.set()
                srs.review(instance, Rating.GOOD)
            except BaseException as exc:
                failures.append(exc)
            finally:
                connections.close_all()

        first = threading.Thread(
            target=run_review, args=(card,), name="first-review"
        )
        second = threading.Thread(
            target=run_review,
            args=(stale_card,),
            kwargs={"second": True},
            name="second-review",
        )
        with patch("study.srs.compute", side_effect=observed_compute):
            first.start()
            try:
                self.assertTrue(first_computing.wait(timeout=10))
                second.start()
                self.assertTrue(second_started.wait(timeout=10))
                self.assertFalse(second_computing.wait(timeout=0.2))
            finally:
                release_first.set()
                first.join(timeout=10)
                if second.ident is not None:
                    second.join(timeout=10)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(failures, [])
        self.assertTrue(second_computing.is_set())
        card.refresh_from_db()
        self.assertEqual(card.reps, 2)
        self.assertEqual(card.state, CardState.REVIEW)
        self.assertEqual(
            list(card.reviews.order_by("pk").values_list("state_before", flat=True)),
            [CardState.NEW, CardState.LEARNING],
        )


class ScopedQueueReliabilityTests(TestCase):
    def setUp(self):
        self.user = factories.make_user()

    def test_spine_lot_revisit_counts_do_not_repartition_flagged_cards(self):
        cards = [factories.make_spine_card(user=self.user) for _ in range(16)]
        Card.objects.filter(pk__in=[cards[0].pk, cards[15].pk]).update(
            needs_revisit=True
        )
        for batch in ("1", "2"):
            with self.subTest(batch=batch):
                counts = queue.queue_counts(
                    {"kind": "spine", "batch": batch}, user=self.user
                )
                self.assertEqual(counts["revisit_total"], 1)

    def test_vocabulary_lot_revisit_counts_keep_phrase_twins_together(self):
        cards = []
        for _ in range(11):
            phrase = factories.make_phrase()
            cards.append(factories.make_phrase_card(user=self.user, phrase=phrase))
            factories.make_phrase_card(
                user=self.user, phrase=phrase, card_type="phrase_recog"
            )
        Card.objects.filter(phrase_id=cards[-1].phrase_id).update(needs_revisit=True)

        for batch, expected in (("1", 0), ("2", 2)):
            with self.subTest(batch=batch):
                counts = queue.queue_counts(
                    {"kind": "phrase", "batch": batch}, user=self.user
                )
                self.assertEqual(counts["revisit_total"], expected)

    def test_future_calendar_days_do_not_count_as_today(self):
        now = timezone.now()
        tomorrow = timezone.localtime(now).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        card = factories.make_spine_card(user=self.user)
        for reviewed_at in (now, tomorrow):
            ReviewLog.objects.create(
                user=self.user,
                card=card,
                reviewed_at=reviewed_at,
                rating=Rating.GOOD,
                state_before=CardState.NEW,
                state_after=CardState.LEARNING,
            )

        counts = queue.queue_counts({"kind": "spine"}, now=now, user=self.user)
        self.assertEqual(counts["new_done_today"], 1)


class RecentSessionReliabilityTests(TestCase):
    def test_long_session_is_not_truncated_at_a_fetch_batch(self):
        user = factories.make_user()
        card = factories.make_spine_card(user=user)
        now = timezone.now()
        ReviewLog.objects.bulk_create([
            ReviewLog(
                user=user,
                card=card,
                reviewed_at=now - timedelta(seconds=index),
                rating=Rating.GOOD,
                state_before=CardState.REVIEW,
                state_after=CardState.REVIEW,
                elapsed_ms=1000,
            )
            for index in range(401)
        ])
        ReviewLog.objects.create(
            user=user,
            card=card,
            reviewed_at=now - timedelta(hours=2),
            rating=Rating.AGAIN,
            state_before=CardState.REVIEW,
            state_after=CardState.RELEARNING,
        )

        sessions = recent_review_sessions(ReviewLog.objects.filter(user=user))
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0]["review_count"], 401)
        self.assertEqual(sessions[0]["elapsed_ms"], 401000)
        self.assertEqual(sessions[0]["started_at"], now - timedelta(seconds=400))
        self.assertEqual(sessions[1]["review_count"], 1)
        self.assertEqual(
            recent_review_sessions(ReviewLog.objects.filter(user=user), limit=1),
            sessions[:1],
        )


class WritingProgressReliabilityTests(TestCase):
    def test_model_edits_start_subject_and_aggregate_progress_for_the_owner(self):
        user = factories.make_user()
        other = factories.make_user()
        sujet = factories.make_writing_sujet()
        WritingResponseOverride.objects.create(
            user=user,
            sujet=sujet,
            version_key="model-1",
            body="My saved revision.",
        )

        progress = writing_sujet_progress_by_id(user, [sujet.pk])[sujet.pk]
        self.assertEqual(progress.status, "active")
        self.assertEqual(progress.started, 1)
        self.assertEqual(progress.completed, 0)
        self.assertFalse(progress.is_personalized)
        self.assertFalse(progress.explicitly_completed)
        self.assertEqual(
            writing_sujet_progress_by_id(other, [sujet.pk])[sujet.pk].started, 0
        )

        direct = _ee_writing_task_card(sujet.task, user)["stats"]["progress"]
        grouped = expression_task_summaries(
            timezone.now(), user, [sujet.task]
        )[sujet.task_id]["stats"]["progress"]
        for summary in (direct, grouped):
            self.assertEqual(summary.started, 1)
            self.assertEqual(summary.completed, 0)
            self.assertEqual(summary.status, "active")


class ReviewPresentationReliabilityTests(TestCase):
    def setUp(self):
        self.user = factories.make_user()
        self.client.force_login(self.user)
        self.card = factories.make_spine_card(user=self.user)

    def _present(self):
        response = self.client.get(reverse("study:review_next"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["card_id"], self.card.pk)
        return response.json()["presentation_token"]

    def test_non_ascii_token_is_a_conflict_not_a_server_error(self):
        token = self._present()
        response = self.client.post(
            reverse("study:review_answer"),
            {
                "card_id": self.card.pk,
                "action": "correct",
                "presentation_token": "\N{LATIN SMALL LETTER E WITH ACUTE}",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "stale_presentation")
        self.assertEqual(ReviewSession.load(self.user).presentation_token, token)
        self.assertFalse(ReviewLog.objects.exists())
