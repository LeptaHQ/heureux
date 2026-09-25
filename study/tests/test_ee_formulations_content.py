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
from study.ee_formulation_language import (
    REPORTING_LANGUAGE,
    THEME_LANGUAGE,
    THEME_LANGUAGE_ROLES,
)

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
EXPECTED_LANGUAGE_ITEM_COUNTS = {
    "education": 26,
    "sante-alimentation": 26,
    "environnement": 26,
    "travail": 26,
    "numerique": 27,
    "societe": 25,
    "transports": 24,
    "logement": 27,
    "culture-loisirs": 26,
    "consommation": 25,
    "voyages": 26,
}
EXPECTED_LANGUAGE_EXAMPLE_COUNTS = {
    "education": 31,
    "sante-alimentation": 39,
    "environnement": 31,
    "travail": 32,
    "numerique": 34,
    "societe": 31,
    "transports": 28,
    "logement": 37,
    "culture-loisirs": 34,
    "consommation": 36,
    "voyages": 31,
}
MINIMUM_LANGUAGE_ROLE_COUNTS = {
    "notion": 4,
    "collocation": 4,
    "benefit": 4,
    "risk": 4,
    "condition": 4,
    "solution": 2,
    "mechanism": 2,
}
EXPECTED_PRODUCTION_PRIORITIES = {
    "education": {
        "préserver le lien humain",
        "réduire la comparaison des marques",
    },
    "sante-alimentation": {
        "des informations nutritionnelles claires",
        "soutenir les producteurs locaux",
    },
    "environnement": {
        "le plastique à usage unique",
        "la responsabilité des producteurs",
    },
    "travail": {
        "maintenir la qualité du service",
        "discuter de la charge de travail",
    },
    "numerique": {
        "protéger le sommeil",
        "un consentement éclairé",
        "protéger la vie privée",
    },
    "societe": {
        "un accompagnement à long terme",
        "retrouver son autonomie",
    },
    "transports": set(),
    "logement": {
        "partager les dépenses",
        "un calendrier de ménage",
        "le respect de l’intimité",
    },
    "culture-loisirs": {
        "nourrir la curiosité",
        "des espaces autorisés",
        "réduire les inégalités d’accès à la culture",
    },
    "consommation": {"faire une vraie pause"},
    "voyages": {
        "un tarif transparent",
        "le coût total",
        "l’empreinte carbone",
    },
}
CROSS_THEME_LANGUAGE_PROVENANCE = {
    (
        "voyages",
        "l’empreinte carbone",
        "Comparer l’avion et le train exige de considérer l’empreinte carbone en plus du prix.",
    ): {("ee-tache3:mai:combinaison-5", "position")},
}
# Key exceptions by (theme, headword, complete example) only when natural
# French requires an inflected surface form.
JUSTIFIED_LANGUAGE_INFLECTIONS = {}
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
        self.assertEqual(
            {
                slug: len(items)
                for slug, items in THEME_LANGUAGE.items()
            },
            EXPECTED_LANGUAGE_ITEM_COUNTS,
        )
        self.assertGreater(len(set(EXPECTED_LANGUAGE_ITEM_COUNTS.values())), 1)
        self.assertEqual(
            {
                slug: sum(len(item.examples) for item in items)
                for slug, items in THEME_LANGUAGE.items()
            },
            EXPECTED_LANGUAGE_EXAMPLE_COUNTS,
        )
        self.assertTrue(all(
            len(items) > 18
            for items in THEME_LANGUAGE.values()
        ))
        self.assertTrue(all(
            any(len(item.examples) > 1 for item in items)
            for items in THEME_LANGUAGE.values()
        ))
        education = {item.french for item in THEME_LANGUAGE["education"]}
        self.assertIn("la mixité sociale", education)
        self.assertIn("les classes socialement homogènes", education)
        self.assertIn("développer l’autonomie", education)
        all_french = [item.french.casefold() for item in REPORTING_LANGUAGE]
        all_examples = [
            example.text.casefold()
            for item in REPORTING_LANGUAGE
            for example in item.examples
        ]
        for slug, items in THEME_LANGUAGE.items():
            with self.subTest(theme=slug):
                self.assertEqual(
                    tuple(dict.fromkeys(item.role for item in items)),
                    tuple(dict.fromkeys(THEME_LANGUAGE_ROLES)),
                )
                role_counts = Counter(item.role for item in items)
                for role, minimum in MINIMUM_LANGUAGE_ROLE_COUNTS.items():
                    self.assertGreaterEqual(role_counts[role], minimum)
                self.assertEqual(
                    len({item.french.casefold() for item in items}), len(items),
                )
                self.assertLessEqual(
                    EXPECTED_PRODUCTION_PRIORITIES[slug],
                    {item.french for item in items},
                )
                self.assertTrue(all(
                    item.french.strip()
                    and item.english.strip()
                    and item.examples
                    for item in items
                ))
                all_french.extend(item.french.casefold() for item in items)
                all_examples.extend(
                    example.text.casefold()
                    for item in items
                    for example in item.examples
                )
        self.assertEqual(len(all_french), len(set(all_french)))
        self.assertEqual(len(all_examples), len(set(all_examples)))

    def test_language_examples_are_complete_sentences_using_the_headword(self):
        banks = {"reporting": REPORTING_LANGUAGE, **THEME_LANGUAGE}
        for slug, items in banks.items():
            for item in items:
                self.assertEqual(
                    item.pattern,
                    " ".join(example.text for example in item.examples),
                )
                for language_example in item.examples:
                    with self.subTest(
                        theme=slug,
                        french=item.french,
                        example=language_example.text,
                    ):
                        example = " ".join(language_example.text.split())
                        self.assertGreaterEqual(len(example.split()), 6)
                        self.assertTrue(example[0].isupper())
                        self.assertTrue(example.endswith((".", "!", "?")))
                        self.assertNotIn("...", example)
                        self.assertNotIn("\u2026", example)
                        inflection = JUSTIFIED_LANGUAGE_INFLECTIONS.get(
                            (slug, item.french, language_example.text),
                            item.french,
                        )
                        self.assertIn(
                            " ".join(inflection.split()).casefold(),
                            example.casefold(),
                        )

        declared = {
            (slug, item.french, example.text)
            for slug, items in banks.items()
            for item in items
            for example in item.examples
        }
        self.assertLessEqual(set(JUSTIFIED_LANGUAGE_INFLECTIONS), declared)

    def test_theme_language_is_grounded_in_both_response_parts(self):
        authors = load_ee_tache_three_author_responses()
        provenance_sources = set()
        used_cross_theme_provenance = set()
        self.assertEqual(len(self.responses), 78)
        for response in self.responses.values():
            self.assertTrue(response.reformulation.strip())
            self.assertTrue(response.position.strip())
            self.assertTrue(response.position_claire.strip())

        for item in REPORTING_LANGUAGE:
            with self.subTest(theme="reporting", french=item.french):
                self.assertEqual(item.role, "reporting")
                for example in item.examples:
                    self.assertTrue(example.provenance)
                    self.assertEqual(
                        len(example.provenance),
                        len(set(example.provenance)),
                    )
                    for source_key, field in example.provenance:
                        self.assertIn(source_key, self.responses)
                        self.assertIn(
                            field,
                            {"reformulation", "position", "position_claire"},
                        )
                        self.assertTrue(
                            getattr(self.responses[source_key], field).strip()
                        )

        for slug, items in THEME_LANGUAGE.items():
            parts = set()
            for item in items:
                with self.subTest(theme=slug, french=item.french):
                    expected_item_provenance = tuple(dict.fromkeys(
                        pair
                        for example in item.examples
                        for pair in example.provenance
                    ))
                    self.assertEqual(
                        item.provenance,
                        expected_item_provenance,
                    )
                    for example in item.examples:
                        self.assertTrue(example.provenance)
                        self.assertEqual(
                            len(example.provenance),
                            len(set(example.provenance)),
                        )
                        for source_key, field in example.provenance:
                            self.assertIn(source_key, self.responses)
                            if self.theme_by_key[source_key] != slug:
                                exception_key = (
                                    slug,
                                    item.french,
                                    example.text,
                                )
                                self.assertIn(
                                    (source_key, field),
                                    CROSS_THEME_LANGUAGE_PROVENANCE.get(
                                        exception_key,
                                        set(),
                                    ),
                                )
                                used_cross_theme_provenance.add(
                                    (exception_key, (source_key, field))
                                )
                            self.assertIn(
                                field,
                                {"reformulation", "position", "position_claire"},
                            )
                            self.assertTrue(
                                getattr(self.responses[source_key], field).strip()
                            )
                            provenance_sources.add(source_key)
                            parts.add(field)
            self.assertEqual(
                parts,
                {"reformulation", "position", "position_claire"},
            )
        self.assertEqual(provenance_sources, set(self.responses))
        self.assertLessEqual(set(authors), provenance_sources)
        self.assertEqual(
            used_cross_theme_provenance,
            {
                (exception_key, pair)
                for exception_key, pairs in CROSS_THEME_LANGUAGE_PROVENANCE.items()
                for pair in pairs
            },
        )

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
