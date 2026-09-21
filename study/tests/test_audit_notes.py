from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from study.forms import NoteForm
from study.models import Annotation, AnnotationKind

from . import factories


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class NoteReliabilityTests(TestCase):
    def setUp(self):
        self.user = factories.make_user()
        self.client.force_login(self.user)

    def test_note_edit_preserves_concurrent_completion_and_study_flags(self):
        note = Annotation.objects.create(
            user=self.user, kind=AnnotationKind.NOTE, body="Original note",
        )
        completed_at = timezone.now()
        original_is_valid = NoteForm.is_valid

        def validate_after_another_tab_marks_complete(form):
            Annotation.objects.filter(pk=note.pk).update(
                completed_at=completed_at, study_later=True,
            )
            return original_is_valid(form)

        with patch.object(NoteForm, "is_valid", validate_after_another_tab_marks_complete):
            response = self.client.post(
                reverse("study:annotation_update", args=[note.pk]),
                {"title": "Edited", "body": "Updated note"},
            )

        self.assertEqual(response.status_code, 302)
        note.refresh_from_db()
        self.assertEqual(note.body, "Updated note")
        self.assertEqual(note.title, "Edited")
        self.assertEqual(note.completed_at, completed_at)
        self.assertTrue(note.study_later)

    def test_comprehension_capture_and_actions_return_to_their_own_folder(self):
        for mode in ("ecrite", "orale"):
            for kind in AnnotationKind.values:
                with self.subTest(mode=mode, kind=kind):
                    response = self.client.post(reverse("study:annotation_create"), {
                        "kind": kind, "quote": "Selected passage", "body": "My note",
                        "source_path": f"/comprehension/{mode}/tests/test-1/",
                        "start_offset": "0", "end_offset": "16",
                    })
                    self.assertEqual(response.status_code, 201)
                    pk = response.json()["id"]
                    tab = "notes" if kind == AnnotationKind.NOTE else "highlights"
                    folder = reverse("study:comprehension_notes", args=[mode]) + f"?tab={tab}"
                    self.assertEqual(response.json()["notes_url"].split("#")[0], folder)
                    for route, data in (
                        ("study:annotation_study_toggle", {"study_later": "1"}),
                        ("study:annotation_complete_toggle", {"completed": "1"}),
                        ("study:annotation_delete", {}),
                    ):
                        action = self.client.post(reverse(route, args=[pk]), data)
                        self.assertRedirects(action, folder, fetch_redirect_response=False)

    def test_unmapped_writing_sujet_never_matches_another_sources_highlights(self):
        sujet = factories.make_writing_sujet()
        path = reverse(
            "study:writing_sujet_detail",
            args=[sujet.task.part.slug, sujet.task.slug, sujet.pk],
        )
        unrelated = Annotation.objects.create(
            user=self.user, kind=AnnotationKind.HIGHLIGHT, quote="Unrelated",
            source_path="/vocabulaire/", source_key="shared", start_offset=0, end_offset=10,
        )
        before = Annotation.objects.filter(pk=unrelated.pk).values().get()
        with patch(
            "study.views.notes.content_module.ee_writing_canonical_slug_by_slug",
            return_value={},
        ):
            listing = self.client.get(
                reverse("study:annotations_for_source"), {"source_path": path},
            )
            self.assertEqual(listing.json()["highlights"], [])
            created = self.client.post(reverse("study:annotation_create"), {
                "kind": AnnotationKind.HIGHLIGHT, "quote": "Own selection",
                "source_path": path, "source_key": "shared",
                "start_offset": "0", "end_offset": "10",
                "task_id": sujet.task_id,
            })
            self.assertEqual(created.status_code, 201)
            listing = self.client.get(
                reverse("study:annotations_for_source"), {"source_path": path},
            )
        self.assertEqual(
            [row["id"] for row in listing.json()["highlights"]], [created.json()["id"]],
        )
        self.assertEqual(Annotation.objects.filter(pk=unrelated.pk).values().get(), before)

    def test_invalid_numeric_search_filters_are_rejected_without_server_errors(self):
        for value in ("\u00b2", "9" * 5000, str(2**63)):
            with self.subTest(value=value[:20]):
                response = self.client.get(
                    reverse("study:annotation_search"), {"task": value},
                )
                self.assertEqual(response.status_code, 400)


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    TRANSLATION_API_URL="http://translation.test/translate",
)
class TranslationReliabilityTests(TestCase):
    def setUp(self):
        self.client.force_login(factories.make_user())
        cache.clear()
        self.addCleanup(cache.clear)

    def translate(self):
        return self.client.post(reverse("study:translate_selection"), {"text": "Bonjour"})

    def test_invalid_upstream_shapes_are_rejected_and_never_cached(self):
        for body in (
            ["not an object"], "not an object", 42,
            {"translatedText": {"wrong": "shape"}},
            {"translatedText": [42]},
            {"translatedText": ["Hello", "unexpected second translation"]},
        ):
            with self.subTest(body=body):
                upstream = MagicMock()
                upstream.__enter__.return_value.read.return_value = json.dumps(body).encode()
                with patch("study.views.notes.urllib.request.urlopen", return_value=upstream) as send:
                    self.assertEqual(self.translate().status_code, 502)
                    self.assertEqual(self.translate().status_code, 502)
                self.assertEqual(send.call_count, 2)

    def test_network_and_invalid_encoding_failures_return_upstream_errors(self):
        with patch("study.views.notes.urllib.request.urlopen", side_effect=URLError("offline")):
            self.assertEqual(self.translate().status_code, 502)
        for body in (b"not json", b"\xff"):
            upstream = MagicMock()
            upstream.__enter__.return_value.read.return_value = body
            with patch("study.views.notes.urllib.request.urlopen", return_value=upstream):
                self.assertEqual(self.translate().status_code, 502)

    def test_single_translation_list_remains_supported(self):
        upstream = MagicMock()
        upstream.__enter__.return_value.read.return_value = b'{"translatedText":["Hello"]}'
        with patch("study.views.notes.urllib.request.urlopen", return_value=upstream):
            response = self.translate()
        self.assertEqual(response.json(), {"translation": "Hello"})
