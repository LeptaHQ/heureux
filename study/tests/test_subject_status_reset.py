from datetime import timedelta
from dataclasses import asdict
from io import StringIO

from django.core.management import call_command
from django.template.defaultfilters import date as date_filter
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from study.account_services import provision_user_study_data
from study import catalogue
from study.models import Annotation, AnnotationKind, Card, CardType, PersonalResponse, Prompt
from study.oral_highlights import AnnotationRootText
from study.progress import mark_card_started, subject_progress_by_response
from study.oral_highlights import _render_questions
from study.oral_history import variant_annotation_key
from study.tache_two_dialogues import dialogue_response
from study.routing import prompt_detail_url, review_url

from . import factories


class SubjectStatusResetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("status-reset-learner")
        provision_user_study_data(cls.user)

    def setUp(self):
        self.client.force_login(self.user)
        self.prompt = Prompt.objects.select_related(
            "response__theme__task__part", "theme__task__part",
        ).get(content_key="culture:p1")
        self.response_id = self.prompt.response_id
        self.url = reverse(
            "study:subject_completion", args=["eo", "tache-3", self.response_id],
        )

    def post(self, data):
        return self.client.post(self.url, data, HTTP_X_REQUESTED_WITH="fetch")

    def status(self):
        return subject_progress_by_response(
            self.user, {self.response_id},
        )[self.response_id].status

    def card(self):
        return Card.objects.get(
            user=self.user, card_type=CardType.SPINE, response_id=self.response_id,
        )

    def add_highlight(self, created_at, word=0):
        detail_url = prompt_detail_url(self.prompt)
        text = AnnotationRootText(self.client.get(detail_url).content.decode()).text
        words = [item for item in text.split() if len(item) > 3]
        quote = words[word]
        start = text.index(quote, text.index(words[word - 1]) + 1 if word else 0)
        return Annotation.objects.create(
            user=self.user, task=self.prompt.theme.task, kind=AnnotationKind.HIGHLIGHT,
            source_path=detail_url, source_key=f"response:{self.prompt.response.content_key}",
            quote=quote, start_offset=start, end_offset=start + len(quote),
            prefix=text[max(0, start - 160):start],
            suffix=text[start + len(quote):start + len(quote) + 160],
            created_at=created_at,
        )

    def test_done_subject_with_activity_resets_to_new_without_losing_history(self):
        card = self.card()
        mark_card_started(self.user, card)
        self.assertEqual(self.post({"completed": "1"}).json()["subject"]["status"], "done")
        practice_started = self.card().response_practice_started_at

        reset = self.post({"completed": "0", "action": "reset"})

        self.assertEqual(reset.status_code, 200)
        self.assertEqual(reset.json()["subject"], {"status": "new", "label": "À commencer"})
        self.assertFalse(reset.json()["completed"])
        card = self.card()
        self.assertIsNone(card.subject_completed_at)
        self.assertIsNotNone(card.subject_status_reset_at)
        self.assertEqual(card.response_practice_started_at, practice_started)

        again = self.post({"completed": "0", "action": "reset"})
        self.assertEqual(again.json()["subject"]["status"], "new")

    def test_new_activity_after_reset_reactivates_but_completion_wins(self):
        mark_card_started(self.user, self.card())
        self.post({"completed": "0", "action": "reset"})
        self.assertEqual(self.status(), "new")

        mark_card_started(self.user, self.card())

        self.assertIsNone(self.card().subject_status_reset_at)
        self.assertEqual(self.status(), "active")
        self.post({"completed": "0", "action": "reset"})
        self.assertEqual(self.post({"completed": "1"}).json()["subject"]["status"], "done")
        self.assertIsNone(self.card().subject_status_reset_at)

    def test_only_highlights_newer_than_reset_reactivate(self):
        self.add_highlight(timezone.now() - timedelta(days=1))
        self.assertEqual(self.status(), "active")
        self.post({"completed": "0", "action": "reset"})
        self.assertEqual(self.status(), "new")

        self.add_highlight(timezone.now() + timedelta(seconds=1), word=1)

        self.assertEqual(self.status(), "active")

    def started_at(self):
        return subject_progress_by_response(
            self.user, {self.response_id},
        )[self.response_id].started_at

    def test_started_date_follows_each_move_to_in_progress(self):
        detail_url = prompt_detail_url(self.prompt)
        self.assertIsNone(self.started_at())
        self.assertNotContains(self.client.get(detail_url), "<dt>Commencée</dt>")

        first_highlight = timezone.now() - timedelta(days=3)
        self.add_highlight(first_highlight)
        self.assertEqual(self.started_at(), first_highlight)
        mark_card_started(self.user, self.card())
        self.assertEqual(self.started_at(), first_highlight)
        page = self.client.get(detail_url)
        self.assertContains(
            page,
            f"<dt>Commencée</dt><dd>{date_filter(timezone.localtime(first_highlight), 'j M Y')}</dd>",
        )

        self.post({"completed": "0", "action": "reset"})
        self.assertEqual(self.status(), "new")
        self.assertIsNone(self.started_at())
        self.assertNotContains(self.client.get(detail_url), "<dt>Commencée</dt>")

        mark_card_started(self.user, self.card())
        restarted = self.card().subject_started_at
        self.assertIsNotNone(restarted)
        self.assertEqual(self.status(), "active")
        self.assertEqual(self.started_at(), restarted)

        self.post({"completed": "0", "action": "reset"})
        highlighted = timezone.now() + timedelta(seconds=1)
        self.add_highlight(highlighted, word=1)
        self.assertEqual(self.status(), "active")
        self.assertEqual(self.started_at(), highlighted)

        self.post({"completed": "1"})
        self.assertEqual(self.status(), "done")
        self.assertEqual(self.started_at(), self.card().subject_started_at)

    def test_invalid_reset_requests_are_rejected_without_changes(self):
        self.post({"completed": "1"})
        for data in (
            {"completed": "1", "action": "reset"},
            {"completed": "0", "action": "erase"},
        ):
            with self.subTest(data=data):
                self.assertEqual(self.post(data).status_code, 400)
        ee_url = reverse(
            "study:subject_completion", args=["eo", "tache-2", self.response_id],
        )
        self.assertIn(
            self.client.post(ee_url, {"completed": "0", "action": "reset"}).status_code,
            {400, 404},
        )
        card = self.card()
        self.assertIsNotNone(card.subject_completed_at)
        self.assertIsNone(card.subject_status_reset_at)

    def test_detail_header_shows_reset_control_without_changing_annotation_text(self):
        page = self.client.get(prompt_detail_url(self.prompt))
        self.assertContains(page, 'data-subject-reset-form', count=1)
        self.assertContains(page, 'name="action" value="reset"', count=1)
        self.assertContains(page, "Remettre ce sujet à commencer")

    def test_reset_hides_subject_highlights_without_deleting_or_editing_saved_work(self):
        highlight = self.add_highlight(timezone.now())
        note = Annotation.objects.create(
            user=self.user, task=self.prompt.theme.task, kind=AnnotationKind.NOTE,
            source_path=highlight.source_path, source_key=highlight.source_key,
            quote=highlight.quote, body="Keep my note.", study_later=True,
        )
        back = Annotation.objects.create(
            user=self.user, task=self.prompt.theme.task, kind=AnnotationKind.HIGHLIGHT,
            source_path=highlight.source_path, source_key=highlight.source_key + ":back",
            quote=highlight.quote, start_offset=0, end_offset=len(highlight.quote),
        )
        other = factories.make_user("other-reset-learner")
        other_highlight = Annotation.objects.create(
            user=other, task=self.prompt.theme.task, kind=AnnotationKind.HIGHLIGHT,
            source_path=highlight.source_path, source_key=highlight.source_key,
            quote=highlight.quote, start_offset=0, end_offset=len(highlight.quote),
        )
        other_prompt = Prompt.objects.select_related("response", "theme").get(content_key="culture:p2")
        unrelated = Annotation.objects.create(
            user=self.user, task=other_prompt.theme.task, kind=AnnotationKind.HIGHLIGHT,
            source_path=prompt_detail_url(other_prompt),
            source_key=f"response:{other_prompt.response.content_key}",
            quote="Other subject", start_offset=0, end_offset=13,
        )
        before = list(Annotation.objects.order_by("pk").values())

        result = self.post({"completed": "0", "action": "reset"})

        self.assertEqual(result.status_code, 200)
        self.assertCountEqual(result.json()["hidden_highlight_ids"], [highlight.pk, back.pk])
        self.assertEqual(list(Annotation.objects.order_by("pk").values()), [
            {**row, "hidden_on_source": row["id"] in {highlight.pk, back.pk}}
            for row in before
        ])
        for item in (note, other_highlight, unrelated):
            item.refresh_from_db()
            self.assertFalse(item.hidden_on_source)
        visible = self.client.get(
            reverse("study:annotations_for_source"), {"source_path": highlight.source_path},
        )
        self.assertEqual(visible.json()["highlights"], [])
        self.assertEqual(
            self.post({"completed": "0", "action": "reset"}).json()["hidden_highlight_ids"], [],
        )
        folder = self.client.get(
            reverse("study:task_notes", args=["eo", "tache-3"]), {"tab": "highlights"},
        )
        self.assertContains(folder, f'id="highlight-{highlight.pk}"')
        exported = self.client.get(reverse("study:export_account")).json()["annotations"]
        archived = next(row for row in exported if row["id"] == highlight.pk)
        self.assertTrue(archived["hidden_on_source"])

    def test_same_passage_can_be_highlighted_again_without_reusing_hidden_record(self):
        original = self.add_highlight(timezone.now())
        self.post({"completed": "0", "action": "reset"})
        original.refresh_from_db()
        saved = Annotation.objects.filter(pk=original.pk).values().get()
        payload = {
            "kind": "highlight", "task_id": self.prompt.theme.task_id,
            "source_path": original.source_path, "source_key": original.source_key,
            "quote": original.quote, "start_offset": original.start_offset,
            "end_offset": original.end_offset, "prefix": original.prefix,
            "suffix": original.suffix, "overlap_ids": "",
        }

        created = self.client.post(reverse("study:annotation_create"), payload)

        self.assertEqual(created.status_code, 201, created.content)
        self.assertNotEqual(created.json()["id"], original.pk)
        self.assertEqual(Annotation.objects.filter(pk=original.pk).values().get(), saved)
        duplicate = self.client.post(reverse("study:annotation_create"), payload)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.json()["id"], created.json()["id"])
        self.assertEqual(self.status(), "active")
        visible = self.client.get(
            reverse("study:annotations_for_source"), {"source_path": original.source_path},
        ).json()["highlights"]
        self.assertEqual([row["id"] for row in visible], [created.json()["id"]])
        self.post({"completed": "0", "action": "reset"})
        third = self.client.post(reverse("study:annotation_create"), payload)
        self.assertEqual(third.status_code, 201)
        self.assertEqual(Annotation.objects.filter(user=self.user, kind="highlight").count(), 3)
        self.assertEqual(Annotation.objects.filter(user=self.user, hidden_on_source=True).count(), 2)

    def test_resuming_practice_does_not_restore_hidden_highlights(self):
        original = self.add_highlight(timezone.now())
        self.post({"completed": "0", "action": "reset"})
        self.client.get(review_url({
            "part": "eo", "task": "tache-3", "kind": "spine",
            "response": self.response_id, "prompt": self.prompt.pk,
        }))
        mark_card_started(self.user, self.card())
        self.assertIsNone(self.card().subject_status_reset_at)
        result = self.client.get(
            reverse("study:annotations_for_source"), {"source_path": original.source_path},
        )
        self.assertEqual(result.json()["highlights"], [])
        original.refresh_from_db()
        self.assertTrue(original.hidden_on_source)


