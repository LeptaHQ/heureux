"""Bundled catalogues are shared; custom inputs and learner state are not."""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from study import catalogue
from study import content_loader as content
from study.account_services import provision_user_study_data
from study.models import Card, CardType, MemoryQuestionProgress, Prompt
from study.views import library

from . import factories


class CatalogueTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def test_catalogues_preserve_parser_records_and_reuse_them(self):
        cases = [
            (catalogue.tache_two_subject_months, "load_tache_two_subject_months", ()),
            (catalogue.tache_two_subject_themes, "load_tache_two_subject_themes", ()),
            (catalogue.eo_tache_three_family_labels, "load_eo_tache_three_family_labels", ()),
            (catalogue.ee_tache_three_months, "load_ee_tache_three_months", ()),
            *[
                (catalogue.ee_subject_keys, "load_ee_subject_keys", (tache,))
                for tache in (1, 2, 3)
            ],
            *[
                (catalogue.ee_subject_themes, "load_ee_subject_themes", (tache,))
                for tache in (1, 2, 3)
            ],
            *[
                (
                    catalogue.ee_writing_categories,
                    "load_ee_writing_categories",
                    (tache,),
                )
                for tache in (1, 2)
            ],
        ]
        for cached, name, args in cases:
            with self.subTest(loader=name, args=args):
                loader = getattr(content, name)
                expected = loader(*args)
                with patch.object(content, name, wraps=loader) as load:
                    actual = cached(*args)
                    self.assertEqual(actual, expected)
                    self.assertIs(cached(*args), actual)
                load.assert_called_once_with(*args)

        for task_key, (directory, namespace) in content.MEMOIRE_TASKS.items():
            with self.subTest(task=task_key):
                actual = catalogue.task_memoires(*task_key)
                self.assertEqual(
                    actual,
                    content.load_question_banks(directory, key_namespace=namespace),
                )
                self.assertIs(catalogue.task_memoires(*task_key), actual)

    def test_library_uses_the_shared_cache_functions(self):
        for library_name, shared in (
            ("_ee_tache_three_source_months", catalogue.ee_tache_three_months),
            ("_ee_subject_theme_data", catalogue.ee_subject_themes),
            ("_ee_writing_source_categories", catalogue.ee_writing_categories),
            ("_load_task_memoires_by_key", catalogue.task_memoires),
            ("_ee_tache_three_sources_by_key", catalogue.ee_tache_three_sources_by_key),
            ("_ee_writing_sources_by_slug", catalogue.ee_writing_sources_by_slug),
        ):
            with self.subTest(name=library_name):
                self.assertIs(getattr(library, library_name), shared)

    def test_catalogue_mappings_and_records_are_read_only(self):
        mappings = [
            catalogue.eo_tache_three_family_labels(),
            catalogue.tache_two_subject_themes()[1],
            catalogue.ee_subject_themes(3)[1],
            catalogue.ee_tache_three_sources_by_key(),
            catalogue.ee_writing_sources_by_slug(1),
        ]
        for mapping in mappings:
            with self.assertRaises(TypeError):
                mapping["changed"] = "not bundled content"
        subject = catalogue.tache_two_subject_months()[0].batches[0].subjects[0]
        with self.assertRaises(FrozenInstanceError):
            subject.title = "not bundled content"

    def test_clear_reloads_sources_and_derived_indexes(self):
        cases = [
            (catalogue.tache_two_subject_months, ()),
            (catalogue.tache_two_subject_themes, ()),
            (catalogue.task_memoires, ("eo", "tache-1")),
            (catalogue.eo_tache_three_family_labels, ()),
            (catalogue.ee_tache_three_months, ()),
            (catalogue.ee_subject_keys, (3,)),
            (catalogue.ee_subject_themes, (3,)),
            (catalogue.ee_writing_categories, (1,)),
            (catalogue.ee_tache_three_sources_by_key, ()),
            (catalogue.ee_writing_sources_by_slug, (1,)),
        ]
        before = [loader(*args) for loader, args in cases]
        catalogue.clear_catalogue_cache()
        for (loader, args), previous in zip(cases, before):
            with self.subTest(loader=loader.__name__):
                current = loader(*args)
                self.assertEqual(current, previous)
                self.assertIsNot(current, previous)
        month = catalogue.ee_tache_three_months()[0]
        source = month.combinaisons[0]
        self.assertIs(
            catalogue.ee_tache_three_sources_by_key()[source.content_key][0],
            month,
        )
        sujet = catalogue.ee_writing_categories(1)[0].sujets[0]
        self.assertIs(catalogue.ee_writing_sources_by_slug(1)[sujet.slug], sujet)

    def test_oral_family_labels_match_existing_assignments_and_reject_invalid_data(self):
        labels = content.load_eo_tache_three_family_labels()
        self.assertEqual(len(labels), 18)
        self.assertEqual(labels[("culture", "family:13")], "Métiers artistiques")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "labels.json"
            for invalid in (
                [],
                {"culture": []},
                {"unknown-theme": {}},
                {"culture": {"family:99": "Inconnue"}},
                {"sante": {"family:16": "Voyages dans l'espace"}},
                {"culture": {"family:13": " "}},
                {"culture": {"family:13": None}},
            ):
                with self.subTest(payload=invalid):
                    path.write_text(json.dumps(invalid), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        content.load_eo_tache_three_family_labels(path)

    def test_patched_loaders_are_used_after_clear_and_failures_are_not_cached(self):
        months = catalogue.tache_two_subject_months()
        catalogue.clear_catalogue_cache()
        with patch.object(
            content,
            "load_tache_two_subject_months",
            side_effect=[ValueError("invalid subject batch"), months],
        ) as load:
            with self.assertRaisesMessage(ValueError, "invalid subject batch"):
                catalogue.tache_two_subject_months()
            self.assertIs(catalogue.tache_two_subject_months(), months)
            self.assertIs(catalogue.tache_two_subject_months(), months)
        self.assertEqual(load.call_count, 2)

    def test_custom_path_is_reparsed_and_validated_after_bundled_warmup(self):
        bundled = catalogue.tache_two_subject_months()
        payload = json.loads(
            (content.TACHE_TWO_SUBJECTS_DIR / "janvier" / "batch_01.json").read_text()
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "janvier").mkdir()
            path = root / "janvier" / "batch_01.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            first = content.load_tache_two_subject_months(root)
            self.assertEqual(first[0].batches[0], bundled[0].batches[0])

            payload["subjects"][0]["title"] = "Custom subject title"
            path.write_text(json.dumps(payload), encoding="utf-8")
            updated = content.load_tache_two_subject_months(root)
            self.assertEqual(
                updated[0].batches[0].subjects[0].title, "Custom subject title"
            )
            self.assertIs(catalogue.tache_two_subject_months(), bundled)

            payload["subjects"][0]["questions"] = []
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesMessage(ValueError, "has no questions"):
                content.load_tache_two_subject_months(root)


class CatalogueRequestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("catalogue-reader")
        cls.other = factories.make_user("catalogue-other")
        provision_user_study_data(cls.user)
        cls.prompt = Prompt.objects.select_related("response").get(
            content_key=content.tache_two_subject_content_key("janvier", 1, 1)
        )

    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.client.force_login(self.user)
        self.now = timezone.now()
        clock = patch("django.utils.timezone.now", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)

    def _pages(self):
        return {
            "dashboard": reverse("study:dashboard"),
            "expression": reverse("study:expression"),
            "eo2-overview": reverse("study:task_detail", args=["eo", "tache-2"]),
            "eo2-directory": reverse("study:task_browse", args=["eo", "tache-2"]),
            "eo2-detail": reverse(
                "study:task_subject_detail", args=["eo", "tache-2", "janvier", 1, 1]
            ),
            "eo1-overview": reverse("study:task_detail", args=["eo", "tache-1"]),
        }

    @contextmanager
    def _no_bundled_reads(self):
        original_open = Path.open

        def open_path(path, *args, **kwargs):
            self.assertFalse(
                path.is_relative_to(content.CONTENT_DIR),
                f"Warmed request reopened bundled file: {path}",
            )
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", open_path):
            yield

    def _html(self, response):
        self.assertEqual(response.status_code, 200)
        # Django masks the CSRF token independently for each rendered request.
        return re.sub(
            rb'(name="csrfmiddlewaretoken" value=")[^"]+',
            rb'\1CSRF',
            response.content,
        )

    def test_warmed_pages_do_not_reopen_content_and_keep_the_same_output(self):
        for name, url in self._pages().items():
            with self.subTest(page=name):
                cold = self._html(self.client.get(url))
                with self._no_bundled_reads():
                    for _ in range(2):
                        self.assertEqual(self._html(self.client.get(url)), cold)

    def _summary(self, response, task_slug):
        self.assertEqual(response.status_code, 200)
        paths = (
            response.context["expression_paths"]
            if "expression_paths" in response.context
            else response.context["paths"]
        )
        return next(
            row["stats"]
            for path in paths
            if path["part"].slug == "eo"
            for row in path["tasks"]
            if row["task"].slug == task_slug
        )

    def test_warmed_pages_keep_progress_fresh_and_private(self):
        pages = self._pages()
        for url in pages.values():
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(
            self._summary(self.client.get(pages["dashboard"]), "tache-2")["completed"],
            0,
        )

        Card.objects.filter(
            user=self.user, response=self.prompt.response, card_type=CardType.SPINE
        ).update(subject_completed_at=self.now)
        memory = catalogue.task_memoires("eo", "tache-1")[0]
        MemoryQuestionProgress.objects.create(
            user=self.user,
            memory_number=memory.number,
            question_key=memory.question_keys[0],
        )
        group_count = Prompt.objects.filter(
            theme__task=self.prompt.theme.task, is_active=True,
        ).values("response_id").distinct().count()

        with self._no_bundled_reads():
            for name in ("dashboard", "expression"):
                response = self.client.get(pages[name])
                summary = self._summary(response, "tache-2")
                self.assertEqual(summary["total"], group_count)
                self.assertEqual(summary["completed"], 1)
                self.assertEqual(
                    self._summary(response, "tache-1")["completed"], 1
                )
            detail = self.client.get(pages["eo2-detail"])
            self.assertTrue(detail.context["subject_progress"].explicitly_completed)
            self.assertEqual(detail.context["selected_prompt"].pk, self.prompt.pk)
            bank_page = self.client.get(pages["eo1-overview"])
            self.assertEqual(bank_page.context["memory_progress"].completed, 1)

            self.client.force_login(self.other)
            for name in ("dashboard", "expression"):
                response = self.client.get(pages[name])
                self.assertEqual(self._summary(response, "tache-2")["completed"], 0)
                self.assertEqual(self._summary(response, "tache-1")["completed"], 0)
            detail = self.client.get(pages["eo2-detail"])
            self.assertFalse(detail.context["subject_progress"].explicitly_completed)

    def test_warmed_catalogue_does_not_cache_active_database_content(self):
        url = self._pages()["eo2-detail"]
        self.assertEqual(self.client.get(url).status_code, 200)
        with self._no_bundled_reads():
            Prompt.objects.filter(pk=self.prompt.pk).update(is_active=False)
            self.assertEqual(self.client.get(url).status_code, 404)
            Prompt.objects.filter(pk=self.prompt.pk).update(is_active=True)
            self.assertEqual(self.client.get(url).status_code, 200)
