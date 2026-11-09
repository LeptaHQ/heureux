import json
from io import StringIO
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from study.catalogue import registry as catalogue
from study.catalogue import loader as content
from study.accounts.services import provision_user_study_data
from study.expression.eo.tache_3.languages import manifest, read_manifest, write_manifest
from study.expression.eo.tache_3.responses import load_tache_three_models
from study.models import Annotation, AnnotationKind, Card, CardType, PersonalResponse, Phrase, Prompt, Response, WritingSujet

from . import factories


class ContentHierarchyTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())) / "themes"
        shutil.copytree(content.EO_TACHE_THREE_THEMES_DIR, self.root)
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def test_current_themes_own_models_once_without_renaming_source_groups(self):
        taxonomy = catalogue.eo_tache_three_taxonomy()
        self.assertEqual(len(taxonomy.themes), 9)
        self.assertEqual({path.name for path in self.root.iterdir()}, {theme.slug for theme in taxonomy.themes})
        models = load_tache_three_models()
        self.assertEqual(len(models), 131)
        self.assertEqual(sum(len(model.source_prompts) for model in models.values()), 167)
        seen = set()
        for path in self.root.glob("*/responses.json"):
            for key in json.loads(path.read_text())["responses"]:
                identity = f"eo/tache-3/{key}"
                self.assertNotIn(identity, seen)
                self.assertEqual(taxonomy.by_group[identity].theme.slug, path.parent.name)
                seen.add(identity)
        self.assertEqual(seen, set(models))
        self.assertEqual(load_tache_three_models(self.root), models)
        self.assertIn("culture-p3", json.loads((self.root / "societe/responses.json").read_text())["responses"])
        self.assertTrue((content.RESPONSES_DIR / "Economie/batch_11_15.md").is_file())
        self.assertFalse(any((content.CONTENT_DIR / name).exists() for name in (
            "responses", "subject_vocabulary", "comprehension_vocabulary", "ee",
            "tache_1", "tache_2", "tache_3",
        )))

    def test_missing_duplicate_and_wrong_theme_catalogues_are_rejected(self):
        path = self.root / "culture/hints.json"
        original = path.read_text()
        row = json.loads(original)
        key, value = next(iter(row["groups"].items()))
        del row["groups"][key]
        path.write_text(json.dumps(row))
        with self.assertRaisesMessage(ValueError, "coverage"):
            content.load_eo3_catalogue(self.root, "hints.json")
        path.write_text(original)
        other = self.root / "societe/hints.json"
        data = json.loads(other.read_text())
        data["groups"][key] = value
        other.write_text(json.dumps(data))
        with self.assertRaisesMessage(ValueError, "ownership"):
            content.load_eo3_catalogue(self.root, "hints.json")
        path.unlink()
        with self.assertRaisesMessage(ValueError, "incomplete"):
            content.load_eo3_catalogue(self.root, "hints.json")

    def test_translation_roundtrip_preserves_every_history_row_and_invalidates_cache(self):
        before = read_manifest(self.root)
        write_manifest(self.root, before)
        self.assertEqual(read_manifest(self.root), before)
        incomplete = {**before, "groups": {}}
        with self.assertRaisesMessage(ValueError, "every semantic group"):
            write_manifest(self.root, incomplete)
        self.assertEqual(read_manifest(self.root), before)
        with override_settings(EO3_RESPONSE_TRANSLATIONS_PATH=self.root):
            cached = manifest()
            path = self.root / "immigration/translations.en.json"
            data = json.loads(path.read_text())
            rows = data["groups"]["eo/tache-3/economie-p14"]
            row = next(iter(rows.values()))
            row["english"] += " Updated."
            path.write_text(json.dumps(data))
            refreshed = manifest()
            self.assertNotEqual(refreshed, cached)
            self.assertEqual(read_manifest(self.root), refreshed)
            with patch("study.translations.service.urllib.request.urlopen") as provider:
                self.assertEqual(manifest(), refreshed)
            provider.assert_not_called()

    def test_translation_metadata_and_theme_directories_are_strict(self):
        path = self.root / "culture/translations.en.json"
        data = json.loads(path.read_text())
        data["target_language"] = "EN-US"
        path.write_text(json.dumps(data))
        with self.assertRaisesMessage(ValueError, "metadata"):
            read_manifest(self.root)
        (self.root / "obsolete").mkdir()
        with self.assertRaisesMessage(ValueError, "taxonomy"):
            content.load_eo3_catalogue(self.root, "hints.json")


class ContentHierarchyImportTests(TestCase):
    def test_complete_relocated_import_preserves_keys_and_private_state_on_repeat(self):
        call_command("import_content", stdout=StringIO())
        identities = {
            model: list(model.objects.order_by("pk").values_list("pk", key))
            for model, key in (
                (Prompt, "content_key"), (Response, "content_key"),
                (Phrase, "phrase_id"), (WritingSujet, "slug"),
            )
        }
        prompt = Prompt.objects.get(content_key="economie:p14")
        user = factories.make_user("content-hierarchy-preservation")
        provision_user_study_data(user)
        card = Card.objects.get(
            user=user, response=prompt.response, card_type=CardType.SPINE,
        )
        card.reps, card.ease = 7, 2.8
        card.save(update_fields=["reps", "ease"])
        personal = PersonalResponse.objects.create(
            user=user, response=prompt.response, source_prompt=prompt,
            conclusion="Ma conclusion personnelle.",
        )
        annotation = Annotation.objects.create(
            user=user, task=prompt.theme.task, kind=AnnotationKind.NOTE,
            source_key="response:economie:p14:back",
            source_path="/expression/orale/tache-3/",
            body="Ma note conservée.",
        )
        private = {
            (type(obj), obj.pk): type(obj).objects.filter(pk=obj.pk).values().get()
            for obj in (card, personal, annotation)
        }
        call_command("import_content", stdout=StringIO())
        for model, rows in identities.items():
            key = "phrase_id" if model is Phrase else "slug" if model is WritingSujet else "content_key"
            self.assertEqual(list(model.objects.order_by("pk").values_list("pk", key)), rows)
        for (model, pk), row in private.items():
            self.assertEqual(model.objects.filter(pk=pk).values().get(), row)
