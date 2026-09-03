"""Query budgets and legacy-equality proofs for the audited page families.

Each optimization has two guards here: an absolute budget (or a no-growth
check) so a regression is visible, and an equality check against the query
shape it replaced so the numbers cannot drift.
"""

from __future__ import annotations

from django.db import connection
from django.db.models import Count, Q
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from study import queue as queue_module
from study.models import (
    Annotation,
    AnnotationKind,
    Card,
    CardState,
    CardType,
    ComprehensionMode,
    ComprehensionTest,
    MemoryQuestionProgress,
    PersonalResponse,
    Phrase,
    PhraseCategory,
    PhraseTier,
    Prompt,
    Rating,
    Response,
    ReviewLog,
    Task,
    Theme,
)
from study.progress import card_unit_progress, subject_progress_by_response
from study.views.helpers import (
    _review_batches,
    current_streak,
    deck_stats,
    review_day_counts,
)
from study.views.library import _distinct_count

from . import factories


def legacy_current_streak(now, user):
    """The streak as it was computed before the day grouping."""
    days = {
        timezone.localtime(moment).date()
        for moment in ReviewLog.objects.filter(user=user).values_list(
            "reviewed_at",
            flat=True,
        )
    }
    if not days:
        return 0
    today = timezone.localtime(now).date()
    cursor = today
    if cursor not in days:
        cursor = today - timezone.timedelta(days=1)
        if cursor not in days:
            return 0
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timezone.timedelta(days=1)
    return streak


def legacy_forecast(active_cards, today):
    """The fourteen per-day counts the stats page used to run separately."""
    active = active_cards.filter(
        state__in=[CardState.REVIEW, CardState.LEARNING, CardState.RELEARNING]
    )
    forecast = []
    for offset in range(0, 14):
        day = today + timezone.timedelta(days=offset)
        start = timezone.make_aware(
            timezone.datetime.combine(day, timezone.datetime.min.time())
        )
        end = start + timezone.timedelta(days=1)
        if offset == 0:
            count = active.filter(due__lt=end).count()
        else:
            count = active.filter(due__gte=start, due__lt=end).count()
        forecast.append({"date": day, "count": count})
    return forecast


class QueryBudgetTestCase(TestCase):
    """Shared plumbing: a logged-in learner and a warm query counter."""

    def _query_count(self, url):
        self.client.get(url)  # warm the content-loader caches
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return len(ctx.captured_queries)

    def _queries(self, url):
        self.client.get(url)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        return response, ctx.captured_queries


class ExpressionPageBudgetTests(QueryBudgetTestCase):
    """Part, task, browse, review hub and stats pages of one task family."""

    def setUp(self):
        self.user = factories.make_user("budgets")
        self.client.force_login(self.user)
        self.part = factories.make_part("eo")
        self.task = factories.make_task(self.part, "tache-3")
        self.functional_category = PhraseCategory.objects.create(
            slug="budget-nuancer-et-comparer",
            name="Nuancer et comparer",
            content_key="test-category:budget-nuancer",
            order=10,
        )
        self.themes = [
            self._theme_with_content(f"theme-{index}", responses=3)
            for index in range(3)
        ]

    def _theme_with_content(self, slug, *, responses):
        theme = factories.make_theme(slug, task=self.task)
        for _ in range(responses):
            card = factories.make_spine_card(theme=theme, user=self.user)
            prompt = card.response.prompts.first()
            shared = factories.make_phrase(
                tier=PhraseTier.SHARED,
                category=self.functional_category,
            )
            shared.source_prompts.add(prompt)
            factories.make_phrase_card(phrase=shared, user=self.user)
            subject = factories.make_phrase(tier=PhraseTier.SUBJECT)
            subject.source_prompts.add(prompt)
            factories.make_phrase_card(phrase=subject, user=self.user)
        return theme

    def _add_theme(self, slug):
        return self._theme_with_content(slug, responses=3)

    def _pages(self):
        args = [self.part.slug, self.task.slug]
        return {
            "part": reverse("study:part_detail", args=[self.part.slug]),
            "task": reverse("study:task_detail", args=args),
            "browse": reverse("study:task_browse", args=args),
            "review_hub": reverse("study:task_review_hub", args=args),
            "task_stats": reverse("study:task_stats", args=args),
            "part_stats": reverse("study:part_stats", args=[self.part.slug]),
            "stats": reverse("study:stats"),
            "vocabulary": reverse("study:task_phrases", args=args),
            "revisit": reverse("study:task_revisit_list", args=args),
        }

    def test_absolute_query_budgets(self):
        budgets = {
            "part": 22,
            "task": 20,
            "browse": 24,
            "review_hub": 18,
            "task_stats": 22,
            "part_stats": 22,
            "stats": 22,
            "vocabulary": 20,
            "revisit": 12,
        }
        for key, url in self._pages().items():
            with self.subTest(page=key):
                self.assertLessEqual(self._query_count(url), budgets[key])

    def test_query_count_does_not_grow_with_more_themes(self):
        pages = self._pages()
        before = {key: self._query_count(url) for key, url in pages.items()}

        self._add_theme("theme-extra-1")
        self._add_theme("theme-extra-2")

        for key, url in pages.items():
            with self.subTest(page=key):
                self.assertEqual(self._query_count(url), before[key])

    def test_query_count_does_not_grow_with_more_tasks(self):
        pages = self._pages()
        before = {key: self._query_count(url) for key, url in pages.items()}

        for slug in ("tache-4", "tache-5"):
            other = factories.make_task(self.part, slug)
            theme = factories.make_theme(f"{slug}-theme", task=other)
            factories.make_spine_card(theme=theme, user=self.user)

        for key, url in pages.items():
            with self.subTest(page=key):
                self.assertEqual(self._query_count(url), before[key])


