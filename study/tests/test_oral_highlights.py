from django.test import TestCase
from django.urls import reverse

from study.models import Annotation, AnnotationKind, PersonalResponse, Prompt
from study.oral_highlights import _render_questions
from study.oral_history import variant_annotation_key
from study.response_personalization import effective_response
from study.routing import prompt_detail_url

from . import factories


class OralHighlightPersonalizationTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("eo2-highlights")
        self.task = factories.make_task(factories.make_part("eo"), "tache-2")
        self.response = factories.make_response(theme=factories.make_theme(task=self.task))
        self.response.content_key = "tache2:janvier:batch-01:subject-01"
        self.response.semantic_group = "eo2-highlight-test"
        self.response.save(update_fields=["content_key", "semantic_group"])
        self.prompt = self.response.prompts.get()
        self.rows = [
            ("Quel budget prévoir ?", "Environ cent euros."),
            ("Quel horaire prévoir ?", "Le samedi matin."),
            ("Où se trouve l’accueil ?", "À côté du café."),
        ]
        self.prompt.content_key = self.response.content_key
        self.prompt.model_content = {
            "storage_key": self.response.content_key,
            "reformulation": "", "position": "", "position_claire": "",
            "arguments": self._arguments(self.rows), "nuance": "", "conclusion": "",
        }
        self.prompt.save(update_fields=["content_key", "model_content"])
        self.path = prompt_detail_url(self.prompt)
        self.edit_url = reverse("study:edit_response", args=["eo", "tache-2", self.prompt.pk])
        self.client.force_login(self.user)

    def _arguments(self, rows):
        return [
            {"order": number, "idea": question, "developpement": answer, "exemple": "", "consequence": ""}
            for number, (question, answer) in enumerate(rows, 1)
        ]

    def _content(self):
        return effective_response(self.response, self.user, prompt=self.prompt)

    def _highlight(self, number, field="question", *, surface="detail", quote=None, **overrides):
        content = self._content()
        rendered = _render_questions(self.prompt, content, surface, [self.prompt])
        start, end = rendered.fields[(number, field)]
        if quote is not None:
            start = rendered.text.index(quote.encode("utf-16-le"), start * 2, end * 2) // 2
            end = start + len(quote.encode("utf-16-le")) // 2
        values = {
            "user": self.user, "task": self.task, "kind": AnnotationKind.HIGHLIGHT,
            "source_path": self.path,
            "source_key": variant_annotation_key(self.prompt, content) + (":back" if surface == "back" else ""),
            "start_offset": start, "end_offset": end,
            "quote": rendered.slice(start, end),
            "prefix": rendered.slice(max(0, start - 160), start),
            "suffix": rendered.slice(end, end + 160),
        }
        return Annotation.objects.create(**(values | overrides))

    def _save(self, rows, *, deleted=()):
        initial = len(self._content().arguments)
        payload = {
            "questions-TOTAL_FORMS": str(len(rows)), "questions-INITIAL_FORMS": str(initial),
            "questions-MIN_NUM_FORMS": "1", "questions-MAX_NUM_FORMS": "30", "action": "save",
        }
        for index, (question, answer) in enumerate(rows):
            payload[f"questions-{index}-question"] = question
            payload[f"questions-{index}-response"] = answer
            if index in deleted:
                payload[f"questions-{index}-DELETE"] = "on"
        result = self.client.post(self.edit_url, payload)
        self.assertEqual(result.status_code, 302)

    def _assert_current(self, annotation, *, surface="detail"):
        annotation.refresh_from_db()
        content = self._content()
        key = variant_annotation_key(self.prompt, content) + (":back" if surface == "back" else "")
        self.assertEqual(annotation.source_key, key)
        rendered = _render_questions(self.prompt, content, surface, [self.prompt])
        self.assertEqual(
            rendered.slice(annotation.start_offset, annotation.end_offset), annotation.quote
        )
        return annotation

    def test_first_personal_save_without_text_changes_preserves_every_highlight(self):
        marks = [self._highlight(number) for number in (1, 2, 3)]
        old_key = marks[0].source_key
        self._save(self.rows)
        self.assertNotEqual(variant_annotation_key(self.prompt, self._content()), old_key)
        for mark in marks:
            self._assert_current(mark)
        self.assertEqual(Annotation.objects.count(), 3)

    def test_edits_only_reset_the_changed_question_or_prepared_answer(self):
        question = self._highlight(1)
        changed_answer = self._highlight(1, "response")
        changed_question = self._highlight(2, quote="Quel")
        answer = self._highlight(2, "response")
        last = self._highlight(3, body="Ma note.", title="À retenir", study_later=True)
        old_key = question.source_key
        rows = [
            (self.rows[0][0], "Deux cents euros, avec une réduction."),
            ("Quel horaire serait possible le dimanche ?", self.rows[1][1]),
            self.rows[2],
        ]
        self._save(rows)
        for mark in (question, answer, last):
            self._assert_current(mark)
        for mark in (changed_answer, changed_question):
            mark.refresh_from_db()
            self.assertEqual(mark.source_key, old_key)
        self.assertEqual((last.body, last.title, last.study_later), ("Ma note.", "À retenir", True))
        self._save([("Un nouveau texte plus long ?", rows[0][1]), *rows[1:]])
        for mark in (answer, last):
            self._assert_current(mark)
        self.assertEqual(Annotation.objects.count(), 5)

    def test_deleting_an_earlier_question_keeps_renumbered_question_highlights(self):
        removed = self._highlight(1)
        retained = self._highlight(3)
        old_offset = retained.start_offset
        self._save(self.rows, deleted=(0,))
        self._assert_current(retained)
        self.assertLess(retained.start_offset, old_offset)
        removed.refresh_from_db()
        self.assertNotEqual(removed.source_key, retained.source_key)
        self.assertEqual(Annotation.objects.count(), 2)

    def test_identical_question_text_does_not_move_a_highlight_to_an_edited_row(self):
        retained = self._highlight(2)
        self._save([self.rows[1], *self.rows[1:]])
        self._assert_current(retained)
        rendered = _render_questions(self.prompt, self._content(), "detail", [self.prompt])
        self.assertEqual(retained.start_offset, rendered.fields[(2, "question")][0])

    def test_reset_keeps_unchanged_fields_and_does_not_delete_changed_highlights(self):
        self._save([("Une question personnelle ?", self.rows[0][1]), *self.rows[1:]])
        changed = self._highlight(1)
        kept = self._highlight(2)
        old_key = changed.source_key
        self.assertEqual(self.client.post(self.edit_url, {"action": "reset"}).status_code, 302)
        self._assert_current(kept)
        changed.refresh_from_db()
        self.assertEqual(changed.source_key, old_key)
        self.assertEqual(Annotation.objects.count(), 2)

    def test_existing_hidden_model_highlights_are_recovered_on_the_next_save(self):
        kept = self._highlight(2)
        rows = [("Une question déjà personnalisée ?", self.rows[0][1]), *self.rows[1:]]
        PersonalResponse.objects.create(
            user=self.user, response=self.response, source_prompt=self.prompt,
            arguments=self._arguments(rows),
        )
        self._save(rows)
        self._assert_current(kept)

    def test_review_and_legacy_highlights_keep_unicode_offsets(self):
        self.rows[0] = ("Un café ☕ ou un film 🎬 ?", "L’après-midi & le soir.")
        self.prompt.model_content["arguments"] = self._arguments(self.rows)
        self.prompt.save(update_fields=["model_content"])
        review = self._highlight(
            2, surface="back",
            source_path=reverse("study:task_review", args=["eo", "tache-2"]) + "?reset=1",
        )
        legacy = self._highlight(
            2, source_key="tache-two:janvier:batch-1:subject-1",
        )
        self._save([("Quand partir 🎬 avec les enfants ?", self.rows[0][1]), *self.rows[1:]])
        self._assert_current(review, surface="back")
        self._assert_current(legacy)

    def test_review_prompt_highlights_follow_question_edits(self):
        key = variant_annotation_key(self.prompt, self._content()) + ":front"
        front = Annotation.objects.create(
            user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
            source_path=reverse("study:review") + "?kind=spine&reset=1",
            source_key=key, quote=self.prompt.text,
            start_offset=10, end_offset=10 + len(self.prompt.text),
        )
        self._save([("Une nouvelle question ?", ""), *self.rows[1:]])
        front.refresh_from_db()
        self.assertEqual(
            front.source_key, variant_annotation_key(self.prompt, self._content()) + ":front"
        )
        self.assertEqual(front.quote, self.prompt.text)
        self.assertEqual(front.start_offset, 10)

    def test_other_users_and_unrelated_annotations_are_untouched(self):
        kept = self._highlight(2)
        other_user = self._highlight(2, user=factories.make_user("other-highlights"))
        other_source = self._highlight(2, source_path="/another-subject/")
        old = (other_user.source_key, other_source.source_key)
        self._save([("Une question différente ?", ""), *self.rows[1:]])
        self._assert_current(kept)
        other_user.refresh_from_db()
        other_source.refresh_from_db()
        self.assertEqual((other_user.source_key, other_source.source_key), old)

    def test_existing_destination_highlight_preserves_both_private_records(self):
        old_model = self._highlight(2, body="Note du modèle.")
        rows = [("Une question personnelle ?", self.rows[0][1]), *self.rows[1:]]
        PersonalResponse.objects.create(
            user=self.user, response=self.response, source_prompt=self.prompt,
            arguments=self._arguments(rows),
        )
        current = self._highlight(2, body="Note personnelle.")
        self._save(rows)
        self._assert_current(current)
        old_model.refresh_from_db()
        self.assertEqual(old_model.body, "Note du modèle.")
        self.assertEqual(Annotation.objects.count(), 2)

    def test_equivalent_prompt_keeps_its_own_unchanged_model_highlights(self):
        alias_model = {
            **self.prompt.model_content,
            "arguments": self._arguments([("Un autre point de départ ?", ""), *self.rows[1:]]),
        }
        alias = Prompt.objects.create(
            content_key="tache2:mars:batch-01:subject-02",
            response=self.response, theme=self.prompt.theme, family=self.prompt.family,
            number=self.prompt.number + 1, text="Autre formulation.", model_content=alias_model,
        )
        old = effective_response(self.response, self.user, prompt=alias)
        rendered = _render_questions(alias, old, "detail", [self.prompt, alias])
        start, end = rendered.fields[(2, "question")]
        mark = Annotation.objects.create(
            user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
            source_path=prompt_detail_url(alias), source_key=variant_annotation_key(alias, old),
            quote=rendered.slice(start, end), start_offset=start, end_offset=end,
        )
        self._save([("Un nouveau point de départ ?", ""), *self.rows[1:]])
        mark.refresh_from_db()
        current = effective_response(self.response, self.user, prompt=alias)
        self.assertEqual(mark.source_key, variant_annotation_key(alias, current))
        self.assertNotEqual(mark.source_key, variant_annotation_key(self.prompt, current))

    def test_deleting_a_duplicate_question_does_not_restore_its_removed_anchor(self):
        self.rows[1] = self.rows[0]
        self.prompt.model_content["arguments"] = self._arguments(self.rows)
        self.prompt.save(update_fields=["model_content"])
        removed = self._highlight(1)
        kept = self._highlight(2)
        old_key = removed.source_key
        self._save(self.rows, deleted=(0,))
        self._assert_current(kept)
        self._save(self.rows[1:])
        self._assert_current(kept)
        removed.refresh_from_db()
        self.assertEqual(removed.source_key, old_key)
