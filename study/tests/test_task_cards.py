"""Task card content counts: values, batching, and query budget."""

from __future__ import annotations

from unittest.mock import patch

from django.db.models import Prefetch
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from study import content_loader as content_module
from study.models import (
    Annotation,
    AnnotationKind,
    Card,
    CardState,
    CardType,
    ExamPart,
    PersonalWritingResponse,
    Phrase,
    PhraseCategory,
    PhraseTier,
    Prompt,
    Task,
    Theme,
    WritingSujet,
    WritingSujetCompletion,
)
from study.views.dashboard import (
    _home_expression_paths,
    _parts_with_task_summaries,
)
from study.views.helpers import (
    FUNCTIONAL_PHRASE_CATEGORY_NAMES,
    _task_card,
    _task_content_counts,
    _task_phrases,
    expression_task_summaries,
)

from . import factories


def legacy_expression_paths(now, user):
    """The pre-batch expression paths, kept as the reference for the new ones.

    This is what the home page and the expression hub used to run: a full
    :func:`_task_card` per active task, folded into paths by
    :func:`_home_expression_paths`.
    """
    parts = list(
        ExamPart.objects.filter(is_active=True).prefetch_related(
            Prefetch("tasks", queryset=Task.objects.filter(is_active=True))
        )
    )
    tasks_by_part = [(part, list(part.tasks.all())) for part in parts]
    content_counts = _task_content_counts(
        [task for _, tasks in tasks_by_part for task in tasks]
    )
    return _home_expression_paths(
        [
            {
                "part": part,
                "tasks": [
                    _task_card(
                        task,
                        now,
                        user,
                        with_deck_stats=False,
                        content_counts=content_counts,
                    )
                    for task in tasks
                ],
            }
            for part, tasks in tasks_by_part
        ]
    )


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

    def test_unbatched_writing_card_counts_shared_occurrences(self):
        sujet_ids = list(
            WritingSujet.objects.filter(
                task=self.task,
                is_active=True,
            ).values_list("pk", flat=True)
        )
        counts = _task_content_counts([self.task])
        counts[self.task.pk]["writing_sujet_ids"] = [
            sujet_ids[0],
            sujet_ids[0],
            sujet_ids[1],
        ]
        WritingSujetCompletion.objects.create(
            user=self.user,
            sujet_id=sujet_ids[0],
        )

        card = _task_card(
            self.task,
            timezone.now(),
            self.user,
            content_counts=counts,
        )

        self.assertEqual(card["stats"]["total"], 3)
        self.assertEqual(card["stats"]["completed"], 2)
        self.assertEqual(card["stats"]["seen"], 2)

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

    def test_expression_pages_summarize_every_task_in_one_call(self):
        with patch(
            "study.views.dashboard.expression_task_summaries",
            wraps=expression_task_summaries,
        ) as batched:
            self.client.get(reverse("study:dashboard"))
            self.client.get(reverse("study:expression"))

        self.assertEqual(batched.call_count, 2)
        for call in batched.call_args_list:
            tasks = list(call.args[2])
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
        url = reverse("study:part_detail", args=[self.part.slug])
        before = self._query_count(url)

        added_tasks = 2
        self._task_with_content("tache-4")
        self._task_with_content("tache-5")

        growth = self._query_count(url) - before
        unbatched_growth = (
            self._unbatched_query_count(url, "library") - before
        )
        self.assertLessEqual(growth, unbatched_growth - 4 * added_tasks)

    def test_extra_tasks_do_not_add_expression_page_queries(self):
        """The hub and the home page cost the same whatever the task count."""
        pages = [
            reverse("study:dashboard"),
            reverse("study:expression"),
        ]
        before = {url: self._query_count(url) for url in pages}

        self._task_with_content("tache-4")
        self._task_with_content("tache-5")

        for url in pages:
            with self.subTest(url=url):
                self.assertEqual(self._query_count(url), before[url])


PATH_KEYS = (
    "available",
    "task_count",
    "has_content",
    "prompt_count",
    "seen",
    "total",
    "due",
    "progress",
    "title",
)


