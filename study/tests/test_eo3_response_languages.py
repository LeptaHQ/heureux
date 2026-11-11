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

from study.expression.eo.tache_3.languages import (
    DEFAULT_PATH, empty_manifest, fingerprint, language_presentation, manifest, public_fields,
    scoped_models, validate_manifest, read_manifest,
)
from study.catalogue import registry as catalogue
from study.accounts.services import provision_user_study_data
from study.review.presentation import card_payload
from study.models import Card, CardType, PersonalResponse, Prompt
from study.expression.eo.annotations import render_current_response
from study.navigation.routing import prompt_detail_url

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
        with patch("study.translations.service.urllib.request.urlopen") as provider:
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
        with patch("study.translations.service.urllib.request.urlopen") as provider:
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
        with self.assertLogs("study.expression.eo.tache_3.languages", level="ERROR"):
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
        data = read_manifest(DEFAULT_PATH)
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
        self.assertIn("tone, gestures and cultural references", row["english"])
        self.assertIn("every word without getting a joke", row["english"])
        row = data["groups"][country.group][fingerprint(country.response.arguments[1].exemple)]
        self.assertIn("subtitled in French", row["english"])
        self.assertIn("Netherlands", row["english"])
        self.assertIn("land to be reclaimed from the sea", row["english"])
        self.assertIn("dikes and pumps", row["english"])
        row = data["groups"][country.group][fingerprint(country.response.arguments[0].exemple)]
        self.assertIn("in Tokyo", row["english"])
        self.assertIn("passengers speaking quietly and avoiding phone calls", row["english"])
        row = data["groups"][country.group][fingerprint(country.response.arguments[0].consequence)]
        self.assertIn("keep the noise down on public transport", row["english"])
        cuisine = scoped_models()["eo/tache-3/culture-p15"]
        row = data["groups"][cuisine.group][fingerprint(cuisine.response.arguments[0].exemple)]
        self.assertIn("one large dish", row["english"])
        self.assertIn("Their hosts would explain", row["english"])
        self.assertIn("this evening meal", row["english"])
        self.assertIn("talk after work", row["english"])
        row = data["groups"][cuisine.group][fingerprint(cuisine.response.arguments[0].consequence)]
        self.assertTrue(row["english"].startswith("The visitor"))
        self.assertIn("this family keeps time together", row["english"])
        self.assertIn("without assuming all families", row["english"])
        row = data["groups"][cuisine.group][fingerprint(cuisine.response.nuance)]
        self.assertIn("it does not show all its culture", row["english"])
        self.assertIn("political debates or the language", row["english"])
        self.assertNotIn("must also explore the language", row["english"])
        row = data["groups"][cuisine.group][fingerprint(cuisine.response.arguments[0].developpement)]
        self.assertIn("When people eat", row["english"])
        self.assertIn("how everyday life is organised", row["english"])
        self.assertIn("what these habits mean to our hosts", row["english"])
        row = data["groups"][cuisine.group][fingerprint(cuisine.response.arguments[1].developpement)]
        self.assertIn("Ingredients and preparation methods", row["english"])
        self.assertIn("preserving food without a refrigerator", row["english"])
        row = data["groups"][cuisine.group][fingerprint(cuisine.response.arguments[1].exemple)]
        self.assertIn("This method preserved fish, particularly during long sea voyages", row["english"])
        self.assertIn("constraints of seafaring", row["english"])
        older = scoped_models()["eo/tache-3/culture-p8"]
        row = data["groups"][older.group][fingerprint(older.response.arguments[0].exemple)]
        self.assertIn("arguing with their parents", row["english"])
        self.assertIn("disagreement between generations", row["english"])
        row = data["groups"][older.group][fingerprint(older.response.arguments[1].exemple)]
        self.assertIn("clips of the same school fight", row["english"])
        self.assertIn("violence is common among young people", row["english"])
        self.assertNotIn("violence is rife", row["english"])

    def test_adults_recalling_their_own_behaviour_corrects_the_comparison_in_both_languages(self):
        data = read_manifest(DEFAULT_PATH)
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
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        models = scoped_models()
        quebec = models["eo/tache-3/education-p5"]
        rows = data["groups"][quebec.group]
        questions = (
            "is my French good enough to live and work in Quebec?",
            "is my profession recognised and in demand in Quebec?",
            "do I have the money and support I need to settle there?",
        )
        for argument, question in zip(quebec.response.arguments, questions):
            self.assertIn(question, rows[fingerprint(argument.idea)]["english"])
        self.assertIn("I would ask myself three questions", rows[
            fingerprint(quebec.response.position_claire)
        ]["english"])
        qualification = rows[fingerprint(quebec.response.arguments[1].exemple)]["english"]
        self.assertIn("may need to have her training recognised", qualification)
        self.assertIn("rather than count on being able to start work immediately", qualification)
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
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        models = scoped_models()
        phone = models["eo/tache-3/education-p15"]
        rows = data["groups"][phone.group]
        introduction = rows[fingerprint(phone.response.position_claire)]["english"]
        self.assertIn("find accurate information, but do not guarantee it", introduction)
        example = rows[fingerprint(phone.response.arguments[1].exemple)]["english"]
        self.assertIn("all quote the same unsourced message", example)
        development = rows[fingerprint(phone.response.arguments[2].developpement)]["english"]
        self.assertIn("compare independent sources rather than count repetitions", development)
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
        data = read_manifest(DEFAULT_PATH)
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
        data = read_manifest(DEFAULT_PATH)
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
        data = read_manifest(DEFAULT_PATH)
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
        data = read_manifest(DEFAULT_PATH)
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
        data = read_manifest(DEFAULT_PATH)
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
        data = read_manifest(DEFAULT_PATH)
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
        data = read_manifest(DEFAULT_PATH)
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
                ("After buying them, the teenager notices",),
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
        data = read_manifest(DEFAULT_PATH)
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
                digest = (
                    "f5fe4cdbc4a8ea73f66e372862de1a2e5dd148964c80d6efe97ad58b22650b1d"
                    if name == "culture-p31" else fingerprint(french)
                )
                row = data["groups"][group][digest]
                self.assertIn(current, row["english"])
                self.assertNotIn(previous, row["english"])
                preceding = row["editorial_history"][-1]
                self.assertEqual(preceding["french"], row["french"])
                self.assertIn(previous, preceding["english"])
                self.assertEqual(row.get("deepl_english"), preceding.get("deepl_english"))
                self.assertIn("editorial_history", row["review_note"])

    def test_education_english_matches_speaking_feedback_to_progress_under_fresh_ids(self):
        data = read_manifest(DEFAULT_PATH)
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
        data = read_manifest(DEFAULT_PATH)
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
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p16"]
        row = data["groups"][model.group][fingerprint(model.response.arguments[2].exemple)]
        self.assertIn("woman can tell her parents that she will be home late", row["english"])
        self.assertIn("without asking permission to go out", row["english"])
        self.assertIn("takes care not to wake them on returning", row["english"])
        self.assertNotIn("nights out", row["english"])
        development = data["groups"][model.group][
            fingerprint(model.response.arguments[2].developpement)
        ]["english"]
        self.assertIn("Discussing schedules, visitors and private spaces", development)
        self.assertIn("must respect household habits", development)
        self.assertIn("keep the ability to organise their life", development)
        example = data["groups"][model.group][
            fingerprint(model.response.arguments[0].exemple)
        ]["english"]
        self.assertIn("With his parents' agreement", example)
        self.assertIn("three hundred euros a month", example)
        self.assertIn("nine hundred euros before bills", example)
        nuance = data["groups"][model.group][fingerprint(model.response.nuance)]["english"]
        self.assertIn("requires the parents' agreement and enough space", nuance)
        self.assertIn("If tensions become constant", nuance)
        self.assertIn("savings are no longer enough to justify it", nuance)
        self.assertIn("does not require moving out by a particular date", nuance)

    def test_family_language_english_distinguishes_direct_family_contact_and_parent_expression(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p13"]
        rows = data["groups"][model.group]
        self.assertEqual(model.argument_ids, (1, 2, 3))
        expression, contact, _ = model.response.arguments
        development = rows[fingerprint(contact.developpement)]["english"]
        self.assertIn("do not necessarily speak the host country's language", development)
        self.assertIn("If every conversation depends on translation", development)
        example = rows[fingerprint(contact.exemple)]["english"]
        self.assertIn("Her grandson can ask where it was taken", example)
        self.assertIn("instead of waiting for his mother to translate every sentence", example)
        development = rows[fingerprint(expression.developpement)]["english"]
        self.assertIn("parents are still learning the country's language", development)
        self.assertIn("do not always find the words to explain an emotion", development)
        self.assertIn("the language they know best", development)
        self.assertIn("beyond everyday instructions and really listen", development)
        example = rows[fingerprint(expression.exemple)]["english"]
        self.assertIn("classmates refused to play with him", example)
        self.assertIn("In their shared language, his mother can ask what happened", example)
        self.assertIn("listen to the details and reassure him", example)
        self.assertNotIn("fluent", example)
        result = rows[fingerprint(expression.consequence)]["english"]
        self.assertIn("preserve a relationship", result)
        self.assertIn("discuss what matters", result)

    def test_living_alone_english_connects_actual_help_needs_and_household_workload(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p11"]
        fields = public_fields(model)
        for field, required, forbidden in (
            (
                "argument-4-developpement",
                ("If a health problem stops us shopping or preparing meals", "arranged with available relatives or suitable services"),
                ("without relying on someone already being at home",),
            ),
            (
                "nuance",
                ("shopping, cooking and cleaning for everyone", "living alone can instead make their everyday life easier"),
                ("rich social life",),
            ),
            (
                "conclusion",
                ("budget", "help available", "responsibilities would really be shared"),
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
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p11"]
        row = data["groups"][model.group][fingerprint(model.response.arguments[0].exemple)]
        self.assertIn("nurse returning from a night shift", row["english"])
        self.assertIn("can sleep in her quiet flat", row["english"])
        self.assertIn("without fitting her rest around", row["english"])
        self.assertIn("an entire family's morning preparations", row["english"])
        self.assertNotIn("go to bed", row["english"])
        result = data["groups"][model.group][
            fingerprint(model.response.arguments[0].consequence)
        ]["english"]
        self.assertIn("makes resting simpler", result)
        self.assertNotIn("bedtime", result)
        costs = data["groups"][model.group][
            fingerprint(model.response.arguments[1].developpement)
        ]["english"]
        self.assertIn("Not every cost falls because only one person uses the home", costs)
        self.assertIn("can cost the same for one person as for two", costs)
        self.assertNotIn("divide every bill", costs)
        example = data["groups"][model.group][
            fingerprint(model.response.arguments[1].exemple)
        ]["english"]
        self.assertIn("forty euros a month: each pays twenty euros", example)
        self.assertIn("separate homes", example)
        self.assertIn("each keep that subscription", example)
        self.assertIn("each pay forty euros for the same service", example)

    def test_family_work_english_identifies_sibling_coworkers_before_family_spillover(self):
        data = read_manifest(DEFAULT_PATH)
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

    def test_grade_reward_english_recognises_effort_without_requiring_the_top_mark(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p6"]
        example = data["groups"][model.group][
            fingerprint(model.response.arguments[1].exemple)
        ]["english"]
        self.assertIn("a pupil who struggles with maths", example)
        self.assertIn("after several weeks of regular, sustained study", example)
        self.assertIn("her parents praise her efforts and progress", example)
        self.assertIn("Even though her mark is still average", example)
        self.assertIn("rather than looking only at the result", example)
        consequence = data["groups"][model.group][
            fingerprint(model.response.arguments[1].consequence)
        ]["english"]
        self.assertIn("their efforts count", consequence)
        self.assertIn("can give them confidence to keep improving", consequence)
        self.assertNotIn("will give", consequence)

    def test_family_distance_english_keeps_local_contacts_and_unexpected_problems_proportionate(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p5"]
        rows = data["groups"][model.group]
        development = rows[fingerprint(model.response.arguments[1].developpement)]["english"]
        self.assertIn("cannot always help in practical ways", development)
        self.assertIn("know who to call when something unexpected happens", development)
        self.assertNotIn("emergency", development)
        example = rows[fingerprint(model.response.arguments[1].exemple)]["english"]
        self.assertIn("parent who relied on the grandparents", example)
        self.assertIn("collect their child from school when they finished work late", example)
        self.assertIn("Once they have moved far away", example)
        self.assertIn("find another trusted person or ask to leave work earlier", example)
        result = rows[fingerprint(model.response.arguments[1].consequence)]["english"]
        self.assertIn("require much more planning", result)
        self.assertNotIn("She collects the child", result)
        self.assertNotIn("emergency", result)

    def test_family_distance_english_keeps_work_time_and_travel_budget_explicit(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p5"]
        example = data["groups"][model.group][
            fingerprint(model.response.arguments[2].exemple)
        ]["english"]
        self.assertIn("woman who works", example)
        self.assertIn("eight-hour train journey", example)
        self.assertIn("two days off", example)
        self.assertIn("a ticket she cannot afford", example)
        self.assertIn("has to give up the visit", example)

    def test_personal_advice_english_distinguishes_outdated_methods_and_different_priorities(self):
        data = read_manifest(DEFAULT_PATH)
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
        data = read_manifest(DEFAULT_PATH)
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
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p10"]
        rows = data["groups"][model.group]
        idea = rows[fingerprint(model.response.arguments[0].idea)]["english"]
        self.assertIn("family affection is not always enough", idea)
        self.assertIn("a real rapport", idea)
        development = rows[fingerprint(model.response.arguments[0].developpement)]["english"]
        self.assertIn("friendship often develops", development)
        self.assertIn("sense of humour, interests", development)
        self.assertIn("Loving your brother", development)
        self.assertIn("Both relationships can matter without offering exactly the same thing", development)
        self.assertNotIn("must", development)
        self.assertNotIn("confide", development)
        example = rows[fingerprint(model.response.arguments[0].exemple)]["english"]
        self.assertIn("enjoy meals with their brother", example)
        self.assertIn("prefer meeting a friend", example)
        self.assertIn("discuss music or laugh for hours", example)
        self.assertIn("takes nothing away from their affection for their brother", example)
        result = rows[fingerprint(model.response.arguments[0].consequence)]["english"]
        self.assertIn("Family closeness and the rapport between friends", result)
        self.assertIn("do not necessarily amount to the same thing", result)
        self.assertNotIn("confidant", result)
        next_idea = rows[fingerprint(model.response.arguments[1].idea)]["english"]
        self.assertIn("do not always confide in family and friends in the same way", next_idea)
        self.assertNotIn("This reserve", next_idea)
        development = rows[fingerprint(model.response.arguments[2].developpement)]["english"]
        self.assertTrue(development.startswith("Friendship requires being able to listen"))
        self.assertNotIn("We must", development)
        example = rows[fingerprint(model.response.arguments[2].exemple)]["english"]
        self.assertIn("two cousins who grew up together", example)
        self.assertIn("attended the same school", example)
        self.assertIn("supported one another through difficulties", example)
        result = rows[fingerprint(model.response.arguments[2].consequence)]["english"]
        self.assertIn("without this being a rule for everyone", result)
        nuance = rows[fingerprint(model.response.nuance)]["english"]
        self.assertIn("great freedom to speak and a strong rapport", nuance)
        self.assertIn("we should not feel guilty", nuance)
        self.assertIn("even when we love our relatives deeply", nuance)

    def test_friendship_help_english_keeps_transport_unspecified_and_other_benefits_distinct(self):
        data = read_manifest(DEFAULT_PATH)
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
        data = read_manifest(DEFAULT_PATH)
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
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p13"]
        rows = data["groups"][model.group]
        row = rows[fingerprint(model.response.arguments[2].exemple)]
        self.assertIn("parents enrol their child in football", row["english"])
        self.assertIn("As training sessions go by", row["english"])
        self.assertIn("understands instructions better", row["english"])
        self.assertIn("dares to talk with his teammates", row["english"])
        self.assertIn("sees the same people and often hears the same expressions", row["english"])
        self.assertNotIn("in class", row["english"])
        self.assertNotIn("fluently", row["english"])
        development = rows[fingerprint(model.response.arguments[2].developpement)]["english"]
        self.assertIn("Outside lessons", development)
        self.assertIn("regular conversations help them gain confidence", development)
        self.assertIn("Parents can provide these opportunities even if they still speak little", development)
        self.assertIn("join an activity where they meet other children", development)
        result = rows[fingerprint(model.response.arguments[2].consequence)]["english"]
        self.assertIn("practises the language in a situation he enjoys", result)
        self.assertIn("without his parents having to teach him everything", result)
        nuance = rows[fingerprint(model.response.nuance)]["english"]
        self.assertIn("no need to separate the two languages strictly", nuance)
        self.assertIn("read a story in the country's language at home", nuance)
        self.assertIn("speak the family language on a walk", nuance)
        self.assertIn("creating opportunities to use both", nuance)
        cue = catalogue.tache_three_subject_hints()[model.group].nuance
        self.assertIn("Pas de séparation stricte", cue.french)
        self.assertIn("No strict separation", cue.english)
        self.assertIn("local language at home", cue.english)
        self.assertIn("family language on a walk", cue.english)

    def test_family_reassurance_and_learning_transaction_wording_has_matching_english(self):
        data = read_manifest(DEFAULT_PATH)
        cases = (
            ("famille-p4", "argument-1-exemple",
             "On le rassure ainsi sans lui faire une fausse promesse.",
             "This reassures the child without making a false promise."),
            ("famille-p6", "argument-1-idea",
             "transformer l'apprentissage en une simple transaction financière",
             "turning learning into a purely financial transaction"),
            ("famille-p6", "argument-1-exemple",
             "peut bâcler un exposé qui ne sera pas noté",
             "may rush through a presentation that will not be marked"),
            ("famille-p6", "argument-2-developpement",
             "S'il travaille régulièrement, s'il apprend de ses erreurs et s'il fait des progrès",
             "If they work regularly, learn from their mistakes and make progress"),
            ("famille-p6", "argument-4-idea",
             "donner de l'argent ne remplace pas l'aide dont un enfant a besoin pour progresser",
             "giving a child money is no substitute for the help they need to improve"),
        )
        for name, field, french_clause, english_clause in cases:
            with self.subTest(model=name, field=field):
                group = f"eo/tache-3/{name}"
                french = public_fields(scoped_models()[group])[field]
                row = data["groups"][group][fingerprint(french)]
                self.assertIn(french_clause, french)
                self.assertEqual(row["french"], french)
                self.assertIn(english_clause, row["english"])

    def test_family_cohabitation_and_authority_have_complete_saved_english(self):
        with patch("study.translations.service.urllib.request.urlopen") as provider:
            data = read_manifest(DEFAULT_PATH)
            for group, identities in (
                ("eo/tache-3/famille-p2", (1, 5, 3)),
                ("eo/tache-3/famille-p12", (4, 2, 5)),
            ):
                with self.subTest(group=group):
                    model = scoped_models()[group]
                    self.assertEqual(model.argument_ids, identities)
                    fields = public_fields(model)
                    self.assertEqual(len(fields), 15)
                    for field, french in fields.items():
                        with self.subTest(field=field):
                            row = data["groups"][group][fingerprint(french)]
                            self.assertEqual(row["french"], french)
                            self.assertTrue(row["english"].strip())
        provider.assert_not_called()

    def test_rewritten_family_english_keeps_contribution_honesty_rules_and_household_agreements(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        cases = (
            ("famille-p2", "argument-1-exemple", ("twenty-six-year-old woman", "pays her own expenses", "telling them about her day", "freely organising her own outings and plans"), ("asks permission",)),
            ("famille-p2", "argument-1-developpement", ("can reflect good relationships", "making your own decisions"), ("always",)),
            ("famille-p2", "argument-1-consequence", ("confuse this attachment to family with a lack of maturity",), ()),
            ("famille-p2", "argument-3-developpement", ("make their everyday lives easier", "becomes a genuine exchange"), ()),
            ("famille-p2", "nuance", ("must suit the parents too", "need rest and privacy", "putting off responsibilities"), ()),
            ("famille-p2", "argument-5-developpement", ("feeling happy there is the main reason for staying", "rent takes up a large part", "save and prepare"), ()),
            ("famille-p2", "argument-3-exemple", ("does the week's shopping", "prepares dinner", "parents get home late", "manage everything after work"), ()),
            ("famille-p3", "argument-1-exemple", ("grandfather had left his job", "check whether her savings would cover the course fees before resigning"), ()),
            ("famille-p4", "argument-1-developpement", ("false promise", "less willing to believe later explanations", "know what to expect"), ("next explanation",)),
            ("famille-p4", "argument-1-exemple", ("before a vaccination", "a little prick", "without making a false promise"), ("in the long term",)),
            ("famille-p4", "argument-2-exemple", ("grandmother on Wednesdays", "in hospital after a fall", "without promising that she will recover straight away"), ()),
            ("famille-p4", "argument-3-developpement", ("recognise a child's efforts", "exactly what they can improve", "how to go about it", "rather than a compliment that gives them no guidance"), ("A child can hear", "judgement of their worth")),
            ("famille-p4", "argument-3-consequence", ("helping them move forward", "not of discouraging them"), ()),
            ("famille-p4", "nuance", ("a matter for adults", "acknowledge that we do not know yet", "does not require lying"), ("guarantee",)),
            ("famille-p6", "nuance", ("a family outing or a book we choose together", "without promising a reward for every mark", "automatic payment"), ()),
            ("famille-p7", "nuance", ("discuss a work problem with your relative", "better to avoid working together"), ("no one dares say no",)),
            ("famille-p12", "introduction", ("children need parental authority", "not rigid authoritarianism", "without trying to obtain obedience through fear", "being willing to listen"), ()),
            ("famille-p12", "argument-4-exemple", ("keep playing", "school the next day", "maintaining a reasonable bedtime", "gets enough sleep"), ()),
            ("famille-p12", "argument-4-consequence", ("caring for the child", "not simply imposing your will"), ()),
            ("famille-p12", "argument-2-exemple", ("damaged a library book", "hide it in their schoolbag", "without being humiliated", "repair or replace it"), ()),
            ("famille-p12", "argument-2-consequence", ("Fear produces silence", "not necessarily trust", "understanding of their actions"), ()),
            ("famille-p12", "argument-5-developpement", ("understand why a limit exists", "listen to their objections", "remaining firm", "does not mean giving up the right to make it"), ()),
            ("famille-p12", "argument-5-exemple", ("phones to be put aside during meals", "everyone can talk about their day", "put their own phones away too"), ()),
            ("famille-p12", "nuance", ("intervene immediately", "explain afterwards", "non-negotiable limits"), ()),
            ("famille-p14", "argument-2-exemple", ("sort the clothes", "choose the wash programme", "guides him through several attempts", "wash his clothes without help"), ("without waiting for someone",)),
            ("famille-p14", "argument-1-exemple", ("one can prepare dinner while the other lays the table", "washing-up after the meal", "share the evening's work"), ()),
            ("famille-p14", "argument-4-exemple", ("father and his teenage son often argue", "They agree", "except on sports practice evenings", "his father will take over"), ()),
            ("famille-p14", "argument-4-consequence", ("can reduce reminders and arguments", "everyone knows their responsibility"), ("other person", "check every step")),
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

    def test_country_language_english_keeps_observation_broad_information_and_live_discussions_distinct(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p19"]
        rows = data["groups"][model.group]
        introduction = rows[fingerprint(model.response.position_claire)]["english"]
        self.assertIn("learn a lot about a country without speaking its language", introduction)
        self.assertIn("following spontaneous exchanges", introduction)
        observation = rows[fingerprint(model.response.arguments[0].exemple)]["english"]
        self.assertIn("a traveller takes the metro every morning", observation)
        self.assertIn("speaking quietly and avoiding phone calls", observation)
        information = rows[fingerprint(model.response.arguments[1].idea)]["english"]
        self.assertIn("knowledge about the country in a language we understand", information)
        self.assertNotIn("reasons behind", information)
        development = rows[fingerprint(model.response.arguments[1].developpement)]["english"]
        for phrase in ("history", "current affairs", "institutions"):
            self.assertIn(phrase, development)
        documentary = rows[fingerprint(model.response.arguments[1].exemple)]["english"]
        self.assertIn("Netherlands subtitled in French", documentary)
        self.assertIn("dikes and pumps allowed land to be reclaimed from the sea", documentary)
        consequence = rows[fingerprint(model.response.arguments[1].consequence)]["english"]
        self.assertIn("understand an important issue without mastering the local language", consequence)
        self.assertIn("flood protection", documentary)
        nuance = rows[fingerprint(model.response.nuance)]["english"]
        self.assertIn("tone, gestures and cultural references", nuance)
        self.assertIn("every word without getting a joke", nuance)
        self.assertNotIn("meeting", nuance)
        discussion = rows[fingerprint(model.response.arguments[2].exemple)]["english"]
        self.assertIn("a translated document about a housing proposal", discussion)
        self.assertIn("do not understand why some defend the project and others oppose it", discussion)
        with (
            override_settings(EO3_RESPONSE_TRANSLATIONS_PATH=DEFAULT_PATH),
            patch("study.translations.service.urllib.request.urlopen") as provider,
        ):
            for response in (model.response, replace(model.response, is_personal=True)):
                with self.subTest(personal=response.is_personal):
                    result = language_presentation(model, response, response.arguments)
                    self.assertTrue(result["ready"])
                    self.assertEqual(result["available"], 15)
                    self.assertEqual(result["total"], 15)
                    self.assertTrue(all(result["fields"].values()))
        provider.assert_not_called()

    def test_cuisine_english_aligns_clear_agreement_shared_meal_and_preservation_history(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p15"]
        rows = data["groups"][model.group]
        introduction = rows[fingerprint(model.response.position_claire)]["english"]
        self.assertTrue(introduction.startswith("Yes, I think food is a good way to discover a country's culture."))
        for phrase in ("how they live together", "part of their history", "skills passed down within families"):
            self.assertIn(phrase, introduction)
        shared_meal = rows[fingerprint(model.response.arguments[0].exemple)]["english"]
        self.assertIn("a visitor could share rice and fish with a family", shared_meal)
        self.assertIn("around one large dish", shared_meal)
        self.assertIn("come together and talk after work", shared_meal)
        history = rows[fingerprint(model.response.arguments[1].exemple)]["english"]
        self.assertIn("salted and dried fish, found in Portuguese cooking", history)
        self.assertIn("This method preserved fish, particularly during long sea voyages", history)
        self.assertIn("connection between certain recipes and the constraints of seafaring", history)
        self.assertNotIn("a visitor", history)
        with (
            override_settings(EO3_RESPONSE_TRANSLATIONS_PATH=DEFAULT_PATH),
            patch("study.translations.service.urllib.request.urlopen") as provider,
        ):
            result = language_presentation(model, model.response, model.response.arguments)
        self.assertTrue(result["ready"])
        self.assertEqual(result["available"], 15)
        self.assertEqual(result["total"], 15)
        provider.assert_not_called()

    def test_cultural_discovery_english_keeps_connected_introduction_and_firsthand_nuance(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p14"]
        rows = data["groups"][model.group]
        introduction = rows[fingerprint(model.response.position_claire)]["english"]
        self.assertIn("genuinely discover other cultures without travelling", introduction)
        self.assertIn("understand practices and their meaning", introduction)
        nuance = rows[fingerprint(model.response.nuance)]["english"]
        self.assertTrue(nuance.startswith(
            "Although these ways of learning are useful, they do not fully replace being there"
        ))
        self.assertIn("smells and everyday pace", nuance)
        self.assertIn("But not everyone can travel", nuance)
        self.assertIn("does not take value away from knowledge gained in other ways", nuance)
        self.assertNotIn("documentary", nuance)
        with (
            override_settings(EO3_RESPONSE_TRANSLATIONS_PATH=DEFAULT_PATH),
            patch("study.translations.service.urllib.request.urlopen") as provider,
        ):
            result = language_presentation(model, model.response, model.response.arguments)
        self.assertTrue(result["ready"])
        self.assertEqual(result["available"], 15)
        self.assertEqual(result["total"], 15)
        provider.assert_not_called()

    def test_traditions_english_covers_all_fifteen_selected_version_blocks(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p10"]
        rows = data["groups"][model.group]
        self.assertEqual({key for key, _ in model.source_prompts}, {"culture:p10", "culture:p32"})
        self.assertIn("a language, customs and a pace that may be very different", rows[fingerprint(model.response.arguments[0].developpement)]["english"])
        self.assertIn("a story they can understand and make their own, not just a rule", rows[fingerprint(model.response.arguments[1].consequence)]["english"])
        self.assertIn("making room for new habits", rows[fingerprint(model.response.conclusion)]["english"])
        with (
            override_settings(EO3_RESPONSE_TRANSLATIONS_PATH=DEFAULT_PATH),
            patch("study.translations.service.urllib.request.urlopen") as provider,
        ):
            for response in (model.response, replace(model.response, is_personal=True)):
                with self.subTest(personal=response.is_personal):
                    result = language_presentation(model, response, response.arguments)
                    self.assertTrue(result["ready"])
                    self.assertEqual(result["available"], 15)
                    self.assertEqual(result["total"], 15)
                    self.assertTrue(all(result["fields"].values()))
        provider.assert_not_called()

    def test_adaptation_english_clinic_example_connects_neighbour_advice_to_checking_hours(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p9"]
        rows = data["groups"][model.group]
        example = rows[fingerprint(model.response.arguments[2].exemple)]["english"]
        for phrase in (
            "One Sunday", "their child, who has a fever", "Unfamiliar with local healthcare services",
            "ask a neighbour for advice", "walk-in clinic's phone number",
            "check its opening hours before going",
        ):
            self.assertIn(phrase, example)

    def test_new_country_habits_english_restores_the_majority_distinction(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p1"]
        rows = data["groups"][model.group]
        development = rows[fingerprint(model.response.arguments[1].developpement)]["english"]
        self.assertIn("familiar routines helps us feel at home", development)
        self.assertIn(
            "A habit does not have to disappear simply because the majority of people do things differently.",
            development,
        )
        nuance = rows[fingerprint(model.response.nuance)]["english"]
        self.assertIn("safety and shared rules", nuance)
        self.assertIn("whilst respecting others", nuance)

    def test_goals_abroad_english_restores_achievable_steps_and_preparation(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p5"]
        rows = data["groups"][model.group]
        preparation = model.response.arguments[1]
        self.assertIn("transforms a broad ambition into achievable steps", rows[fingerprint(preparation.idea)]["english"])
        development = rows[fingerprint(preparation.developpement)]["english"]
        for phrase in ("entry requirements", "costs involved", "skills you are lacking", "before incurring significant expenses"):
            self.assertIn(phrase, development)
        self.assertIn("If further training is required", rows[fingerprint(preparation.exemple)]["english"])
        result = rows[fingerprint(preparation.consequence)]["english"]
        self.assertIn("minimises surprises", result)
        self.assertIn("adjust your timetable", result)

    def test_migration_choice_english_keeps_real_constraints_and_a_genuine_option_to_stay(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/economie-p14"]
        rows = data["groups"][model.group]
        livelihood, safety, choice = model.response.arguments
        self.assertIn("people often leave", rows[fingerprint(model.response.position_claire)]["english"])
        self.assertIn("His savings are almost gone", rows[fingerprint(livelihood.exemple)]["english"])
        self.assertIn("staying without an income is not a realistic alternative", rows[fingerprint(livelihood.consequence)]["english"])
        school = rows[fingerprint(safety.exemple)]["english"]
        self.assertIn("violence repeatedly forces their children's school to close", school)
        self.assertIn("could give the children a chance", school)
        self.assertIn("can keep her job or accept", rows[fingerprint(choice.exemple)]["english"])
        conclusion = rows[fingerprint(model.response.conclusion)]["english"]
        self.assertIn("some really do have the option to stay", conclusion)
        self.assertIn("leaving out of necessity may also want a change", conclusion)

    def test_personal_letters_english_keeps_emotional_gesture_and_fuller_expression(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p18"]
        self.assertEqual({key for key, _ in model.source_prompts}, {"culture:p18", "culture:p23"})
        rows = data["groups"][model.group]
        attention, reflection, _ = model.response.arguments
        self.assertIn("given them particular attention", rows[fingerprint(attention.idea)]["english"])
        development = rows[fingerprint(attention.developpement)]["english"]
        self.assertIn("Choosing a card, finding a few words and sending it", development)
        self.assertIn("actions done with this person in mind", development)
        example = rows[fingerprint(attention.exemple)]["english"]
        self.assertIn("Sunday walks", example)
        self.assertIn("Recognising his handwriting", example)
        self.assertIn("hear him speaking to her", example)
        self.assertIn("express our feelings more fully", rows[fingerprint(reflection.idea)]["english"])
        development = rows[fingerprint(reflection.developpement)]["english"]
        self.assertIn("what we feel and why", development)
        self.assertIn("choosing precise words and linking our ideas", development)
        example = rows[fingerprint(reflection.exemple)]["english"]
        self.assertIn("In a love letter", example)
        self.assertIn("looking for work", example)
        self.assertIn("her support helped him regain confidence", example)
        self.assertIn("why they matter in our lives", rows[fingerprint(reflection.consequence)]["english"])
        conclusion = rows[fingerprint(model.response.conclusion)]["english"]
        for phrase in ("attention, words and memories", "keep letters for certain occasions"):
            self.assertIn(phrase, conclusion)

    def test_shared_family_letter_result_states_the_readers_gain(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        expected = "She discovers a period of her grandmother's life she did not experience herself."
        for group in ("eo/tache-3/culture-p18", "eo/tache-3/technologie-p12"):
            result = scoped_models()[group].response.arguments[2].consequence
            row = data["groups"][group][fingerprint(result)]
            self.assertEqual(row["english"], expected)
            self.assertIn("Elle découvre une période", row["french"])
            self.assertIn("la vie de sa grand-mère qu'elle n'a pas connue elle-même", row["french"])

    def test_solo_travel_english_keeps_information_seeking_distinct_from_the_travellers_decision(self):
        data = read_manifest(DEFAULT_PATH)
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
        self.assertIn("travelling alone for the first time", example)
        self.assertIn("Her train is cancelled", example)
        self.assertIn("the following day", example)
        self.assertLess(example.index("asks for information"), example.index("buys a bus ticket"))
        self.assertIn("that same day", example)
        self.assertNotIn("hotel", example)
        result = rows[fingerprint(argument.consequence)]["english"]
        self.assertIn("can handle an unexpected problem", result)
        self.assertIn("without waiting for someone close to her", result)
        painting = rows[fingerprint(solo.response.arguments[1].exemple)]["english"]
        self.assertIn("spend the afternoon at an exhibition.", painting)
        self.assertNotIn("head home early", painting)
        self.assertIn("friends who would rather go shopping", painting)
        with (
            override_settings(EO3_RESPONSE_TRANSLATIONS_PATH=DEFAULT_PATH),
            patch("study.translations.service.urllib.request.urlopen") as provider,
        ):
            for response in (solo.response, replace(solo.response, is_personal=True)):
                with self.subTest(personal=response.is_personal):
                    presentation = language_presentation(solo, response, response.arguments)
                    self.assertTrue(presentation["ready"])
                    self.assertEqual(presentation["available"], 15)
                    self.assertEqual(presentation["total"], 15)
                    self.assertTrue(all(presentation["fields"].values()))
        provider.assert_not_called()

    def test_reading_alternatives_english_links_documentary_images_to_art_and_history(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p20"]
        rows = data["groups"][model.group]
        argument = model.response.arguments[1]
        development = rows[fingerprint(argument.developpement)]["english"]
        self.assertIn("draw attention to a detail", development)
        self.assertIn("context and the artist's choices", development)
        self.assertIn("understand what it expresses", development)
        example = rows[fingerprint(argument.exemple)]["english"]
        self.assertIn("Picasso's Guernica", example)
        self.assertIn("Close-ups show the figures crying out", example)
        self.assertIn("bombing that inspired the painting", example)
        self.assertIn("condemns the violence of war", example)
        consequence = rows[fingerprint(argument.consequence)]["english"]
        self.assertIn("artistic and historical knowledge", consequence)
        self.assertIn("without necessarily reading a book", consequence)
        nuance = rows[fingerprint(model.response.nuance)]["english"]
        self.assertIn("ways of learning can complement each other", nuance)
        conclusion = rows[fingerprint(model.response.conclusion)]["english"]
        self.assertIn("Documentaries, encounters and practice", conclusion)

    def test_school_arts_english_keeps_expression_cultural_openness_and_professional_discovery(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p13"]
        rows = data["groups"][model.group]
        expression, cultures, careers = model.response.arguments
        self.assertIn("personal expression, sensitivity and critical thinking", rows[fingerprint(expression.idea)]["english"])
        self.assertIn("hesitant voice and pauses", rows[fingerprint(expression.exemple)]["english"])
        self.assertIn("world's cultural diversity", rows[fingerprint(cultures.idea)]["english"])
        culture_example = rows[fingerprint(cultures.exemple)]["english"]
        self.assertIn("Day of the Dead", culture_example)
        self.assertIn("photographs honour relatives who have died", culture_example)
        self.assertIn("consider further training", rows[fingerprint(careers.developpement)]["english"])
        self.assertIn("graphic design as a career", rows[fingerprint(careers.exemple)]["english"])
        self.assertIn("sometimes find a career path", rows[fingerprint(model.response.conclusion)]["english"])

    def test_television_english_keeps_world_cup_togetherness_and_explicit_time_tradeoffs(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p12"]
        rows = data["groups"][model.group]
        social = model.response.arguments[1]
        self.assertIn("A live match or performance", rows[fingerprint(social.developpement)]["english"])
        example = rows[fingerprint(social.exemple)]["english"]
        for phrase in ("World Cup", "at one neighbour's home", "Cheering the team on", "talking at half-time"):
            self.assertIn(phrase, example)
        self.assertIn("an opportunity for shared time rather than a reason to isolate", rows[fingerprint(social.consequence)]["english"])
        nuance = rows[fingerprint(model.response.nuance)]["english"]
        self.assertIn("neglecting sleep or time with loved ones", nuance)
        self.assertIn("bring people together", rows[fingerprint(model.response.conclusion)]["english"])

    def test_reality_tv_english_links_entertaining_mockery_to_normalising_humiliation(self):
        data = read_manifest(DEFAULT_PATH)
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p31"]
        rows = data["groups"][model.group]
        argument = model.response.arguments[1]
        self.assertIn("making humiliation more acceptable", rows[fingerprint(argument.idea)]["english"])
        development = rows[fingerprint(argument.developpement)]["english"]
        self.assertIn("an insult attracts attention and laughter", development)
        self.assertIn("remember the joke rather than the hurt", development)
        example = rows[fingerprint(argument.exemple)]["english"]
        self.assertIn("replays", example)
        self.assertIn("a contestant's appearance", example)
        self.assertIn("barely shows the discomfort", example)
        consequence = rows[fingerprint(argument.consequence)]["english"]
        self.assertIn("may then find the remark acceptable because it amuses others", consequence)
        self.assertIn("without seeing what it puts the recipient through", consequence)

    def test_requested_book_english_keeps_learning_practice_and_the_characters_choice(self):
        data = read_manifest(DEFAULT_PATH)
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
        with patch("study.translations.service.urllib.request.urlopen") as provider:
            page = self.client.get(prompt_detail_url(prompt))
        provider.assert_not_called()
        self.assertContains(page, 'data-eo3-language-ready="true"')
        self.assertContains(page, 'data-eo3-language-total="15"')
        self.assertContains(page, 'data-eo3-argument-toggle=', count=3)
        self.assertContains(page, 'data-eo3-section-toggle=', count=12)
        self.assertContains(page, 'data-eo3-french=', count=15)
        self.assertContains(page, 'data-eo3-english=', count=15)
        self.assertEqual(page.context["response_content"], scoped_models()[prompt.response.semantic_group].response)

    def test_selected_traditions_version_has_complete_english_for_default_and_matching_personal_text(self):
        model = scoped_models()["eo/tache-3/culture-p10"]
        prompts = [self.prompt(key) for key in ("culture:p10", "culture:p32")]
        with (
            override_settings(EO3_RESPONSE_TRANSLATIONS_PATH=DEFAULT_PATH),
            patch("study.translations.service.urllib.request.urlopen") as provider,
        ):
            for prompt in prompts:
                with self.subTest(prompt=prompt.content_key, personal=False):
                    page = self.client.get(prompt_detail_url(prompt))
                    self.assertFalse(page.context["response_content"].is_personal)
                    self.assertTrue(page.context["eo3_language"]["ready"])
                    self.assertEqual(page.context["eo3_language"]["available"], 15)
                    self.assertContains(page, 'data-eo3-language-ready="true"')
                    self.assertContains(page, 'data-eo3-english=', count=15)
            fields = asdict(model.response)
            fields.pop("is_personal")
            fields["arguments"] = list(fields["arguments"])
            PersonalResponse.objects.create(
                user=self.user, response=prompts[0].response, source_prompt=prompts[0], **fields,
            )
            for prompt in prompts:
                with self.subTest(prompt=prompt.content_key, personal=True):
                    page = self.client.get(prompt_detail_url(prompt))
                    self.assertTrue(page.context["response_content"].is_personal)
                    self.assertTrue(page.context["eo3_language"]["ready"])
                    self.assertEqual(page.context["eo3_language"]["available"], 15)
                    self.assertContains(page, 'data-eo3-language-ready="true"')
                    self.assertContains(page, 'data-eo3-english=', count=15)
        provider.assert_not_called()

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
        with patch("study.translations.service.urllib.request.urlopen") as provider:
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
        rendered = render_to_string("study/review/partials/card_back.html", payload)
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
        with self.assertLogs("study.expression.eo.tache_3.languages", level="ERROR"):
            page = self.client.get(prompt_detail_url(prompt))
        self.assertTrue(page.context["eo3_language"]["error"])
        self.assertContains(page, 'data-eo3-language-error="true"')
