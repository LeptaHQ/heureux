"""Content, view, and progress coverage for the Learn curriculum."""

from __future__ import annotations

import json
import re
import tempfile
from copy import deepcopy
from pathlib import Path

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from study.learning_content import (
    LEARNING_CONTENT_PATH,
    NOUN_ARTICLE_RE,
    NOUN_GENDER_RE,
    load_learning_catalog,
)
from study.models import LearningLessonProgress
from study.templatetags.study_markdown import render_markdown_inline

from . import factories


def _catalog_payload():
    return {
        "version": 1,
        "title": "Apprendre le français",
        "description": "Un parcours structuré.",
        "modules": [
            {
                "id": "fondations",
                "slug": "fondations",
                "title": "Fondations",
                "description": "Construire des bases fiables.",
                "icon": "graduation-cap",
                "color": "#357566",
                "order": 1,
                "lessons": [
                    {
                        "id": "articles-et-genres",
                        "slug": "articles-et-genres",
                        "title": "Les articles et les genres",
                        "summary": "Apprendre chaque nom avec son article.",
                        "level": "Fondamental",
                        "duration_minutes": 8,
                        "source_type": "pdf",
                        "sources": ["Tips 2"],
                        "objectives": [
                            "Associer un nom à son article.",
                        ],
                        "sections": [
                            {
                                "id": "regle",
                                "title": "La règle",
                                "paragraphs": [
                                    "Le déterminant révèle souvent le genre.",
                                ],
                                "points": [
                                    "Mémoriser le groupe nominal complet.",
                                ],
                                "examples": [
                                    {
                                        "french": "La stratégie est claire.",
                                        "english": "The strategy is clear.",
                                        "note": "",
                                    },
                                    {
                                        "french": "Une méthode régulière facilite les progrès.",
                                        "english": "A regular method makes progress easier.",
                                        "note": "",
                                    },
                                    {
                                        "french": "Le programme commence lundi.",
                                        "english": "The program starts on Monday.",
                                        "note": "",
                                    },
                                    {
                                        "french": "Du matériel est disponible à l’accueil.",
                                        "english": "Some materials are available at reception.",
                                        "note": "",
                                    },
                                ],
                                "mistakes": [
                                    {
                                        "avoid": "un stratégie",
                                        "prefer": "une stratégie",
                                        "why": "Le nom stratégie est féminin.",
                                    },
                                    {
                                        "avoid": "Je cherche information.",
                                        "prefer": "Je cherche une information.",
                                        "why": "Le nom commun singulier prend un déterminant.",
                                    }
                                ],
                            }
                        ],
                        "vocabulary": [
                            {
                                "kind": "noun",
                                "french": "la stratégie (f.)",
                                "english": "strategy",
                                "example": "La stratégie est claire.",
                                "note": "Nom féminin.",
                            }
                        ],
                        "practice": [
                            {
                                "prompt": "Complète : ___ stratégie.",
                                "hint": "Le nom est féminin.",
                                "answer": "La stratégie.",
                            }
                        ],
                        "takeaways": [
                            "Toujours apprendre le nom avec son article.",
                        ],
                        "keywords": ["article", "genre"],
                    }
                ],
            }
        ],
    }