class ReviewHubEqualityTests(TestCase):
    """The batched theme rows must equal the per-theme queries they replaced."""

    def setUp(self):
        self.user = factories.make_user("review-hub")
        self.client.force_login(self.user)
        self.part = factories.make_part("eo")
        self.task = factories.make_task(self.part, "tache-3")
        self.now = timezone.now()
        self.themes = []
        for index in range(3):
            theme = factories.make_theme(f"hub-theme-{index}", task=self.task)
            self.themes.append(theme)
            for card_index in range(3):
                card = factories.make_spine_card(theme=theme, user=self.user)
                if card_index == 0:
                    Card.objects.filter(pk=card.pk).update(
                        state=CardState.REVIEW,
                        interval_days=40,
                        due=self.now - timezone.timedelta(days=1),
                        started_at=self.now,
                    )
                elif card_index == 1:
                    Card.objects.filter(pk=card.pk).update(
                        state=CardState.LEARNING,
                        due=self.now - timezone.timedelta(minutes=5),
                        started_at=self.now,
                    )
        # A theme with no cards at all must still be listed.
        self.empty_theme = factories.make_theme("hub-empty", task=self.task)
        self.themes.append(self.empty_theme)

    def test_theme_rows_match_the_per_theme_queries(self):
        url = reverse(
            "study:task_review_hub",
            args=[self.part.slug, self.task.slug],
        )
        response = self.client.get(url)
        rows = {
            item["theme"].pk: item for item in response.context["themes"]
        }

        self.assertEqual(
            [item["theme"].pk for item in response.context["themes"]],
            list(
                Theme.objects.filter(
                    task=self.task,
                    is_active=True,
                ).values_list("pk", flat=True)
            ),
        )
        for theme in self.themes:
            with self.subTest(theme=theme.slug):
                scope = {
                    "part": self.part.slug,
                    "task": self.task.slug,
                    "kind": "spine",
                    "theme": theme.slug,
                }
                cards = queue_module.scoped_cards(scope, user=self.user)
                expected_stats = deck_stats(cards, self.now)
                expected_counts = queue_module.queue_counts(
                    scope,
                    self.now,
                    user=self.user,
                )
                row = rows[theme.pk]
                self.assertEqual(
                    {
                        key: row["stats"][key]
                        for key in expected_stats
                        if key != "due"
                    },
                    {
                        key: value
                        for key, value in expected_stats.items()
                        if key != "due"
                    },
                )
                self.assertEqual(
                    row["counts"]["total_due"],
                    expected_counts["total_due"],
                )
                self.assertEqual(
                    row["review_url"],
                    reverse("study:task_review", args=[
                        self.part.slug,
                        self.task.slug,
                    ]) + "?kind=spine&theme=" + theme.slug,
                )

    def test_weak_and_revisit_counts_match_the_queue_summary(self):
        card = Card.objects.filter(
            user=self.user,
            card_type=CardType.SPINE,
        ).first()
        Card.objects.filter(pk=card.pk).update(
            needs_revisit=True,
            state=CardState.REVIEW,
            last_rating=Rating.AGAIN,
            revisit_added_at=self.now,
        )
        scope = {"part": self.part.slug, "task": self.task.slug}

        response = self.client.get(
            reverse(
                "study:task_review_hub",
                args=[self.part.slug, self.task.slug],
            )
        )

        self.assertEqual(
            response.context["weak_count"],
            queue_module.queue_counts(
                {**scope, "kind": "weak", "content": "spine"},
                self.now,
                user=self.user,
            )["weak_total"],
        )
        self.assertEqual(
            response.context["revisit_count"],
            queue_module.scoped_cards(
                {**scope, "kind": "revisit", "content": "spine"},
                user=self.user,
            ).count(),
        )


