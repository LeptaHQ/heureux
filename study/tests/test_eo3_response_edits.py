from dataclasses import asdict, replace
from io import StringIO
import re
from unittest.mock import patch

from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from study import catalogue
from study.card_presentation import _spine_payload
from study.french_audio import SpeechError, normalize_text, resolve_sources
from study.models import Annotation, AnnotationKind, Card, CardType, OralStateSnapshot, PersonalResponse, Prompt
from study.oral_highlights import AnnotationRootText
from study.oral_history import legacy_variant_annotation_key, snapshot, variant_annotation_key
from study.public_response_annotations import capture_rendered_response_anchor, render_current_response
from study.response_personalization import effective_response
from study.routing import prompt_detail_url
from study.tache_three_models import annotation_arguments, response_text, spoken_text

from . import factories


class EO3ResponseEditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("eo3-edit-owner")
        cls.other = factories.make_user("eo3-edit-other")

    def setUp(self):
        self.client.force_login(self.user)
        self.prompt = self.get_prompt("culture:p1")
        self.model = catalogue.tache_three_models()[self.prompt.response.semantic_group].response
        self.card = Card.objects.create(
            user=self.user, response=self.prompt.response, card_type=CardType.SPINE,
        )

    def get_prompt(self, key):
        return Prompt.objects.select_related(
            "response__theme__task__part", "theme__task__part", "family",
        ).get(content_key=key)

    def save(self, content, prompt=None):
        prompt = prompt or self.prompt
        payload = {
            name: getattr(content, name)
            for name in ("reformulation", "position", "position_claire", "nuance", "conclusion")
        }
        payload.update({
            f"argument_{argument.order}_{name}": getattr(argument, name)
            for argument in content.arguments
            for name in ("idea", "developpement", "exemple", "consequence")
        })
        result = self.client.post(
            reverse("study:edit_response", args=["eo", "tache-3", prompt.pk]),
            {**payload, "action": "save"},
        )
        self.assertEqual(result.status_code, 302, result.content)
        return PersonalResponse.objects.get(user=self.user, response=prompt.response)

    def personal(self, content, prompt=None, user=None):
        prompt = prompt or self.prompt
        fields = asdict(content)
        fields.pop("is_personal")
        fields["arguments"] = list(fields["arguments"])
        return PersonalResponse.objects.create(
            user=user or self.user, response=prompt.response, source_prompt=prompt, **fields,
        )

    def mark(self, content, quote, *, prompt=None, surface="detail", field=None, legacy=False, anchored=True, **overrides):
        prompt = prompt or self.prompt
        rendered = render_current_response(
            prompt, content, surface, self.user, legacy_personal=legacy,
        )
        left, right = rendered.response_fields[field] if field else (0, len(rendered.text) // 2)
        start = rendered.text.index(quote.encode("utf-16-le"), left * 2, right * 2) // 2
        end = start + len(quote.encode("utf-16-le")) // 2
        key = (
            legacy_variant_annotation_key(prompt, content)
            if legacy else variant_annotation_key(prompt, content)
        )
        annotation = Annotation(
            user=self.user, task=prompt.theme.task, source_prompt=prompt,
            kind=AnnotationKind.HIGHLIGHT, quote=quote,
            source_path=(
                prompt_detail_url(prompt) if surface == "detail"
                else reverse("study:task_review", args=["eo", "tache-3"])
            ),
            source_key=key + (f":{surface}" if surface != "detail" else ""),
            start_offset=start, end_offset=end,
            prefix=rendered.slice(max(0, start - 160), start),
            suffix=rendered.slice(end, end + 160),
            body="My **saved** note.", title="Keep my title",
            study_later=True, completed_at=timezone.now(),
        )
        if anchored:
            annotation.response_anchor = capture_rendered_response_anchor(annotation, rendered)
        for name, value in overrides.items():
            setattr(annotation, name, value)
        annotation.save()
        return annotation

    def visible(self, path=None):
        result = self.client.get(
            reverse("study:annotations_for_source"),
            {"source_path": path or prompt_detail_url(self.prompt)},
        )
        self.assertEqual(result.status_code, 200)
        return {item["id"] for item in result.json()["highlights"]}

    def assert_attached(self, annotation, content, *, prompt=None, surface="detail"):
        prompt = prompt or self.prompt
        preserved = {
            name: getattr(annotation, name)
            for name in ("pk", "quote", "body", "title", "study_later", "completed_at", "created_at")
        }
        annotation.refresh_from_db()
        for name, value in preserved.items():
            self.assertEqual(getattr(annotation, name), value)
        self.assertEqual(
            annotation.source_key,
            variant_annotation_key(prompt, content) + (f":{surface}" if surface != "detail" else ""),
        )
        rendered = render_current_response(prompt, content, surface, self.user)
        self.assertEqual(rendered.slice(annotation.start_offset, annotation.end_offset), annotation.quote)

    def edited_example(self, content):
        return replace(content, arguments=(
            replace(content.arguments[0], exemple="Mon nouvel exemple concret, modifié uniquement pour mon compte."),
            *content.arguments[1:],
        ), is_personal=True)

    def test_first_edit_keeps_every_unchanged_highlight_and_note(self):
        texts = [
            self.model.position_claire,
            *(getattr(argument, name) for argument in self.model.arguments
              for name in ("idea", "developpement", "exemple", "consequence")),
            self.model.nuance, self.model.conclusion,
        ]
        marks = [self.mark(self.model, text, anchored=False) for text in texts]
        note = self.mark(self.model, self.model.conclusion, kind=AnnotationKind.NOTE)
        hidden = self.mark(self.model, self.model.position_claire, hidden_on_source=True)
        hidden_before = Annotation.objects.filter(pk=hidden.pk).values().get()
        changed = marks[texts.index(self.model.arguments[0].exemple)]
        after = self.edited_example(self.model)
        self.save(after)
        self.assertEqual(self.visible(), {item.pk for item in marks if item != changed})
        for mark in [item for item in marks if item != changed] + [note]:
            self.assert_attached(mark, after)
            self.assertTrue(mark.response_anchor)
        self.assertEqual(Annotation.objects.filter(pk=hidden.pk).values().get(), hidden_before)
        changed.refresh_from_db()
        self.assertEqual(changed.quote, self.model.arguments[0].exemple)
        self.assertEqual(Annotation.objects.filter(user=self.user).count(), len(marks) + 2)
        self.assertFalse(OralStateSnapshot.objects.filter(user=self.user).exists())

    def test_successive_edits_update_one_row_without_history_and_keep_field_anchors(self):
        quote = self.model.arguments[1].exemple.split()[0]
        mark = self.mark(self.model, quote, field="argument-2-exemple")
        first = self.save(self.edited_example(self.model))
        for changes in (
            {"position_claire": "Une nouvelle introduction beaucoup plus courte."},
            {"nuance": "Une nuance différente.", "conclusion": "Ma nouvelle conclusion."},
        ):
            current = effective_response(self.prompt.response, self.user, prompt=self.prompt)
            content = replace(current, **changes)
            saved = self.save(content)
            self.assertEqual(saved.pk, first.pk)
            self.assertEqual(saved.created_at, first.created_at)
            self.assert_attached(mark, content)
        self.assertEqual(PersonalResponse.objects.filter(
            user=self.user, response=self.prompt.response,
        ).count(), 1)
        self.assertFalse(OralStateSnapshot.objects.filter(user=self.user).exists())

    @override_settings(FRENCH_AUDIO_ENABLED=True)
    def test_private_detail_and_practice_keep_the_full_response_without_public_audio(self):
        after = self.edited_example(self.model)
        marks = [
            self.mark(
                self.model, self.prompt.text if surface == "front" else self.model.arguments[1].exemple,
                surface=surface,
            )
            for surface in ("detail", "front", "back")
        ]
        self.save(after)
        for mark, surface in zip(marks, ("detail", "front", "back")):
            self.assert_attached(mark, after, surface=surface)
            self.assertIn(mark.pk, self.visible(mark.source_path))
        detail = self.client.get(prompt_detail_url(self.prompt))
        self.assertContains(detail, "Modifier la réponse")
        self.assertContains(detail, after.arguments[0].exemple)
        self.assertNotContains(detail, "Version personnelle")
        self.assertFalse(detail.context["reviewed_eo3"])
        self.assertTrue(detail.context["structured_eo3"])
        self.assertFalse(detail.context["eo3_audio"]["ready"])
        payload = _spine_payload(self.card, prompt=self.prompt)
        self.assertTrue(payload["structured_eo3"])
        self.assertFalse(payload["eo3_audio"]["ready"])
        self.assertIn(after.arguments[0].exemple, payload["speech_text"])
        self.assertTrue(payload["response_content"].is_personal)
        back = render_to_string("study/partials/card_back.html", payload)
        grant = re.search(r'data-speech-grant="([^"]+)"', back)
        self.assertIsNotNone(grant)
        sources = [{"grant": grant[1]}]
        with self.assertRaises(SpeechError) as denied:
            resolve_sources(sources, self.user.pk)
        self.assertEqual(denied.exception.code, "consent")
        self.assertEqual(
            resolve_sources(sources, self.user.pk, consent=True),
            (normalize_text(payload["speech_text"]), self.user.pk),
        )
        with self.assertRaises(SpeechError):
            resolve_sources(sources, self.other.pk, consent=True)

    def test_already_disconnected_model_selections_are_recovered_without_a_snapshot(self):
        mark = self.mark(
            self.model, self.model.arguments[1].exemple.split()[0],
            field="argument-2-exemple", anchored=False,
        )
        after = self.edited_example(self.model)
        self.personal(after)
        self.assertIn(mark.pk, self.visible())
        self.assert_attached(mark, after)
        self.assertTrue(mark.response_anchor)
        self.assertFalse(OralStateSnapshot.objects.filter(user=self.user).exists())

    def test_old_private_namespace_moves_to_the_current_response_before_another_edit(self):
        before = replace(self.model, position_claire="Mon introduction privée, avec une idée personnelle.", is_personal=True)
        personal = self.personal(before)
        marks = [
            self.mark(before, before.position_claire, legacy=True, anchored=False),
            self.mark(before, before.conclusion, legacy=True, anchored=False, kind=AnnotationKind.NOTE),
        ]
        after = self.edited_example(before)
        self.assertEqual(self.save(after).pk, personal.pk)
        for mark in marks:
            self.assert_attached(mark, after)
            self.assertTrue(mark.response_anchor)
        self.assertIn(marks[0].pk, self.visible())
        self.assertFalse(OralStateSnapshot.objects.filter(user=self.user).exists())

    def test_owned_old_snapshot_can_prove_a_disconnected_private_namespace(self):
        before = replace(self.model, position_claire="Une introduction privée plus ancienne.", is_personal=True)
        personal = self.personal(before)
        mark = self.mark(before, before.arguments[1].exemple, legacy=True, anchored=False)
        snapshot(personal, "personal")
        after = self.edited_example(before)
        PersonalResponse.objects.filter(pk=personal.pk).update(arguments=asdict(after)["arguments"])
        self.assertIn(mark.pk, self.visible())
        self.assert_attached(mark, after)
        self.assertEqual(OralStateSnapshot.objects.filter(user=self.user).count(), 1)

    def test_another_users_snapshot_does_not_authorize_unknown_namespaces(self):
        private = replace(self.model, position_claire="L'introduction privée d'un autre compte.", is_personal=True)
        other = self.personal(private, user=self.other)
        snapshot(other, "personal")
        mark = self.mark(
            private, private.arguments[1].exemple, legacy=True, anchored=False,
        )
        before = Annotation.objects.filter(pk=mark.pk).values().get()
        self.visible()
        self.assertEqual(Annotation.objects.filter(pk=mark.pk).values().get(), before)

    def test_duplicate_destination_keeps_both_saved_records(self):
        before = replace(self.model, position_claire="Mon introduction privée.", is_personal=True)
        self.personal(before)
        old = self.mark(before, before.conclusion, legacy=True, anchored=False)
        current = self.mark(before, before.conclusion)
        self.visible()
        self.assertEqual(set(Annotation.objects.values_list("pk", flat=True)), {old.pk, current.pk})
        self.assertIn(current.pk, self.visible())

    def test_special_argument_identities_survive_private_edits(self):
        prompt = self.get_prompt("economie:p22")
        model = catalogue.tache_three_models()[prompt.response.semantic_group].response
        mark = self.mark(model, model.arguments[1].exemple, prompt=prompt)
        after = self.edited_example(model)
        self.save(after, prompt)
        self.assertEqual([arg.annotation_id for arg in annotation_arguments(prompt, after)], [1, 4, 2])
        self.assert_attached(mark, after, prompt=prompt)
        self.assertEqual(mark.response_anchor["field"], "argument-4-exemple")

    def test_saved_private_argument_identities_do_not_follow_later_public_model_rewrites(self):
        after = self.edited_example(self.model)
        personal = self.save(after)
        self.assertEqual([argument["annotation_id"] for argument in personal.arguments], [1, 2, 3])
        current = effective_response(self.prompt.response, self.user, prompt=self.prompt)
        mark = self.mark(
            current, current.arguments[1].exemple, field="argument-2-exemple",
        )
        models = catalogue.tache_three_models()
        group = self.prompt.response.semantic_group
        replacement = replace(
            models[group],
            response=replace(self.model, arguments=(
                self.model.arguments[0],
                replace(self.model.arguments[1], idea="Un argument public entièrement différent."),
                replace(self.model.arguments[2], idea="Une autre raison publique."),
            )),
            argument_ids=(1, 4, 5),
        )
        with patch("study.catalogue.tache_three_models", return_value={**models, group: replacement}):
            self.assertEqual(
                [argument.annotation_id for argument in annotation_arguments(self.prompt, current)],
                [1, 2, 3],
            )
            self.assertIn(mark.pk, self.visible())
            saved = self.save(replace(current, nuance="Une nouvelle nuance privée."))
            self.assertEqual(saved.pk, personal.pk)
            self.assertEqual([argument["annotation_id"] for argument in saved.arguments], [1, 2, 3])
            self.assert_attached(mark, current)
        self.assertFalse(OralStateSnapshot.objects.filter(user=self.user).exists())

    def test_model_reset_keeps_one_row_and_does_not_create_a_response_archive(self):
        mark = self.mark(self.model, self.model.conclusion)
        personal = self.save(self.edited_example(self.model))
        result = self.client.post(
            reverse("study:edit_response", args=["eo", "tache-3", self.prompt.pk]),
            {"action": "reset"},
        )
        self.assertEqual(result.status_code, 302)
        self.assert_attached(mark, self.model)
        personal.refresh_from_db()
        self.assertFalse(personal.is_active)
        self.assertFalse(OralStateSnapshot.objects.filter(user=self.user).exists())
        self.assertEqual(self.save(self.edited_example(self.model)).pk, personal.pk)

    def test_editor_starts_with_model_and_labels_position_as_pistes_metadata(self):
        page = self.client.get(reverse(
            "study:edit_response", args=["eo", "tache-3", self.prompt.pk],
        ))
        self.assertEqual(page.context["form"]["position_claire"].value(), self.model.position_claire)
        self.assertContains(page, "Enregistrer la réponse")
        self.assertNotContains(page, "Enregistrer ma version")
        self.assertNotContains(page, "Version personnelle")
        self.assertFalse(page.context["form"]["position"].is_hidden)
        self.assertEqual(page.context["form"]["position"].value(), self.model.position)
        self.assertContains(page, "Position (Pistes)")
        self.assertContains(page, "Repère affiché dans les Pistes, pas dans le texte de la réponse.")
        self.assertLess(
            page.content.index(b'for="id_position_claire"'),
            page.content.index(b'for="id_position"'),
        )
        self.assertTrue(page.context["form"]["reformulation"].is_hidden)
        self.assertFalse(PersonalResponse.objects.exists())

    def test_position_is_in_pistes_not_the_spoken_answer_for_models_and_edits(self):
        for content in (
            self.model,
            replace(self.model, position="Mon avis personnel pour les Pistes.", is_personal=True),
        ):
            with self.subTest(personal=content.is_personal):
                if content.is_personal:
                    self.save(content)
                page = self.client.get(prompt_detail_url(self.prompt))
                html = page.content.decode()
                answer = AnnotationRootText(html, root_class="answer-columns")
                position = AnnotationRootText(html, root_class="subject-hints__position")
                self.assertNotIn(content.position.encode("utf-16-le"), answer.text)
                self.assertIn(content.position.encode("utf-16-le"), position.text)
                self.assertContains(
                    page,
                    f'data-annotation-source-key="{variant_annotation_key(self.prompt, content)}:position"',
                    count=1,
                )
                self.assertContains(page, 'data-prompt-copy-source="eo3-response-content"', count=1)
                self.assertContains(page, "data-response-edit", count=1)
                self.assertEqual(
                    answer.text,
                    render_current_response(self.prompt, content, "detail", self.user).text,
                )
                self.assertEqual(
                    position.text,
                    render_current_response(self.prompt, content, "position", self.user).text,
                )
                payload = _spine_payload(self.card, prompt=self.prompt)
                practice = render_to_string("study/partials/card_back.html", payload)
                self.assertInHTML(
                    f'<p class="spine-text" lang="fr">{content.position}</p>',
                    practice,
                )
                self.assertNotIn("data-response-field", practice)
                self.assertEqual(payload["speech_text"], response_text(content))
                self.assertEqual(page.context["eo3_response_copy_text"], response_text(content))

    def test_empty_private_position_stays_empty_and_shows_an_explicit_pistes_prompt(self):
        personal = self.save(replace(self.model, position="", is_personal=True))
        page = self.client.get(prompt_detail_url(self.prompt))
        self.assertContains(page, "À préciser dans l'introduction.")
        self.assertNotContains(page, 'data-response-field="position"')
        personal.refresh_from_db()
        self.assertEqual(personal.position, "")

    def test_old_private_position_selections_follow_the_field_into_pistes(self):
        before = replace(
            self.model, position="Mon ancienne position personnelle.", is_personal=True,
        )
        self.personal(before)
        marks = [
            self.mark(before, before.position, legacy=True, field="position"),
            self.mark(
                before, "ancienne position", legacy=True, field="position", anchored=False,
                source_key=variant_annotation_key(self.prompt, before),
            ),
            self.mark(
                before, before.position, legacy=True, field="position",
                kind=AnnotationKind.NOTE,
            ),
        ]
        introduction = self.mark(
            before, before.position_claire, legacy=True, field="introduction",
        )
        saved = list(PersonalResponse.objects.values())
        self.client.get(prompt_detail_url(self.prompt))
        visible = self.visible()
        for mark in marks:
            if mark.kind == AnnotationKind.HIGHLIGHT:
                self.assertIn(mark.pk, visible)
            self.assert_attached(mark, before, surface="position")
            self.assertEqual(mark.response_anchor["field"], "position")
        self.assert_attached(introduction, before)
        self.assertEqual(list(PersonalResponse.objects.values()), saved)

    def test_forged_old_position_context_is_not_moved_to_pistes(self):
        before = replace(
            self.model, position="Mon ancienne position personnelle.", is_personal=True,
        )
        self.personal(before)
        mark = self.mark(
            before, before.position, legacy=True, field="position", anchored=False,
            prefix="Un contexte inventé qui ne prouve pas la sélection.",
        )
        saved = Annotation.objects.filter(pk=mark.pk).values().get()
        self.client.get(prompt_detail_url(self.prompt))
        self.visible()
        self.assertEqual(Annotation.objects.filter(pk=mark.pk).values().get(), saved)

    def test_copy_uses_the_current_response_in_french_paragraphs_without_ui_or_hints(self):
        for model in catalogue.tache_three_models().values():
            with self.subTest(group=model.group):
                copied = response_text(model.response)
                self.assertEqual(len(copied.split("\n\n")), 6)
                self.assertEqual(copied.replace("\n\n", " "), spoken_text(model.response))
        after = self.edited_example(self.model)
        self.save(after)
        page = self.client.get(prompt_detail_url(self.prompt))
        self.assertContains(page, "Copier le sujet")
        self.assertContains(page, "Copier la réponse")
        self.assertContains(page, 'data-prompt-copy-source="eo3-subject-content"', count=1)
        self.assertContains(page, 'data-prompt-copy-source="eo3-response-content"', count=1)
        self.assertContains(page, 'id="eo3-subject-content"', count=1)
        self.assertContains(page, 'id="eo3-response-content"', count=1)
        self.assertContains(page, 'class="icon-button prompt-copy-button"', count=2)
        for label in ("Copier le sujet", "Copier la réponse"):
            self.assertInHTML(
                f'<span class="sr-only" data-prompt-copy-label>{label}</span>',
                page.content.decode(),
            )
        self.assertEqual(page.context["eo3_response_copy_text"], response_text(after))
        self.assertIn(after.arguments[0].exemple, page.context["eo3_response_copy_text"])
        self.assertNotIn(self.model.arguments[0].exemple, page.context["eo3_response_copy_text"])
        self.assertEqual(
            AnnotationRootText(page.content.decode(), root_class="answer-columns").text,
            render_current_response(self.prompt, after, "detail", self.user).text,
        )

    def test_legacy_private_position_stays_in_pistes_with_editing_controls_on_the_answer(self):
        self.save(replace(
            self.model, position="Mon ancienne position personnelle.",
            position_claire="", is_personal=True,
        ))
        page = self.client.get(prompt_detail_url(self.prompt))
        self.assertContains(page, "Mon ancienne position personnelle.", count=1)
        self.assertContains(page, 'data-prompt-copy-source="eo3-response-content"', count=1)
        self.assertContains(page, "data-response-edit", count=1)
        current = effective_response(self.prompt.response, self.user, prompt=self.prompt)
        self.assertEqual(
            AnnotationRootText(page.content.decode(), root_class="answer-columns").text,
            render_current_response(self.prompt, current, "detail", self.user).text,
        )
        editor = self.client.get(reverse(
            "study:edit_response", args=["eo", "tache-3", self.prompt.pk],
        ))
        self.assertFalse(editor.context["form"]["position"].is_hidden)
        self.assertTrue(editor.context["form"]["reformulation"].is_hidden)
        self.client.force_login(self.other)
        self.assertNotContains(
            self.client.get(prompt_detail_url(self.prompt)), "Mon ancienne position personnelle.",
        )

    def test_other_accounts_prompts_and_study_state_are_unchanged(self):
        other_prompt = self.get_prompt("culture:p2")
        other_model = catalogue.tache_three_models()[other_prompt.response.semantic_group].response
        other_mark = self.mark(
            other_model, other_model.conclusion, prompt=other_prompt,
        )
        other_user_mark = self.mark(self.model, self.model.conclusion, user=self.other)
        ids = [other_mark.pk, other_user_mark.pk]
        annotations = list(Annotation.objects.filter(pk__in=ids).order_by("pk").values())
        cards = list(Card.objects.values())
        shared = asdict(effective_response(self.prompt.response, self.other, prompt=self.prompt))
        self.save(self.edited_example(self.model))
        self.assertEqual(list(Annotation.objects.filter(pk__in=ids).order_by("pk").values()), annotations)
        self.assertEqual(list(Card.objects.values()), cards)
        self.assertEqual(asdict(effective_response(self.prompt.response, self.other, prompt=self.prompt)), shared)

    def test_legacy_namespace_with_forged_context_is_not_recovered(self):
        private = replace(self.model, position_claire="Mon introduction privée.", is_personal=True)
        self.personal(private)
        mark = self.mark(
            private, private.conclusion, legacy=True, anchored=False,
            prefix="Un contexte qui ne correspond pas au texte sélectionné.",
        )
        before = Annotation.objects.filter(pk=mark.pk).values().get()
        self.visible()
        self.assertEqual(Annotation.objects.filter(pk=mark.pk).values().get(), before)

    def test_malformed_legacy_snapshot_warns_without_losing_saved_selections(self):
        mark = self.mark(
            self.model, self.model.conclusion,
            source_key=f"response:{self.prompt.content_key}:variant-{'f' * 16}",
        )
        record = OralStateSnapshot.objects.create(
            user=self.user, response=self.prompt.response, kind="personal",
            source_id=987654, digest="malformed-private", payload={"fields": {"arguments": None}},
        )
        before = Annotation.objects.filter(pk=mark.pk).values().get()
        with self.assertLogs("study.public_response_annotations", level="WARNING") as logged:
            self.visible()
        self.assertTrue(any(str(record.pk) in message for message in logged.output))
        self.assertEqual(Annotation.objects.filter(pk=mark.pk).values().get(), before)
