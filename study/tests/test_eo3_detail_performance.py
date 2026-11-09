"""Cold EO3 validation and annotation history stay bounded on detail requests."""

from dataclasses import FrozenInstanceError
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from study import catalogue
from study import content_loader as content
from study.eo3_taxonomy import load_eo_tache_three_taxonomy
from study.models import Annotation, AnnotationKind, Card, CardType, Prompt
from study.oral_history import annotation_owners
from study.progress import subject_highlight_times, subject_progress_by_response
from study.routing import prompt_detail_url
from study.tache_three_models import load_tache_three_models
from study.tache_three_prompt_notes import load_tache_three_prompt_notes

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
        with patch("study.oral_history.annotation_owners", wraps=annotation_owners) as owners:
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
