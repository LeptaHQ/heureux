"""Narrow parser/cache contracts without modifying the bundled corpus."""

import json
import shutil
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from study import catalogue
from study import content_loader as content
from study.management.commands.sync_content import THEMES


class AuthorResponseCacheTests(SimpleTestCase):
    key = "ee-tache3:janvier:combinaison-1"

    def payload(self, heading="Original heading"):
        return json.dumps({
            "version": 1,
            "responses": [{
                "content_key": self.key,
                "heading": heading,
                "synthese": " ".join(["synthèse"] * 40),
                "point_de_vue": " ".join(["opinion"] * 80),
                "origin": "author",
            }],
        })

    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        for name, value in (
            ("load_ee_subject_keys", (self.key,)),
            ("ee_canonical_by_content_key", {}),
        ):
            mocked = patch.object(content, name, return_value=value)
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_custom_paths_are_reparsed_and_invalid_edits_are_rejected(self):
        path = Path("custom-author-responses.json")
        with patch.object(Path, "read_text", side_effect=[
            self.payload(), self.payload("Changed heading"), "{}",
        ]) as read:
            self.assertEqual(
                content.load_ee_tache_three_author_responses(path)[self.key]["heading"],
                "Original heading",
            )
            self.assertEqual(
                content.load_ee_tache_three_author_responses(path)[self.key]["heading"],
                "Changed heading",
            )
            with self.assertRaises(ValueError):
                content.load_ee_tache_three_author_responses(path)
        self.assertEqual(read.call_count, 3)

    def test_default_cache_is_deeply_read_only_and_clear_reloads_it(self):
        with patch.object(Path, "read_text", side_effect=[
            self.payload(), self.payload("Changed heading"),
        ]) as read:
            first = content.load_ee_tache_three_author_responses()
            self.assertIs(content.load_ee_tache_three_author_responses(), first)
            with self.assertRaises(TypeError):
                first[self.key]["heading"] = "Not source content"
            with self.assertRaises(TypeError):
                first["invented-key"] = first[self.key]
            catalogue.clear_catalogue_cache()
            self.assertEqual(
                content.load_ee_tache_three_author_responses()[self.key]["heading"],
                "Changed heading",
            )
        self.assertEqual(read.call_count, 2)

    def test_explicit_bundled_path_is_fresh_for_imports(self):
        with patch.object(Path, "read_text", side_effect=[
            self.payload(), self.payload("New import heading"),
        ]):
            cached = content.load_ee_tache_three_author_responses()
            imported = content.load_ee_tache_three_author_responses(
                content.EE_TACHE_THREE_AUTHOR_RESPONSES_PATH
            )
            self.assertEqual(cached[self.key]["heading"], "Original heading")
            self.assertEqual(imported[self.key]["heading"], "New import heading")

    def test_boolean_schema_version_is_not_an_integer_version(self):
        payload = self.payload().replace('"version": 1', '"version": true')
        with patch.object(Path, "read_text", return_value=payload):
            with self.assertRaises(ValueError):
                content.load_ee_tache_three_author_responses(Path("custom.json"))

    def test_response_parser_bypasses_a_warmed_request_cache(self):
        source = content.EeTacheThreeCombinaison(
            content_key=self.key, combinaison="Combinaison 1", position=1,
            sujet="Subject", heading="Source heading",
            document1="First document", document2="Second document",
            synthese="Source synthesis", point_de_vue="Source opinion",
            title_missing=False, document2_missing=False,
            documents_identical=False, document1_invalid=False,
        )
        month = content.EeTacheThreeMonth(
            number=1, slug="janvier", name="Janvier",
            combinaisons=(source,),
        )
        theme = content.EeSubjectThemeData("theme", "Theme", "book", 1)
        with (
            patch.object(content, "load_ee_subject_themes", return_value=(
                (theme,), {self.key: theme.slug},
            )),
            patch.object(Path, "read_text", side_effect=[
                self.payload(), self.payload("Fresh imported heading"),
            ]),
        ):
            content.load_ee_tache_three_author_responses()
            response = content.parse_ee_tache_three_responses((month,))[0]
            self.assertEqual(response.reformulation, "Fresh imported heading")
            self.assertEqual(response.content_key, self.key)


class SemanticManifestContractTests(SimpleTestCase):
    def test_duplicate_fields_cannot_silently_select_a_different_canonical_model(self):
        payload = (
            '{"version": 1, "task": "eo/tache-3", "groups": ['
            '{"id": "group", "canonical": "culture:p1", "canonical": "culture:p2",'
            '"members": ["culture:p1", "culture:p2"], "rationale": "Same subject."}]}'
        )
        with patch.object(Path, "read_text", return_value=payload):
            with self.assertRaisesMessage(ValueError, "Duplicate field"):
                content.load_oral_semantic_groups(
                    "eo/tache-3", ("culture:p1", "culture:p2"),
                    path=Path("semantic.json"),
                )

    def test_equivalence_manifests_reject_duplicate_fields_and_boolean_versions(self):
        loaders = (
            lambda path: content.load_tache_two_equivalent_groups(path),
            lambda path: content.load_ee_equivalent_groups(1, path),
        )
        for load in loaders:
            for payload in (
                '{"version": true, "groups": []}',
                '{"version": 1, "groups": [], "groups": []}',
            ):
                with self.subTest(loader=load, payload=payload):
                    with patch.object(Path, "read_text", return_value=payload):
                        with self.assertRaises(ValueError):
                            load(Path("equivalent.json"))


class CanonicalSlugCacheTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def test_mapping_cannot_be_mutated_and_clear_reloads_equivalences(self):
        first_key = "ee-tache1:janvier:combinaison-1"
        second_key = "ee-tache1:janvier:combinaison-2"
        with (
            patch.object(content, "load_ee_subject_keys", return_value=(first_key, second_key)),
            patch.object(content, "ee_canonical_by_content_key", side_effect=[
                {second_key: first_key}, {},
            ]),
        ):
            first = content.ee_writing_canonical_slug_by_slug(1)
            with self.assertRaises(TypeError):
                first["janvier-combinaison-2"] = "invented-canonical"
            catalogue.clear_catalogue_cache()
            second = content.ee_writing_canonical_slug_by_slug(1)
            self.assertEqual(first["janvier-combinaison-2"], "janvier-combinaison-1")
            self.assertEqual(second["janvier-combinaison-2"], "janvier-combinaison-2")


class SyncContentPreflightTests(SimpleTestCase):
    def setUp(self):
        self.root = Path.cwd() / f".content-contract-{uuid4().hex}"
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        self.source = self.root / "source"
        self.bundle = self.root / "bundle"
        for theme in THEMES:
            source = self.source / "agent_kit" / "theme_data" / theme / "responses"
            source.mkdir(parents=True)
            (source / "batch_01.md").write_text(f"New {theme}", encoding="utf-8")
            destination = self.bundle / "responses" / theme
            destination.mkdir(parents=True)
            (destination / "batch_99.md").write_text(f"Old {theme}", encoding="utf-8")
        (self.source / "anki" / "data").mkdir(parents=True)
        for path in (self.source / "study_sheets.md", self.source / "anki/data/phrases.tsv"):
            path.write_text("New source", encoding="utf-8")
        for path in (self.bundle / "study_sheets.md", self.bundle / "phrases.tsv"):
            path.write_text("Old bundle", encoding="utf-8")
        for name, path in (
            ("RESPONSES_DIR", self.bundle / "responses"),
            ("STUDY_SHEETS_PATH", self.bundle / "study_sheets.md"),
            ("PHRASES_PATH", self.bundle / "phrases.tsv"),
        ):
            mocked = patch.object(content, name, path)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.before = self.bundle_contents()

    def bundle_contents(self):
        return {
            path.relative_to(self.bundle): path.read_bytes()
            for path in self.bundle.rglob("*") if path.is_file()
        }

    def test_missing_last_theme_does_not_erase_any_existing_batches(self):
        shutil.rmtree(self.source / "agent_kit/theme_data" / THEMES[-1] / "responses")
        with self.assertRaises(CommandError):
            call_command("sync_content", source=str(self.source), stdout=StringIO())
        self.assertEqual(self.bundle_contents(), self.before)

    def test_empty_last_theme_does_not_erase_any_existing_batches(self):
        path = self.source / "agent_kit/theme_data" / THEMES[-1] / "responses/batch_01.md"
        path.unlink()
        with self.assertRaises(CommandError):
            call_command("sync_content", source=str(self.source), stdout=StringIO())
        self.assertEqual(self.bundle_contents(), self.before)

    def test_nonfile_source_is_rejected_before_any_destination_changes(self):
        path = self.source / "study_sheets.md"
        path.unlink()
        path.mkdir()
        with self.assertRaises(CommandError):
            call_command("sync_content", source=str(self.source), stdout=StringIO())
        self.assertEqual(self.bundle_contents(), self.before)

    def test_nonfile_last_batch_is_rejected_before_any_destination_changes(self):
        path = self.source / "agent_kit/theme_data" / THEMES[-1] / "responses/batch_01.md"
        path.unlink()
        path.mkdir()
        with self.assertRaises(CommandError):
            call_command("sync_content", source=str(self.source), stdout=StringIO())
        self.assertEqual(self.bundle_contents(), self.before)

    def test_destination_containing_sources_is_rejected_before_deletion(self):
        source_responses = self.source / "agent_kit/theme_data"
        with patch.object(content, "RESPONSES_DIR", source_responses):
            with self.assertRaises(CommandError):
                call_command("sync_content", source=str(self.source), stdout=StringIO())
        for theme in THEMES:
            self.assertEqual(
                (source_responses / theme / "responses/batch_01.md").read_text(),
                f"New {theme}",
            )
        self.assertEqual(self.bundle_contents(), self.before)

    def test_overlapping_source_and_destination_is_rejected_before_deletion(self):
        responses = self.source / "agent_kit/theme_data"
        destination = self.bundle / "responses"
        shutil.rmtree(destination / THEMES[-1])
        (destination / THEMES[-1]).symlink_to(responses / THEMES[-1] / "responses")
        with self.assertRaises(CommandError):
            call_command("sync_content", source=str(self.source), stdout=StringIO())
        self.assertEqual(
            (responses / THEMES[-1] / "responses/batch_01.md").read_text(),
            f"New {THEMES[-1]}",
        )
        for theme in THEMES[:-1]:
            self.assertEqual(
                (destination / theme / "batch_99.md").read_text(), f"Old {theme}"
            )

    def test_valid_source_replaces_stale_batches_and_copies_shared_files(self):
        call_command("sync_content", source=str(self.source), stdout=StringIO())
        for theme in THEMES:
            destination = self.bundle / "responses" / theme
            self.assertEqual(
                (destination / "batch_01.md").read_text(), f"New {theme}"
            )
            self.assertFalse((destination / "batch_99.md").exists())
        self.assertEqual((self.bundle / "study_sheets.md").read_text(), "New source")
        self.assertEqual((self.bundle / "phrases.tsv").read_text(), "New source")
