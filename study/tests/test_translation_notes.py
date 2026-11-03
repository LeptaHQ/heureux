from unittest import mock

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from study.models import Annotation, AnnotationKind

from . import factories


@override_settings(
    DEEPL_API_KEY="test:fx", DEEPL_TARGET_LANG="EN-GB", TRANSLATION_API_URL="",
)
class TranslationNoteTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("translation-note-owner")
        self.client.force_login(self.user)
        self.task = factories.make_task()
        self.url = reverse("study:annotation_create")
        self.selection = {
            "kind": AnnotationKind.NOTE,
            "translate_with": "deepl",
            "quote": "Il faut nuancer cette affirmation.",
            "start_offset": 24,
            "end_offset": 57,
            "prefix": "Préambule ",
            "suffix": " Conclusion",
            "source_path": reverse("study:task_detail", args=["eo", "tache-3"]),
            "source_key": "lesson:selection",
            "source_title": "EO Tâche 3 · Heureux",
            "task_id": self.task.pk,
        }
        cache.clear()
        patcher = mock.patch(
            "study.views.notes._deepl_translation",
            return_value="This statement needs to be qualified.",
        )
        self.provider = patcher.start()
        self.addCleanup(patcher.stop)

    def test_saves_a_private_source_linked_deepl_note_without_a_highlight(self):
        response = self.client.post(self.url, self.selection)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["provider"], "deepl")
        note = Annotation.objects.get()
        self.assertEqual(note.user, self.user)
        self.assertEqual(note.task, self.task)
        self.assertEqual(note.kind, AnnotationKind.NOTE)
        for field in ("quote", "prefix", "suffix", "source_path", "source_key", "source_title"):
            self.assertEqual(getattr(note, field), self.selection[field])
        self.assertEqual(note.start_offset, 24)
        self.assertEqual(note.end_offset, 57)
        self.assertEqual(note.body, self.provider.return_value)
        self.assertFalse(Annotation.objects.filter(kind=AnnotationKind.HIGHLIGHT).exists())
        self.provider.assert_called_once_with(self.selection["quote"], "test:fx")

    def test_retries_reuse_the_note_and_preserve_its_study_state_and_highlights(self):
        highlight = Annotation.objects.create(
            user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
            **{key: self.selection[key] for key in (
                "quote", "source_path", "source_key", "start_offset", "end_offset",
            )},
        )
        before = Annotation.objects.filter(pk=highlight.pk).values().get()
        first = self.client.post(self.url, self.selection)
        note = Annotation.objects.get(pk=first.json()["id"])
        note.study_later = True
        note.completed_at = timezone.now()
        note.save()
        saved = Annotation.objects.filter(pk=note.pk).values().get()

        repeated = self.client.post(self.url, self.selection)

        self.assertEqual(repeated.status_code, 200)
        self.assertFalse(repeated.json()["created"])
        self.assertEqual(repeated.json()["id"], note.pk)
        self.assertEqual(Annotation.objects.filter(kind=AnnotationKind.NOTE).count(), 1)
        self.assertEqual(Annotation.objects.filter(pk=note.pk).values().get(), saved)
        self.assertEqual(Annotation.objects.filter(pk=highlight.pk).values().get(), before)
        self.assertEqual(self.provider.call_count, 1)

    def test_retries_do_not_overwrite_an_edited_note(self):
        first = self.client.post(self.url, self.selection)
        note = Annotation.objects.get(pk=first.json()["id"])
        note.body = "My own explanation."
        note.save()

        repeated = self.client.post(self.url, self.selection)

        self.assertEqual(repeated.status_code, 201)
        self.assertNotEqual(repeated.json()["id"], note.pk)
        note.refresh_from_db()
        self.assertEqual(note.body, "My own explanation.")
        self.assertEqual(Annotation.objects.filter(kind=AnnotationKind.NOTE).count(), 2)

    def test_identical_text_in_other_sources_ranges_contexts_tasks_or_users_is_separate(self):
        self.client.post(self.url, self.selection)
        other_task = factories.make_task(slug="tache-2")
        changes = (
            {"source_path": reverse("study:dashboard")},
            {"source_key": "lesson:other"},
            {"start_offset": 25, "end_offset": 58},
            {"prefix": "Autre préambule "},
            {"suffix": " Autre conclusion"},
            {"task_id": other_task.pk},
        )
        for change in changes:
            with self.subTest(change=change):
                response = self.client.post(self.url, {**self.selection, **change})
                self.assertEqual(response.status_code, 201)
        self.client.force_login(factories.make_user("translation-note-other"))
        other = self.client.post(self.url, self.selection)
        self.assertEqual(other.status_code, 201)
        self.assertEqual(Annotation.objects.count(), len(changes) + 2)
        self.assertEqual(self.provider.call_count, 1)

    def test_rejects_invalid_requests_before_calling_deepl(self):
        changes = (
            {"kind": AnnotationKind.HIGHLIGHT},
            {"translate_with": "libretranslate"},
            {"body": "Do not replace this."},
            {"quote": ""},
            {"start_offset": -1},
            {"source_path": "https://outside.test/"},
            {"source_key": "invalid key"},
            {"task_id": "invalid"},
        )
        for change in changes:
            with self.subTest(change=change):
                response = self.client.post(self.url, {**self.selection, **change})
                self.assertEqual(response.status_code, 400)
        self.provider.assert_not_called()
        self.assertFalse(Annotation.objects.exists())

    def test_selection_length_limit_is_exact_and_prevents_provider_calls(self):
        oversized = self.client.post(self.url, {
            **self.selection, "quote": "a" * 2001, "end_offset": 2025,
        })
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(oversized.json()["code"], "too_long")
        self.provider.assert_not_called()
        self.assertFalse(Annotation.objects.exists())

        maximum = self.client.post(self.url, {
            **self.selection, "quote": "a" * 2000, "end_offset": 2024,
        })
        self.assertEqual(maximum.status_code, 201)
        self.provider.assert_called_once_with("a" * 2000, "test:fx")

    def test_requires_deepl_even_when_another_service_or_cached_translation_exists(self):
        with override_settings(
            DEEPL_API_KEY="", TRANSLATION_API_URL="https://translate.test/",
        ), mock.patch(
            "study.views.notes._libretranslate_translation", return_value="Other provider.",
        ) as libre:
            self.client.post(
                reverse("study:translate_selection"), {"text": self.selection["quote"]},
            )
            response = self.client.post(self.url, self.selection)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "not_configured")
        self.provider.assert_not_called()
        libre.assert_called_once()
        self.assertFalse(Annotation.objects.exists())

    def test_translation_failures_never_save_and_are_not_cached(self):
        for result, code in ((OSError("unavailable"), "upstream"), (None, "upstream"), (" ", "empty")):
            with self.subTest(code=code, result=result):
                self.provider.side_effect = result if isinstance(result, OSError) else None
                self.provider.return_value = result
                response = self.client.post(self.url, self.selection)
                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json()["code"], code)
                self.assertFalse(Annotation.objects.exists())
        self.provider.side_effect = None
        self.provider.return_value = "A valid retry."
        saved = self.client.post(self.url, self.selection)
        self.assertEqual(saved.status_code, 201)
        self.assertEqual(Annotation.objects.get().body, "A valid retry.")
        self.assertEqual(self.provider.call_count, 4)

    def test_oversized_translation_is_not_saved(self):
        self.provider.return_value = "a" * 20001
        response = self.client.post(self.url, self.selection)
        self.assertEqual(response.status_code, 400)
        self.assertIn("trop longue", response.json()["error"])
        self.assertFalse(Annotation.objects.exists())

    def test_reuses_panel_translation_and_isolates_the_deepl_target_language(self):
        panel_url = reverse("study:translate_selection")
        self.client.post(panel_url, {"text": self.selection["quote"]})
        self.client.post(self.url, self.selection)
        self.assertEqual(self.provider.call_count, 1)
        with override_settings(DEEPL_TARGET_LANG="EN-US"):
            self.provider.return_value = "A different English variant."
            response = self.client.post(self.url, self.selection)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.provider.call_count, 2)
        self.assertEqual(Annotation.objects.count(), 2)

    def test_requires_an_authenticated_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(self.url, self.selection).status_code, 302)
        self.provider.assert_not_called()
        self.assertFalse(Annotation.objects.exists())

    def test_requires_csrf_and_does_not_translate_an_unverified_request(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, self.selection).status_code, 403)
        self.provider.assert_not_called()
        self.assertFalse(Annotation.objects.exists())

    def test_an_account_deactivated_during_translation_does_not_save(self):
        def deactivate(text, key):
            type(self.user).objects.filter(pk=self.user.pk).update(is_active=False)
            return "Not saved."

        self.provider.side_effect = deactivate
        response = self.client.post(self.url, self.selection)
        self.assertEqual(response.status_code, 401)
        self.assertIn("session a expiré", response.json()["error"])
        self.assertFalse(Annotation.objects.exists())
