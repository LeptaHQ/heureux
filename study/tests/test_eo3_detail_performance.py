"""EO3 detail validation and EO2/EO3 annotation ownership stay bounded."""

from dataclasses import FrozenInstanceError
from datetime import timedelta
from io import StringIO
from pathlib import Path
import re
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from study.catalogue import registry as catalogue
from study.catalogue import loader as content
from study.expression.eo.tache_3.taxonomy import load_eo_tache_three_taxonomy
from study.expression.eo.tache_3 import languages
from study.models import Annotation, AnnotationKind, Card, CardState, CardType, Prompt, Task
from study.expression.eo.history import annotation_owners
from study.review.progress import subject_highlight_times, subject_progress_by_response
from study.navigation.routing import prompt_detail_url, review_url
from study.expression.eo.tache_3.responses import load_tache_three_models
from study.expression.eo.tache_3.prompt_notes import load_tache_three_prompt_notes
from study.views import library

from . import factories


class EO3SourceReuseTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def test_four_catalogues_share_one_parse_and_preserve_direct_validation(self):
        sources = content.parse_responses()
        cases = (
            (catalogue.tache_three_models, load_tache_three_models),
            (catalogue.tache_three_prompt_notes, load_tache_three_prompt_notes),
            (catalogue.tache_three_subject_hints, content.load_tache_three_subject_hints),
            (catalogue.eo_tache_three_taxonomy, load_eo_tache_three_taxonomy),
        )
        with patch.object(content, "parse_responses", wraps=content.parse_responses) as parse:
            for cached, loader in cases:
                with self.subTest(loader=loader.__name__):
                    actual = cached()
                    self.assertEqual(actual, loader(responses=sources))
                    self.assertIs(actual, cached())
            self.assertEqual(parse.call_count, 1)
            catalogue.clear_catalogue_cache()
            for cached, _loader in cases:
                cached()
            self.assertEqual(parse.call_count, 2)

    def test_shared_identities_are_immutable_and_do_not_retain_bodies(self):
        source = catalogue._eo3_sources()[0]
        with self.assertRaises(FrozenInstanceError):
            source.theme = "changed"
        with self.assertRaises(FrozenInstanceError):
            source.prompts[0].text = "changed"
        self.assertIsInstance(source.prompts, tuple)
        self.assertFalse(hasattr(source, "body_html"))
        self.assertFalse(hasattr(source.prompts[0], "model_content"))

    def test_model_partitions_reuse_the_already_validated_taxonomy(self):
        with patch(
            "study.expression.eo.tache_3.taxonomy.load_eo_tache_three_taxonomy",
            wraps=load_eo_tache_three_taxonomy,
        ) as validate:
            catalogue.tache_three_models()
        validate.assert_called_once_with(responses=catalogue._eo3_sources())

    def test_warm_translation_signature_uses_one_stat_result_per_file(self):
        languages._read_manifest.cache_clear()
        self.addCleanup(languages._read_manifest.cache_clear)
        expected = languages.manifest()
        paths, _taxonomy = content.eo3_theme_paths(
            "translations.en.json", taxonomy=catalogue.eo_tache_three_taxonomy(),
        )
        counts = dict.fromkeys(paths, 0)
        original_stat = Path.stat

        def record_stat(path, *args, **kwargs):
            if path in counts:
                counts[path] += 1
            return original_stat(path, *args, **kwargs)

        with patch.object(Path, "stat", record_stat):
            self.assertIs(languages.manifest(), expected)
        # One existence check and one combined mtime/size lookup per partition.
        self.assertEqual(counts, dict.fromkeys(paths, 2))


