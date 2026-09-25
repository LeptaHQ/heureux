from __future__ import annotations

import json
import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from study.ee_formulations import (
    FUNCTION_CATEGORIES,
    get_ee_formulations,
    load_ee_formulations,
)


class EeFormulationsLoaderTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "formulations.json"
        self.source_key = "ee-tache3:test:combinaison-1"
        self.response = SimpleNamespace(
            content_key=self.source_key,
            reformulation="Un titre",
            position="Les documents se complètent.",
            position_claire="Une mesure peut aider. Il faut la financer.",
        )
        self.categories = [*FUNCTION_CATEGORIES, "education"]
        self.payload = {
            "version": 1,
            "source_response_count": 1,
            "categories": [
                {
                    "slug": slug,
                    "kind": "theme" if slug == "education" else "function",
                    "title": slug,
                    "description": "Choose a suitable pattern.",
                    "icon": "book-open",
                }
                for slug in self.categories
            ],
            "entries": [
                {
                    "slug": f"frame-{slug}",
                    "category": slug,
                    "label": "Develop an argument",
                    "french": f"{slug} : [mesure] peut aider.",
                    "english": "A measure can help.",
                    "usage": "State a possible benefit, not a certainty.",
                    "grammar": "Follow peut with an infinitive.",
                    "example": "Une mesure peut aider.",
                    "example_english": "A measure can help.",
                    "source_key": self.source_key,
                    "transfer_prompt": "Suggest a benefit of free evening classes.",
                    "essential": slug != "education",
                    "themes": ["education"] if slug == "education" else [],
                }
                for slug in self.categories
            ],
        }
        for target, value in (
            ("parse_ee_tache_three_responses", [self.response]),
            (
                "load_ee_subject_themes",
                ([SimpleNamespace(slug="education")], {self.source_key: "education"}),
            ),
        ):
            mock = patch(f"study.ee_formulations.{target}", return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        get_ee_formulations.cache_clear()
        self.addCleanup(get_ee_formulations.cache_clear)

    def load(self):
        self.path.write_text(json.dumps(self.payload), encoding="utf-8")
        return load_ee_formulations(self.path)

    def test_contract_is_immutable_and_keys_are_separate(self):
        catalog = self.load()
        self.assertIsInstance(catalog.categories, tuple)
        self.assertIsInstance(catalog.entries, tuple)
        self.assertEqual(catalog.category_count, 11)
        self.assertEqual(catalog.entry_count, 11)
        self.assertEqual(catalog.source_response_count, 1)
        entry = catalog.entries[0]
        self.assertEqual(entry.content_key, "formulation:ee3:v1:frame-titres")
        self.assertIsInstance(entry.themes, tuple)
        for value, field in ((catalog, "entries"), (entry, "french"),
                             (catalog.categories[0], "title")):
            with self.assertRaises(FrozenInstanceError):
                setattr(value, field, ())

    def test_direct_loading_is_uncached_and_getter_is_cached(self):
        first = self.load()
        self.payload["entries"][0]["label"] = "Changed"
        self.assertNotEqual(first.entries[0].label, self.load().entries[0].label)
        with patch("study.ee_formulations.load_ee_formulations", return_value=first) as load:
            self.assertIs(get_ee_formulations(), get_ee_formulations())
            load.assert_called_once_with()
            get_ee_formulations.cache_clear()
            get_ee_formulations()
            self.assertEqual(load.call_count, 2)

    def test_bad_top_level_types_and_versions(self):
        for field, values in (
            ("version", [True, "1", 2, None]),
            ("source_response_count", [True, "1", 2, None]),
            ("categories", [{}, None, []]),
            ("entries", ["entries", None, []]),
        ):
            original = self.payload[field]
            for value in values:
                with self.subTest(field=field, value=value):
                    self.payload[field] = value
                    with self.assertRaises(ValueError):
                        self.load()
            self.payload[field] = original

    def test_invalid_entry_fields_are_rejected(self):
        entry = self.payload["entries"][0]
        cases = {
            "slug": ["UPPER", "has space", "../escape", "x" * 97, None],
            "category": ["unknown", [], False],
            "essential": ["false", 1, None],
            "themes": ["education", [None], ["unknown"], ["education", "education"]],
            "source_key": ["ee-tache3:alias:combinaison-1", None],
            "french": ["", " ", "Frame []", "Frame [[slot]]", "Frame [123]", "Frame [slot"],
        }
        for field in ("label", "english", "usage", "grammar", "example",
                      "example_english", "transfer_prompt"):
            cases[field] = ["", " ", None, 12]
        for field, values in cases.items():
            original = entry[field]
            for value in values:
                with self.subTest(field=field, value=value):
                    entry[field] = value
                    with self.assertRaises(ValueError):
                        self.load()
            entry[field] = original

    def test_evidence_allows_only_whitespace_normalization(self):
        entry = self.payload["entries"][0]
        entry["example"] = "Une mesure\npeut  aider."
        self.load()
        for example in (
            "une mesure peut aider.",
            "Une mesure pourrait aider.",
            "Une mesure peut aider!",
            "complètent. Une mesure",
            "Original source document text, not the answer.",
        ):
            with self.subTest(example=example):
                entry["example"] = example
                with self.assertRaisesRegex(ValueError, "verbatim"):
                    self.load()

    def test_evidence_uses_effective_override_not_archived_answer(self):
        self.response.position_claire = "La réponse de l’auteur a changé."
        with self.assertRaisesRegex(ValueError, "verbatim"):
            self.load()

    def test_titles_and_synthesis_are_valid_evidence(self):
        for example in ("Un titre", "Les documents se complètent."):
            self.payload["entries"][0]["example"] = example
            self.load()

    def test_duplicate_ids_and_frames_are_rejected(self):
        for field in ("slug", "french"):
            original = self.payload["entries"][1][field]
            self.payload["entries"][1][field] = self.payload["entries"][0][field]
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                self.load()
            self.payload["entries"][1][field] = original
        self.payload["entries"][1]["french"] = "  TITRES :  [mesure] peut aider. "
        with self.assertRaisesRegex(ValueError, "Duplicate frame"):
            self.load()
        self.payload["categories"].append(self.payload["categories"][0])
        with self.assertRaisesRegex(ValueError, "Duplicate category"):
            self.load()

    def test_category_types_fields_and_taxonomy_are_strict(self):
        category = self.payload["categories"][0]
        for field, values in (
            ("kind", ["other", "theme", None]),
            ("slug", ["unknown", "Not-a-slug"]),
            ("icon", ["", "bad icon"]),
            ("title", [False, ""]),
            ("description", [" ", []]),
        ):
            original = category[field]
            for value in values:
                with self.subTest(field=field, value=value):
                    category[field] = value
                    with self.assertRaises(ValueError):
                        self.load()
            category[field] = original
        self.payload["categories"].pop()
        with self.assertRaisesRegex(ValueError, "all functions and subject themes"):
            self.load()

    def test_unknown_or_missing_fields_and_non_objects_are_rejected(self):
        for record in (self.payload, self.payload["categories"][0], self.payload["entries"][0]):
            record["unexpected"] = True
            with self.assertRaises(ValueError):
                self.load()
            del record["unexpected"]
            key = next(iter(record))
            original = record.pop(key)
            with self.assertRaises(ValueError):
                self.load()
            record[key] = original
        self.payload["entries"][0] = []
        with self.assertRaises(ValueError):
            self.load()

    def test_duplicate_json_fields_are_rejected(self):
        self.path.write_text('{"version": 1, "version": 1}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate JSON field"):
            load_ee_formulations(self.path)

    def test_every_category_and_source_must_be_represented(self):
        last = self.payload["entries"].pop()
        with self.assertRaisesRegex(ValueError, "Every category"):
            self.load()
        self.payload["entries"].append(last)
        extra = SimpleNamespace(content_key="ee-tache3:test:combinaison-2")
        self.payload["source_response_count"] = 2
        with patch("study.ee_formulations.parse_ee_tache_three_responses",
                   return_value=[self.response, extra]):
            with self.assertRaisesRegex(ValueError, "Every effective response"):
                self.load()

    def test_thematic_entries_include_category_and_source_theme(self):
        self.payload["entries"][-1]["themes"] = []
        with self.assertRaisesRegex(ValueError, "theme category"):
            self.load()
        self.payload["entries"][-1]["themes"] = ["education"]
        with patch("study.ee_formulations.load_ee_subject_themes",
                   return_value=([SimpleNamespace(slug="education")],
                                 {self.source_key: "travail"})):
            with self.assertRaisesRegex(ValueError, "source theme"):
                self.load()

    def test_essentials_cover_all_functions(self):
        self.payload["entries"][0]["essential"] = False
        with self.assertRaisesRegex(ValueError, "complete function pipeline"):
            self.load()
