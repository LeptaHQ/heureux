from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from study.accounts import provision_user_study_data
from study.content import (
    load_question_bank,
    load_question_banks,
    load_comprehension_tests,
    load_tache_two_subject_months,
    parse_comprehension_vocabulary,
    parse_tache_two_responses,
    parse_tache_two_subject_vocabulary,
)
from study.models import (
    Annotation,
    AnnotationKind,
    Card,
    CardType,
    MemoryQuestionProgress,
    Phrase,
    PhraseTier,
    Response,
    Task,
)
from study.routing import response_detail_url

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
        self.assertEqual(len(bank.question_keys), 65)
        self.assertEqual(len(set(bank.question_keys)), 65)
        self.assertTrue(
            all(
                key.startswith("memory:1:question:")
                for key in bank.question_keys
            )
        )
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

    def test_january_batches_are_question_only_and_memory_driven(self):
        months = load_tache_two_subject_months()

        self.assertEqual(len(months), 1)
        january = months[0]
        self.assertEqual(january.name, "Janvier")
        self.assertEqual(january.batch_count, 2)
        self.assertEqual(january.subject_count, 10)
        self.assertEqual(january.question_count, 144)
        first_batch, second_batch = january.batches
        self.assertEqual(first_batch.number, 1)
        self.assertEqual(
            [subject.number for subject in first_batch.subjects],
            [1, 2, 3, 4, 5],
        )
        self.assertEqual(
            [subject.question_count for subject in first_batch.subjects],
            [14, 12, 14, 15, 15],
        )
        self.assertEqual(
            sum(
                subject.memory_question_count
                for subject in first_batch.subjects
            ),
            67,
        )
        self.assertEqual(second_batch.number, 2)
        self.assertEqual(
            [subject.number for subject in second_batch.subjects],
            [6, 7, 8, 9, 10],
        )
        self.assertEqual(
            [subject.question_count for subject in second_batch.subjects],
            [14, 16, 15, 14, 15],
        )
        self.assertEqual(
            sum(
                subject.memory_question_count
                for subject in second_batch.subjects
            ),
            71,
        )
        self.assertTrue(
            all(
                question.text.endswith("?")
                for batch in january.batches
                for subject in batch.subjects
                for question in subject.questions
            )
        )
        corpus = " ".join(
            (
                subject.prompt
                + " "
                + " ".join(
                    question.text for question in subject.questions
                )
            )
            for batch in january.batches
            for subject in batch.subjects
        )
        self.assertNotIn("Dog sitting", corpus)
        self.assertNotIn("I live in your neighborhood", corpus)
        self.assertNotIn("**»**", corpus)
        self.assertNotIn("Vous partez en vacances où", corpus)
        self.assertNotIn("Quelle est la durée d'une séance.", corpus)
        self.assertNotIn("C'est facilement se déplacer", corpus)
        self.assertIn(
            "Pour finir — si tu ne devais me recommander "
            "qu'une seule chose",
            corpus,
        )

    def test_january_subjects_generate_srs_responses_and_vocabulary(self):
        responses = parse_tache_two_responses()
        vocabulary = parse_tache_two_subject_vocabulary(responses)

        self.assertEqual(len(responses), 10)
        self.assertEqual(
            sum(len(response.arguments) for response in responses),
            144,
        )
        self.assertEqual(len(vocabulary), 300)
        self.assertEqual(
            {phrase.tier for phrase in vocabulary},
            {PhraseTier.SUBJECT},
        )
        self.assertEqual(
            {
                source
                for phrase in vocabulary
                for source in phrase.sources
            },
            {
                (prompt.theme, prompt.number)
                for response in responses
                for prompt in response.prompts
            },
        )
        questions_by_source = {
            (prompt.theme, prompt.number): {
                argument.idea for argument in response.arguments
            }
            for response in responses
            for prompt in response.prompts
        }
        for phrase in vocabulary:
            self.assertEqual(len(phrase.sources), 1)
            self.assertIn(
                phrase.example,
                questions_by_source[phrase.sources[0]],
            )
            self.assertEqual(
                phrase.example.casefold().count(
                    phrase.expression.casefold()
                ),
                1,
            )
        for source in questions_by_source:
            source_phrases = [
                phrase
                for phrase in vocabulary
                if phrase.sources == (source,)
            ]
            category_counts = {}
            for phrase in source_phrases:
                category_counts[phrase.category] = (
                    category_counts.get(phrase.category, 0) + 1
                )
            self.assertEqual(len(source_phrases), 30)
            self.assertEqual(
                category_counts,
                {
                    "Mots clés du sujet": 10,
                    "Collocations du sujet": 10,
                    "Tournures pour l'oral": 10,
                },
            )
        comprehension_orders = {
            item.phrase.order
            for item in parse_comprehension_vocabulary(
                load_comprehension_tests()
            )
        }
        self.assertTrue(
            comprehension_orders.isdisjoint(
                phrase.order for phrase in vocabulary
            )
        )


class QuestionBankViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("question-bank")
        provision_user_study_data(cls.user)
        cls.task = Task.objects.select_related("part").get(
            part__slug="eo",
            slug="tache-2",
        )

    def setUp(self):
        self.client.force_login(self.user)

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
        self.assertEqual(response.context["subject_count"], 10)
        self.assertEqual(response.context["category_count"], 21)
        self.assertEqual(response.context["question_count"], 65)
        self.assertContains(response, 'id="subject-library-title">Sujets</h2>')
        self.assertContains(response, "Janvier · Batch 1")
        self.assertContains(response, "Janvier · Batch 2")
        self.assertLess(
            response.content.index(b'id="memory-library-title"'),
            response.content.index(b'id="subject-library-title"'),
        )
        self.assertContains(
            response,
            reverse(
                "study:task_subject_batch",
                args=[self.task.part.slug, self.task.slug, "janvier", 1],
            ),
        )
        self.assertContains(response, 'id="memory-library-title">Mémoires</h2>')
        self.assertContains(response, "Mémoire 1")
        self.assertNotContains(response, "Questions réutilisables")
        self.assertNotContains(response, "memory-entry__label")
        self.assertContains(response, 'data-collection-view-toggle')
        self.assertContains(response, 'data-collection-view="adaptive"')
        self.assertContains(response, 'collection-table-header--memories')
        self.assertContains(response, 'data-collection-item')
        self.assertContains(
            response,
            reverse(
                "study:task_memory_detail",
                args=[self.task.part.slug, self.task.slug, 1],
            ),
        )
        self.assertNotContains(response, "data-question-bank-question")
        self.assertNotContains(response, "Sujets &amp; réponses")
        self.assertNotContains(response, "Réflexe Mémoire")
        self.assertNotContains(response, ">Pratiquer</a>")

    def test_subjects_are_grouped_by_month_and_batch(self):
        index_url = reverse(
            "study:task_browse",
            args=[self.task.part.slug, self.task.slug],
        )
        batch_url = reverse(
            "study:task_subject_batch",
            args=[self.task.part.slug, self.task.slug, "janvier", 1],
        )
        second_batch_url = reverse(
            "study:task_subject_batch",
            args=[self.task.part.slug, self.task.slug, "janvier", 2],
        )
        subject_url = reverse(
            "study:task_subject_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                "janvier",
                1,
                1,
            ],
        )
        second_batch_subject_url = reverse(
            "study:task_subject_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                "janvier",
                2,
                6,
            ],
        )

        index = self.client.get(index_url)
        self.assertEqual(index.status_code, 200)
        self.assertTemplateUsed(index, "study/tache_two_subjects.html")
        self.assertEqual(index.context["month_count"], 1)
        self.assertEqual(index.context["batch_count"], 2)
        self.assertEqual(index.context["subject_count"], 10)
        self.assertEqual(index.context["question_count"], 144)
        self.assertNotContains(index, "Réflexe Mémoire")
        self.assertContains(index, "Janvier")
        self.assertContains(index, "Batch 01")
        self.assertContains(index, "Batch 02")
        self.assertContains(index, "data-tache-two-subject-batch", count=2)
        self.assertContains(index, batch_url)
        self.assertContains(index, second_batch_url)

        batch = self.client.get(batch_url)
        self.assertEqual(batch.status_code, 200)
        self.assertTemplateUsed(
            batch,
            "study/tache_two_subject_batch.html",
        )
        self.assertContains(batch, "Janvier · Batch 1")
        self.assertContains(batch, "data-tache-two-subject", count=5)
        self.assertContains(batch, subject_url)

        subject = self.client.get(subject_url)
        self.assertEqual(subject.status_code, 200)
        self.assertTemplateUsed(
            subject,
            "study/tache_two_subject_detail.html",
        )
        self.assertContains(
            subject,
            "Achat d&#x27;objets avant un déménagement",
        )
        self.assertContains(subject, "data-tache-two-question", count=14)
        self.assertNotContains(subject, "tache-two-question__memory")
        self.assertNotContains(subject, "Réflexe Mémoire")
        self.assertContains(subject, "Progression du sujet")
        self.assertContains(subject, "Pratiquer ce sujet")
        self.assertContains(subject, "Pratiquer les vocabs")
        self.assertContains(subject, "30 vocabs")
        self.assertEqual(len(subject.context["vocabulary_batches"]), 3)
        self.assertTrue(
            all(
                batch["phrase_count"] == 10
                for batch in subject.context["vocabulary_batches"]
            )
        )
        self.assertEqual(len(subject.context["subject_vocabulary"]), 10)
        self.assertEqual(
            response_detail_url(subject.context["response"]),
            subject_url,
        )
        generic_url = reverse(
            "study:response_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                subject.context["selected_prompt"].pk,
            ],
        )
        self.assertRedirects(
            self.client.get(generic_url),
            subject_url,
            fetch_redirect_response=False,
        )
        self.assertContains(
            subject,
            "Merci pour toutes ces infos",
        )
        self.assertContains(
            subject,
            "data-annotation-source-key="
            '"tache-two:janvier:batch-1:subject-1"',
        )

        second_batch = self.client.get(second_batch_url)
        self.assertEqual(second_batch.status_code, 200)
        self.assertContains(second_batch, "Janvier · Batch 2")
        self.assertContains(
            second_batch,
            "data-tache-two-subject",
            count=5,
        )
        self.assertContains(second_batch, second_batch_subject_url)

        second_batch_subject = self.client.get(second_batch_subject_url)
        self.assertEqual(second_batch_subject.status_code, 200)
        self.assertContains(
            second_batch_subject,
            "Séances de yoga pour les employés",
        )
        self.assertContains(
            second_batch_subject,
            "data-tache-two-question",
            count=14,
        )
        self.assertContains(second_batch_subject, "30 vocabs")
        self.assertEqual(
            len(second_batch_subject.context["vocabulary_batches"]),
            3,
        )

    def test_import_provisions_real_subject_and_vocabulary_cards(self):
        responses = Response.objects.filter(
            content_key__startswith="tache2:",
            is_active=True,
        )
        response_ids = set(responses.values_list("pk", flat=True))
        vocabulary = Phrase.objects.filter(
            tier=PhraseTier.SUBJECT,
            source_prompts__response_id__in=response_ids,
            is_active=True,
        ).distinct()

        self.assertEqual(responses.count(), 10)
        self.assertEqual(vocabulary.count(), 300)
        self.assertEqual(
            Card.objects.filter(
                user=self.user,
                card_type=CardType.SPINE,
                response_id__in=response_ids,
            ).count(),
            10,
        )
        self.assertEqual(
            Card.objects.filter(
                user=self.user,
                card_type=CardType.PHRASE_PRODUCTION,
                phrase__in=vocabulary,
            ).count(),
            300,
        )

        directory = self.client.get(
            reverse(
                "study:task_phrases",
                args=[self.task.part.slug, self.task.slug],
            )
        )
        self.assertEqual(directory.status_code, 200)
        self.assertContains(directory, "Vocabulaire par sujet")
        self.assertContains(
            directory,
            "data-subject-vocabulary-row",
            count=10,
        )

    def test_existing_subject_highlight_marks_imported_response_in_progress(self):
        subject_url = reverse(
            "study:task_subject_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                "janvier",
                1,
                1,
            ],
        )
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            source_path=subject_url,
            source_key="tache-two:janvier:batch-1:subject-1",
            quote="Quels types d'objets",
            start_offset=0,
            end_offset=20,
        )

        subject = self.client.get(subject_url)

        self.assertEqual(subject.status_code, 200)
        self.assertTrue(subject.context["subject_progress"].has_highlight)
        self.assertEqual(subject.context["subject_progress"].status, "active")

    def test_unknown_subject_month_batch_and_number_are_not_found(self):
        route_args = [self.task.part.slug, self.task.slug]
        missing_month = self.client.get(
            reverse(
                "study:task_subject_batch",
                args=[*route_args, "fevrier", 1],
            )
        )
        missing_batch = self.client.get(
            reverse(
                "study:task_subject_batch",
                args=[*route_args, "janvier", 2],
            )
        )
        missing_subject = self.client.get(
            reverse(
                "study:task_subject_detail",
                args=[*route_args, "janvier", 1, 6],
            )
        )

        self.assertEqual(missing_month.status_code, 404)
        self.assertEqual(missing_batch.status_code, 404)
        self.assertEqual(missing_subject.status_code, 404)

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
        self.assertNotContains(response, "Questions réutilisables")
        self.assertNotContains(response, "La règle d'or")
        self.assertNotContains(response, "question-bank-rules")
        self.assertNotContains(
            response,
            "Deux formulations maximum par sujet.",
        )
        self.assertContains(response, "data-question-bank-section", count=21)
        self.assertContains(response, "data-question-bank-question", count=65)
        self.assertContains(response, "data-memory-progress-form", count=65)
        self.assertContains(
            response,
            "<span data-memory-completed>0</span> sur 65 questions apprises",
            html=True,
        )
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
        self.assertContains(
            response,
            "5 sujets · 1 mémoire · 21 catégories · 65 questions",
        )
        self.assertContains(response, "0/65 apprises")
        self.assertContains(response, "À commencer")

    def test_question_progress_can_be_checked_and_unchecked(self):
        bank = load_question_bank()
        question_key = bank.question_keys[0]
        url = reverse(
            "study:task_memory_progress",
            args=[self.task.part.slug, self.task.slug, bank.number],
        )

        checked = self.client.post(
            url,
            {"question_key": question_key, "completed": "1"},
            HTTP_X_REQUESTED_WITH="fetch",
        )

        self.assertEqual(checked.status_code, 200)
        self.assertEqual(
            checked.json()["memory"],
            {
                "completed": 1,
                "total": 65,
                "percent": 2,
                "status": "active",
                "label": "En cours",
            },
        )
        self.assertEqual(checked.json()["section"]["completed"], 1)
        self.assertTrue(
            MemoryQuestionProgress.objects.filter(
                user=self.user,
                memory_number=bank.number,
                question_key=question_key,
            ).exists()
        )
        task_list = self.client.get(
            reverse("study:part_detail", args=[self.task.part.slug])
        )
        self.assertContains(task_list, "1/65 apprises")
        self.assertContains(task_list, "En cours")

        unchecked = self.client.post(
            url,
            {"question_key": question_key, "completed": "0"},
            HTTP_X_REQUESTED_WITH="fetch",
        )

        self.assertEqual(unchecked.status_code, 200)
        self.assertFalse(unchecked.json()["completed"])
        self.assertEqual(unchecked.json()["memory"]["completed"], 0)
        self.assertFalse(
            MemoryQuestionProgress.objects.filter(
                user=self.user,
                question_key=question_key,
            ).exists()
        )

    def test_question_progress_has_a_native_form_fallback(self):
        bank = load_question_bank()
        response = self.client.post(
            reverse(
                "study:task_memory_progress",
                args=[self.task.part.slug, self.task.slug, bank.number],
            ),
            {
                "question_key": bank.question_keys[0],
                "completed": "1",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "study:task_memory_detail",
                args=[self.task.part.slug, self.task.slug, bank.number],
            )
            + f"#{bank.sections[0].anchor}",
            fetch_redirect_response=False,
        )

    def test_question_progress_is_idempotent_and_private(self):
        bank = load_question_bank()
        question_key = bank.question_keys[0]
        url = reverse(
            "study:task_memory_progress",
            args=[self.task.part.slug, self.task.slug, bank.number],
        )
        other_user = factories.make_user("other-memory-learner")

        for _ in range(2):
            response = self.client.post(
                url,
                {"question_key": question_key, "completed": "1"},
                HTTP_X_REQUESTED_WITH="fetch",
            )
            self.assertEqual(response.status_code, 200)

        self.assertEqual(
            MemoryQuestionProgress.objects.filter(
                memory_number=bank.number,
                question_key=question_key,
            ).count(),
            1,
        )
        self.client.force_login(other_user)
        detail = self.client.get(
            reverse(
                "study:task_memory_detail",
                args=[self.task.part.slug, self.task.slug, bank.number],
            )
        )
        self.assertEqual(detail.context["memory_progress"].completed, 0)
        self.assertContains(detail, 'aria-checked="false"', count=65)

    def test_unknown_question_progress_is_rejected(self):
        response = self.client.post(
            reverse(
                "study:task_memory_progress",
                args=[self.task.part.slug, self.task.slug, 1],
            ),
            {"question_key": "memory:1:question:unknown", "completed": "1"},
            HTTP_X_REQUESTED_WITH="fetch",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Cette question ne fait pas partie de la mémoire.",
        )
        self.assertFalse(MemoryQuestionProgress.objects.exists())

    def test_progress_rolls_up_to_memory_and_task_cards(self):
        bank = load_question_bank()
        MemoryQuestionProgress.objects.bulk_create(
            [
                MemoryQuestionProgress(
                    user=self.user,
                    memory_number=bank.number,
                    question_key=key,
                )
                for key in bank.question_keys
            ]
        )

        detail = self.client.get(
            reverse(
                "study:task_memory_detail",
                args=[self.task.part.slug, self.task.slug, bank.number],
            )
        )
        overview = self.client.get(
            reverse(
                "study:task_detail",
                args=[self.task.part.slug, self.task.slug],
            )
        )
        task_list = self.client.get(
            reverse("study:part_detail", args=[self.task.part.slug])
        )

        self.assertEqual(detail.context["memory_progress"].status, "done")
        self.assertContains(detail, 'aria-checked="true"', count=65)
        self.assertContains(
            detail,
            "<span data-memory-completed>65</span> sur 65 questions apprises",
            html=True,
        )
        self.assertEqual(
            overview.context["memories"][0]["progress"].status,
            "done",
        )
        self.assertContains(overview, "65/65 apprises")
        self.assertContains(task_list, "65/65 apprises")
        self.assertContains(task_list, "Terminé")

    def test_account_export_and_reset_include_memory_progress(self):
        bank = load_question_bank()
        own_progress = MemoryQuestionProgress.objects.create(
            user=self.user,
            memory_number=bank.number,
            question_key=bank.question_keys[0],
        )
        other_user = factories.make_user("retained-memory-learner")
        other_progress = MemoryQuestionProgress.objects.create(
            user=other_user,
            memory_number=bank.number,
            question_key=bank.question_keys[1],
        )

        exported = self.client.get(reverse("study:export_account")).json()

        self.assertEqual(exported["version"], 3)
        self.assertEqual(
            exported["memory_question_progress"][0]["question_key"],
            own_progress.question_key,
        )
        self.assertEqual(len(exported["memory_question_progress"]), 1)

        response = self.client.post(
            reverse("study:reset_progress"),
            {
                "current_pin": "123456",
                "confirmation": "REINITIALISER",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            MemoryQuestionProgress.objects.filter(pk=own_progress.pk).exists()
        )
        self.assertTrue(
            MemoryQuestionProgress.objects.filter(pk=other_progress.pk).exists()
        )
