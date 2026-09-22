import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils.html import escape

from study import content_loader as content
from study.models import (
    Annotation,
    AnnotationKind,
    MemoryQuestionProgress,
    PersonalQuestionResponse,
)
from study.views.library import _memory_sections

from . import factories


# Ordered French source and content-key fingerprints from before translations.
BASELINE = {
    1: (
        323,
        "91aea4c42d962fbe473586b40d1a8d12ee96294f981df8ebed1f26803fbc2fd9",
        "2511bacdda3540005f20a1762b040d6180d0930b1b4caaffaadf828b8900ddfd",
    ),
    2: (
        315,
        "cb4a0792e93aa8267d0ae3d7fde2cd9ea961f24578d66c4ef84f564abde47bb5",
        "d0502756da6e7f7b9e8af3ca369e4d2d0dd2b9ac4a4f1ac941371bf20429a2a1",
    ),
    3: (
        338,
        "f778f1efd96cd56f8d9940bd555941572d2dca12315cf9082bb0d75524ad9b95",
        "0e5b9dee1533ffd5351f1347ff314721c65220f5af3043d2d5d74747fdbebe24",
    ),
    4: (
        310,
        "26295f845d093c24a9b3e708af44b236dacc401cae06df245a21adaaa4094d8d",
        "6c904362af0395a80268931b40d808e354f436ec970d29b704da526184b793cf",
    ),
}
BASELINE_ROOT_TEXT = {
    1: "eb81439f71133137b1b89d24960fadf87dc9c41e928f88eb197da1988d8809da",
    2: "17d17d4de63fdff2e56a269c248e6290b5b20df8a145e84aa8c53d565c7ae41d",
    3: "0b1e9a2b5bf0ad70366b5b08d92041eb39176854a01172d110f6890209485c0a",
    4: "3bf26d5d22e71ae16be73f7b0417265a8b7d394e4238102193ccd94063345dd9",
}
APPROVED_CORRECTIONS = {
    (1, 10, 1, 11): (
        "une alimentation moins grasse et variée",
        "une alimentation variée et moins grasse",
    ),
    (2, 3, 2, 8): (
        "Les deux documents s’inquiètent de … Toutefois, une position opposée rappelle que …",
        "Les deux documents expriment une inquiétude concernant … Le premier insiste sur … De son côté, le second souligne …",
    ),
    (2, 10, 3, 7): (
        "l’accès aux enquêteurs autorisés",
        "l’accès réservé aux enquêteurs autorisés",
    ),
    (3, 10, 2, 7): (
        "une étude gratuite",
        "une séance gratuite d’étude surveillée",
    ),
    (3, 10, 5, 10): (
        "des profils infantiles",
        "des profils d’enfants",
    ),
    (3, 10, 7, 10): (
        "une réservation horaire",
        "une réservation sur un créneau horaire",
    ),
}


def _banks():
    return content.load_question_banks(
        content.EE_TACHE_THREE_MEMOIRES_DIR,
        key_namespace="ee-tache3",
    )


class AnnotationRootText(HTMLParser):
    """Collect the exact text stream used by French annotation offsets."""

    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    }

    def __init__(self, legacy=False):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.roots = {}
        self.legacy = legacy

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        key = attrs.get("data-annotation-source-key", "")
        if key:
            self.roots[key] = ""
        if tag not in self.VOID_TAGS:
            excluded = "data-annotation-exclude" in attrs
            if self.legacy and "data-annotation-legacy-text" in attrs:
                if not excluded:
                    self.handle_data(attrs["data-annotation-legacy-text"])
                excluded = True
            self.stack.append((tag, key, excluded))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if any(excluded for _, _, excluded in self.stack):
            return
        for _, key, _ in self.stack:
            if key:
                self.roots[key] += data


