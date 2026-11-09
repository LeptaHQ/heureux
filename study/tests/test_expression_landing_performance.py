"""Expression navigation reads only the statistics its cards render."""

from io import StringIO
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.db.models.query import QuerySet
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from study.account_services import provision_user_study_data
from study import catalogue
from study.expression_overview import writing_occurrence_progress
from study.models import (
    Annotation, AnnotationKind, Card, CardState, CardType,
    PersonalWritingResponse, PhraseTier, Prompt, Response, Task,
    WritingResponseOverride, WritingSujet, WritingSujetCompletion,
)
from study.oral_history import annotation_owners
from study.progress import progress_summary, subject_progress_by_response, writing_sujet_progress_by_id
from study.views.helpers import (
    _review_batches, _theme_vocabulary_batch_summary, summarize_review_batches,
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

    def test_navigation_reads_only_metadata_without_statistics(self):
        with patch("study.views.helpers.expression_task_summaries", side_effect=AssertionError), \
             patch("study.views.helpers._task_content_counts", side_effect=AssertionError), \
             patch("study.expression_overview.expression_overview_summaries", side_effect=AssertionError):
            for url, budget in zip(self.urls, (3, 4, 4)):
                with self.subTest(url=url):
                    with CaptureQueriesContext(connection) as queries:
                        page = self.client.get(url)
                    self.assertEqual(page.status_code, 200)
                    self.assertEqual(len(queries), budget)
                    for query in queries:
                        for table in ("study_card", "study_annotation", "study_prompt", "study_writingsujet"):
                            self.assertNotIn(f'"{table}"', query["sql"])
                    self.assertNotContains(page, "data-expression-stats=")
                    self.assertNotContains(page, "expression-stats.js")
                    self.assertNotContains(page, "en chargement")
                    self.assertNotContains(page, 'class="progress"')
                    self.assertNotContains(page, 'class="area-hero__metrics"')
                    self.assertNotContains(page, "terminés")
                    self.assertNotContains(page, "catégories")
                    self.assertNotContains(page, "fiches de vocabulaire")
                    self.assertEqual(page["Cache-Control"], "private, no-store")
        self.assertContains(
            self.client.get(self.urls[0]),
            reverse("study:part_detail", args=["eo"]),
        )
        for part in ("eo", "ee"):
            page = self.client.get(reverse("study:part_detail", args=[part]))
            for task in Task.objects.filter(part__slug=part, is_active=True):
                self.assertContains(page, reverse("study:task_detail", args=[part, task.slug]))

    def test_obsolete_statistics_query_is_plain_navigation_not_an_api(self):
        for url, budget in zip(self.urls, (3, 4, 4)):
            with self.subTest(url=url):
                with self.assertNumQueries(budget):
                    page = self.client.get(url, {"stats": "1"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
                self.assertEqual(page.status_code, 200)
                self.assertTrue(page["Content-Type"].startswith("text/html"))
                self.assertNotContains(page, "expression-stats.js")
                self.assertNotContains(page, 'class="progress"')

    def test_child_overview_groups_highlights_by_source_instead_of_loading_every_mark(self):
        Annotation.objects.bulk_create([
            Annotation(
                user=self.user, task=self.prompt.theme.task, source_prompt=self.prompt,
                kind=AnnotationKind.HIGHLIGHT, source_path="/review/",
                source_key=f"response:{self.prompt.response.content_key}",
                quote=f"Private words {index}", start_offset=index, end_offset=index + 1,
            )
            for index in range(1000)
        ])
        rows = []
        iterate = QuerySet.__iter__

        def record(queryset):
            result = iterate(queryset)
            if queryset.model is Annotation and queryset.query.group_by:
                rows.append(len(queryset._result_cache))
            return result

        with patch.object(QuerySet, "__iter__", record), self.assertNumQueries(8):
            page = self.client.get(reverse("study:task_detail", args=["eo", "tache-3"]))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(rows, [1])
        self.assertNotContains(page, "Private words")

    def test_published_writing_overviews_preserve_occurrence_weighting_and_task_isolation(self):
        from study.views.library import _ee_writing_sujet_ids_by_slug, _ee_writing_source_categories
        from study import content_loader

        for tache in (1, 2):
            task = Task.objects.get(part__slug="ee", slug=f"tache-{tache}")
            ids = _ee_writing_sujet_ids_by_slug(task, tache)
            aliases = content_loader.ee_writing_canonical_slug_by_slug(tache)
            weights = Counter(
                ids[aliases[source.slug]]
                for category in _ee_writing_source_categories(tache) for source in category.sujets
            )
            a, b, c, d = sorted(weights)[:4]
            PersonalWritingResponse.objects.create(user=self.user, sujet_id=a, body="")
            WritingResponseOverride.objects.create(
                user=self.user, sujet_id=b, version_key="model-1", body="Edit", is_deleted=True,
            )
            WritingSujetCompletion.objects.create(user=self.user, sujet_id=c)
            mark = Annotation.objects.create(
                user=self.user, task=self.prompt.theme.task,
                kind=AnnotationKind.HIGHLIGHT, hidden_on_source=True,
                source_key=f"writing-sujet:{d}:model-1", quote="Hidden words",
                start_offset=0, end_offset=5,
            )
            for user in (self.user, self.other):
                full = writing_sujet_progress_by_id(user, weights, task_id=task.pk)
                expected = progress_summary(
                    total=sum(weights.values()),
                    started=sum(weights[pk] * item.started for pk, item in full.items()),
                    completed=sum(weights[pk] * item.completed for pk, item in full.items()),
                )
                with self.assertNumQueries(2):
                    self.assertEqual(writing_occurrence_progress(user, task, weights), expected)
            before = writing_occurrence_progress(self.user, task, weights)
            Annotation.objects.filter(pk=mark.pk).update(task=None)
            self.assertEqual(
                writing_occurrence_progress(self.user, task, weights).started,
                before.started + weights[d],
            )

    def test_child_overviews_do_not_build_directories_or_full_review_batches(self):
        with patch("study.views.library._tache_two_theme_progress", side_effect=AssertionError), \
             patch("study.views.library._review_batches", side_effect=AssertionError), \
             patch("study.views.library.subject_progress_by_response", side_effect=AssertionError), \
             patch("study.views.library.writing_sujet_progress_by_id", side_effect=AssertionError):
            for part, task, budget in (("eo", "tache-2", 3), ("eo", "tache-3", 8), ("ee", "tache-1", 8),
                                       ("ee", "tache-2", 8), ("ee", "tache-3", 7)):
                with self.subTest(part=part, task=task), CaptureQueriesContext(connection) as queries:
                    page = self.client.get(reverse("study:task_detail", args=[part, task]))
                self.assertEqual(page.status_code, 200)
                self.assertLessEqual(len(queries), budget)
                self.assertNotContains(page, "data-expression-stats=")
                self.assertNotContains(page, "en chargement")
                if (part, task) == ("eo", "tache-2"):
                    self.assertEqual(len(queries), 3)
                    for query in queries:
                        for table in ("study_card", "study_annotation", "study_prompt", "study_phrase"):
                            self.assertNotIn(f'"{table}"', query["sql"])
                    for key in ("subject_summary", "subject_count", "theme_vocabulary", "subject_theme_count"):
                        self.assertNotIn(key, page.context)

    def test_ee3_aggregate_overview_keeps_publication_sync_validation(self):
        from study.views.library import _ee_tache_three_overview_context
        task = Task.objects.get(part__slug="ee", slug="tache-3")
        key = catalogue.ee_subject_keys(3)[0]
        Prompt.objects.filter(content_key=key).update(is_active=False)
        with self.assertRaisesMessage(RuntimeError, "content is not synchronized"):
            _ee_tache_three_overview_context(self.user, task)

    def test_eo3_overview_aggregates_and_directory_uses_existing_sparse_progress(self):
        for route in ("task_detail", "task_browse"):
            with patch(
                "study.views.library.subject_progress_by_response",
                wraps=subject_progress_by_response,
            ) as progress:
                page = self.client.get(reverse(f"study:{route}", args=["eo", "tache-3"]))
            self.assertEqual(page.status_code, 200)
            if route == "task_browse":
                self.assertTrue(progress.call_args.kwargs["summary_only"])
                self.assertContains(page, f'data-subject-progress-row="{self.prompt.response_id}"')
            else:
                progress.assert_not_called()

    def test_writing_directory_counts_do_not_fetch_private_override_bodies(self):
        from study.writing_responses import (
            active_model_version_count, model_version_keys, overrides_by_sujet, replaced_model_key,
        )
        sujet = WritingSujet.objects.filter(is_active=True).first()
        models = [{"body": "Public model"}]
        key = model_version_keys(models)[0]
        override = WritingResponseOverride.objects.create(
            user=self.user, sujet=sujet, version_key=key, body="Very private " * 1000,
        )
        for body, deleted in (("Very private " * 1000, False), ("", False), ("", True)):
            WritingResponseOverride.objects.filter(pk=override.pk).update(body=body, is_deleted=deleted)
            full = overrides_by_sujet(self.user, [sujet.pk])[sujet.pk]
            with CaptureQueriesContext(connection) as queries, self.assertNumQueries(1):
                flags = overrides_by_sujet(self.user, [sujet.pk], metadata_only=True)[sujet.pk]
            self.assertIsInstance(flags[key].body, bool)
            self.assertNotIn('"study_writingresponseoverride"."body",', queries[0]["sql"])
            self.assertEqual(active_model_version_count(models, full), active_model_version_count(models, flags))
            self.assertEqual(
                replaced_model_key(models, full, has_personal=True),
                replaced_model_key(models, flags, has_personal=True),
            )
        self.assertEqual(overrides_by_sujet(self.other, [sujet.pk], metadata_only=True), {})

    def test_navigation_cannot_bypass_authentication_or_inactive_parts(self):
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
        selected = {Prompt: [], Response: []}
        iterate = QuerySet.__iter__

        def record(queryset):
            result = iterate(queryset)
            if queryset.model in selected:
                selected[queryset.model].extend(queryset._result_cache)
            return result

        with self.assertNumQueries(2), patch.object(QuerySet, "__iter__", record):
            owners = annotation_owners(annotations)
        self.assertEqual(owners, {
            index: owner for index, (_fields, owner) in enumerate(cases)
            if owner is not None
        })
        self.assertEqual([row[0] for row in selected[Prompt]], [prompt.pk])
        self.assertCountEqual([row[2] for row in selected[Response]], [response.pk, historical.pk])
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
        self.assertEqual(subject_progress_by_response(
            self.user, [oral.pk], summary_only=True,
        )[oral.pk].status, "new")
        Annotation.objects.filter(
            user=self.user, source_prompt=oral.canonical_prompt, hidden_on_source=False,
        ).update(created_at=reset_at + timezone.timedelta(seconds=1))
        self.assertEqual(subject_progress_by_response(
            self.user, [oral.pk], summary_only=True,
        )[oral.pk].status, "active")

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
