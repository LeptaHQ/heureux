from __future__ import annotations

import re

from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from study import content_loader as content
from study.models import Argument, Card, CardType, PersonalResponse
from study.routing import response_detail_url

from . import factories


def _root_texts(html, root_pattern):
    """Return a root's annotation text and its full textContent."""
    from .test_ee_tache_three_memory_translations import AnnotationRootText

    class RootTextContent(AnnotationRootText):
        def handle_data(self, data):
            for _, key, _ in self.stack:
                if key:
                    self.roots[key] += data

    key = re.search(
        root_pattern + r'[^>]*data-annotation-source-key="([^"]+)"',
        html,
    ).group(1)
    texts = []
    for parser in (AnnotationRootText(), RootTextContent()):
        parser.feed(html)
        texts.append(parser.roots[key])
    return tuple(texts)


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

        position_card = re.search(
            r'<section class="card section-card">\s*<div class="section-card__head">'
            r'<div class="spine-label">Position</div>.*?</section>',
            detail.content.decode(),
            re.S,
        )
        self.assertIsNotNone(position_card)
        self.assertIn(
            '<p class="spine-text">Ma position personnelle.</p>',
            position_card.group(),
        )
        self.assertContains(
            detail,
            """
            <section class="card section-card">
              <div class="section-card__head"><div class="spine-label">Introduction</div></div>
              <p class="spine-text">Je suis clairement favorable.</p>
            </section>
            """,
            html=True,
        )

    def test_detail_pencil_opens_the_editor_from_the_first_card(self):
        detail_url = response_detail_url(self.response)
        pencil = 'href="{}" data-response-edit aria-label="{}"'

        shared = self.client.get(detail_url).content.decode()

        self.assertEqual(shared.count("data-response-edit"), 1)
        self.assertIn(
            'Arguments développés</div><span class="section-card__tools" data-annotation-exclude>',
            shared,
        )
        self.assertIn(pencil.format(self.edit_url, "Personnaliser la réponse"), shared)

        self.client.post(self.edit_url, self.payload)
        personal = self.client.get(detail_url).content.decode()

        self.assertEqual(personal.count("data-response-edit"), 1)
        self.assertIn(
            'Position</div><span class="section-card__tools" data-annotation-exclude>',
            personal,
        )
        self.assertIn(pencil.format(self.edit_url, "Modifier ma version"), personal)

    def test_detail_pencil_leaves_annotation_text_unchanged(self):
        detail_url = response_detail_url(self.response)
        for personalized in (False, True):
            with self.subTest(personalized=personalized):
                if personalized:
                    self.client.post(self.edit_url, self.payload)
                page = self.client.get(detail_url)
                without_pencil = render_to_string(
                    "study/response_detail.html",
                    {**page.context[0].flatten(), "can_edit_response": False},
                    request=page.wsgi_request,
                )
                texts = [
                    _root_texts(html, r'<div class="answer-columns" data-annotation-root')
                    for html in (page.content.decode(), without_pencil)
                ]

                self.assertIn("data-response-edit", page.content.decode())
                self.assertNotIn("data-response-edit", without_pencil)
                self.assertIn("Arguments développés", texts[0][0])
                self.assertNotIn("Personnaliser la réponse", texts[0][1])
                self.assertNotIn("Modifier ma version", texts[0][1])
                self.assertEqual(texts[0], texts[1])

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
                is_active=True,
            ).exists()
        )
        self.owner_card.refresh_from_db()
        self.assertEqual(self.owner_card.reps, 6)
        self.assertIsNone(self.owner_card.started_at)

    def test_editor_rejects_other_writing_tasks(self):
        written_part = factories.make_part("ee")
        written_task = factories.make_task(written_part, "tache-2")
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

    def test_questions_header_pencil_opens_the_editor(self):
        pencil = (
            'class="icon-button" href="{}" data-annotation-exclude '
            'data-response-edit aria-label="{}"'
        )

        shared = self.client.get(self.detail_url)

        self.assertContains(
            shared,
            pencil.format(self.edit_url, "Personnaliser les questions"),
            count=1,
        )

        self.client.post(self.edit_url, self._payload())
        personal = self.client.get(self.detail_url)

        self.assertContains(
            personal,
            pencil.format(self.edit_url, "Modifier mes questions"),
            count=1,
        )
        for page in (shared, personal):
            context = page.context[0].flatten()
            texts = [
                _root_texts(
                    render_to_string(
                        "study/partials/tache_two_questions.html",
                        {**context, "questions_edit_url": questions_edit_url},
                        request=page.wsgi_request,
                    ),
                    r'<section\s+class="tache-two-question-section"',
                )
                for questions_edit_url in (self.edit_url, "")
            ]
            self.assertEqual(texts[0], texts[1])

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
        self.assertNotContains(owner_detail, "Samedi matin me conviendrait.")
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
        self.assertNotIn("Samedi matin me conviendrait.", owner_review["back_html"])
        self.assertEqual(personal.arguments[1]["developpement"], "Samedi matin me conviendrait.")

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
                is_active=True,
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
