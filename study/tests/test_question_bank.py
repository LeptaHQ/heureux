from __future__ import annotations

import copy
import json
import tempfile
from datetime import timedelta
from importlib import import_module
from io import StringIO
from pathlib import Path

from django.apps import apps
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from study.account_services import provision_user_study_data
from study.content_loader import (
    AI_EXAMINER_PROMPT_PATH,
    TACHE_TWO_SUBJECT_THEMES_PATH,
    TACHE_TWO_THEME_VOCABULARY_CATEGORIES,
    TACHE_TWO_THEME_VOCABULARY_DIR,
    TACHE_TWO_THEME_VOCABULARY_PER_KIND,
    TACHE_TWO_THEME_VOCABULARY_PER_THEME,
    TACHE_TWO_VOCABULARY_DIR,
    load_ai_examiner_prompt,
    load_question_bank,
    load_question_banks,
    load_comprehension_tests,
    load_tache_two_subject_months,
    parse_comprehension_vocabulary,
    parse_tache_two_responses,
    parse_tache_two_subject_vocabulary,
    parse_tache_two_theme_vocabulary,
    tache_two_response_key_by_subject_key,
    tache_two_subject_content_key,
)
from study.models import (
    Annotation,
    AnnotationKind,
    Card,
    CardState,
    CardType,
    MemoryQuestionProgress,
    Phrase,
    PhraseTier,
    Prompt,
    Response,
    Task,
    ThemeVocabularyProgress,
)
from study.routing import response_detail_url

annotation_migration = import_module(
    "study.migrations.0040_shared_tache_two_annotation_keys"
)

from . import factories


FINAL_EXACT_RESPONSE_REUSE = (
    ("octobre", 1, "janvier", 3, 11),
    ("octobre", 2, "janvier", 3, 12),
    ("octobre", 3, "janvier", 3, 13),
    ("octobre", 4, "janvier", 3, 14),
    ("octobre", 5, "mai", 4, 15),
    ("octobre", 6, "mars", 3, 11),
    ("octobre", 7, "mars", 3, 12),
    ("octobre", 8, "mars", 3, 13),
    ("octobre", 9, "mars", 3, 14),
    ("octobre", 10, "fevrier", 5, 25),
    ("octobre", 11, "juillet", 1, 1),
    ("octobre", 15, "juin", 1, 4),
    ("octobre", 21, "mai", 2, 8),
    ("octobre", 23, "juillet", 6, 26),
    ("octobre", 31, "aout", 2, 6),
    ("octobre", 32, "mai", 2, 7),
    ("octobre", 33, "mai", 2, 10),
    ("octobre", 34, "mai", 2, 9),
    ("octobre", 35, "aout", 2, 10),
    ("octobre", 46, "fevrier", 4, 16),
    ("octobre", 47, "fevrier", 4, 17),
    ("octobre", 48, "fevrier", 4, 18),
    ("octobre", 49, "fevrier", 4, 19),
    ("octobre", 50, "fevrier", 4, 20),
    ("novembre", 4, "janvier", 2, 8),
    ("novembre", 6, "mai", 5, 21),
    ("novembre", 7, "mai", 5, 22),
    ("novembre", 8, "mai", 5, 23),
    ("novembre", 9, "mai", 5, 24),
    ("novembre", 10, "mai", 5, 25),
    ("novembre", 11, "fevrier", 3, 12),
    ("novembre", 12, "septembre", 4, 17),
    ("novembre", 13, "septembre", 4, 18),
    ("novembre", 14, "septembre", 4, 19),
    ("novembre", 15, "septembre", 4, 20),
    ("decembre", 3, "juin", 3, 11),
    ("decembre", 6, "janvier", 2, 6),
    ("decembre", 7, "janvier", 2, 7),
    ("decembre", 8, "janvier", 2, 8),
    ("decembre", 9, "janvier", 2, 9),
    ("decembre", 10, "janvier", 2, 10),
    ("decembre", 11, "avril", 1, 1),
    ("decembre", 12, "avril", 1, 2),
    ("decembre", 13, "avril", 1, 3),
    ("decembre", 14, "avril", 1, 4),
    ("decembre", 15, "avril", 1, 5),
    ("decembre", 21, "juin", 6, 26),
    ("decembre", 22, "juin", 6, 27),
    ("decembre", 23, "juin", 6, 28),
    ("decembre", 24, "juin", 6, 29),
    ("decembre", 25, "juin", 6, 30),
    ("decembre", 28, "janvier", 3, 13),
    ("decembre", 29, "mars", 3, 12),
    ("decembre", 31, "fevrier", 1, 1),
    ("decembre", 32, "fevrier", 1, 2),
    ("decembre", 33, "fevrier", 1, 3),
    ("decembre", 34, "fevrier", 1, 4),
    ("decembre", 35, "fevrier", 1, 5),
    ("decembre", 44, "janvier", 3, 11),
)

VOCABULARY_MONTH_PREFIXES = {
    "janvier": "J1",
    "fevrier": "F2",
    "mars": "M3",
    "avril": "A4",
    "mai": "M5",
    "juin": "J6",
    "juillet": "J7",
    "aout": "A8",
    "septembre": "S9",
    "octobre": "O10",
    "novembre": "N11",
    "decembre": "D12",
}