class ThemeVocabularyDirectoryEqualityTests(TestCase):
    """Batched theme lots must equal the per-theme lots they replaced."""

    def setUp(self):
        self.user = factories.make_user("theme-vocab")
        self.client.force_login(self.user)
        self.part = factories.make_part("eo")
        self.task = factories.make_task(self.part, "tache-3")
        self.category = PhraseCategory.objects.create(
            slug="theme-notions",
            name="Thème · Notions clés",
            content_key="test-category:notions",
            order=1,
        )
        self.themes = []
        for index in range(3):
            theme = factories.make_theme(f"vocab-theme-{index}", task=self.task)
            self.themes.append(theme)
            response = factories.make_response(theme=theme)
            prompt = response.prompts.first()
            for phrase_index in range(12):
                phrase = factories.make_phrase(
                    tier=PhraseTier.THEME,
                    category=self.category,
                    lot_order=phrase_index,
                )
                phrase.source_prompts.add(prompt)
                factories.make_phrase_card(phrase=phrase, user=self.user)
        # One phrase shared by two themes must land in both decks.
        self.shared = factories.make_phrase(
            tier=PhraseTier.THEME,
            category=self.category,
            lot_order=99,
        )
        for theme in self.themes[:2]:
            self.shared.source_prompts.add(
                Prompt.objects.filter(theme=theme).first()
            )
        factories.make_phrase_card(phrase=self.shared, user=self.user)

    def _batch_signature(self, batches):
        return [
            (
                batch["number"],
                batch["start"],
                batch["end"],
                batch["card_count"],
                batch["phrase_count"],
                batch["active_count"],
                batch["completed_count"],
                batch["started_count"],
                batch["available_now"],
                batch["status"],
                batch["is_next"],
                batch["review_url"],
            )
            for batch in batches
        ]

    def test_directory_lots_match_the_per_theme_lots(self):
        from study.views.library import _theme_vocabulary_directory_batches

        task_batches, by_theme = _theme_vocabulary_directory_batches(
            self.task,
            self.user,
            self.themes,
        )

        self.assertEqual(
            self._batch_signature(task_batches),
            self._batch_signature(
                _review_batches(
                    {
                        "kind": "theme_vocab",
                        "part": self.part.slug,
                        "task": self.task.slug,
                    },
                    self.user,
                )
            ),
        )
        for theme in self.themes:
            with self.subTest(theme=theme.slug):
                expected = _review_batches(
                    {
                        "kind": "theme_vocab",
                        "part": self.part.slug,
                        "task": self.task.slug,
                        "theme": theme.slug,
                    },
                    self.user,
                )
                self.assertEqual(
                    self._batch_signature(by_theme[theme.slug]),
                    self._batch_signature(expected),
                )

    def test_directory_costs_a_fixed_number_of_queries(self):
        from study.views.library import _theme_vocabulary_directory_batches

        with self.assertNumQueries(2):
            _theme_vocabulary_directory_batches(
                self.task,
                self.user,
                self.themes[:1],
            )

        with self.assertNumQueries(2):
            _theme_vocabulary_directory_batches(
                self.task,
                self.user,
                self.themes,
            )


