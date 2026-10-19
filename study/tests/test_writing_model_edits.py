from unittest.mock import patch

from django.test import TestCase, tag
from django.urls import reverse
from django.utils import timezone

from study.models import (
    Annotation, AnnotationKind, PersonalWritingResponse, WritingResponseOverride,
    WritingSujetCompletion,
)
from study.oral_highlights import AnnotationRootText
from study.templatetags.study_markdown import render_markdown_prose

from . import factories


ORIGINAL = (
    "Salut Cédric,\n\n"
    "J'espère que tu vas bien ! Le château se trouve à Kumasi.\n\n"
    "Il est perché au sommet de la montagne qui domine la ville et offre une vue "
    "à couper le souffle. Impossible de le manquer : c'est un grand bâtiment blanc, "
    "visible de loin.\n\n"
    "Pour y accéder, des navettes partent de l'aéroport les vendredis et samedis, "
    "entre 8 h et 12 h ; il faut juste que tu sois à l'heure.\n\n"
    "Si tu te perds en route, n'hésite pas à m'appeler.\n\n"
    "Hâte de célébrer avec toi !\n\nC"
)
EDITED = ORIGINAL.replace(
    "Salut Cédric,\n\nJ'espère que tu vas bien ! Le château se trouve à Kumasi.",
    "Bonjour Cédric,\n\nJe suis ravi que tu viennes à mon mariage ! "
    "Voici les informations pour te rendre au château, à Kumasi.",
)
QUOTES = (
    "Il est perché au sommet de la montagne qui domine la ville et offre une vue "
    "à couper le souffle.",
    "Impossible de le manquer : c'est un grand bâtiment blanc, visible de loin.",
    "Pour y accéder, des navettes partent de l'aéroport les vendredis et samedis, "
    "entre 8 h et 12 h ; il faut juste que tu sois à l'heure.",
    "Si tu te perds en route, n'hésite pas à m'appeler.",
    "Hâte de célébrer avec toi !",
)


def rendered_body(body):
    return AnnotationRootText(
        f"<div data-annotation-root>{render_markdown_prose(body)}</div>"
    )