class EO3DetailPerformanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("eo3-detail-performance")
        cls.other = factories.make_user("other-eo3-detail-performance")
        cls.prompt = Prompt.objects.select_related(
            "response", "theme__task__part",
        ).get(content_key="culture:p4", is_active=True)
        cls.card = Card.objects.create(
            user=cls.user, response=cls.prompt.response, card_type=CardType.SPINE,
        )
        cls.other_prompt = Prompt.objects.select_related(
            "theme__task__part",
        ).filter(
            theme__task=cls.prompt.theme.task, is_active=True,
        ).exclude(response_id=cls.prompt.response_id).first()

    def setUp(self):
        self.client.force_login(self.user)
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def _marks(self, prompt, count, **overrides):
        offset = Annotation.objects.filter(
            user=overrides.get("user", self.user), source_prompt=prompt,
        ).count()
        return Annotation.objects.bulk_create([
            Annotation(**{
                "user": self.user, "task": prompt.theme.task,
                "kind": AnnotationKind.HIGHLIGHT,
                "source_prompt": prompt,
                "source_key": f"response:{prompt.content_key}:model",
                "source_path": prompt_detail_url(prompt),
                "quote": "Un souvenir 🎬",
                "start_offset": (offset + index) * 2,
                "end_offset": (offset + index) * 2 + 14,
                **overrides,
            })
            for index in range(count)
        ])

    def test_authenticated_cold_detail_parses_sources_once_and_skips_unused_totals(self):
        with patch.object(content, "parse_responses", wraps=content.parse_responses) as parse, \
             patch(
                 "study.views.library.subject_progress_by_response",
                 wraps=subject_progress_by_response,
             ) as progress:
            with CaptureQueriesContext(connection) as queries:
                page = self.client.get(prompt_detail_url(self.prompt))
        self.assertEqual(page.status_code, 200)
        self.assertLessEqual(sum(query["sql"].startswith("SELECT") for query in queries), 16)
        parse.assert_called_once_with()
        progress.assert_called_once_with(
            self.user, {self.prompt.response_id}, summary_only=True,
        )
        self.assertContains(page, self.prompt.text)
        self.assertIsNotNone(page.context["eo3_language"])
        self.assertEqual(page["Cache-Control"], "private, no-store")
        self.assertFalse(any("COUNT(DISTINCT" in query["sql"] for query in queries))
        self.assertEqual(
            subject_progress_by_response(self.user, {self.prompt.response_id}),
            subject_progress_by_response(
                self.user, {self.prompt.response_id}, summary_only=True,
            ),
        )

    def test_unrelated_repeated_marks_resolve_once_on_actual_detail_requests(self):
        self._marks(self.other_prompt, 500)
        with patch("study.expression.eo.history.annotation_owners", wraps=annotation_owners) as owners:
            with CaptureQueriesContext(connection) as queries:
                page = self.client.get(prompt_detail_url(self.prompt))
        self.assertEqual(page.status_code, 200)
        self.assertLessEqual(sum(query["sql"].startswith("SELECT") for query in queries), 16)
        owners.assert_called_once()
        self.assertEqual(len(owners.call_args.args[0]), 1)
        self.assertEqual(page.context["subject_progress"].status, "new")
        annotation_sql = [query["sql"] for query in queries if 'MIN("study_annotation"."id")' in query["sql"]]
        self.assertEqual(len(annotation_sql), 1)
        self.assertNotIn('"study_annotation"."body"', annotation_sql[0])
        self.assertNotIn('"study_annotation"."quote"', annotation_sql[0])

    def test_grouped_marks_keep_earliest_latest_reset_and_user_isolation_fresh(self):
        first, last = self._marks(self.prompt, 2)
        now = timezone.now()
        earliest, latest = now - timedelta(days=3), now - timedelta(days=1)
        Annotation.objects.filter(pk=first.pk).update(created_at=earliest)
        Annotation.objects.filter(pk=last.pk).update(created_at=latest)
        self._marks(self.prompt, 1, user=self.other)
        self._marks(self.prompt, 1, hidden_on_source=True)
        self.assertEqual(
            subject_highlight_times(self.user, {self.prompt.response_id}),
            {self.prompt.response_id: (latest, earliest)},
        )
        Card.objects.filter(pk=self.card.pk).update(subject_status_reset_at=now)
        self.assertEqual(subject_progress_by_response(
            self.user, {self.prompt.response_id}, summary_only=True,
        )[self.prompt.response_id].status, "new")
        Annotation.objects.filter(pk=last.pk).update(created_at=now + timedelta(seconds=1))
        self.assertEqual(subject_progress_by_response(
            self.user, {self.prompt.response_id}, summary_only=True,
        )[self.prompt.response_id].status, "active")

    def test_eo2_directory_reuses_grouped_owners_with_fresh_private_completion(self):
        self._marks(self.other_prompt, 500)
        response_id, other_response_id = Prompt.objects.filter(
            theme__task__part__slug="eo", theme__task__slug="tache-2",
            is_active=True,
        ).order_by("response_id").values_list("response_id", flat=True).distinct()[:2]
        card = Card.objects.create(
            user=self.user, response_id=response_id, card_type=CardType.SPINE,
            subject_completed_at=timezone.now(),
        )
        Card.objects.create(
            user=self.other, response_id=other_response_id, card_type=CardType.SPINE,
            subject_completed_at=timezone.now(),
        )
        path = "/expression/orale/tache-2/sujets/"
        with patch("study.expression.eo.history.annotation_owners", wraps=annotation_owners) as owners:
            with CaptureQueriesContext(connection) as queries:
                page = self.client.get(path)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(sum(query["sql"].startswith("SELECT") for query in queries), 10)
        owners.assert_called_once()
        self.assertEqual(len(owners.call_args.args[0]), 1)
        self.assertEqual(page.context["subject_summary"]["completed"], 1)
        Card.objects.filter(pk=card.pk).update(subject_completed_at=None)
        for suffix in ("", "?deduplicate=0"):
            self.assertEqual(
                self.client.get(path + suffix).context["subject_summary"]["completed"], 0,
            )
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(path).context["subject_summary"]["completed"], 1)

    def test_oral_content_omits_practice_urls_without_removing_written_practice(self):
        eo2_prompt = Prompt.objects.select_related("theme__task__part").filter(
            theme__task__part__slug="eo", theme__task__slug="tache-2", is_active=True,
        ).first()
        written_prompt = Prompt.objects.select_related("theme__task__part").filter(
            theme__task__part__slug="ee", theme__task__slug="tache-3", is_active=True,
        ).first()
        with patch("study.views.library.review_url", wraps=review_url) as build_review_url:
            for prompt in (eo2_prompt, self.prompt):
                with self.subTest(task=prompt.theme.task.slug):
                    page = self.client.get(prompt_detail_url(prompt))
                    self.assertEqual(page.status_code, 200)
                    self.assertNotIn("response_review_url", page.context)
                    self.assertIsNotNone(page.context["response_content"])
                    self.assertIsNotNone(page.context["subject_progress"])
                    self.assertIsNotNone(page.context["subject_hints"])
            build_review_url.assert_not_called()
            written = self.client.get(prompt_detail_url(written_prompt))
        self.assertEqual(written.status_code, 200)
        self.assertIn("kind=spine", written.context["response_review_url"])
        build_review_url.assert_called_once()

    def test_forced_task_scope_labels_reuse_joined_metadata(self):
        request = RequestFactory().get("/")
        for part, slug in (("eo", "tache-2"), ("eo", "tache-3"), ("ee", "tache-3")):
            task = Task.objects.select_related("part").get(part__slug=part, slug=slug)
            original_short_name = task.part.short_name
            for short_name in (original_short_name, ""):
                task.part.short_name = short_name
                task.part.save(update_fields=["short_name"])
                expected = library.scope_label(library._task_scope(task))
                self.assertEqual(expected, f"{short_name} · {task.name}")
                with self.subTest(part=part, task=slug, short_name=short_name), \
                     self.assertNumQueries(0):
                    self.assertEqual(library._scope_filters(request, task)["scope_label"], expected)
            task.part.short_name = original_short_name
            task.part.save(update_fields=["short_name"])

    def test_due_calculation_remains_default_and_can_be_explicitly_omitted(self):
        now = timezone.now()
        Card.objects.filter(pk=self.card.pk).update(
            state=CardState.LEARNING, due=now - timedelta(seconds=1),
        )
        scope = {self.prompt.theme_id: {self.prompt.response_id}}
        for summary_only in (False, True):
            with self.subTest(summary_only=summary_only):
                with CaptureQueriesContext(connection) as detailed_queries:
                    detailed, progress, due_ids = library._subject_stats_for_themes(
                        [self.prompt.theme], self.user, now, response_ids_by_theme=scope,
                        summary_only=summary_only,
                    )
                with CaptureQueriesContext(connection) as lean_queries:
                    lean, lean_progress, omitted_due_ids = library._subject_stats_for_themes(
                        [self.prompt.theme], self.user, now, response_ids_by_theme=scope,
                        summary_only=summary_only, include_due=False,
                    )
                self.assertEqual(due_ids, {self.prompt.response_id})
                self.assertEqual(detailed[self.prompt.theme_id]["due"], 1)
                self.assertIsNone(omitted_due_ids)
                self.assertNotIn("due", lean[self.prompt.theme_id])
                self.assertEqual(lean_progress, progress)
                self.assertEqual(
                    lean[self.prompt.theme_id],
                    {
                        key: value for key, value in detailed[self.prompt.theme_id].items()
                        if key != "due"
                    },
                )
                self.assertEqual(len(detailed_queries), len(lean_queries) + 1)

        self.prompt.content_key = "performance:unclassified"
        unclassified = library._oral_subject_themes(
            [{"theme": self.prompt.theme, "stats": lean[self.prompt.theme_id]}],
            lean_progress, prompts=[self.prompt], deduplicate=False,
        )
        self.assertNotIn("due", unclassified[0])
        self.assertEqual(unclassified[0]["started_new"], 1)
        self.assertEqual(
            unclassified[0]["subjects"][0]["progress"], lean_progress[self.prompt.response_id],
        )

    def test_eo3_directory_omits_only_unused_queries_with_identical_private_rendering(self):
        from django.core.signing import TimestampSigner

        self._marks(self.other_prompt, 3)
        Card.objects.filter(pk=self.card.pk).update(subject_completed_at=timezone.now())
        Card.objects.create(
            user=self.other, response_id=self.other_prompt.response_id,
            card_type=CardType.SPINE, subject_completed_at=timezone.now(),
        )
        cards_before = list(Card.objects.order_by("pk").values())
        notes_before = list(Annotation.objects.order_by("pk").values())
        original_filters = library._scope_filters
        original_stats = library._subject_stats_for_themes

        def legacy_filters(request, forced_task=None, forced_part_slug=None):
            context = original_filters(request, forced_task, forced_part_slug)
            if forced_task is not None:
                context["scope_label"] = library.scope_label(context["scope"])
            return context

        def legacy_stats(*args, **kwargs):
            kwargs["include_due"] = True
            return original_stats(*args, **kwargs)

        def normalize(page):
            return re.sub(
                r'(name="csrfmiddlewaretoken" value=")[^"]+', r'\1CSRF', page.content.decode(),
            )

        for suffix in ("", "?deduplicate=0"):
            path = f"/expression/orale/tache-3/sujets/{suffix}"
            with self.subTest(path=path), \
                 patch.object(TimestampSigner, "timestamp", return_value="1"):
                with patch.object(library, "_scope_filters", legacy_filters), \
                     patch.object(library, "_subject_stats_for_themes", legacy_stats), \
                     self.assertNumQueries(13):
                    previous = self.client.get(path)
                with self.assertNumQueries(11):
                    current = self.client.get(path)
                self.assertEqual(previous.status_code, 200)
                self.assertEqual(current.status_code, 200)
                self.assertEqual(normalize(current), normalize(previous))
                self.assertEqual(
                    current.context["subject_summary"], previous.context["subject_summary"],
                )
                self.assertEqual(current.context["subject_summary"]["completed"], 1)
                self.assertTrue(all("due" not in row["stats"] for row in current.context["themes"]))
        self.assertEqual(list(Card.objects.order_by("pk").values()), cards_before)
        self.assertEqual(list(Annotation.objects.order_by("pk").values()), notes_before)
