"""Prompt explanations must stay complete, scope-specific and non-destructive."""

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tache_three_prompt_notes import (
    NOTES_PATH, load_tache_three_prompt_notes, prompt_note_for_response,
)


class TacheThreePromptNoteTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sources = content.parse_responses()
        cls.payload = json.loads(NOTES_PATH.read_text())

    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def load(self, payload):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "notes.json"
            path.write_text(json.dumps(payload))
            return load_tache_three_prompt_notes(path, responses=self.sources)

    def test_every_group_and_every_exact_variant_has_an_explanation(self):
        notes = load_tache_three_prompt_notes(responses=self.sources)
        self.assertEqual(len(notes), 131)
        self.assertEqual(sum(len(row.source_prompts) for row in notes.values()), 167)
        self.assertEqual(set(notes), {row.semantic_group for row in self.sources})
        self.assertEqual(len({row.note for row in notes.values()}), 131)
        for source in self.sources:
            note = notes[source.semantic_group]
            with self.subTest(group=source.semantic_group):
                self.assertEqual(
                    note.source_prompts,
                    tuple((prompt.content_key, prompt.text) for prompt in source.prompts),
                )
                self.assertGreaterEqual(len(note.note.split()), 40)
                self.assertLessEqual(len(note.note.split()), 160)

    def test_explanations_address_qualifiers_and_different_question_scopes(self):
        notes = load_tache_three_prompt_notes()
        note = lambda key: notes[f"eo/tache-3/{key}"].note
        for key, phrase in {
            "culture-p3": "although one says",
            "culture-p17": "always positive",
            "culture-p20": "two linked questions",
            "famille-p2": "already says",
            "famille-p16": "after 25",
            "education-p5": "three important questions",
            "education-p22": "everything",
            "sante-p10": "banning all sales",
            "sante-p11": "stop being the seller",
            "sante-p15": "freely choose",
            "sante-p16": "not your nationality",
            "technologie-p2": "easy",
            "technologie-p11": "fixed telephone is therefore not a solution",
            "technologie-p18": "all purchases",
            "technologie-p20": "carpooling, taxis and rentals still involve cars",
            "technologie-p21": "newspapers, radio, Internet or social networks",
            "technologie-p24": "television, Internet and radio",
            "environnement-p2": "not directly whether all should close",
            "environnement-p4": "what happens to the animals",
            "environnement-p11": "not an assumption about your country",
            "economie-p1": "province or territory",
            "economie-p3": "refusing a role does not prove",
            "economie-p14": "without inventing which category is the majority",
            "economie-p22": "not no cost for the city",
            "economie-p23": "only",
        }.items():
            with self.subTest(group=key):
                self.assertIn(phrase, note(key))

    def test_rejects_missing_extra_or_changed_source_memberships(self):
        for mutation in ("missing", "unknown", "changed", "variant"):
            payload = deepcopy(self.payload)
            if mutation == "missing":
                payload["groups"].pop("culture-p1")
            elif mutation == "unknown":
                payload["groups"]["culture-p999"] = payload["groups"]["culture-p1"]
            elif mutation == "changed":
                payload["groups"]["culture-p1"]["prompt_signatures"]["culture:p1"] = "stale"
            else:
                payload["groups"]["culture-p3"]["prompt_signatures"].pop("economie:p5")
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.load(payload)

    def test_optional_examples_do_not_become_extra_prompt_requirements(self):
        notes = load_tache_three_prompt_notes()
        cause = notes["eo/tache-3/culture-p4"].note
        self.assertIn("choose a priority cause and explain why", cause)
        self.assertIn("can illustrate your reasons", cause)
        self.assertNotIn("Explain a feasible action", cause)
        culture = notes["eo/tache-3/culture-p14"].note
        self.assertIn("local cultural events", culture)
        self.assertIn("without travelling abroad", culture)
        self.assertNotIn("without leaving home", culture)
        traditions = notes["eo/tache-3/culture-p10"].note
        self.assertIn("feel at home", traditions)
        self.assertIn("other people's rights", traditions)
        self.assertIn("Keeping meaningful traditions and adapting", traditions)

    def test_notes_keep_screen_scope_and_choice_of_position_open(self):
        notes = load_tache_three_prompt_notes()
        screens = notes["eo/tache-3/sante-p2"].note
        self.assertIn("computers, tablets, phones and television", screens)
        self.assertIn("rather than a universal hour limit", screens)
        sport = notes["eo/tache-3/sante-p8"].note
        self.assertIn("adapted requirements or prefer encouragement", sport)
        self.assertIn("Avoid claiming one sport or intensity is suitable for every child", sport)
        volunteering = notes["eo/tache-3/education-p10"].note
        self.assertIn("would like to do", volunteering)
        self.assertIn("if you have not actually volunteered", volunteering)
        organic = notes["eo/tache-3/environnement-p7"].note
        self.assertIn("One source stops", organic)
        self.assertIn("no missing question wording should be invented", organic)

    def test_rejects_malformed_schema_notes_and_duplicate_json_fields(self):
        for payload in ([], {**self.payload, "extra": True}):
            with self.subTest(payload_type=type(payload)), self.assertRaises(ValueError):
                self.load(payload)
        for field, value in (("version", True), ("task", "ee/tache-3"), ("groups", [])):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load({**self.payload, field: value})
        for text in ("", "Too short.", " " + self.payload["groups"]["culture-p1"]["note"],
                     "\n".join(["text"] * 50), " ".join(["word"] * 161), None):
            payload = deepcopy(self.payload)
            payload["groups"]["culture-p1"]["note"] = text
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.load(payload)
        for row in ([], {"note": "Incomplete"}, {
            **self.payload["groups"]["culture-p1"], "extra": True,
        }):
            payload = deepcopy(self.payload)
            payload["groups"]["culture-p1"] = row
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.load(payload)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "notes.json"
            path.write_text('{"version": 1, "version": 1}')
            with self.assertRaises(ValueError):
                load_tache_three_prompt_notes(path, responses=self.sources)

    def test_cache_is_immutable_clearable_and_does_not_cache_validation_failures(self):
        with patch(
            "study.tache_three_prompt_notes.load_tache_three_prompt_notes",
            wraps=load_tache_three_prompt_notes,
        ) as loader:
            notes = catalogue.tache_three_prompt_notes()
            self.assertIs(catalogue.tache_three_prompt_notes(), notes)
            loader.assert_called_once_with()
            with self.assertRaises(TypeError):
                notes["new"] = notes["eo/tache-3/culture-p1"]
            with self.assertRaises(FrozenInstanceError):
                notes["eo/tache-3/culture-p1"].note = "Changed"
            catalogue.clear_catalogue_cache()
            self.assertEqual(catalogue.tache_three_prompt_notes(), notes)
            self.assertEqual(loader.call_count, 2)
        catalogue.clear_catalogue_cache()
        with patch(
            "study.tache_three_prompt_notes.load_tache_three_prompt_notes",
            side_effect=ValueError("Invalid notes"),
        ) as loader:
            for _ in range(2):
                with self.assertRaisesMessage(ValueError, "Invalid notes"):
                    catalogue.tache_three_prompt_notes()
            self.assertEqual(loader.call_count, 2)

    def test_task_boundaries_ad_hoc_groups_and_stale_prompts(self):
        with patch.object(catalogue, "tache_three_prompt_notes", side_effect=AssertionError("Wrong task")):
            for group in ("", "eo/tache-2/example", "ee/tache-3/example"):
                self.assertIsNone(prompt_note_for_response(SimpleNamespace(semantic_group=group)))
        self.assertIsNone(prompt_note_for_response(SimpleNamespace(semantic_group="eo/tache-3/ad-hoc")))
        with self.assertRaisesMessage(RuntimeError, "not synchronized"):
            prompt_note_for_response(
                SimpleNamespace(semantic_group="eo/tache-3/culture-p1"),
                SimpleNamespace(content_key="culture:p1", text="Changed question"),
            )
