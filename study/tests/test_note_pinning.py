from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from study.models import Annotation, AnnotationKind

from . import factories


class NotePinningTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("pin-owner")
        self.other = factories.make_user("pin-other")
        self.client.force_login(self.user)
        self.url = reverse("study:custom_notes")

    def note(self, **values):
        return Annotation.objects.create(**{
            "user": self.user, "kind": AnnotationKind.NOTE,
            "title": "Repère", "body": "Le contenu complet.", **values,
        })

    def pin_url(self, note):
        return reverse("study:annotation_pin_toggle", args=[note.pk])

    def test_explicit_pin_and_unpin_preserve_note_content_dates_and_study_state(self):
        note = self.note(study_later=True)
        original = (note.body, note.created_at, note.updated_at)
        for value in ("1", "1", "0", "0"):
            result = self.client.post(
                self.pin_url(note), {"is_pinned": value, "next": self.url},
            )
            self.assertEqual(result.status_code, 302)
            note.refresh_from_db()
            self.assertEqual(note.is_pinned, value == "1")
            self.assertEqual((note.body, note.created_at, note.updated_at), original)
            self.assertTrue(note.study_later)

    def test_pin_endpoint_is_private_note_only_post_only_and_validates_state(self):
        note = self.note()
        foreign = self.note(user=self.other)
        highlight = self.note(kind=AnnotationKind.HIGHLIGHT, quote="Passage")
        self.assertEqual(self.client.get(self.pin_url(note)).status_code, 405)
        for value in (None, "", "true", "2"):
            data = {} if value is None else {"is_pinned": value}
            self.assertEqual(self.client.post(self.pin_url(note), data).status_code, 400)
        for item in (foreign, highlight):
            self.assertEqual(
                self.client.post(self.pin_url(item), {"is_pinned": "1"}).status_code, 404
            )
            item.refresh_from_db()
            self.assertFalse(item.is_pinned)
        self.client.logout()
        self.assertEqual(
            self.client.post(self.pin_url(note), {"is_pinned": "1"}).status_code, 302
        )

    def test_pins_are_first_once_within_the_same_bounded_pagination(self):
        old = timezone.now() - timedelta(days=40)
        pins = [self.note(is_pinned=True, created_at=old) for _ in range(52)]
        ordinary = self.note()
        self.note(user=self.other, is_pinned=True)
        first = self.client.get(self.url)
        self.assertEqual(first.context["notes_count"], 53)
        self.assertEqual(len(first.context["notes"]), 50)
        self.assertTrue(all(item.is_pinned for item in first.context["notes"]))
        self.assertEqual([s["key"] for s in first.context["notes_sections"]], ["pinned"])
        self.assertContains(first, 'data-pinned-note-open', count=50)
        self.assertContains(first, 'annotation-card__pin-dot', count=50)
        self.assertNotContains(first, 'data-annotation-period-sort="pinned"')
        second = self.client.get(self.url, {"page": 2})
        self.assertEqual(second.context["notes"], [pins[1], pins[0], ordinary])
        self.assertEqual(
            [s["key"] for s in second.context["notes_sections"]], ["pinned", "today"]
        )

    def test_locator_matches_actual_order_with_pins_dates_context_and_ties(self):
        now = timezone.now()
        rows = [
            self.note(is_pinned=bool(index % 2), created_at=now - timedelta(days=index % 4))
            for index in range(56)
        ]
        for params in ({}, {"sort_today": "asc", "sort_week": "asc"}, {"order": "context"},
                       {"order": "context", "sort_week": "asc"}):
            ordered = []
            for page in (1, 2):
                ordered.extend(self.client.get(self.url, {**params, "page": page}).context["notes"])
            self.assertCountEqual(ordered, rows)
            for index in (0, 27, 28, 49, 50, 55):
                with self.subTest(params=params, index=index):
                    note = ordered[index]
                    located = self.client.get(
                        self.url, {**params, "locate": note.pk}, follow=True
                    )
                    self.assertEqual(located.context["page_obj"].number, index // 50 + 1)
                    self.assertContains(located, f'id="note-{note.pk}"', count=1)

    def test_pin_and_unpin_redirect_to_actual_page_and_preserve_filters(self):
        for _ in range(51):
            self.note()
        note = self.note(created_at=timezone.now() - timedelta(days=40))
        target = self.url + "?q=Repère&status=todo&page=2"
        pinned = self.client.post(
            self.pin_url(note), {"is_pinned": "1", "next": target}, follow=True
        )
        self.assertEqual(pinned.context["page_obj"].number, 1)
        self.assertEqual(pinned.context["notes"][0].pk, note.pk)
        self.assertEqual(pinned.context["query"], "Repère")
        self.assertEqual(pinned.context["status"], "todo")
        unpinned = self.client.post(
            self.pin_url(note), {"is_pinned": "0", "next": target}, follow=True
        )
        self.assertEqual(unpinned.context["page_obj"].number, 2)
        self.assertContains(unpinned, f'id="note-{note.pk}"', count=1)

    def test_new_unpinned_note_locates_after_fifty_pins(self):
        for _ in range(50):
            self.note(is_pinned=True)
        result = self.client.post(
            self.url, {"title": "Nouvelle", "body": "Nouvelle note."}, follow=True
        )
        self.assertEqual(result.context["page_obj"].number, 2)
        self.assertEqual(result.context["notes"][0].title, "Nouvelle")

    def test_pins_respect_scope_search_and_status_without_extra_page_queries(self):
        part = factories.make_part("eo")
        task = factories.make_task(part, "tache-3")
        self.note(is_pinned=True, task=task, title="Autre dossier")
        self.note(is_pinned=True, title="Terminée", completed_at=timezone.now())
        visible = self.note(is_pinned=True, title="À retenir")
        filtered = self.client.get(self.url, {"q": "retenir", "status": "todo"})
        self.assertEqual(filtered.context["notes"], [visible])
        self.client.get(self.url)
        with CaptureQueriesContext(connection) as before:
            self.client.get(self.url)
        for _ in range(60):
            self.note(is_pinned=True)
        with CaptureQueriesContext(connection) as after:
            result = self.client.get(self.url)
        self.assertEqual(len(before), len(after))
        self.assertEqual(len(result.context["notes"]), 50)

    def test_account_export_preserves_pin_state_without_mutating_notes(self):
        note = self.note(is_pinned=True)
        result = self.client.get(reverse("study:export_account"))
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["annotations"][0]["is_pinned"])
        note.refresh_from_db()
        self.assertTrue(note.is_pinned)
