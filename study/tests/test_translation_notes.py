import json
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

    def selection_with_highlight(self, *, highlights=(), covered=False):
        return {
            **self.selection,
            "highlight_selection": json.dumps({
                "quote": self.selection["quote"],
                "start": self.selection["start_offset"],
                "end": self.selection["end_offset"],
                "prefix": self.selection["prefix"],
                "suffix": self.selection["suffix"],
                "fully_highlighted": covered,
            }),
            "overlap_ids": ",".join(str(item.pk) for item in highlights),
            "overlap_revisions": json.dumps({
                str(item.pk): item.updated_at.isoformat() for item in highlights
            }),
        }

    def test_saves_the_note_and_highlight_in_the_same_request(self):
        response = self.client.post(self.url, self.selection_with_highlight())

        self.assertEqual(response.status_code, 201)
        note = Annotation.objects.get(kind=AnnotationKind.NOTE)
        highlight = Annotation.objects.get(kind=AnnotationKind.HIGHLIGHT)
        for field in (
            "user", "task", "quote", "source_path", "source_key",
            "source_title", "start_offset", "end_offset", "prefix", "suffix",
        ):
            self.assertEqual(getattr(highlight, field), getattr(note, field))
        self.assertEqual(note.body, self.provider.return_value)
        self.assertEqual(highlight.body, "")
        result = response.json()["highlight"]
        self.assertIsNone(result["error"])
        self.assertEqual(result["removed_ids"], [])
        self.assertEqual(result["items"][0]["id"], highlight.pk)
        self.assertEqual(result["items"][0]["revision"], highlight.updated_at.isoformat())
        self.assertEqual(result["items"][0]["quote"], highlight.quote)
        self.provider.assert_called_once()

    def test_combined_action_preserves_an_existing_highlight_entirely(self):
        highlight = Annotation.objects.create(
            user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
            body="Keep this explanation.", study_later=True,
            completed_at=timezone.now(), response_anchor={"preserved": True},
            **{key: self.selection[key] for key in (
                "quote", "source_path", "source_key", "source_title",
                "start_offset", "end_offset", "prefix", "suffix",
            )},
        )
        before = Annotation.objects.filter(pk=highlight.pk).values().get()

        response = self.client.post(
            self.url, self.selection_with_highlight(highlights=[highlight], covered=True),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["highlight"]["items"][0]["id"], highlight.pk)
        self.assertEqual(Annotation.objects.filter(pk=highlight.pk).values().get(), before)
        self.assertEqual(Annotation.objects.filter(kind=AnnotationKind.HIGHLIGHT).count(), 1)

    def test_existing_contiguous_highlights_are_reused_without_merging_or_editing(self):
        quote = self.selection["quote"]
        middle = len(quote) // 2
        highlights = [
            Annotation.objects.create(
                user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
                source_path=self.selection["source_path"],
                source_key=self.selection["source_key"],
                quote=quote[start:end],
                start_offset=self.selection["start_offset"] + start,
                end_offset=self.selection["start_offset"] + end,
                body="Keep both rows.", study_later=True,
            )
            for start, end in ((0, middle), (middle, len(quote)))
        ]
        before = list(Annotation.objects.order_by("pk").values())

        response = self.client.post(
            self.url, self.selection_with_highlight(highlights=highlights, covered=True),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            {item["id"] for item in response.json()["highlight"]["items"]},
            {item.pk for item in highlights},
        )
        self.assertEqual(list(
            Annotation.objects.filter(kind=AnnotationKind.HIGHLIGHT).order_by("pk").values(),
        ), before)

    def test_a_completed_merge_can_be_replayed_without_duplication_or_new_edits(self):
        quote = self.selection["quote"]
        highlights = [
            Annotation.objects.create(
                user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
                source_path=self.selection["source_path"],
                source_key=self.selection["source_key"],
                quote=quote[start:end],
                start_offset=self.selection["start_offset"] + start,
                end_offset=self.selection["start_offset"] + end,
                study_later=True,
            )
            for start, end in ((0, 10), (20, len(quote)))
        ]
        payload = self.selection_with_highlight(highlights=highlights)
        first = self.client.post(self.url, payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(len(first.json()["highlight"]["removed_ids"]), 1)
        before = list(Annotation.objects.order_by("pk").values())

        repeated = self.client.post(self.url, payload)

        self.assertEqual(repeated.status_code, 200)
        self.assertFalse(repeated.json()["created"])
        self.assertIsNone(repeated.json()["highlight"]["error"])
        self.assertEqual(
            repeated.json()["highlight"]["removed_ids"],
            first.json()["highlight"]["removed_ids"],
        )
        self.assertEqual(list(Annotation.objects.order_by("pk").values()), before)
        self.assertEqual(Annotation.objects.get(kind=AnnotationKind.HIGHLIGHT).quote, quote)
        self.provider.assert_called_once()

    def test_highlight_conflict_preserves_the_note_and_allows_a_deduplicated_retry(self):
        highlight = Annotation.objects.create(
            user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
            source_path=self.selection["source_path"],
            source_key=self.selection["source_key"],
            quote="Il faut", start_offset=24, end_offset=31,
        )
        payload = self.selection_with_highlight(highlights=[highlight])
        highlight.body = "Changed in another tab."
        highlight.save()
        before = Annotation.objects.filter(pk=highlight.pk).values().get()

        response = self.client.post(self.url, payload)

        self.assertEqual(response.status_code, 201)
        self.assertIn("autre onglet", response.json()["highlight"]["error"])
        self.assertEqual(response.json()["highlight"]["items"], [])
        self.assertEqual(Annotation.objects.filter(pk=highlight.pk).values().get(), before)
        note = Annotation.objects.get(kind=AnnotationKind.NOTE)

        retry = self.client.post(
            self.url, self.selection_with_highlight(highlights=[highlight]),
        )
        self.assertEqual(retry.status_code, 200)
        self.assertFalse(retry.json()["created"])
        self.assertEqual(retry.json()["id"], note.pk)
        self.assertIsNone(retry.json()["highlight"]["error"])
        self.assertEqual(Annotation.objects.filter(kind=AnnotationKind.NOTE).count(), 1)
        self.assertEqual(Annotation.objects.filter(kind=AnnotationKind.HIGHLIGHT).count(), 1)

    def test_invalid_combined_highlights_are_rejected_before_translation(self):
        valid = self.selection_with_highlight()
        changes = (
            {"highlight_selection": "[]"},
            {"highlight_selection": "not json"},
            {"highlight_selection": json.dumps({"quote": "French", "start": True, "end": 57})},
            {"highlight_selection": json.dumps({"quote": "French", "start": 25, "end": 57})},
            {"highlight_selection": json.dumps({"quote": "French", "start": 24, "end": 56})},
            {"highlight_selection": json.dumps({
                "quote": "a" * 5001, "start": 24, "end": 5025,
            })},
            {"overlap_revisions": ""},
            {"overlap_revisions": json.dumps({"99": "unexpected revision"})},
            {"highlight_selection": json.dumps({
                "quote": self.selection["quote"], "start": 24, "end": 57,
                "fully_highlighted": True,
            })},
            {"translate_with": ""},
        )
        for change in changes:
            with self.subTest(change=change):
                response = self.client.post(self.url, {**valid, **change})
                self.assertEqual(response.status_code, 400)
        self.provider.assert_not_called()
        self.assertFalse(Annotation.objects.exists())

    def test_combined_highlights_do_not_reuse_hidden_other_source_or_other_user_rows(self):
        other_user = factories.make_user("another-highlight-owner")
        for change in (
            {"user": other_user},
            {"source_path": reverse("study:dashboard")},
            {"hidden_on_source": True},
        ):
            with self.subTest(change=change):
                highlight = Annotation.objects.create(
                    **{
                        "user": self.user, "task": self.task,
                        "kind": AnnotationKind.HIGHLIGHT,
                        "quote": self.selection["quote"],
                        "source_path": self.selection["source_path"],
                        "source_key": self.selection["source_key"],
                        "start_offset": 24, "end_offset": 57,
                        **change,
                    },
                )
                before = Annotation.objects.filter(pk=highlight.pk).values().get()

                response = self.client.post(
                    self.url,
                    self.selection_with_highlight(highlights=[highlight], covered=True),
                )

                self.assertIn("autre onglet", response.json()["highlight"]["error"])
                self.assertEqual(response.json()["highlight"]["items"], [])
                self.assertEqual(Annotation.objects.filter(pk=highlight.pk).values().get(), before)
        self.assertEqual(Annotation.objects.filter(kind=AnnotationKind.NOTE).count(), 1)

    def test_combined_translation_failure_saves_neither_a_note_nor_a_highlight(self):
        self.provider.side_effect = OSError("Unavailable.")

        response = self.client.post(self.url, self.selection_with_highlight())

        self.assertEqual(response.status_code, 502)
        self.assertNotIn("DeepL", response.json()["error"])
        self.assertFalse(Annotation.objects.exists())

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
