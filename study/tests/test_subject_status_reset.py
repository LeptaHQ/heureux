from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from study.account_services import provision_user_study_data
from study.models import Annotation, AnnotationKind, Card, CardType, Prompt
from study.oral_highlights import AnnotationRootText
from study.progress import mark_card_started, subject_progress_by_response
from study.routing import prompt_detail_url

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