class ComprehensionVocabularyDirectoryTests(TestCase):
    """The batched deck rows must equal the per-test queries they replaced."""

    def setUp(self):
        self.user = factories.make_user("comprehension-vocab")
        self.client.force_login(self.user)
        self.now = timezone.now()
        self.category = PhraseCategory.objects.create(
            slug="comprehension-mots",
            name="Compréhension · Mots",
            content_key="test-category:comprehension",
            order=1,
        )
        self.tests = [
            factories.make_comprehension_test(number=number, question_count=2)
            for number in (1, 2, 3)
        ]
        self.phrases = []
        for index, test in enumerate(self.tests):
            question = test.questions.first()
            for phrase_index in range(12):
                phrase = factories.make_phrase(
                    tier=PhraseTier.COMPREHENSION,
                    category=self.category,
                    lot_order=phrase_index,
                )
                phrase.source_questions.add(question)
                card = factories.make_phrase_card(
                    phrase=phrase,
                    user=self.user,
                )
                if phrase_index % 4 == 0:
                    Card.objects.filter(pk=card.pk).update(
                        state=CardState.REVIEW,
                        interval_days=40,
                        due=self.now - timezone.timedelta(days=1),
                        started_at=self.now,
                    )
                elif phrase_index % 4 == 1:
                    Card.objects.filter(pk=card.pk).update(
                        state=CardState.LEARNING,
                        due=self.now - timezone.timedelta(minutes=5),
                        started_at=self.now,
                        needs_revisit=True,
                    )
                self.phrases.append(phrase)
        # One entry shared by the first two tests must appear in both decks and
        # in neither of the others.
        self.shared = factories.make_phrase(
            tier=PhraseTier.COMPREHENSION,
            category=self.category,
            lot_order=99,
        )
        for test in self.tests[:2]:
            self.shared.source_questions.add(test.questions.first())
        factories.make_phrase_card(phrase=self.shared, user=self.user)
        # A shared-tier entry owns both a production and a recognition card,
        # and the revisit list counts cards rather than phrases.
        self.two_way = factories.make_phrase(
            tier=PhraseTier.SHARED,
            category=self.category,
            lot_order=98,
        )
        self.two_way.source_questions.add(self.tests[0].questions.first())
        for card_type in (
            CardType.PHRASE_PRODUCTION,
            CardType.PHRASE_RECOGNITION,
        ):
            card = factories.make_phrase_card(
                card_type=card_type,
                phrase=self.two_way,
                user=self.user,
            )
            Card.objects.filter(pk=card.pk).update(
                needs_revisit=True,
                state=CardState.REVIEW,
                due=self.now - timezone.timedelta(days=1),
            )

    def _decks(self):
        from study.views.library import _comprehension_vocabulary_decks

        tests = list(
            ComprehensionTest.objects.filter(is_active=True, is_published=True)
            .annotate(
                vocabulary_count=Count(
                    "questions__vocabulary",
                    filter=Q(
                        questions__vocabulary__is_active=True,
                        questions__vocabulary__tier=PhraseTier.COMPREHENSION,
                    ),
                    distinct=True,
                )
            )
            .filter(vocabulary_count__gt=0)
            .order_by("mode", "number")
        )
        return tests, _comprehension_vocabulary_decks(tests, self.user, self.now)

    def test_deck_rows_match_the_per_test_queries(self):
        tests, decks = self._decks()
        decks_by_test = {deck["test"].pk: deck for deck in decks}

        for test in tests:
            with self.subTest(test=test.slug):
                scope = {"kind": "vocab", "test": test.slug}
                cards = queue_module.scoped_cards(scope, user=self.user)
                expected_batches = _review_batches(scope, self.user)
                expected_counts = queue_module.queue_counts(
                    scope,
                    self.now,
                    user=self.user,
                )
                deck = decks_by_test[test.pk]
                self.assertEqual(deck["batch_count"], len(expected_batches))
                self.assertEqual(
                    deck["completed_batch_count"],
                    sum(
                        batch["status"] == "complete"
                        for batch in expected_batches
                    ),
                )
                self.assertEqual(
                    deck["progress"],
                    card_unit_progress(cards),
                )
                self.assertEqual(deck["stats"], deck_stats(cards, self.now))
                for key, value in deck["counts"].items():
                    self.assertEqual(value, expected_counts[key], key)

    def test_shared_entries_do_not_leak_between_tests(self):
        _tests, decks = self._decks()
        decks_by_slug = {deck["test"].slug: deck for deck in decks}

        for slug in ("test-1", "test-2"):
            self.assertEqual(decks_by_slug[slug]["counts"]["scoped_total"], 13)
        self.assertEqual(decks_by_slug["test-3"]["counts"]["scoped_total"], 12)

    def test_directory_query_count_does_not_grow_with_more_tests(self):
        url = reverse("study:comprehension_vocabulary")
        self.client.get(url)
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        before = len(ctx.captured_queries)

        extra = factories.make_comprehension_test(number=9, question_count=2)
        question = extra.questions.first()
        for phrase_index in range(12):
            phrase = factories.make_phrase(
                tier=PhraseTier.COMPREHENSION,
                category=self.category,
                lot_order=phrase_index,
            )
            phrase.source_questions.add(question)
            factories.make_phrase_card(phrase=phrase, user=self.user)

        self.client.get(url)  # re-warm the slug -> mode cache
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(len(ctx.captured_queries), before)

    def test_directory_and_test_pages_stay_within_budget(self):
        pages = {
            "directory": reverse("study:comprehension_vocabulary"),
            "test": reverse(
                "study:comprehension_test_vocabulary",
                args=["test-1"],
            ),
            "test_detail": reverse("study:comprehension_test", args=["test-1"]),
        }
        budgets = {"directory": 12, "test": 20, "test_detail": 12}
        for key, url in pages.items():
            with self.subTest(page=key):
                self.client.get(url)
                with CaptureQueriesContext(connection) as ctx:
                    self.assertEqual(self.client.get(url).status_code, 200)
                self.assertLessEqual(len(ctx.captured_queries), budgets[key])


