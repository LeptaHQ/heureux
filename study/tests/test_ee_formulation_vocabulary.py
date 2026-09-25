import copy
import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from study.content_loader import load_ee_subject_themes
from study.ee_formulation_vocabulary import (
    VOCABULARY_PATH,
    get_ee_formulation_vocabulary,
    load_ee_formulation_vocabulary,
)


class EeOneFormulationVocabularyTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.payload = json.loads(VOCABULARY_PATH.read_text(encoding="utf-8"))

    def _load(self, payload):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "formulation_vocabulary.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            return load_ee_formulation_vocabulary(path)

    def test_catalog_covers_every_theme_with_usable_grounded_entries(self):
        vocabulary = get_ee_formulation_vocabulary()
        expected = [
            theme.slug for theme in load_ee_subject_themes(1)[0]
        ]
        self.assertEqual(list(vocabulary), expected)
        self.assertEqual(
            sum(len(items) for items in vocabulary.values()),
            110,
        )
        for theme_slug, items in vocabulary.items():
            with self.subTest(theme=theme_slug):
                self.assertEqual(len(items), 10)
                self.assertIsInstance(items, tuple)
                for item in items:
                    self.assertTrue(item.french.strip())
                    self.assertTrue(item.english.strip())
                    self.assertTrue(item.usage.strip())
                    self.assertEqual(item.role, "vocabulary")
                    self.assertTrue(item.examples)
                    self.assertEqual(item.pattern, item.usage)
        with self.assertRaises(TypeError):
            vocabulary[expected[0]] = ()

    def test_loader_rejects_non_verbatim_or_wrong_theme_evidence(self):
        adapted = copy.deepcopy(self.payload)
        adapted["themes"][0]["entries"][0]["examples"][0][
            "french"
        ] += " Texte inventé."
        with self.assertRaisesRegex(ValueError, "not verbatim evidence"):
            self._load(adapted)

        misplaced = copy.deepcopy(self.payload)
        misplaced["themes"][0]["entries"][0]["examples"][0][
            "source_key"
        ] = self.payload["themes"][1]["entries"][0]["examples"][0][
            "source_key"
        ]
        with self.assertRaisesRegex(ValueError, "another theme"):
            self._load(misplaced)

    def test_loader_rejects_term_missing_from_example_and_theme_drift(self):
        missing_term = copy.deepcopy(self.payload)
        missing_term["themes"][0]["entries"][0]["term"] = (
            "terme totalement absent"
        )
        with self.assertRaisesRegex(ValueError, "does not contain term"):
            self._load(missing_term)

        reordered = copy.deepcopy(self.payload)
        reordered["themes"][0], reordered["themes"][1] = (
            reordered["themes"][1],
            reordered["themes"][0],
        )
        with self.assertRaisesRegex(ValueError, "theme order"):
            self._load(reordered)
