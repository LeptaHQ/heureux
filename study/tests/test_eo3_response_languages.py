from dataclasses import asdict, replace
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase, override_settings

from study.eo3_response_languages import (
    DEFAULT_PATH, empty_manifest, fingerprint, language_presentation, manifest, public_fields,
    scoped_models, validate_manifest,
)
from study import catalogue
from study.account_services import provision_user_study_data
from study.card_presentation import card_payload
from study.models import Card, CardType, PersonalResponse, Prompt
from study.public_response_annotations import render_current_response
from study.routing import prompt_detail_url

from . import factories


def fixture_manifest(models=None):
    data = empty_manifest()
    for group, model in (models or scoped_models()).items():
        data["groups"][group] = {
            fingerprint(text): {"french": text, "english": f"English test-only gloss {number}."}
            for number, text in enumerate(public_fields(model).values(), 1)
        }
    return data


class EO3ResponseLanguageTests(SimpleTestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "responses.en.json"
        self.enterContext(override_settings(
            EO3_RESPONSE_TRANSLATIONS_PATH=self.path,
            DEEPL_API_KEY="", DEEPL_TARGET_LANG="EN-GB",
        ))
        self.write(empty_manifest())
        self.model = scoped_models()["eo/tache-3/culture-p30"]
        self.characters = sum(
            sum(len(text) for text in dict.fromkeys(public_fields(model).values()))
            for model in scoped_models().values()
        )

    def write(self, data):
        self.path.write_text(json.dumps(data, ensure_ascii=False))

    def presentation(self, response=None):
        response = response or self.model.response
        return language_presentation(self.model, response, response.arguments)

    def test_complete_public_scope_has_131_models_and_1965_spoken_blocks(self):
        models = scoped_models()
        self.assertEqual(len(models), 131)
        self.assertEqual(sum(len(public_fields(model)) for model in models.values()), 1965)
        fields = public_fields(self.model)
        self.assertEqual(len(fields), 15)
        self.assertNotIn(self.model.response.reformulation, fields.values())
        self.assertNotIn(self.model.response.position, fields.values())

    def test_unprepared_data_preserves_french_without_uploading_anything(self):
        with patch("study.translation.urllib.request.urlopen") as provider:
            result = self.presentation()
        provider.assert_not_called()
        self.assertFalse(result["ready"])
        self.assertEqual(result["available"], 0)
        self.assertEqual(result["total"], 15)
        self.assertEqual(result["annotation_key"], "")
        self.assertTrue(all(not value for value in result["fields"].values()))

    def test_english_annotation_identity_tracks_model_and_actual_translation(self):
        other = next(model for model in scoped_models().values() if model.group != self.model.group)
        data = fixture_manifest({model.group: model for model in (self.model, other)})
        for rows in data["groups"].values():
            for row in rows.values():
                row["english"] = "The same English gloss."
        self.write(data)
        first = self.presentation()["annotation_key"]
        self.assertTrue(first.startswith("english:eo3:"))
        self.assertEqual(self.presentation()["annotation_key"], first)
        self.assertNotEqual(language_presentation(
            other, other.response, other.response.arguments,
        )["annotation_key"], first)
        row = next(iter(data["groups"][self.model.group].values()))
        row["english"] = "An updated English gloss."
        self.write(data)
        self.assertNotEqual(self.presentation()["annotation_key"], first)

    def test_private_and_stale_text_is_never_uploaded_or_given_an_unmatched_gloss(self):
        self.write(fixture_manifest())
        private = replace(
            self.model.response, position_claire="My private French draft.", is_personal=True,
        )
        with patch("study.translation.urllib.request.urlopen") as provider:
            result = self.presentation(private)
        provider.assert_not_called()
        self.assertFalse(result["ready"])
        self.assertEqual(result["available"], 14)
        self.assertTrue(result["annotation_key"].startswith("english:eo3:"))
        self.assertEqual(result["fields"]["introduction"], "")
        self.assertTrue(result["fields"]["argument-1-exemple"])
        result = self.presentation(replace(
            self.model.response, position_claire=self.model.response.position_claire + " ",
        ))
        self.assertEqual(result["fields"]["introduction"], "")

    def test_translation_identity_uses_stable_argument_ids(self):
        model = scoped_models()["eo/tache-3/culture-p1"]
        fields = public_fields(replace(model, argument_ids=(1, 4, 2)))
        self.assertIn("argument-4-exemple", fields)
        self.assertNotIn("argument-3-exemple", fields)

    def test_corrupt_cache_reports_an_error_without_losing_french(self):
        self.path.write_text("{")
        with self.assertLogs("study.eo3_response_languages", level="ERROR"):
            result = self.presentation()
        self.assertTrue(result["error"])
        self.assertFalse(result["ready"])
        self.assertEqual(result["fields"], {})

    def test_invalid_fingerprints_and_review_provenance_are_rejected(self):
        data = fixture_manifest({self.model.group: self.model})
        row = next(iter(data["groups"][self.model.group].values()))
        row["french"] += " Changed"
        with self.assertRaises(ValueError):
            validate_manifest(data)
        data = fixture_manifest({self.model.group: self.model})
        row = next(iter(data["groups"][self.model.group].values()))
        row["deepl_english"] = "Original English."
        with self.assertRaises(ValueError):
            validate_manifest(data)
        row["review_note"] = "Reviewed idiom."
        self.assertIs(validate_manifest(data), data)

    def test_warm_manifest_reads_are_cached_and_changed_files_are_reloaded(self):
        self.write(fixture_manifest())
        first = manifest()
        self.assertIs(manifest(), first)
        self.write(empty_manifest())
        self.assertFalse(manifest()["groups"])

    def test_dry_run_never_contacts_deepl_and_counts_only_spoken_public_fields(self):
        output = StringIO()
        with patch("study.management.commands.prepare_eo3_translations.deepl_translate") as provider:
            call_command("prepare_eo3_translations", "--dry-run", stdout=output)
        provider.assert_not_called()
        self.assertIn("131 models; 1965 response blocks; 1965 missing translations", output.getvalue())
        self.assertIn(f"{self.characters} source characters", output.getvalue())

    def test_preparation_requires_exact_confirmation_and_a_key(self):
        with self.assertRaisesMessage(CommandError, "confirm the exact"):
            call_command("prepare_eo3_translations", "--prepare", stdout=StringIO())
        with self.assertRaisesMessage(CommandError, "not configured"):
            call_command(
                "prepare_eo3_translations", "--prepare", "--confirm-characters", str(self.characters),
                stdout=StringIO(),
            )

    def test_preparation_checks_allowance_before_any_billable_request(self):
        with (
            override_settings(DEEPL_API_KEY="test-only-key"),
            patch("study.management.commands.prepare_eo3_translations.deepl_usage", return_value=(90, 100)),
            patch("study.management.commands.prepare_eo3_translations.deepl_translate") as provider,
            self.assertRaisesMessage(CommandError, "remaining DeepL"),
        ):
            call_command(
                "prepare_eo3_translations", "--prepare", "--confirm-characters", str(self.characters),
                stdout=StringIO(),
            )
        provider.assert_not_called()

    def test_preparation_resumes_atomically_and_never_sends_preparation_or_private_text(self):
        models = dict(list(scoped_models().items())[:2])
        characters = sum(
            sum(len(text) for text in dict.fromkeys(public_fields(model).values()))
            for model in models.values()
        )
        sent = []

        def translate(texts, key, *, context):
            sent.append((texts, context))
            if len(sent) == 2:
                raise OSError("Provider stopped")
            return [f"English test-only result {number}." for number in range(len(texts))]

        with (
            override_settings(DEEPL_API_KEY="test-only-key"),
            patch("study.management.commands.prepare_eo3_translations.scoped_models", return_value=models),
            patch("study.management.commands.prepare_eo3_translations.deepl_usage", return_value=(0, 1000000)),
            patch("study.management.commands.prepare_eo3_translations.deepl_translate", side_effect=translate),
            self.assertRaisesMessage(CommandError, "No automatic retry"),
        ):
            call_command(
                "prepare_eo3_translations", "--prepare", "--confirm-characters", str(characters),
                stdout=StringIO(),
            )
        saved = manifest()
        self.assertEqual(len(saved["groups"]), 1)
        self.assertNotIn("reviewed_at", saved)
        public_texts = {text for model in models.values() for text in public_fields(model).values()}
        for texts, context in sent:
            self.assertTrue(any(model.source_prompts[0][1] in context for model in models.values()))
            self.assertLessEqual(set(texts), public_texts)
        output = StringIO()
        with patch("study.management.commands.prepare_eo3_translations.scoped_models", return_value=models):
            call_command("prepare_eo3_translations", "--dry-run", stdout=output)
        self.assertIn("15 missing translations", output.getvalue())

    def test_saved_public_english_is_complete_reviewed_and_keeps_post_edit_provenance(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        self.assertTrue(data["generated_at"])
        self.assertTrue(data.get("reviewed_at"))
        for group, model in scoped_models().items():
            for french in public_fields(model).values():
                row = data["groups"][group][fingerprint(french)]
                self.assertEqual(row["french"], french)
                self.assertTrue(row["english"].strip())
                if row.get("deepl_english"):
                    self.assertTrue(row["review_note"].strip())
        regressions = (
            ("eo/tache-3/sante-p11", "61475ab4126e358f014a171f226f56baf5d51f047084793d3cab31af42157e3a", "remove a bonus"),
            ("eo/tache-3/education-p12", "f84a48745f67d1f9227f880afdd27a89be1dc94528b01757ab167707141492b4", "in an exercise"),
            ("eo/tache-3/culture-p34", "39f31843ac1ae30322b45068d101980d912bfa93ef9755c4eeaafa35204e7779", "buying second-hand"),
            ("eo/tache-3/famille-p2", "7e88df36a5f5c16bc2f25b291a6db1f6b458c321ca207c4c34668f6660ab8cdc", "where they live"),
            ("eo/tache-3/culture-p31", "a7902cf141991845f71442d19f7300637afda293dcabc98300f3a868907f356a", "A high-school student"),
        )
        for group, digest, wording in regressions:
            row = data["groups"][group][digest]
            self.assertIn(wording, row["english"])
            self.assertTrue(row["deepl_english"])
            self.assertTrue(row["review_note"])
        student = data["groups"]["eo/tache-3/culture-p31"]["a7902cf141991845f71442d19f7300637afda293dcabc98300f3a868907f356a"]
        self.assertTrue(student["french"].startswith("Un lycéen"))
        self.assertTrue(student["english"].startswith("A high-school student"))
        self.assertNotIn("sixth-former", student["english"])
        country = scoped_models()["eo/tache-3/culture-p19"]
        row = data["groups"][country.group][fingerprint(country.response.nuance)]
        self.assertIn("neighbourhood meeting", row["english"])
        self.assertIn("last time", row["english"])
        self.assertIn("abandoned project", row["english"])
        row = data["groups"][country.group][fingerprint(country.response.arguments[1].exemple)]
        self.assertIn("French but not Japanese", row["english"])
        self.assertIn("French subtitles", row["english"])
        self.assertIn("translate a teacher", row["english"])
        self.assertIn("the pupils do this to learn", row["english"])
        row = data["groups"][country.group][fingerprint(country.response.arguments[0].exemple)]
        self.assertIn("leave without buying anything", row["english"])
        row = data["groups"][country.group][fingerprint(country.response.arguments[0].consequence)]
        self.assertIn("this market is also a meeting place", row["english"])
        cuisine = scoped_models()["eo/tache-3/culture-p15"]
        row = data["groups"][cuisine.group][fingerprint(cuisine.response.arguments[0].exemple)]
        self.assertIn("the same large dish", row["english"])
        self.assertIn("The hosts explain", row["english"])
        self.assertIn("this evening meal", row["english"])
        self.assertIn("talk after work", row["english"])
        row = data["groups"][cuisine.group][fingerprint(cuisine.response.arguments[0].consequence)]
        self.assertTrue(row["english"].startswith("The visitor"))
        self.assertIn("this family organises its day", row["english"])
        self.assertIn("set aside time together", row["english"])
        row = data["groups"][cuisine.group][fingerprint(cuisine.response.nuance)]
        self.assertIn("it does not show everything", row["english"])
        self.assertIn("its political system, its debates or its language", row["english"])
        self.assertNotIn("must also explore the language", row["english"])
        row = data["groups"][cuisine.group][fingerprint(cuisine.response.arguments[0].developpement)]
        self.assertIn("Mealtimes may reflect the rhythm of work", row["english"])
        self.assertIn("also shows the importance given to family conversation", row["english"])
        self.assertIn("How a meal is organised", row["english"])
        row = data["groups"][cuisine.group][fingerprint(cuisine.response.arguments[1].developpement)]
        self.assertIn("Ingredients and ways of preserving food", row["english"])
        self.assertIn("retain traces of life in the past", row["english"])
        row = data["groups"][cuisine.group][fingerprint(cuisine.response.arguments[1].exemple)]
        self.assertIn("people salted and dried fish", row["english"])
        self.assertIn("to keep it during long sea voyages", row["english"])
        older = scoped_models()["eo/tache-3/culture-p8"]
        row = data["groups"][older.group][fingerprint(older.response.arguments[0].exemple)]
        self.assertIn("arguing with their parents", row["english"])
        self.assertIn("disagreement between generations", row["english"])
        row = data["groups"][older.group][fingerprint(older.response.arguments[1].exemple)]
        self.assertIn("clips of the same school fight", row["english"])
        self.assertIn("violence is common among young people", row["english"])
        self.assertNotIn("violence is rife", row["english"])

    def test_adults_recalling_their_own_behaviour_corrects_the_comparison_in_both_languages(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p2"]
        argument = model.response.arguments[0]
        self.assertIn("son jugement devient déjà moins catégorique", argument.exemple)
        self.assertIn("peut donc porter un jugement plus juste", argument.consequence)
        english = data["groups"][model.group][fingerprint(argument.consequence)]["english"]
        self.assertIn("can therefore help the adult judge the young person more fairly", english)
        self.assertNotIn("is then judged against an idealised memory", english)
        self.assertEqual(model.argument_ids, (1, 2, 3))

    def test_education_english_keeps_quebec_questions_and_volunteering_hypothetical(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        models = scoped_models()
        quebec = models["eo/tache-3/education-p5"]
        rows = data["groups"][quebec.group]
        questions = (
            "is my French good enough for everyday life?",
            "is my career plan feasible in Quebec?",
            "do I have enough money, and who can I count on to help me settle in?",
        )
        for argument, question in zip(quebec.response.arguments, questions):
            self.assertIn(question, rows[fingerprint(argument.idea)]["english"])
        self.assertIn("I would ask myself three questions", rows[
            fingerprint(quebec.response.position_claire)
        ]["english"])
        qualification = rows[fingerprint(quebec.response.arguments[1].exemple)]["english"]
        self.assertIn("whether her qualification allows her to practise", qualification)
        self.assertIn("before counting on an income", qualification)
        volunteer = models["eo/tache-3/education-p10"]
        self.assertEqual(
            {key for key, _ in volunteer.source_prompts}, {"education:p10", "education:p24"},
        )
        rows = data["groups"][volunteer.group]
        self.assertIn("I would like to take part", rows[
            fingerprint(volunteer.response.position_claire)
        ]["english"])
        example = rows[fingerprint(volunteer.response.arguments[2].exemple)]["english"]
        self.assertIn("If someone explained", example)
        self.assertIn("I would ask", example)
        self.assertIn("rice they could not prepare", example)

    def test_education_english_distinguishes_information_access_and_learning_alone(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        models = scoped_models()
        phone = models["eo/tache-3/education-p15"]
        rows = data["groups"][phone.group]
        introduction = rows[fingerprint(phone.response.position_claire)]["english"]
        self.assertIn("easy access to information, but not always to accurate information", introduction)
        example = rows[fingerprint(phone.response.arguments[1].exemple)]["english"]
        self.assertIn("all cite the same unsourced message", example)
        development = rows[fingerprint(phone.response.arguments[2].developpement)]["english"]
        self.assertIn("Comparing independent sources", development)
        self.assertIn("counting repetitions of the same message does not", development)
        alone = models["eo/tache-3/education-p22"]
        rows = data["groups"][alone.group]
        self.assertIn("I don't agree with the word 'everything'", rows[
            fingerprint(alone.response.position_claire)
        ]["english"])
        result = rows[fingerprint(alone.response.arguments[1].consequence)]["english"]
        self.assertIn("with the partner's help", result)
        self.assertIn("no longer entirely solitary", result)
        example = rows[fingerprint(alone.response.arguments[2].exemple)]["english"]
        self.assertIn("they stall", example)
        self.assertIn("with the instructor beside them", example)

    def test_education_english_keeps_salary_argument_ids_and_shared_arts_polarity(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        models = scoped_models()
        salary = models["eo/tache-3/education-p16"]
        self.assertEqual(salary.argument_ids, (1, 3, 4))
        self.assertEqual(
            {key for key, _ in salary.source_prompts}, {"education:p16", "economie:p12"},
        )
        fields = public_fields(salary)
        self.assertNotIn("argument-2-idea", fields)
        rows = data["groups"][salary.group]
        self.assertIn("retain skills that are hard to replace", rows[
            fingerprint(fields["argument-4-idea"])
        ]["english"])
        retention = rows[fingerprint(fields["argument-4-exemple"])]["english"]
        self.assertIn("She receives a better offer elsewhere", retention)
        self.assertIn("can offer her a pay rise", retention)
        self.assertIn("risk the machine being out of operation", retention)
        arts = models["eo/tache-3/culture-p13"]
        self.assertEqual(
            {key for key, _ in arts.source_prompts}, {"culture:p13", "education:p11"},
        )
        introduction = data["groups"][arts.group][
            fingerprint(arts.response.position_claire)
        ]["english"]
        self.assertIn("No, I don't agree with this proposal", introduction)
        self.assertIn("Removing music, drawing or drama from school would be a mistake", introduction)

    def test_education_english_keeps_university_access_conditional_not_unconditional_entry(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/education-p20"]
        self.assertEqual(
            {key for key, _ in model.source_prompts}, {"education:p20", "economie:p19"},
        )
        rows = data["groups"][model.group]
        introduction = rows[fingerprint(model.response.position_claire)]["english"]
        self.assertIn("a real chance to get in", introduction)
        self.assertIn("neither accepting every application unconditionally", introduction)
        self.assertIn("nor sending everyone to university", introduction)
        example = rows[fingerprint(model.response.arguments[0].exemple)]["english"]
        self.assertIn("If she receives the aid", example)
        self.assertIn("can consider this plan", example)
        result = rows[fingerprint(model.response.arguments[2].consequence)]["english"]
        self.assertIn("without removing the course requirements", result)

    def test_education_english_keeps_life_success_possible_and_school_priority_nonexclusive(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        models = scoped_models()
        grades = models["eo/tache-3/education-p21"]
        rows = data["groups"][grades.group]
        introduction = rows[fingerprint(grades.response.position_claire)]["english"]
        self.assertIn("good grades can contribute to success in life", introduction)
        self.assertIn("not the same as saying they are essential or sufficient", introduction)
        self.assertIn("a successful life cannot be reduced to an academic record", introduction)
        example = rows[fingerprint(grades.response.arguments[2].exemple)]["english"]
        self.assertIn("student who works in the evenings", example)
        self.assertIn("If she receives this aid", example)
        self.assertIn("and can adjust her working hours", example)
        self.assertIn("will be able to work less", example)
        school = models["eo/tache-3/education-p18"]
        rows = data["groups"][school.group]
        introduction = rows[fingerprint(school.response.position_claire)]["english"]
        self.assertIn("teaching the curriculum is an essential priority", introduction)
        self.assertIn("a priority is not an exclusive mission", introduction)
        self.assertIn("often during the very same lessons", introduction)

    def test_education_english_post_edits_preserve_the_preceding_editorial_translation(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        models = scoped_models()
        for group, digest, current, previous in (
            (
                "education-p1",
                "d485ec30753b481c63a84f29bca19406974f7749f7e1f338a0763ba06044ebc4",
                "the employee knows who to turn to",
                "In his first job, a manager",
            ),
            (
                "education-p20",
                fingerprint(models["eo/tache-3/education-p20"].response.arguments[1].idea),
                "Wider access to university",
                "An open university",
            ),
        ):
            with self.subTest(group=group, digest=digest):
                row = data["groups"][f"eo/tache-3/{group}"][digest]
                self.assertEqual(fingerprint(row["french"]), digest)
                self.assertIn(current, row["english"])
                self.assertNotIn(previous, row["english"])
                preceding = row["editorial_history"][-1]
                self.assertEqual(preceding["french"], row["french"])
                self.assertIn(previous, preceding["english"])
                self.assertIn("No DeepL original or provider call was made", preceding["review_note"])
                self.assertIn("editorial_history", row["review_note"])

    def test_proactive_education_english_keeps_context_and_possible_help_explicit(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        cases = (
            ("education-p1", "argument-1-exemple", ("doctor's office", "without help"), ()),
            ("education-p5", "argument-3-exemple", ("found a job in Quebec", "what help they could actually provide"), ()),
            ("education-p7", "argument-1-consequence", ("concrete skills", "in her application"), ("change careers",)),
            ("education-p16", "argument-4-exemple", ("specialised machine", "while it finds and trains someone"), ()),
        )
        models = scoped_models()
        for name, field, required, forbidden in cases:
            with self.subTest(model=name, field=field):
                group = f"eo/tache-3/{name}"
                french = public_fields(models[group])[field]
                english = data["groups"][group][fingerprint(french)]["english"]
                for phrase in required:
                    self.assertIn(phrase, english)
                for phrase in forbidden:
                    self.assertNotIn(phrase, english)

    def test_proactive_education_english_post_edits_preserve_complete_preceding_rows(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        for name, field, current, previous in (
            ("education-p6", "argument-1-exemple", "organise a drop-off", "organise a collection"),
            ("education-p10", "argument-2-exemple", "team to look for a solution", "team to find a solution"),
        ):
            with self.subTest(model=name, field=field):
                group = f"eo/tache-3/{name}"
                french = public_fields(scoped_models()[group])[field]
                row = data["groups"][group][fingerprint(french)]
                self.assertIn(current, row["english"])
                self.assertNotIn(previous, row["english"])
                preceding = row["editorial_history"][-1]
                self.assertIn(previous, preceding["english"])
                self.assertEqual(preceding["french"], french)
                self.assertEqual(row.get("deepl_english"), preceding.get("deepl_english"))
                self.assertIn("editorial_history", row["review_note"])
        plans = catalogue.tache_three_subject_hints()
        volunteer = plans["eo/tache-3/education-p10"]
        self.assertIn("look for a replacement", volunteer.arguments[1].example.english)
        self.assertIn("look for no-cook food", volunteer.arguments[2].example.english)

    def test_proactive_culture_english_keeps_concrete_help_actors_and_shared_language(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        cases = (
            (
                "culture-p11", "argument-4-exemple",
                ("A colleague from another country", "housing-aid application form", "The newcomer also joins"),
            ),
            (
                "culture-p29", "argument-2-exemple",
                ("An employee abroad", "cannot get leave immediately", "can look for someone to help her father"),
            ),
            (
                "culture-p31", "argument-3-exemple",
                ("After the purchase, the teenager notices",),
            ),
            (
                "culture-p35", "argument-3-exemple",
                ("a language they share", "The family understands"),
            ),
        )
        models = scoped_models()
        for name, field, required in cases:
            with self.subTest(model=name, field=field):
                group = f"eo/tache-3/{name}"
                french = public_fields(models[group])[field]
                english = data["groups"][group][fingerprint(french)]["english"]
                for phrase in required:
                    self.assertIn(phrase, english)

    def test_culture_english_actor_corrections_preserve_the_preceding_records(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        models = scoped_models()
        for name, field, current, previous in (
            (
                "culture-p24", "argument-4-consequence",
                "conclude that they are struggling", "conclude that she is struggling",
            ),
            (
                "culture-p31", "argument-3-consequence",
                "The teenager therefore made a purchase believing they were following",
                "He therefore made",
            ),
        ):
            with self.subTest(model=name, field=field):
                group = f"eo/tache-3/{name}"
                french = public_fields(models[group])[field]
                row = data["groups"][group][fingerprint(french)]
                self.assertIn(current, row["english"])
                self.assertNotIn(previous, row["english"])
                preceding = row["editorial_history"][-1]
                self.assertEqual(preceding["french"], french)
                self.assertIn(previous, preceding["english"])
                self.assertEqual(row.get("deepl_english"), preceding.get("deepl_english"))
                self.assertIn("editorial_history", row["review_note"])

    def test_education_english_matches_speaking_feedback_to_progress_under_fresh_ids(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        models = scoped_models()
        language = models["eo/tache-3/education-p13"]
        outing = models["eo/tache-3/education-p23"]
        self.assertEqual(language.argument_ids, (1, 2, 4))
        self.assertEqual(outing.argument_ids, (1, 2, 4))
        for model in (language, outing):
            self.assertNotIn("argument-3-idea", public_fields(model))
        example = data["groups"][language.group][
            fingerprint(language.response.arguments[2].exemple)
        ]["english"]
        self.assertIn("points out unclear phrases", example)
        self.assertIn("practise those phrases", example)
        self.assertIn("their partner understands their account", example)
        self.assertIn("without asking them to rephrase", example)
        self.assertNotIn("understand a voice message", example)

    def test_education_english_does_not_narrow_close_contacts_to_relatives(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        models = scoped_models()
        for group, index, field, wording in (
            ("education-p2", 0, "exemple", "someone close to her"),
            ("education-p5", 2, "exemple", "someone close to them"),
        ):
            with self.subTest(group=group, field=field):
                model = models[f"eo/tache-3/{group}"]
                french = getattr(model.response.arguments[index], field)
                english = data["groups"][model.group][fingerprint(french)]["english"]
                self.assertIn(wording, english)
                self.assertNotIn("relative", english)
        solidarity = models["eo/tache-3/education-p6"]
        rows = data["groups"][solidarity.group]
        for french, wording in (
            (
                "Une aide décidée sans les consulter peut être mal adaptée. Un échange direct permet de préciser un problème ; un message aux proches permet aussi de les rassurer.",
                "a message to loved ones",
            ),
            (
                "L'aide correspond mieux à sa situation, et ses proches savent ce qui se passe.",
                "their loved ones know",
            ),
        ):
            with self.subTest(historical_french=french):
                row = rows[fingerprint(french)]
                self.assertEqual(row["french"], french)
                self.assertIn(wording, row["english"])
                self.assertNotIn("relative", row["english"])
        historical_example = (
            "Une personne hébergée temporairement écrit à un référent qu'elle ne peut pas transporter un colis lourd. "
            "Ils conviennent d'une livraison. Elle peut ensuite envoyer un message à sa famille pour dire qu'elle est en sécurité et reçoit de l'aide."
        )
        example = rows[fingerprint(historical_example)]["english"]
        self.assertIn("message their family", example)

    def test_living_with_parents_english_keeps_adult_freedom_and_reciprocal_consideration(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p16"]
        row = data["groups"][model.group][fingerprint(model.response.arguments[2].exemple)]
        self.assertIn("woman tells her parents she'll be home late", row["english"])
        self.assertIn("doesn't need their permission to go out", row["english"])
        self.assertIn("comes in quietly so she doesn't wake them", row["english"])
        self.assertNotIn("nights out", row["english"])
        development = data["groups"][model.group][
            fingerprint(model.response.arguments[2].developpement)
        ]["english"]
        self.assertIn("Schedules, visitors and private spaces need to be discussed", development)
        self.assertIn("Without this balance", development)
        self.assertIn("can come with constant tension", development)
        example = data["groups"][model.group][
            fingerprint(model.response.arguments[0].exemple)
        ]["english"]
        self.assertIn("With his parents' agreement", example)
        self.assertIn("three hundred euros a month", example)
        self.assertIn("nine hundred euros a month, before bills", example)
        nuance = data["groups"][model.group][fingerprint(model.response.nuance)]["english"]
        self.assertIn("requires the parents' agreement and enough space", nuance)
        self.assertIn("If these conditions are not met", nuance)
        self.assertIn("do not necessarily make up for the tensions", nuance)
        self.assertIn("does not require moving out by a specific date", nuance)

    def test_family_language_english_distinguishes_direct_family_contact_and_parent_expression(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p13"]
        rows = data["groups"][model.group]
        self.assertEqual(model.argument_ids, (1, 2, 3))
        expression, contact, _ = model.response.arguments
        development = rows[fingerprint(contact.developpement)]["english"]
        self.assertIn("do not necessarily speak the host country's language", development)
        self.assertIn("If every conversation requires translation", development)
        example = rows[fingerprint(contact.exemple)]["english"]
        self.assertIn("Her grandson understands her language", example)
        self.assertIn("asks his own questions without waiting for his mother", example)
        development = rows[fingerprint(expression.developpement)]["english"]
        self.assertIn("a language they are still learning", development)
        self.assertIn("may lack the words to explain an emotion", development)
        self.assertIn("ask questions and offer reassurance", development)
        self.assertIn("beyond simply giving instructions", development)
        example = rows[fingerprint(expression.exemple)]["english"]
        self.assertIn("classmates refused to play with him", example)
        self.assertIn("His mother speaks to him in their language", example)
        self.assertIn("listens to the details", example)
        self.assertNotIn("fluent", example)
        result = rows[fingerprint(expression.consequence)]["english"]
        self.assertIn("understands better why he is hurt", result)
        self.assertIn("can reassure him without having to search for the right words", result)

    def test_living_alone_english_connects_actual_help_needs_and_household_workload(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p11"]
        fields = public_fields(model)
        for field, required, forbidden in (
            (
                "argument-4-developpement",
                ("If a health problem prevents you", "asking someone close to you when they can come", "scheduling deliveries"),
                ("without relying on someone already being at home",),
            ),
            (
                "nuance",
                ("shopping, cooking and cleaning for everyone", "For that person", "less work day to day"),
                ("rich social life",),
            ),
            (
                "conclusion",
                ("can cost more and require more planning", "costs and chores are genuinely shared"),
                (),
            ),
        ):
            with self.subTest(field=field):
                english = data["groups"][model.group][fingerprint(fields[field])]["english"]
                for phrase in required:
                    self.assertIn(phrase, english)
                for phrase in forbidden:
                    self.assertNotIn(phrase, english)
        cue = catalogue.tache_three_subject_hints()[model.group].nuance
        self.assertIn("Pour la personne qui fait toutes les tâches du foyer", cue.french)
        self.assertIn("For the person doing all the household chores", cue.english)
        self.assertNotIn("social", cue.french)
        self.assertNotIn("social", cue.english)

    def test_living_alone_english_keeps_rest_broader_than_going_to_bed(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p11"]
        row = data["groups"][model.group][fingerprint(model.response.arguments[0].exemple)]
        self.assertIn("nurse comes home after a night shift", row["english"])
        self.assertIn("sleeps in her quiet flat", row["english"])
        self.assertIn("does not have to adapt her rest", row["english"])
        self.assertIn("other people's morning preparations for school or work", row["english"])
        self.assertNotIn("go to bed", row["english"])
        result = data["groups"][model.group][
            fingerprint(model.response.arguments[0].consequence)
        ]["english"]
        self.assertIn("makes it easier for her to rest", result)
        self.assertNotIn("bedtime", result)
        costs = data["groups"][model.group][
            fingerprint(model.response.arguments[1].developpement)
        ]["english"]
        self.assertIn("Some costs do not go down when you live alone", costs)
        self.assertIn("can cost the same for one person as for two", costs)
        self.assertNotIn("divide every bill", costs)
        example = data["groups"][model.group][
            fingerprint(model.response.arguments[1].exemple)
        ]["english"]
        self.assertIn("forty euros a month: each pays twenty euros", example)
        self.assertIn("separate homes", example)
        self.assertIn("each takes out the same forty-euro subscription", example)

    def test_family_work_english_identifies_sibling_coworkers_before_family_spillover(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p7"]
        development = data["groups"][model.group][
            fingerprint(model.response.arguments[0].developpement)
        ]["english"]
        self.assertIn("reacts under pressure", development)
        self.assertIn("according to each person's skills", development)
        self.assertNotIn("grown up", development)
        shared_work = data["groups"][model.group][
            fingerprint(model.response.arguments[0].exemple)
        ]["english"]
        self.assertIn("sold bread together", shared_work)
        self.assertIn("One made the bread", shared_work)
        self.assertIn("other served customers and handled payments", shared_work)
        self.assertIn("arrangement worked well", shared_work)
        self.assertIn("same roles when they open a bakery", shared_work)
        example = data["groups"][model.group][
            fingerprint(model.response.arguments[1].exemple)
        ]["english"]
        self.assertIn("At the family's Sunday meal", example)
        self.assertIn("brother and sister work at the same restaurant", example)
        self.assertIn("in front of everyone", example)
        self.assertIn("repeatedly arriving late for work", example)
        self.assertIn("Their mother defends him", example)
        self.assertIn("turns into a three-way argument", example)
        result = data["groups"][model.group][
            fingerprint(model.response.arguments[1].consequence)
        ]["english"]
        self.assertIn("lateness is not resolved and the meal is spoilt", result)
        self.assertIn("would have been better", result)
        self.assertIn("discuss it privately at work", result)
        self.assertIn("rather than in front of the whole family", result)
        self.assertNotIn("meeting at the restaurant", result)
        self.assertNotIn("was resolved", result)
        promotion = data["groups"][model.group][
            fingerprint(model.response.arguments[2].exemple)
        ]["english"]
        self.assertIn("father appoints him because he is his son", promotion)
        self.assertIn("without considering a more experienced colleague's application", promotion)

    def test_grade_reward_english_keeps_progress_threshold_and_possible_discouragement(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p6"]
        example = data["groups"][model.group][
            fingerprint(model.response.arguments[1].exemple)
        ]["english"]
        self.assertIn("girl gets sixteen out of twenty without much revision", example)
        self.assertIn("brother improves from eight to twelve", example)
        self.assertIn("If payment starts at fifteen, only she is rewarded", example)
        consequence = data["groups"][model.group][
            fingerprint(model.response.arguments[1].consequence)
        ]["english"]
        self.assertIn("brother may become discouraged", consequence)
        self.assertIn("at precisely the moment when he needs recognition", consequence)
        self.assertNotIn("will become", consequence)

    def test_family_distance_english_keeps_local_contacts_and_unexpected_problems_proportionate(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p5"]
        rows = data["groups"][model.group]
        development = rows[fingerprint(model.response.arguments[1].developpement)]["english"]
        self.assertIn("cannot always help in practical ways", development)
        self.assertIn("know who to call when something unexpected happens", development)
        self.assertNotIn("emergency", development)
        example = rows[fingerprint(model.response.arguments[1].exemple)]["english"]
        self.assertIn("parent finishes work too late to collect his child", example)
        self.assertIn("Before moving, he relied on the grandparents", example)
        self.assertIn("may then need to call", example)
        self.assertIn("trusted neighbour", example)
        self.assertIn("already authorised with the school to collect the child", example)
        result = rows[fingerprint(model.response.arguments[1].consequence)]["english"]
        self.assertIn("If she is unavailable", result)
        self.assertIn("asking to leave work early", result)
        self.assertNotIn("She collects the child", result)
        self.assertNotIn("emergency", result)

    def test_family_distance_english_keeps_work_time_and_travel_budget_explicit(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p5"]
        example = data["groups"][model.group][
            fingerprint(model.response.arguments[2].exemple)
        ]["english"]
        self.assertIn("lives and works", example)
        self.assertIn("eight-hour train journey", example)
        self.assertIn("two days off work", example)
        self.assertIn("cannot afford the train ticket", example)
        self.assertIn("decides not to make the trip", example)

    def test_personal_advice_english_distinguishes_outdated_methods_and_different_priorities(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p3"]
        rows = data["groups"][model.group]
        development = rows[fingerprint(model.response.arguments[1].developpement)]["english"]
        self.assertIn("may be well intentioned but based on outdated assumptions", development)
        example = rows[fingerprint(model.response.arguments[1].exemple)]["english"]
        self.assertIn("grandfather advises handing in a CV in person", example)
        self.assertIn("granddaughter checks the procedure", example)
        self.assertIn("only accepts an online application", example)
        self.assertIn("She therefore submits hers that way", example)
        result = rows[fingerprint(model.response.arguments[1].consequence)]["english"]
        self.assertIn("keeps the idea of taking the initiative", result)
        self.assertIn("would have left her application unprocessed", result)
        example = rows[fingerprint(model.response.arguments[2].exemple)]["english"]
        self.assertIn("grandmother recommends a stable job", example)
        self.assertIn("job offer abroad in the field she studied", example)
        self.assertIn("discuss the risks", example)
        self.assertIn("start working in her chosen field", example)
        priorities = rows[fingerprint(model.response.arguments[2].developpement)]
        self.assertIn("recommending what they themselves would choose", priorities["english"])
        self.assertNotIn("the choice they made themselves", priorities["english"])
        self.assertIn("the choice they made themselves", priorities["review_note"])

    def test_teen_social_media_english_keeps_sleep_help_seeking_and_private_messages_distinct(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p1"]
        rows = data["groups"][model.group]
        self.assertEqual(model.argument_ids, (5, 2, 3))
        introduction = rows[fingerprint(model.response.position_claire)]["english"]
        self.assertTrue(introduction.startswith("In my opinion, parents can let their children"))
        self.assertIn("which information to keep private", introduction)
        self.assertIn("how to respond to a worrying message", introduction)
        example = rows[fingerprint(model.response.arguments[1].exemple)]["english"]
        self.assertIn("group chat until midnight even though he has school the next day", example)
        self.assertIn("decides to leave his phone in the living room overnight", example)
        cue = catalogue.tache_three_subject_hints()[model.group].arguments[1].example.english
        self.assertIn("no longer stays up replying", cue)
        self.assertIn("until midnight", cue)
        result = rows[fingerprint(model.response.arguments[1].consequence)]["english"]
        self.assertIn("sleep without being woken by their messages", result)
        development = rows[fingerprint(model.response.arguments[2].developpement)]["english"]
        self.assertIn("If the child thinks their phone will immediately be confiscated", development)
        self.assertIn("they may keep quiet", development)
        self.assertIn("you will work out what to do together", development)
        example = rows[fingerprint(model.response.arguments[2].exemple)]["english"]
        self.assertIn("stranger asks a child for a photo", example)
        self.assertIn("shows the message to his father", example)
        self.assertIn("keep evidence, then block and report the account", example)
        nuance = rows[fingerprint(model.response.nuance)]["english"]
        self.assertIn("does not mean reading all their messages", nuance)
        self.assertIn("more freedom when they follow the rules", nuance)
        conclusion = rows[fingerprint(model.response.conclusion)]["english"]
        self.assertIn("gradual access, with explained rules", conclusion)
        self.assertIn("learn to protect themselves", conclusion)
        self.assertIn("more independently", conclusion)

    def test_family_friendship_english_keeps_affection_confidences_and_earned_trust_distinct(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p10"]
        rows = data["groups"][model.group]
        idea = rows[fingerprint(model.response.arguments[0].idea)]["english"]
        self.assertIn("family affection does not guarantee", idea)
        self.assertIn("things in common", idea)
        development = rows[fingerprint(model.response.arguments[0].developpement)]["english"]
        self.assertIn("companionship you naturally seek", development)
        self.assertIn("sense of humour or interests", development)
        self.assertIn("make conversation more natural", development)
        self.assertIn("does not depend on being related", development)
        self.assertNotIn("must", development)
        self.assertNotIn("confide", development)
        example = rows[fingerprint(model.response.arguments[0].exemple)]["english"]
        self.assertIn("enjoys meals with their brother", example)
        self.assertIn("every week with a friend", example)
        self.assertIn("laugh and talk with for hours", example)
        self.assertIn("seek out this friend's company because they enjoy it", example)
        result = rows[fingerprint(model.response.arguments[0].consequence)]["english"]
        self.assertIn("love their brother, but feel more in tune with this friend", result)
        self.assertIn("Both relationships matter without offering exactly the same thing", result)
        self.assertNotIn("confidant", result)
        next_idea = rows[fingerprint(model.response.arguments[1].idea)]["english"]
        self.assertIn("Family roles can also limit what we dare to share", next_idea)
        self.assertNotIn("This reserve", next_idea)
        development = rows[fingerprint(model.response.arguments[2].developpement)]["english"]
        self.assertTrue(development.startswith("Friendship requires being able to listen"))
        self.assertNotIn("We must", development)
        example = rows[fingerprint(model.response.arguments[2].exemple)]["english"]
        self.assertIn("Two cousins grew up together", example)
        self.assertIn("went to the same school", example)
        self.assertIn("listened to and supported each other", example)
        result = rows[fingerprint(model.response.arguments[2].consequence)]["english"]
        self.assertIn("not just from being related", result)
        nuance = rows[fingerprint(model.response.nuance)]["english"]
        self.assertIn("if everyone feels free within it", nuance)
        self.assertIn("no one should feel guilty", nuance)
        self.assertIn("even when they love their relatives deeply", nuance)

    def test_friendship_help_english_keeps_transport_unspecified_and_other_benefits_distinct(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p9"]
        rows = data["groups"][model.group]
        help_, growth, community = model.response.arguments
        development = rows[fingerprint(help_.developpement)]["english"]
        self.assertIn("Family do not always live nearby", development)
        self.assertIn("paid services are not always accessible", development)
        self.assertIn("return the favour", development)
        self.assertNotIn("driving", development)
        example = rows[fingerprint(help_.exemple)]["english"]
        self.assertIn("follow-up appointment at the hospital", example)
        self.assertIn("accompanies them to the relevant department", example)
        self.assertIn("takes them back home", example)
        self.assertNotIn("drives", example)
        result = rows[fingerprint(help_.consequence)]["english"]
        self.assertTrue(result.startswith("The person"))
        self.assertIn("without having to manage a difficult journey alone", result)
        community_example = rows[fingerprint(community.exemple)]["english"]
        self.assertIn("retired man with no friends", community_example)
        self.assertIn("walking club", community_example)
        self.assertIn("Every Tuesday, he talks to the same people", community_example)
        self.assertIn("without socialising with them outside the outings", community_example)
        community_result = rows[fingerprint(community.consequence)]["english"]
        self.assertIn("activity and regular conversations", community_result)
        self.assertIn("takes part in local life without having formed any friendships", community_result)
        self.assertNotIn("close friends", community_result)
        growth_text = rows[fingerprint(growth.developpement)]["english"]
        self.assertIn("hesitate to start an activity because we lack confidence", growth_text)
        self.assertIn("encourage us when we doubt ourselves", growth_text)
        self.assertIn("does not do the work for us, but helps us persevere", growth_text)
        growth_example = rows[fingerprint(growth.exemple)]["english"]
        self.assertIn("taster session with a choir", growth_example)
        self.assertIn("rehearsing every week", growth_example)
        self.assertIn("her first concert", growth_example)
        self.assertIn("might have left unexplored", rows[fingerprint(growth.consequence)]["english"])

    def test_shared_friendship_english_keeps_support_family_confidant_and_personal_satisfaction_distinct(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p16"]
        rows = data["groups"][model.group]
        self.assertEqual(model.argument_ids, (1, 4, 5))
        self.assertEqual({key for key, _ in model.source_prompts}, {"culture:p16", "famille:p8"})
        example = rows[fingerprint(model.response.arguments[0].exemple)]["english"]
        self.assertIn("turned down for a job", example)
        self.assertIn("one rejection does not sum up her abilities", example)
        self.assertIn("prepare for the next interview", example)
        example = rows[fingerprint(model.response.arguments[1].exemple)]["english"]
        self.assertIn("without a circle of friends calls their sister on Sundays", example)
        self.assertIn("listens without judging them", example)
        self.assertIn("hang up feeling relieved", example)
        example = rows[fingerprint(model.response.arguments[2].exemple)]["english"]
        self.assertIn("learns the piano at home", example)
        self.assertIn("After several weeks", example)
        self.assertIn("from beginning to end", example)
        self.assertIn("with enjoyment, proud of their progress", example)
        self.assertNotIn("no friends", example)
        development = rows[fingerprint(model.response.arguments[2].developpement)]["english"]
        self.assertIn("pleasure and pride", development)
        self.assertIn("can exist without having friends", development)
        self.assertIn("what we have managed to do", development)
        result = rows[fingerprint(model.response.arguments[2].consequence)]["english"]
        self.assertIn("does not replace affection", result)
        self.assertIn("source of joy they build for themselves", result)
        nuance = rows[fingerprint(model.response.nuance)]["english"]
        self.assertIn("choosing not to have friends is not the same as suffering from loneliness", nuance)
        self.assertIn("If someone feels this absence", nuance)
        self.assertIn("can really improve their life", nuance)
        self.assertNotIn("will", nuance)

    def test_child_language_english_connects_regular_practice_to_understanding_and_confidence(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p13"]
        rows = data["groups"][model.group]
        row = rows[fingerprint(model.response.arguments[2].exemple)]
        self.assertIn("do not yet speak the local language well", row["english"])
        self.assertIn("enrol their child in a football club", row["english"])
        self.assertIn("As the training sessions go on", row["english"])
        self.assertIn("understands the coach's instructions better", row["english"])
        self.assertIn("feels more confident talking to their teammates", row["english"])
        self.assertNotIn("in class", row["english"])
        self.assertNotIn("fluently", row["english"])
        development = rows[fingerprint(model.response.arguments[2].developpement)]["english"]
        self.assertIn("Outside lessons", development)
        self.assertIn("opportunities to listen and respond", development)
        self.assertIn("Parents can arrange these even if they still speak little", development)
        self.assertIn("same words and people again", development)
        result = rows[fingerprint(model.response.arguments[2].consequence)]["english"]
        self.assertIn("takes part in the game more easily", result)
        self.assertIn("gains confidence in speaking", result)
        self.assertIn("without their parents having to teach them everything", result)
        nuance = rows[fingerprint(model.response.nuance)]["english"]
        self.assertIn("no obligation to reserve one language for home and the other for school", nuance)
        self.assertIn("read a story in the country's language at home", nuance)
        self.assertIn("speak the family language during a walk", nuance)
        self.assertIn("not keeping them separate at all costs", nuance)
        cue = catalogue.tache_three_subject_hints()[model.group].nuance
        self.assertIn("Pas de séparation stricte", cue.french)
        self.assertIn("No strict separation", cue.english)
        self.assertIn("local language at home", cue.english)
        self.assertIn("family language on a walk", cue.english)

    def test_rewritten_family_english_keeps_contribution_honesty_rules_and_household_agreements(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        cases = (
            ("famille-p2", "argument-1-exemple", ("twenty-six-year-old woman", "having dinner with her parents", "organises her own outings"), ("asks permission",)),
            ("famille-p2", "argument-1-developpement", ("can reflect a good relationship", "making your own decisions"), ("always",)),
            ("famille-p2", "argument-1-consequence", ("without giving up her adult life",), ()),
            ("famille-p2", "argument-3-developpement", ("each side brings something to the other", "take some chores off their parents' hands"), ()),
            ("famille-p2", "nuance", ("Housing costs can also play a part", "living separately may be preferable", "No single age for leaving home"), ()),
            ("famille-p2", "argument-4-developpement", ("need for privacy", "may feel very comfortable without noticing", "before small irritations become arguments"), ()),
            ("famille-p2", "argument-3-exemple", ("contributes to household expenses every month", "does the week's shopping", "do not have to remind him"), ()),
            ("famille-p3", "argument-1-exemple", ("grandfather had left his job", "check whether her savings would cover the course fees before resigning"), ()),
            ("famille-p4", "argument-1-developpement", ("false promise", "may trust their parents less", "know what to expect"), ("next explanation",)),
            ("famille-p4", "argument-1-exemple", ("Before a vaccination", "a little prick", "better than promising they will not feel anything"), ()),
            ("famille-p4", "argument-2-exemple", ("grandmother on Wednesdays", "in hospital after a fall", "without promising that she will recover straight away"), ()),
            ("famille-p4", "argument-3-developpement", ("recognise their effort", "exactly what they can improve", "how to go about it"), ("A child can hear", "judgement of their worth")),
            ("famille-p4", "argument-3-consequence", ("more confidently at the audition", "something to improve", "rather than a compliment with no guidance"), ()),
            ("famille-p4", "nuance", ("adult matter", "acknowledge that you do not know something yet", "does not require lying"), ("guarantee",)),
            ("famille-p6", "nuance", ("a family outing or a book we choose together", "without promising a reward for every grade", "automatic payment"), ()),
            ("famille-p7", "nuance", ("discuss a work problem with your relative", "better to avoid working together"), ("no one dares say no",)),
            ("famille-p12", "introduction", ("set clear rules", "not make children obey out of fear", "while still setting limits"), ("distinguish between", "being authoritarian")),
            ("famille-p12", "argument-1-exemple", ("baby is having a nap", "seven-year-old boy", "siren on his toy truck", "His father tells him", "without the siren"), ("drawing in another room",)),
            ("famille-p12", "argument-1-consequence", ("without using the siren", "letting the baby sleep"), ("continues his activity",)),
            ("famille-p12", "argument-2-exemple", ("damaged a library book", "listens without shouting", "how to replace the book"), ()),
            ("famille-p12", "argument-2-consequence", ("putting their mistake right instead of hiding it", "has not removed their responsibility"), ()),
            ("famille-p12", "argument-3-developpement", ("what needs to be done", "suggest how to do it", "follow through on what they have agreed to do"), ("exercises their judgement", "Firmness therefore")),
            ("famille-p12", "argument-3-exemple", ("homework at 5 pm", "on condition that it is finished before dinner", "without her having to remind him"), ()),
            ("famille-p12", "nuance", ("intervene immediately", "even if it means explaining afterwards", "must not prevent the parent ensuring the child's safety"), ()),
            ("famille-p14", "argument-2-exemple", ("sort laundry", "choose the wash programme", "several loads under the parent's supervision", "washes his clothes without needing help"), ("without waiting for someone",)),
            ("famille-p14", "argument-1-exemple", ("One prepares dinner and the other lays the table", "After the meal, the second parent does the washing-up", "Once the kitchen is tidy, both can rest"), ()),
            ("famille-p14", "argument-4-exemple", ("A father often has to remind his teenage son", "They then agree", "except on evenings when he has sports practice", "his father takes over"), ()),
            ("famille-p14", "argument-4-consequence", ("father has less need to remind his son", "fewer arguments between them"), ("other person", "check every step")),
            ("famille-p14", "nuance", ("someone who is ill can be excused", "what everyone can actually do"), ("equally",)),
        )
        for name, field, required, forbidden in cases:
            with self.subTest(model=name, field=field):
                group = f"eo/tache-3/{name}"
                french = public_fields(scoped_models()[group])[field]
                english = data["groups"][group][fingerprint(french)]["english"]
                for phrase in required:
                    self.assertIn(phrase, english)
                for phrase in forbidden:
                    self.assertNotIn(phrase, english)

    def test_shared_family_letter_result_states_the_readers_gain(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        expected = "Reading this helps the young woman to gain a better understanding of her grandmother’s early days abroad."
        for group in ("eo/tache-3/culture-p18", "eo/tache-3/technologie-p12"):
            result = scoped_models()[group].response.arguments[2].consequence
            row = data["groups"][group][fingerprint(result)]
            self.assertEqual(row["english"], expected)
            self.assertIn("à la jeune femme", row["french"])
            self.assertIn("sa grand-mère à l'étranger", row["french"])

    def test_solo_travel_english_keeps_information_seeking_distinct_from_the_travellers_decision(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        solo = scoped_models()["eo/tache-3/culture-p21"]
        rows = data["groups"][solo.group]
        argument = solo.response.arguments[0]
        development = rows[fingerprint(argument.developpement)]["english"]
        self.assertIn("We can ask for information", development)
        self.assertIn("compare the options and choose", development)
        self.assertNotIn("you should", development)
        example = rows[fingerprint(argument.exemple)]["english"]
        self.assertIn("train has been cancelled", example)
        self.assertLess(example.index("member of staff"), example.index("choose the bus"))
        self.assertIn("before their hotel", example)
        self.assertIn("reception closes", example)
        self.assertIn("let the hotel know", example)
        result = rows[fingerprint(argument.consequence)]["english"]
        self.assertIn("arrives at the hotel", result)
        self.assertIn("may feel more capable", result)

    def test_reading_alternatives_english_links_listening_to_local_historical_knowledge(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p20"]
        rows = data["groups"][model.group]
        argument = model.response.arguments[1]
        development = rows[fingerprint(argument.developpement)]["english"]
        self.assertIn("residents share their stories", development)
        self.assertIn("how they lived", development)
        example = rows[fingerprint(argument.exemple)]["english"]
        self.assertIn("former factory worker", example)
        self.assertIn("so they could walk to work", example)
        self.assertIn("why the neighbourhood developed around that factory", example)
        consequence = rows[fingerprint(argument.consequence)]["english"]
        self.assertIn("broadens your cultural knowledge", consequence)
        self.assertIn("even if you have not read a book", consequence)
        nuance = rows[fingerprint(model.response.nuance)]["english"]
        self.assertIn("complement a podcast or a workshop", nuance)

    def test_requested_book_english_keeps_learning_practice_and_the_characters_choice(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        book = scoped_models()["eo/tache-3/culture-p6"]
        rows = data["groups"][book.group]
        self.assertEqual({key for key, _ in book.source_prompts}, {"culture:p6", "education:p8"})
        development = rows[fingerprint(book.response.arguments[1].developpement)]["english"]
        self.assertIn("explains a method", development)
        self.assertIn("spot your mistakes", development)
        self.assertIn("reread the explanation and try again", development)
        example = rows[fingerprint(book.response.arguments[1].exemple)]["english"]
        self.assertIn("four equal parts", example)
        self.assertIn("two quarters make a half", example)
        self.assertIn("do exercises and check their answers against the answer key", example)
        story = rows[fingerprint(book.response.arguments[2].exemple)]
        self.assertIn("their sick mother's side despite the danger", story["english"])
        self.assertIn("why leaving is not a simple decision", story["english"])
        self.assertTrue(story["deepl_english"])
        self.assertTrue(story["review_note"])
        nuance = rows[fingerprint(book.response.nuance)]["english"]
        self.assertIn("A book can also be read on a screen", nuance)
        self.assertIn("combine these different resources", nuance)


class EO3ResponseLanguageViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("eo3-language-view")
        provision_user_study_data(cls.user)

    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "responses.en.json"
        self.enterContext(override_settings(
            EO3_RESPONSE_TRANSLATIONS_PATH=self.path, DEEPL_TARGET_LANG="EN-GB",
        ))
        self.path.write_text(json.dumps(fixture_manifest(), ensure_ascii=False))
        self.client.force_login(self.user)

    def prompt(self, key="culture:p30"):
        return Prompt.objects.select_related(
            "response__theme__task__part", "theme__task__part", "family",
        ).get(content_key=key)

    def test_all_262_canonical_french_layouts_remain_byte_exact_with_english_prepared(self):
        import hashlib

        expected = json.loads(Path(__file__).with_name("eo3_response_language_anchors.json").read_text())
        for group, model in scoped_models().items():
            prompt = self.prompt(model.source_prompts[0][0])
            for surface in ("detail", "back"):
                rendered = render_current_response(prompt, model.response, surface, self.user)
                self.assertEqual(
                    hashlib.sha256(rendered.text).hexdigest(), expected[group][surface],
                    f"Canonical French changed for {group}/{surface}",
                )
                self.assertEqual(len(rendered.response_fields), 15)

    def test_detail_has_global_argument_and_subsection_controls_without_paid_calls(self):
        prompt = self.prompt()
        with patch("study.translation.urllib.request.urlopen") as provider:
            page = self.client.get(prompt_detail_url(prompt))
        provider.assert_not_called()
        self.assertContains(page, 'data-eo3-language-ready="true"')
        self.assertContains(page, 'data-eo3-language-total="15"')
        self.assertContains(page, 'data-eo3-argument-toggle=', count=3)
        self.assertContains(page, 'data-eo3-section-toggle=', count=12)
        self.assertContains(page, 'data-eo3-french=', count=15)
        self.assertContains(page, 'data-eo3-english=', count=15)
        self.assertEqual(page.context["response_content"], scoped_models()[prompt.response.semantic_group].response)

    def test_private_field_gets_no_unmatched_english_and_other_exact_public_fields_remain_available(self):
        prompt = self.prompt()
        model = scoped_models()[prompt.response.semantic_group].response
        fields = asdict(model)
        fields.pop("is_personal")
        fields["arguments"] = list(fields["arguments"])
        fields["position_claire"] = "Un texte personnel qui ne figure dans aucun modèle public."
        PersonalResponse.objects.create(
            user=self.user, response=prompt.response, source_prompt=prompt, **fields,
        )
        with patch("study.translation.urllib.request.urlopen") as provider:
            page = self.client.get(prompt_detail_url(prompt))
        provider.assert_not_called()
        presentation = page.context["eo3_language"]
        self.assertFalse(presentation["ready"])
        self.assertEqual(presentation["available"], 14)
        self.assertEqual(presentation["fields"]["introduction"], "")
        self.assertContains(page, fields["position_claire"])
        self.assertContains(page, 'data-eo3-english=', count=14)
        self.assertIn(fields["position_claire"], page.context["eo3_response_copy_text"])

    def test_normal_practice_keeps_bilingual_pistes_instead_of_reintroducing_the_full_response(self):
        prompt = self.prompt()
        card = Card.objects.get(
            user=self.user, response=prompt.response, card_type=CardType.SPINE,
        )
        payload = card_payload(card, prompt=prompt)
        rendered = render_to_string("study/partials/card_back.html", payload)
        self.assertIn("subject-hints--speaking", rendered)
        self.assertNotIn("data-eo3-language", rendered)
        self.assertNotIn("data-response-field", rendered)
        self.assertEqual(payload["eo3_pistes"], catalogue.tache_three_subject_plan(prompt.response.semantic_group))

    def test_empty_and_corrupt_catalogues_explain_unavailability_without_changing_french(self):
        prompt = self.prompt()
        self.path.write_text(json.dumps(empty_manifest()))
        page = self.client.get(prompt_detail_url(prompt))
        self.assertFalse(page.context["eo3_language"]["ready"])
        self.assertContains(page, 'data-eo3-english=', count=0)
        self.path.write_text("{")
        with self.assertLogs("study.eo3_response_languages", level="ERROR"):
            page = self.client.get(prompt_detail_url(prompt))
        self.assertTrue(page.context["eo3_language"]["error"])
        self.assertContains(page, 'data-eo3-language-error="true"')
