"""EE detail dates share progress reads; navigation does not fetch answers."""

from dataclasses import asdict
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from study.catalogue import loader as content_loader
from study.models import (
    Annotation, PersonalWritingResponse, WritingResponseOverride,
    WritingSujet, WritingSujetCompletion,
)
from study.review.progress import writing_sujet_progress_by_id, writing_sujet_started_at

from . import factories


class WritingActivityTimestampTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("writing-timestamps")
        self.other = factories.make_user("other-writing-timestamps")
        self.sujets = [factories.make_writing_sujet() for _ in range(3)]
        self.task = self.sujets[0].task
        self.now = timezone.now()

    def test_batched_dates_match_original_sources_and_statuses(self):
        first, second, completed = self.sujets
        PersonalWritingResponse.objects.create(
            user=self.user, sujet=first, body="Un texte personnel.",
            created_at=self.now - timedelta(days=3),
        )
        for index, days in enumerate((7, 4)):
            edit = WritingResponseOverride.objects.create(
                user=self.user, sujet=first,
                version_key=f"model-{index}", body="Un modèle modifié.",
            )
            WritingResponseOverride.objects.filter(pk=edit.pk).update(
                updated_at=self.now - timedelta(days=days),
            )
        other_task = factories.make_task(self.task.part, "tache-2")
        for user, task, days in (
            (self.user, None, 5),
            (self.other, self.task, 30),
            (self.user, other_task, 40),
        ):
            Annotation.objects.create(
                user=user, task=task, kind="highlight", quote="Un passage.",
                source_key=f"writing-sujet:{second.pk}:model-1",
                created_at=self.now - timedelta(days=days),
            )
        WritingSujetCompletion.objects.create(user=self.user, sujet=completed)
        WritingResponseOverride.objects.create(
            user=self.user, sujet=completed, version_key="model-1", body="",
        )
        ids = [sujet.pk for sujet in self.sujets]
        with self.assertNumQueries(3):
            dated = writing_sujet_progress_by_id(
                self.user, ids, task_id=self.task.pk, with_started_at=True,
            )
        ordinary = writing_sujet_progress_by_id(self.user, ids, task_id=self.task.pk)
        for sujet in self.sujets:
            self.assertEqual(
                dated[sujet.pk].started_at,
                writing_sujet_started_at(self.user, sujet.pk, task_id=self.task.pk),
            )
            values = asdict(dated[sujet.pk])
            values["started_at"] = None
            self.assertEqual(values, asdict(ordinary[sujet.pk]))
        self.assertEqual(dated[first.pk].started_at, self.now - timedelta(days=7))
        self.assertEqual(dated[second.pk].started_at, self.now - timedelta(days=5))
        self.assertEqual(dated[completed.pk].status, "done")
        self.assertIsNone(dated[completed.pk].started_at)

    def test_dates_are_fresh_after_updates_and_removal_and_user_scoped(self):
        sujet = self.sujets[0]
        own = PersonalWritingResponse.objects.create(
            user=self.user, sujet=sujet, body="Ma réponse.",
        )
        PersonalWritingResponse.objects.create(
            user=self.other, sujet=sujet, body="Une autre réponse privée.",
            created_at=self.now - timedelta(days=30),
        )

        def progress():
            return writing_sujet_progress_by_id(
                self.user, [sujet.pk], task_id=self.task.pk,
                with_started_at=True,
            )[sujet.pk]

        self.assertEqual(progress().started_at, own.created_at)
        earlier = self.now - timedelta(days=2)
        PersonalWritingResponse.objects.filter(pk=own.pk).update(created_at=earlier)
        self.assertEqual(progress().started_at, earlier)
        own.delete()
        self.assertEqual(progress().status, "new")
        self.assertIsNone(progress().started_at)

    def test_empty_ids_do_not_query(self):
        with self.assertNumQueries(0):
            self.assertEqual(writing_sujet_progress_by_id(
                self.user, [], with_started_at=True,
            ), {})


class WritingDetailRequestPerformanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("writing-detail-performance")
        cls.other = factories.make_user("other-writing-detail-performance")
        cls.sujets = []
        for tache in (1, 2):
            sujet = WritingSujet.objects.filter(
                task__part__slug="ee", task__slug=f"tache-{tache}",
                is_active=True,
            ).select_related("task__part").first()
            canonical_slug = content_loader.ee_writing_canonical_slug_by_slug(tache).get(
                sujet.slug, sujet.slug,
            )
            cls.sujets.append(WritingSujet.objects.select_related("task__part").get(
                task=sujet.task, slug=canonical_slug,
            ))

    def setUp(self):
        self.client.force_login(self.user)

    def test_active_details_reuse_progress_reads_and_do_not_load_sibling_answers(self):
        for sujet in self.sujets:
            personal = PersonalWritingResponse.objects.create(
                user=self.user, sujet=sujet,
                body="Une réponse privée unique pour mesurer la page.",
            )
            url = reverse("study:writing_sujet_detail", args=["ee", sujet.task.slug, sujet.pk])
            with CaptureQueriesContext(connection) as queries:
                page = self.client.get(url)
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, personal.body)
            self.assertEqual(page.context["writing_started_at"], personal.created_at)
            self.assertEqual(page.context["writing_progress"].status, "active")
            self.assertLessEqual(len(queries), 11)
            selected = [
                query["sql"].partition(" FROM ")[0]
                for query in queries
                if query["sql"].startswith('SELECT "study_writingsujet".')
            ]
            self.assertEqual(sum(
                '"study_writingsujet"."versions"' in columns
                for columns in selected
            ), 1)
            self.assertEqual(page["Cache-Control"], "private, no-store")

    def test_private_writing_dates_and_answers_do_not_leak_and_reset_is_immediate(self):
        sujet = self.sujets[0]
        personal = PersonalWritingResponse.objects.create(
            user=self.user, sujet=sujet, body="Ma réponse privée non partagée.",
        )
        url = reverse("study:writing_sujet_detail", args=["ee", sujet.task.slug, sujet.pk])
        self.assertTrue(self.client.get(url).context["has_personal"])
        self.client.force_login(self.other)
        page = self.client.get(url)
        self.assertNotContains(page, personal.body)
        self.assertFalse(page.context["has_personal"])
        self.assertIsNone(page.context["writing_started_at"])
        self.client.force_login(self.user)
        personal.delete()
        page = self.client.get(url)
        self.assertFalse(page.context["has_personal"])
        self.assertIsNone(page.context["writing_started_at"])