class ComprehensionTestDetailScopeTests(TestCase):
    """The detail page loads only the test it renders."""

    def setUp(self):
        self.user = factories.make_user("test-detail")
        self.client.force_login(self.user)
        self.tests = [
            factories.make_comprehension_test(number=number, question_count=2)
            for number in (1, 2, 3)
        ]
        self.archived = factories.make_comprehension_test(
            number=4,
            question_count=2,
        )
        factories.make_comprehension_attempt(
            user=self.user,
            test=self.archived,
        )
        ComprehensionTest.objects.filter(pk=self.archived.pk).update(
            is_active=False,
        )

    def test_detail_query_count_does_not_grow_with_more_tests(self):
        url = reverse("study:comprehension_test", args=["test-1"])
        self.client.get(url)
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        before = len(ctx.captured_queries)

        for number in (5, 6, 7, 8):
            factories.make_comprehension_test(
                number=number,
                question_count=2,
            )

        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(len(ctx.captured_queries), before)

    def test_archived_test_with_activity_is_still_reachable(self):
        response = self.client.get(
            reverse("study:comprehension_test", args=[self.archived.slug])
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["test"].has_activity)
        self.assertEqual(response.context["questions"], [])

    def test_marker_counts_match_the_unscoped_pass(self):
        from study.views.comprehension import _comprehension_test_cards

        question = self.tests[0].questions.first()
        self.client.post(
            reverse(
                "study:comprehension_question_study_toggle",
                args=[self.tests[0].slug, question.number],
            ),
            {"marked": "1"},
        )

        scoped = _comprehension_test_cards(
            self.user,
            mode=ComprehensionMode.ECRITE,
            slug=self.tests[0].slug,
        )
        unscoped = [
            test
            for test in _comprehension_test_cards(
                self.user,
                mode=ComprehensionMode.ECRITE,
            )
            if test.slug == self.tests[0].slug
        ]

        self.assertEqual(len(scoped), 1)
        self.assertEqual(
            scoped[0].study_marked_count,
            unscoped[0].study_marked_count,
        )
        self.assertEqual(
            scoped[0].active_question_count,
            unscoped[0].active_question_count,
        )
        self.assertEqual(
            scoped[0].explicitly_completed,
            unscoped[0].explicitly_completed,
        )
        self.assertEqual(scoped[0].is_accessible, unscoped[0].is_accessible)


class StatsAggregateEqualityTests(TestCase):
    """Stats replaced several loops with aggregates; the numbers must match."""

    def setUp(self):
        self.user = factories.make_user("stats-equality")
        self.client.force_login(self.user)
        self.now = timezone.now()
        self.today = timezone.localtime(self.now).date()
        self.part = factories.make_part("eo")
        self.task = factories.make_task(self.part, "tache-3")
        self.themes = []
        for index in range(3):
            theme = factories.make_theme(f"stats-theme-{index}", task=self.task)
            self.themes.append(theme)
            for card_index in range(4):
                card = factories.make_spine_card(theme=theme, user=self.user)
                Card.objects.filter(pk=card.pk).update(
                    state=CardState.REVIEW,
                    interval_days=40 if card_index else 3,
                    due=self.now + timezone.timedelta(days=card_index - 1),
                    started_at=self.now,
                    last_rating=Rating.GOOD,
                )
                ReviewLog.objects.create(
                    user=self.user,
                    card_id=card.pk,
                    rating=Rating.GOOD if card_index else Rating.AGAIN,
                    state_before=CardState.REVIEW,
                    state_after=CardState.REVIEW,
                    interval_before=40,
                    interval_after=41,
                    ease_before=2.5,
                    ease_after=2.5,
                    reviewed_at=self.now - timezone.timedelta(days=card_index),
                    elapsed_ms=4200,
                )
        Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            body="note",
            created_at=self.now - timezone.timedelta(days=2),
        )
        PersonalResponse.objects.create(
            user=self.user,
            response=Response.objects.first(),
            reformulation="Ma reformulation.",
        )
        MemoryQuestionProgress.objects.create(
            user=self.user,
            memory_number=1,
            question_key="memoire-1:q1",
        )

    def test_forecast_matches_the_per_day_counts(self):
        response = self.client.get(reverse("study:stats"))

        expected = legacy_forecast(
            Card.objects.current_content().filter(
                user=self.user,
                suspended=False,
            ),
            self.today,
        )
        self.assertEqual(response.context["forecast"], expected)
        self.assertEqual(
            response.context["forecast_total"],
            sum(item["count"] for item in expected),
        )

    def test_theme_rows_match_the_per_theme_deck_stats(self):
        response = self.client.get(reverse("study:stats"))
        rows = {item["theme"].pk: item["stats"] for item in response.context["themes"]}

        for theme in self.themes:
            with self.subTest(theme=theme.slug):
                self.assertEqual(
                    rows[theme.pk],
                    deck_stats(
                        Card.objects.active().filter(
                            user=self.user,
                            card_type=CardType.SPINE,
                            response__theme=theme,
                        ),
                        self.now,
                    ),
                )

    def test_weak_counts_match_the_queue_summary(self):
        response = self.client.get(reverse("study:stats"))

        for key, content in (
            ("expression_weak_count", "spine"),
            ("vocabulary_weak_count", "vocabulary"),
        ):
            with self.subTest(key=key):
                self.assertEqual(
                    response.context[key],
                    queue_module.queue_counts(
                        {"kind": "weak", "content": content},
                        self.now,
                        user=self.user,
                    )["weak_total"],
                )

    def test_activity_breakdown_matches_the_per_source_counts(self):
        response = self.client.get(reverse("study:stats"))
        breakdown = {
            item["key"]: item["count"] for item in response.context["breakdown"]
        }

        self.assertEqual(
            breakdown["reviews"],
            ReviewLog.objects.filter(user=self.user).count(),
        )
        self.assertEqual(
            breakdown["notes"],
            Annotation.objects.filter(user=self.user).count(),
        )
        self.assertEqual(
            breakdown["responses"],
            PersonalResponse.objects.filter(user=self.user).count(),
        )
        self.assertEqual(
            breakdown["memories"],
            MemoryQuestionProgress.objects.filter(user=self.user).count(),
        )
        self.assertEqual(
            response.context["total_reviews"],
            ReviewLog.objects.filter(user=self.user).count(),
        )
        self.assertEqual(
            response.context["activity_today"],
            response.context["daily"][-1]["count"],
        )
        self.assertEqual(
            response.context["activity_30_days"],
            sum(item["count"] for item in response.context["daily"]),
        )

    def test_scope_filter_counts_match_the_per_task_counts(self):
        other = factories.make_task(self.part, "tache-2")
        theme = factories.make_theme("stats-other-theme", task=other)
        factories.make_spine_card(theme=theme, user=self.user)
        active = Card.objects.active().filter(
            user=self.user,
            card_type=CardType.SPINE,
        )

        response = self.client.get(
            reverse("study:part_stats", args=[self.part.slug])
        )

        counts = {
            item["slug"]: item["count"]
            for item in response.context["filter_parts"]
        }
        self.assertEqual(
            counts[self.part.slug],
            active.filter(response__theme__task__part=self.part).count(),
        )
        task_counts = {
            item["slug"]: item["count"]
            for item in response.context["active_part_tasks"]
        }
        for task in Task.objects.filter(part=self.part, is_active=True):
            with self.subTest(task=task.slug):
                self.assertEqual(
                    task_counts[task.slug],
                    active.filter(response__theme__task=task).count(),
                )


