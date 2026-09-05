"""Content, view, and progress coverage for the Learn curriculum."""

from __future__ import annotations

import json
import re
import tempfile
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
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

    def test_notion_and_mixed_lessons_require_source_labels(self):
        for source_type in ("notion", "mixed"):
            with self.subTest(source_type=source_type):
                payload = _catalog_payload()
                lesson = payload["modules"][0]["lessons"][0]
                lesson["source_type"] = source_type
                lesson["sources"] = ["Notion · Tips 1"]
                catalog = load_learning_catalog(self._write_payload(payload))
                self.assertEqual(catalog.lessons[0].source_type, source_type)

                lesson["sources"] = []
                with self.assertRaisesRegex(ValueError, "sources"):
                    load_learning_catalog(self._write_payload(payload))

    def test_bundled_catalog_is_cached_between_requests(self):
        self.assertIs(load_learning_catalog(), load_learning_catalog())

    def test_topics_are_grouped_in_a_clear_learning_order(self):
        catalog = load_learning_catalog()
        self.assertEqual(
            [module.id for module in catalog.modules],
            [
                "grammar-foundations",
                "spelling-punctuation",
                "verbs-tenses-moods",
                "pronouns-questions-negation",
                "time-place-prepositions",
                "communication-expressions",
                "word-meanings-expressions",
                "everyday-vocabulary",
                "exam-writing",
                "learning-strategy",
            ],
        )
        for slug, category in {
            "orthography-diacritics": "spelling-punctuation",
            "writing-capitalisation": "spelling-punctuation",
            "writing-punctuation-typography": "spelling-punctuation",
            "imperative": "verbs-tenses-moods",
            "grammar-relative-pronouns": "pronouns-questions-negation",
            "daily-on-usage": "pronouns-questions-negation",
            "expressions-opinion-preference": "communication-expressions",
            "verbs-lexical-distinctions": "word-meanings-expressions",
            "daily-social-idioms": "word-meanings-expressions",
            "lexicon-aller-suit": "everyday-vocabulary",
        }.items():
            with self.subTest(lesson=slug):
                module, _lesson = catalog.lesson_by_slug(slug)
                self.assertEqual(module.id, category)

    def test_new_vocabulary_topics_are_not_buried_in_grammar_or_abbreviations(self):
        catalog = load_learning_catalog()
        for source, target, section_ids in (
            (
                "grammar-adjective-agreement",
                "daily-description-personality",
                {
                    "describing-weight-shape-and-condition",
                    "describing-impressions-and-coolness",
                    "describing-personality-and-reputation",
                    "net-and-pareil-by-context",
                },
            ),
            (
                "lexicon-abbreviations-register",
                "daily-school-work",
                {
                    "school-stages-subjects-and-activities",
                    "learner-interface-and-personal-information",
                    "occupations-and-people-in-charge",
                },
            ),
        ):
            with self.subTest(lesson=target):
                _module, original = catalog.lesson_by_slug(source)
                module, focused = catalog.lesson_by_slug(target)
                self.assertEqual(module.id, "everyday-vocabulary")
                self.assertEqual(
                    {section.id for section in focused.sections}, section_ids
                )
                self.assertTrue(
                    section_ids.isdisjoint(section.id for section in original.sections)
                )
                self.assertIn("core-concept", {section.id for section in original.sections})

    def test_supported_variants_are_not_listed_as_grammar_errors(self):
        catalog = load_learning_catalog()
        for slug, supported in {
            "writing-job-application": "J’ai postulé ce poste la semaine dernière.",
            "daily-social-idioms": "Merci beaucoup. — Plaisir partagé.",
            "lexicon-part-partie": "Chacun doit faire sa partie du travail.",
        }.items():
            with self.subTest(lesson=slug):
                _module, lesson = catalog.lesson_by_slug(slug)
                self.assertNotIn(
                    supported,
                    [
                        mistake.avoid
                        for section in lesson.sections
                        for mistake in section.mistakes
                    ],
                )

    def test_french_correction_fields_do_not_contain_english_instructions(self):
        for lesson in load_learning_catalog().lessons:
            for section in lesson.sections:
                for mistake in section.mistakes:
                    for text in (mistake.avoid, mistake.prefer):
                        with self.subTest(lesson=lesson.id, correction=text):
                            self.assertNotRegex(
                                text,
                                r"^(?:Translating|Reading|Translate|Read|Use|"
                                r"Always translating)\b",
                            )
                            self.assertNotIn("(intended:", text)
                            self.assertNotIn("(intended only:", text)

    def test_notion_teaching_terms_are_in_visible_sections(self):
        catalog = load_learning_catalog()
        for slug, terms in {
            "grammar-articles-gender": ("un arbre", "un niveau", "FLE"),
            "daily-sports-music": ("le footing", "un jogging"),
            "verbs-subjunctive": ("prenions", "voulions", "past subjunctive"),
            "verbs-conditional-si": (
                "au cas où", "pourvu que", "viendrait", "aurais dû",
            ),
            "connectors-concession": ("avoir beau", "quand même"),
            "connectors-logical-organization": (
                "c’est-à-dire", "autrement dit", "à savoir", "du moins", "tel que",
            ),
            "verbs-infinitive-time-purpose": (
                "de manière à", "en vue de", "histoire de", "dans le but de",
            ),
            "imperative": ("soyez", "ayez", "soyons", "ayons"),
            "verbs-future": ("saur", "tiendr"),
        }.items():
            with self.subTest(lesson=slug):
                _module, lesson = catalog.lesson_by_slug(slug)
                visible_text = " ".join(
                    text
                    for section in lesson.sections
                    for text in (
                        section.title,
                        *section.paragraphs,
                        *section.points,
                        *(example.french for example in section.examples),
                    )
                ).casefold().replace("’", "'")
                for term in terms:
                    self.assertIn(term.casefold().replace("’", "'"), visible_text)

    def test_new_notion_topics_can_be_found_in_lesson_search(self):
        catalog = load_learning_catalog()
        for slug, terms in {
            "grammar-articles-gender": ("FLE", "niveau"),
            "daily-sports-music": ("footing", "jogging"),
            "connectors-logical-organization": ("autrement dit", "tel que"),
            "verbs-conditional-si": ("au cas où", "pourvu que"),
            "daily-school-work": ("maternelle", "factrice", "examen"),
            "daily-description-personality": ("talentueux", "pointu", "extraverti"),
            "daily-news-community": ("informations", "solidarité"),
        }.items():
            with self.subTest(lesson=slug):
                _module, lesson = catalog.lesson_by_slug(slug)
                for term in terms:
                    self.assertIn(
                        term.casefold(),
                        lesson.searchable_text.casefold(),
                    )

    def test_country_reference_keeps_all_source_families_visible(self):
        _module, lesson = load_learning_catalog().lesson_by_slug(
            "lexicon-country-nationalities"
        )
        reference = [
            point
            for section in lesson.sections
            if section.id.startswith("country-reference-")
            for point in section.points
        ]
        self.assertEqual(len(reference), 51)
        self.assertEqual(
            {point.split(" — ", 1)[0] for point in reference},
            {
                "l’Albanie (f.)", "l’Allemagne (f.)", "l’Andorre (f.)",
                "l’Arménie (f.)", "l’Autriche (f.)", "l’Azerbaïdjan (m.)",
                "la Belgique (f.)", "la Biélorussie (f.)",
                "la Bosnie-Herzégovine (f.)", "la Bulgarie (f.)",
                "Chypre (f.; normally no article)", "la Croatie (f.)",
                "le Danemark (m.)", "l’Espagne (f.)", "l’Estonie (f.)",
                "la Finlande (f.)", "la France (f.)", "la Géorgie (f.)",
                "la Grèce (f.)", "la Hongrie (f.)", "l’Irlande (f.)",
                "l’Islande (f.)", "l’Italie (f.)", "le Kazakhstan (m.)",
                "le Kosovo (m.)", "la Lettonie (f.)", "le Liechtenstein (m.)",
                "la Lituanie (f.)", "le Luxembourg (m.)",
                "la Macédoine du Nord (f.)", "Malte (f.; normally no article)",
                "la Moldavie (f.)", "Monaco (normally no article)",
                "le Monténégro (m.)", "la Norvège (f.)", "les Pays-Bas (m. pl.)",
                "la Pologne (f.)", "le Portugal (m.)", "la République tchèque (f.)",
                "la Roumanie (f.)", "le Royaume-Uni (m.)", "la Russie (f.)",
                "Saint-Marin (m.; normally no article)", "la Serbie (f.)",
                "la Slovaquie (f.)", "la Slovénie (f.)", "la Suède (f.)",
                "la Suisse (f.)", "la Turquie (f.)", "l’Ukraine (f.)",
                "le Vatican (m.)",
            },
        )
        for point in reference:
            with self.subTest(country=point):
                _name, meaning, adjectives = point.split(" — ")
                self.assertTrue(meaning)
                self.assertIn(" / ", adjectives)
        reference_text = " ".join(reference)
        for forms in ("letton / lettone", "grec / grecque", "turc / turque"):
            self.assertIn(forms, reference_text)

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

    def test_bundled_curriculum_preserves_source_labels_and_noun_examples(self):
        catalog = load_learning_catalog(LEARNING_CONTENT_PATH)
        source_labels = {
            source
            for lesson in catalog.lessons
            for source in lesson.sources
        }
        pdf_sources = {
            source for source in source_labels if source.startswith("Tips ")
        }
        notion_sources = {
            source
            for source in source_labels
            if source.startswith(("Notion · ", "Essentials · "))
        }

        self.assertGreaterEqual(len(catalog.modules), 8)
        self.assertGreaterEqual(len(catalog.lessons), 80)
        self.assertEqual(
            pdf_sources,
            {f"Tips {number}" for number in range(2, 31)},
        )
        self.assertTrue(
            {
                "Essentials · Punctuation",
                "Essentials · Majuscule",
                "Essentials · Tenses",
                "Essentials · Connectors",
                "Notion · Tips 1",
                "Notion · Tips Revision",
            }.issubset(notion_sources)
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
        self.assertTemplateUsed(response, "study/partials/theme_group_summary.html")
        self.assertContains(
            response, "data-learning-module-status", count=len(self.catalog.modules)
        )
        self.assertContains(
            response,
            "data-learning-module-details",
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

    def test_hub_loads_lesson_progress_in_one_query(self):
        self.client.get(reverse("study:learn"))
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("study:learn"))
        self.assertEqual(response.status_code, 200)
        progress_queries = [
            query["sql"]
            for query in queries
            if "study_learninglessonprogress" in query["sql"]
        ]
        self.assertEqual(len(progress_queries), 1)

    def test_all_lessons_render_examples_without_removed_sections(self):
        for lesson in self.catalog.lessons:
            with self.subTest(lesson=lesson.id):
                response = self.client.get(
                    reverse("study:learn_lesson", args=[lesson.slug])
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, lesson.title)
                self.assertContains(
                    response,
                    'class="learn-example"',
                    count=sum(len(section.examples) for section in lesson.sections),
                )
                for removed in ("learn-vocabulary-item", "learn-practice", "learn-takeaways"):
                    self.assertNotContains(response, removed)

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

    def test_reorganizing_a_lesson_preserves_its_completion_and_url(self):
        source, lesson = self.catalog.lesson_by_slug("imperative")
        target = next(
            module for module in self.catalog.modules if module.id != source.id
        )
        progress = LearningLessonProgress.objects.create(
            user=self.user, lesson_id=lesson.id, completed_at=timezone.now()
        )
        original_completion = progress.completed_at
        modules = []
        for module in self.catalog.modules:
            lessons = tuple(item for item in module.lessons if item.id != lesson.id)
            if module.id == target.id:
                lessons += (lesson,)
            modules.append(replace(module, lessons=lessons))
        reorganized = replace(self.catalog, modules=tuple(modules))

        with patch(
            "study.views.learning.load_learning_catalog", return_value=reorganized
        ):
            hub = self.client.get(reverse("study:learn"))
            detail = self.client.get(
                reverse("study:learn_lesson", args=[lesson.slug])
            )

        group = next(
            item for item in hub.context["modules"] if item["module"].id == target.id
        )
        card = next(item for item in group["lessons"] if item["lesson"].id == lesson.id)
        self.assertTrue(card["completed"])
        self.assertEqual(card["status"], "done")
        self.assertEqual(group["progress"].completed, 1)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.context["module"].id, target.id)
        self.assertTrue(detail.context["is_completed"])
        progress.refresh_from_db()
        self.assertEqual(progress.completed_at, original_completion)

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
