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
        self.assertTrue(all(not value for value in result["fields"].values()))

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
        cuisine = scoped_models()["eo/tache-3/culture-p15"]
        row = data["groups"][cuisine.group][fingerprint(cuisine.response.nuance)]
        self.assertIn("Learning the language can also help", row["english"])
        self.assertNotIn("must also explore the language", row["english"])


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
