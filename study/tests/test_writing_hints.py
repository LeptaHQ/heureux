import copy
import json
import re
from collections import Counter
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from study import catalogue
from study import content_loader as content
from study.management.commands.import_content import Command
from study.models import (
    Annotation, AnnotationKind, PersonalWritingResponse, WritingResponseOverride,
    WritingSujet, WritingSujetCompletion,
)
from study.writing_responses import model_version_keys

from . import factories


class WritingHintsContentTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.categories = content.load_ee_writing_categories(1)
        cls.subjects = [
            subject for category in cls.categories
            if category.slug in content.EE_TACHE_ONE_HINT_THEMES
            for subject in category.sujets
        ]
        cls.payload = json.loads(content.EE_TACHE_ONE_SUBJECT_HINTS_PATH.read_text(encoding="utf-8"))

    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def load(self, payload):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "hints.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return content.load_ee_tache_one_subject_hints(path, categories=self.categories)

    def test_exactly_the_requested_themes_share_complete_bilingual_pistes(self):
        hints = content.load_ee_tache_one_subject_hints(categories=self.categories)
        self.assertEqual(len(hints), 89)
        self.assertEqual(set(hints), {subject.slug for subject in self.subjects})
        canonical = [subject for subject in self.subjects if subject.slug == subject.canonical_slug]
        self.assertEqual(Counter(subject.category for subject in canonical), {
            "invitations": 9, "sorties": 8, "accueil": 5, "voyages": 9, "ville": 3, "logement": 8,
        })
        self.assertEqual(len(set(hints.values())), 42)
        for subject in self.subjects:
            with self.subTest(subject=subject.slug):
                cues = hints[subject.slug]
                self.assertIs(cues, hints[subject.canonical_slug])
                self.assertTrue(5 <= len(cues) <= 8)
                self.assertLessEqual(sum(len(cue.french.split()) for cue in cues), 75)
                for cue in cues:
                    self.assertNotEqual(cue.french.casefold(), cue.english.casefold())
                    for text in (cue.french, cue.english):
                        self.assertTrue(0 < len(text) <= 110)
                        self.assertEqual(text, text.strip())
        for category in self.categories:
            if category.slug not in content.EE_TACHE_ONE_HINT_THEMES:
                self.assertTrue(all(subject.slug not in hints for subject in category.sujets))

    def test_instruction_reminders_do_not_assume_every_accounts_response_is_incomplete(self):
        hints = catalogue.ee_tache_one_subject_hints()
        for slug, topic in (("avril-combinaison-4", "accueil chez soi"), ("mai-combinaison-2", "voisins")):
            text = " ".join(cue.french for cue in hints[slug])
            self.assertIn(topic, text)
            self.assertIn("lorsque la consigne le demande", text)
            self.assertNotIn("absents de la réponse", text)
            self.assertNotIn("non précisé ici", text)

    def test_travel_pistes_use_the_refreshed_countryside_and_culture_examples(self):
        hints = catalogue.ee_tache_one_subject_hints()
        for language, expected, outdated in (
            ("french", ("mont Rainier", "famille", "nature", "animaux sauvages"),
             ("Kakum", "anniversaire", "sœur", "tropicale", "singes")),
            ("english", ("Mount Rainier", "family", "nature", "wild animals"),
             ("Kakum", "birthday", "sister", "rainforest", "monkeys")),
        ):
            text = " ".join(getattr(cue, language) for cue in hints["mars-combinaison-7"])
            for phrase in expected:
                self.assertIn(phrase, text)
            for phrase in outdated:
                self.assertNotIn(phrase, text)
        for language, expected, outdated in (
            ("french", ("Makola", "Manhyia", "kente", "jollof", "waakye", "hospitalité", "danse"),
             ("Indépendance", "août", "arrivée")),
            ("english", ("Makola", "Manhyia", "kente", "jollof", "waakye", "hospitality", "dance"),
             ("Independence", "August", "arrives")),
        ):
            text = " ".join(getattr(cue, language) for cue in hints["septembre-combinaison-7"])
            for phrase in expected:
                self.assertIn(phrase, text)
            for phrase in outdated:
                self.assertNotIn(phrase, text)

    def test_missing_extra_and_alias_keys_cannot_hide_coverage_errors(self):
        for change in ("missing", "unrequested", "alias"):
            invalid = copy.deepcopy(self.payload)
            first = next(iter(invalid["groups"]))
            if change == "missing":
                invalid["groups"].pop(first)
            else:
                extra = (
                    "ee-tache1:janvier:combinaison-1" if change == "unrequested"
                    else "ee-tache1:mars:combinaison-12"
                )
                invalid["groups"][extra] = invalid["groups"][first]
            with self.subTest(change=change), self.assertRaisesMessage(ValueError, "group coverage"):
                self.load(invalid)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "hints.json"
            with self.assertRaises(FileNotFoundError):
                content.load_ee_tache_one_subject_hints(path, categories=self.categories)
            path.write_text('{"groups":{"duplicate":[],"duplicate":[]}}', encoding="utf-8")
            with self.assertRaisesMessage(ValueError, "Duplicate field"):
                content.load_ee_tache_one_subject_hints(path, categories=self.categories)

    def test_housing_pistes_cover_distinct_plans_without_private_contact_details(self):
        hints = catalogue.ee_tache_one_subject_hints()
        expected_topics = {
            "mars-combinaison-9": ("redécorer", "peindre", "camion"),
            "avril-combinaison-1": ("propriétaire", "charges", "visite"),
            "juillet-combinaison-4": ("agence", "Nice", "étudiant", "salle de bain privée"),
            "aout-combinaison-13": ("travail", "camion", "disponibilité"),
            "aout-combinaison-14": ("colocataire", "intimité", "non-fumeuse", "contact"),
            "aout-combinaison-17": ("Montréal", "annonces", "remercier"),
            "aout-combinaison-18": ("trouvé", "studio", "dîner"),
            "novembre-combinaison-12": ("déjà accepté", "Répartir", "Trajet", "déchargement"),
        }
        for slug, topics in expected_topics.items():
            with self.subTest(slug=slug):
                french = " ".join(cue.french for cue in hints[slug])
                bilingual = " ".join(f"{cue.french} {cue.english}" for cue in hints[slug])
                for topic in topics:
                    self.assertIn(topic, french)
                self.assertNotRegex(bilingual, r"@|https?://|\b(?:\d[- .]?){8,}\d\b")
                self.assertNotRegex(bilingual, r"\b\d+\s*,?\s+(?:rue|avenue)\b")

    def test_metadata_shape_count_and_bilingual_text_are_strict(self):
        for key, value in (("task", "ee/tache-2"), ("version", True), ("version", 2), ("groups", [])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.load({**self.payload, key: value})
        for rows in ([], [None] * 5, [{"french": "Sans traduction"}] * 5, "Not a list"):
            invalid = copy.deepcopy(self.payload)
            invalid["groups"][next(iter(invalid["groups"]))] = rows
            with self.assertRaises(ValueError):
                self.load(invalid)
        for size in (4, 9):
            invalid = copy.deepcopy(self.payload)
            first = next(iter(invalid["groups"]))
            invalid["groups"][first] = [invalid["groups"][first][0]] * size
            with self.assertRaises(ValueError):
                self.load(invalid)
        for language in ("french", "english"):
            for text in (None, 7, "", " ", " Padded ", "x" * 111, "Two\nlines", "A question ?"):
                invalid = copy.deepcopy(self.payload)
                next(iter(invalid["groups"].values()))[0][language] = text
                with self.subTest(language=language, text=text), self.assertRaises(ValueError):
                    self.load(invalid)
            invalid = copy.deepcopy(self.payload)
            rows = next(iter(invalid["groups"].values()))
            rows[1][language] = rows[0][language].upper()
            with self.assertRaisesMessage(ValueError, "Duplicate"):
                self.load(invalid)

    def test_overlong_lists_and_incomplete_sources_are_rejected(self):
        invalid = copy.deepcopy(self.payload)
        for index, row in enumerate(next(iter(invalid["groups"].values()))):
            row["french"] = " ".join(["un"] * 20 + [str(index)])
        with self.assertRaisesMessage(ValueError, "75 French words"):
            self.load(invalid)
        for categories in (
            (), self.categories[1:],
            tuple(category for category in self.categories if category.slug != "logement"),
        ):
            with self.assertRaisesMessage(ValueError, "source themes"):
                content.load_ee_tache_one_subject_hints(categories=categories)
        invalid_categories = list(self.categories)
        category = invalid_categories[0]
        invalid_categories[0] = replace(category, sujets=(
            replace(category.sujets[0], canonical_slug="missing-source"), *category.sujets[1:],
        ))
        with self.assertRaisesMessage(ValueError, "source publications"):
            content.load_ee_tache_one_subject_hints(categories=tuple(invalid_categories))

    def test_cache_reuses_frozen_cues_and_does_not_cache_failures(self):
        with patch.object(content, "load_ee_tache_one_subject_hints", wraps=content.load_ee_tache_one_subject_hints) as loader:
            hints = catalogue.ee_tache_one_subject_hints()
            self.assertIs(catalogue.ee_tache_one_subject_hints(), hints)
            loader.assert_called_once_with(categories=catalogue.ee_writing_categories(1))
            key = next(iter(hints))
            with self.assertRaises(TypeError):
                hints[key] = ()
            with self.assertRaises(FrozenInstanceError):
                hints[key][0].french = "Changed"
            catalogue.clear_catalogue_cache()
            self.assertEqual(catalogue.ee_tache_one_subject_hints(), hints)
            self.assertEqual(loader.call_count, 2)
        catalogue.clear_catalogue_cache()
        with patch.object(content, "load_ee_tache_one_subject_hints", side_effect=ValueError("Invalid pistes")) as loader:
            for _ in range(2):
                with self.assertRaisesMessage(ValueError, "Invalid pistes"):
                    catalogue.ee_tache_one_subject_hints()
            self.assertEqual(loader.call_count, 2)


class WritingHintsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.task = factories.make_task(factories.make_part("ee"), "tache-1")
        Command()._import_writing_sujets(content.load_ee_writing_categories(1), {"ee/tache-1": cls.task})
        cls.user = factories.make_user("writing-pistes")

    def setUp(self):
        self.client.force_login(self.user)

    def url(self, sujet):
        return reverse("study:writing_sujet_detail", args=["ee", sujet.task.slug, sujet.pk])

    def test_every_selected_publication_renders_shared_pistes(self):
        hints = catalogue.ee_tache_one_subject_hints()
        sujets = WritingSujet.objects.filter(task=self.task, slug__in=hints).select_related("task")
        self.assertEqual(sujets.count(), 89)
        for sujet in sujets:
            with self.subTest(sujet=sujet.slug):
                page = self.client.get(self.url(sujet))
                self.assertEqual(page.status_code, 200)
                self.assertIs(page.context["subject_hints"], hints[sujet.slug])
                self.assertContains(page, 'lang="fr">Pistes</h2>')
                self.assertContains(page, "Voir les pistes")
                self.assertContains(page, 'class="subject-hints__french"', count=len(hints[sujet.slug]))
                self.assertContains(page, 'class="subject-hints__english"', count=len(hints[sujet.slug]))
                self.assertNotContains(page, ">Hints<")
                self.assertLess(
                    page.content.index(b"response-sidebar-card--status"),
                    page.content.index(b'id="subject-hints-title"'),
                )
                self.assertNotContains(page, "<dt>Position</dt>")
                self.assertNotContains(page, "<dt>Réponses modèles</dt>")
                self.assertNotContains(page, "subject-progress-control__help")

    def test_personal_answers_edits_deletions_and_annotations_remain_private_and_unchanged(self):
        canonical = WritingSujet.objects.get(task=self.task, slug="janvier-combinaison-2")
        alias = WritingSujet.objects.get(task=self.task, slug="mars-combinaison-12")
        personal = PersonalWritingResponse.objects.create(
            user=self.user, sujet=canonical, body="Bonjour, voici mon message personnel à conserver.",
        )
        WritingSujetCompletion.objects.create(user=self.user, sujet=canonical)
        key = model_version_keys(canonical.model_versions)[0]
        WritingResponseOverride.objects.create(user=self.user, sujet=canonical, version_key=key, is_deleted=True)
        Annotation.objects.create(
            user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
            source_path=self.url(alias), source_key=f"writing-sujet:{canonical.pk}:personal",
            quote="mon message personnel", start_offset=15, end_offset=35,
        )
        tracked = (WritingSujet, PersonalWritingResponse, WritingResponseOverride, WritingSujetCompletion, Annotation)
        before = {model: list(model.objects.order_by("pk").values()) for model in tracked}
        expected = catalogue.ee_tache_one_subject_hints()[canonical.slug]
        for sujet in (canonical, alias):
            for query in ({}, {"deduplicate": "0"}):
                page = self.client.get(self.url(sujet), query)
                self.assertIs(page.context["subject_hints"], expected)
                self.assertTrue(page.context["explicitly_completed"])
                self.assertContains(page, personal.body)
                self.assertEqual(page.context["response_copy_texts"], {"personal": personal.body})
                self.assertNotContains(page, "data-writing-response-delete")
        self.assertEqual(before, {model: list(model.objects.order_by("pk").values()) for model in tracked})
        other = factories.make_user("other-writing-pistes")
        WritingResponseOverride.objects.create(user=other, sujet=canonical, version_key=key, body="Mon modèle modifié.")
        self.client.force_login(other)
        page = self.client.get(self.url(alias))
        self.assertIs(page.context["subject_hints"], expected)
        self.assertContains(page, "Mon modèle modifié.")
        self.assertNotContains(page, personal.body)
        self.assertFalse(page.context["explicitly_completed"])

    def test_all_response_roots_and_controls_keep_the_same_markup(self):
        sujet = WritingSujet.objects.get(task=self.task, slug="janvier-combinaison-8")
        page = self.client.get(self.url(sujet))
        with patch("study.views.library.catalogue.ee_tache_one_subject_hints", return_value={sujet.slug: ()}):
            baseline = self.client.get(self.url(sujet))
        roots = re.compile(
            r'<div\s+class="t1-response__body"\s+data-annotation-root\s+data-annotation-source-key="([^"]+)">(.*?)</div>',
            re.S,
        )
        annotated = roots.findall(page.content.decode())
        self.assertTrue(annotated)
        self.assertEqual(annotated, roots.findall(baseline.content.decode()))
        self.assertTrue(all("subject-hints" not in markup for _, markup in annotated))
        self.assertEqual(page.context["response_copy_texts"], baseline.context["response_copy_texts"])
        for control in ("data-writing-response-edit", "data-writing-response-delete", "data-response-copy"):
            self.assertEqual(page.content.count(control.encode()), baseline.content.count(control.encode()))

    def test_housing_equivalents_preserve_personal_answers_and_overrides(self):
        canonical = WritingSujet.objects.get(task=self.task, slug="aout-combinaison-14")
        personal = PersonalWritingResponse.objects.create(
            user=self.user, sujet=canonical, body="Ma recherche personnelle de colocataire.",
        )
        WritingResponseOverride.objects.create(
            user=self.user, sujet=canonical,
            version_key=model_version_keys(canonical.model_versions)[0],
            body="Mon modèle modifié reste inchangé.",
        )
        tracked = (WritingSujet, PersonalWritingResponse, WritingResponseOverride)
        before = {model: list(model.objects.order_by("pk").values()) for model in tracked}
        expected = catalogue.ee_tache_one_subject_hints()[canonical.slug]
        for slug in ("aout-combinaison-14", "aout-combinaison-16", "novembre-combinaison-11"):
            sujet = WritingSujet.objects.get(task=self.task, slug=slug)
            with self.subTest(slug=slug):
                page = self.client.get(self.url(sujet))
                self.assertEqual(page.status_code, 200)
                self.assertIs(page.context["subject_hints"], expected)
                self.assertEqual(page.context["response_copy_texts"]["personal"], personal.body)
                self.assertIn("Mon modèle modifié reste inchangé.", page.context["response_copy_texts"].values())
        self.assertEqual(before, {model: list(model.objects.order_by("pk").values()) for model in tracked})

    def test_unrequested_themes_custom_sujets_and_ee2_keep_their_existing_page(self):
        transport = WritingSujet.objects.filter(task=self.task, category="transport").first()
        custom = factories.make_writing_sujet(self.task, slug="adhoc-pistes")
        ee2 = factories.make_task(self.task.part, "tache-2")
        source = content.load_ee_writing_categories(2)[0].sujets[0]
        writing = factories.make_writing_sujet(
            ee2, slug=source.slug, category=source.category, prompt=source.prompt,
        )
        with patch("study.views.library.catalogue.ee_tache_one_subject_hints", side_effect=AssertionError("Unrequested pistes")):
            for sujet in (transport, custom, writing):
                page = self.client.get(self.url(sujet))
                self.assertEqual(page.status_code, 200)
                self.assertNotContains(page, "subject-hints--writing")
                self.assertNotContains(page, "<dt>Position</dt>")
                self.assertNotContains(page, "<dt>Réponses modèles</dt>")
                self.assertNotContains(page, "subject-progress-control__help")

    def test_warm_requests_do_not_reread_sources_or_add_database_queries(self):
        sujet = WritingSujet.objects.get(task=self.task, slug="janvier-combinaison-2")
        url = self.url(sujet)
        self.client.get(url)
        with patch.object(content, "load_ee_tache_one_subject_hints", side_effect=AssertionError("Uncached hints")):
            with patch.object(content, "load_ee_writing_categories", side_effect=AssertionError("Uncached responses")):
                with CaptureQueriesContext(connection) as with_hints:
                    page = self.client.get(url)
                with patch("study.views.library.catalogue.ee_tache_one_subject_hints", return_value={sujet.slug: ()}):
                    with CaptureQueriesContext(connection) as without_hints:
                        self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(with_hints), len(without_hints))
