from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path

from django.test import SimpleTestCase

from study.content_loader import (
    EE_TACHE_THREE_MEMOIRES_DIR,
    load_ee_subject_themes,
    load_ee_tache_three_author_responses,
    parse_ee_tache_three_responses,
)
from study.ee_formulations import (
    CONTENT_KEY_PREFIX,
    FUNCTION_CATEGORIES,
    load_ee_formulations,
)
from study.ee_formulation_language import REPORTING_LANGUAGE, THEME_LANGUAGE

EXPECTED_THEME_COUNTS = {
    "education": 8,
    "sante-alimentation": 12,
    "environnement": 5,
    "travail": 12,
    "numerique": 10,
    "societe": 6,
    "transports": 2,
    "logement": 5,
    "culture-loisirs": 7,
    "consommation": 10,
    "voyages": 1,
}
LEGACY_MEMOIRE_SHA256 = {
    1: "cda55a4d8208e08f9a9cb2fa6560db61c91aff47025c0c640848abc1c2a429e1",
    2: "86708ac81671de5497706ad8c70b4256c699e297ce3b646ac0ccb82872d9ba6d",
    3: "d9b9eefd4abf37d7bd427d3844df7ba0bea6e257dfa9e956b908b48b807106a7",
    4: "29517ef76100cd1e05cc9a18ef43d9b934e67df0b581ce91c6e6e3ac6c752aa5",
}


