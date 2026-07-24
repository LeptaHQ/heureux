from __future__ import annotations

import json

from django.test import TestCase
from django.urls import reverse

from study.content_loader import (
    WritingCategoryData,
    WritingSujetData,
    WritingVersionData,
)
from study.management.commands.import_content import Command
from study.models import (
    PersonalWritingResponse,
    WritingSujet,
    WritingSujetCompletion,
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

    def test_detail_shows_best_version_first_with_others_toggle(self):
        page = self.client.get(self._detail_url(self.multi))

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Version A la meilleure.")
        self.assertContains(page, "Voir mes autres versions (2)")
        self.assertContains(page, "Version B.")
        self.assertContains(page, "Version C.")

    def test_detail_single_version_has_no_others_toggle(self):
        page = self.client.get(self._detail_url(self.single))

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Une seule version modèle.")
        self.assertNotContains(page, "Voir mes autres versions")

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

    def test_save_creates_personal_and_detail_shows_ma_version(self):
        result = self.client.post(
            self._edit_url(self.multi),
            {"action": "save", "body": "Coucou, voici ma version à moi."},
        )

        self.assertRedirects(
            result,
            self._detail_url(self.multi) + "?saved=1",
            fetch_redirect_response=False,
        )
        personal = PersonalWritingResponse.objects.get(
            user=self.owner, sujet=self.multi
        )
        self.assertEqual(personal.body, "Coucou, voici ma version à moi.")

        detail = self.client.get(self._detail_url(self.multi))
        self.assertContains(detail, "Ma version")
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

        self.assertContains(page, "subject-row-hit-area")
        self.assertContains(page, "subject-table-row-link")
        self.assertContains(page, "data-writing-sujet-completion-form")

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
        self.assertEqual(payload["version"], 4)
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
