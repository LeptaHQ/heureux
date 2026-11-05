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
        self.assertIn("leaving without buying anything", row["english"])
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
        self.assertIn("Learning the language can also help", row["english"])
        self.assertNotIn("must also explore the language", row["english"])
        row = data["groups"][cuisine.group][fingerprint(cuisine.response.arguments[0].developpement)]
        self.assertIn("Meal times can reflect the rhythm of work", row["english"])
        self.assertIn("can also reveal the importance placed on family interaction", row["english"])
        self.assertIn("how meals are organised", row["english"])
        row = data["groups"][cuisine.group][fingerprint(cuisine.response.arguments[1].developpement)]
        self.assertIn("ingredients in a dish", row["english"])
        self.assertIn("salt was used to preserve food", row["english"])
        self.assertIn("This practice", row["english"])
        older = scoped_models()["eo/tache-3/culture-p8"]
        row = data["groups"][older.group][fingerprint(older.response.arguments[0].exemple)]
        self.assertIn("arguing with their parents", row["english"])
        self.assertIn("disagreement between generations", row["english"])
        row = data["groups"][older.group][fingerprint(older.response.arguments[1].exemple)]
        self.assertIn("clips of the same school fight", row["english"])
        self.assertIn("violence is common among young people", row["english"])
        self.assertNotIn("violence is rife", row["english"])

    def test_living_with_parents_english_keeps_adult_freedom_and_reciprocal_consideration(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p16"]
        row = data["groups"][model.group][fingerprint(model.response.arguments[2].exemple)]
        self.assertIn("adult woman who comes home late lets her parents know", row["english"])
        self.assertIn("without asking permission to go out", row["english"])
        self.assertIn("avoids making noise and respects shared spaces", row["english"])
        self.assertNotIn("nights out", row["english"])
        development = data["groups"][model.group][
            fingerprint(model.response.arguments[2].developpement)
        ]["english"]
        self.assertIn("Schedules, visitors and private spaces need to be discussed", development)
        self.assertIn("Without this balance", development)
        self.assertIn("can come with constant tension", development)
        result = data["groups"][model.group][
            fingerprint(model.response.arguments[0].consequence)
        ]["english"]
        self.assertIn("can look for a job under less financial pressure", result)
        self.assertIn("reduces the risk of accepting an option in a hurry", result)
        self.assertNotIn("will not", result)
        nuance = data["groups"][model.group][fingerprint(model.response.nuance)]["english"]
        self.assertIn("some parents lack space or money", nuance)
        self.assertIn("does not require moving out by a specific date", nuance)

    def test_family_language_english_distinguishes_direct_family_contact_and_parent_expression(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p13"]
        rows = data["groups"][model.group]
        contact, expression, _ = model.response.arguments
        development = rows[fingerprint(contact.developpement)]["english"]
        self.assertIn("do not necessarily speak the host country's language", development)
        self.assertIn("If every conversation requires translation", development)
        example = rows[fingerprint(contact.exemple)]["english"]
        self.assertIn("Her grandson understands her language", example)
        self.assertIn("asks his own questions without waiting for his mother", example)
        development = rows[fingerprint(expression.developpement)]["english"]
        self.assertIn("a language they are still learning", development)
        self.assertIn("struggle to explain an emotion", development)
        self.assertIn("allows in-depth discussions", development)
        example = rows[fingerprint(expression.exemple)]["english"]
        self.assertIn("father who is a beginner in the local language", example)
        self.assertIn("In his mother tongue", example)
        self.assertNotIn("fluent", example)

    def test_living_alone_english_keeps_rest_broader_than_going_to_bed(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p11"]
        row = data["groups"][model.group][fingerprint(model.response.arguments[0].exemple)]
        self.assertIn("nurse comes home after a night shift", row["english"])
        self.assertIn("sleeps in a quiet flat", row["english"])
        self.assertIn("others might be getting ready for school or work", row["english"])
        self.assertIn("would mean finding a compromise", row["english"])
        self.assertNotIn("go to bed", row["english"])
        result = data["groups"][model.group][
            fingerprint(model.response.arguments[0].consequence)
        ]["english"]
        self.assertIn("makes it easier for her to rest", result)
        self.assertNotIn("bedtime", result)
        costs = data["groups"][model.group][
            fingerprint(model.response.arguments[1].developpement)
        ]["english"]
        self.assertIn("Even if you consume less", costs)
        self.assertIn("some expenses remain difficult to reduce", costs)
        self.assertIn("if everyone genuinely contributes", costs)

    def test_family_work_english_identifies_sibling_coworkers_before_family_spillover(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p7"]
        example = data["groups"][model.group][
            fingerprint(model.response.arguments[1].exemple)
        ]["english"]
        self.assertIn("brother often arrives late at the restaurant he runs with his sister", example)
        self.assertIn("She can raise this with him in a meeting", example)
        self.assertIn("rather than in front of all their relatives at Sunday lunch", example)
        self.assertNotIn("mother", example)
        result = data["groups"][model.group][
            fingerprint(model.response.arguments[1].consequence)
        ]["english"]
        self.assertIn("without drawing the family into the conflict", result)

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
        self.assertIn("Someone who is ill needs to collect some medicine", example)
        self.assertIn("parents are several hours away by plane", example)
        self.assertIn("If they know a neighbour who is available", example)
        self.assertIn("may be able to ask", example)
        self.assertNotIn("agrees", example)
        self.assertNotIn("will", example)

    def test_personal_advice_english_distinguishes_outdated_methods_and_different_priorities(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p3"]
        rows = data["groups"][model.group]
        development = rows[fingerprint(model.response.arguments[1].developpement)]["english"]
        self.assertIn("may be well intentioned but based on outdated assumptions", development)
        example = rows[fingerprint(model.response.arguments[1].exemple)]["english"]
        self.assertIn("handing a CV directly to a company", example)
        self.assertIn("requires an online application with a reference number", example)
        self.assertIn("that approach alone is not enough", example)
        result = rows[fingerprint(model.response.arguments[1].consequence)]["english"]
        self.assertIn("keep the idea of showing initiative", result)
        self.assertIn("adapting the method", result)
        example = rows[fingerprint(model.response.arguments[2].exemple)]["english"]
        self.assertIn("grandmother recommends a stable job", example)
        self.assertIn("granddaughter, who wants to work abroad", example)
        self.assertIn("without condemning her decision to leave", example)

    def test_teen_social_media_english_keeps_sleep_help_seeking_and_private_messages_distinct(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p1"]
        rows = data["groups"][model.group]
        self.assertEqual(model.argument_ids, (5, 2, 3))
        example = rows[fingerprint(model.response.arguments[1].exemple)]["english"]
        self.assertIn("boy goes to bed on time, but still replies to messages in bed", example)
        self.assertIn("agrees to leave his phone in the living room overnight", example)
        result = rows[fingerprint(model.response.arguments[1].consequence)]["english"]
        self.assertIn("without their messages interrupting his sleep", result)
        development = rows[fingerprint(model.response.arguments[2].developpement)]["english"]
        self.assertIn("If asking for help immediately leads", development)
        self.assertIn("they may hide the problem", development)
        self.assertIn("block an account, report a message and keep evidence", development)
        nuance = rows[fingerprint(model.response.nuance)]["english"]
        self.assertIn("minimum age must be respected", nuance)
        self.assertIn("without routinely reading their private messages", nuance)
        conclusion = rows[fingerprint(model.response.conclusion)]["english"]
        self.assertIn("gradual access with support", conclusion)
        self.assertIn("rather than allowing everything or banning everything", conclusion)

    def test_family_friendship_english_keeps_affection_confidences_and_respected_choice_distinct(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p10"]
        rows = data["groups"][model.group]
        development = rows[fingerprint(model.response.arguments[0].developpement)]["english"]
        self.assertIn("We do not choose our family", development)
        self.assertIn("be fond of our brother", development)
        self.assertIn("without wanting the same things or having many personal conversations", development)
        self.assertNotIn("must", development)
        result = rows[fingerprint(model.response.arguments[0].consequence)]["english"]
        self.assertIn("His brother remains important to him", result)
        self.assertIn("not the person he spontaneously tells about his day-to-day life", result)
        example = rows[fingerprint(model.response.arguments[2].exemple)]["english"]
        self.assertIn("Her cousin would prefer her to stay", example)
        self.assertIn("respects her choice and keeps it confidential", example)
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
        self.assertIn("retired man", community_example)
        self.assertIn("gardening workshop every Tuesday", community_example)
        self.assertIn("They are not his friends yet", community_example)
        growth_text = rows[fingerprint(growth.developpement)]["english"]
        self.assertIn("confidence to try, then continue despite our doubts", growth_text)
        self.assertIn("without making the decision for us", growth_text)
        growth_example = rows[fingerprint(growth.exemple)]["english"]
        self.assertIn("amateur drama class", growth_example)
        self.assertIn("continues rehearsing and then takes part in a show", growth_example)
        self.assertIn("might otherwise", rows[fingerprint(growth.consequence)]["english"])

    def test_shared_friendship_english_keeps_chosen_solitude_confiding_and_partner_space_distinct(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/culture-p16"]
        rows = data["groups"][model.group]
        self.assertEqual(model.argument_ids, (4, 1, 6))
        self.assertEqual({key for key, _ in model.source_prompts}, {"culture:p16", "famille:p8"})
        example = rows[fingerprint(model.response.arguments[0].exemple)]["english"]
        self.assertIn("gardening on Saturdays", example)
        self.assertIn("meeting their sister for dinner", example)
        self.assertIn("no friends at this stage of their life", example)
        self.assertIn("an affectionate relationship", example)
        example = rows[fingerprint(model.response.arguments[1].exemple)]["english"]
        self.assertIn("unsure about changing career", example)
        self.assertIn("without immediately having to reassure their parents", example)
        example = rows[fingerprint(model.response.arguments[2].exemple)]["english"]
        self.assertIn("enjoys hiking, but his spouse does not", example)
        self.assertIn("without giving up his activity or making his partner accompany him", example)
        development = rows[fingerprint(model.response.arguments[2].developpement)]["english"]
        self.assertIn("does not necessarily share our hobbies", development)
        self.assertIn("cannot always be available", development)
        self.assertIn("personal space and other people to rely on", development)
        result = rows[fingerprint(model.response.arguments[2].consequence)]["english"]
        self.assertIn("less pressure on his relationship", result)
        nuance = rows[fingerprint(model.response.nuance)]["english"]
        self.assertIn("does not comfort someone who suffers from its absence", nuance)
        self.assertIn("quality matters more than numbers", nuance)

    def test_child_language_english_keeps_local_practice_and_school_help_conditional(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        model = scoped_models()["eo/tache-3/famille-p13"]
        rows = data["groups"][model.group]
        row = rows[fingerprint(model.response.arguments[2].exemple)]
        self.assertIn("keeps using its language at mealtimes", row["english"])
        self.assertIn("enrols its child in a neighbourhood sports activity", row["english"])
        self.assertIn("If the child struggles to understand instructions in class", row["english"])
        self.assertIn("asks the school what help is available", row["english"])
        self.assertNotIn("puppet", row["english"])
        self.assertNotIn("fluently", row["english"])
        development = rows[fingerprint(model.response.arguments[2].developpement)]["english"]
        self.assertIn("School does not necessarily resolve every difficulty", development)
        self.assertIn("Even without a good command of this language", development)
        self.assertIn("parents can seek opportunities for practice and suitable support", development)

    def test_rewritten_family_english_keeps_contribution_honesty_authority_and_mental_load(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        cases = (
            ("famille-p2", "argument-1-exemple", ("twenty-six-year-old woman", "cooks two evenings a week", "organises her own outings"), ("asks permission",)),
            ("famille-p2", "argument-4-developpement", ("Parents also need peace and privacy", "Everyone must be able to express their limits"), ()),
            ("famille-p4", "argument-1-exemple", ("Before a vaccination", "a little prick", "better than promising they will not feel anything"), ()),
            ("famille-p4", "argument-2-exemple", ("If a child's parents separate", "not the child's fault", "where the child will sleep"), ()),
            ("famille-p4", "nuance", ("without asking them to solve the problem", "acknowledge uncertainty"), ("guarantee",)),
            ("famille-p12", "argument-1-exemple", ("maintains bedtime", "five minutes' warning"), ()),
            ("famille-p12", "argument-3-exemple", ("before 10 pm", "transport becomes infrequent", "let their parents know if they are delayed"), ()),
            ("famille-p12", "nuance", ("intervene immediately", "then explain afterwards", "reconsider a rule they have outgrown"), ()),
            ("famille-p14", "argument-2-exemple", ("sort his laundry", "run a washing machine", "without waiting for someone"), ()),
            ("famille-p14", "argument-3-exemple", ("checks the cupboards", "prepares the list", "If they wait to be told every item"), ()),
            ("famille-p14", "argument-3-consequence", ("full responsibility", "organisational burden"), ()),
            ("famille-p14", "nuance", ("adult who is ill can be excused", "abilities and available time"), ("equally",)),
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

    def test_requested_book_english_keeps_learning_retention_and_the_characters_choice(self):
        data = validate_manifest(json.loads(DEFAULT_PATH.read_text()))
        if not data["groups"]:
            self.skipTest("DeepL response translations have not been prepared.")
        book = scoped_models()["eo/tache-3/culture-p6"]
        rows = data["groups"][book.group]
        self.assertEqual({key for key, _ in book.source_prompts}, {"culture:p6", "education:p8"})
        example = rows[fingerprint(book.response.arguments[1].exemple)]["english"]
        self.assertIn("A week later", example)
        self.assertIn("can still explain these connections in their own words", example)
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