class Eo2SubjectStatusResetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("eo2-status-reset-learner")
        provision_user_study_data(cls.user)

    def setUp(self):
        self.client.force_login(self.user)
        self.prompt = Prompt.objects.select_related("response", "theme__task__part").get(
            content_key="tache2:avril:batch-01:subject-05",
        )
        self.url = reverse(
            "study:subject_completion", args=["eo", "tache-2", self.prompt.response_id],
        )

    def post(self, data):
        return self.client.post(self.url, data, HTTP_X_REQUESTED_WITH="fetch")

    def card(self):
        return Card.objects.get(
            user=self.user, card_type=CardType.SPINE, response_id=self.prompt.response_id,
        )

    def highlight(self, *, surface="detail", **overrides):
        dialogue = catalogue.tache_two_dialogues()[self.prompt.content_key]
        value = dialogue_response(dialogue)
        aliases = list(self.prompt.response.prompts.filter(is_active=True).select_related(
            "theme__task__part",
        ))
        rendered = _render_questions(self.prompt, value, surface, aliases, dialogue=dialogue)
        start, end = rendered.fields[(1, "question")]
        return Annotation.objects.create(**{
            "user": self.user, "task": self.prompt.theme.task, "kind": AnnotationKind.HIGHLIGHT,
            "source_path": prompt_detail_url(self.prompt) if surface == "detail" else review_url({
                "part": "eo", "task": "tache-2", "kind": "spine",
                "response": self.prompt.response_id, "prompt": self.prompt.pk,
            }),
            "source_key": variant_annotation_key(
                self.prompt, value, tache_two_dialogue=dialogue,
            ) + (":back" if surface == "back" else ""),
            "quote": rendered.slice(start, end), "start_offset": start, "end_offset": end,
            "prefix": rendered.slice(max(0, start - 160), start),
            "suffix": rendered.slice(end, end + 160),
            "body": "Keep my learned EO2 note.", "study_later": True,
            **overrides,
        })

    def test_reset_restores_to_do_without_erasing_srs_private_questions_or_notes(self):
        card = self.card()
        mark_card_started(self.user, card)
        self.post({"completed": "1"})
        values = asdict(dialogue_response(catalogue.tache_two_dialogues()[self.prompt.content_key]))
        values.pop("is_personal")
        values["arguments"] = list(values["arguments"])
        values["arguments"][0]["idea"] = "Ma propre question pour ce sujet ?"
        values["nuance"] = "My private EO2 prompt explanation."
        personal = PersonalResponse.objects.create(
            user=self.user, response=self.prompt.response, source_prompt=self.prompt, **values,
        )
        mark = self.highlight()
        saved_card = Card.objects.filter(pk=card.pk).values().get()
        saved_personal = PersonalResponse.objects.filter(pk=personal.pk).values().get()
        saved_mark = Annotation.objects.filter(pk=mark.pk).values().get()

        result = self.post({"completed": "0", "action": "reset"})

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["subject"], {"status": "new", "label": "À commencer"})
        self.assertFalse(result.json()["completed"])
        self.assertEqual(result.json()["hidden_highlight_ids"], [mark.pk])
        current_card = Card.objects.filter(pk=card.pk).values().get()
        allowed = {"subject_completed_at", "subject_started_at", "subject_status_reset_at"}
        self.assertEqual(
            {key: value for key, value in current_card.items() if key not in allowed},
            {key: value for key, value in saved_card.items() if key not in allowed},
        )
        self.assertIsNone(current_card["subject_completed_at"])
        self.assertIsNotNone(current_card["subject_status_reset_at"])
        self.assertEqual(PersonalResponse.objects.filter(pk=personal.pk).values().get(), saved_personal)
        self.assertEqual(
            Annotation.objects.filter(pk=mark.pk).values().get(),
            {**saved_mark, "hidden_on_source": True},
        )

    def test_reset_hides_both_surfaces_alias_and_legacy_marks_but_not_other_users(self):
        detail = self.highlight()
        back = self.highlight(surface="back")
        alias = self.highlight(source_key=self.prompt.content_key.replace("tache2:", "tache-two:", 1))
        legacy = self.highlight(source_key="")
        other_user = factories.make_user("another-eo2-reset-learner")
        other = self.highlight(user=other_user)
        note = self.highlight(kind=AnnotationKind.NOTE)
        result = self.post({"completed": "0", "action": "reset"})
        self.assertEqual(result.status_code, 200)
        self.assertCountEqual(
            result.json()["hidden_highlight_ids"], [detail.pk, back.pk, alias.pk, legacy.pk],
        )
        self.assertEqual(Annotation.objects.filter(user=self.user).count(), 5)
        for item in (other, note):
            item.refresh_from_db()
            self.assertFalse(item.hidden_on_source)
        self.assertEqual(
            self.post({"completed": "0", "action": "reset"}).json()["hidden_highlight_ids"], [],
        )

    def test_status_is_shared_by_equivalent_prompts_and_reactivates_on_new_practice(self):
        mark = self.highlight()
        self.post({"completed": "1"})
        self.post({"completed": "0", "action": "reset"})
        for prompt in self.prompt.response.prompts.filter(is_active=True):
            self.assertContains(self.client.get(prompt_detail_url(prompt)), "À commencer")
        mark_card_started(self.user, self.card())
        progress = subject_progress_by_response(
            self.user, {self.prompt.response_id},
        )[self.prompt.response_id]
        self.assertEqual(progress.status, "active")
        self.assertIsNone(self.card().subject_status_reset_at)
        mark.refresh_from_db()
        self.assertTrue(mark.hidden_on_source)

    def test_eo2_detail_exposes_the_reset_without_changing_question_text(self):
        page = self.client.get(prompt_detail_url(self.prompt))
        self.assertContains(page, 'data-subject-reset-form', count=1)
        self.assertContains(page, 'name="action" value="reset"', count=1)
        for question in catalogue.tache_two_dialogues()[self.prompt.content_key].questions:
            self.assertContains(page, escape(question.question))

    def test_invalid_completion_or_wrong_task_does_not_reset_state(self):
        self.post({"completed": "1"})
        self.assertEqual(self.post({"completed": "1", "action": "reset"}).status_code, 400)
        wrong = reverse(
            "study:subject_completion", args=["eo", "tache-3", self.prompt.response_id],
        )
        self.assertEqual(self.client.post(wrong, {"completed": "0", "action": "reset"}).status_code, 404)
        self.assertIsNotNone(self.card().subject_completed_at)
        self.assertIsNone(self.card().subject_status_reset_at)


