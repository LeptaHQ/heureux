"""Regression coverage for legacy writing identities during isolated imports."""

from io import StringIO
from dataclasses import replace
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from study import content_loader as content
from study.management.commands.import_content import Command
from study.models import (
    Annotation, AnnotationKind, PersonalWritingResponse,
    WritingResponseOverride, WritingSujet, WritingSujetCompletion,
)
from study.writing_responses import model_version_keys, writing_model_versions

from . import factories


class WritingImportIdentityTests(TestCase):
    def setUp(self):
        self.user = factories.make_user()
        self.task = factories.make_task(factories.make_part("ee"), "tache-1")
        self.canonical = factories.make_writing_sujet(
            self.task, slug="janvier-combinaison-1",
            versions=("Original main.", "Original alternative."),
        )
        self.alias = factories.make_writing_sujet(
            self.task, slug="janvier-combinaison-2", versions=("Original alternative.",),
        )
        self.categories = (content.WritingCategoryData(
            slug="invitations", label="Invitations", order=1,
            sujets=tuple(
                content.WritingSujetData(
                    category="invitations", category_label="Invitations",
                    slug=sujet.slug, order=index, prompt=sujet.prompt,
                    versions=(
                        tuple(content.WritingVersionData(version["body"]) for version in sujet.versions)
                        if sujet == self.canonical else ()
                    ),
                    source_key=f"ee-tache1:janvier:combinaison-{index}",
                    canonical_slug=self.canonical.slug,
                )
                for index, sujet in enumerate((self.canonical, self.alias), 1)
            ),
        ),)
        self.command = Command(stdout=StringIO())

    def import_sujets(self):
        self.command._import_writing_sujets(
            self.categories, {"ee/tache-1": self.task}
        )
        self.canonical.refresh_from_db()
        self.alias.refresh_from_db()

    def test_adding_origin_metadata_keeps_private_edit_identity_and_body(self):
        original_key = model_version_keys(self.canonical.model_versions)[1]
        override = WritingResponseOverride.objects.create(
            user=self.user, sujet=self.canonical, version_key=original_key,
            body="My saved alternative.",
        )
        saved_time = override.updated_at
        for _ in range(2):
            self.import_sujets()
            override.refresh_from_db()
            current_key = model_version_keys(self.canonical.model_versions)[1]
            self.assertEqual(override.version_key, current_key)
            self.assertEqual(override.body, "My saved alternative.")
            self.assertEqual(override.updated_at, saved_time)
            self.assertEqual(
                writing_model_versions(self.canonical, {current_key: override})[1]["content"]["body"],
                "My saved alternative.",
            )
            self.assertFalse(WritingSujetCompletion.objects.exists())

    def test_equivalent_alias_keeps_private_alternative_and_deletion(self):
        other = factories.make_user()
        original_key = model_version_keys(self.alias.model_versions)[0]
        overrides = [
            WritingResponseOverride.objects.create(
                user=self.user, sujet=self.alias, version_key=original_key,
                body="A personal alias alternative.",
            ),
            WritingResponseOverride.objects.create(
                user=other, sujet=self.alias, version_key=original_key, is_deleted=True,
            ),
        ]
        for _ in range(2):
            self.import_sujets()
            current_key = model_version_keys(self.canonical.model_versions)[1]
            for override in overrides:
                override.refresh_from_db()
                self.assertEqual(override.sujet_id, self.canonical.pk)
                self.assertEqual(override.version_key, current_key)
            self.assertEqual(overrides[0].body, "A personal alias alternative.")
            self.assertTrue(overrides[1].is_deleted)
            self.assertEqual(
                [row["number"] for row in writing_model_versions(
                    self.canonical, {current_key: overrides[1]}
                )],
                [1],
            )
            self.assertFalse(WritingSujetCompletion.objects.exists())

    def test_existing_canonical_override_wins_without_discarding_alias_edit(self):
        target = WritingResponseOverride.objects.create(
            user=self.user, sujet=self.canonical,
            version_key=model_version_keys([
                {"body": "Original alternative.", "origin": "original"}
            ])[0],
            body="Current canonical edit.",
        )
        source = WritingResponseOverride.objects.create(
            user=self.user, sujet=self.alias,
            version_key=model_version_keys(self.alias.model_versions)[0],
            body="Different alias edit, retained.",
        )
        before = list(WritingResponseOverride.objects.order_by("pk").values())
        for _ in range(2):
            self.import_sujets()
            self.assertEqual(
                list(WritingResponseOverride.objects.order_by("pk").values()), before
            )
        self.assertNotEqual(source.pk, target.pk)

    def highlight(self, sujet, key, quote):
        return Annotation.objects.create(
            user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
            quote=quote, start_offset=0, end_offset=len(quote), body=f"Note for {quote}",
            source_key=f"writing-sujet:{sujet.pk}:{key}",
            source_path=reverse(
                "study:writing_sujet_detail", args=["ee", "tache-1", sujet.pk]
            ),
        )

    def test_unmatched_alias_model_highlight_does_not_attach_to_an_unrelated_model(self):
        self.alias.versions = [{"body": "Retired alias model."}]
        self.alias.save(update_fields=["versions"])
        highlight = self.highlight(self.alias, "model-1", "Retired")
        before = Annotation.objects.values().get(pk=highlight.pk)
        for _ in range(2):
            self.import_sujets()
            self.assertEqual(Annotation.objects.values().get(pk=highlight.pk), before)

    def test_conflicting_personal_drafts_and_their_highlights_are_both_preserved(self):
        for sujet, body in (
            (self.canonical, "Existing canonical draft."),
            (self.alias, "Newer different alias draft."),
        ):
            PersonalWritingResponse.objects.create(user=self.user, sujet=sujet, body=body)
            self.highlight(sujet, "personal", body[:7])
        drafts = list(PersonalWritingResponse.objects.order_by("pk").values())
        marks = list(Annotation.objects.order_by("pk").values())
        for _ in range(2):
            self.import_sujets()
            self.assertEqual(list(PersonalWritingResponse.objects.order_by("pk").values()), drafts)
            self.assertEqual(list(Annotation.objects.order_by("pk").values()), marks)
            self.assertFalse(WritingSujetCompletion.objects.exists())

    def test_reordering_into_a_removed_model_slot_keeps_both_highlights(self):
        self.canonical.versions = [
            {"body": "Original alternative."}, {"body": "Removed old model."}
        ]
        self.canonical.save(update_fields=["versions"])
        original = self.highlight(self.canonical, "model-1", "Original")
        retired = self.highlight(self.canonical, "model-2", "Removed ")
        previous_key = model_version_keys(self.canonical.model_versions)[1]
        for _ in range(2):
            self.import_sujets()
            original.refresh_from_db()
            retired.refresh_from_db()
            self.assertEqual(
                original.source_key, f"writing-sujet:{self.canonical.pk}:model-2"
            )
            self.assertEqual(
                retired.source_key,
                f"writing-sujet:{self.canonical.pk}:archived-model-{previous_key}",
            )
            self.assertEqual(original.quote, "Original")
            self.assertEqual(retired.quote, "Removed ")
            self.assertEqual(Annotation.objects.count(), 2)
            self.assertFalse(Annotation.objects.filter(source_key__startswith="writing-import:").exists())
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("study:annotations_for_source"), {"source_path": retired.source_path}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row["id"] for row in response.json()["highlights"]}, {original.pk, retired.pk}
        )

    def test_moving_one_users_draft_does_not_move_another_users_conflicting_marks(self):
        other = factories.make_user()
        for user, sujet in (
            (self.user, self.canonical), (self.user, self.alias), (other, self.alias),
        ):
            PersonalWritingResponse.objects.create(user=user, sujet=sujet, body=f"Draft {user.pk}/{sujet.pk}")
        retained = self.highlight(self.alias, "personal", "Retained")
        moved = self.highlight(self.alias, "personal:paragraph", "Moved")
        moved.user = other
        moved.save(update_fields=["user"])
        for _ in range(2):
            self.import_sujets()
            retained.refresh_from_db()
            moved.refresh_from_db()
            self.assertEqual(retained.source_key, f"writing-sujet:{self.alias.pk}:personal")
            self.assertEqual(moved.source_key, f"writing-sujet:{self.canonical.pk}:personal:paragraph")

    def test_failed_writing_reconciliation_rolls_back_the_shared_import(self):
        before = list(WritingSujet.objects.order_by("pk").values())
        with patch.object(self.command, "_reconcile_writing_sujet_state", side_effect=ValueError("invalid keys")):
            with self.assertRaisesMessage(ValueError, "invalid keys"):
                self.import_sujets()
        self.assertEqual(list(WritingSujet.objects.order_by("pk").values()), before)

    def test_identical_models_keep_separate_override_and_annotation_identities(self):
        for include_origin in (False, True):
            with self.subTest(include_origin=include_origin):
                WritingResponseOverride.objects.all().delete()
                Annotation.objects.all().delete()
                self.canonical.versions = [
                    {"body": "Identical model.", **({"origin": "original"} if include_origin else {})},
                    {"body": "Identical model.", **({"origin": "original"} if include_origin else {})},
                ]
                self.canonical.save(update_fields=["versions"])
                source = replace(
                    self.categories[0].sujets[0],
                    versions=tuple(content.WritingVersionData("Identical model.") for _ in range(2)),
                )
                categories = (replace(self.categories[0], sujets=(source,)),)
                keys = model_version_keys(self.canonical.model_versions)
                edits = [
                    WritingResponseOverride.objects.create(
                        user=self.user, sujet=self.canonical, version_key=key,
                        body=f"Personal model {number}",
                    )
                    for number, key in enumerate(keys, 1)
                ]
                marks = [
                    self.highlight(self.canonical, f"model-{number}", "Identical")
                    for number in (1, 2)
                ]
                for _ in range(2):
                    self.command._import_writing_sujets(categories, {"ee/tache-1": self.task})
                    self.canonical.refresh_from_db()
                    current_keys = model_version_keys(self.canonical.model_versions)
                    for number, (edit, mark) in enumerate(zip(edits, marks), 1):
                        edit.refresh_from_db()
                        mark.refresh_from_db()
                        self.assertEqual(edit.version_key, current_keys[number - 1])
                        self.assertEqual(mark.source_key, f"writing-sujet:{self.canonical.pk}:model-{number}")
