from importlib import import_module
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from django.apps import apps
from django.db import connection
from django.test import TestCase, tag
from django.urls import reverse
from django.utils import timezone

from study.models import Annotation, AnnotationKind

from . import factories


class StandaloneNoteGroupTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("note-grouping")
        self.ee = factories.make_task(factories.make_part("ee"), "tache-1")
        self.eo = factories.make_task(factories.make_part("eo"), "tache-2")
        self.personal_url = reverse("study:custom_notes")
        self.client.force_login(self.user)

    def folder(self, task):
        return reverse("study:task_notes", args=[task.part.slug, task.slug])

    def test_every_new_note_defaults_to_personal_regardless_of_the_open_folder(self):
        for index, url in enumerate((
            reverse("study:notes_overview"), reverse("study:general_notes"), self.personal_url,
            self.folder(self.ee), self.folder(self.eo),
            reverse("study:comprehension_notes", args=["ecrite"]),
            reverse("study:comprehension_notes", args=["orale"]),
        )):
            with self.subTest(folder=url):
                page = self.client.get(url)
                self.assertIsNone(page.context["form"]["task"].value())
                saved = self.client.post(url, {
                    "title": f"Impératif {index}", "body": "Prends ! Prenons ! Prenez !",
                    "next": url + "?status=done&page=2",
                })
                note = Annotation.objects.get(user=self.user, title=f"Impératif {index}")
                self.assertIsNone(note.task_id)
                self.assertEqual((note.quote, note.source_path, note.source_key), ("", "", ""))
                self.assertEqual(saved.status_code, 302)
                destination = urlsplit(saved.url)
                self.assertEqual(destination.path, self.personal_url)
                self.assertEqual(destination.fragment, f"note-{note.pk}")
                self.assertFalse({"q", "status", "page"} & parse_qs(destination.query).keys())

    def test_an_explicit_group_wins_over_the_open_folder_without_fabricating_a_source(self):
        saved = self.client.post(self.folder(self.ee), {
            "task": str(self.eo.pk), "title": "Une note EO", "body": "Ma note volontairement classée.",
            "next": self.folder(self.ee) + "?q=ancien",
        })
        note = Annotation.objects.get(user=self.user)
        self.assertEqual(note.task_id, self.eo.pk)
        self.assertEqual((note.quote, note.source_path, note.source_key), ("", "", ""))
        self.assertRedirects(
            saved, self.folder(self.eo) + f"?tab=notes#note-{note.pk}",
            fetch_redirect_response=False,
        )
        self.assertIsNone(self.client.get(self.folder(self.eo)).context["form"]["task"].value())
        self.assertEqual(Annotation.objects.get(pk=note.pk).task_id, self.eo.pk)

    def test_invalid_or_retired_groups_show_errors_without_creating_a_note(self):
        inactive = factories.make_task(self.ee.part, "retired")
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        for value in ("invalid", "-1", "999999999", str(inactive.pk)):
            with self.subTest(group=value):
                response = self.client.post(self.folder(self.ee), {
                    "task": value, "title": "Mon brouillon", "body": "Ne pas perdre mon texte.",
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn("task", response.context["form"].errors)
                self.assertContains(response, "Ne pas perdre mon texte.")
                self.assertContains(response, "data-dialog-open-on-load")
                self.assertFalse(Annotation.objects.filter(user=self.user).exists())

    def test_editing_a_contextual_note_does_not_reset_its_group(self):
        note = Annotation.objects.create(
            user=self.user, task=self.ee, kind=AnnotationKind.NOTE, body="Avant.",
            quote="Passage", source_path="/expression/ecrite/tache-1/",
            source_key="writing-example", completed_at=timezone.now(), study_later=True,
        )
        before = Annotation.objects.values().get(pk=note.pk)
        response = self.client.post(
            reverse("study:annotation_update", args=[note.pk]), {"body": "Après."},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertEqual(response.status_code, 200)
        after = Annotation.objects.values().get(pk=note.pk)
        for field in ("task_id", "quote", "source_path", "source_key", "created_at", "completed_at", "study_later"):
            self.assertEqual(after[field], before[field])
        self.assertEqual(after["body"], "Après.")

    def test_notes_captured_from_expression_keep_their_content_task(self):
        for task in (self.ee, self.eo):
            with self.subTest(task=task.slug, part=task.part.slug):
                path = reverse("study:task_detail", args=[task.part.slug, task.slug])
                response = self.client.post(reverse("study:annotation_create"), {
                    "kind": "note", "body": "Note sur ce passage.", "quote": "Passage",
                    "source_path": path, "source_key": f"task:{task.pk}",
                    "task_id": str(task.pk), "start_offset": "0", "end_offset": "7",
                })
                self.assertEqual(response.status_code, 201)
                note = Annotation.objects.get(pk=response.json()["id"])
                self.assertEqual(note.task_id, task.pk)
                self.assertEqual(note.source_path, path)
                self.assertEqual(note.quote, "Passage")


@tag("database-locking")
class StandaloneNoteMigrationTests(TestCase):
    def test_only_old_standalone_notes_are_reclassified_without_changing_other_fields(self):
        user = factories.make_user("note-migration")
        task = factories.make_task(factories.make_part("ee"), "tache-1")
        standalone = Annotation.objects.create(
            user=user, task=task, kind=AnnotationKind.NOTE, title="Impératif",
            body="| Sujet | Impératif |\n| --- | --- |\n| tu | Prends ! |",
            study_later=True, completed_at=timezone.now(),
        )
        cases = (
            {"kind": AnnotationKind.NOTE, "quote": "Un extrait"},
            {"kind": AnnotationKind.NOTE, "source_path": "/expression/ecrite/tache-1/"},
            {"kind": AnnotationKind.NOTE, "source_key": "response:example"},
            {"kind": AnnotationKind.HIGHLIGHT, "quote": "Un surlignage", "start_offset": 0, "end_offset": 13},
        )
        for fields in cases:
            Annotation.objects.create(user=user, task=task, body="À conserver.", **fields)
        before = {row["id"]: row for row in Annotation.objects.values()}
        migration = import_module("study.migrations.0057_standalone_notes_are_personal")
        for _ in range(2):
            migration.restore_personal_note_groups(apps, SimpleNamespace(connection=connection))
        after = {row["id"]: row for row in Annotation.objects.values()}
        expected = {key: dict(value) for key, value in before.items()}
        expected[standalone.pk]["task_id"] = None
        self.assertEqual(after, expected)