class StreakAndDayCountTests(TestCase):
    """The grouped review days must reproduce the timestamp scan."""

    def setUp(self):
        self.user = factories.make_user("streak")
        self.now = timezone.localtime(timezone.now()).replace(
            hour=12,
            minute=0,
            second=0,
            microsecond=0,
        )
        theme = factories.make_theme("streak-theme")
        self.card = factories.make_spine_card(theme=theme, user=self.user)

    def _log(self, days_ago, count=1):
        for _ in range(count):
            ReviewLog.objects.create(
                user=self.user,
                card_id=self.card.pk,
                rating=Rating.GOOD,
                state_before=CardState.REVIEW,
                state_after=CardState.REVIEW,
                interval_before=1,
                interval_after=2,
                ease_before=2.5,
                ease_after=2.5,
                reviewed_at=self.now - timezone.timedelta(days=days_ago, hours=2),
                elapsed_ms=1000,
            )

    def test_streak_matches_the_full_history_scan(self):
        for days_ago in (0, 1, 2, 5, 6):
            self._log(days_ago)

        self.assertEqual(
            current_streak(self.now, user=self.user),
            legacy_current_streak(self.now, self.user),
        )
        self.assertEqual(current_streak(self.now, user=self.user), 3)

    def test_streak_is_zero_without_reviews(self):
        self.assertEqual(current_streak(self.now, user=self.user), 0)
        self.assertEqual(
            current_streak(self.now, user=self.user),
            legacy_current_streak(self.now, self.user),
        )

    def test_streak_reads_one_row_per_day(self):
        self._log(0, count=25)
        self._log(1, count=25)

        with self.assertNumQueries(1):
            self.assertEqual(current_streak(self.now, user=self.user), 2)

    def test_day_counts_match_the_per_day_totals(self):
        self._log(0, count=3)
        self._log(2, count=2)

        counts = review_day_counts(user=self.user)
        today = timezone.localtime(self.now).date()

        self.assertEqual(counts[today], 3)
        self.assertEqual(counts[today - timezone.timedelta(days=2)], 2)
        self.assertEqual(sum(counts.values()), 5)


class DashboardBudgetTests(QueryBudgetTestCase):
    """The home page must stay flat as content grows."""

    def setUp(self):
        self.user = factories.make_user("dashboard-budget")
        self.client.force_login(self.user)
        self.part = factories.make_part("eo")
        for slug in ("tache-2", "tache-3"):
            task = factories.make_task(self.part, slug)
            theme = factories.make_theme(f"{slug}-dash", task=task)
            factories.make_spine_card(theme=theme, user=self.user)

    def test_dashboard_and_hub_budgets(self):
        self.assertLessEqual(
            self._query_count(reverse("study:dashboard")),
            26,
        )
        self.assertLessEqual(
            self._query_count(reverse("study:expression")),
            20,
        )

    def test_dashboard_query_count_does_not_grow_with_more_tasks(self):
        pages = [reverse("study:dashboard"), reverse("study:expression")]
        before = {url: self._query_count(url) for url in pages}

        other = factories.make_part("ee")
        for slug in ("tache-4", "tache-5"):
            task = factories.make_task(other, slug)
            theme = factories.make_theme(f"{slug}-extra", task=task)
            factories.make_spine_card(theme=theme, user=self.user)

        for url in pages:
            with self.subTest(url=url):
                self.assertEqual(self._query_count(url), before[url])


