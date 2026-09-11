from __future__ import annotations

import json
import re

from django.test import Client, TestCase
from django.urls import reverse

from study.content_loader import (
    WritingCategoryData,
    WritingSujetData,
    WritingVersionData,
)
from study.management.commands.import_content import Command
from study.models import (
    Annotation,
    AnnotationKind,
    PersonalWritingResponse,
    WritingSujet,
    WritingSujetCompletion,
    WritingResponseOverride,
)

from . import factories


def _category(slug, label, *sujets):
    return WritingCategoryData(slug=slug, label=label, order=1, sujets=tuple(sujets))


def _sujet(slug, prompt, *bodies, category="invitations", label="Invitations"):
    return WritingSujetData(
        category=category,
        category_label=label,
        slug=slug,
        order=1,
        prompt=prompt,
        versions=tuple(WritingVersionData(body=body) for body in bodies),
    )


class WritingSujetImportTests(TestCase):
    def setUp(self):
        self.part = factories.make_part("ee")
        self.task = factories.make_task(self.part, "tache-1")
        self.task_by_slug = {"ee/tache-1": self.task}

    def _import(self, *categories):
        Command()._import_writing_sujets(categories, self.task_by_slug)

    def test_import_creates_grouped_sujets_with_best_first_versions(self):
        self._import(
            _category(
                "invitations",
                "Invitations",
                _sujet("mariage", "Invitez un ami.", "Meilleure.", "Autre."),
            ),
            _category(
                "sorties",
                "Sorties",
                _sujet("resto", "Proposez un resto.", category="sorties",
                       label="Sorties"),
            ),
        )

        sujets = list(WritingSujet.objects.order_by("order"))
        self.assertEqual(len(sujets), 2)
        first, second = sujets
        self.assertEqual(first.slug, "mariage")
        self.assertEqual(first.category, "invitations")
        self.assertEqual(first.category_label, "Invitations")
        self.assertEqual(first.order, 1)
        self.assertEqual(first.versions, [{"body": "Meilleure."}, {"body": "Autre."}])
        self.assertTrue(first.has_model_response)
        self.assertEqual(second.category, "sorties")
        self.assertEqual(second.order, 2)
        self.assertEqual(second.model_versions, [])
        self.assertFalse(second.has_model_response)

    def test_reimport_is_idempotent_and_preserves_learner_versions(self):
        self._import(
            _category(
                "invitations",
                "Invitations",
                _sujet("mariage", "Invitez un ami.", "Modèle."),
            )
        )
        sujet = WritingSujet.objects.get(slug="mariage")
        owner = factories.make_user("t1-import-owner")
        PersonalWritingResponse.objects.create(
            user=owner,
            sujet=sujet,
            body="Ma réponse personnelle.",
        )

        self._import(
            _category(
                "invitations",
                "Invitations",
                _sujet("mariage", "Invitez un ami.", "Modèle révisé."),
            )
        )

        self.assertEqual(WritingSujet.objects.count(), 1)
        sujet.refresh_from_db()
        self.assertEqual(sujet.versions, [{"body": "Modèle révisé."}])
        personal = PersonalWritingResponse.objects.get(user=owner, sujet=sujet)
        self.assertEqual(personal.body, "Ma réponse personnelle.")

    def test_removed_sujets_are_deactivated_not_deleted(self):
        self._import(
            _category(
                "invitations",
                "Invitations",
                _sujet("mariage", "Invitez un ami.", "Modèle."),
                _sujet("diner", "Invitez à dîner.", "Modèle."),
            )
        )
        dropped = WritingSujet.objects.get(slug="diner")
        owner = factories.make_user("t1-drop-owner")
        PersonalWritingResponse.objects.create(
            user=owner, sujet=dropped, body="Gardez-moi."
        )

        self._import(
            _category(
                "invitations",
                "Invitations",
                _sujet("mariage", "Invitez un ami.", "Modèle."),
            )
        )

        dropped.refresh_from_db()
        self.assertFalse(dropped.is_active)
        self.assertTrue(WritingSujet.objects.get(slug="mariage").is_active)
        self.assertTrue(
            PersonalWritingResponse.objects.filter(sujet=dropped).exists()
        )

    def test_missing_task_deactivates_all_sujets(self):
        self._import(
            _category(
                "invitations",
                "Invitations",
                _sujet("mariage", "Invitez un ami.", "Modèle."),
            )
        )

        Command()._import_writing_sujets((), {})

        self.assertFalse(WritingSujet.objects.filter(is_active=True).exists())
        self.assertEqual(WritingSujet.objects.count(), 1)


