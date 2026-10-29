import copy
from dataclasses import replace
import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from study import catalogue
from study.eo2_question_languages import (
    DEFAULT_PATH, empty_manifest, fingerprint, language_presentation, manifest,
    scoped_dialogues, validate_manifest,
)
from study.models import ExamPart, Prompt, Response, Task, Theme
from study.oral_highlights import _render_questions
from study.tache_two_dialogues import dialogue_response, question_presentation
from study.translation import DeepLResponseError


def fixture_manifest(groups=None):
    """Mock English for isolated UI tests, never production content."""
    data = empty_manifest()
    for group, dialogue in scoped_dialogues().items():
        if groups is not None and group not in groups:
            continue
        data["groups"][group] = {
            fingerprint(question.question): {
                "french": question.question,
                "english": f"English test-only question {number} for {group}?",
            }
            for number, question in enumerate(dialogue.questions, 1)
        }
    return data


def unsaved_prompt(key):
    part = ExamPart(pk=1, slug="eo")
    task = Task(pk=1, part=part, slug="tache-2")
    theme = Theme(pk=1, task=task)
    return Prompt(
        pk=1, theme=theme, response=Response(pk=1, theme=theme),
        content_key=key, model_content={"storage_key": key},
    )


class EO2QuestionLanguageTests(SimpleTestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "questions.en.json"
        self.enterContext(override_settings(
            EO2_QUESTION_TRANSLATIONS_PATH=self.path,
            DEEPL_API_KEY="", DEEPL_TARGET_LANG="EN-GB", FRENCH_AUDIO_ENABLED=False,
        ))
        self.write(empty_manifest())

    def write(self, data):
        self.path.write_text(json.dumps(data, ensure_ascii=False))

    def test_scope_is_exactly_the_nine_requested_themes_75_models_and_600_questions(self):
        rows = scoped_dialogues()
        self.assertEqual(len(rows), 75)
        self.assertEqual(sum(len(row.questions) for row in rows.values()), 600)

    def test_empty_catalogue_explicitly_reports_unprepared_without_a_provider_call(self):
        dialogue = next(iter(scoped_dialogues().values()))
        questions = [{"text": question.question} for question in dialogue.questions]
        with patch("study.translation.urllib.request.urlopen") as provider:
            result = language_presentation(dialogue, questions)
        provider.assert_not_called()
        self.assertFalse(result["ready"])
        self.assertEqual(result["available"], 0)
        self.assertTrue(all(not row["english"] for row in questions))

    def test_exact_french_identity_blocks_stale_or_private_question_translations(self):
        self.write(fixture_manifest())
        key, dialogue = next(
            (key, row) for key, row in catalogue.tache_two_dialogues().items()
            if row.group in scoped_dialogues()
        )
        value = dialogue_response(dialogue)
        value = replace(
            value, is_personal=True,
            arguments=(replace(value.arguments[0], idea="Ma question privée non publiée ?"),)
            + value.arguments[1:],
        )
        with patch("study.translation.urllib.request.urlopen") as provider:
            result = question_presentation(unsaved_prompt(key), value)
        provider.assert_not_called()
        self.assertFalse(result["question_language"]["ready"])
        self.assertEqual(result["question_language"]["available"], 7)
        self.assertFalse(result["subject_questions"][0]["english"])
        self.assertTrue(result["subject_questions"][1]["english"])

    def test_all_150_french_annotation_layouts_remain_exact_even_with_english_prepared(self):
        self.write(fixture_manifest())
        expected = json.loads(Path(__file__).with_name("eo2_question_language_anchors.json").read_text())
        seen = set()
        for key, dialogue in catalogue.tache_two_dialogues().items():
            if dialogue.group not in expected or dialogue.group in seen:
                continue
            seen.add(dialogue.group)
            prompt = unsaved_prompt(key)
            for surface in ("detail", "back"):
                with self.subTest(group=dialogue.group, surface=surface):
                    rendered = _render_questions(
                        prompt, dialogue_response(dialogue), surface, [prompt],
                    )
                    self.assertEqual(
                        hashlib.sha256(rendered.text).hexdigest(),
                        expected[dialogue.group][surface],
                    )
        self.assertEqual(len(seen), 75)

    def test_unsupported_themes_do_not_get_controls(self):
        row = next(
            row for row in catalogue.tache_two_dialogues().values()
            if row.group not in scoped_dialogues()
        )
        self.assertIsNone(language_presentation(row, [{"text": q.question} for q in row.questions]))

    def test_corrupt_translation_catalogue_logs_an_error_but_preserves_french(self):
        self.path.write_text("{invalid")
        dialogue = next(iter(scoped_dialogues().values()))
        with self.assertLogs("study.eo2_question_languages", level="ERROR"):
            result = language_presentation(dialogue, [{"text": dialogue.questions[0].question}])
        self.assertTrue(result["error"])
        self.assertFalse(result["ready"])

    def test_manifest_rejects_mismatched_french_fingerprints_and_non_questions(self):
        data = fixture_manifest()
        group = next(iter(data["groups"]))
        digest = next(iter(data["groups"][group]))
        for field, value in (("french", "Un autre texte ?"), ("english", "Not a question")):
            bad = copy.deepcopy(data)
            bad["groups"][group][digest][field] = value
            with self.assertRaises(ValueError):
                validate_manifest(bad)

    def test_dry_run_counts_600_questions_and_never_uses_deepl(self):
        output = StringIO()
        with patch("study.translation.urllib.request.urlopen") as provider:
            call_command("prepare_eo2_translations", "--dry-run", stdout=output)
        provider.assert_not_called()
        self.assertIn("75 models; 600 questions; 600 missing", output.getvalue())
        self.assertEqual(manifest()["groups"], {})

    def test_generation_requires_exact_cost_confirmation_and_configured_key(self):
        characters = sum(len(q.question) for row in scoped_dialogues().values() for q in row.questions)
        with patch("study.translation.urllib.request.urlopen") as provider:
            with self.assertRaisesRegex(CommandError, "exact current character"):
                call_command("prepare_eo2_translations", "--prepare", stdout=StringIO())
            with self.assertRaisesRegex(CommandError, "DEEPL_API_KEY"):
                call_command(
                    "prepare_eo2_translations", "--prepare",
                    "--confirm-characters", str(characters), stdout=StringIO(),
                )
        provider.assert_not_called()

    @override_settings(DEEPL_TARGET_LANG="EN-US")
    def test_empty_manifest_accepts_the_configured_english_variant_without_writing_on_dry_run(self):
        before = self.path.read_bytes()
        with patch("study.translation.urllib.request.urlopen") as provider:
            call_command("prepare_eo2_translations", "--dry-run", stdout=StringIO())
        provider.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    @override_settings(DEEPL_API_KEY="test-only-key:fx")
    def test_generation_saves_completed_models_resumes_and_never_uploads_hidden_replies(self):
        from study.management.commands import prepare_eo2_translations as command

        group_theme = "benevolat-associations"
        _, mapping = catalogue.tache_two_subject_themes()
        groups = {
            row.group for key, row in catalogue.tache_two_dialogues().items()
            if mapping[key] == group_theme
        }
        characters = sum(
            len(q.question) for group, row in scoped_dialogues().items()
            if group in groups for q in row.questions
        )
        calls = []

        def translate(texts, key, *, context):
            calls.append((list(texts), context))
            if len(calls) == 2:
                raise DeepLResponseError("test failure")
            return [f"Test English question {i}?" for i, _ in enumerate(texts, 1)]

        with patch.object(command, "deepl_usage", return_value=(0, 1000000)), \
                patch.object(command, "deepl_translate", side_effect=translate):
            with self.assertRaisesRegex(CommandError, "earlier completed models are saved"):
                call_command(
                    "prepare_eo2_translations", "--prepare", "--themes", group_theme,
                    "--confirm-characters", str(characters), stdout=StringIO(),
                )
        self.assertEqual(len(manifest()["groups"]), 1)
        pending_characters = characters - sum(len(text) for text in calls[0][0])
        with patch.object(command, "deepl_usage", return_value=(0, 1000000)), \
                patch.object(command, "deepl_translate", side_effect=lambda texts, key, **kw: [
                    f"Test English question {i}?" for i, _ in enumerate(texts, 1)
                ]) as provider:
            call_command(
                "prepare_eo2_translations", "--prepare", "--themes", group_theme,
                "--confirm-characters", str(pending_characters), stdout=StringIO(),
            )
        self.assertEqual(provider.call_count, 3)
        self.assertEqual(len(manifest()["groups"]), 4)
        public_questions = {q.question for row in scoped_dialogues().values() for q in row.questions}
        self.assertTrue(all(text in public_questions for texts, _ in calls for text in texts))
        with patch.object(command, "deepl_usage") as usage, patch.object(command, "deepl_translate") as provider:
            call_command("prepare_eo2_translations", "--prepare", "--themes", group_theme, stdout=StringIO())
        usage.assert_not_called()
        provider.assert_not_called()

    @override_settings(DEEPL_API_KEY="test-only-key:fx")
    def test_generation_refuses_to_exceed_provider_allowance(self):
        from study.management.commands import prepare_eo2_translations as command

        characters = sum(len(q.question) for row in scoped_dialogues().values() for q in row.questions)
        with patch.object(command, "deepl_usage", return_value=(10, 11)), \
                patch.object(command, "deepl_translate") as provider:
            with self.assertRaisesRegex(CommandError, "remaining DeepL"):
                call_command(
                    "prepare_eo2_translations", "--prepare",
                    "--confirm-characters", str(characters), stdout=StringIO(),
                )
        provider.assert_not_called()


class EO2RecordedTranslationTests(SimpleTestCase):
    def test_production_manifest_is_honestly_empty_or_covers_every_current_scoped_question(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.assertIsNone(data["generated_at"])
            return
        self.assertTrue(data["generated_at"])
        self.assertTrue(data.get("reviewed_at"), "Review the generated English before publishing.")
        for group, dialogue in scoped_dialogues().items():
            saved = data["groups"].get(group, {})
            for question in dialogue.questions:
                with self.subTest(group=group, question=question.question):
                    self.assertIn(fingerprint(question.question), saved)

    def test_recorded_english_keeps_property_taxes_deposits_and_question_goals_distinct(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL translations have not been prepared.")
        for rows in data["groups"].values():
            for row in rows.values():
                french, english = row["french"].casefold(), row["english"].casefold()
                if "taxes foncières" in french:
                    self.assertIn("property tax", english)
                    self.assertNotIn("council tax", english)
                if "caution remboursable" in french and "acompte" in french:
                    self.assertIn("security deposit", english)
                    self.assertIn("booking deposit", english)
                self.assertNotIn("him/her", english)
        survey = scoped_dialogues()["french-class-survey-francophone-student"]
        row = data["groups"][survey.group][fingerprint(survey.questions[1].question)]
        self.assertIn("institution", row["english"].casefold())
        outing = scoped_dialogues()["neighbor-municipal-cultural-outings"]
        row = data["groups"][outing.group][fingerprint(outing.questions[1].question)]
        self.assertIn("what the next outing", row["english"])
        self.assertNotIn("when the next", row["english"])
