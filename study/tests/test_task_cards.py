"""Task card content counts: values, batching, and query budget."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from study.models import (
    Phrase,
    PhraseCategory,
    PhraseTier,
    Prompt,
    Task,
    Theme,
    WritingSujet,
)
from study.views.helpers import (
    FUNCTIONAL_PHRASE_CATEGORY_NAMES,
    _task_card,
    _task_content_counts,
    _task_phrases,
)

from . import factories


def legacy_task_counts(task):
    """The per-task queries the card used to run, kept as the reference."""
    return {
        "theme_count": Theme.objects.filter(task=task, is_active=True).count(),
        "prompt_count": Prompt.objects.filter(
            theme__task=task,
            is_active=True,
        ).count(),
        "phrase_count": _task_phrases(task).count(),
        "functional_phrase_count": _task_phrases(task)
        .filter(category__name__in=FUNCTIONAL_PHRASE_CATEGORY_NAMES)
        .count(),
        "subject_vocabulary_count": Phrase.objects.filter(
            is_active=True,
            tier=PhraseTier.SUBJECT,
            source_prompts__is_active=True,
            source_prompts__theme__is_active=True,
            source_prompts__theme__task=task,
        )
        .distinct()
        .count(),
        "subject_vocabulary_prompt_count": Prompt.objects.filter(
            is_active=True,
            response__is_active=True,
            theme__is_active=True,
            theme__task=task,
            phrases__is_active=True,
            phrases__tier=PhraseTier.SUBJECT,
        )
        .distinct()
        .count(),
        "theme_vocabulary_count": Phrase.objects.filter(
            is_active=True,
            tier=PhraseTier.THEME,
            source_prompts__is_active=True,
            source_prompts__theme__is_active=True,
            source_prompts__theme__task=task,
        )
        .distinct()
        .count(),
    }


class TaskContentCountsTests(TestCase):
    """The batched counts must equal the per-task counts they replaced."""

    def setUp(self):
        self.user = factories.make_user("counts")
        self.part = factories.make_part("eo")
        self.functional_category = PhraseCategory.objects.create(
            slug="nuancer-et-comparer",
            name="Nuancer et comparer",
            content_key="test-category:nuancer-et-comparer",
            order=90,
        )
        self.tasks = [
            self._task_with_content("tache-2", themes=2, responses=3),
            self._task_with_content("tache-3", themes=1, responses=2),
        ]
        self.empty_task = factories.make_task(self.part, "tache-4")
        self.unavailable_task = factories.make_task(
            self.part,
            "tache-5",
            available=False,
        )
        factories.make_theme("indisponible", task=self.unavailable_task)
        factories.make_spine_card(
            theme=Theme.objects.get(slug="indisponible"),
            user=self.user,
        )

    def _task_with_content(self, slug, *, themes, responses):
        task = factories.make_task(self.part, slug)
        for theme_index in range(themes):
            theme = factories.make_theme(
                f"{slug}-theme-{theme_index}",
                task=task,
            )
            for _ in range(responses):
                response = factories.make_response(theme=theme)
                prompt = response.prompts.first()
                shared = factories.make_phrase(tier=PhraseTier.SHARED)
                shared.source_prompts.add(prompt)
                functional = factories.make_phrase(
                    category=self.functional_category,
                    tier=PhraseTier.SHARED,
                )
                functional.source_prompts.add(prompt)
                subject = factories.make_phrase(tier=PhraseTier.SUBJECT)
                subject.source_prompts.add(prompt)
                theme_phrase = factories.make_phrase(tier=PhraseTier.THEME)
                theme_phrase.source_prompts.add(prompt)
        return task

    def test_batched_counts_match_the_per_task_counts(self):
        tasks = [*self.tasks, self.empty_task]
        counts = _task_content_counts(tasks)

        for task in tasks:
            with self.subTest(task=task.slug):
                expected = legacy_task_counts(task)
                actual = {key: counts[task.pk][key] for key in expected}
                self.assertEqual(actual, expected)

    def test_counts_are_populated_rather_than_zero(self):
        counts = _task_content_counts(self.tasks)[self.tasks[0].pk]

        self.assertEqual(counts["theme_count"], 2)
        self.assertEqual(counts["prompt_count"], 6)
        self.assertEqual(counts["phrase_count"], 12)
        self.assertEqual(counts["functional_phrase_count"], 6)
        self.assertEqual(counts["subject_vocabulary_count"], 6)
        self.assertEqual(counts["subject_vocabulary_prompt_count"], 6)
        self.assertEqual(counts["theme_vocabulary_count"], 6)

    def test_unavailable_tasks_read_as_zero_without_querying(self):
        with self.assertNumQueries(0):
            counts = _task_content_counts([self.unavailable_task])

        self.assertEqual(
            counts[self.unavailable_task.pk],
            {
                "theme_count": 0,
                "prompt_count": 0,
                "phrase_count": 0,
                "functional_phrase_count": 0,
                "subject_vocabulary_count": 0,
                "subject_vocabulary_prompt_count": 0,
                "theme_vocabulary_count": 0,
                "writing_sujet_ids": (),
                "writing_sujet_category_count": 0,
                "writing_sujet_response_count": 0,
            },
        )

    def test_query_count_does_not_grow_with_the_number_of_tasks(self):
        with self.assertNumQueries(4):
            _task_content_counts(self.tasks[:1])

        with self.assertNumQueries(4):
            _task_content_counts([*self.tasks, self.empty_task])

    def test_card_counts_match_whether_batched_or_alone(self):
        now = timezone.now()
        count_keys = (
            "theme_count",
            "prompt_count",
            "phrase_count",
            "functional_phrase_count",
            "subject_vocabulary_count",
            "subject_vocabulary_prompt_count",
            "show_phrases",
        )
        batch = _task_content_counts(self.tasks)

        for task in self.tasks:
            with self.subTest(task=task.slug):
                batched = _task_card(
                    task,
                    now,
                    self.user,
                    content_counts=batch,
                )
                alone = _task_card(task, now, self.user)
                self.assertEqual(
                    {key: batched[key] for key in count_keys},
                    {key: alone[key] for key in count_keys},
                )

    def test_card_falls_back_to_its_own_lookup_without_a_batch(self):
        card = _task_card(self.tasks[0], timezone.now(), self.user)

        self.assertEqual(card["theme_count"], 2)
        self.assertEqual(card["prompt_count"], 6)
        self.assertEqual(card["phrase_count"], 12)

    def test_unavailable_task_card_reports_zero_counts(self):
        card = _task_card(self.unavailable_task, timezone.now(), self.user)

        self.assertEqual(card["theme_count"], 0)
        self.assertEqual(card["prompt_count"], 0)
        self.assertEqual(card["phrase_count"], 0)
        self.assertEqual(card["subject_vocabulary_count"], 0)
        self.assertIsNone(card["stats"])


class WritingSujetCardCountsTests(TestCase):
    """EE Tâche 1 counts come from the same batch as every other card."""

    def setUp(self):
        self.user = factories.make_user("writer")
        self.part = factories.make_part("ee")
        self.task = factories.make_task(self.part, "tache-1")
        for category, category_label, versions in (
            ("invitations", "Invitations", ("Bonjour, viens samedi.",)),
            ("invitations", "Invitations", ()),
            ("excuses", "Excuses", ("Je suis désolé pour hier.",)),
        ):
            factories.make_writing_sujet(
                self.task,
                category=category,
                category_label=category_label,
                versions=versions,
            )
        factories.make_writing_sujet(
            self.task,
            category="archives",
            category_label="Archives",
            is_active=False,
        )

    def test_batched_writing_counts(self):
        counts = _task_content_counts([self.task])[self.task.pk]

        self.assertEqual(
            sorted(counts["writing_sujet_ids"]),
            sorted(
                WritingSujet.objects.filter(
                    task=self.task,
                    is_active=True,
                ).values_list("pk", flat=True)
            ),
        )
        self.assertEqual(counts["writing_sujet_category_count"], 2)
        self.assertEqual(counts["writing_sujet_response_count"], 2)

    def test_writing_card_matches_the_unbatched_card(self):
        now = timezone.now()
        batch = _task_content_counts([self.task])

        batched = _task_card(self.task, now, self.user, content_counts=batch)
        alone = _task_card(self.task, now, self.user)

        self.assertEqual(batched["theme_count"], 2)
        self.assertEqual(batched["prompt_count"], 3)
        self.assertEqual(batched["response_stats"], {"total": 2})
        self.assertEqual(batched["stats"]["total"], alone["stats"]["total"])
        self.assertEqual(batched["theme_count"], alone["theme_count"])
        self.assertEqual(batched["prompt_count"], alone["prompt_count"])
        self.assertEqual(batched["response_stats"], alone["response_stats"])

    def test_writing_sujets_add_two_queries_to_a_batch(self):
        other = factories.make_task(factories.make_part("eo"), "tache-3")
        factories.make_theme("culture-batch", task=other)

        with self.assertNumQueries(4):
            _task_content_counts([other])

        with self.assertNumQueries(6):
            _task_content_counts([other, self.task])


class TaskCardQueryBudgetTests(TestCase):
    """Pages must fetch content counts once, not once per task."""

    def setUp(self):
        self.user = factories.make_user("budget")
        self.client.force_login(self.user)
        self.part = factories.make_part("eo")
        self.tasks = [
            self._task_with_content("tache-2"),
            self._task_with_content("tache-3"),
        ]

    def _task_with_content(self, slug):
        task = factories.make_task(self.part, slug)
        theme = factories.make_theme(f"{slug}-theme", task=task)
        response = factories.make_spine_card(theme=theme, user=self.user).response
        phrase = factories.make_phrase(tier=PhraseTier.SHARED)
        phrase.source_prompts.add(response.prompts.first())
        factories.make_phrase_card(phrase=phrase, user=self.user)
        return task

    def _query_count(self, url):
        self.client.get(url)  # warm the content loader caches
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries)

    def _unbatched_query_count(self, url, view_module):
        """Query count for the same page with the batch turned off.

        An empty mapping sends every card back to looking its own counts up,
        which is what the per-task version of ``_task_card`` used to do.
        """
        with patch(
            f"study.views.{view_module}._task_content_counts",
            return_value={},
        ):
            return self._query_count(url)

    def test_dashboard_batches_content_counts_once(self):
        with patch(
            "study.views.dashboard._task_content_counts",
            wraps=_task_content_counts,
        ) as batched:
            self.client.get(reverse("study:dashboard"))
            self.client.get(reverse("study:expression"))

        self.assertEqual(batched.call_count, 2)
        for call in batched.call_args_list:
            tasks = list(call.args[0])
            self.assertEqual(
                sorted(task.pk for task in tasks),
                sorted(
                    Task.objects.filter(
                        is_active=True,
                        part__is_active=True,
                    ).values_list("pk", flat=True)
                ),
            )

    def test_part_detail_batches_content_counts_once(self):
        with patch(
            "study.views.library._task_content_counts",
            wraps=_task_content_counts,
        ) as batched:
            self.client.get(
                reverse("study:part_detail", args=[self.part.slug])
            )

        self.assertEqual(batched.call_count, 1)

    def test_extra_tasks_do_not_add_content_count_queries(self):
        """Extra tasks may add user progress queries, never content counts."""
        pages = [
            (reverse("study:dashboard"), "dashboard"),
            (reverse("study:expression"), "dashboard"),
            (reverse("study:part_detail", args=[self.part.slug]), "library"),
        ]
        before = {url: self._query_count(url) for url, _ in pages}

        added_tasks = 2
        self._task_with_content("tache-4")
        self._task_with_content("tache-5")

        for url, view_module in pages:
            with self.subTest(url=url):
                growth = self._query_count(url) - before[url]
                unbatched_growth = (
                    self._unbatched_query_count(url, view_module)
                    - before[url]
                )
                self.assertLessEqual(
                    growth,
                    unbatched_growth - 4 * added_tasks,
                )