class LearningContentTests(TestCase):
    def _write_payload(self, payload) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "curriculum.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_loader_builds_a_typed_catalog(self):
        catalog = load_learning_catalog(self._write_payload(_catalog_payload()))

        self.assertEqual(catalog.title, "Apprendre le français")
        self.assertEqual(catalog.modules[0].lessons[0].id, "articles-et-genres")
        self.assertEqual(
            catalog.modules[0].lessons[0].vocabulary[0].kind_label,
            "Nom",
        )

    def test_loader_requires_an_article_and_gender_for_nouns(self):
        payload = deepcopy(_catalog_payload())
        payload["modules"][0]["lessons"][0]["vocabulary"][0]["french"] = (
            "stratégie"
        )

        with self.assertRaisesRegex(
            ValueError,
            "article and gender marker",
        ):
            load_learning_catalog(self._write_payload(payload))

    def test_loader_rejects_duplicate_lesson_ids(self):
        payload = deepcopy(_catalog_payload())
        duplicate = deepcopy(payload["modules"][0]["lessons"][0])
        duplicate["slug"] = "autre-lecon"
        payload["modules"][0]["lessons"].append(duplicate)

        with self.assertRaisesRegex(ValueError, "repeats a lesson id"):
            load_learning_catalog(self._write_payload(payload))

    def test_inline_teaching_copy_marks_french_targets(self):
        rendered = render_markdown_inline(
            "Use `être` and compare « avoir besoin de »."
        )

        self.assertIn('<code lang="fr">être</code>', rendered)
        self.assertIn(
            '<span lang="fr">« avoir besoin de »</span>',
            rendered,
        )

    def test_bundled_curriculum_covers_every_source_and_uses_real_examples(self):
        catalog = load_learning_catalog(LEARNING_CONTENT_PATH)
        pdf_sources = {
            source
            for lesson in catalog.lessons
            if lesson.source_type == "pdf"
            for source in lesson.sources
        }

        self.assertGreaterEqual(len(catalog.modules), 8)
        self.assertGreaterEqual(len(catalog.lessons), 67)
        self.assertEqual(
            pdf_sources,
            {f"Tips {number}" for number in range(2, 31)},
        )

        for lesson in catalog.lessons:
            with self.subTest(lesson=lesson.id):
                self.assertTrue(lesson.sections)
                self.assertTrue(lesson.practice)
                self.assertTrue(lesson.takeaways)
            for vocabulary in lesson.vocabulary:
                if vocabulary.kind != "noun":
                    continue
                with self.subTest(
                    lesson=lesson.id,
                    noun=vocabulary.french,
                ):
                    self.assertRegex(vocabulary.french, NOUN_ARTICLE_RE)
                    self.assertRegex(vocabulary.french, NOUN_GENDER_RE)
                    target = NOUN_GENDER_RE.sub("", vocabulary.french).strip()
                    example = vocabulary.example.casefold()
                    lemmas = [
                        NOUN_ARTICLE_RE.sub("", variant.strip())
                        .casefold()
                        .replace("’", "'")
                        .split()[0]
                        for variant in target.split("/")
                    ]
                    self.assertTrue(
                        any(
                            lemma in example.replace("’", "'")
                            for lemma in lemmas
                        ),
                        f"{vocabulary.french!r} is absent from "
                        f"{vocabulary.example!r}",
                    )


class LearningViewTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("learning-view")
        self.client.force_login(self.user)
        self.catalog = load_learning_catalog()
        self.lesson = self.catalog.lessons[0]

    def test_hub_renders_searchable_modules_and_active_navigation(self):
        response = self.client.get(reverse("study:learn"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-active-area="learn"')
        self.assertContains(response, "data-learning-search")
        self.assertContains(response, "data-collection-view-toggle")
        self.assertContains(response, "collection-table--learn")
        self.assertContains(
            response,
            "data-learning-module-toggle",
            count=len(self.catalog.modules),
        )
        self.assertContains(
            response,
            "data-learning-card-progress",
            count=len(self.catalog.lessons),
        )
        self.assertContains(response, "data-learning-card-check")
        self.assertNotContains(response, "Continuer le parcours")
        self.assertNotContains(response, "Bien commencer")
        self.assertContains(response, self.lesson.title)
        self.assertEqual(
            response.context["summary"].total,
            len(self.catalog.lessons),
        )

    def test_viewing_is_safe_and_start_endpoint_is_user_scoped(self):
        other_user = factories.make_user("other-learning-view")

        response = self.client.get(
            reverse("study:learn_lesson", args=[self.lesson.slug])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="learn-content-section card"')
        self.assertContains(response, 'lang="en"')
        self.assertContains(response, '<code lang="fr">')
        self.assertNotContains(
            response,
            'data-read-aloud-target="core-concept"',
        )
        lesson_identity = (
            response.content.decode()
            .split('<div class="learn-lesson-hero__identity">', 1)[1]
            .split('<div class="learn-lesson-hero__meta">', 1)[0]
        )
        self.assertEqual(lesson_identity.count("<p"), 1)
        for removed_section in (
            "Vocabulaire utile",
            "S’entraîner",
            "À retenir",
            "Origine de cette leçon",
            "learn-outline",
        ):
            self.assertNotContains(response, removed_section)
        self.assertFalse(
            LearningLessonProgress.objects.filter(
                user=self.user,
                lesson_id=self.lesson.id,
            ).exists()
        )

        started = self.client.post(
            reverse("study:learn_lesson_start", args=[self.lesson.slug]),
            HTTP_X_REQUESTED_WITH="fetch",
        )

        self.assertEqual(started.status_code, 200)
        self.assertTrue(
            LearningLessonProgress.objects.filter(
                user=self.user,
                lesson_id=self.lesson.id,
                completed_at__isnull=True,
            ).exists()
        )
        self.assertFalse(
            LearningLessonProgress.objects.filter(
                user=other_user,
                lesson_id=self.lesson.id,
            ).exists()
        )

    def test_repeated_completion_preserves_the_original_timestamp(self):
        url = reverse(
            "study:learn_lesson_progress",
            args=[self.lesson.slug],
        )
        self.client.post(url, {"completed": "1"})
        original = LearningLessonProgress.objects.get(
            user=self.user,
            lesson_id=self.lesson.id,
        ).completed_at

        self.client.post(url, {"completed": "1"})

        self.assertEqual(
            LearningLessonProgress.objects.get(
                user=self.user,
                lesson_id=self.lesson.id,
            ).completed_at,
            original,
        )

    def test_progress_endpoint_marks_and_reopens_a_lesson(self):
        url = reverse(
            "study:learn_lesson_progress",
            args=[self.lesson.slug],
        )

        completed = self.client.post(
            url,
            {"completed": "1"},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        reopened = self.client.post(
            url,
            {"completed": "0"},
            HTTP_X_REQUESTED_WITH="fetch",
        )

        self.assertEqual(completed.status_code, 200)
        self.assertTrue(completed.json()["completed"])
        self.assertFalse(reopened.json()["completed"])
        self.assertIsNone(
            LearningLessonProgress.objects.get(
                user=self.user,
                lesson_id=self.lesson.id,
            ).completed_at
        )

    def test_progress_endpoint_rejects_invalid_state_and_unknown_lesson(self):
        invalid = self.client.post(
            reverse(
                "study:learn_lesson_progress",
                args=[self.lesson.slug],
            ),
            {"completed": "yes"},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        missing = self.client.post(
            reverse(
                "study:learn_lesson_progress",
                args=["lecon-inconnue"],
            ),
            {"completed": "1"},
        )

        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(missing.status_code, 404)

    def test_account_export_includes_learning_progress(self):
        LearningLessonProgress.objects.create(
            user=self.user,
            lesson_id=self.lesson.id,
        )

        payload = self.client.get(reverse("study:export_account")).json()

        self.assertEqual(payload["version"], 8)
        self.assertEqual(
            payload["learning_lesson_progress"][0]["lesson_id"],
            self.lesson.id,
        )

    def test_dashboard_and_stats_include_learning_progress(self):
        LearningLessonProgress.objects.create(
            user=self.user,
            lesson_id=self.lesson.id,
            completed_at=timezone.now(),
        )

        dashboard = self.client.get(reverse("study:dashboard"))
        stats = self.client.get(reverse("study:stats"))
        breakdown = {
            item["key"]: item["count"]
            for item in stats.context["breakdown"]
        }

        self.assertEqual(
            dashboard.context["learning"]["progress"].completed,
            1,
        )
        self.assertContains(dashboard, "Apprendre")
        self.assertEqual(breakdown["lessons"], 1)
