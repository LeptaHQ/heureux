from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from study import content_loader as content
from study.models import Argument, Card, CardType, PersonalResponse
from study.routing import response_detail_url

from . import factories


class PersonalResponseTests(TestCase):
    def setUp(self):
        self.owner = factories.make_user("response-owner")
        self.other = factories.make_user("response-other")
        self.part = factories.make_part("eo")
        self.task = factories.make_task(self.part, "tache-3")
        self.theme = factories.make_theme("culture", task=self.task)
        self.response = factories.make_response(theme=self.theme)
        self.prompt = self.response.prompts.get()
        self.owner_card = Card.objects.create(
            user=self.owner,
            card_type=CardType.SPINE,
            response=self.response,
        )
        Card.objects.create(
            user=self.other,
            card_type=CardType.SPINE,
            response=self.response,
        )
        self.edit_url = reverse(
            "study:edit_response",
            args=[self.part.slug, self.task.slug, self.prompt.pk],
        )
        argument = self.response.arguments.get()
        self.payload = {
            "reformulation": "Ma reformulation personnelle.",
            "position": "Ma position personnelle.",
            "position_claire": "Je suis clairement favorable.",
            f"argument_{argument.order}_idea": "Mon idée précise.",
            f"argument_{argument.order}_developpement": (
                "Mon développement détaillé."
            ),
            f"argument_{argument.order}_exemple": "Mon exemple concret.",
            f"argument_{argument.order}_consequence": (
                "Ma conséquence logique."
            ),
            "nuance": "Ma nuance personnelle.",
            "conclusion": "Ma conclusion personnelle.",
            "prompt": "Tentative de modifier le sujet.",
            "action": "save",
        }
        self.client.force_login(self.owner)

    def test_editor_shows_prompt_as_read_only(self):
        page = self.client.get(self.edit_url)

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, self.response.prompt)
        self.assertContains(page, "Sujet non modifiable")
        self.assertNotContains(page, 'name="prompt"')

    def test_introduction_and_position_are_labeled_independently(self):
        editor = self.client.get(self.edit_url)

        self.assertEqual(editor.context["form"].fields["position"].label, "Position")
        self.assertEqual(
            editor.context["form"].fields["position_claire"].label,
            "Introduction",
        )

        self.client.post(self.edit_url, self.payload)
        detail = self.client.get(
            response_detail_url(self.response)
        )

        self.assertContains(
            detail,
            """
            <section class="card section-card">
              <div class="spine-label">Position</div>
              <p class="spine-text">Ma position personnelle.</p>
            </section>
            """,
            html=True,
        )
        self.assertContains(
            detail,
            """
            <section class="card section-card">
              <div class="spine-label">Introduction</div>
              <p class="spine-text">Je suis clairement favorable.</p>
            </section>
            """,
            html=True,
        )

    def test_personal_edit_keeps_shared_prompt_and_response_unchanged(self):
        original_prompt = self.response.prompt
        original_position = self.response.position

        result = self.client.post(self.edit_url, self.payload)

        self.assertRedirects(
            result,
            response_detail_url(self.response) + "?saved=1",
            fetch_redirect_response=False,
        )
        personal = PersonalResponse.objects.get(
            user=self.owner,
            response=self.response,
        )
        self.assertEqual(personal.position, "Ma position personnelle.")
        self.response.refresh_from_db()
        self.owner_card.refresh_from_db()
        other_card = Card.objects.get(
            user=self.other,
            card_type=CardType.SPINE,
            response=self.response,
        )
        self.assertEqual(self.response.prompt, original_prompt)
        self.assertEqual(self.response.position, original_position)
        self.assertIsNone(self.owner_card.started_at)
        self.assertIsNone(other_card.started_at)

    def test_personal_version_is_private_and_used_in_learning_and_review(self):
        self.client.post(self.edit_url, self.payload)

        detail = self.client.get(
            response_detail_url(self.response)
        )
        review = self.client.get(
            reverse("study:review_next") + "?kind=spine"
        ).json()

        self.assertContains(detail, "Ma position personnelle.")
        self.assertContains(detail, "Mon développement détaillé.")
        self.assertContains(detail, "Version personnelle")
        self.assertIn("Mon idée précise.", review["back_html"])
        self.assertNotIn("Mon développement détaillé.", review["back_html"])

        self.client.force_login(self.other)
        other_detail = self.client.get(
            response_detail_url(self.response)
        )
        other_review = self.client.get(
            reverse("study:review_next") + "?kind=spine"
        ).json()
        self.assertNotContains(other_detail, "Ma position personnelle.")
        self.assertNotIn("Mon idée précise.", other_review["back_html"])

    def test_reset_restores_shared_version_without_touching_progress(self):
        self.client.post(self.edit_url, self.payload)
        self.owner_card.reps = 6
        self.owner_card.save(update_fields=["reps"])

        result = self.client.post(self.edit_url, {"action": "reset"})

        self.assertRedirects(
            result,
            response_detail_url(self.response) + "?reset=1",
            fetch_redirect_response=False,
        )
        self.assertFalse(
            PersonalResponse.objects.filter(
                user=self.owner,
                response=self.response,
            ).exists()
        )
        self.owner_card.refresh_from_db()
        self.assertEqual(self.owner_card.reps, 6)
        self.assertIsNone(self.owner_card.started_at)

    def test_editor_is_limited_to_expression_orale_tache_3(self):
        written_part = factories.make_part("ee")
        written_task = factories.make_task(written_part, "tache-3")
        written_theme = factories.make_theme(
            "written-theme",
            task=written_task,
        )
        written_response = factories.make_response(theme=written_theme)
        written_prompt = written_response.prompts.get()

        response = self.client.get(
            reverse(
                "study:edit_response",
                args=[
                    written_part.slug,
                    written_task.slug,
                    written_prompt.pk,
                ],
            )
        )

        self.assertEqual(response.status_code, 404)