class EeFormulationsContentTests(SimpleTestCase):
    """Structural/provenance safeguards; teaching semantics need editorial review."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.catalog = load_ee_formulations()
        cls.responses = {
            response.content_key: response
            for response in parse_ee_tache_three_responses()
        }
        cls.themes, cls.theme_by_key = load_ee_subject_themes(3)

    def test_curated_size_and_order(self):
        self.assertEqual(self.catalog.entry_count, 152)
        self.assertEqual(self.catalog.category_count, 21)
        self.assertEqual(self.catalog.source_response_count, 78)
        self.assertEqual(
            [category.slug for category in self.catalog.categories],
            [*FUNCTION_CATEGORIES, *(theme.slug for theme in self.themes)],
        )
        self.assertTrue(all(
            category.kind == "function"
            for category in self.catalog.categories[:len(FUNCTION_CATEGORIES)]
        ))
        self.assertTrue(all(
            category.kind == "theme"
            for category in self.catalog.categories[len(FUNCTION_CATEGORIES):]
        ))

    def test_all_effective_answers_ground_entries_not_all_raw_variants(self):
        sources = {entry.source_key for entry in self.catalog.entries}
        self.assertEqual(sources, set(self.responses))
        self.assertEqual(len(sources), 78)
        self.assertEqual(
            Counter(self.theme_by_key[source] for source in sources),
            EXPECTED_THEME_COUNTS,
        )
        self.assertNotIn("ee-tache3:mars:combinaison-8", sources)
        self.assertIn("ee-tache3:janvier:combinaison-19", sources)

    def test_every_author_override_is_used(self):
        authors = load_ee_tache_three_author_responses()
        self.assertEqual(len(authors), 10)
        self.assertLessEqual(
            set(authors), {entry.source_key for entry in self.catalog.entries}
        )

    def test_quotations_are_verbatim_effective_evidence(self):
        normalize = lambda text: " ".join(text.split())
        for entry in self.catalog.entries:
            response = self.responses[entry.source_key]
            evidence = [response.reformulation, response.position, response.position_claire]
            with self.subTest(slug=entry.slug):
                self.assertTrue(any(
                    normalize(entry.example) in normalize(text) for text in evidence
                ))
                # Titles are complete titles; other examples are substantial excerpts.
                if normalize(entry.example) != normalize(response.reformulation):
                    self.assertGreaterEqual(len(entry.example.split()), 8)
                    self.assertTrue(entry.example.endswith((".", "!", "?")))

    def test_essentials_cover_the_function_pipeline(self):
        essential = [entry for entry in self.catalog.entries if entry.essential]
        self.assertEqual(len(essential), 16)
        self.assertEqual({entry.category for entry in essential}, set(FUNCTION_CATEGORIES))
        self.assertEqual([entry.slug for entry in essential], [
            "titre-enjeu-equilibre",
            "synthese-theme-commun",
            "synthese-premier-argument",
            "synthese-complement",
            "avis-position-claire",
            "avis-favorable-condition",
            "opposition-reelle",
            "concession-bien-que",
            "condition-subjonctif",
            "argument-premiere-raison",
            "argument-deuxieme-raison",
            "argument-mecanisme-car",
            "exemple-acteur-action",
            "exemple-hypothetique",
            "consequence-ainsi",
            "conclusion-position-condition",
        ])

    def test_all_teaching_fields_and_transfer_tasks_are_present(self):
        for entry in self.catalog.entries:
            with self.subTest(slug=entry.slug):
                for field in ("label", "french", "english", "usage", "grammar",
                              "example", "example_english", "transfer_prompt"):
                    self.assertTrue(getattr(entry, field).strip())
                self.assertNotEqual(entry.example, entry.example_english)
                self.assertNotEqual(entry.french, entry.english)
                self.assertNotEqual(
                    entry.transfer_prompt, self.responses[entry.source_key].prompt
                )
                self.assertNotIn("...", entry.french)
                self.assertNotIn("\u2026", entry.french)
                for slot in re.findall(r"\[([^\]]+)\]", entry.french):
                    self.assertTrue(any(character.isalpha() for character in slot))

    def test_theme_categories_have_substantial_varied_banks(self):
        counts = Counter(entry.category for entry in self.catalog.entries)
        self.assertEqual(
            {theme.slug: counts[theme.slug] for theme in self.themes},
            {
                "education": 10, "sante-alimentation": 16, "environnement": 7,
                "travail": 16, "numerique": 13, "societe": 7, "transports": 4,
                "logement": 7, "culture-loisirs": 9, "consommation": 13, "voyages": 3,
            },
        )
        for theme in self.themes:
            for entry in self.catalog.entries:
                if entry.category == theme.slug:
                    self.assertIn(theme.slug, entry.themes)
                    self.assertIn(self.theme_by_key[entry.source_key], entry.themes)

    def test_function_and_theme_language_references_are_complete(self):
        self.assertEqual(len(REPORTING_LANGUAGE), 10)
        self.assertEqual(set(THEME_LANGUAGE), set(EXPECTED_THEME_COUNTS))
        self.assertTrue(all(len(items) == 8 for items in THEME_LANGUAGE.values()))
        education = {item.french for item in THEME_LANGUAGE["education"]}
        self.assertIn("la mixité sociale", education)
        self.assertIn("les classes socialement homogènes", education)
        for slug, items in THEME_LANGUAGE.items():
            with self.subTest(theme=slug):
                self.assertEqual(
                    len({item.french.casefold() for item in items}), len(items),
                )
                self.assertTrue(all(
                    item.french.strip()
                    and item.english.strip()
                    and item.pattern.strip()
                    for item in items
                ))

    def test_source_defects_have_explicit_provenance(self):
        by_slug = {entry.slug: entry for entry in self.catalog.entries}
        self.assertEqual(
            by_slug["synthese-document-absent"].source_key,
            "ee-tache3:juin:combinaison-2",
        )
        self.assertEqual(
            by_slug["synthese-doublon-source"].source_key,
            "ee-tache3:mai:combinaison-3-bis",
        )
        self.assertEqual(
            by_slug["synthese-texte-hors-sujet"].source_key,
            "ee-tache3:decembre:combinaison-10",
        )
        self.assertEqual(
            by_slug["societe-urgence-passerelle"].source_key,
            "ee-tache3:juin:combinaison-3",
        )

    def test_icons_exist_in_the_shared_sprite(self):
        sprite = (
            Path(__file__).resolve().parents[1]
            / "static" / "study" / "icons" / "ui-icons.svg"
        ).read_text(encoding="utf-8")
        icons = set(re.findall(r'id="icon-([a-z0-9-]+)"', sprite))
        for category in self.catalog.categories:
            self.assertIn(category.icon, icons)

    def test_new_keys_are_unique_and_fit_existing_progress_field(self):
        keys = [entry.content_key for entry in self.catalog.entries]
        self.assertEqual(len(keys), len(set(keys)))
        for key in keys:
            self.assertTrue(key.startswith(CONTENT_KEY_PREFIX))
            self.assertLessEqual(len(key), 96)
            self.assertNotIn("memoire", key)

    def test_historical_memoires_remain_byte_for_byte(self):
        for number, digest in LEGACY_MEMOIRE_SHA256.items():
            with self.subTest(memory=number):
                content = (
                    EE_TACHE_THREE_MEMOIRES_DIR / f"memoire_{number}.json"
                ).read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(), digest)
