import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from study import catalogue
from study import content_loader as content


class SubjectHintsTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.months = content.load_tache_two_subject_months()
        cls.payload = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text(encoding="utf-8"))
        cls.responses = content.parse_tache_two_responses(cls.months)

    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def load(self, payload):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "hints.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return content.load_tache_two_subject_hints(path, months=self.months)

    def test_every_publication_uses_its_semantic_groups_bilingual_hints(self):
        hints = content.load_tache_two_subject_hints(months=self.months)
        self.assertEqual(len(self.responses), 163)
        self.assertEqual(len(hints), 348)
        self.assertEqual(
            set(hints),
            {prompt.content_key for response in self.responses for prompt in response.prompts},
        )
        lists = set()
        for response in self.responses:
            group_hints = hints[response.content_key]
            self.assertGreaterEqual(len(group_hints), 5)
            self.assertLessEqual(len(group_hints), 10)
            lists.add(group_hints)
            for prompt in response.prompts:
                self.assertIs(hints[prompt.content_key], group_hints)
            for language in ("french", "english"):
                values = [getattr(hint, language) for hint in group_hints]
                self.assertEqual(len(values), len(set(values)))
                self.assertTrue(all(value.strip() == value and 0 < len(value) <= 100 for value in values))
        self.assertEqual(len(lists), len(self.responses), "Distinct scenarios must not share generic lists")

    def test_same_source_model_does_not_merge_distinct_scenarios_hints(self):
        hints = catalogue.tache_two_subject_hints()
        models = {}
        for response in self.responses:
            for prompt in response.prompts:
                models.setdefault(prompt.model_content["body_hash"], set()).add(response.content_key)
        distinct_scenarios = [keys for keys in models.values() if len(keys) > 1]
        self.assertTrue(distinct_scenarios)
        for keys in distinct_scenarios:
            self.assertEqual(len({hints[key] for key in keys}), len(keys))

    def test_apartment_watching_cues_cover_the_requested_practical_topics(self):
        hints = catalogue.tache_two_subject_hints()["tache2:mai:batch-02:subject-08"]
        french = " ".join(hint.french for hint in hints).casefold()
        english = " ".join(hint.english for hint in hints).casefold()
        for concept in ("départ", "retour", "fréquence", "clés", "alarme", "sécurité", "courrier", "colis"):
            self.assertIn(concept, french)
        for concept in ("departure", "return", "frequency", "keys", "alarm", "security", "mail", "packages"):
            self.assertIn(concept, english)

    def test_cached_hints_are_immutable_and_clear_reloads_the_source(self):
        with patch.object(content, "load_tache_two_subject_hints", wraps=content.load_tache_two_subject_hints) as loader:
            hints = catalogue.tache_two_subject_hints()
            self.assertIs(catalogue.tache_two_subject_hints(), hints)
            loader.assert_called_once_with(months=catalogue.tache_two_subject_months())
            key = next(iter(hints))
            with self.assertRaises(TypeError):
                hints[key] = ()
            with self.assertRaises(FrozenInstanceError):
                hints[key][0].french = "Autre sujet"
            catalogue.clear_catalogue_cache()
            refreshed = catalogue.tache_two_subject_hints()
            self.assertEqual(refreshed, hints)
            self.assertIsNot(refreshed, hints)
            self.assertEqual(loader.call_count, 2)

    def test_missing_unknown_and_duplicate_groups_fail_instead_of_falling_back(self):
        for remove in (True, False):
            invalid = copy.deepcopy(self.payload)
            if remove:
                invalid["groups"].pop(next(iter(invalid["groups"])))
            else:
                invalid["groups"]["unknown-subject"] = next(iter(invalid["groups"].values()))
            with self.subTest(remove=remove), self.assertRaisesMessage(ValueError, "group coverage"):
                self.load(invalid)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "hints.json"
            with self.assertRaises(FileNotFoundError):
                content.load_tache_two_subject_hints(path, months=self.months)
            key = next(iter(self.payload["groups"]))
            path.write_text('{"groups": {"' + key + '": [], "' + key + '": []}}', encoding="utf-8")
            with self.assertRaisesMessage(ValueError, "Duplicate field"):
                content.load_tache_two_subject_hints(path, months=self.months)

    def test_rejects_invalid_metadata_and_hint_rows(self):
        for field, value in (
            ("version", True), ("version", 2), ("task", "eo/tache-3"), ("groups", []),
        ):
            invalid = {**self.payload, field: value}
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.load(invalid)
        for rows in ([], ["cue"] * 6, [{"french": "Sans traduction"}] * 6, [None] * 6):
            invalid = copy.deepcopy(self.payload)
            invalid["groups"][next(iter(invalid["groups"]))] = rows
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.load(invalid)
        for language in ("french", "english"):
            for value in (None, 1, "", " ", " Sans espace ", "x" * 101, "Deux\nlignes", "Une question ?"):
                invalid = copy.deepcopy(self.payload)
                next(iter(invalid["groups"].values()))[0][language] = value
                with self.subTest(language=language, value=value), self.assertRaises(ValueError):
                    self.load(invalid)
            invalid = copy.deepcopy(self.payload)
            rows = next(iter(invalid["groups"].values()))
            rows[1][language] = rows[0][language].upper()
            with self.assertRaisesMessage(ValueError, "Duplicate"):
                self.load(invalid)

    def test_custom_file_is_revalidated_after_catalogue_warmup(self):
        original = catalogue.tache_two_subject_hints()
        invalid = {**self.payload, "task": "ee/tache-2"}
        with self.assertRaises(ValueError):
            self.load(invalid)
        self.assertIs(catalogue.tache_two_subject_hints(), original)

    def test_failed_loads_are_not_cached(self):
        with patch.object(content, "load_tache_two_subject_hints", side_effect=ValueError("Invalid hints")) as loader:
            for _ in range(2):
                with self.assertRaisesMessage(ValueError, "Invalid hints"):
                    catalogue.tache_two_subject_hints()
            self.assertEqual(loader.call_count, 2)