class TacheTwoPersonalResponseTests(TestCase):
    def setUp(self):
        self.owner = factories.make_user("tache-two-owner")
        self.other = factories.make_user("tache-two-other")
        self.part = factories.make_part("eo")
        self.task = factories.make_task(self.part, "tache-2")
        self.theme = factories.make_theme(
            "tache-two-personal",
            task=self.task,
        )
        month = content.load_tache_two_subject_months()[0]
        batch = month.batches[0]
        self.subject = batch.subjects[0]
        self.detail_url = reverse(
            "study:task_subject_detail",
            args=[
                self.part.slug,
                self.task.slug,
                month.slug,
                batch.number,
                self.subject.number,
            ],
        )
        content_key = content.tache_two_subject_content_key(
            month.slug,
            batch.number,
            self.subject.number,
        )
        self.response = factories.make_response(theme=self.theme)
        self.response.content_key = content_key
        self.response.prompt = self.subject.prompt
        self.response.save(update_fields=["content_key", "prompt"])
        self.prompt = self.response.prompts.get()
        self.prompt.content_key = content_key
        self.prompt.text = self.subject.prompt
        self.prompt.save(update_fields=["content_key", "text"])
        self.response.arguments.all().delete()
        self.original_questions = [
            question.text for question in self.subject.questions[:2]
        ]
        Argument.objects.bulk_create(
            [
                Argument(
                    response=self.response,
                    order=index,
                    idea=question,
                )
                for index, question in enumerate(
                    self.original_questions,
                    start=1,
                )
            ]
        )
        Card.objects.create(
            user=self.owner,
            card_type=CardType.SPINE,
            response=self.response,
        )
        Card.objects.create(
            user=self.other,
            card_type=CardType.SPINE,
            response=self.response,
        )
        self.edit_url = reverse(
            "study:edit_response",
            args=[self.part.slug, self.task.slug, self.prompt.pk],
        )
        self.client.force_login(self.owner)

    def _payload(self):
        return {
            "questions-TOTAL_FORMS": "3",
            "questions-INITIAL_FORMS": "2",
            "questions-MIN_NUM_FORMS": "1",
            "questions-MAX_NUM_FORMS": "30",
            "questions-0-question": "Quel est votre budget personnel ?",
            "questions-0-response": "Je peux consacrer environ 500 euros.",
            "questions-1-question": self.original_questions[1],
            "questions-1-response": "",
            "questions-1-DELETE": "on",
            "questions-2-question": "Quand pouvons-nous nous rencontrer ?",
            "questions-2-response": "Samedi matin me conviendrait.",
            "action": "save",
        }

    def test_editor_supports_dynamic_question_and_response_rows(self):
        editor = self.client.get(self.edit_url)

        self.assertEqual(editor.status_code, 200)
        self.assertTrue(editor.context["is_tache_two"])
        self.assertEqual(
            editor.context["question_formset"].total_form_count(),
            2,
        )
        self.assertContains(editor, "Ajouter une question")
        self.assertContains(editor, 'name="questions-0-question"')
        self.assertContains(editor, 'data-question-template')
        self.assertContains(editor, "Je suis votre ami(e).")
        self.assertNotContains(editor, 'name="prompt"')

    def test_personal_questions_are_private_and_used_on_cards(self):
        result = self.client.post(self.edit_url, self._payload())

        self.assertRedirects(
            result,
            self.detail_url + "?saved=1",
            fetch_redirect_response=False,
        )
        personal = PersonalResponse.objects.get(
            user=self.owner,
            response=self.response,
        )
        self.assertEqual(
            [argument["order"] for argument in personal.arguments],
            [1, 2],
        )
        self.assertEqual(
            personal.arguments[0]["idea"],
            "Quel est votre budget personnel ?",
        )
        self.assertEqual(
            personal.arguments[1]["idea"],
            "Quand pouvons-nous nous rencontrer ?",
        )

        owner_detail = self.client.get(self.detail_url)
        owner_review = self.client.get(
            reverse("study:review_next")
            + f"?kind=spine&response={self.response.pk}"
        ).json()
        self.assertContains(owner_detail, "Version personnelle")
        self.assertContains(owner_detail, "Quel est votre budget personnel ?")
        self.assertContains(owner_detail, "Samedi matin me conviendrait.")
        self.assertEqual(
            [
                question["text"]
                for question in owner_detail.context["subject_questions"]
            ],
            [
                "Quel est votre budget personnel ?",
                "Quand pouvons-nous nous rencontrer ?",
            ],
        )
        self.assertIn("Quand pouvons-nous nous rencontrer ?", owner_review["back_html"])
        self.assertIn("Samedi matin me conviendrait.", owner_review["back_html"])

        self.response.refresh_from_db()
        self.assertEqual(
            list(
                self.response.arguments.order_by("order").values_list(
                    "idea",
                    flat=True,
                )
            ),
            self.original_questions,
        )

        self.client.force_login(self.other)
        other_detail = self.client.get(self.detail_url)
        self.assertEqual(
            [
                question["text"]
                for question in other_detail.context["subject_questions"]
            ],
            self.original_questions,
        )
        self.assertNotContains(other_detail, "Quel est votre budget personnel ?")

    def test_reset_restores_the_original_questions(self):
        self.client.post(self.edit_url, self._payload())

        result = self.client.post(self.edit_url, {"action": "reset"})

        self.assertRedirects(
            result,
            self.detail_url + "?reset=1",
            fetch_redirect_response=False,
        )
        self.assertFalse(
            PersonalResponse.objects.filter(
                user=self.owner,
                response=self.response,
            ).exists()
        )
        detail = self.client.get(self.detail_url)
        self.assertEqual(
            [
                question["text"]
                for question in detail.context["subject_questions"]
            ],
            self.original_questions,
        )
        self.assertNotContains(detail, "Quel est votre budget personnel ?")