class OwnerVerifiedSampleReleaseTests(TestCase):
    def release(self):
        from importlib import import_module
        from django.apps import apps
        import_module(
            "study.migrations.0063_release_owner_verified_sample"
        ).release_owner_verified_sample(apps, None)

    def make_attempt(self, status, fingerprint="a" * 64):
        from study.models import FrenchNarration
        return FrenchNarration.objects.create(
            fingerprint=fingerprint, text="x", voice_id="v", model_id="m",
            status=status, target_group="eo/tache-3/culture-p1",
        )

    def test_single_legacy_failed_sample_is_released_but_spend_stays_reserved(self):
        from study.models import FrenchNarration, FrenchNarrationBudget
        FrenchNarrationBudget.objects.create(pk=1, sample_claimed=True, reserved_characters=900)
        self.make_attempt("failed")
        self.release()
        budget = FrenchNarrationBudget.objects.get(pk=1)
        self.assertFalse(budget.sample_claimed)
        self.assertEqual(budget.reserved_characters, 900)
        self.assertFalse(FrenchNarration.objects.exists())

    def test_ambiguous_or_successful_states_stay_locked(self):
        from study.models import FrenchNarration, FrenchNarrationBudget
        for statuses in (["working"], ["ready"], ["failed", "failed"], []):
            with self.subTest(statuses=statuses):
                FrenchNarration.objects.all().delete()
                FrenchNarrationBudget.objects.update_or_create(pk=1, defaults={"sample_claimed": True})
                for index, status in enumerate(statuses):
                    self.make_attempt(status, fingerprint=str(index) * 64)
                self.release()
                self.assertTrue(FrenchNarrationBudget.objects.get(pk=1).sample_claimed)