class DistinctCountTests(TestCase):
    """The cheap distinct count must equal the wide DISTINCT it replaced."""

    def setUp(self):
        self.user = factories.make_user("distinct-count")
        self.part = factories.make_part("eo")
        self.task = factories.make_task(self.part, "tache-3")
        theme = factories.make_theme("distinct-theme", task=self.task)
        self.phrase = factories.make_phrase(tier=PhraseTier.SHARED)
        for _ in range(3):
            response = factories.make_response(theme=theme)
            self.phrase.source_prompts.add(response.prompts.first())

    def test_matches_distinct_count(self):
        qs = Phrase.objects.filter(
            is_active=True,
            source_prompts__theme__task=self.task,
        )

        self.assertEqual(_distinct_count(qs), qs.distinct().count())
        self.assertEqual(_distinct_count(qs), 1)


class CategoryPhraseCountTests(TestCase):
    """Grouped category counts must equal the per-category counts."""

    def setUp(self):
        self.user = factories.make_user("category-counts")
        self.client.force_login(self.user)
        self.part = factories.make_part("eo")
        self.task = factories.make_task(self.part, "tache-1")
        theme = factories.make_theme("category-theme", task=self.task)
        self.categories = [
            PhraseCategory.objects.create(
                slug=slug,
                name=name,
                content_key=f"test-category:{slug}",
                order=index,
            )
            for index, (slug, name) in enumerate(
                (
                    ("cat-structurer", "Structurer et prendre position"),
                    ("cat-nuancer", "Nuancer et comparer"),
                    ("cat-autre", "Autre catégorie"),
                )
            )
        ]
        for index, category in enumerate(self.categories):
            for _ in range(index + 2):
                response = factories.make_response(theme=theme)
                phrase = factories.make_phrase(
                    tier=PhraseTier.SHARED,
                    category=category,
                )
                phrase.source_prompts.add(response.prompts.first())
                factories.make_phrase_card(phrase=phrase, user=self.user)

    def test_category_counts_match_the_per_category_counts(self):
        response = self.client.get(
            reverse(
                "study:task_phrases",
                args=[self.part.slug, self.task.slug],
            )
        )

        all_phrases = Phrase.objects.filter(
            is_active=True,
            tier=PhraseTier.SHARED,
            source_prompts__theme__task=self.task,
        ).distinct()
        for category in response.context["categories"]:
            with self.subTest(category=category.slug):
                self.assertEqual(
                    category.phrase_count,
                    all_phrases.filter(category=category).count(),
                )

    def test_category_page_lots_match_the_scoped_lots(self):
        category = self.categories[1]
        url = reverse(
            "study:task_vocabulary_category",
            args=[self.part.slug, self.task.slug, category.slug],
        )

        response = self.client.get(url)

        expected = _review_batches(
            {
                "kind": "phrase",
                "part": self.part.slug,
                "task": self.task.slug,
                "category": category.slug,
            },
            self.user,
        )
        self.assertEqual(
            [batch["review_url"] for batch in response.context["review_batches"]],
            [batch["review_url"] for batch in expected],
        )
        self.assertEqual(
            [batch["status"] for batch in response.context["review_batches"]],
            [batch["status"] for batch in expected],
        )

    def test_category_pages_do_not_grow_with_more_categories(self):
        url = reverse(
            "study:task_phrases",
            args=[self.part.slug, self.task.slug],
        )
        self.client.get(url)
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        before = len(ctx.captured_queries)

        theme = Theme.objects.get(slug="category-theme")
        for index in range(3):
            category = PhraseCategory.objects.create(
                slug=f"extra-{index}",
                name=f"Extra {index}",
                content_key=f"test-category:extra-{index}",
                order=10 + index,
            )
            response = factories.make_response(theme=theme)
            phrase = factories.make_phrase(
                tier=PhraseTier.SHARED,
                category=category,
            )
            phrase.source_prompts.add(response.prompts.first())

        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(len(ctx.captured_queries), before)

    def test_category_page_does_not_query_each_phrase_source(self):
        category = self.categories[1]
        url = reverse(
            "study:task_vocabulary_category",
            args=[self.part.slug, self.task.slug, category.slug],
        )
        questions = list(
            factories.make_comprehension_test(
                number=41,
                question_count=12,
            ).questions.all()
        )
        phrases = list(
            Phrase.objects.filter(category=category).order_by("pk")
        )
        for phrase, question in zip(
            phrases,
            questions[: len(phrases)],
            strict=True,
        ):
            phrase.source_questions.add(question)

        self.client.get(url)
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        before = len(ctx.captured_queries)

        theme = Theme.objects.get(slug="category-theme")
        for question in questions[len(phrases) :]:
            response = factories.make_response(theme=theme)
            phrase = factories.make_phrase(
                tier=PhraseTier.SHARED,
                category=category,
            )
            phrase.source_prompts.add(response.prompts.first())
            phrase.source_questions.add(question)
            factories.make_phrase_card(phrase=phrase, user=self.user)

        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(len(ctx.captured_queries), before)
        self.assertLessEqual(before, 18)