class WritingSujetViewTests(TestCase):
    def setUp(self):
        self.part = factories.make_part("ee")
        self.task = factories.make_task(self.part, "tache-1")
        self.owner = factories.make_user("t1-owner")
        self.other = factories.make_user("t1-other")
        self.multi = factories.make_writing_sujet(
            self.task,
            slug="chateau",
            category="invitations",
            category_label="Invitations",
            prompt="Invitez Cédric au château.",
            versions=("Version A la meilleure.", "Version B.", "Version C."),
            order=1,
        )
        self.single = factories.make_writing_sujet(
            self.task,
            slug="sortie",
            category="sorties",
            category_label="Sorties",
            prompt="Proposez une sortie ce week-end.",
            versions=("Une seule version modèle.",),
            order=2,
        )
        self.empty = factories.make_writing_sujet(
            self.task,
            slug="a-rediger",
            category="sorties",
            category_label="Sorties",
            prompt="Sujet encore sans réponse.",
            versions=(),
            order=3,
        )
        self.client.force_login(self.owner)

    def _detail_url(self, sujet):
        return reverse(
            "study:writing_sujet_detail",
            args=["ee", "tache-1", sujet.pk],
        )

    def _edit_url(self, sujet):
        return reverse(
            "study:writing_sujet_edit",
            args=["ee", "tache-1", sujet.pk],
        )

    def _completion_url(self, sujet):
        return reverse(
            "study:writing_sujet_completion",
            args=["ee", "tache-1", sujet.pk],
        )

    def _version_delete_url(self, sujet, card):
        return reverse(
            "study:writing_response_delete",
            args=["ee", sujet.task.slug, sujet.pk, card["key"]],
        )

    def test_main_response_has_edit_but_no_delete_and_rejects_direct_deletion(self):
        page = self.client.get(self._detail_url(self.multi))
        main = re.search(
            r'<section[^>]+aria-labelledby="t1-model-label">(.*?)</section>',
            page.content.decode(), re.DOTALL,
        ).group(1)
        self.assertIn("data-writing-response-edit", main)
        self.assertNotIn("data-writing-response-delete", main)
        self.assertContains(page, "data-writing-response-delete", count=2)
        url = self._version_delete_url(self.multi, page.context["primary_version_card"])
        self.assertEqual(self.client.get(url).status_code, 405)
        rejected = self.client.post(url)
        self.assertEqual(rejected.status_code, 400)
        self.assertContains(rejected, "principale", status_code=400)
        self.assertFalse(WritingResponseOverride.objects.exists())
        edit = self.client.get(self._edit_url(self.multi))
        self.assertEqual(edit.context["body_value"], self.multi.model_versions[0]["body"])
        self.assertNotContains(edit, "Supprimer ma version")

    def test_delete_alternative_keeps_main_and_original_copy_and_annotation_numbers(self):
        original = list(self.multi.versions)
        page = self.client.get(self._detail_url(self.multi))
        cards = page.context["model_version_cards"]
        annotation = Annotation.objects.create(
            user=self.owner, task=self.task, kind=AnnotationKind.HIGHLIGHT,
            source_path=self._detail_url(self.multi),
            source_key=f"writing-sujet:{self.multi.pk}:model-3",
            quote="Version C.", start_offset=0, end_offset=10,
        )
        response = self.client.post(self._version_delete_url(self.multi, cards[1]) + "?deduplicate=0")
        self.assertRedirects(response, self._detail_url(self.multi) + "?deleted=1&deduplicate=0")
        page = self.client.get(self._detail_url(self.multi))
        self.assertEqual([card["number"] for card in page.context["model_version_cards"]], [1, 3])
        self.assertEqual(page.context["primary_version"], original[0])
        self.assertEqual(page.context["response_copy_texts"], {
            "model-1": original[0]["body"], "model-3": original[2]["body"],
        })
        self.assertContains(page, f'data-annotation-source-key="writing-sujet:{self.multi.pk}:model-3"')
        self.assertNotContains(page, "Version B.")
        self.multi.refresh_from_db()
        annotation.refresh_from_db()
        self.assertEqual(self.multi.versions, original)
        self.assertEqual(annotation.quote, "Version C.")
        self.assertFalse(PersonalWritingResponse.objects.filter(user=self.owner).exists())

    def test_personal_main_is_kept_when_every_model_is_deleted(self):
        personal = PersonalWritingResponse.objects.create(
            user=self.owner, sujet=self.multi, body="Ma réponse principale, intacte.",
        )
        WritingSujetCompletion.objects.create(user=self.owner, sujet=self.multi)
        page = self.client.get(self._detail_url(self.multi))
        self.assertContains(page, "data-writing-response-delete", count=3)
        for card in page.context["model_version_cards"]:
            self.assertEqual(self.client.post(self._version_delete_url(self.multi, card)).status_code, 302)
        page = self.client.get(self._detail_url(self.multi))
        self.assertContains(page, personal.body)
        self.assertNotContains(page, "data-writing-response-delete")
        self.assertNotContains(page, "Voir la réponse modèle")
        self.assertEqual(page.context["response_copy_texts"], {"personal": personal.body})
        self.assertEqual(page.context["writing_progress"].status, "done")
        personal.refresh_from_db()
        self.assertEqual(personal.body, "Ma réponse principale, intacte.")
        directory = self.client.get(reverse("study:task_browse", args=["ee", "tache-1"]))
        row = next(row for category in directory.context["categories"]
                   for row in category["sujets"] if row["sujet"].pk == self.multi.pk)
        self.assertEqual(row["version_count"], 1)
        self.client.force_login(self.other)
        other_page = self.client.get(self._detail_url(self.multi))
        self.assertEqual(len(other_page.context["model_versions"]), 3)
        self.assertNotContains(other_page, personal.body)

    def test_editing_one_alternative_does_not_replace_the_main_response(self):
        original = list(self.multi.versions)
        page = self.client.get(self._detail_url(self.multi))
        card = page.context["model_version_cards"][1]
        url = card["edit_url"] + "&deduplicate=0"
        editor = self.client.get(url)
        self.assertEqual(editor.context["body_value"], original[1]["body"])
        self.assertTrue(editor.context["editing_model_version"])
        invalid = self.client.post(url, {"body": "  "})
        self.assertContains(invalid, "ne peut pas être vide")
        self.assertFalse(WritingResponseOverride.objects.exists())
        changed = "Autre réponse modifiée.\n\nUn deuxième paragraphe."
        saved = self.client.post(url, {"body": changed})
        self.assertRedirects(saved, self._detail_url(self.multi) + "?saved=1&deduplicate=0")
        page = self.client.get(self._detail_url(self.multi))
        self.assertEqual(page.context["primary_version"], original[0])
        self.assertEqual(page.context["response_copy_texts"]["model-2"], changed)
        self.assertEqual(page.context["model_version_cards"][1]["key"], card["key"])
        self.assertEqual(page.context["writing_progress"].status, "active")
        self.assertFalse(PersonalWritingResponse.objects.filter(user=self.owner).exists())
        self.multi.refresh_from_db()
        self.assertEqual(self.multi.versions, original)
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(url).context["body_value"], original[1]["body"],
        )

    def test_edit_delete_validate_version_scope_csrf_and_stale_links(self):
        page = self.client.get(self._detail_url(self.multi))
        card = page.context["model_version_cards"][1]
        url = self._version_delete_url(self.multi, card)
        secured = Client(enforce_csrf_checks=True)
        secured.force_login(self.owner)
        self.assertEqual(secured.post(url).status_code, 403)
        self.assertEqual(self.client.get(self._edit_url(self.multi) + "?version=invalid").status_code, 404)
        wrong_task = reverse(
            "study:writing_response_delete", args=["ee", "tache-2", self.multi.pk, card["key"]],
        )
        self.assertEqual(self.client.post(wrong_task).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self.client.get(card["edit_url"]).status_code, 404)
        self.assertEqual(self.client.post(card["edit_url"], {"body": "Stale edit"}).status_code, 404)
        self.assertTrue(WritingResponseOverride.objects.get(user=self.owner).is_deleted)

    def test_second_writing_task_has_the_same_response_controls(self):
        task = factories.make_task(self.part, "tache-2")
        sujet = factories.make_writing_sujet(task, versions=("Récit principal.", "Autre récit."))
        url = reverse("study:writing_sujet_detail", args=["ee", task.slug, sujet.pk])
        page = self.client.get(url)
        self.assertContains(page, "data-writing-response-edit", count=2)
        self.assertContains(page, "data-writing-response-delete", count=1)
        card = page.context["model_version_cards"][1]
        self.assertEqual(self.client.post(card["edit_url"], {"body": "Mon autre récit."}).status_code, 302)
        self.assertContains(self.client.get(url), "Mon autre récit.")
        self.assertEqual(self.client.post(self._version_delete_url(sujet, card)).status_code, 302)
        final = self.client.get(url)
        self.assertContains(final, "Récit principal.")
        self.assertNotContains(final, "Mon autre récit.")
        self.assertNotContains(final, "data-writing-response-delete")

    def test_identical_models_have_distinct_controls(self):
        self.multi.versions = [{"body": "Identique."}, {"body": "Identique."}]
        self.multi.save(update_fields=["versions"])
        cards = self.client.get(self._detail_url(self.multi)).context["model_version_cards"]
        self.assertNotEqual(cards[0]["key"], cards[1]["key"])
        self.assertEqual(self.client.post(self._version_delete_url(self.multi, cards[1])).status_code, 302)
        page = self.client.get(self._detail_url(self.multi))
        self.assertEqual(len(page.context["model_versions"]), 1)
        self.assertEqual(page.context["primary_version_card"]["key"], cards[0]["key"])

    def test_task_detail_and_browse_list_categories(self):
        for name in ("task_detail", "task_browse"):
            page = self.client.get(
                reverse(f"study:{name}", args=["ee", "tache-1"])
            )
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, "Invitations")
            self.assertContains(page, "Sorties")
            self.assertContains(page, "Invitez Cédric au château.")
            self.assertContains(page, "À rédiger")

    def test_subject_without_a_response_has_no_response_copy_button(self):
        page = self.client.get(self._detail_url(self.empty))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["response_copy_texts"], {})
        self.assertNotContains(
            page, 'data-prompt-copy-source="ee-writing-response-content"'
        )

    def test_subject_directory_search_finds_writing_prompts(self):
        directory = self.client.get(
            reverse("study:task_browse", args=["ee", "tache-1"])
        )
        results = self.client.get(
            reverse("study:task_search", args=["ee", "tache-1"]),
            {"q": "château", "scope": "subjects"},
        )

        self.assertContains(directory, "data-subject-directory-search")
        self.assertEqual(results.context["writing_sujet_result_count"], 1)
        self.assertEqual(results.context["result_count"], 1)
        self.assertContains(results, self.multi.prompt)
        self.assertContains(results, self._detail_url(self.multi))
        self.assertNotContains(results, self.single.prompt)

    def test_table_groups_subjects_by_theme(self):
        page = self.client.get(
            reverse("study:task_browse", args=["ee", "tache-1"])
        )

        self.assertContains(page, "data-t1-table-theme", count=2)
        self.assertContains(page, "data-t1-table-subject", count=3)
        self.assertNotContains(page, 'class="t1-table__theme"')
        self.assertContains(page, "Sujets du thème Invitations")
        self.assertContains(page, "Sujets du thème Sorties")

    def test_response_highlight_sets_only_its_sujet_in_progress(self):
        source_path = self._detail_url(self.multi)
        source_key = f"writing-sujet:{self.multi.pk}:model-1"

        detail = self.client.get(source_path)
        self.assertContains(
            detail,
            f'data-annotation-source-key="{source_key}"',
        )
        created = self.client.post(
            reverse("study:annotation_create"),
            {
                "kind": AnnotationKind.HIGHLIGHT,
                "quote": "Version A la meilleure.",
                "start_offset": "0",
                "end_offset": "24",
                "prefix": "",
                "suffix": "",
                "source_path": source_path,
                "source_key": source_key,
                "source_title": "Sujet Tâche 1",
                "task_id": str(self.task.pk),
                "overlap_ids": "",
            },
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(
            created.json()["writing_sujet_progress"],
            {
                "sujet_id": self.multi.pk,
                "completed": False,
                "sujet": {"status": "active", "label": "En cours"},
            },
        )
        browse = self.client.get(
            reverse("study:task_browse", args=["ee", "tache-1"])
        )
        progress_by_sujet = {
            row["sujet"].pk: row["progress"]
            for category in browse.context["categories"]
            for row in category["sujets"]
        }
        self.assertEqual(progress_by_sujet[self.multi.pk].status, "active")
        self.assertEqual(progress_by_sujet[self.single.pk].status, "new")
        self.assertEqual(browse.context["subject_progress"].started, 1)

        part_page = self.client.get(reverse("study:part_detail", args=["ee"]))
        task_card = next(
            item
            for item in part_page.context["tasks"]
            if item["task"].pk == self.task.pk
        )
        self.assertEqual(task_card["stats"]["seen"], 1)
        self.assertEqual(task_card["stats"]["started_new"], 1)

        deleted = self.client.post(
            reverse(
                "study:annotation_delete",
                args=[created.json()["id"]],
            ),
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertEqual(
            deleted.json()["writing_sujet_progress"]["sujet"],
            {"status": "new", "label": "À commencer"},
        )
        self.assertEqual(
            self.client.get(source_path).context["writing_progress"].status,
            "new",
        )

    def test_detail_shows_best_version_first_with_others_toggle(self):
        page = self.client.get(self._detail_url(self.multi))

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Version A la meilleure.")
        self.assertContains(page, "Voir les autres versions (2)")
        self.assertContains(page, "Version B.")
        self.assertContains(page, "Version C.")

    def test_detail_single_version_has_no_others_toggle(self):
        page = self.client.get(self._detail_url(self.single))

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Une seule version modèle.")
        self.assertNotContains(page, "Voir les autres versions")

    def test_detail_topic_only_shows_empty_state(self):
        page = self.client.get(self._detail_url(self.empty))

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "n'a pas encore de réponse modèle")
        self.assertContains(page, "Personnaliser la réponse")

    def test_edit_renders_textarea_and_model_reference(self):
        page = self.client.get(self._edit_url(self.multi))

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'name="body"')
        self.assertContains(page, "Invitez Cédric au château.")
        self.assertContains(page, "Version A la meilleure.")

    def test_save_creates_personal_and_preserves_publication_selection(self):
        result = self.client.post(
            self._edit_url(self.multi) + "?deduplicate=0",
            {"action": "save", "body": "Coucou, voici ma version à moi."},
        )

        self.assertRedirects(
            result,
            self._detail_url(self.multi) + "?saved=1&deduplicate=0",
            fetch_redirect_response=False,
        )
        personal = PersonalWritingResponse.objects.get(
            user=self.owner, sujet=self.multi
        )
        self.assertEqual(personal.body, "Coucou, voici ma version à moi.")

        detail = self.client.get(result.url)
        self.assertContains(detail, 'id="t1-personal-label">Réponse</div>')
        self.assertContains(detail, "Coucou, voici ma version à moi.")
        self.assertContains(detail, "Voir la réponse modèle")
        self.assertContains(detail, "En cours")
        self.assertNotContains(detail, "Sujet terminé")

    def test_completion_is_explicit_and_reversible(self):
        self.client.post(
            self._edit_url(self.multi),
            {"action": "save", "body": "Ma réponse personnalisée."},
        )

        before = self.client.get(
            reverse("study:task_detail", args=["ee", "tache-1"])
        )
        self.assertContains(before, "En cours")
        self.assertNotContains(before, "Sujet terminé")

        completed = self.client.post(
            self._completion_url(self.multi),
            {"completed": "1"},
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="fetch",
        )

        self.assertEqual(completed.status_code, 200)
        self.assertEqual(
            completed.json()["sujet"],
            {"status": "done", "label": "Terminé"},
        )
        self.assertTrue(
            WritingSujetCompletion.objects.filter(
                user=self.owner,
                sujet=self.multi,
            ).exists()
        )

        reopened = self.client.post(
            self._completion_url(self.multi),
            {"completed": "0"},
            HTTP_ACCEPT="application/json",
            HTTP_X_REQUESTED_WITH="fetch",
        )

        self.assertEqual(
            reopened.json()["sujet"],
            {"status": "active", "label": "En cours"},
        )
        self.assertFalse(
            WritingSujetCompletion.objects.filter(
                user=self.owner,
                sujet=self.multi,
            ).exists()
        )

    def test_completion_is_private_and_rejects_invalid_state(self):
        WritingSujetCompletion.objects.create(
            user=self.owner,
            sujet=self.multi,
        )
        self.client.force_login(self.other)

        page = self.client.get(self._detail_url(self.multi))
        self.assertNotContains(page, "Sujet terminé")
        invalid = self.client.post(
            self._completion_url(self.multi),
            {"completed": "yes"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(
            WritingSujetCompletion.objects.filter(
                sujet=self.multi,
            ).count(),
            1,
        )

    def test_completion_controls_and_full_row_links_are_rendered(self):
        page = self.client.get(
            reverse("study:task_detail", args=["ee", "tache-1"])
        )

        self.assertContains(page, "data-subject-collection-row", count=3)
        self.assertContains(page, "subject-table-row-link", count=3)
        self.assertContains(page, "data-writing-sujet-completion-form", count=3)
        self.assertNotContains(page, "data-collection-view-panel")

    def test_account_export_and_reset_include_owned_writing_progress(self):
        personal = PersonalWritingResponse.objects.create(
            user=self.owner,
            sujet=self.multi,
            body="Ma réponse.",
        )
        completion = WritingSujetCompletion.objects.create(
            user=self.owner,
            sujet=self.multi,
        )
        PersonalWritingResponse.objects.create(
            user=self.other,
            sujet=self.single,
            body="Réponse privée.",
        )
        WritingSujetCompletion.objects.create(
            user=self.other,
            sujet=self.single,
        )

        payload = json.loads(
            self.client.get(reverse("study:export_account")).content
        )
        self.assertEqual(payload["version"], 10)
        self.assertEqual(
            payload["personal_writing_responses"],
            [
                {
                    "part": "ee",
                    "task": "tache-1",
                    "sujet": "chateau",
                    "body": "Ma réponse.",
                    "created_at": personal.created_at.isoformat(
                        timespec="milliseconds"
                    ).replace("+00:00", "Z"),
                    "updated_at": personal.updated_at.isoformat(
                        timespec="milliseconds"
                    ).replace("+00:00", "Z"),
                }
            ],
        )
        self.assertEqual(
            payload["writing_sujet_completions"],
            [
                {
                    "part": "ee",
                    "task": "tache-1",
                    "sujet": "chateau",
                    "completed_at": completion.completed_at.isoformat(
                        timespec="milliseconds"
                    ).replace("+00:00", "Z"),
                }
            ],
        )

        reset = self.client.post(
            reverse("study:reset_progress"),
            {
                "current_pin": "123456",
                "confirmation": "REINITIALISER",
            },
        )
        self.assertEqual(reset.status_code, 302)
        self.assertTrue(
            PersonalWritingResponse.objects.filter(user=self.owner).exists()
        )
        self.assertFalse(
            WritingSujetCompletion.objects.filter(user=self.owner).exists()
        )
        self.assertTrue(
            PersonalWritingResponse.objects.filter(user=self.other).exists()
        )
        self.assertTrue(
            WritingSujetCompletion.objects.filter(user=self.other).exists()
        )

    def test_save_rejects_empty_body(self):
        page = self.client.post(
            self._edit_url(self.multi),
            {"action": "save", "body": "   "},
        )

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "ne peut pas être vide")
        self.assertFalse(
            PersonalWritingResponse.objects.filter(
                user=self.owner, sujet=self.multi
            ).exists()
        )

    def test_save_updates_existing_personal_without_duplicating(self):
        url = self._edit_url(self.multi)
        self.client.post(url, {"action": "save", "body": "Première version."})
        self.client.post(url, {"action": "save", "body": "Version corrigée."})

        personal = PersonalWritingResponse.objects.get(
            user=self.owner, sujet=self.multi
        )
        self.assertEqual(personal.body, "Version corrigée.")
        self.assertEqual(
            PersonalWritingResponse.objects.filter(sujet=self.multi).count(), 1
        )

    def test_reset_deletes_personal_version(self):
        self.client.post(
            self._edit_url(self.multi),
            {"action": "save", "body": "À supprimer."},
        )

        result = self.client.post(
            self._edit_url(self.multi), {"action": "reset"}
        )

        self.assertRedirects(
            result,
            self._detail_url(self.multi) + "?reset=1",
            fetch_redirect_response=False,
        )
        self.assertFalse(
            PersonalWritingResponse.objects.filter(
                user=self.owner, sujet=self.multi
            ).exists()
        )
        detail = self.client.get(self._detail_url(self.multi))
        self.assertNotContains(detail, "Ma version")

    def test_personal_version_stays_private_to_its_owner(self):
        self.client.post(
            self._edit_url(self.multi),
            {"action": "save", "body": "Secret de l'auteur."},
        )

        self.client.force_login(self.other)
        detail = self.client.get(self._detail_url(self.multi))

        self.assertNotContains(detail, "Secret de l'auteur.")
        self.assertContains(detail, "Version A la meilleure.")
        self.assertNotContains(detail, "Ma version")

    def test_writing_routes_reject_non_ee_tache_one_tasks(self):
        eo = factories.make_part("eo")
        factories.make_task(eo, "tache-3")

        detail = self.client.get(
            reverse(
                "study:writing_sujet_detail",
                args=["eo", "tache-3", self.multi.pk],
            )
        )
        edit = self.client.get(
            reverse(
                "study:writing_sujet_edit",
                args=["eo", "tache-3", self.multi.pk],
            )
        )

        self.assertEqual(detail.status_code, 404)
        self.assertEqual(edit.status_code, 404)
