from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from study.content import (
    load_question_bank,
    load_question_banks,
    load_sections,
)
from study.management.commands.import_content import Command
from study.models import Task

from . import factories


class QuestionBankContentTests(TestCase):
    def test_master_bank_is_complete_and_consolidated(self):
        bank = load_question_bank()

        self.assertEqual(bank.number, 1)
        self.assertEqual(bank.title, "Mémoire 1")
        self.assertEqual(bank.label, "Questions réutilisables")
        self.assertEqual(bank.icon, "book-open")
        self.assertEqual(bank.category_count, 21)
        self.assertEqual(bank.question_count, 65)
        self.assertEqual(
            [section.number for section in bank.sections],
            list(range(1, 22)),
        )
        self.assertEqual(bank.sections[0].question_count, 7)
        self.assertEqual(bank.sections[3].question_count, 6)
        self.assertEqual(bank.sections[-1].title, "Rythme / journée type")

        questions = [
            question.text
            for section in bank.sections
            for group in section.groups
            for question in group.questions
        ]
        self.assertEqual(len(questions), len(set(questions)))
        self.assertIn(
            "Parlons du budget — combien est-ce que ça coûte "
            "approximativement au total ?",
            questions,
        )
        self.assertIn(
            "Pour finir — si tu ne devais me recommander qu'une seule "
            "chose, ce serait laquelle ?",
            questions,
        )
        self.assertEqual(load_question_banks(), (bank,))


class QuestionBankViewTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("question-bank")
        self.client.force_login(self.user)
        Command()._import_sections(load_sections())
        self.task = Task.objects.select_related("part").get(
            part__slug="eo",
            slug="tache-2",
        )

    def test_tache_two_opens_a_memory_overview(self):
        response = self.client.get(
            reverse(
                "study:task_detail",
                args=[self.task.part.slug, self.task.slug],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "study/tache_two_overview.html")
        self.assertTrue(self.task.available)
        self.assertEqual(response.context["memory_count"], 1)
        self.assertEqual(response.context["category_count"], 21)
        self.assertEqual(response.context["question_count"], 65)
        self.assertContains(response, 'id="memory-library-title">Mémoires</h2>')
        self.assertContains(response, "Mémoire 1")
        self.assertContains(response, "Questions réutilisables")
        self.assertContains(
            response,
            reverse(
                "study:task_memory_detail",
                args=[self.task.part.slug, self.task.slug, 1],
            ),
        )
        self.assertNotContains(response, "data-question-bank-question")
        self.assertNotContains(response, "Sujets &amp; réponses")
        self.assertNotContains(response, ">Pratiquer</a>")

    def test_memory_detail_opens_the_annotation_ready_master_bank(self):
        response = self.client.get(
            reverse(
                "study:task_memory_detail",
                args=[self.task.part.slug, self.task.slug, 1],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "study/question_bank.html")
        self.assertEqual(response.context["question_bank"].question_count, 65)
        self.assertContains(response, "Mémoire 1")
        self.assertContains(response, "Questions réutilisables")
        self.assertNotContains(
            response,
            "Deux formulations maximum par sujet.",
        )
        self.assertContains(response, "data-question-bank-section", count=21)
        self.assertContains(response, "data-question-bank-question", count=65)
        self.assertContains(
            response,
            'data-annotation-source-key="question-bank:part-01"',
        )
        self.assertContains(
            response,
            f'data-annotation-task-id="{self.task.pk}"',
        )
        self.assertNotContains(response, "Sujets &amp; réponses")
        self.assertNotContains(response, ">Pratiquer</a>")

    def test_unknown_or_unrelated_memory_is_not_found(self):
        missing = self.client.get(
            reverse(
                "study:task_memory_detail",
                args=[self.task.part.slug, self.task.slug, 2],
            )
        )
        unrelated = self.client.get(
            reverse(
                "study:task_memory_detail",
                args=[self.task.part.slug, "tache-3", 1],
            )
        )

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(unrelated.status_code, 404)

    def test_task_card_describes_the_guide_instead_of_empty_responses(self):
        task_url = reverse(
            "study:task_detail",
            args=[self.task.part.slug, self.task.slug],
        )

        response = self.client.get(
            reverse("study:part_detail", args=[self.task.part.slug])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, task_url)
        self.assertContains(response, "1 mémoire · 21 catégories · 65 questions")
        self.assertContains(response, "Questions réutilisables")