class ExpressionPathSummaryTests(TestCase):
    """The batched hub summary must equal the task cards it replaced.

    The fixture covers every rule the two pages render: aliases collapsing onto
    one response, Tâche 2 counting each subject occurrence, the three ways a
    subject counts as started, explicit completion, due response cards, EE
    Tâche 1 sujets, and unavailable tasks and parts.
    """

    def setUp(self):
        self.user = factories.make_user("expression-paths")
        self.now = timezone.now()
        self.prompt_number = 0
        self.subject_keys = [
            content_module.tache_two_subject_content_key(
                month.slug,
                batch.number,
                subject.number,
            )
            for month in content_module.load_tache_two_subject_months()
            for batch in month.batches
            for subject in batch.subjects
        ]

        self.eo = factories.make_part("eo")
        self.ee = factories.make_part("ee")
        self.soon = factories.make_part("ex", available=False)

        self._build_tache_two()
        self._build_tache_three()
        self._build_writing_task()
        self._build_edge_cases()

    def _add_prompt(self, response, content_key, theme=None):
        self.prompt_number += 1
        return Prompt.objects.create(
            content_key=content_key,
            response=response,
            theme=theme or response.theme,
            family=response.family,
            number=self.prompt_number,
            text=f"Sujet équivalent {self.prompt_number} ?",
        )

    def _subject_vocabulary_card(self, response, **overrides):
        phrase = factories.make_phrase(tier=PhraseTier.SUBJECT)
        phrase.source_prompts.add(response.prompts.first())
        return factories.make_phrase_card(
            phrase=phrase,
            user=self.user,
            **overrides,
        )

    def _highlight(self, **overrides):
        return Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.HIGHLIGHT,
            quote="extrait",
            **overrides,
        )

    def _build_tache_two(self):
        """EO Tâche 2: two equivalent subjects share one response."""
        self.tache_two = factories.make_task(self.eo, "tache-2")
        theme = factories.make_theme("eo-tache-2-theme", task=self.tache_two)
        shared_card = factories.make_spine_card(theme=theme, user=self.user)
        self.shared_subject = shared_card.response
        shared_card.subject_completed_at = self.now
        shared_card.response_practice_started_at = self.now
        shared_card.save(
            update_fields=[
                "subject_completed_at",
                "response_practice_started_at",
            ]
        )
        self._add_prompt(self.shared_subject, self.subject_keys[0])
        self._add_prompt(self.shared_subject, self.subject_keys[1])

        highlighted = factories.make_spine_card(theme=theme, user=self.user)
        self.highlighted_subject = highlighted.response
        self._add_prompt(self.highlighted_subject, self.subject_keys[2])
        self._highlight(
            source_path="/expression/orale/tache-2/",
            source_key=(
                f"response:{self.highlighted_subject.content_key}:front"
            ),
        )

    def _build_tache_three(self):
        """EO Tâche 3: started by practice, by vocabulary, or by a due card."""
        self.tache_three = factories.make_task(self.eo, "tache-3")
        theme = factories.make_theme("eo-tache-3-theme", task=self.tache_three)

        practiced = factories.make_spine_card(theme=theme, user=self.user)
        practiced.response_practice_started_at = self.now
        practiced.save(update_fields=["response_practice_started_at"])
        # An alias: a second prompt on the same response, as the content has.
        self._add_prompt(practiced.response, "test-prompt-alias:tache-3")

        vocabulary_started = factories.make_spine_card(
            theme=theme,
            user=self.user,
        )
        self._subject_vocabulary_card(
            vocabulary_started.response,
            started_at=self.now,
        )

        self.due_card = factories.make_spine_card(
            theme=theme,
            user=self.user,
            state=CardState.REVIEW,
            due=self.now - timezone.timedelta(days=1),
            interval_days=6,
        )
        untouched = factories.make_spine_card(theme=theme, user=self.user)
        self._subject_vocabulary_card(untouched.response)

    def _build_writing_task(self):
        """EE Tâche 1: completion, personalization, and a highlight."""
        self.writing_task = factories.make_task(self.ee, "tache-1")
        self.sujets = [
            factories.make_writing_sujet(self.writing_task)
            for _ in range(4)
        ]
        factories.make_writing_sujet(self.writing_task, is_active=False)
        WritingSujetCompletion.objects.create(
            user=self.user,
            sujet=self.sujets[0],
        )
        PersonalWritingResponse.objects.create(
            user=self.user,
            sujet=self.sujets[1],
            body="Bonjour, viens samedi.",
        )
        self._highlight(
            source_path=(
                f"/expression/ecrite/tache-1/sujets/{self.sujets[2].pk}/"
            ),
            source_key=f"writing-sujet:{self.sujets[2].pk}:personal",
        )

    def _build_edge_cases(self):
        """Content the two pages must ignore, skip, or still count."""
        self.ee_tache_three = factories.make_task(self.ee, "tache-3")
        theme = factories.make_theme(
            "ee-tache-3-theme",
            task=self.ee_tache_three,
        )
        self.ee_tache_three_card = factories.make_spine_card(
            theme=theme,
            user=self.user,
        )

        # An archived theme still owns prompts: they count as content, but
        # their responses are not part of the progress.
        archived = factories.make_theme(
            "eo-tache-3-archive",
            task=self.tache_three,
        )
        Theme.objects.filter(pk=archived.pk).update(is_active=False)
        factories.make_response(theme=archived)

        unavailable_task = factories.make_task(
            self.eo,
            "tache-1",
            available=False,
        )
        unavailable_theme = factories.make_theme(
            "eo-tache-1-theme",
            task=unavailable_task,
        )
        factories.make_spine_card(theme=unavailable_theme, user=self.user)

        soon_task = factories.make_task(self.soon, "tache-1")
        soon_theme = factories.make_theme("ex-tache-1-theme", task=soon_task)
        factories.make_spine_card(theme=soon_theme, user=self.user)

    def _paths(self):
        return {
            path["part"].slug: path
            for path in _home_expression_paths(
                _parts_with_task_summaries(self.now, self.user)
            )
        }

    def _comparable(self, paths):
        return [
            (path["part"].slug, {key: path[key] for key in PATH_KEYS})
            for path in paths
        ]

    def test_paths_match_the_task_card_paths(self):
        legacy = legacy_expression_paths(self.now, self.user)
        batched = _home_expression_paths(
            _parts_with_task_summaries(self.now, self.user)
        )

        self.assertEqual(self._comparable(batched), self._comparable(legacy))

    def test_hub_totals_match_the_task_card_totals(self):
        legacy = [
            path
            for path in legacy_expression_paths(self.now, self.user)
            if path["available"]
        ]
        batched = [
            path
            for path in _home_expression_paths(
                _parts_with_task_summaries(self.now, self.user)
            )
            if path["available"]
        ]

        for key in ("prompt_count", "total", "seen", "due"):
            with self.subTest(key=key):
                self.assertEqual(
                    sum(path[key] for path in batched),
                    sum(path[key] for path in legacy),
                )

    def test_tache_two_keeps_every_subject_occurrence(self):
        summaries = expression_task_summaries(
            self.now,
            self.user,
            [self.tache_two],
        )
        stats = summaries[self.tache_two.pk]["stats"]

        self.assertEqual(len(self.subject_keys), 348)
        self.assertEqual(stats["total"], 348)
        # The two equivalent subjects share one completed response, and each
        # occurrence counts on its own instead of collapsing into one.
        self.assertEqual(stats["completed"], 2)
        self.assertEqual(stats["seen"], 3)
        self.assertEqual(stats["progress"].total, 348)
        self.assertEqual(stats["progress"].completed, 2)

    def test_ordinary_tasks_collapse_aliases_onto_their_response(self):
        summaries = expression_task_summaries(
            self.now,
            self.user,
            [self.tache_three],
        )
        summary = summaries[self.tache_three.pk]

        # Five prompts — four responses plus one alias — and one archived
        # theme's prompt, over four responses with progress.
        self.assertEqual(summary["prompt_count"], 6)
        self.assertEqual(summary["stats"]["total"], 4)
        self.assertEqual(summary["stats"]["seen"], 3)
        self.assertEqual(summary["stats"]["completed"], 0)

    def test_due_counts_the_due_response_cards_of_each_task(self):
        summaries = expression_task_summaries(
            self.now,
            self.user,
            [self.tache_two, self.tache_three],
        )

        self.assertEqual(summaries[self.tache_three.pk]["stats"]["due"], 1)
        self.assertEqual(summaries[self.tache_two.pk]["stats"]["due"], 0)

    def test_due_ignores_suspended_and_vocabulary_cards(self):
        Card.objects.filter(pk=self.due_card.pk).update(suspended=True)
        self._subject_vocabulary_card(
            self.shared_subject,
            state=CardState.REVIEW,
            due=self.now - timezone.timedelta(days=1),
            started_at=self.now,
        )

        summaries = expression_task_summaries(
            self.now,
            self.user,
            [self.tache_two, self.tache_three],
        )

        self.assertEqual(summaries[self.tache_three.pk]["stats"]["due"], 0)
        self.assertEqual(summaries[self.tache_two.pk]["stats"]["due"], 0)

    def test_writing_task_counts_sujets(self):
        summaries = expression_task_summaries(
            self.now,
            self.user,
            [self.writing_task],
        )
        summary = summaries[self.writing_task.pk]

        self.assertEqual(summary["prompt_count"], 4)
        self.assertEqual(summary["stats"]["total"], 4)
        self.assertEqual(summary["stats"]["completed"], 1)
        self.assertEqual(summary["stats"]["seen"], 3)
        self.assertEqual(summary["stats"]["due"], 0)

    def test_ee_tache_three_counts_each_published_alias(self):
        keys = content_module.load_ee_subject_keys(3)
        canonical = self.ee_tache_three_card.response.prompts.get(
            is_canonical=True
        )
        canonical.content_key = keys[0]
        canonical.save(update_fields=["content_key"])
        self._add_prompt(
            self.ee_tache_three_card.response,
            keys[1],
            theme=canonical.theme,
        )
        self.ee_tache_three_card.subject_completed_at = self.now
        self.ee_tache_three_card.save(update_fields=["subject_completed_at"])

        summaries = expression_task_summaries(
            self.now,
            self.user,
            [self.ee_tache_three],
        )
        summary = summaries[self.ee_tache_three.pk]

        self.assertEqual(summary["prompt_count"], 2)
        self.assertEqual(summary["stats"]["total"], 2)
        self.assertEqual(summary["stats"]["completed"], 2)
        self.assertEqual(summary["stats"]["seen"], 2)

    def test_unbatched_ee_tache_three_card_counts_published_aliases(self):
        keys = content_module.load_ee_subject_keys(3)
        canonical = self.ee_tache_three_card.response.prompts.get(
            is_canonical=True
        )
        canonical.content_key = keys[0]
        canonical.save(update_fields=["content_key"])
        self._add_prompt(
            self.ee_tache_three_card.response,
            keys[1],
            theme=canonical.theme,
        )
        self.ee_tache_three_card.subject_completed_at = self.now
        self.ee_tache_three_card.save(update_fields=["subject_completed_at"])

        card = _task_card(
            self.ee_tache_three,
            self.now,
            self.user,
        )

        self.assertEqual(card["stats"]["total"], 2)
        self.assertEqual(card["stats"]["completed"], 2)

    def test_unavailable_tasks_and_parts_stay_empty(self):
        paths = self._paths()
        unavailable_task = Task.objects.get(part=self.eo, slug="tache-1")
        summaries = expression_task_summaries(
            self.now,
            self.user,
            [unavailable_task],
        )

        self.assertEqual(
            summaries[unavailable_task.pk],
            {"prompt_count": 0, "stats": None},
        )
        self.assertEqual(paths["eo"]["task_count"], 3)
        self.assertFalse(paths["ex"]["available"])
        self.assertTrue(paths["ex"]["has_content"])

    def test_rendered_hub_matches_the_task_card_numbers(self):
        self.client.force_login(self.user)
        legacy = [
            path
            for path in legacy_expression_paths(self.now, self.user)
            if path["available"]
        ]

        response = self.client.get(reverse("study:expression"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["prompt_count"],
            sum(path["prompt_count"] for path in legacy),
        )
        self.assertEqual(
            response.context["card_total"],
            sum(path["total"] for path in legacy),
        )
        self.assertEqual(
            response.context["card_seen"],
            sum(path["seen"] for path in legacy),
        )
        self.assertEqual(
            response.context["response_due"],
            sum(path["due"] for path in legacy),
        )

    def test_dashboard_skills_match_the_task_card_progress(self):
        self.client.force_login(self.user)
        legacy = {
            path["part"].slug: path
            for path in legacy_expression_paths(self.now, self.user)
        }

        response = self.client.get(reverse("study:dashboard"))

        self.assertEqual(response.status_code, 200)
        skills = {skill["key"]: skill for skill in response.context["skills"]}
        for slug in ("eo", "ee"):
            with self.subTest(slug=slug):
                progress = legacy[slug]["progress"]
                self.assertEqual(skills[slug]["percent"], progress.percent)
                self.assertEqual(skills[slug]["status"], progress.status)
                self.assertEqual(
                    skills[slug]["detail"],
                    (
                        f"{progress.completed}/{progress.total} "
                        f"{'contenus' if slug == 'eo' else 'sujets'}"
                    ),
                )

    def test_query_count_does_not_grow_with_the_number_of_tasks(self):
        tasks = list(
            Task.objects.select_related("part").filter(
                is_active=True,
                part__is_active=True,
            )
        )
        small = [self.tache_three]

        with CaptureQueriesContext(connection) as one_task:
            expression_task_summaries(self.now, self.user, small)
        with CaptureQueriesContext(connection) as every_task:
            expression_task_summaries(self.now, self.user, tasks)

        self.assertGreaterEqual(len(tasks), 6)
        self.assertLessEqual(
            len(every_task.captured_queries),
            len(one_task.captured_queries) + 4,
        )
        self.assertLessEqual(len(every_task.captured_queries), 12)