class EeTacheThreeMemoryTranslationContentTests(SimpleTestCase):
    def test_every_formulation_has_consistent_authored_english(self):
        translations = {}
        total = 0
        for bank in _banks():
            self.assertEqual(bank.question_count, BASELINE[bank.number][0])
            for section in bank.sections:
                for group in section.groups:
                    for question in group.questions:
                        with self.subTest(bank=bank.number, text=question.text):
                            self.assertTrue(question.english.strip())
                            self.assertNotEqual(question.text, question.english)
                            self.assertEqual(
                                question.text.count("…"),
                                question.english.count("…"),
                            )
                            previous = translations.setdefault(
                                question.text, question.english
                            )
                            self.assertEqual(previous, question.english)
                        total += 1
        self.assertEqual(total, 1286)
        self.assertEqual(len(translations), 977)
        self.assertEqual(
            translations["… : un service à encadrer"],
            "…: a service that needs regulation",
        )
        self.assertEqual(translations["l’esprit critique"], "critical thinking")
        self.assertEqual(translations["… garantit à …"], "… guarantees …")

    def test_original_french_metadata_order_and_content_keys_are_preserved(self):
        for bank in _banks():
            with self.subTest(bank=bank.number):
                raw = json.loads(
                    (
                        content.EE_TACHE_THREE_MEMOIRES_DIR
                        / f"memoire_{bank.number}.json"
                    ).read_text(encoding="utf-8")
                )
                for section in raw["sections"]:
                    for group in section["groups"]:
                        group["questions"] = [
                            question.get("legacy_text", question["text"])
                            for question in group["questions"]
                        ]
                french_digest = hashlib.sha256(
                    json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest()
                key_digest = hashlib.sha256(
                    "\n".join(bank.question_keys).encode()
                ).hexdigest()
                self.assertEqual(french_digest, BASELINE[bank.number][1])
                self.assertEqual(key_digest, BASELINE[bank.number][2])
                prefix = "question-bank:ee-tache3"
                if bank.number != 1:
                    prefix += f":memory-{bank.number:02d}"
                self.assertEqual(bank.annotation_key_prefix, prefix)

    def test_only_six_approved_french_items_are_corrected(self):
        corrections = {}
        for bank in _banks():
            for section in bank.sections:
                for group_number, group in enumerate(section.groups, 1):
                    for question_number, question in enumerate(group.questions, 1):
                        if question.legacy_text:
                            location = (
                                bank.number, section.number,
                                group_number, question_number,
                            )
                            corrections[location] = (
                                question.legacy_text, question.text
                            )
        self.assertEqual(corrections, APPROVED_CORRECTIONS)

    def _load_rows(self, rows):
        raw = {
            "number": 1,
            "title": "Mémoire",
            "label": "Formulations",
            "icon": "book-open",
            "subtitle": "Réutiliser",
            "sections": [{
                "number": 1,
                "title": "Arguments",
                "groups": [{"questions": rows}],
            }],
        }
        with patch.object(Path, "read_text", return_value=json.dumps(raw)):
            return content.load_question_bank(Path("unused.json"))

    def test_strings_and_existing_question_objects_remain_supported(self):
        bank = self._load_rows([
            "Une formulation.",
            {"text": "Une autre.", "note": "À adapter."},
            {"text": "Un exemple.", "english": " An example. "},
        ])
        plain, noted, bilingual = bank.sections[0].groups[0].questions
        self.assertEqual((plain.text, plain.note, plain.english),
                         ("Une formulation.", "", ""))
        self.assertEqual((noted.note, noted.english), ("À adapter.", ""))
        self.assertEqual(bilingual.english, "An example.")
        self.assertEqual(
            self._load_rows(["Un exemple."]).question_keys,
            self._load_rows([{
                "text": "Un exemple.", "english": "Another translation."
            }]).question_keys,
        )

    def test_invalid_english_types_are_rejected(self):
        for english in (None, 7, [], {"en": "An example."}):
            with self.subTest(english=english):
                with self.assertRaisesMessage(ValueError, "invalid English"):
                    self._load_rows([{"text": "Un exemple.", "english": english}])

    def test_legacy_identity_seed_keeps_old_keys_and_rejects_collisions(self):
        original = self._load_rows(["Une ancienne formulation."])
        corrected = self._load_rows([{
            "text": "Une formulation corrigée.",
            "legacy_text": "Une ancienne formulation.",
        }])
        self.assertEqual(original.question_keys, corrected.question_keys)
        key = original.question_keys[0]
        row = _memory_sections(
            corrected, {key}, {key: "Ma réponse avant la correction."}
        )[0]["groups"][0]["questions"][0]
        self.assertTrue(row["completed"])
        self.assertEqual(row["response"], "Ma réponse avant la correction.")
        self.assertEqual(row["text"], "Une formulation corrigée.")
        for value in (None, 7, [], {}, "", "  "):
            with self.subTest(value=value):
                with self.assertRaisesMessage(ValueError, "invalid legacy text"):
                    self._load_rows([{"text": "Un exemple.", "legacy_text": value}])
        with self.assertRaisesMessage(ValueError, "Duplicate question-bank identity"):
            self._load_rows([
                "Une ancienne formulation.",
                {"text": "Une formulation corrigée.",
                 "legacy_text": "Une ancienne formulation."},
            ])

    def test_memory_context_preserves_completion_notes_and_personal_responses(self):
        bank = self._load_rows([{
            "text": "Un exemple.",
            "note": "À adapter.",
            "english": "An example.",
        }])
        key = bank.question_keys[0]
        sections = _memory_sections(bank, {key}, {key: "Ma réponse inchangée."})
        question = sections[0]["groups"][0]["questions"][0]
        self.assertEqual(question, {
            "content_key": key,
            "text": "Un exemple.",
            "note": "À adapter.",
            "english": "An example.",
            "legacy_text": "",
            "completed": True,
            "response": "Ma réponse inchangée.",
        })
        self.assertEqual(sections[0]["progress"].completed, 1)


class EeTacheThreeMemoryTranslationViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = factories.make_user("ee3-memory-english")
        cls.task = factories.make_task(factories.make_part("ee"), "tache-3")

    def setUp(self):
        self.client.force_login(self.user)

    def _url(self, bank):
        return reverse("study:task_memory_detail", args=["ee", "tache-3", bank.number])

    def test_all_four_pages_render_paired_language_tagged_formulations(self):
        for bank in _banks():
            with self.subTest(bank=bank.number):
                response = self.client.get(self._url(bank))
                self.assertEqual(response.status_code, 200)
                self.assertContains(
                    response, 'class="question-bank-question__translation"',
                    count=bank.question_count,
                )
                self.assertContains(response, 'lang="en" data-annotation-exclude',
                                    count=bank.question_count)
                self.assertContains(response, '<p lang="fr"',
                                    count=bank.question_count)
                self.assertContains(
                    response,
                    'class="ee3-memory-guide card"',
                    count=1,
                )
                self.assertContains(
                    response,
                    'id="writing-methodology-dialog"',
                    count=1,
                )
                self.assertContains(
                    response,
                    'aria-label="Catégories de formulations"',
                    count=1,
                )
                self.assertContains(response, "formulations apprises", count=1)
                self.assertNotContains(response, "questions apprises")
                parser = AnnotationRootText(legacy=True)
                parser.feed(response.content.decode())
                self.assertEqual(len(parser.roots), 10)
                self.assertEqual(
                    hashlib.sha256(json.dumps(
                        parser.roots, ensure_ascii=False, sort_keys=True
                    ).encode()).hexdigest(),
                    BASELINE_ROOT_TEXT[bank.number],
                )
                self.assertContains(
                    response, "data-annotation-legacy-text=",
                    count=sum(key[0] == bank.number for key in APPROVED_CORRECTIONS),
                )
                for section in bank.sections:
                    self.assertContains(
                        response,
                        f'data-annotation-source-key="{bank.annotation_key_prefix}'
                        f':part-{section.number_label}"',
                        count=1,
                    )
                    for group in section.groups:
                        for question in group.questions:
                            self.assertContains(response, escape(question.text))
                            self.assertContains(response, escape(question.english))

    def test_all_1286_original_completion_keys_restore_after_corrections(self):
        banks = _banks()
        records = []
        for bank in banks:
            for section in bank.sections:
                for group in section.groups:
                    for question in group.questions:
                        seed = question.legacy_text or question.text
                        original_key = (
                            f"memory:ee-tache3:{bank.number}:question:"
                            + hashlib.sha256(seed.casefold().encode()).hexdigest()
                        )
                        self.assertEqual(question.content_key, original_key)
                        records.append(MemoryQuestionProgress(
                            user=self.user, memory_number=bank.number,
                            question_key=original_key,
                        ))
        MemoryQuestionProgress.objects.bulk_create(records)
        self.assertEqual(MemoryQuestionProgress.objects.count(), 1286)
        for bank in banks:
            with self.subTest(bank=bank.number):
                response = self.client.get(self._url(bank))
                self.assertEqual(
                    response.context["memory_progress"].completed,
                    bank.question_count,
                )
                self.assertContains(response, 'class="is-complete"',
                                    count=bank.question_count)
                self.assertTrue(all(
                    question["completed"]
                    for section in response.context["memory_sections"]
                    for group in section["groups"]
                    for question in group["questions"]
                ))

    def test_saved_learning_state_responses_and_highlights_remain_intact(self):
        bank = _banks()[0]
        question = bank.sections[0].groups[0].questions[2]
        completed = MemoryQuestionProgress.objects.create(
            user=self.user, memory_number=bank.number,
            question_key=question.content_key,
        )
        personal = PersonalQuestionResponse.objects.create(
            user=self.user, task=self.task, question_key=question.content_key,
            body="Une réponse personnelle déjà enregistrée.",
        )
        response = self.client.get(self._url(bank))
        parser = AnnotationRootText()
        parser.feed(response.content.decode())
        source_key = f"{bank.annotation_key_prefix}:part-01"
        french_root = parser.roots[source_key]
        start = french_root.index(question.text)
        highlight = Annotation.objects.create(
            user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
            source_path=self._url(bank), source_key=source_key,
            quote=question.text, start_offset=start,
            end_offset=start + len(question.text),
            prefix=french_root[max(0, start - 160):start],
            suffix=french_root[start + len(question.text):][:160],
        )
        before = (
            completed.completed_at, personal.body, personal.updated_at,
            highlight.source_key, highlight.quote, highlight.start_offset,
            highlight.end_offset, highlight.prefix, highlight.suffix,
        )
        response = self.client.get(self._url(bank))
        self.assertContains(response, 'class="is-complete"')
        self.assertEqual(response.context["memory_progress"].completed, 1)
        highlights = self.client.get(
            reverse("study:annotations_for_source"),
            {"source_path": self._url(bank)},
        ).json()["highlights"]
        self.assertEqual(len(highlights), 1)
        self.assertEqual(highlights[0]["source_key"], source_key)
        self.assertEqual(highlights[0]["start_offset"], start)
        completed.refresh_from_db()
        personal.refresh_from_db()
        highlight.refresh_from_db()
        self.assertEqual(before, (
            completed.completed_at, personal.body, personal.updated_at,
            highlight.source_key, highlight.quote, highlight.start_offset,
            highlight.end_offset, highlight.prefix, highlight.suffix,
        ))