class QuestionBankContentTests(TestCase):
    THEME_MEMOIRES = [
        (1, "Arrivée & installation", "hand-wave"),
        (2, "Logement & déménagement", "compass"),
        (3, "Vie de quartier & entraide", "users"),
        (4, "Travail & emploi", "laptop"),
        (5, "École & études", "graduation-cap"),
        (6, "Transports & mobilité", "arrow-left-right"),
        (7, "Voyages & vacances", "globe"),
        (8, "Sport & plein air", "sun"),
        (9, "Sorties & spectacles", "theater"),
        (10, "Arts & loisirs", "pen-line"),
        (11, "Fêtes & célébrations", "sparkles"),
    ]

    def test_ai_examiner_prompt_loader_extracts_only_the_master_prompt(self):
        prompt = load_ai_examiner_prompt()

        self.assertTrue(AI_EXAMINER_PROMPT_PATH.exists())
        self.assertTrue(prompt.startswith("You are a strict but fair simulator"))
        self.assertIn("scenario: WAIT_FOR_MY_SUBJECT (default)", prompt)
        self.assertIn(
            "CANDIDATE = QUESTIONER AND CONVERSATION LEADER.",
            prompt,
        )
        self.assertIn(
            "A normal AI role-play turn contains ZERO interrogative sentences",
            prompt,
        )
        self.assertIn("[STOP ASKING]", prompt)
        self.assertIn("[ANSWER ONLY]", prompt)
        self.assertIn(
            "Every sentence in your reply must directly answer my current",
            prompt,
        )
        self.assertNotIn(
            "ask a brief, role-natural return question",
            prompt,
        )
        self.assertNotIn(
            "occasionally mention a detail that invites a genuine follow-up",
            prompt,
        )
        self.assertNotIn("## Register guide", prompt)
        self.assertNotIn("```text", prompt)

    def test_ai_examiner_prompt_loader_rejects_a_missing_master_block(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prompt.md"
            path.write_text("# Incomplete guide", encoding="utf-8")

            with self.assertRaisesMessage(ValueError, "Master prompt section"):
                load_ai_examiner_prompt(path)

    def test_every_subject_theme_has_its_own_memoire(self):
        banks = load_question_banks()

        self.assertEqual(len(banks), len(self.THEME_MEMOIRES))
        self.assertEqual(
            [bank.number for bank in banks],
            [number for number, _, _ in self.THEME_MEMOIRES],
        )
        for bank, (number, label, icon) in zip(banks, self.THEME_MEMOIRES):
            self.assertEqual(bank.number, number)
            self.assertEqual(bank.label, label)
            self.assertEqual(bank.icon, icon)
            self.assertEqual(bank.title, f"Mémoire {number} · {label}")
            self.assertTrue(bank.subtitle)

        themes = json.loads(
            TACHE_TWO_SUBJECT_THEMES_PATH.read_text(encoding="utf-8")
        )["themes"]
        self.assertEqual(
            [(theme["order"], theme["name"], theme["icon"]) for theme in themes],
            self.THEME_MEMOIRES,
        )

    def test_each_memoire_shares_the_same_thirteen_categories(self):
        banks = load_question_banks()

        for bank in banks:
            self.assertEqual(bank.category_count, 13)
            self.assertEqual(
                [section.number for section in bank.sections],
                list(range(1, 14)),
            )
            self.assertEqual(bank.question_count, 52)
            self.assertEqual(len(bank.question_keys), 52)
            self.assertEqual(len(set(bank.question_keys)), 52)
            self.assertTrue(
                all(
                    key.startswith(f"memory:{bank.number}:question:")
                    for key in bank.question_keys
                )
            )
            for section in bank.sections:
                self.assertTrue(section.title)
                self.assertEqual(len(section.groups), 1)
                self.assertEqual(section.question_count, 4)
                for group in section.groups:
                    self.assertTrue(group.title)
                    self.assertTrue(group.guidance)

        self.assertEqual(sum(bank.category_count for bank in banks), 143)
        self.assertEqual(sum(bank.question_count for bank in banks), 572)

    def test_memoire_questions_are_unique_across_every_theme(self):
        questions = [
            question.text.casefold()
            for bank in load_question_banks()
            for section in bank.sections
            for group in section.groups
            for question in group.questions
        ]

        self.assertEqual(len(questions), 572)
        self.assertEqual(len(set(questions)), 572)

    def test_subject_questions_point_at_their_own_theme_memoire(self):
        themes = json.loads(
            TACHE_TWO_SUBJECT_THEMES_PATH.read_text(encoding="utf-8")
        )
        theme_order = {theme["slug"]: theme["order"] for theme in themes["themes"]}
        subject_themes = themes["subjects"]

        referenced = set()
        linked = 0
        for month in load_tache_two_subject_months():
            for batch in month.batches:
                for subject in batch.subjects:
                    key = (
                        f"tache2:{month.slug}:batch-{batch.number:02d}"
                        f":subject-{subject.number:02d}"
                    )
                    expected = theme_order[subject_themes[key]]
                    for question in subject.questions:
                        if not question.uses_memory:
                            continue
                        linked += 1
                        self.assertEqual(
                            question.memory_number,
                            expected,
                            f"{key} points at Mémoire {question.memory_number}",
                        )
                        self.assertIn(question.memory_section, range(1, 14))
                        referenced.add(
                            (question.memory_number, question.memory_section)
                        )

        self.assertEqual(linked, 3889)
        # Every theme mémoire is reached by at least one subject question.
        self.assertEqual(
            {number for number, _ in referenced},
            set(range(1, 12)),
        )
        for number in range(1, 12):
            sections = {
                section for memory, section in referenced if memory == number
            }
            self.assertGreaterEqual(len(sections), 10)

    def test_monthly_batches_are_question_only_and_memory_driven(self):
        months = load_tache_two_subject_months()

        self.assertEqual(len(months), 12)
        january = months[0]
        self.assertEqual(january.name, "Janvier")
        self.assertEqual(january.batch_count, 3)
        self.assertEqual(january.subject_count, 15)
        self.assertEqual(january.question_count, 219)
        first_batch, second_batch, third_batch = january.batches
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
        self.assertEqual(third_batch.number, 3)
        self.assertEqual(
            [subject.number for subject in third_batch.subjects],
            [11, 12, 13, 14, 15],
        )
        self.assertEqual(
            [subject.question_count for subject in third_batch.subjects],
            [15, 15, 15, 15, 15],
        )
        self.assertEqual(
            sum(
                subject.memory_question_count
                for subject in third_batch.subjects
            ),
            75,
        )
        february = months[1]
        self.assertEqual(february.name, "Février")
        self.assertEqual(february.batch_count, 6)
        self.assertEqual(february.subject_count, 30)
        self.assertEqual(february.question_count, 430)
        self.assertEqual(
            [
                [subject.number for subject in batch.subjects]
                for batch in february.batches
            ],
            [
                [1, 2, 3, 4, 5],
                [6, 7, 8, 9, 10],
                [11, 12, 13, 14, 15],
                [16, 17, 18, 19, 20],
                [21, 22, 23, 24, 25],
                [26, 27, 28, 29, 30],
            ],
        )
        self.assertEqual(
            [
                [subject.question_count for subject in batch.subjects]
                for batch in february.batches
            ],
            [
                [15, 15, 15, 14, 14],
                [14, 14, 13, 14, 15],
                [14, 13, 14, 8, 15],
                [15, 13, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
            ],
        )
        self.assertEqual(
            [
                sum(
                    subject.memory_question_count
                    for subject in batch.subjects
                )
                for batch in february.batches
            ],
            [73, 38, 51, 72, 75, 73],
        )
        march = months[2]
        self.assertEqual(march.name, "Mars")
        self.assertEqual(march.batch_count, 3)
        self.assertEqual(march.subject_count, 15)
        self.assertEqual(march.question_count, 223)
        self.assertEqual(
            [
                [subject.number for subject in batch.subjects]
                for batch in march.batches
            ],
            [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10], [11, 12, 13, 14, 15]],
        )
        self.assertEqual(
            [
                [subject.question_count for subject in batch.subjects]
                for batch in march.batches
            ],
            [
                [15, 15, 15, 15, 15],
                [15, 15, 15, 14, 14],
                [15, 15, 15, 15, 15],
            ],
        )
        self.assertEqual(
            [
                sum(
                    subject.memory_question_count
                    for subject in batch.subjects
                )
                for batch in march.batches
            ],
            [75, 73, 75],
        )
        april = months[3]
        self.assertEqual(april.name, "Avril")
        self.assertEqual(april.batch_count, 2)
        self.assertEqual(april.subject_count, 10)
        self.assertEqual(april.question_count, 150)
        self.assertEqual(
            [
                [subject.number for subject in batch.subjects]
                for batch in april.batches
            ],
            [[1, 2, 3, 4, 5], [6, 7, 8, 9, 10]],
        )
        self.assertEqual(
            [
                [subject.question_count for subject in batch.subjects]
                for batch in april.batches
            ],
            [[15, 15, 15, 15, 15], [15, 15, 15, 15, 15]],
        )
        self.assertEqual(
            [
                sum(
                    subject.memory_question_count
                    for subject in batch.subjects
                )
                for batch in april.batches
            ],
            [75, 75],
        )
        may = months[4]
        self.assertEqual(may.name, "Mai")
        self.assertEqual(may.batch_count, 5)
        self.assertEqual(may.subject_count, 25)
        self.assertEqual(may.question_count, 372)
        self.assertEqual(
            [
                [subject.number for subject in batch.subjects]
                for batch in may.batches
            ],
            [
                [1, 2, 3, 4, 5],
                [6, 7, 8, 9, 10],
                [11, 12, 13, 14],
                [15, 16, 17, 18, 19],
                [20, 21, 22, 23, 24, 25],
            ],
        )
        self.assertEqual(
            [
                [subject.question_count for subject in batch.subjects]
                for batch in may.batches
            ],
            [
                [15, 13, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15],
                [15, 14, 15, 15, 15],
                [15, 15, 15, 15, 15, 15],
            ],
        )
        self.assertEqual(
            [
                sum(
                    subject.memory_question_count
                    for subject in batch.subjects
                )
                for batch in may.batches
            ],
            [72, 74, 60, 72, 88],
        )
        june = months[5]
        self.assertEqual(june.name, "Juin")
        self.assertEqual(june.batch_count, 9)
        self.assertEqual(june.subject_count, 45)
        self.assertEqual(june.question_count, 673)
        self.assertEqual(
            [
                [subject.number for subject in batch.subjects]
                for batch in june.batches
            ],
            [
                [1, 2, 3, 4, 5],
                [6, 7, 8, 9, 10],
                [11, 12, 13, 14, 15],
                [16, 17, 18, 19, 20],
                [21, 22, 23, 24, 25],
                [26, 27, 28, 29, 30],
                [31, 32, 33, 34, 35],
                [36, 37, 38, 39, 40],
                [41, 42, 43, 44, 45],
            ],
        )
        self.assertEqual(
            [
                [subject.question_count for subject in batch.subjects]
                for batch in june.batches
            ],
            [
                [15, 15, 15, 15, 15],
                [15, 15, 14, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [14, 16, 15, 14, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
            ],
        )
        self.assertEqual(
            [
                sum(
                    subject.memory_question_count
                    for subject in batch.subjects
                )
                for batch in june.batches
            ],
            [75, 74, 75, 75, 71, 75, 73, 75, 75],
        )
        july = months[6]
        self.assertEqual(july.name, "Juillet")
        self.assertEqual(july.batch_count, 8)
        self.assertEqual(july.subject_count, 38)
        self.assertEqual(july.question_count, 567)
        self.assertEqual(
            [
                [subject.number for subject in batch.subjects]
                for batch in july.batches
            ],
            [
                [1, 2, 3, 4, 5],
                [6, 7, 8, 9, 10],
                [11, 12, 13, 14, 15],
                [16, 17, 18, 19, 20],
                [21, 22, 23, 24, 25],
                [26, 27, 28],
                [29, 30, 31, 32, 33],
                [34, 35, 36, 37, 38],
            ],
        )
        self.assertEqual(
            [
                [subject.question_count for subject in batch.subjects]
                for batch in july.batches
            ],
            [
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 13, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 14, 15, 15],
            ],
        )
        self.assertEqual(
            [
                sum(
                    subject.memory_question_count
                    for subject in batch.subjects
                )
                for batch in july.batches
            ],
            [34, 41, 72, 28, 28, 45, 21, 47],
        )
        august = months[7]
        self.assertEqual(august.name, "Août")
        self.assertEqual(august.batch_count, 4)
        self.assertEqual(august.subject_count, 20)
        self.assertEqual(august.question_count, 300)
        self.assertEqual(
            [
                [subject.number for subject in batch.subjects]
                for batch in august.batches
            ],
            [
                [1, 2, 3, 4, 5],
                [6, 7, 8, 9, 10],
                [11, 12, 13, 14, 15],
                [16, 17, 18, 19, 20],
            ],
        )
        self.assertEqual(
            [
                [subject.question_count for subject in batch.subjects]
                for batch in august.batches
            ],
            [[15, 15, 15, 15, 15]] * 4,
        )
        self.assertEqual(
            [
                sum(
                    subject.memory_question_count
                    for subject in batch.subjects
                )
                for batch in august.batches
            ],
            [75, 64, 74, 75],
        )
        september = months[8]
        self.assertEqual(september.name, "Septembre")
        self.assertEqual(september.batch_count, 7)
        self.assertEqual(september.subject_count, 35)
        self.assertEqual(september.question_count, 523)
        self.assertEqual(
            [
                [subject.number for subject in batch.subjects]
                for batch in september.batches
            ],
            [
                [1, 2, 3, 4, 5],
                [6, 7, 8, 9, 10],
                [11, 12, 13, 14, 15],
                [16, 17, 18, 19, 20],
                [21, 22, 23, 24, 25],
                [26, 27, 28, 29, 30],
                [31, 32, 33, 34, 35],
            ],
        )
        self.assertEqual(
            [
                [subject.question_count for subject in batch.subjects]
                for batch in september.batches
            ],
            [
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [13, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
            ],
        )
        self.assertEqual(
            [
                sum(
                    subject.memory_question_count
                    for subject in batch.subjects
                )
                for batch in september.batches
            ],
            [10, 73, 75, 20, 34, 34, 2],
        )
        october = months[9]
        self.assertEqual(october.name, "Octobre")
        self.assertEqual(october.batch_count, 10)
        self.assertEqual(october.subject_count, 50)
        self.assertEqual(october.question_count, 748)
        self.assertEqual(
            [
                [subject.question_count for subject in batch.subjects]
                for batch in october.batches
            ],
            [[15, 15, 15, 15, 15]] * 9
            + [[15, 13, 15, 15, 15]],
        )
        self.assertEqual(
            [
                sum(
                    subject.memory_question_count
                    for subject in batch.subjects
                )
                for batch in october.batches
            ],
            [75, 75, 54, 27, 37, 20, 64, 4, 12, 72],
        )
        november = months[10]
        self.assertEqual(november.name, "Novembre")
        self.assertEqual(november.batch_count, 3)
        self.assertEqual(november.subject_count, 15)
        self.assertEqual(november.question_count, 223)
        self.assertEqual(
            [
                [subject.question_count for subject in batch.subjects]
                for batch in november.batches
            ],
            [
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [13, 15, 15, 15, 15],
            ],
        )
        self.assertEqual(
            [
                sum(
                    subject.memory_question_count
                    for subject in batch.subjects
                )
                for batch in november.batches
            ],
            [35, 73, 20],
        )
        december = months[11]
        self.assertEqual(december.name, "Décembre")
        self.assertEqual(december.batch_count, 10)
        self.assertEqual(december.subject_count, 50)
        self.assertEqual(december.question_count, 747)
        self.assertEqual(
            [
                [subject.question_count for subject in batch.subjects]
                for batch in december.batches
            ],
            [
                [15, 15, 15, 15, 15],
                [14, 16, 15, 14, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 14, 14],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
                [15, 15, 15, 15, 15],
            ],
        )
        self.assertEqual(
            [
                sum(
                    subject.memory_question_count
                    for subject in batch.subjects
                )
                for batch in december.batches
            ],
            [26, 71, 75, 15, 75, 47, 73, 16, 24, 45],
        )

        def question_signatures(subject):
            return [
                (
                    question.text,
                    question.memory_number,
                    question.memory_section,
                )
                for question in subject.questions
            ]

        january_gym = january.batches[2].subjects[2]
        march_gym = march.batches[0].subjects[0]
        self.assertEqual(
            question_signatures(march_gym),
            question_signatures(january_gym),
        )
        for march_subject, february_subject in zip(
            march.batches[1].subjects,
            february.batches[0].subjects,
            strict=True,
        ):
            self.assertEqual(
                question_signatures(march_subject),
                question_signatures(february_subject),
            )
        for march_subject, february_subject in zip(
            march.batches[2].subjects,
            february.batches[4].subjects,
            strict=True,
        ):
            self.assertEqual(
                question_signatures(march_subject),
                question_signatures(february_subject),
            )
        april_travel = april.batches[1].subjects[0]
        february_travel = february.batches[5].subjects[3]
        self.assertEqual(
            question_signatures(april_travel),
            question_signatures(february_travel),
        )
        subjects_by_key = {
            (month.slug, batch.number, subject.number): subject
            for month in months
            for batch in month.batches
            for subject in batch.subjects
        }
        for may_key, source_key in (
            (("mai", 1, 1), ("fevrier", 4, 16)),
            (("mai", 1, 2), ("fevrier", 4, 17)),
            (("mai", 1, 3), ("fevrier", 4, 18)),
            (("mai", 1, 4), ("fevrier", 4, 19)),
            (("mai", 1, 5), ("fevrier", 4, 20)),
            (("mai", 3, 11), ("janvier", 3, 11)),
            (("mai", 3, 12), ("janvier", 3, 12)),
            (("mai", 3, 13), ("janvier", 3, 13)),
            (("mai", 3, 14), ("janvier", 3, 14)),
            (("mai", 4, 16), ("fevrier", 3, 11)),
        ):
            self.assertEqual(
                question_signatures(subjects_by_key[may_key]),
                question_signatures(subjects_by_key[source_key]),
            )
        for june_key, source_key in (
            (("juin", 2, 7), ("mars", 3, 12)),
            (("juin", 2, 8), ("mars", 2, 10)),
            (("juin", 4, 19), ("janvier", 3, 13)),
            (("juin", 5, 21), ("janvier", 2, 6)),
            (("juin", 5, 22), ("janvier", 2, 7)),
            (("juin", 5, 23), ("janvier", 2, 8)),
            (("juin", 5, 24), ("janvier", 2, 9)),
            (("juin", 5, 25), ("janvier", 2, 10)),
            (("juin", 7, 31), ("fevrier", 6, 26)),
            (("juin", 7, 32), ("fevrier", 6, 27)),
            (("juin", 7, 33), ("fevrier", 6, 28)),
            (("juin", 7, 34), ("fevrier", 6, 29)),
            (("juin", 7, 35), ("fevrier", 6, 30)),
            (("juin", 8, 36), ("juin", 1, 1)),
            (("juin", 8, 37), ("juin", 1, 2)),
            (("juin", 8, 38), ("juin", 1, 3)),
            (("juin", 8, 39), ("juin", 1, 4)),
            (("juin", 8, 40), ("juin", 1, 5)),
            (("juin", 9, 41), ("avril", 1, 1)),
            (("juin", 9, 42), ("avril", 1, 2)),
            (("juin", 9, 43), ("avril", 1, 3)),
            (("juin", 9, 44), ("avril", 1, 4)),
            (("juin", 9, 45), ("avril", 1, 5)),
        ):
            self.assertEqual(
                question_signatures(subjects_by_key[june_key]),
                question_signatures(subjects_by_key[source_key]),
            )
        for july_key, source_key in (
            (("juillet", 1, 1), ("juin", 1, 2)),
            (("juillet", 1, 5), ("avril", 1, 3)),
            (("juillet", 3, 11), ("mai", 1, 1)),
            (("juillet", 3, 12), ("mai", 1, 2)),
            (("juillet", 3, 13), ("fevrier", 4, 18)),
            (("juillet", 3, 14), ("fevrier", 4, 19)),
            (("juillet", 3, 15), ("fevrier", 4, 20)),
            (("juillet", 5, 21), ("juillet", 4, 16)),
            (("juillet", 5, 22), ("juillet", 4, 17)),
            (("juillet", 5, 23), ("juillet", 4, 18)),
            (("juillet", 5, 24), ("juillet", 4, 19)),
            (("juillet", 5, 25), ("juillet", 4, 20)),
            (("juillet", 6, 26), ("juin", 4, 18)),
            (("juillet", 6, 27), ("avril", 2, 7)),
            (("juillet", 6, 28), ("janvier", 3, 15)),
            (("juillet", 8, 35), ("mars", 3, 12)),
            (("juillet", 8, 36), ("mars", 2, 10)),
            (("juillet", 8, 37), ("juin", 2, 9)),
        ):
            self.assertEqual(
                question_signatures(subjects_by_key[july_key]),
                question_signatures(subjects_by_key[source_key]),
            )
        for august_key, source_key in (
            (("aout", 1, 1), ("juin", 1, 1)),
            (("aout", 1, 2), ("juin", 1, 2)),
            (("aout", 1, 3), ("juin", 1, 3)),
            (("aout", 1, 4), ("juin", 1, 4)),
            (("aout", 1, 5), ("juin", 1, 5)),
            (("aout", 2, 7), ("mai", 2, 7)),
            (("aout", 2, 8), ("mai", 2, 10)),
            (("aout", 2, 9), ("mai", 2, 9)),
            (("aout", 3, 11), ("mai", 2, 6)),
            (("aout", 3, 12), ("mai", 2, 7)),
            (("aout", 3, 13), ("mai", 2, 8)),
            (("aout", 3, 14), ("mai", 2, 9)),
            (("aout", 3, 15), ("mai", 2, 10)),
            (("aout", 4, 16), ("janvier", 3, 11)),
            (("aout", 4, 17), ("janvier", 3, 12)),
            (("aout", 4, 18), ("janvier", 3, 13)),
            (("aout", 4, 19), ("janvier", 3, 14)),
            (("aout", 4, 20), ("mai", 4, 15)),
        ):
            self.assertEqual(
                question_signatures(subjects_by_key[august_key]),
                question_signatures(subjects_by_key[source_key]),
            )
        for september_key, source_key in (
            (("septembre", 1, 1), ("juillet", 1, 4)),
            (("septembre", 2, 6), ("fevrier", 6, 26)),
            (("septembre", 2, 7), ("fevrier", 6, 27)),
            (("septembre", 2, 8), ("fevrier", 6, 28)),
            (("septembre", 2, 9), ("fevrier", 6, 29)),
            (("septembre", 2, 10), ("fevrier", 6, 30)),
            (("septembre", 3, 11), ("mars", 3, 11)),
            (("septembre", 3, 12), ("mars", 3, 12)),
            (("septembre", 3, 13), ("mars", 3, 13)),
            (("septembre", 3, 14), ("mars", 3, 14)),
            (("septembre", 3, 15), ("fevrier", 5, 25)),
            (("septembre", 4, 16), ("fevrier", 3, 12)),
            (("septembre", 5, 21), ("juillet", 8, 34)),
            (("septembre", 5, 24), ("janvier", 3, 13)),
            (("septembre", 5, 25), ("juillet", 1, 4)),
            (("septembre", 6, 26), ("juillet", 8, 34)),
            (("septembre", 6, 29), ("janvier", 3, 13)),
            (("septembre", 6, 30), ("juillet", 1, 4)),
            (("septembre", 7, 31), ("septembre", 1, 3)),
            (("septembre", 7, 33), ("septembre", 1, 4)),
            (("septembre", 6, 27), ("septembre", 5, 22)),
            (("septembre", 6, 28), ("septembre", 5, 23)),
        ):
            self.assertEqual(
                question_signatures(subjects_by_key[september_key]),
                question_signatures(subjects_by_key[source_key]),
            )
        for (
            target_month,
            target_subject,
            source_month,
            source_batch,
            source_subject,
        ) in FINAL_EXACT_RESPONSE_REUSE:
            target_batch = (target_subject - 1) // 5 + 1
            self.assertEqual(
                question_signatures(
                    subjects_by_key[
                        (target_month, target_batch, target_subject)
                    ]
                ),
                question_signatures(
                    subjects_by_key[
                        (source_month, source_batch, source_subject)
                    ]
                ),
            )
        self.assertTrue(
            all(
                question.text.endswith("?")
                for month in months
                for batch in month.batches
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
            for month in months
            for batch in month.batches
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

    def test_equivalent_subjects_must_share_their_vocabulary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            responses = parse_tache_two_responses()
            shared = next(
                response
                for response in responses
                if len(response.prompts) > 1
            )
            canonical_key = shared.content_key
            alias_key = next(
                prompt.content_key
                for prompt in shared.prompts
                if prompt.content_key != canonical_key
            )
            blocks = {}
            for path in TACHE_TWO_VOCABULARY_DIR.glob("*.json"):
                payload = json.loads(path.read_text(encoding="utf-8"))
                for row in payload["subjects"]:
                    blocks[row["subject_key"]] = row
            drifted = copy.deepcopy(blocks[alias_key])
            drifted["entries"][0]["french"] = "une formulation divergente"
            (root / "vocabulary.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "subjects": [blocks[canonical_key], drifted],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as error:
                parse_tache_two_subject_vocabulary(
                    responses,
                    directory=root,
                )

        self.assertIn("not its vocabulary", str(error.exception))

    def test_subjects_generate_srs_responses_and_vocabulary(self):
        months = load_tache_two_subject_months()
        responses = parse_tache_two_responses()
        vocabulary = parse_tache_two_subject_vocabulary(responses)

        subject_keys = [
            tache_two_subject_content_key(
                month.slug,
                batch.number,
                subject.number,
            )
            for month in months
            for batch in month.batches
            for subject in batch.subjects
        ]
        prompts = [
            prompt for response in responses for prompt in response.prompts
        ]

        self.assertEqual(len(subject_keys), 348)
        self.assertEqual(len(responses), 186)
        self.assertEqual(len(prompts), len(subject_keys))
        self.assertEqual(
            {prompt.content_key for prompt in prompts},
            set(subject_keys),
        )
        self.assertEqual(
            sum(len(response.arguments) for response in responses),
            2764,
        )
        self.assertEqual(len(vocabulary), 5580)
        for response in responses:
            canonical = [
                prompt for prompt in response.prompts if prompt.is_canonical
            ]
            self.assertEqual(len(canonical), 1)
            self.assertEqual(canonical[0].content_key, response.content_key)
            self.assertEqual(
                response.body,
                "\n".join(
                    argument.idea for argument in response.arguments
                ),
            )

        # Subjects that repeat a question set collapse onto one response.
        subjects_by_key = {
            tache_two_subject_content_key(
                month.slug,
                batch.number,
                subject.number,
            ): subject
            for month in months
            for batch in month.batches
            for subject in batch.subjects
        }
        response_key_by_subject_key = tache_two_response_key_by_subject_key(
            responses
        )
        self.assertEqual(
            set(response_key_by_subject_key),
            set(subject_keys),
        )
        grouped_by_questions = {}
        for subject_key, subject in subjects_by_key.items():
            signature = tuple(
                question.text for question in subject.questions
            )
            grouped_by_questions.setdefault(signature, set()).add(
                response_key_by_subject_key[subject_key]
            )
        self.assertEqual(len(grouped_by_questions), len(responses))
        for response_keys in grouped_by_questions.values():
            self.assertEqual(len(response_keys), 1)

        for (
            target_month,
            target_subject,
            source_month,
            source_batch,
            source_subject,
        ) in FINAL_EXACT_RESPONSE_REUSE:
            target_batch = (target_subject - 1) // 5 + 1
            self.assertEqual(
                response_key_by_subject_key[
                    tache_two_subject_content_key(
                        target_month,
                        target_batch,
                        target_subject,
                    )
                ],
                response_key_by_subject_key[
                    tache_two_subject_content_key(
                        source_month,
                        source_batch,
                        source_subject,
                    )
                ],
            )

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
        sources_by_response_key = {
            response.content_key: tuple(
                (prompt.theme, prompt.number)
                for prompt in response.prompts
            )
            for response in responses
        }
        questions_by_sources = {
            sources_by_response_key[response.content_key]: {
                argument.idea for argument in response.arguments
            }
            for response in responses
        }
        for phrase in vocabulary:
            self.assertIn(phrase.sources, questions_by_sources)
            self.assertIn(
                phrase.example,
                questions_by_sources[phrase.sources],
            )
            self.assertEqual(
                phrase.example.casefold().count(
                    phrase.expression.casefold()
                ),
                1,
            )
        for sources in questions_by_sources:
            source_phrases = [
                phrase
                for phrase in vocabulary
                if phrase.sources == sources
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
        vocabulary_orders = [phrase.order for phrase in vocabulary]
        self.assertEqual(len(set(vocabulary_orders)), len(vocabulary_orders))
        self.assertEqual(
            vocabulary_orders,
            list(
                range(
                    vocabulary_orders[0],
                    vocabulary_orders[0] + len(vocabulary_orders),
                )
            ),
        )
        self.assertFalse(comprehension_orders & set(vocabulary_orders))

    def test_theme_vocabulary_covers_every_theme_with_three_equal_sections(self):
        phrases = parse_tache_two_theme_vocabulary()

        self.assertEqual(len(phrases), 11 * TACHE_TWO_THEME_VOCABULARY_PER_THEME)
        self.assertEqual(len({phrase.phrase_id for phrase in phrases}), len(phrases))
        self.assertEqual(
            len({phrase.expression.casefold() for phrase in phrases}),
            len(phrases),
        )
        self.assertTrue(all(phrase.tier == PhraseTier.THEME for phrase in phrases))
        expected_categories = tuple(
            category
            for category in TACHE_TWO_THEME_VOCABULARY_CATEGORIES.values()
            for _ in range(TACHE_TWO_THEME_VOCABULARY_PER_KIND)
        )
        for start in range(0, len(phrases), TACHE_TWO_THEME_VOCABULARY_PER_THEME):
            theme_phrases = phrases[
                start : start + TACHE_TWO_THEME_VOCABULARY_PER_THEME
            ]
            self.assertEqual(
                tuple(phrase.category for phrase in theme_phrases),
                expected_categories,
            )
            self.assertEqual(len({phrase.expression.casefold() for phrase in theme_phrases}), 45)
            for phrase in theme_phrases:
                self.assertEqual(
                    phrase.example.casefold().count(phrase.anchor.casefold()),
                    1,
                )

    def test_theme_vocabulary_rejects_an_example_without_its_anchor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            for source in TACHE_TWO_THEME_VOCABULARY_DIR.glob("*.json"):
                payload = json.loads(source.read_text(encoding="utf-8"))
                if source.name == "arrivee.json":
                    payload["entries"][0]["example"] = (
                        "Phrase volontairement invalide sans cible attendue."
                    )
                (directory / source.name).write_text(
                    json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(
                ValueError,
                "example must contain its anchor exactly once",
            ):
                parse_tache_two_theme_vocabulary(directory=directory)

    def test_theme_vocabulary_rejects_duplicate_targets_across_themes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            arrival_payload = json.loads(
                (TACHE_TWO_THEME_VOCABULARY_DIR / "arrivee.json").read_text(
                    encoding="utf-8"
                )
            )
            duplicate_target = arrival_payload["entries"][15]["french"]
            for source in TACHE_TWO_THEME_VOCABULARY_DIR.glob("*.json"):
                payload = json.loads(source.read_text(encoding="utf-8"))
                if source.name == "logement.json":
                    payload["entries"][15]["french"] = duplicate_target
                (directory / source.name).write_text(
                    json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(
                ValueError,
                "Duplicate Tâche 2 theme-vocabulary target",
            ):
                parse_tache_two_theme_vocabulary(directory=directory)

    def test_theme_vocabulary_requires_noun_articles_and_gender_markers(self):
        invalid_targets = (
            (
                "un logement temporaire",
                "noun must include an article and a gender/number marker",
            ),
            (
                "un logement temporaire (m./f.)",
                "noun must include an article and a gender/number marker",
            ),
            (
                "un logement temporaire (f.)",
                "article and gender/number marker do not agree",
            ),
        )
        for french, expected_error in invalid_targets:
            with self.subTest(french=french):
                with tempfile.TemporaryDirectory() as temp_dir:
                    directory = Path(temp_dir)
                    for source in TACHE_TWO_THEME_VOCABULARY_DIR.glob(
                        "*.json"
                    ):
                        payload = json.loads(
                            source.read_text(encoding="utf-8")
                        )
                        if source.name == "arrivee.json":
                            payload["entries"][1]["french"] = french
                        (directory / source.name).write_text(
                            json.dumps(payload, ensure_ascii=False),
                            encoding="utf-8",
                        )

                    with self.assertRaisesRegex(ValueError, expected_error):
                        parse_tache_two_theme_vocabulary(directory=directory)


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

    def test_tache_two_overview_features_theme_vocabulary(self):
        response = self.client.get(
            reverse(
                "study:task_detail",
                args=[self.task.part.slug, self.task.slug],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "study/tache_two_overview.html")
        self.assertTrue(self.task.available)
        self.assertEqual(response.context["subject_count"], 348)
        self.assertEqual(response.context["theme_vocabulary"]["theme_count"], 11)
        self.assertEqual(response.context["theme_vocabulary"]["phrase_count"], 495)
        self.assertEqual(response.context["theme_vocabulary"]["batch_count"], 33)
        self.assertEqual(
            response.context["ai_practice_prompt"],
            load_ai_examiner_prompt(),
        )
        self.assertContains(response, "AI Practice Prompt")
        self.assertContains(
            response,
            'data-prompt-copy-source="ai-practice-prompt-content"',
        )
        self.assertContains(response, 'id="ai-practice-prompt-content"')
        self.assertContains(
            response,
            "data-tache-two-overview-panel",
            count=2,
        )
        self.assertContains(
            response,
            (
                'id="theme-vocabulary-overview-panel-title">'
                "Vocabulaire par thème</h2>"
            ),
        )
        self.assertContains(
            response,
            'id="subject-overview-panel-title">Sujets</h2>',
        )
        self.assertContains(response, "0/33")
        self.assertContains(response, "lots terminés")
        self.assertContains(response, "0/348")
        self.assertContains(response, "sujets terminés")
        self.assertContains(
            response,
            reverse("study:tache_two_theme_vocabulary"),
        )
        self.assertContains(
            response,
            reverse(
                "study:task_browse",
                args=[self.task.part.slug, self.task.slug],
            ),
        )
        self.assertNotContains(response, "data-collection-view-toggle")
        self.assertNotContains(response, "data-collection-item")
        self.assertNotContains(response, "data-tache-two-subject-month")
        self.assertNotContains(response, "Janvier · Batch 1")
        self.assertNotContains(response, "Mémoires")
        self.assertNotContains(response, "memory-entry")
        self.assertNotContains(response, "data-question-bank-question")
        self.assertNotContains(response, "Sujets &amp; réponses")
        self.assertNotContains(response, "Réflexe Mémoire")
        self.assertNotContains(response, ">Pratiquer</a>")

    def test_theme_vocabulary_has_a_dedicated_directory(self):
        url = reverse("study:tache_two_theme_vocabulary")
        response = self.client.get(url)

        self.assertEqual(
            url,
            "/expression/orale/tache-2/vocabulaire-par-theme/",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "study/tache_two_theme_vocabulary.html",
        )
        self.assertEqual(response.context["theme_count"], 11)
        self.assertEqual(response.context["phrase_count"], 495)
        self.assertEqual(response.context["batch_count"], 33)
        self.assertEqual(response.context["active_nav_area"], "expression")
        self.assertEqual(response.context["content_task"], self.task)
        self.assertContains(response, "<span>Vocabulaire par thème</span>", html=True)
        self.assertContains(response, "data-collection-view-toggle")
        self.assertContains(response, 'data-collection-view="adaptive"')
        self.assertContains(response, "collection-table-header--memories")
        self.assertContains(response, "data-collection-item", count=11)
        self.assertNotContains(response, "Choisissez une situation")
        self.assertNotContains(response, "Les 11 thèmes de la Tâche 2")
        self.assertNotContains(
            response,
            "Chaque thème propose trois parcours complémentaires",
        )
        for item in response.context["themes"]:
            self.assertEqual(item["phrase_count"], 45)
            self.assertEqual(item["word_count"], 15)
            self.assertEqual(item["expression_count"], 15)
            self.assertEqual(item["fragment_count"], 15)
            self.assertEqual(item["batch_count"], 3)
            self.assertContains(
                response,
                item["url"],
            )
        self.assertContains(response, "Arrivée &amp; installation")
        self.assertContains(response, "Fêtes &amp; célébrations")
        self.assertContains(
            response,
            '<a class="is-active" href="'
            + reverse("study:tache_two_theme_vocabulary")
            + '">Vocabulaire par thème</a>',
            html=True,
        )
        self.assertNotContains(response, "data-question-bank-question")
        self.assertNotContains(response, "data-tache-two-subject-month")

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
        third_batch_url = reverse(
            "study:task_subject_batch",
            args=[self.task.part.slug, self.task.slug, "janvier", 3],
        )
        february_batch_url = reverse(
            "study:task_subject_batch",
            args=[self.task.part.slug, self.task.slug, "fevrier", 6],
        )
        march_batch_url = reverse(
            "study:task_subject_batch",
            args=[self.task.part.slug, self.task.slug, "mars", 1],
        )
        march_second_batch_url = reverse(
            "study:task_subject_batch",
            args=[self.task.part.slug, self.task.slug, "mars", 2],
        )
        march_third_batch_url = reverse(
            "study:task_subject_batch",
            args=[self.task.part.slug, self.task.slug, "mars", 3],
        )
        april_batch_url = reverse(
            "study:task_subject_batch",
            args=[self.task.part.slug, self.task.slug, "avril", 1],
        )
        april_second_batch_url = reverse(
            "study:task_subject_batch",
            args=[self.task.part.slug, self.task.slug, "avril", 2],
        )
        may_batch_url = reverse(
            "study:task_subject_batch",
            args=[self.task.part.slug, self.task.slug, "mai", 5],
        )
        june_batch_url = reverse(
            "study:task_subject_batch",
            args=[self.task.part.slug, self.task.slug, "juin", 9],
        )
        july_batch_url = reverse(
            "study:task_subject_batch",
            args=[self.task.part.slug, self.task.slug, "juillet", 8],
        )
        august_batch_url = reverse(
            "study:task_subject_batch",
            args=[self.task.part.slug, self.task.slug, "aout", 4],
        )
        september_batch_url = reverse(
            "study:task_subject_batch",
            args=[self.task.part.slug, self.task.slug, "septembre", 7],
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
        third_batch_subject_url = reverse(
            "study:task_subject_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                "janvier",
                3,
                11,
            ],
        )
        february_subject_url = reverse(
            "study:task_subject_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                "fevrier",
                6,
                26,
            ],
        )
        march_subject_url = reverse(
            "study:task_subject_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                "mars",
                1,
                5,
            ],
        )
        march_second_subject_url = reverse(
            "study:task_subject_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                "mars",
                2,
                10,
            ],
        )
        march_third_subject_url = reverse(
            "study:task_subject_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                "mars",
                3,
                11,
            ],
        )
        april_subject_url = reverse(
            "study:task_subject_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                "avril",
                1,
                1,
            ],
        )
        april_second_subject_url = reverse(
            "study:task_subject_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                "avril",
                2,
                6,
            ],
        )
        may_subject_url = reverse(
            "study:task_subject_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                "mai",
                5,
                25,
            ],
        )
        june_subject_url = reverse(
            "study:task_subject_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                "juin",
                9,
                45,
            ],
        )
        july_subject_url = reverse(
            "study:task_subject_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                "juillet",
                8,
                38,
            ],
        )
        august_subject_url = reverse(
            "study:task_subject_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                "aout",
                4,
                20,
            ],
        )
        september_subject_url = reverse(
            "study:task_subject_detail",
            args=[
                self.task.part.slug,
                self.task.slug,
                "septembre",
                7,
                32,
            ],
        )
        final_route_data = (
            (
                "octobre",
                "Octobre",
                10,
                50,
                "Apéritif de bienvenue – Québec",
                15,
            ),
            (
                "novembre",
                "Novembre",
                3,
                15,
                "Louer son appartement pour les vacances",
                15,
            ),
            (
                "decembre",
                "Décembre",
                10,
                50,
                "Découvrir la ville avec des amis – Office de tourisme",
                15,
            ),
        )
        final_routes = [
            (
                month_name,
                batch_number,
                subject_number,
                title,
                question_count,
                reverse(
                    "study:task_subject_batch",
                    args=[
                        self.task.part.slug,
                        self.task.slug,
                        month_slug,
                        batch_number,
                    ],
                ),
                reverse(
                    "study:task_subject_detail",
                    args=[
                        self.task.part.slug,
                        self.task.slug,
                        month_slug,
                        batch_number,
                        subject_number,
                    ],
                ),
            )
            for (
                month_slug,
                month_name,
                batch_number,
                subject_number,
                title,
                question_count,
            ) in final_route_data
        ]

        index = self.client.get(index_url)
        first_subject_key = tache_two_subject_content_key("janvier", 1, 1)
        self.assertEqual(index.status_code, 200)
        self.assertTemplateUsed(index, "study/tache_two_subjects.html")
        self.assertEqual(index.context["theme_count"], 11)
        self.assertEqual(index.context["subject_count"], 348)
        self.assertEqual(index.context["question_count"], 5175)
        self.assertEqual(len(index.context["subject_prompt_map"]), 348)
        self.assertContains(
            index,
            'data-prompt-copy-source="tache-two-theme-prompts"',
            count=696,
        )
        self.assertContains(
            index,
            f'data-prompt-copy-key="{first_subject_key}"',
            count=2,
        )
        self.assertNotContains(index, "Réflexe Mémoire")
        self.assertContains(index, "Sujets par thème")
        self.assertContains(index, "Voyages &amp; vacances")
        self.assertContains(index, "Logement &amp; déménagement")
        self.assertContains(index, "Vie de quartier &amp; entraide")
        self.assertContains(index, "Sport &amp; plein air")
        self.assertContains(index, "Arts &amp; loisirs")
        self.assertContains(index, "Transports &amp; mobilité")
        self.assertContains(index, "Sorties &amp; spectacles")
        self.assertContains(index, "École &amp; études")
        self.assertContains(index, "Travail &amp; emploi")
        self.assertContains(index, "Fêtes &amp; célébrations")
        self.assertContains(index, "Arrivée &amp; installation")
        self.assertNotContains(index, "data-tache-two-subject-batch")
        self.assertNotContains(index, "Batch 01")
        self.assertContains(index, "t1-row__link", count=348)
        self.assertContains(index, "data-t1-table-theme", count=11)
        self.assertContains(index, "data-t1-table-subject", count=348)
        self.assertNotContains(index, 'class="t1-table__theme"')
        self.assertContains(index, subject_url)
        self.assertContains(index, february_subject_url)
        self.assertContains(index, march_subject_url)
        self.assertContains(index, april_subject_url)
        self.assertContains(index, may_subject_url)
        self.assertContains(index, june_subject_url)
        self.assertContains(index, july_subject_url)
        self.assertContains(index, august_subject_url)
        self.assertContains(index, september_subject_url)
        for *_, batch_route, subject_route in final_routes:
            self.assertContains(index, subject_route)
            self.assertContains(self.client.get(batch_route), subject_route)

        batch = self.client.get(batch_url)
        self.assertEqual(batch.status_code, 200)
        self.assertTemplateUsed(
            batch,
            "study/tache_two_subject_batch.html",
        )
        self.assertContains(batch, "Janvier · Batch 1")
        self.assertContains(batch, "data-tache-two-subject", count=5)
        self.assertContains(batch, "tache-two-subject-card--new", count=5)
        self.assertContains(
            batch,
            'data-prompt-copy-source="tache-two-batch-prompts"',
            count=5,
        )
        self.assertEqual(len(batch.context["subject_prompt_map"]), 5)
        self.assertEqual(
            batch.context["subject_prompt_map"][first_subject_key],
            batch.context["subject_batch"]["subjects"][0]["prompt"],
        )
        self.assertEqual(batch.context["subject_batch"]["progress"].status, "new")
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
        self.assertContains(
            subject,
            'data-prompt-copy-source="tache-two-subject-prompt"',
            count=1,
        )
        self.assertEqual(len(subject.context["vocabulary_batches"]), 3)
        self.assertTrue(
            all(
                batch["phrase_count"] == 10
                for batch in subject.context["vocabulary_batches"]
            )
        )
        self.assertEqual(len(subject.context["subject_vocabulary"]), 10)
        self.assertContains(
            subject,
            'data-recall-controls="tache-two-subject-vocabulary-recall-catalog"',
            count=1,
        )
        self.assertContains(subject, 'data-recall-cell="french"', count=10)
        self.assertContains(subject, 'data-recall-cell="meaning"', count=10)
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

        third_batch = self.client.get(third_batch_url)
        self.assertEqual(third_batch.status_code, 200)
        self.assertContains(third_batch, "Janvier · Batch 3")
        self.assertContains(
            third_batch,
            "data-tache-two-subject",
            count=5,
        )
        self.assertContains(third_batch, third_batch_subject_url)

        third_batch_subject = self.client.get(third_batch_subject_url)
        self.assertEqual(third_batch_subject.status_code, 200)
        self.assertContains(
            third_batch_subject,
            "Nouveau dans l&#x27;entreprise",
        )
        self.assertContains(
            third_batch_subject,
            "data-tache-two-question",
            count=15,
        )
        self.assertContains(third_batch_subject, "30 vocabs")
        self.assertEqual(
            len(third_batch_subject.context["vocabulary_batches"]),
            3,
        )

        february_batch = self.client.get(february_batch_url)
        self.assertEqual(february_batch.status_code, 200)
        self.assertContains(february_batch, "Février · Batch 6")
        self.assertContains(
            february_batch,
            "data-tache-two-subject",
            count=5,
        )
        self.assertContains(february_batch, february_subject_url)

        february_subject = self.client.get(february_subject_url)
        self.assertEqual(february_subject.status_code, 200)
        self.assertContains(
            february_subject,
            "Garde d&#x27;enfant pendant un week-end",
        )
        self.assertContains(
            february_subject,
            "data-tache-two-question",
            count=15,
        )
        self.assertContains(february_subject, "30 vocabs")
        self.assertEqual(
            len(february_subject.context["vocabulary_batches"]),
            3,
        )

        march_batch = self.client.get(march_batch_url)
        self.assertEqual(march_batch.status_code, 200)
        self.assertContains(march_batch, "Mars · Batch 1")
        self.assertContains(
            march_batch,
            "data-tache-two-subject",
            count=5,
        )
        self.assertContains(march_batch, march_subject_url)

        march_subject = self.client.get(march_subject_url)
        self.assertEqual(march_subject.status_code, 200)
        self.assertContains(
            march_subject,
            "Achat d&#x27;une voiture d&#x27;occasion",
        )
        self.assertContains(
            march_subject,
            "data-tache-two-question",
            count=15,
        )
        self.assertContains(march_subject, "30 vocabs")
        self.assertEqual(
            len(march_subject.context["vocabulary_batches"]),
            3,
        )

        march_second_batch = self.client.get(march_second_batch_url)
        self.assertEqual(march_second_batch.status_code, 200)
        self.assertContains(march_second_batch, "Mars · Batch 2")
        self.assertContains(
            march_second_batch,
            "data-tache-two-subject",
            count=5,
        )
        self.assertContains(
            march_second_batch,
            march_second_subject_url,
        )

        march_second_subject = self.client.get(march_second_subject_url)
        self.assertEqual(march_second_subject.status_code, 200)
        self.assertContains(
            march_second_subject,
            "Transports en commun dans une ville",
        )
        self.assertContains(
            march_second_subject,
            "data-tache-two-question",
            count=14,
        )
        self.assertContains(march_second_subject, "30 vocabs")
        self.assertEqual(
            len(march_second_subject.context["vocabulary_batches"]),
            3,
        )

        march_third_batch = self.client.get(march_third_batch_url)
        self.assertEqual(march_third_batch.status_code, 200)
        self.assertContains(march_third_batch, "Mars · Batch 3")
        self.assertContains(
            march_third_batch,
            "data-tache-two-subject",
            count=5,
        )
        self.assertContains(march_third_batch, march_third_subject_url)

        march_third_subject = self.client.get(march_third_subject_url)
        self.assertEqual(march_third_subject.status_code, 200)
        self.assertContains(
            march_third_subject,
            "Présentation d&#x27;un film",
        )
        self.assertContains(
            march_third_subject,
            "data-tache-two-question",
            count=15,
        )
        self.assertContains(march_third_subject, "30 vocabs")

        april_batch = self.client.get(april_batch_url)
        self.assertEqual(april_batch.status_code, 200)
        self.assertContains(april_batch, "Avril · Batch 1")
        self.assertContains(
            april_batch,
            "data-tache-two-subject",
            count=5,
        )
        self.assertContains(april_batch, april_subject_url)

        april_subject = self.client.get(april_subject_url)
        self.assertEqual(april_subject.status_code, 200)
        self.assertContains(
            april_subject,
            "Nouveau centre sportif de la ville",
        )
        self.assertContains(
            april_subject,
            "data-tache-two-question",
            count=15,
        )
        self.assertContains(april_subject, "30 vocabs")
        self.assertEqual(
            len(april_subject.context["vocabulary_batches"]),
            3,
        )

        april_second_batch = self.client.get(april_second_batch_url)
        self.assertEqual(april_second_batch.status_code, 200)
        self.assertContains(april_second_batch, "Avril · Batch 2")
        self.assertContains(
            april_second_batch,
            "data-tache-two-subject",
            count=5,
        )
        self.assertContains(april_second_batch, april_second_subject_url)

        april_second_subject = self.client.get(april_second_subject_url)
        self.assertEqual(april_second_subject.status_code, 200)
        self.assertContains(
            april_second_subject,
            "Vacances au Canada",
        )
        self.assertContains(
            april_second_subject,
            "data-tache-two-question",
            count=15,
        )
        self.assertContains(april_second_subject, "30 vocabs")

        may_batch = self.client.get(may_batch_url)
        self.assertEqual(may_batch.status_code, 200)
        self.assertContains(may_batch, "Mai · Batch 5")
        self.assertContains(
            may_batch,
            "data-tache-two-subject",
            count=6,
        )
        self.assertContains(may_batch, may_subject_url)

        may_subject = self.client.get(may_subject_url)
        self.assertEqual(may_subject.status_code, 200)
        self.assertContains(
            may_subject,
            "Garde d&#x27;un enfant le week-end",
        )
        self.assertContains(
            may_subject,
            "data-tache-two-question",
            count=15,
        )
        self.assertContains(may_subject, "30 vocabs")

        june_batch = self.client.get(june_batch_url)
        self.assertEqual(june_batch.status_code, 200)
        self.assertContains(june_batch, "Juin · Batch 9")
        self.assertContains(
            june_batch,
            "data-tache-two-subject",
            count=5,
        )
        self.assertContains(june_batch, june_subject_url)

        june_subject = self.client.get(june_subject_url)
        self.assertEqual(june_subject.status_code, 200)
        self.assertContains(
            june_subject,
            "École de langues – Renseignements",
        )
        self.assertContains(
            june_subject,
            "data-tache-two-question",
            count=15,
        )
        self.assertContains(june_subject, "30 vocabs")

        july_batch = self.client.get(july_batch_url)
        self.assertEqual(july_batch.status_code, 200)
        self.assertContains(july_batch, "Juillet · Batch 8")
        self.assertContains(
            july_batch,
            "data-tache-two-subject",
            count=5,
        )
        self.assertContains(july_batch, july_subject_url)

        july_subject = self.client.get(july_subject_url)
        self.assertEqual(july_subject.status_code, 200)
        self.assertContains(july_subject, "Choisir une nouvelle série")
        self.assertContains(
            july_subject,
            "data-tache-two-question",
            count=15,
        )
        self.assertContains(july_subject, "30 vocabs")

        august_batch = self.client.get(august_batch_url)
        self.assertEqual(august_batch.status_code, 200)
        self.assertContains(august_batch, "Août · Batch 4")
        self.assertContains(
            august_batch,
            "data-tache-two-subject",
            count=5,
        )
        self.assertContains(august_batch, august_subject_url)

        august_subject = self.client.get(august_subject_url)
        self.assertEqual(august_subject.status_code, 200)
        self.assertContains(
            august_subject,
            "Ville à visiter le temps d&#x27;un week-end",
        )
        self.assertContains(
            august_subject,
            "data-tache-two-question",
            count=15,
        )
        self.assertContains(august_subject, "30 vocabs")

        september_batch = self.client.get(september_batch_url)
        self.assertEqual(september_batch.status_code, 200)
        self.assertContains(september_batch, "Septembre · Batch 7")
        self.assertContains(
            september_batch,
            "data-tache-two-subject",
            count=5,
        )
        self.assertContains(september_batch, september_subject_url)

        september_subject = self.client.get(september_subject_url)
        self.assertEqual(september_subject.status_code, 200)
        self.assertContains(september_subject, "Nouvel emploi à Toronto")
        self.assertContains(
            september_subject,
            "data-tache-two-question",
            count=15,
        )
        self.assertContains(september_subject, "30 vocabs")
        for (
            month_name,
            batch_number,
            _subject_number,
            title,
            question_count,
            batch_route,
            subject_route,
        ) in final_routes:
            final_batch = self.client.get(batch_route)
            self.assertEqual(final_batch.status_code, 200)
            self.assertContains(
                final_batch,
                f"{month_name} · Batch {batch_number}",
            )
            self.assertContains(
                final_batch,
                "data-tache-two-subject",
                count=5,
            )
            self.assertContains(final_batch, subject_route)

            final_subject = self.client.get(subject_route)
            self.assertEqual(final_subject.status_code, 200)
            self.assertContains(final_subject, title)
            self.assertContains(
                final_subject,
                "data-tache-two-question",
                count=question_count,
            )
            self.assertContains(final_subject, "30 vocabs")
            self.assertEqual(
                sum(
                    batch["phrase_count"]
                    for batch in final_subject.context["vocabulary_batches"]
                ),
                30,
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
        theme_vocabulary = Phrase.objects.filter(
            tier=PhraseTier.THEME,
            source_prompts__response_id__in=response_ids,
            is_active=True,
        ).distinct()

        self.assertEqual(responses.count(), 186)
        self.assertEqual(
            Prompt.objects.filter(
                content_key__startswith="tache2:",
                is_active=True,
            ).count(),
            348,
        )
        self.assertEqual(vocabulary.count(), 5580)
        self.assertEqual(theme_vocabulary.count(), 495)
        self.assertEqual(
            Card.objects.filter(
                user=self.user,
                card_type=CardType.SPINE,
                response_id__in=response_ids,
            ).count(),
            186,
        )
        self.assertEqual(
            Card.objects.filter(
                user=self.user,
                card_type=CardType.PHRASE_PRODUCTION,
                phrase__in=vocabulary,
            ).count(),
            5580,
        )
        self.assertEqual(
            Card.objects.filter(
                user=self.user,
                card_type=CardType.PHRASE_PRODUCTION,
                phrase__in=theme_vocabulary,
            ).count(),
            495,
        )
        self.assertFalse(
            Card.objects.filter(
                user=self.user,
                card_type=CardType.PHRASE_RECOGNITION,
                phrase__in=theme_vocabulary,
            ).exists()
        )

        legacy_directory = self.client.get(
            reverse(
                "study:task_phrases",
                args=[self.task.part.slug, self.task.slug],
            )
        )
        self.assertRedirects(
            legacy_directory,
            reverse("study:tache_two_theme_vocabulary"),
            fetch_redirect_response=False,
        )

    def test_repeated_subjects_share_one_deck_and_list_equivalents(self):
        shared_url = reverse(
            "study:task_subject_detail",
            args=[self.task.part.slug, self.task.slug, "mai", 1, 5],
        )
        canonical_url = reverse(
            "study:task_subject_detail",
            args=[self.task.part.slug, self.task.slug, "fevrier", 4, 20],
        )

        shared = self.client.get(shared_url)
        canonical = self.client.get(canonical_url)

        self.assertEqual(shared.status_code, 200)
        self.assertEqual(canonical.status_code, 200)
        self.assertEqual(
            shared.context["response"].pk,
            canonical.context["response"].pk,
        )
        self.assertEqual(
            shared.context["response"].content_key,
            "tache2:fevrier:batch-04:subject-20",
        )
        self.assertEqual(
            shared.context["selected_prompt"].content_key,
            "tache2:mai:batch-01:subject-05",
        )
        self.assertFalse(shared.context["selected_prompt"].is_canonical)
        self.assertTrue(canonical.context["selected_prompt"].is_canonical)
        self.assertEqual(
            [
                (item["month_slug"], item["number"])
                for item in shared.context["equivalent_subjects"]
            ],
            [("fevrier", 20), ("juillet", 15), ("octobre", 50)],
        )
        self.assertEqual(
            [
                (item["month_slug"], item["number"])
                for item in canonical.context["equivalent_subjects"]
            ],
            [("mai", 5), ("juillet", 15), ("octobre", 50)],
        )
        self.assertContains(shared, "Sujets équivalents")
        self.assertContains(shared, canonical_url)
        self.assertEqual(
            [
                question["text"]
                for question in shared.context["subject_questions"]
            ],
            [
                question["text"]
                for question in canonical.context["subject_questions"]
            ],
        )

        completion_url = reverse(
            "study:subject_completion",
            args=[
                self.task.part.slug,
                self.task.slug,
                shared.context["response"].pk,
            ],
        )
        completed = self.client.post(
            completion_url,
            {"completed": "1"},
            HTTP_X_REQUESTED_WITH="fetch",
        )

        self.assertEqual(completed.status_code, 200)
        self.assertEqual(
            self.client.get(canonical_url).context[
                "subject_progress"
            ].status,
            "done",
        )
        self.assertEqual(
            self.client.get(shared_url).context["subject_progress"].status,
            "done",
        )

    def test_equivalent_subjects_share_highlights(self):
        shared_url = reverse(
            "study:task_subject_detail",
            args=[self.task.part.slug, self.task.slug, "mai", 1, 5],
        )
        canonical_url = reverse(
            "study:task_subject_detail",
            args=[self.task.part.slug, self.task.slug, "fevrier", 4, 20],
        )
        created = self.client.post(
            reverse("study:annotation_create"),
            {
                "kind": "highlight",
                "source_path": shared_url,
                "source_key": self.client.get(shared_url).context[
                    "subject_annotation_key"
                ],
                "quote": "Quels types",
                "start_offset": 0,
                "end_offset": 11,
            },
            HTTP_X_REQUESTED_WITH="fetch",
        )

        self.assertEqual(created.status_code, 201)

        listing = self.client.get(
            reverse("study:annotations_for_source"),
            {"source_path": canonical_url},
        )
        payload = listing.json()

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(
            [item["source_key"] for item in payload["highlights"]],
            ["tache-two:fevrier:batch-4:subject-20"],
        )
        self.assertEqual(
            self.client.get(canonical_url).context["subject_annotation_key"],
            "tache-two:fevrier:batch-4:subject-20",
        )
        self.assertEqual(
            self.client.get(shared_url).context["subject_annotation_key"],
            "tache-two:fevrier:batch-4:subject-20",
        )

    def test_migration_moves_alias_highlights_onto_the_shared_key(self):
        shared_url = reverse(
            "study:task_subject_detail",
            args=[self.task.part.slug, self.task.slug, "mai", 1, 5],
        )
        alias = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            source_path=shared_url,
            source_key="tache-two:mai:batch-1:subject-5",
            quote="Quels types",
            start_offset=0,
            end_offset=11,
        )

        annotation_migration.share_tache_two_annotation_keys(apps, None)
        alias.refresh_from_db()

        self.assertEqual(
            alias.source_key,
            "tache-two:fevrier:batch-4:subject-20",
        )

        annotation_migration.restore_per_subject_annotation_keys(apps, None)
        alias.refresh_from_db()

        self.assertEqual(alias.source_key, "tache-two:mai:batch-1:subject-5")

    def test_migration_merges_duplicate_highlights_across_equivalents(self):
        shared_url = reverse(
            "study:task_subject_detail",
            args=[self.task.part.slug, self.task.slug, "mai", 1, 5],
        )
        survivor = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            source_path=shared_url,
            source_key="tache-two:fevrier:batch-4:subject-20",
            quote="Quels types",
            start_offset=0,
            end_offset=11,
        )
        duplicate = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            source_path=shared_url,
            source_key="tache-two:mai:batch-1:subject-5",
            quote="Quels types",
            body="Note à garder",
            start_offset=0,
            end_offset=11,
            study_later=True,
        )
        Annotation.objects.filter(pk=survivor.pk).update(
            updated_at=timezone.now() - timedelta(minutes=1)
        )

        annotation_migration.share_tache_two_annotation_keys(apps, None)
        survivor.refresh_from_db()

        self.assertFalse(Annotation.objects.filter(pk=duplicate.pk).exists())
        self.assertEqual(survivor.body, "Note à garder")
        self.assertTrue(survivor.study_later)

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
        batch = self.client.get(
            reverse(
                "study:task_subject_batch",
                args=[
                    self.task.part.slug,
                    self.task.slug,
                    "janvier",
                    1,
                ],
            )
        )
        directory = self.client.get(
            reverse(
                "study:task_browse",
                args=[self.task.part.slug, self.task.slug],
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

        self.assertEqual(subject.status_code, 200)
        self.assertTrue(subject.context["subject_progress"].has_highlight)
        self.assertEqual(subject.context["subject_progress"].status, "active")
        self.assertEqual(
            batch.context["subject_batch"]["subjects"][0]["progress"].status,
            "active",
        )
        self.assertContains(batch, "tache-two-subject-card--active", count=1)
        themes_by_slug = {
            theme["slug"]: theme
            for theme in directory.context["subject_themes"]
        }
        logement = themes_by_slug["logement"]
        self.assertEqual(logement["progress"].status, "active")
        self.assertEqual(logement["progress"].started, 1)
        active_rows = [
            row
            for row in logement["subjects"]
            if row["progress"].status == "active"
        ]
        self.assertEqual(len(active_rows), 1)
        self.assertContains(directory, "is-status-active")
        self.assertEqual(
            overview.context["subject_summary"]["progress"].status,
            "active",
        )
        overview_themes = {
            theme["slug"]: theme
            for theme in overview.context["subject_summary"]["themes"]
        }
        self.assertEqual(
            overview_themes["logement"]["progress"].status,
            "active",
        )
        task_card = next(
            row
            for row in task_list.context["tasks"]
            if row["task"].pk == self.task.pk
        )
        self.assertEqual(
            task_card["question_bank"]["subject_progress"].status,
            "active",
        )
        self.assertEqual(
            task_card["question_bank"]["progress"].status,
            "active",
        )
        self.assertContains(task_list, "0/348 sujets terminés")

    def test_explicit_subject_completion_rolls_up_through_tache_two(self):
        response = Response.objects.get(
            content_key="tache2:janvier:batch-01:subject-01"
        )
        completion_url = reverse(
            "study:subject_completion",
            args=[self.task.part.slug, self.task.slug, response.pk],
        )

        completed = self.client.post(
            completion_url,
            {"completed": "1"},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        batch = self.client.get(
            reverse(
                "study:task_subject_batch",
                args=[
                    self.task.part.slug,
                    self.task.slug,
                    "janvier",
                    1,
                ],
            )
        )
        directory = self.client.get(
            reverse(
                "study:task_browse",
                args=[self.task.part.slug, self.task.slug],
            )
        )

        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["subject"]["status"], "done")
        first_subject = batch.context["subject_batch"]["subjects"][0]
        self.assertEqual(first_subject["progress"].status, "done")
        self.assertTrue(first_subject["progress"].explicitly_completed)
        self.assertEqual(batch.context["subject_batch"]["completed"], 1)
        self.assertEqual(directory.context["subject_summary"]["completed"], 1)
        self.assertContains(batch, 'aria-checked="true"', count=1)

        cleared = self.client.post(
            completion_url,
            {"completed": "0"},
            HTTP_X_REQUESTED_WITH="fetch",
        )

        self.assertEqual(cleared.json()["subject"]["status"], "new")

    def test_unknown_subject_month_batch_and_number_are_not_found(self):
        route_args = [self.task.part.slug, self.task.slug]
        missing_month = self.client.get(
            reverse(
                "study:task_subject_batch",
                args=[*route_args, "inconnu", 1],
            )
        )
        missing_batch = self.client.get(
            reverse(
                "study:task_subject_batch",
                args=[*route_args, "janvier", 4],
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

    def test_theme_vocabulary_detail_groups_contextual_entries(self):
        response = self.client.get(
            reverse(
                "study:tache_two_theme_vocabulary_detail",
                args=["logement"],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "study/tache_two_theme_vocabulary_detail.html",
        )
        self.assertEqual(response.context["theme_data"].slug, "logement")
        self.assertEqual(response.context["phrase_count"], 45)
        self.assertEqual(
            [len(section["phrases"]) for section in response.context["phrase_sections"]],
            [15, 15, 15],
        )
        self.assertEqual(len(response.context["review_batches"]), 3)
        self.assertEqual(
            [batch["title"] for batch in response.context["review_batches"]],
            ["Mots clés", "Expressions utiles", "Fragments de phrase"],
        )
        self.assertContains(
            response,
            "class=\"phrase card theme-vocabulary-phrase",
            count=45,
        )
        self.assertContains(
            response,
            "data-theme-vocabulary-progress-form",
            count=45,
        )
        self.assertContains(response, "data-read-aloud-key=", count=45)
        self.assertContains(response, 'role="checkbox"', count=45)
        learned_summary = response.context["learned_summary"]
        self.assertEqual(learned_summary.completed, 0)
        self.assertEqual(learned_summary.total, 45)
        self.assertContains(response, "Mots clés")
        self.assertContains(response, "Expressions utiles")
        self.assertContains(response, "Fragments de phrase")
        self.assertContains(response, "Lot 01 · Mots clés")
        self.assertContains(response, "data-theme-vocabulary-recall")
        self.assertContains(
            response,
            'data-recall-controls="theme-vocabulary-recall-catalog"',
            count=1,
        )
        self.assertContains(response, "data-recall-catalog", count=1)
        self.assertContains(
            response,
            'data-theme-vocabulary-recall-column="french"',
            count=1,
        )
        self.assertContains(
            response,
            'data-theme-vocabulary-recall-column="meaning"',
            count=1,
        )
        self.assertContains(
            response,
            'data-theme-vocabulary-recall-cell="french"',
            count=45,
        )
        self.assertContains(
            response,
            'data-theme-vocabulary-recall-cell="meaning"',
            count=45,
        )
        self.assertContains(
            response,
            'data-recall-cell="french"',
            count=45,
        )
        self.assertContains(
            response,
            'data-recall-cell="meaning"',
            count=45,
        )
        self.assertNotContains(response, "Repères pour les noms")
        self.assertNotContains(response, "Registre :")
        self.assertNotContains(response, "Mémoires")

    def test_theme_vocabulary_learned_marker_is_visual_only(self):
        detail_url = reverse(
            "study:tache_two_theme_vocabulary_detail",
            args=["logement"],
        )
        detail = self.client.get(detail_url)
        phrase = detail.context["phrase_sections"][0]["phrases"][0]
        card = Card.objects.get(
            user=self.user,
            phrase=phrase,
            card_type=CardType.PHRASE_PRODUCTION,
        )
        progress_url = reverse(
            "study:tache_two_theme_vocabulary_progress",
            args=["logement", phrase.pk],
        )

        marked = self.client.post(
            progress_url,
            {"completed": "1"},
            HTTP_X_REQUESTED_WITH="fetch",
        )

        self.assertEqual(marked.status_code, 200)
        self.assertEqual(
            marked.json(),
            {
                "completed": True,
                "phrase_id": phrase.phrase_id,
                "learned": 1,
                "total": 45,
            },
        )
        self.assertTrue(
            ThemeVocabularyProgress.objects.filter(
                user=self.user,
                phrase=phrase,
            ).exists()
        )
        card.refresh_from_db()
        self.assertEqual(card.state, CardState.NEW)
        refreshed = self.client.get(detail_url)
        self.assertContains(
            refreshed,
            f'id="phrase-{phrase.phrase_id}"',
        )
        self.assertContains(refreshed, 'aria-checked="true"', count=1)
        learned_summary = refreshed.context["learned_summary"]
        self.assertEqual(learned_summary.completed, 1)
        self.assertEqual(learned_summary.total, 45)

        # Explicit values make retries idempotent.
        self.client.post(
            progress_url,
            {"completed": "1"},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertEqual(
            ThemeVocabularyProgress.objects.filter(
                user=self.user,
                phrase=phrase,
            ).count(),
            1,
        )

        unmarked = self.client.post(progress_url, {"completed": "0"})
        self.assertEqual(
            unmarked.url,
            detail_url + f"#phrase-{phrase.phrase_id}",
        )
        self.assertFalse(
            ThemeVocabularyProgress.objects.filter(
                user=self.user,
                phrase=phrase,
            ).exists()
        )

    def test_theme_vocabulary_progress_validates_value_and_theme(self):
        logement = self.client.get(
            reverse(
                "study:tache_two_theme_vocabulary_detail",
                args=["logement"],
            )
        )
        logement_phrase = logement.context["phrase_sections"][0]["phrases"][0]
        wrong_theme = self.client.get(
            reverse(
                "study:tache_two_theme_vocabulary_detail",
                args=["travail"],
            )
        )
        travail_phrase = wrong_theme.context["phrase_sections"][0]["phrases"][0]

        invalid = self.client.post(
            reverse(
                "study:tache_two_theme_vocabulary_progress",
                args=["logement", logement_phrase.pk],
            ),
            {"completed": "oui"},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        unrelated = self.client.post(
            reverse(
                "study:tache_two_theme_vocabulary_progress",
                args=["logement", travail_phrase.pk],
            ),
            {"completed": "1"},
        )

        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(
            invalid.json(),
            {"error": "État d’apprentissage invalide."},
        )
        self.assertEqual(unrelated.status_code, 404)
        self.assertFalse(ThemeVocabularyProgress.objects.exists())

    def test_theme_vocabulary_review_keeps_its_theme_and_returns_to_it(self):
        detail_url = reverse(
            "study:tache_two_theme_vocabulary_detail",
            args=["logement"],
        )
        detail = self.client.get(detail_url)
        review = self.client.get(
            detail.context["review_batches"][0]["review_url"]
        )
        state = self.client.get(reverse("study:review_next")).json()

        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.context["scope"]["kind"], "theme_vocab")
        self.assertEqual(review.context["active_nav_area"], "expression")
        self.assertEqual(
            review.context["scope"]["theme"],
            "tache-2-logement",
        )
        self.assertEqual(review.context["batch_index_url"], detail_url)
        self.assertIn("Vocabulaire du thème", state["front_html"])
        self.assertIn("Réponse française", state["back_html"])

    def test_mixed_theme_vocabulary_review_returns_to_its_theme(self):
        detail_url = reverse(
            "study:tache_two_theme_vocabulary_detail",
            args=["logement"],
        )
        detail = self.client.get(detail_url)
        theme = self.task.themes.get(slug="tache-2-logement")
        Card.objects.filter(
            user=self.user,
            phrase__tier=PhraseTier.THEME,
            phrase__source_prompts__theme=theme,
        ).update(
            state=CardState.REVIEW,
            due=timezone.now() + timedelta(days=30),
        )

        review = self.client.get(detail.context["mixed_review_url"])

        self.assertEqual(review.context["collection_return_url"], detail_url)
        self.assertContains(review, f'href="{detail_url}"')
        self.assertContains(review, "Retour au vocabulaire par thème")

    def test_legacy_memory_urls_redirect_and_unknown_theme_is_not_found(self):
        legacy_index = self.client.get(
            reverse(
                "study:task_memories",
                args=[self.task.part.slug, self.task.slug],
            )
        )
        legacy_detail = self.client.get(
            reverse(
                "study:task_memory_detail",
                args=[self.task.part.slug, self.task.slug, 12],
            )
        )
        missing_theme = self.client.get(
            reverse(
                "study:tache_two_theme_vocabulary_detail",
                args=["theme-inconnu"],
            )
        )
        unrelated = self.client.get(
            reverse(
                "study:task_memory_detail",
                args=[self.task.part.slug, "tache-3", 1],
            )
        )
        unrelated_index = self.client.get(
            reverse(
                "study:task_memories",
                args=[self.task.part.slug, "tache-3"],
            )
        )

        self.assertRedirects(
            legacy_index,
            reverse("study:tache_two_theme_vocabulary"),
        )
        self.assertRedirects(
            legacy_detail,
            reverse("study:tache_two_theme_vocabulary"),
        )
        self.assertEqual(missing_theme.status_code, 404)
        self.assertEqual(unrelated.status_code, 404)
        self.assertEqual(unrelated_index.status_code, 404)

    def test_every_theme_vocabulary_detail_is_available(self):
        index = self.client.get(reverse("study:tache_two_theme_vocabulary"))

        for item in index.context["themes"]:
            detail = self.client.get(item["url"])

            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.context["theme_data"], item["data"])
            self.assertEqual(detail.context["phrase_count"], 45)
            self.assertEqual(
                [len(section["phrases"]) for section in detail.context["phrase_sections"]],
                [15, 15, 15],
            )
            self.assertEqual(len(detail.context["review_batches"]), 3)

    def test_task_card_describes_subjects_and_theme_vocabulary(self):
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
            "348 sujets · 11 thèmes · 495 fiches de vocabulaire",
        )
        self.assertContains(response, "0/33 lots terminés")
        self.assertContains(response, "0/348 sujets terminés")
        self.assertContains(response, "À commencer")
        task_card = next(
            row
            for row in response.context["tasks"]
            if row["task"].pk == self.task.pk
        )
        self.assertEqual(task_card["question_bank"]["progress"].total, 381)
        self.assertEqual(
            task_card["question_bank"]["vocabulary_progress"].total,
            33,
        )
        self.assertEqual(
            task_card["question_bank"]["subject_progress"].total,
            348,
        )

    def test_theme_vocabulary_progress_rolls_up_to_every_entry_point(self):
        theme = self.task.themes.get(slug="tache-2-logement")
        first_lot_phrase_ids = list(
            Phrase.objects.filter(
                tier=PhraseTier.THEME,
                source_prompts__theme=theme,
            )
            .order_by("lot_order")
            .values_list("pk", flat=True)[:15]
        )
        Card.objects.filter(
            user=self.user,
            phrase_id__in=first_lot_phrase_ids,
            card_type=CardType.PHRASE_PRODUCTION,
        ).update(state=CardState.LEARNING)

        detail = self.client.get(
            reverse(
                "study:tache_two_theme_vocabulary_detail",
                args=["logement"],
            )
        )
        directory = self.client.get(
            reverse("study:tache_two_theme_vocabulary")
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
        directory_item = next(
            item
            for item in directory.context["themes"]
            if item["data"].slug == "logement"
        )
        task_card = next(
            item
            for item in task_list.context["tasks"]
            if item["task"].pk == self.task.pk
        )

        self.assertEqual(detail.context["summary"]["completed"], 1)
        self.assertEqual(directory_item["summary"]["completed"], 1)
        self.assertEqual(
            overview.context["theme_vocabulary"]["summary"]["completed"],
            1,
        )
        self.assertEqual(
            task_card["question_bank"]["vocabulary_progress"].completed,
            1,
        )
        self.assertContains(task_list, "1/33 lots terminés")

    def test_legacy_memory_progress_post_does_not_create_progress(self):
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
            reverse("study:tache_two_theme_vocabulary"),
        )
        self.assertFalse(MemoryQuestionProgress.objects.exists())

    def test_account_export_and_reset_include_manual_progress(self):
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
        phrase = Phrase.objects.filter(tier=PhraseTier.THEME).first()
        own_theme_progress = ThemeVocabularyProgress.objects.create(
            user=self.user,
            phrase=phrase,
        )
        other_theme_progress = ThemeVocabularyProgress.objects.create(
            user=other_user,
            phrase=phrase,
        )
        response = Response.objects.filter(
            content_key__startswith="tache2:"
        ).first()
        completed_at = timezone.now()
        own_card = Card.objects.get(
            user=self.user,
            card_type=CardType.SPINE,
            response=response,
        )
        own_card.subject_completed_at = completed_at
        own_card.save(update_fields=["subject_completed_at"])
        other_card = Card.objects.create(
            user=other_user,
            card_type=CardType.SPINE,
            response=response,
            subject_completed_at=completed_at,
        )

        exported = self.client.get(reverse("study:export_account")).json()

        self.assertEqual(exported["version"], 5)
        self.assertEqual(
            exported["memory_question_progress"][0]["question_key"],
            own_progress.question_key,
        )
        self.assertEqual(len(exported["memory_question_progress"]), 1)
        self.assertEqual(
            exported["theme_vocabulary_progress"][0]["phrase_id"],
            phrase.phrase_id,
        )
        self.assertEqual(len(exported["theme_vocabulary_progress"]), 1)
        exported_card = next(
            card
            for card in exported["cards"]
            if card["response_key"] == response.content_key
        )
        self.assertIsNotNone(exported_card["subject_completed_at"])

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
        self.assertFalse(
            ThemeVocabularyProgress.objects.filter(
                pk=own_theme_progress.pk
            ).exists()
        )
        self.assertTrue(
            ThemeVocabularyProgress.objects.filter(
                pk=other_theme_progress.pk
            ).exists()
        )
        own_card.refresh_from_db()
        other_card.refresh_from_db()
        self.assertIsNone(own_card.subject_completed_at)
        self.assertEqual(other_card.subject_completed_at, completed_at)