@tag("database-locking")
class WritingModelEditTests(TestCase):
    def setUp(self):
        self.task = factories.make_task(factories.make_part("ee"), "tache-1")
        self.user = factories.make_user("ee1-model-edit")
        self.other = factories.make_user("ee1-model-other")
        self.sujet = factories.make_writing_sujet(self.task, versions=(ORIGINAL,))
        self.detail = reverse(
            "study:writing_sujet_detail", args=["ee", "tache-1", self.sujet.pk],
        )
        self.editor = reverse(
            "study:writing_sujet_edit", args=["ee", "tache-1", self.sujet.pk],
        )
        self.key = f"writing-sujet:{self.sujet.pk}:model-1"
        self.client.force_login(self.user)

    def annotation(self, quote, *, body=ORIGINAL, key=None, **kwargs):
        rendered = rendered_body(body)
        position = rendered.text.index(quote.encode("utf-16-le")) // 2
        end = position + len(quote.encode("utf-16-le")) // 2
        return Annotation.objects.create(
            user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
            source_path=self.detail, source_key=key or self.key, quote=quote,
            start_offset=position, end_offset=end,
            prefix=rendered.slice(max(0, position - 160), position),
            suffix=rendered.slice(end, end + 160), **kwargs,
        )

    def highlights(self):
        response = self.client.get(
            reverse("study:annotations_for_source"), {"source_path": self.detail},
        )
        self.assertEqual(response.status_code, 200)
        return {row["id"]: row for row in response.json()["highlights"]}

    def test_primary_model_editor_updates_one_model_without_creating_a_copy(self):
        page = self.client.get(self.detail)
        card = page.context["primary_version_card"]
        self.assertContains(page, f'href="{card["edit_url"]}"')
        for editor, body in ((self.editor, EDITED), (card["edit_url"], EDITED + "\n\nÀ bientôt.")):
            saved = self.client.post(editor, {"body": body})
            self.assertEqual(saved.status_code, 302)
            page = self.client.get(self.detail)
            self.assertEqual(page.context["response_copy_texts"], {"model-1": body})
            self.assertContains(page, f'data-annotation-source-key="{self.key}"', count=1)
            self.assertNotContains(page, "Voir la réponse modèle")
            self.assertFalse(PersonalWritingResponse.objects.filter(user=self.user).exists())
            self.assertEqual(WritingResponseOverride.objects.filter(user=self.user).count(), 1)
        self.sujet.refresh_from_db()
        self.assertEqual(self.sujet.model_versions[0]["body"], ORIGINAL)
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(self.detail).context["response_copy_texts"], {"model-1": ORIGINAL},
        )

    def test_editing_only_opening_paragraphs_keeps_all_other_highlight_ids_and_notes(self):
        annotations = [self.annotation(quote) for quote in QUOTES]
        note = Annotation.objects.create(
            user=self.user, task=None, kind=AnnotationKind.NOTE, body="Keep my note.",
            quote=QUOTES[-1], source_path=self.editor, source_key=self.key,
            completed_at=timezone.now(), study_later=True,
        )
        original_note = Annotation.objects.values().get(pk=note.pk)
        completion = WritingSujetCompletion.objects.create(user=self.user, sujet=self.sujet)
        self.assertEqual(self.client.post(self.editor, {"body": EDITED}).status_code, 302)
        highlights = self.highlights()
        self.assertEqual(set(highlights), {item.pk for item in annotations})
        rendered = rendered_body(EDITED)
        for item in annotations:
            saved = highlights[item.pk]
            self.assertEqual(saved["source_key"], self.key)
            self.assertEqual(saved["quote"], item.quote)
            self.assertEqual(
                rendered.slice(saved["start_offset"], saved["end_offset"]), item.quote,
            )
        after_note = Annotation.objects.values().get(pk=note.pk)
        for name in ("id", "body", "quote", "created_at", "completed_at", "study_later", "source_path"):
            self.assertEqual(after_note[name], original_note[name])
        self.assertTrue(WritingSujetCompletion.objects.filter(pk=completion.pk).exists())
        self.assertEqual(Annotation.objects.count(), len(annotations) + 1)

    def test_existing_personal_copy_is_shown_once_and_inherits_unchanged_model_highlights(self):
        annotations = [self.annotation(quote) for quote in QUOTES]
        personal = PersonalWritingResponse.objects.create(
            user=self.user, sujet=self.sujet, body=EDITED,
        )
        personal_key = f"writing-sujet:{self.sujet.pk}:personal"
        own_highlight = self.annotation("Bonjour Cédric,", body=EDITED, key=personal_key)
        page = self.client.get(self.detail)
        self.assertEqual(page.context["response_copy_texts"], {"personal": EDITED})
        self.assertNotContains(page, "Voir la réponse modèle")
        self.assertContains(page, "data-annotation-root", count=1)
        highlights = self.highlights()
        self.assertEqual(set(highlights), {item.pk for item in annotations} | {own_highlight.pk})
        for item in annotations:
            self.assertEqual(highlights[item.pk]["source_key"], personal_key)
        personal.refresh_from_db()
        self.assertEqual(personal.body, EDITED)
        self.assertFalse(WritingResponseOverride.objects.exists())
        directory = self.client.get(reverse("study:task_browse", args=["ee", "tache-1"]))
        self.assertEqual(directory.context["categories"][0]["sujets"][0]["version_count"], 1)

    def test_existing_copy_can_be_edited_again_without_losing_recovered_highlights(self):
        annotations = [self.annotation(quote) for quote in QUOTES]
        personal = PersonalWritingResponse.objects.create(
            user=self.user, sujet=self.sujet, body=EDITED,
        )
        changed = EDITED.replace("Bonjour Cédric,", "Bonjour Cédric et toute la famille,")
        self.assertEqual(self.client.post(self.editor, {"body": changed}).status_code, 302)
        highlights = self.highlights()
        self.assertEqual(set(highlights), {item.pk for item in annotations})
        personal.refresh_from_db()
        self.assertEqual(personal.body, changed)
        self.assertEqual(PersonalWritingResponse.objects.count(), 1)
        self.assertFalse(WritingResponseOverride.objects.exists())
        self.assertContains(self.client.get(self.detail), "data-annotation-root", count=1)

    def test_unchanged_short_quotes_and_utf16_offsets_survive_a_known_edit(self):
        before = "Bonjour 👋,\n\nTexte initial.\n\nOK.\n\nUn dernier paragraphe."
        after = before.replace("Texte initial.", "Une introduction beaucoup plus détaillée.")
        self.sujet.versions = [{"body": before}]
        self.sujet.save(update_fields=["versions"])
        mark = self.annotation("OK.", body=before)
        self.assertEqual(self.client.post(self.editor, {"body": after}).status_code, 302)
        saved = self.highlights()[mark.pk]
        self.assertEqual(
            rendered_body(after).slice(saved["start_offset"], saved["end_offset"]), "OK.",
        )
        self.assertNotEqual(saved["start_offset"], mark.start_offset)

    def test_removed_and_ambiguous_quotes_remain_in_notes_not_on_unrelated_text(self):
        before = "Merci.\n\nMerci."
        self.sujet.versions = [{"body": before}]
        self.sujet.save(update_fields=["versions"])
        mark = self.annotation("Merci.", body=before)
        self.assertEqual(self.client.post(self.editor, {"body": "Merci."}).status_code, 302)
        self.assertNotIn(mark.pk, self.highlights())
        mark.refresh_from_db()
        self.assertEqual(mark.quote, "Merci.")
        self.assertTrue(Annotation.objects.filter(pk=mark.pk).exists())

    def test_changed_opening_selection_is_retained_without_a_false_inline_highlight(self):
        quote = "J'espère que tu vas bien ! Le château se trouve à Kumasi."
        mark = self.annotation(quote, body=ORIGINAL)
        self.assertEqual(self.client.post(self.editor, {"body": EDITED}).status_code, 302)
        self.assertNotIn(mark.pk, self.highlights())
        mark.refresh_from_db()
        self.assertEqual(mark.quote, quote)

    def test_independently_edited_models_are_not_overwritten_by_copy_consolidation(self):
        card = self.client.get(self.detail).context["primary_version_card"]
        WritingResponseOverride.objects.create(
            user=self.user, sujet=self.sujet, version_key=card["key"],
            body="Une autre réponse déjà modifiée séparément.",
        )
        personal = PersonalWritingResponse.objects.create(
            user=self.user, sujet=self.sujet, body=EDITED,
        )
        page = self.client.get(self.detail)
        self.assertEqual(page.context["response_copy_texts"], {
            "personal": personal.body, "model-1": "Une autre réponse déjà modifiée séparément.",
        })

    def test_subject_without_models_still_saves_one_private_answer(self):
        self.sujet.versions = []
        self.sujet.save(update_fields=["versions"])
        for body in ("Première réponse.", "Même réponse corrigée."):
            self.assertEqual(self.client.post(self.editor, {"body": body}).status_code, 302)
        self.assertEqual(PersonalWritingResponse.objects.get(user=self.user).body, body)
        self.assertFalse(WritingResponseOverride.objects.exists())

    def test_annotation_failure_rolls_back_the_response_and_copy_recovery_together(self):
        mark = self.annotation(QUOTES[0])
        PersonalWritingResponse.objects.create(user=self.user, sujet=self.sujet, body=EDITED)
        original = Annotation.objects.values().get(pk=mark.pk)
        with patch(
            "study.views.library.preserve_edited_writing_annotations",
            side_effect=RuntimeError("Regression probe"),
        ):
            with self.assertRaisesMessage(RuntimeError, "Regression probe"):
                self.client.post(self.editor, {"body": EDITED + "\n\nÀ bientôt."})
        self.assertEqual(Annotation.objects.values().get(pk=mark.pk), original)
        self.assertEqual(PersonalWritingResponse.objects.get(user=self.user).body, EDITED)
        self.assertFalse(WritingResponseOverride.objects.exists())

    def test_other_learners_annotations_are_not_changed(self):
        own = self.annotation(QUOTES[0])
        other = self.annotation(QUOTES[1])
        other.user = self.other
        other.save(update_fields=["user"])
        before = Annotation.objects.values().get(pk=other.pk)
        self.client.post(self.editor, {"body": EDITED})
        self.assertEqual(set(self.highlights()), {own.pk})
        self.assertEqual(Annotation.objects.values().get(pk=other.pk), before)