class RevisitListBudgetTests(QueryBudgetTestCase):
    """The revisit list resolves every row's link in a fixed query set."""

    def setUp(self):
        self.user = factories.make_user("revisit-budget")
        self.client.force_login(self.user)
        self.part = factories.make_part("eo")
        self.task = factories.make_task(self.part, "tache-3")
        self.theme = factories.make_theme("revisit-theme", task=self.task)
        self._mark(3)

    def _mark(self, count):
        for _ in range(count):
            card = factories.make_spine_card(theme=self.theme, user=self.user)
            Card.objects.filter(pk=card.pk).update(
                needs_revisit=True,
                revisit_added_at=timezone.now(),
            )

    def test_query_count_does_not_grow_with_more_rows(self):
        url = reverse("study:revisit_list")
        before = self._query_count(url)

        self._mark(5)

        self.assertEqual(self._query_count(url), before)
        self.assertLessEqual(before, 12)

    def test_rows_keep_their_titles_and_links(self):
        response = self.client.get(reverse("study:revisit_list"))
        rows = [
            item
            for group in response.context["revisit_groups"]
            for item in group["items"]
        ]

        self.assertEqual(len(rows), 3)
        for item in rows:
            canonical = item["card"].response.canonical_prompt
            self.assertEqual(item["title"], canonical.text)
            self.assertEqual(
                item["url"],
                reverse(
                    "study:response_detail",
                    args=[self.part.slug, self.task.slug, canonical.pk],
                ),
            )


class ResponseDetailLotTests(TestCase):
    """A sujet with no related phrases must not scan the phrase deck."""

    def setUp(self):
        self.user = factories.make_user("response-detail")
        self.client.force_login(self.user)
        self.part = factories.make_part("eo")
        self.task = factories.make_task(self.part, "tache-3")
        self.theme = factories.make_theme("detail-theme", task=self.task)
        self.card = factories.make_spine_card(theme=self.theme, user=self.user)
        self.prompt = self.card.response.prompts.first()

    def _url(self):
        return reverse(
            "study:response_detail",
            args=[self.part.slug, self.task.slug, self.prompt.pk],
        )

    def test_empty_related_phrases_produce_no_lots(self):
        response = self.client.get(self._url())

        self.assertEqual(response.context["phrase_batches"], [])
        self.assertEqual(list(response.context["related_phrases"]), [])
        self.assertEqual(
            response.context["phrase_batches"],
            _review_batches(
                {
                    "part": self.part.slug,
                    "task": self.task.slug,
                    "kind": "phrase",
                    "response": str(self.card.response_id),
                },
                self.user,
            ),
        )

    def test_related_phrases_still_produce_the_same_lots(self):
        phrase = factories.make_phrase(tier=PhraseTier.SHARED)
        phrase.source_prompts.add(self.prompt)
        factories.make_phrase_card(phrase=phrase, user=self.user)

        response = self.client.get(self._url())

        expected = _review_batches(
            {
                "part": self.part.slug,
                "task": self.task.slug,
                "kind": "phrase",
                "response": str(self.card.response_id),
            },
            self.user,
        )
        self.assertEqual(len(response.context["phrase_batches"]), len(expected))
        self.assertEqual(
            [batch["status"] for batch in response.context["phrase_batches"]],
            [batch["status"] for batch in expected],
        )

    def test_page_stays_within_budget(self):
        url = self._url()
        self.client.get(url)
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertLessEqual(len(ctx.captured_queries), 22)


class SubjectProgressHighlightTests(TestCase):
    """Highlight resolution keeps its result and skips work when it can't match."""

    def setUp(self):
        self.user = factories.make_user("subject-progress")
        self.part = factories.make_part("eo")
        self.task = factories.make_task(self.part, "tache-3")
        self.theme = factories.make_theme("highlight-theme", task=self.task)
        self.card = factories.make_spine_card(theme=self.theme, user=self.user)
        self.response = self.card.response

    def test_no_highlights_skips_the_resolution_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            progress = subject_progress_by_response(
                self.user,
                {self.response.pk},
            )

        self.assertFalse(progress[self.response.pk].has_highlight)
        self.assertEqual(len(ctx.captured_queries), 3)

    def test_a_highlight_still_marks_the_subject_as_started(self):
        Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.HIGHLIGHT,
            quote="extrait",
            source_key=f"response:{self.response.content_key}",
            source_path="/expression/orale/tache-3/sujets/1/",
            start_offset=0,
            end_offset=7,
        )

        progress = subject_progress_by_response(self.user, {self.response.pk})

        self.assertTrue(progress[self.response.pk].has_highlight)
        self.assertEqual(progress[self.response.pk].status, "active")
