"""Landing navigation never waits for the private statistics batch."""

from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from study.account_services import provision_user_study_data
from study import catalogue
from study.ee_formulations import get_ee_formulations
from study.formulation_progress import formulation_progress_states
from study.models import (
    Annotation, AnnotationKind, Card, CardState, CardType,
    MemoryQuestionProgress, PhraseTier, Prompt, Task,
)
from study.oral_history import annotation_owners
from study.progress import progress_summary, subject_progress_by_response
from study.views.helpers import (
    _memory_progress, _review_batches, _task_card, _task_content_counts,
    _theme_vocabulary_batch_summary, expression_task_summaries, summarize_review_batches,
)

from . import factories


class ExpressionLandingPerformanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("landing-performance")
        cls.other = factories.make_user("other-landing-performance")
        provision_user_study_data(cls.user)
        cls.prompt = Prompt.objects.filter(
            theme__task__part__slug="eo", theme__task__slug="tache-3",
            is_active=True,
        ).first()

    def setUp(self):
        self.client.force_login(self.user)
        self.urls = [
            reverse("study:expression"),
            reverse("study:part_detail", args=["eo"]),
            reverse("study:part_detail", args=["ee"]),
        ]

    def test_initial_pages_only_read_navigation_and_keep_links_live(self):
        with patch("study.views.dashboard.expression_task_summaries", side_effect=AssertionError), \
             patch("study.views.library.expression_task_summaries", side_effect=AssertionError), \
             patch("study.views.library._task_content_counts", side_effect=AssertionError), \
             patch("study.views.library._task_card", side_effect=AssertionError):
            for url in self.urls:
                with self.subTest(url=url):
                    with CaptureQueriesContext(connection) as queries:
                        page = self.client.get(url)
                    self.assertEqual(page.status_code, 200)
                    self.assertEqual(len(queries), 4)
                    self.assertContains(page, f'data-expression-stats="{url}?stats=1"')
                    self.assertContains(page, "Les parcours restent accessibles")
                    self.assertContains(page, "sans JavaScript")
                    self.assertNotContains(page, "progress-status--new")
                    self.assertNotContains(page, "0/0")
                    self.assertEqual(page["Cache-Control"], "private, no-store")
        self.assertContains(
            self.client.get(self.urls[0]),
            reverse("study:part_detail", args=["eo"]),
        )
        for part in ("eo", "ee"):
            page = self.client.get(reverse("study:part_detail", args=[part]))
            for task in Task.objects.filter(part__slug=part, is_active=True):
                self.assertContains(page, reverse("study:task_detail", args=[part, task.slug]))

    def test_one_private_batch_and_no_javascript_fallback_keep_complete_output(self):
        for url, budget in zip(self.urls, (19, 15, 16)):
            with self.subTest(url=url):
                with CaptureQueriesContext(connection) as queries:
                    batch = self.client.get(url, {"stats": "1"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
                self.assertEqual(batch.status_code, 200)
                self.assertLessEqual(len(queries), budget)
                self.assertEqual(batch["Cache-Control"], "private, no-store")
                payload = batch.json()
                self.assertIn('href="/expression/', payload["html"])
                self.assertNotIn("en chargement", payload["html"])
                fallback = self.client.get(url, {"stats": "1"})
                self.assertEqual(fallback.status_code, 200)
                self.assertNotContains(fallback, "data-expression-stats=")
                self.assertNotContains(fallback, "expression-stats.js")
                self.assertContains(fallback, payload["html"], html=True)
                if url == self.urls[0]:
                    self.assertContains(fallback, payload["metrics"], html=True)

    def test_batch_is_fresh_after_completion_reset_and_account_switch(self):
        url = self.urls[0] + "?stats=1"

        def metrics():
            return self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest").json()["metrics"]

        before = metrics()
        card = Card.objects.get(user=self.user, response=self.prompt.response, card_type=CardType.SPINE)
        Card.objects.filter(pk=card.pk).update(subject_completed_at=timezone.now(), state=CardState.NEW)
        completed = metrics()
        self.assertNotEqual(before, completed)
        self.client.force_login(self.other)
        self.assertEqual(metrics(), before)
        self.client.force_login(self.user)
        Card.objects.filter(pk=card.pk).update(subject_completed_at=None)
        self.assertEqual(metrics(), before)

    def test_batch_cannot_bypass_authentication_or_inactive_parts(self):
        self.client.logout()
        for url in self.urls:
            page = self.client.get(url, {"stats": "1"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(page.status_code, 302)
            self.assertIn(reverse("study:login"), page.url)
        self.client.force_login(self.user)
        part = self.prompt.theme.task.part
        part.is_active = False
        part.save(update_fields=["is_active"])
        url = reverse("study:part_detail", args=[part.slug])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(url, {"stats": "1"}).status_code, 404)

    def test_lean_counts_preserve_every_rendered_card_value(self):
        tasks = list(Task.objects.filter(is_active=True).select_related("part"))
        now = timezone.now()
        original = _task_content_counts(tasks)
        summaries = expression_task_summaries(now, self.user, tasks, original)
        lean = _task_content_counts(tasks, landing=True)
        rendered = (
            "stats", "response_stats", "prompt_count", "phrase_count",
            "question_bank", "show_phrases",
        )
        for task in tasks:
            lean[task.pk]["prompt_count"] = summaries[task.pk]["prompt_count"]
            old = _task_card(task, now, self.user, with_deck_stats=False, content_counts=original, summaries=summaries)
            new = _task_card(task, now, self.user, with_deck_stats=False, content_counts=lean, summaries=summaries)
            for key in rendered:
                if key == "prompt_count" and old["question_bank"]:
                    continue
                with self.subTest(task=task.slug, part=task.part.slug, key=key):
                    self.assertEqual(new[key], old[key])

    def test_memory_completions_are_batched_without_losing_task_or_user_scope(self):
        catalogs = (get_ee_formulations(1), get_ee_formulations(3))
        memories = catalogue.task_memoires("eo", "tache-1")
        memory_key = next(iter(memories[0].question_keys))
        for user, number, key in (
            (self.user, memories[0].number, memory_key),
            (self.user, 2, catalogs[0].entries[0].content_key),
            (self.user, 1, catalogs[1].entries[0].content_key),
            (self.other, 1, catalogs[0].entries[1].content_key),
        ):
            MemoryQuestionProgress.objects.create(
                user=user, memory_number=number, question_key=key,
            )
        tasks = list(Task.objects.filter(is_active=True).select_related("part"))

        def summarize():
            return expression_task_summaries(timezone.now(), self.user, tasks)

        with CaptureQueriesContext(connection) as queries:
            summaries = summarize()
        self.assertEqual(sum('"study_memoryquestionprogress"' in q["sql"] for q in queries), 1)
        expected = formulation_progress_states(self.user, catalogs)
        for task in tasks:
            if task.part.slug == "ee" and task.slug in ("tache-1", "tache-3"):
                self.assertEqual(
                    summaries[task.pk]["formulation_progress"],
                    expected[int(task.slug[-1])][2],
                )
        oral_task = next(t for t in tasks if (t.part.slug, t.slug) == ("eo", "tache-1"))
        memory_states = _memory_progress(self.user, memories)
        self.assertEqual(
            summaries[oral_task.pk]["stats"]["completed"],
            sum(state["progress"].completed for state in memory_states.values()),
        )
        MemoryQuestionProgress.objects.filter(
            user=self.user, question_key=catalogs[0].entries[0].content_key,
        ).update(memory_number=1)
        writing_task = next(t for t in tasks if (t.part.slug, t.slug) == ("ee", "tache-1"))
        changed = summarize()[writing_task.pk]["formulation_progress"]
        self.assertEqual(changed.completed, expected[1][2].completed + 1)


class ExpressionStatisticsProjectionTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("statistics-projections")
        self.other = factories.make_user("statistics-other")
        self.task = factories.make_task(factories.make_part("eo"), "tache-2")
        self.theme = factories.make_theme("statistics-theme", task=self.task)

    def oral_response(self):
        response = factories.make_response(theme=self.theme)
        response.semantic_group = f"eo/tache-2/{response.pk}"
        response.save(update_fields=["semantic_group"])
        return response

    def test_owner_metadata_only_fetches_references_and_preserves_legacy_priority(self):
        response = self.oral_response()
        prompt = response.canonical_prompt
        prompt.content_key = "tache2:janvier:batch-01:subject-01"
        prompt.save(update_fields=["content_key"])
        historical = self.oral_response()
        historical.semantic_owner = response
        historical.semantic_group = ""
        historical.save(update_fields=["semantic_owner", "semantic_group"])
        for _ in range(25):
            self.oral_response()
        cases = [
            ({"source_prompt_id": prompt.pk, "source_key": "unknown"}, response.pk),
            ({"source_prompt_id": prompt.pk, "source_path": "http://["}, response.pk),
            ({"source_path": f"/expression/orale/tache-2/sujets/{prompt.pk}/?x=1"}, response.pk),
            ({"source_path": f"/expression/orale/tache-3/sujets/{prompt.pk}/"}, None),
            ({"source_path": "/expression/orale/tache-2/sujets/janvier/batch-0001/0001/"}, response.pk),
            ({"source_key": f"response:{prompt.content_key}:model:front"}, response.pk),
            ({"source_key": f"subject-sidebar:{prompt.content_key}:variant-0123456789abcdef:back"}, response.pk),
            ({"source_key": "tache-two:janvier:batch-١:subject-١"}, response.pk),
            ({"source_key": f"response:{historical.content_key}:front"}, response.pk),
            ({"source_key": f"response:{response.content_key}:back"}, response.pk),
            ({"source_key": f"response:{response.content_key}:front:back"}, None),
            ({"source_key": "response:missing:model"}, None),
            ({"source_prompt_id": prompt.pk, "task_id": self.task.pk + 1000,
              "source_key": f"response:{response.content_key}"}, None),
        ]
        annotations = [
            SimpleNamespace(**{
                "pk": index, "source_prompt_id": None, "source_path": "/review/",
                "source_key": "", "task_id": self.task.pk, **fields,
            })
            for index, (fields, _owner) in enumerate(cases)
        ]
        selected = []

        def record(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            selected.append(context["cursor"].rowcount)
            return result

        with self.assertNumQueries(2), connection.execute_wrapper(record):
            owners = annotation_owners(annotations)
        self.assertEqual(owners, {
            index: owner for index, (_fields, owner) in enumerate(cases)
            if owner is not None
        })
        self.assertEqual(sum(selected), 3)  # One referenced prompt, two response roots.
        with self.assertNumQueries(1):
            self.assertEqual(annotation_owners([annotations[0]]), {0: response.pk})
        with self.assertNumQueries(0):
            self.assertEqual(annotation_owners([]), {})

    def test_mixed_subjects_reuse_shape_counts_without_selecting_annotation_text(self):
        oral = self.oral_response()
        ordinary = factories.make_response(theme=self.theme)
        for owner, hidden in ((self.user, False), (self.other, False), (self.user, True)):
            Annotation.objects.create(
                user=owner, task=self.task, kind=AnnotationKind.HIGHLIGHT,
                source_key=f"response:{oral.content_key if owner == self.user and not hidden else ordinary.content_key}",
                source_prompt=oral.canonical_prompt if owner == self.user and not hidden else None,
                source_path="/review/", quote="Private highlighted text",
                start_offset=0, end_offset=7, hidden_on_source=hidden,
            )
        with CaptureQueriesContext(connection) as queries:
            progress = subject_progress_by_response(self.user, [oral.pk, ordinary.pk], summary_only=True)
        self.assertTrue(progress[oral.pk].has_highlight)
        self.assertFalse(progress[ordinary.pk].has_highlight)
        self.assertEqual(sum('COUNT("study_annotation"."id")' in q["sql"] for q in queries), 1)
        for query in queries:
            projection = query["sql"].partition(" FROM ")[0]
            self.assertNotIn('"study_annotation"."quote"', projection)
            self.assertNotIn('"study_annotation"."body"', projection)
        reset_at = timezone.now() + timezone.timedelta(seconds=1)
        Card.objects.create(
            user=self.user, response=oral, card_type=CardType.SPINE,
            subject_status_reset_at=reset_at,
        )
        self.assertFalse(subject_progress_by_response(
            self.user, [oral.pk], summary_only=True,
        )[oral.pk].has_highlight)
        Annotation.objects.filter(
            user=self.user, source_prompt=oral.canonical_prompt, hidden_on_source=False,
        ).update(created_at=reset_at + timezone.timedelta(seconds=1))
        self.assertTrue(subject_progress_by_response(
            self.user, [oral.pk], summary_only=True,
        )[oral.pk].has_highlight)

    def test_projected_lot_counts_preserve_stable_suspended_boundaries_and_freshness(self):
        scope = {"part": "eo", "task": "tache-2", "kind": "theme_vocab"}
        cards = []
        now = timezone.now()
        for index in range(81):
            lot = index // 15
            phrase = factories.make_phrase(
                tier=PhraseTier.THEME, vocabulary_theme=self.theme,
                lot_order=index // 3,
            )
            card = factories.make_phrase_card(
                user=self.user, phrase=phrase,
                suspended=lot == 0 or (lot == 4 and index % 15 != 0),
                state=CardState.REVIEW if lot in (1, 4, 5) else CardState.NEW,
                started_at=now if index == 30 else None,
            )
            cards.append(card)
            if index < 3:
                factories.make_phrase_card(user=self.other, phrase=phrase, state=CardState.REVIEW)

        def assert_equal():
            batches = _review_batches(scope, self.user)
            with self.assertNumQueries(1):
                count, summary = _theme_vocabulary_batch_summary(scope, self.user)
            self.assertEqual(count, len(batches))
            self.assertEqual(summary, summarize_review_batches(batches))
            return count, summary

        self.assertEqual(assert_equal(), (6, progress_summary(total=5, started=4, completed=3)))
        Card.objects.filter(pk__in=[card.pk for card in cards[:15]]).update(suspended=False)
        self.assertEqual(assert_equal(), (6, progress_summary(total=6, started=4, completed=3)))
        Card.objects.filter(user=self.user).delete()
        self.assertEqual(assert_equal(), (0, progress_summary(total=0, started=0, completed=0)))
