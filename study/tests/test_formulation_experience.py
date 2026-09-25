from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from study import queue
from study.formulation_progress import (
    formulation_language_content_key,
    formulation_progress,
)
from study.models import (
    Annotation, AnnotationKind, Card, CardState, MemoryQuestionProgress, Phrase,
    PhraseTier, Rating, ReviewLog, ReviewSession, ThemeVocabularyProgress,
)
from study.retirement import active_phrases
from study.progress import progress_summary
from study.srs import review as apply_review
from study.views.helpers import expression_task_summaries, _task_card
from . import factories
from .formulation_fixtures import THEMES, formulation_catalog, mock_catalog


class FormulationExperienceTests(TestCase):
    def setUp(self):
        self.user = factories.make_user()
        self.other = factories.make_user()
        self.task = factories.make_task(factories.make_part("ee"), "tache-3")
        self.theme = factories.make_theme("ee-tache-3-education", task=self.task)
        self.response = factories.make_response(theme=self.theme)
        self.catalog = formulation_catalog(self.response.content_key)
        self.mocks = mock_catalog(self.catalog)
        self.addCleanup(self.mocks.close)
        self.client.force_login(self.user)
        self.url = reverse("study:ee_formulations")
        self.essentials_url = reverse("study:ee_formulation_essentials")
        self.function_url = reverse(
            "study:ee_formulation_function", args=["affirmation"],
        )
        self.synthesis_url = reverse(
            "study:ee_formulation_function", args=["synthese"],
        )
        self.search_url = reverse("study:ee_formulation_search")

    def test_nested_tables_open_clear_subdivision_pages(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="formulation-directory-tables"')
        self.assertContains(
            response,
            'class="t1-table-groups formulation-directory-table"',
            count=2,
        )
        self.assertContains(response, "Fonctions d’écriture")
        self.assertContains(response, "Thèmes")
        self.assertContains(
            response,
            "formulation-subdivision-disclosure",
        )
        self.assertContains(response, "data-formulation-topic-row")
        self.assertNotContains(response, "Ouvrir toute la subdivision")
        self.assertNotContains(response, "Ouvrir les 16 essentiels")
        self.assertNotContains(response, 'class="formulation-list"')

        response = self.client.get(self.function_url)
        self.assertContains(
            response,
            'class="formulation-list formulation-lesson-content"',
        )
        self.assertNotContains(response, "data-formulation-practice")
        self.assertContains(response, "Essentiels · Fonction d’écriture")
        self.assertContains(response, "Sens en anglais")
        self.assertContains(response, "Construction et grammaire")
        self.assertContains(response, "Exemple du modèle de référence")
        self.assertContains(response, "Je sais reproduire et adapter")
        self.assertContains(response, reverse("study:response_detail", args=[
            "ee", "tache-3", self.response.prompts.first().pk,
        ]))
        self.assertContains(
            response,
            'data-annotation-source-key="formulation:ee3:v1:',
            count=2,
        )
        self.assertNotContains(response, 'name="transfer_response"')

        response = self.client.get(reverse(
            "study:ee_formulation_entry", args=["cadre-0"],
        ))
        self.assertContains(response, "formulation-entry-lesson")
        self.assertContains(response, "Comprendre et appliquer")
        self.assertContains(response, "formulation-entry-focus__text")
        self.assertContains(
            response,
            'data-annotation-source-key="formulation:ee3:v1:cadre-0"',
        )
        self.assertNotContains(response, 'class="formulation-list')
        self.assertNotContains(response, "formulation-topic-sidebar")

    def test_synthesis_page_has_a_reporting_language_reference(self):
        response = self.client.get(reverse(
            "study:ee_formulation_language", args=["synthese"],
        ))
        self.assertContains(
            response, "Verbes utiles pour présenter les documents",
        )
        for phrase in (
            "mettre en avant",
            "mettre en garde contre",
            "indiquer",
        ):
            self.assertContains(response, phrase)

    def test_entry_navigation_is_repeated_above_and_below(self):
        next_url = reverse(
            "study:ee_formulation_entry", args=["cadre-1"],
        )
        response = self.client.get(reverse(
            "study:ee_formulation_entry", args=["cadre-0"],
        ))
        self.assertContains(
            response,
            'aria-label="Navigation entre les formulations"',
            count=2,
        )
        self.assertContains(
            response, '<span class="prompt-nav__position">1 sur 2</span>',
            count=2, html=True,
        )
        self.assertContains(
            response, f'href="{next_url}" rel="next"', count=2,
        )
        self.assertContains(response, "prompt-nav--bottom", count=1)
        self.assertNotContains(response, "formulation-entry-hero__summary")

    def test_each_theme_page_has_a_useful_vocabulary_reference(self):
        for theme in THEMES:
            with self.subTest(theme=theme):
                response = self.client.get(reverse(
                    "study:ee_formulation_language", args=[theme],
                ))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Vocabulaire utile")
                self.assertGreaterEqual(
                    len(response.context["language_bank"]), 24,
                )
                self.assertEqual(
                    len(response.context["language_sections"]), 7,
                )
                self.assertGreaterEqual(
                    response.context["example_count"], 28,
                )
                self.assertNotContains(
                    response,
                    "Chaque exemple complet vient d’une réponse de référence",
                )

    def test_vocabulary_checkmarks_are_private_and_persistent(self):
        page_url = reverse(
            "study:ee_formulation_language", args=["education"],
        )
        response = self.client.get(page_url)
        row = response.context["language_sections"][0]["items"][0]
        item = row["item"]
        progress_url = reverse(
            "study:ee_formulation_language_progress",
            args=["education", row["item_id"]],
        )
        key = formulation_language_content_key(
            "education", item.french,
        )
        self.assertLessEqual(len(key), 96)
        self.assertEqual(self.client.get(progress_url).status_code, 405)
        self.assertEqual(
            self.client.post(
                progress_url, {"completed": "maybe"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                progress_url, {"completed": ["0", "1"]},
            ).status_code,
            400,
        )
        result = self.client.post(
            progress_url, {"completed": "1"},
        )
        self.assertEqual(
            result.url,
            page_url + "#vocabulaire-" + row["item_id"],
        )
        self.assertTrue(MemoryQuestionProgress.objects.filter(
            user=self.user,
            memory_number=1,
            question_key=key,
        ).exists())
        self.assertFalse(MemoryQuestionProgress.objects.filter(
            user=self.other,
            memory_number=1,
            question_key=key,
        ).exists())
        response = self.client.get(page_url)
        self.assertEqual(response.context["language_progress"].completed, 1)
        self.assertTrue(
            response.context["language_sections"][0]["items"][0]["learned"],
        )
        other_progress = MemoryQuestionProgress.objects.create(
            user=self.other,
            memory_number=1,
            question_key=key,
        )
        self.client.post(progress_url, {"completed": "0"})
        self.assertFalse(MemoryQuestionProgress.objects.filter(
            user=self.user,
            memory_number=1,
            question_key=key,
        ).exists())
        self.assertTrue(MemoryQuestionProgress.objects.filter(
            pk=other_progress.pk,
        ).exists())
        self.assertEqual(
            self.client.post(
                reverse(
                    "study:ee_formulation_language_progress",
                    args=["education", "missing"],
                ),
                {"completed": "1"},
            ).status_code,
            404,
        )

    def test_all_themes_and_accent_insensitive_search(self):
        response = self.client.get(self.search_url, {"q": "PREVENTION"})
        self.assertEqual(response.context["result_count"], len(self.catalog.entries))
        response = self.client.get(self.essentials_url)
        self.assertEqual(response.context["result_count"], 2)
        response = self.client.get(self.function_url)
        self.assertEqual(response.context["result_count"], 2)
        response = self.client.get(self.search_url, {"q": "not-a-real-search"})
        self.assertContains(response, "Aucune formulation dans cette sélection")
        self.assertContains(response, "Réinitialiser les filtres")
        for query in ("improves health", "Adaptez cette construction"):
            response = self.client.get(self.search_url, {"q": query})
            self.assertEqual(response.context["result_count"], len(self.catalog.entries))

    def test_filter_ids_duplicates_and_open_redirects(self):
        for query in (
            "theme=invalid", "category=invalid", "status=invalid", "essential=2",
            "mode=flashcards", "entry=missing", "theme=education&theme=education",
            "q=a&q=b", "q=" + "x" * 201,
        ):
            self.assertEqual(self.client.get(self.url + "?" + query).status_code, 404)
        response = self.client.post(reverse("study:ee_formulation_progress", args=["cadre-0"]), {
            "completed": "1", "next": "https://example.invalid/", "q": "prevention",
        })
        self.assertEqual(urlsplit(response.url).netloc, "")
        self.assertEqual(parse_qs(urlsplit(response.url).query), {"q": ["prevention"]})

    def test_native_post_private_state_context_and_legacy_retention(self):
        legacy = MemoryQuestionProgress.objects.create(
            user=self.user, memory_number=1, question_key="legacy-question",
        )
        other = MemoryQuestionProgress.objects.create(
            user=self.other, memory_number=1, question_key=self.catalog.entries[0].content_key,
        )
        self.assertEqual(formulation_progress(self.user)[1].completed, 0)
        params = {
            "completed": "1", "q": "prévention", "status": "new",
            "mode": "practice", "entry": "cadre-0", "next": self.function_url,
        }
        url = reverse("study:ee_formulation_progress", args=["cadre-0"])
        self.assertEqual(self.client.get(url).status_code, 405)
        result = self.client.post(url, params)
        expected = {
            key: [value] for key, value in params.items()
            if key not in {"completed", "next"}
        }
        self.assertEqual(urlsplit(result.url).path, self.function_url)
        self.assertEqual(parse_qs(urlsplit(result.url).query), expected)
        self.assertEqual(formulation_progress(self.user)[1].completed, 1)
        self.assertEqual(self.client.get(result.url).context["result_count"], 1)
        self.client.post(url, {"completed": "0"})
        self.assertEqual(formulation_progress(self.user)[1].completed, 0)
        self.assertTrue(MemoryQuestionProgress.objects.filter(pk=legacy.pk).exists())
        self.assertTrue(MemoryQuestionProgress.objects.filter(pk=other.pk).exists())
        self.assertEqual(self.client.post(url, {"completed": "maybe"}).status_code, 400)
        self.assertEqual(self.client.post(url + "?next=bad", {"completed": ["0", "1"]}).status_code, 400)

    def test_note_or_highlight_marks_formulation_in_progress(self):
        entry = self.catalog.entries[0]
        detail_url = reverse(
            "study:ee_formulation_entry", args=[entry.slug],
        )
        created = self.client.post(
            reverse("study:annotation_create"),
            {
                "kind": AnnotationKind.NOTE,
                "quote": entry.french,
                "body": "À réutiliser.",
                "source_path": detail_url,
                "source_key": entry.content_key,
                "source_title": entry.label,
                "task_id": self.task.pk,
                "start_offset": 0,
                "end_offset": len(entry.french),
                "prefix": "",
                "suffix": "",
                "overlap_ids": "",
            },
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(
            created.json()["formulation_progress"]["status"],
            "active",
        )
        self.assertEqual(
            created.json()["formulation_progress"]["label"],
            "En cours",
        )
        state = formulation_progress(self.user, self.catalog)[1]
        self.assertEqual((state.started, state.completed), (1, 0))
        self.assertEqual(
            formulation_progress(self.other, self.catalog)[1].started,
            0,
        )

        detail = self.client.get(detail_url)
        self.assertEqual(detail.context["row"]["status"], "active")
        self.assertContains(
            detail,
            '<span class="progress-status progress-status--active" '
            f'data-formulation-status="{entry.slug}">En cours</span>',
            html=True,
        )
        directory = self.client.get(self.url)
        topic = next(
            topic
            for table in directory.context["tables"]
            for item in table["items"]
            for topic in item["topics"]
            if topic["slug"] == entry.slug
        )
        self.assertEqual(topic["status"], "active")
        active = self.client.get(self.function_url, {"status": "active"})
        self.assertEqual(active.context["result_count"], 1)
        self.assertEqual(active.context["rows"][0]["entry"], entry)
        self.assertEqual(
            self.client.get(
                self.function_url, {"status": "new"},
            ).context["result_count"],
            1,
        )

        annotation = Annotation.objects.get(
            user=self.user,
            source_key=entry.content_key,
        )
        deleted = self.client.post(
            reverse("study:annotation_delete", args=[annotation.pk]),
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertEqual(
            deleted.json()["formulation_progress"]["status"],
            "new",
        )
        self.assertEqual(
            formulation_progress(self.user, self.catalog)[1].started,
            0,
        )

    def test_fetch_progress_returns_live_counts_without_redirecting(self):
        entry = self.catalog.entries[0]
        response = self.client.post(
            reverse(
                "study:ee_formulation_progress",
                args=[entry.slug],
            ),
            {"completed": "1"},
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {
            "completed": True,
            "status": "done",
            "label": "Apprise",
            "slug": entry.slug,
            "tache": 3,
            "overall": {
                "status": "active",
                "label": "En cours",
                "total": len(self.catalog.entries),
                "started": 1,
                "completed": 1,
                "percent": 9,
            },
            "category": {
                "slug": entry.category,
                "status": "active",
                "label": "En cours",
                "total": 2,
                "started": 1,
                "completed": 1,
                "percent": 50,
            },
            "essentials": {
                "status": "active",
                "label": "En cours",
                "total": 2,
                "started": 1,
                "completed": 1,
                "percent": 50,
            },
        })

        language_page = self.client.get(reverse(
            "study:ee_formulation_language",
            args=["education"],
        ))
        language_row = language_page.context[
            "language_sections"
        ][0]["items"][0]
        response = self.client.post(
            language_row["progress_url"],
            {"completed": "1"},
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["completed"])
        self.assertEqual(response.json()["progress"]["completed"], 1)

    def test_explicit_practice_reveals_and_preserves_selection(self):
        response = self.client.get(self.essentials_url, {"mode": "practice"})
        self.assertContains(response, "data-formulation-practice")
        self.assertContains(response, "Révéler la formulation et l’exemple")
        self.assertContains(response, "data-flashcard-controls")
        self.assertContains(response, "data-prompt-copy")
        self.assertContains(response, "Formulation 1 sur 2")
        self.assertEqual(response.context["rows"][0]["entry"].slug, "cadre-0")
        next_url = response.context["next_url"]
        response = self.client.get(next_url)
        self.assertEqual(response.context["position"], 2)
        self.assertEqual(response.context["next_url"], "")

    def test_sources_are_batched_and_never_link_to_other_task(self):
        with CaptureQueriesContext(connection) as queries:
            self.client.get(self.function_url)
        source_queries = [
            query["sql"] for query in queries
            if 'FROM "study_prompt"' in query["sql"]
            and '"study_response"."content_key" IN' in query["sql"]
        ]
        self.assertEqual(len(source_queries), 1)
        self.theme.task = factories.make_task(factories.make_part("eo"))
        self.theme.save()
        response = self.client.get(self.function_url)
        self.assertTrue(all(not row["source_url"] for row in response.context["rows"]))

    def test_rollups_use_new_namespace_not_archived_memory(self):
        MemoryQuestionProgress.objects.create(
            user=self.user, memory_number=1, question_key="legacy-question",
        )
        summaries = expression_task_summaries(timezone.now(), self.user, [self.task])
        self.assertEqual(summaries[self.task.pk]["formulation_progress"].completed, 0)
        self.assertEqual(summaries[self.task.pk]["stats"]["total"], 1 + len(self.catalog.entries))
        card = _task_card(self.task, timezone.now(), self.user, summaries=summaries)
        self.assertEqual(card["question_bank"]["question_count"], len(self.catalog.entries))
        self.assertEqual(card["question_bank"]["subject_count"], 1)

    def test_removed_vocabulary_urls_404_and_numbered_memories_redirect(self):
        for route, args in (
            ("task_phrases", ["ee", "tache-3"]),
            ("task_vocabulary_category", ["ee", "tache-3", "nuancer"]),
        ):
            self.assertEqual(
                self.client.get(reverse("study:" + route, args=args)).status_code,
                404,
            )
        for theme in THEMES:
            response = self.client.get(reverse("study:task_vocabulary_theme", args=[
                "ee", "tache-3", "ee-tache-3-" + theme,
            ]))
            self.assertEqual(response.status_code, 404)
        self.assertRedirects(
            self.client.get(reverse(
                "study:task_memories", args=["ee", "tache-3"],
            )),
            self.url,
            fetch_redirect_response=False,
        )
        for number in range(1, 5):
            response = self.client.get(reverse("study:task_memory_detail", args=["ee", "tache-3", number]))
            self.assertRedirects(response, self.url, fetch_redirect_response=False)
            for route in ("task_memory_progress", "task_question_response"):
                response = self.client.post(reverse("study:" + route, args=["ee", "tache-3", number]), {
                    "question_key": "unused", "completed": "1",
                })
                self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertFalse(MemoryQuestionProgress.objects.filter(user=self.user).exists())
        self.assertNotContains(self.client.get(self.url), "archives")

    def test_directory_progress_updates_after_learning(self):
        response = self.client.get(self.url)
        self.assertContains(response, "0/2")
        self.client.post(
            reverse("study:ee_formulation_progress", args=["cadre-0"]),
            {"completed": "1", "next": self.function_url},
        )
        response = self.client.get(self.url)
        self.assertContains(response, "1/2")
        self.assertContains(
            response,
            'data-formulation-progress-completed="overall">1</b>',
        )
        self.assertContains(response, "<span><b>11</b> au total</span>", html=True)


class EeTacheOneFormulationExperienceTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("ee1-formulations")
        self.other = factories.make_user("ee1-formulations-other")
        self.task = factories.make_task(
            factories.make_part("ee"), "tache-1",
        )
        self.source_key = "ee-tache1:janvier:combinaison-1"
        self.sujet = factories.make_writing_sujet(
            task=self.task,
            slug="janvier-combinaison-1",
            category="education",
        )
        self.catalog = formulation_catalog(
            self.source_key, tache=1,
        )
        self.mocks = mock_catalog(self.catalog)
        self.addCleanup(self.mocks.close)
        self.client.force_login(self.user)

    def test_routes_nav_sources_and_task_header_are_isolated(self):
        directory = reverse("study:ee_tache_one_formulations")
        route_cases = (
            ("ee_tache_one_formulations", (), "/expression/ecrite/tache-1/formulations/"),
            ("ee_tache_one_formulation_search", (), "/expression/ecrite/tache-1/formulations/recherche/"),
            ("ee_tache_one_formulation_essentials", (), "/expression/ecrite/tache-1/formulations/essentiels/"),
            ("ee_tache_one_formulation_function", ("affirmation",), "/expression/ecrite/tache-1/formulations/essentiels/affirmation/"),
            ("ee_tache_one_formulation_theme", ("education",), "/expression/ecrite/tache-1/formulations/themes/education/"),
            ("ee_tache_one_formulation_entry", ("cadre-0",), "/expression/ecrite/tache-1/formulations/fiches/cadre-0/"),
            ("ee_tache_one_formulation_progress", ("cadre-0",), "/expression/ecrite/tache-1/formulations/progression/cadre-0/"),
            ("ee_tache_one_formulation_language", ("education",), "/expression/ecrite/tache-1/formulations/langue/education/"),
        )
        for name, args, expected in route_cases:
            with self.subTest(route=name):
                self.assertEqual(reverse("study:" + name, args=args), expected)
        response = self.client.get(directory)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, f"Formulations · {self.task.name} · Heureux",
        )
        html = response.content.decode()
        self.assertLess(html.index(">Sujets</a>"), html.index(">Formulations</a>"))
        self.assertNotContains(response, ">Vocabulaire</a>")
        self.assertContains(response, "Vocabulaire utile", count=3)

        function_url = reverse(
            "study:ee_tache_one_formulation_function",
            args=["affirmation"],
        )
        response = self.client.get(function_url)
        self.assertContains(
            response,
            reverse(
                "study:writing_sujet_detail",
                args=["ee", "tache-1", self.sujet.pk],
            ),
        )
        self.assertContains(response, ">Réponse</span>")
        self.assertNotContains(
            response,
            reverse(
                "study:response_detail",
                args=["ee", "tache-3", self.sujet.pk],
            ),
        )

    def test_progress_is_private_and_separate_from_ee3_namespace(self):
        entry = self.catalog.entries[0]
        url = reverse(
            "study:ee_tache_one_formulation_progress",
            args=[entry.slug],
        )
        result = self.client.post(url, {
            "completed": "1",
            "next": reverse("study:ee_formulations"),
        })
        self.assertEqual(
            urlsplit(result.url).path,
            reverse("study:ee_tache_one_formulations"),
        )
        self.assertTrue(MemoryQuestionProgress.objects.filter(
            user=self.user,
            question_key="formulation:ee1:v1:" + entry.slug,
        ).exists())
        self.assertFalse(MemoryQuestionProgress.objects.filter(
            user=self.other,
            question_key="formulation:ee1:v1:" + entry.slug,
        ).exists())
        self.assertFalse(MemoryQuestionProgress.objects.filter(
            user=self.user,
            question_key="formulation:ee3:v1:" + entry.slug,
        ).exists())

    def test_entry_navigation_is_repeated_above_and_below(self):
        next_url = reverse(
            "study:ee_tache_one_formulation_entry", args=["cadre-1"],
        )
        response = self.client.get(reverse(
            "study:ee_tache_one_formulation_entry", args=["cadre-0"],
        ))
        self.assertContains(
            response,
            'aria-label="Navigation entre les formulations"',
            count=2,
        )
        self.assertContains(
            response, '<span class="prompt-nav__position">1 sur 2</span>',
            count=2, html=True,
        )
        self.assertContains(
            response, f'href="{next_url}" rel="next"', count=2,
        )
        self.assertContains(response, "prompt-nav--bottom", count=1)
        self.assertNotContains(response, "formulation-entry-hero__summary")

    def test_removed_vocabulary_routes_return_404(self):
        theme = factories.make_theme(
            "ee-tache-1-education", task=self.task,
        )
        phrase = factories.make_phrase(
            tier=PhraseTier.THEME,
            vocabulary_theme=theme,
        )
        self.assertEqual(
            self.client.get(reverse(
                "study:task_vocabulary_theme",
                args=["ee", "tache-1", theme.slug],
            )).status_code,
            404,
        )
        search = self.client.get(
            reverse("study:task_search", args=["ee", "tache-1"]),
            {"q": phrase.expression},
        )
        self.assertEqual(search.context["phrase_result_count"], 0)
        for route, args in (
            ("task_phrases", ["ee", "tache-1"]),
            ("task_vocabulary_category", ["ee", "tache-1", "nuancer"]),
        ):
            self.assertEqual(
                self.client.get(
                    reverse("study:" + route, args=args)
                ).status_code,
                404,
            )
        self.assertEqual(
            self.client.post(reverse(
                "study:theme_vocabulary_progress",
                args=["ee", "tache-1", theme.slug, 999999],
            )).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("study:task_review", args=["ee", "tache-1"]),
                {"kind": "vocab", "theme": theme.slug},
            ).status_code,
            404,
        )

    def test_overview_puts_subjects_before_formulations_without_vocabulary(self):
        subject_progress = progress_summary(total=1, started=0, completed=0)
        subject_context = {
            "category_count": 1,
            "sujet_count": 1,
            "distinct_count": 1,
            "response_count": 1,
            "personalized_count": 0,
            "completed_count": 0,
            "subject_progress": subject_progress,
            "writing_tache": 1,
        }
        with (
            patch(
                "study.views.library._ee_writing_sujet_ids_by_slug",
                return_value={self.sujet.slug: self.sujet.pk},
            ),
            patch(
                "study.views.library._ee_writing_overview_context",
                return_value=subject_context,
            ),
        ):
            response = self.client.get(reverse(
                "study:task_detail", args=["ee", "tache-1"],
            ))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<dt>Formulations</dt>", html=True)
        self.assertNotContains(response, "<dt>Vocabulaire</dt>", html=True)
        self.assertNotContains(response, 'data-task-choice="vocabulary"')
        html = response.content.decode()
        self.assertLess(
            html.index('data-task-choice="subjects"'),
            html.index('data-task-choice="formulations"'),
        )

    def test_dashboard_rollup_combines_distinct_subjects_and_formulations(self):
        duplicate = factories.make_writing_sujet(
            task=self.task,
            slug="janvier-combinaison-2",
            category="education",
        )
        with patch(
            "study.views.helpers._canonical_writing_sujet_ids_by_task",
            return_value={
                self.task.pk: [
                    self.sujet.pk,
                    self.sujet.pk,
                    duplicate.pk,
                ],
            },
        ):
            summaries = expression_task_summaries(
                timezone.now(), self.user, [self.task],
            )
        summary = summaries[self.task.pk]
        self.assertEqual(summary["prompt_count"], 3)
        self.assertEqual(summary["subject_stats"]["total"], 2)
        self.assertEqual(
            summary["stats"]["total"],
            2 + len(self.catalog.entries),
        )
        card = _task_card(
            self.task,
            timezone.now(),
            self.user,
            summaries=summaries,
        )
        self.assertEqual(card["prompt_count"], 2)
        self.assertEqual(card["phrase_count"], 0)
        self.assertEqual(card["question_bank"]["subject_count"], 2)
        self.assertEqual(
            card["question_bank"]["question_count"],
            len(self.catalog.entries),
        )


class VocabularyRetirementTests(TestCase):
    def setUp(self):
        self.user = factories.make_user()
        self.task = factories.make_task(factories.make_part("ee"))
        self.theme = factories.make_theme("ee-tache-3-education", task=self.task)
        self.spine = factories.make_spine_card(user=self.user, theme=self.theme)
        self.prompt = self.spine.response.prompts.first()
        self.phrase = factories.make_phrase(tier=PhraseTier.SUBJECT)
        self.phrase.source_prompts.add(self.prompt)
        self.card = factories.make_phrase_card(
            user=self.user, phrase=self.phrase, state=CardState.REVIEW,
            due=timezone.now(), interval_days=17, needs_revisit=True,
        )
        self.other_task = factories.make_task(factories.make_part("eo"))
        self.other_theme = factories.make_theme("active-oral", task=self.other_task)
        self.other_response = factories.make_response(theme=self.other_theme)
        self.active_phrase = factories.make_phrase()
        self.active_phrase.source_prompts.add(self.other_response.prompts.first())
        self.active_card = factories.make_phrase_card(user=self.user, phrase=self.active_phrase)
        self.mocks = mock_catalog(formulation_catalog())
        self.addCleanup(self.mocks.close)
        self.client.force_login(self.user)

    def test_global_mixed_focused_and_task_queues_skip_legacy_without_mutation(self):
        ThemeVocabularyProgress.objects.create(user=self.user, phrase=self.phrase)
        before = Card.objects.filter(pk=self.card.pk).values().get()
        for scope in ({}, {"kind": "vocab"}, {"kind": "weak"}, {"kind": "revisit"},
                      {"part": "ee", "task": "tache-3"}):
            self.assertNotIn(self.card, queue.scoped_cards(scope, user=self.user))
        self.assertIn(self.active_card, queue.scoped_cards(user=self.user))
        self.assertIn(self.spine, queue.scoped_cards(user=self.user))
        self.assertEqual(before, Card.objects.filter(pk=self.card.pk).values().get())
        self.assertTrue(Phrase.objects.filter(pk=self.phrase.pk).exists())
        self.assertTrue(ThemeVocabularyProgress.objects.filter(phrase=self.phrase).exists())

    def test_shared_with_other_active_task_or_comprehension_is_not_retired(self):
        self.phrase.source_prompts.add(self.other_response.prompts.first())
        self.assertIn(self.card, queue.scoped_cards({"kind": "vocab"}, user=self.user))
        self.assertNotIn(self.card, queue.scoped_cards({"part": "ee", "task": "tache-3"}, user=self.user))
        self.phrase.source_prompts.remove(self.other_response.prompts.first())
        test = factories.make_comprehension_test()
        self.phrase.source_questions.add(test.questions.first())
        self.assertIn(self.phrase, active_phrases())
        self.assertIn(self.card, queue.scoped_cards({"kind": "vocab"}, user=self.user))

    def test_part_wide_ee_scope_requires_active_ee_ownership(self):
        self.phrase.tier = PhraseTier.SHARED
        self.phrase.save()
        self.phrase.source_prompts.add(
            self.other_response.prompts.first(),
        )
        self.assertNotIn(
            self.card,
            queue.scoped_cards({"part": "ee"}, user=self.user),
        )
        self.assertIn(
            self.card,
            queue.scoped_cards({"part": "eo"}, user=self.user),
        )

        ee2_task = factories.make_task(self.task.part, "tache-2")
        ee2_theme = factories.make_theme("active-ee2", task=ee2_task)
        ee2_response = factories.make_response(theme=ee2_theme)
        self.phrase.source_prompts.add(ee2_response.prompts.first())
        self.assertIn(
            self.card,
            queue.scoped_cards({"part": "ee"}, user=self.user),
        )

    def test_direct_theme_and_unrelated_ee_tasks(self):
        direct = factories.make_phrase(tier=PhraseTier.THEME, vocabulary_theme=self.theme)
        self.assertNotIn(direct, active_phrases())
        other = factories.make_task(self.task.part, "tache-2")
        active_theme = factories.make_theme("ee2-theme", task=other)
        direct.vocabulary_theme = active_theme
        direct.save()
        self.assertIn(direct, active_phrases())

    def test_ee1_only_is_retired_but_shared_active_ownership_survives(self):
        ee1_task = factories.make_task(self.task.part, "tache-1")
        ee1_theme = factories.make_theme(
            "ee-tache-1-education", task=ee1_task,
        )
        ee1_response = factories.make_response(theme=ee1_theme)
        phrase = factories.make_phrase(tier=PhraseTier.SUBJECT)
        phrase.source_prompts.add(ee1_response.prompts.first())
        card = factories.make_phrase_card(user=self.user, phrase=phrase)
        self.assertNotIn(phrase, active_phrases())
        self.assertNotIn(
            card,
            queue.scoped_cards({"kind": "vocab"}, user=self.user),
        )
        phrase.source_prompts.add(self.other_response.prompts.first())
        self.assertIn(phrase, active_phrases())
        self.assertIn(
            card,
            queue.scoped_cards({"kind": "vocab"}, user=self.user),
        )
        self.assertNotIn(
            card,
            queue.scoped_cards(
                {"part": "ee", "task": "tache-1"}, user=self.user,
            ),
        )

    def test_inferred_ee3_scopes_exclude_shared_phrases_in_one_query(self):
        self.phrase.tier = PhraseTier.SHARED
        self.phrase.save()
        self.phrase.source_prompts.add(self.other_response.prompts.first())
        scopes = (
            {"part": "ee", "task": "tache-3"},
            {"theme": self.theme.slug},
            {"theme": self.theme.slug, "kind": "revisit"},
            {"theme": self.theme.slug, "kind": "weak"},
            {"response": self.spine.response_id},
            {"response": self.spine.response_id, "kind": "revisit"},
            {"prompt": self.prompt.pk, "kind": "revisit"},
        )
        for scope in scopes:
            with self.subTest(scope=scope), self.assertNumQueries(1):
                ids = list(queue.scoped_cards(scope, user=self.user).values_list("pk", flat=True))
                self.assertNotIn(self.card.pk, ids)
        for scope in ({}, {"part": "eo", "task": "tache-3"},
                      {"theme": self.other_theme.slug},
                      {"response": self.other_response.pk}):
            with self.subTest(active_scope=scope):
                self.assertIn(self.card, queue.scoped_cards(scope, user=self.user))

    def test_stale_shared_cards_cannot_cross_ee3_review_boundaries(self):
        self.phrase.tier = PhraseTier.SHARED
        self.phrase.save()
        self.phrase.source_prompts.add(self.other_response.prompts.first())
        _, log = apply_review(self.card, Rating.GOOD, return_log=True)
        scopes = (
            {"part": "ee", "task": "tache-3"},
            {"theme": self.theme.slug, "kind": "revisit"},
            {"response": self.spine.response_id},
            {"prompt": self.prompt.pk, "kind": "revisit"},
        )
        for scope in scopes:
            session, _ = ReviewSession.objects.update_or_create(
                user=self.user, defaults={
                    "scope": scope, "current_card": self.card,
                    "previous_card": self.card, "previous_review": log,
                    "presentation_token": "old-shared-token",
                },
            )
            before_card = Card.objects.filter(pk=self.card.pk).values().get()
            before_session = ReviewSession.objects.filter(pk=session.pk).values().get()
            before_log = ReviewLog.objects.filter(pk=log.pk).values().get()
            with self.subTest(scope=scope):
                self.assertEqual(self.client.get(reverse("study:review_previous")).status_code, 404)
                self.assertEqual(self.client.post(reverse("study:review_answer"), {
                    "card_id": self.card.pk, "presentation_token": "old-shared-token",
                    "action": "correct",
                }).status_code, 404)
                self.assertEqual(self.client.post(reverse("study:review_undo")).status_code, 404)
                self.assertEqual(Card.objects.filter(pk=self.card.pk).values().get(), before_card)
                self.assertEqual(ReviewSession.objects.filter(pk=session.pk).values().get(), before_session)
                self.assertEqual(ReviewLog.objects.filter(pk=log.pk).values().get(), before_log)
                self.assertEqual(ReviewLog.objects.count(), 1)

    def test_completed_focused_review_still_allows_previous_and_undo(self):
        for kind in ("revisit", "weak"):
            self.active_card.refresh_from_db()
            self.active_card.state = CardState.REVIEW
            self.active_card.needs_revisit = True
            self.active_card.due = timezone.now() + timezone.timedelta(days=10)
            self.active_card.save()
            ReviewSession.objects.update_or_create(
                user=self.user, defaults={
                    "scope": {"part": "eo", "task": "tache-3", "kind": kind},
                    "current_card": self.active_card, "presentation_token": "active-token",
                },
            )
            with self.subTest(kind=kind):
                answer = self.client.post(reverse("study:review_answer"), {
                    "card_id": self.active_card.pk, "presentation_token": "active-token",
                    "action": "correct",
                })
                self.assertEqual(answer.status_code, 200)
                self.active_card.refresh_from_db()
                self.assertFalse(self.active_card.needs_revisit)
                self.assertEqual(self.client.get(reverse("study:review_previous")).status_code, 200)
                undone = self.client.post(reverse("study:review_undo"))
                self.assertEqual(undone.status_code, 200)
                self.assertTrue(undone.json()["undone"])
                self.active_card.refresh_from_db()
                self.assertTrue(self.active_card.needs_revisit)

    def test_removed_bookmarks_and_saved_scopes_return_404(self):
        for kind in ("phrase", "vocab", "theme_vocab"):
            url = reverse("study:task_review", args=["ee", "tache-3"])
            self.assertEqual(
                self.client.get(url, {"kind": kind}).status_code,
                404,
            )
        self.assertEqual(
            self.client.get(reverse("study:review"), {
                "kind": "vocab", "response": self.spine.response_id,
            }).status_code,
            404,
        )
        scope = {"part": "ee", "task": "tache-3", "kind": "vocab"}
        session, _ = ReviewSession.objects.update_or_create(
            user=self.user, defaults={
                "scope": scope, "current_card": self.card, "presentation_token": "old-token",
            },
        )
        self.assertEqual(
            self.client.get(reverse("study:review")).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("study:review_next")).status_code,
            404,
        )
        session.refresh_from_db()
        self.assertEqual(session.scope, scope)
        self.assertEqual(session.current_card_id, self.card.pk)

    def test_stale_mixed_review_post_cannot_grade_retired_card(self):
        ReviewSession.objects.create(
            user=self.user, scope={"kind": "phrase"},
            current_card=self.card, presentation_token="old-token",
            previous_card=self.card,
        )
        response = self.client.post(reverse("study:review_answer"), {
            "card_id": self.card.pk, "presentation_token": "old-token", "rating": "3",
        })
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(reverse("study:review_previous")).status_code, 404)
        self.card.refresh_from_db()
        self.assertEqual(self.card.interval_days, 17)
        self.assertFalse(self.card.reviews.exists())

    def test_subject_no_longer_offers_vocabulary_and_search_omits_retired_phrase(self):
        response = self.client.get(reverse("study:response_detail", args=["ee", "tache-3", self.prompt.pk]))
        self.assertContains(response, "Explorer les formulations")
        self.assertNotContains(response, "Vocabulaire de ce sujet")
        self.assertNotContains(response, "Pratiquer les vocabs")
        response = self.client.get(reverse("study:search"), {"q": self.phrase.expression})
        self.assertEqual(response.context["phrase_result_count"], 0)
