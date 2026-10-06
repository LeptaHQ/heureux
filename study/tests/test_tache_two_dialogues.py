from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import FrozenInstanceError, asdict, replace
from html import unescape
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils.html import escape

from study import catalogue
from study import content_loader as content
from study.forms import TacheTwoConversationForm
from study.models import Annotation, AnnotationKind, Card, CardType, PersonalResponse, Prompt
from study.oral_highlights import AnnotationRootText, QuestionText, _render_questions
from study.oral_history import variant_annotation_key
from study.response_personalization import effective_response
from study.routing import prompt_detail_url
from study.tache_two_dialogues import (
    DIALOGUES_DIR,
    DialogueQuestion,
    TacheTwoDialogue,
    dialogue_response,
    load_tache_two_dialogues,
    prompt_note_presentation,
    question_presentation,
)

from . import factories


def first_dialogue_fixture():
    row = json.loads((DIALOGUES_DIR / "dialogues_01.json").read_text())["dialogues"][0]
    return TacheTwoDialogue(
        row["group"], row["register"], row["note"], row["opening"], row["closing"],
        tuple(
            DialogueQuestion(
                question["topic"], question["question"], question["answer"],
                question["follow_up_to"], question.get("condition", ""),
            )
            for question in row["questions"]
        ),
    )


class TacheTwoDialogueLoaderTests(SimpleTestCase):
    def setUp(self):
        self.data = json.loads((DIALOGUES_DIR / "dialogues_01.json").read_text())
        self.data["dialogues"] = self.data["dialogues"][:1]
        self.row = self.data["dialogues"][0]
        self.source_month = content.load_tache_two_subject_months()[0]
        self.months = (
            replace(
                self.source_month,
                batches=(
                    replace(
                        self.source_month.batches[0],
                        subjects=self.source_month.batches[0].subjects[:1],
                    ),
                ),
            ),
        )
        self.manifest = json.loads(
            content.ORAL_SEMANTIC_GROUP_PATHS["eo/tache-2"].read_text()
        )
        self.manifest["groups"] = self.manifest["groups"][:1]
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "dialogues"
        self.directory.mkdir()
        self.semantic_path = Path(self.temporary.name) / "groups.json"

    def load(self, document=None):
        (self.directory / "dialogues.json").write_text(
            document if document is not None else json.dumps(self.data),
            encoding="utf-8",
        )
        self.semantic_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        return load_tache_two_dialogues(
            self.directory, months=self.months, semantic_path=self.semantic_path,
        )

    def test_records_and_question_collections_are_immutable(self):
        records = self.load()
        dialogue = records[self.manifest["groups"][0]["canonical"]]
        self.assertEqual(len(dialogue.questions), 8)
        self.assertIsInstance(dialogue.questions, tuple)
        with self.assertRaises(FrozenInstanceError):
            dialogue.note = "Changed"
        with self.assertRaises(FrozenInstanceError):
            dialogue.questions[0].question = "Changed?"

    def test_published_response_never_exports_editorial_answers(self):
        dialogue = next(iter(self.load().values()))
        value = dialogue_response(dialogue)
        self.assertEqual(
            [argument.idea for argument in value.arguments],
            [question.question for question in dialogue.questions],
        )
        self.assertTrue(all(argument.developpement == "" for argument in value.arguments))
        self.assertEqual(value.reformulation, dialogue.opening)
        self.assertEqual(value.conclusion, dialogue.closing)
        exported = json.dumps(asdict(value), ensure_ascii=False)
        for question in dialogue.questions:
            self.assertNotIn(question.answer, exported)

    def test_rejects_non_integer_version(self):
        self.data["version"] = True
        with self.assertRaisesRegex(ValueError, "version 1"):
            self.load()

    def test_rejects_duplicate_json_fields(self):
        document = '{"version":1,"version":1,"dialogues":' + json.dumps(
            self.data["dialogues"]
        ) + "}"
        with self.assertRaisesRegex(ValueError, "[Dd]uplicate"):
            self.load(document)

    def test_rejects_unknown_or_duplicate_groups(self):
        original = copy.deepcopy(self.row)
        self.row["group"] = "unpublished-situation"
        with self.assertRaisesRegex(ValueError, "unknown or duplicate"):
            self.load()
        self.data["dialogues"] = [original, copy.deepcopy(original)]
        with self.assertRaisesRegex(ValueError, "unknown or duplicate"):
            self.load()

    def test_requires_every_semantic_group(self):
        self.months = (
            replace(
                self.source_month,
                batches=(
                    replace(
                        self.source_month.batches[0],
                        subjects=self.source_month.batches[0].subjects[:2],
                    ),
                ),
            ),
        )
        self.manifest["groups"] = json.loads(
            content.ORAL_SEMANTIC_GROUP_PATHS["eo/tache-2"].read_text()
        )["groups"][:2]
        with self.assertRaisesRegex(ValueError, "Missing reviewed EO2 dialogues"):
            self.load()

    def test_requires_eight_questions_including_followups(self):
        original = copy.deepcopy(self.row["questions"])
        for count in (7, 9):
            with self.subTest(count=count):
                self.row["questions"] = (original + original)[:count]
                with self.assertRaisesRegex(ValueError, "exactly eight"):
                    self.load()

    def test_rejects_duplicate_or_incomplete_questions(self):
        original = self.row["questions"][2]["question"]
        self.row["questions"][2]["question"] = self.row["questions"][1]["question"]
        with self.assertRaisesRegex(ValueError, "repeats a question"):
            self.load()
        for text in ("Une phrase sans question.", "Une question ? Encore une ?"):
            self.row["questions"][2]["question"] = text
            with self.assertRaisesRegex(ValueError, "one complete question"):
                self.load()
        self.row["questions"][2]["question"] = original

    def test_followup_requires_a_short_condition(self):
        question = self.row["questions"][1]
        for condition in (None, "", "word " * 15):
            with self.subTest(condition=condition):
                question["condition"] = condition
                with self.assertRaises(ValueError):
                    self.load()
        question.pop("condition")
        with self.assertRaisesRegex(ValueError, "follow-up condition"):
            self.load()

    def test_primary_question_cannot_have_a_followup_condition(self):
        self.row["questions"][0]["condition"] = "If useful."
        with self.assertRaisesRegex(ValueError, "condition without a follow-up"):
            self.load()

    def test_followup_must_reference_an_earlier_question_in_the_same_topic(self):
        for reference in (False, 0, 2, 99):
            with self.subTest(reference=reference):
                self.row["questions"][1]["follow_up_to"] = reference
                with self.assertRaisesRegex(ValueError, "invalid follow-up reference"):
                    self.load()
        self.row["questions"][1]["follow_up_to"] = 1
        self.row["questions"][-1].update(
            follow_up_to=1, condition="After the first question.",
        )
        with self.assertRaisesRegex(ValueError, "invalid follow-up reference"):
            self.load()

    def test_topics_cannot_reappear_after_another_block(self):
        self.row["questions"][-1]["topic"] = self.row["questions"][0]["topic"]
        with self.assertRaisesRegex(ValueError, "contiguous"):
            self.load()

    def test_requires_two_to_four_topics_and_a_followup(self):
        original = copy.deepcopy(self.row["questions"])
        for question in self.row["questions"]:
            question["topic"] = "Un seul thème"
        with self.assertRaisesRegex(ValueError, "two to four"):
            self.load()
        self.row["questions"] = original
        for question in self.row["questions"]:
            question["follow_up_to"] = None
            question.pop("condition", None)
        with self.assertRaisesRegex(ValueError, "response-grounded follow-up"):
            self.load()

    def test_editorial_replies_must_stay_short_and_not_ask_questions(self):
        for text in ("Et vous ?", "word " * 36, "Un. Deux. Trois."):
            with self.subTest(text=text):
                self.row["questions"][0]["answer"] = text
                with self.assertRaises(ValueError):
                    self.load()

    def test_requires_a_separate_greeting_and_final_thanks(self):
        original_opening = self.row["opening"]
        self.row["opening"] = "Bonjour, comment allez-vous ?"
        with self.assertRaisesRegex(ValueError, "separate opening and final thanks"):
            self.load()
        self.row["opening"] = original_opening
        self.row["closing"] = "À bientôt."
        with self.assertRaisesRegex(ValueError, "separate opening and final thanks"):
            self.load()

    def test_publication_note_must_belong_to_its_group(self):
        self.row["notes"] = {"tache2:unknown:batch-01:subject-01": "Use vous."}
        with self.assertRaisesRegex(ValueError, "own prompt publications"):
            self.load()

    def test_question_only_component_is_shared_and_answers_are_absent(self):
        dialogue = next(iter(self.load().values()))
        prompt = SimpleNamespace(content_key=self.manifest["groups"][0]["canonical"])
        value = dialogue_response(dialogue)
        with patch("study.tache_two_dialogues.published_dialogue", return_value=dialogue):
            context = {
                **question_presentation(prompt, value),
                "response_content": value,
                "task": SimpleNamespace(pk=1),
                "subject_annotation_key": "question-only-fixture",
                "kind": "spine",
                "tache_two_subject": True,
                "arguments": value.arguments,
            }
            subject_html = render_to_string("study/partials/tache_two_questions.html", context)
            back_html = render_to_string("study/partials/card_back.html", context)
            body_html = render_to_string("study/partials/tache_two_dialogue_body.html", context)
        for html in (subject_html, back_html):
            self.assertIn(body_html, html)
            self.assertEqual(html.count("data-tache-two-question"), 8)
            self.assertEqual(html.count("data-question-highlight-text="), 8)
            self.assertNotIn("data-question-highlight-response", html)
            self.assertNotIn("Réponse préparée", html)
            for question in dialogue.questions:
                self.assertNotIn(str(escape(question.answer)), html)
                if question.condition:
                    self.assertNotIn(question.condition, html)
        self.assertTrue(all("response" not in row for row in context["subject_questions"]))
        spoken = unescape(" ".join(re.findall(
            r'<p[^>]*data-read-aloud-text[^>]*>(.*?)</p>', body_html, re.S,
        )))
        self.assertIn(dialogue.opening, spoken)
        self.assertIn(dialogue.closing, spoken)
        self.assertNotIn("Eight questions are", body_html)
        for question in dialogue.questions:
            self.assertIn(question.question, spoken)
            if question.condition:
                self.assertNotIn(question.condition, spoken)
        parsed = QuestionText(subject_html)
        self.assertEqual(parsed.text, AnnotationRootText(subject_html).text)
        for number, question in enumerate(dialogue.questions, 1):
            self.assertEqual(
                parsed.slice(*parsed.fields[number, "question"]), question.question,
            )

    def test_offsets_exclude_controls_and_use_browser_utf16_units(self):
        question = "Où aller \U0001f3e0 ?"
        html = (
            '<section data-annotation-root>'
            '<span data-annotation-exclude>Do not count \U0001f436</span>'
            f'<p data-question-highlight-text="1">{question}</p></section>'
        )
        parsed = QuestionText(html)
        self.assertEqual(parsed.text, AnnotationRootText(html).text)
        self.assertEqual(
            parsed.fields[1, "question"],
            (0, len(question.encode("utf-16-le")) // 2),
        )
        self.assertEqual(parsed.slice(*parsed.fields[1, "question"]), question)

    def test_question_only_layout_invalidates_old_anchors_without_affecting_other_tasks(self):
        dialogue = next(iter(self.load().values()))
        value = dialogue_response(dialogue)
        old_digest = hashlib.sha256(
            json.dumps(asdict(value), sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        prompt = SimpleNamespace(content_key="tache2:janvier:batch-01:subject-01")
        with patch("study.tache_two_dialogues.published_dialogue", return_value=dialogue):
            key = variant_annotation_key(prompt, value)
        self.assertNotEqual(key, f"response:{prompt.content_key}:variant-{old_digest}")
        other_prompt = SimpleNamespace(content_key="tache3:fixture")
        self.assertEqual(
            variant_annotation_key(other_prompt, value),
            f"response:{other_prompt.content_key}:variant-{old_digest}",
        )

    def test_editing_only_the_note_preserves_question_metadata_and_annotation_identity(self):
        dialogue = next(iter(self.load().values()))
        prompt = SimpleNamespace(content_key=self.manifest["groups"][0]["canonical"])
        model = dialogue_response(dialogue)
        personal = replace(
            model, is_personal=True,
            nuance="Your friend is selling belongings before moving.",
        )
        with patch("study.tache_two_dialogues.published_dialogue", return_value=dialogue):
            self.assertEqual(prompt_note_presentation(prompt, personal)["note"], personal.nuance)
            self.assertEqual(question_presentation(prompt, personal)["tache_two_dialogue"], dialogue)
            self.assertEqual(
                variant_annotation_key(prompt, model),
                variant_annotation_key(prompt, personal),
            )
            self.assertEqual(
                variant_annotation_key(prompt, personal),
                variant_annotation_key(
                    prompt,
                    replace(
                        personal,
                        arguments=(
                            replace(
                                personal.arguments[0],
                                developpement="A hidden private reply.",
                            ),
                            *personal.arguments[1:],
                        ),
                    ),
                ),
            )
            self.assertEqual(
                prompt_note_presentation(prompt, replace(personal, nuance=""))["note"],
                dialogue.note,
            )
            changed = replace(
                personal,
                arguments=(
                    replace(personal.arguments[0], idea="Puis-je passer demain ?"),
                    *personal.arguments[1:],
                ),
            )
            self.assertIsNone(question_presentation(prompt, changed)["tache_two_dialogue"])

    def test_personal_note_is_escaped_excluded_from_annotations_and_not_spoken(self):
        dialogue = next(iter(self.load().values()))
        value = replace(dialogue_response(dialogue), is_personal=True, nuance="<b>My note</b>")
        with patch("study.tache_two_dialogues.published_dialogue", return_value=None):
            note = prompt_note_presentation(None, value)
        self.assertEqual(note["register"], "")
        html = render_to_string(
            "study/partials/tache_two_prompt_note.html",
            {"subject_prompt_note": note, "prompt_note_edit_url": "/edit/"},
        )
        self.assertIn("&lt;b&gt;My note&lt;/b&gt;", html)
        self.assertNotIn("<b>My note</b>", html)
        self.assertIn('lang="en"', html)
        self.assertIn('href="/edit/#id_prompt_note"', html)
        self.assertIn('<details class="eo2-prompt-note"', html)
        self.assertIn('<summary class="eo2-prompt-note__heading">', html)
        self.assertNotIn('<details class="eo2-prompt-note" open', html)
        self.assertNotIn("data-read-aloud-text", html)
        self.assertNotIn("Vouvoiement", html)
        self.assertEqual(
            AnnotationRootText(
                f"<section data-annotation-root>{html}</section>"
            ).text.decode("utf-16-le").strip(),
            "",
        )

    def test_prompt_note_form_validates_length_and_accepts_resetting_to_default(self):
        invalid = TacheTwoConversationForm({"prompt_note": "x" * 1001})
        self.assertFalse(invalid.is_valid())
        self.assertIn("prompt_note", invalid.errors)
        blank = TacheTwoConversationForm({"prompt_note": ""})
        self.assertTrue(blank.is_valid())
        self.assertEqual(blank.cleaned_data["prompt_note"], "")


class TacheTwoDialogueCorpusTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def test_all_publications_have_eight_reviewed_questions(self):
        dialogues = load_tache_two_dialogues()
        self.assertEqual(len(dialogues), 348)
        self.assertEqual(len({dialogue.group for dialogue in dialogues.values()}), 163)
        self.assertEqual(sum(len(dialogue.questions) for dialogue in dialogues.values()), 2784)
        for key, dialogue in dialogues.items():
            with self.subTest(publication=key):
                self.assertEqual(len(dialogue.questions), 8)
                self.assertRegex(dialogue.note, r"(?i)\b(?:you|your|the|this|ask|use|already)\b")
                self.assertRegex(dialogue.closing, r"(?i)\bmerci\b")
                for question in dialogue.questions:
                    self.assertEqual(question.question.count("?"), 1)
                    if question.follow_up_to is not None:
                        self.assertTrue(question.condition)
                        self.assertLessEqual(len(question.condition.split()), 14)
                        self.assertNotIn("?", question.condition)

    def test_cached_catalogue_is_immutable_and_clearable(self):
        first = catalogue.tache_two_dialogues()
        self.assertIs(first, catalogue.tache_two_dialogues())
        with self.assertRaises(TypeError):
            first["other"] = next(iter(first.values()))
        catalogue.clear_catalogue_cache()
        self.assertEqual(first, catalogue.tache_two_dialogues())
        self.assertIsNot(first, catalogue.tache_two_dialogues())

    def test_question_forms_are_varied_without_mandating_inversion(self):
        questions = [
            question.question
            for dialogue in {row.group: row for row in load_tache_two_dialogues().values()}.values()
            for question in dialogue.questions
        ]
        for pattern in (
            r"^(?:Où|Quand|Comment|Combien|Quel|Quels|Quelle|Quelles)\b",
            r"\b[Ee]st-ce que\b",
            r"\b(?:pourriez|pourrais|serait|conseillerais|conseilleriez)\b",
            r"^(?:Tu|C'est|Ça|Il y a)\b",
        ):
            with self.subTest(form=pattern):
                self.assertGreaterEqual(sum(bool(re.search(pattern, text)) for text in questions), 5)

    def test_semantic_traps_remain_explicit_in_publication_notes(self):
        dialogues = load_tache_two_dialogues()
        neighbour = dialogues["tache2:janvier:batch-03:subject-11"]
        self.assertIn("already work", neighbour.note)
        child = dialogues["tache2:septembre:batch-02:subject-06"]
        self.assertIn("already", child.note)
        self.assertIn("timings", child.note)
        for question in child.questions:
            self.assertNotRegex(question.question, r"(?i)quelles dates|quels horaires")
        ticket = dialogues["tache2:juin:batch-02:subject-10"]
        self.assertIn("already have a cinema ticket", ticket.note)
        for question in ticket.questions:
            self.assertNotRegex(question.question, r"(?i)acheter|tarif|coûte|réserver")
        purchase = dialogues["tache2:mai:batch-05:subject-21"]
        self.assertIn("buy", purchase.note)
        for question in purchase.questions:
            self.assertNotRegex(question.question, r"(?i)loyer|dossier de location")
        generic_city = dialogues["tache2:juillet:batch-02:subject-07"]
        toronto = dialogues["tache2:juin:batch-02:subject-09"]
        self.assertNotEqual(generic_city.note, toronto.note)
        self.assertIn("Toronto", toronto.note)
        self.assertEqual(generic_city.questions, toronto.questions)


class TacheTwoDialogueViewTests(TestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.dialogue = first_dialogue_fixture()
        publication_keys = [
            content.tache_two_subject_content_key(month.slug, batch.number, subject.number)
            for month in content.load_tache_two_subject_months()
            for batch in month.batches for subject in batch.subjects
        ]
        dialogues_patch = patch(
            "study.catalogue.tache_two_dialogues",
            return_value=dict.fromkeys(publication_keys, self.dialogue),
        )
        dialogues_patch.start()
        self.addCleanup(dialogues_patch.stop)
        self.user = factories.make_user("dialogue-reader")
        task = factories.make_task(factories.make_part("eo"), "tache-2")
        self.response = factories.make_response(theme=factories.make_theme("dialogue-fixture", task=task))
        self.prompt = self.response.prompts.get()
        self.prompt.content_key = "tache2:janvier:batch-01:subject-01"
        self.prompt.text = content.load_tache_two_subject_months()[0].batches[0].subjects[0].prompt
        model = asdict(effective_response(self.response, None))
        model.pop("is_personal")
        self.prompt.model_content = model
        self.prompt.save(update_fields=["content_key", "text", "model_content"])
        self.response.content_key = self.prompt.content_key
        self.response.prompt = self.prompt.text
        self.response.semantic_group = "friend-moving-abroad-sale"
        self.response.save(update_fields=["content_key", "prompt", "semantic_group"])
        self.card = Card.objects.create(
            user=self.user, card_type=CardType.SPINE, response=self.response,
        )
        self.detail_url = prompt_detail_url(self.prompt)
        self.edit_url = reverse("study:edit_response", args=["eo", "tache-2", self.prompt.pk])
        self.client.force_login(self.user)

    def review(self):
        return self.client.get(
            reverse("study:review_next") + f"?kind=spine&response={self.response.pk}&prompt={self.prompt.pk}"
        ).json()

    def question_payload(self, note):
        return {
            "questions-TOTAL_FORMS": "8", "questions-INITIAL_FORMS": "8",
            "opening": self.dialogue.opening, "closing": self.dialogue.closing,
            "prompt_note": note,
            **{
                f"questions-{index}-question": question.question
                for index, question in enumerate(self.dialogue.questions)
            },
        }

    def test_model_is_question_only_on_subject_practice_and_editor(self):
        dialogue = catalogue.tache_two_dialogues()[self.prompt.content_key]
        detail = self.client.get(self.detail_url)
        editor = self.client.get(self.edit_url)
        practice = self.review()
        self.assertContains(detail, "data-tache-two-question", count=8)
        self.assertContains(detail, str(escape(dialogue.note)))
        self.assertContains(detail, 'class="eo2-dialogue__topic"', count=3)
        self.assertNotContains(detail, "Task 2: how to practise effectively")
        self.assertIn(str(escape(dialogue.note)), practice["front_html"])
        self.assertEqual(practice["back_html"].count("data-tache-two-question"), 8)
        self.assertEqual(editor.context["question_formset"].total_form_count(), 8)
        self.assertContains(editor, 'name="opening"')
        self.assertContains(editor, 'name="closing"')
        self.assertContains(editor, 'name="prompt_note"', count=1)
        self.assertEqual(editor.context["conversation_form"]["prompt_note"].value(), dialogue.note)
        self.assertNotContains(editor, 'name="questions-0-response"')
        self.assertNotContains(editor, "Réponse préparée")
        for question in dialogue.questions:
            for html in (detail.content.decode(), editor.content.decode(), practice["back_html"]):
                self.assertNotIn(str(escape(question.answer)), html)
        self.assertEqual(json.loads(json.dumps(self.prompt.model_content)), Prompt.objects.get(
            pk=self.prompt.pk,
        ).model_content)
        self.assertEqual(self.response.arguments.count(), 1)
        self.assertEqual(
            [argument.idea for argument in effective_response(self.response, self.user, prompt=self.prompt).arguments],
            [question.question for question in dialogue.questions],
        )

    def test_personal_answers_stay_private_stored_but_never_rendered(self):
        private_answer = "Une ancienne réponse privée à conserver."
        personal = PersonalResponse.objects.create(
            user=self.user, response=self.response, source_prompt=self.prompt,
            reformulation="Bonjour, j'aimerais préparer cet achat.",
            conclusion="Merci pour votre aide.",
            arguments=[{
                "order": 1, "idea": "Quand puis-je passer ?",
                "developpement": private_answer, "exemple": "", "consequence": "",
            }],
        )
        detail = self.client.get(self.detail_url)
        editor = self.client.get(self.edit_url)
        practice = self.review()
        self.assertContains(detail, "Quand puis-je passer ?")
        self.assertIn("Quand puis-je passer ?", practice["back_html"])
        self.assertIn(str(escape(catalogue.tache_two_dialogues()[self.prompt.content_key].note)), practice["front_html"])
        for html in (detail.content.decode(), editor.content.decode(), practice["back_html"]):
            self.assertNotIn(private_answer, unescape(html))
            self.assertNotIn("data-question-highlight-response", html)
        result = self.client.post(self.edit_url, {
            "questions-TOTAL_FORMS": "1", "questions-INITIAL_FORMS": "1",
            "questions-0-question": "Quand puis-je passer ?",
            "opening": personal.reformulation, "closing": personal.conclusion,
        })
        self.assertEqual(result.status_code, 302)
        personal.refresh_from_db()
        self.assertEqual(personal.arguments[0]["developpement"], private_answer)
        self.assertEqual(personal.reformulation, "Bonjour, j'aimerais préparer cet achat.")
        self.assertEqual(personal.conclusion, "Merci pour votre aide.")

    def test_question_offsets_match_actual_subject_and_practice_templates(self):
        value = effective_response(self.response, self.user, prompt=self.prompt)
        detail = self.client.get(self.detail_url)
        match = re.search(
            r'<section\s+class="tache-two-question-section".*?</section>',
            detail.content.decode(), re.S,
        )
        self.assertIsNotNone(match)
        actual = QuestionText(match.group())
        rendered = _render_questions(self.prompt, value, "detail", [self.prompt])
        self.assertEqual(actual.text, rendered.text)
        self.assertEqual(actual.fields, rendered.fields)
        actual_back = QuestionText(self.review()["back_html"])
        rendered_back = _render_questions(self.prompt, value, "back", [self.prompt])
        self.assertEqual(actual_back.text, rendered_back.text)
        self.assertEqual(actual_back.fields, rendered_back.fields)

    def test_legacy_answer_anchors_are_retained_but_not_replayed(self):
        annotation = Annotation.objects.create(
            user=self.user, kind=AnnotationKind.HIGHLIGHT,
            source_key="tache-two:janvier:batch-1:subject-1",
            source_path=self.detail_url, task=self.prompt.theme.task,
            quote="Une ancienne réponse d'examinateur.", body="",
            start_offset=20, end_offset=55,
        )
        detail = self.client.get(self.detail_url)
        self.assertNotContains(detail, "data-annotation-legacy-source-keys")
        self.assertTrue(Annotation.objects.filter(pk=annotation.pk).exists())

    def test_note_is_editable_private_and_used_on_subject_and_practice(self):
        note = "Your friend is selling belongings before moving. Keep the questions practical."
        original = effective_response(self.response, self.user, prompt=self.prompt)
        original_key = variant_annotation_key(self.prompt, original)
        parsed = _render_questions(self.prompt, original, "detail", [self.prompt])
        start, end = parsed.fields[1, "question"]
        annotation = Annotation.objects.create(
            user=self.user, kind=AnnotationKind.HIGHLIGHT,
            source_key=original_key, source_path=self.detail_url,
            source_prompt=self.prompt, task=self.prompt.theme.task,
            quote=self.dialogue.questions[0].question, start_offset=start, end_offset=end,
        )

        result = self.client.post(self.edit_url, self.question_payload(note))
        self.assertEqual(result.status_code, 302)
        personal = PersonalResponse.objects.get(user=self.user, response=self.response)
        self.assertEqual(personal.nuance, note)
        updated = effective_response(self.response, self.user, prompt=self.prompt)
        self.assertEqual(updated.arguments, original.arguments)
        self.assertEqual(variant_annotation_key(self.prompt, updated), original_key)
        annotation.refresh_from_db()
        self.assertEqual((annotation.start_offset, annotation.end_offset), (start, end))
        self.assertEqual(annotation.source_key, original_key)

        detail = self.client.get(self.detail_url)
        self.assertContains(detail, note)
        self.assertContains(detail, "Modifier la note")
        self.assertContains(detail, self.edit_url + "#id_prompt_note")
        self.assertContains(detail, '<details class="eo2-prompt-note"', count=1)
        self.assertNotContains(detail, '<details class="eo2-prompt-note" open')
        self.assertContains(detail, 'class="eo2-dialogue__topic"', count=3)
        practice = self.review()
        self.assertIn(note, practice["front_html"])
        self.assertIn('<details class="eo2-prompt-note"', practice["front_html"])
        self.assertNotIn('<details class="eo2-prompt-note" open', practice["front_html"])
        self.assertNotIn(note, practice["back_html"])
        self.assertEqual(
            self.client.get(self.edit_url).context["conversation_form"]["prompt_note"].value(),
            note,
        )

        other = factories.make_user("other-note-reader")
        self.client.force_login(other)
        other_detail = self.client.get(self.detail_url)
        self.assertContains(other_detail, str(escape(self.dialogue.note)))
        self.assertNotContains(other_detail, note)
        self.prompt.refresh_from_db()
        self.assertEqual(self.prompt.model_content["nuance"], "")

    def test_omitted_note_is_preserved_and_clearing_restores_default(self):
        note = "An existing private explanation to keep."
        self.client.post(self.edit_url, self.question_payload(note))
        legacy_payload = self.question_payload(note)
        legacy_payload.pop("prompt_note")
        self.assertEqual(self.client.post(self.edit_url, legacy_payload).status_code, 302)
        personal = PersonalResponse.objects.get(user=self.user, response=self.response)
        self.assertEqual(personal.nuance, note)

        self.assertEqual(self.client.post(self.edit_url, self.question_payload("")).status_code, 302)
        personal.refresh_from_db()
        self.assertEqual(personal.nuance, "")
        detail = self.client.get(self.detail_url)
        self.assertContains(detail, str(escape(self.dialogue.note)))
        self.assertNotContains(detail, note)
        self.assertContains(detail, 'class="eo2-dialogue__topic"', count=3)

    def test_invalid_note_is_reported_without_overwriting_the_saved_version(self):
        note = "Keep this saved English explanation."
        self.client.post(self.edit_url, self.question_payload(note))
        result = self.client.post(self.edit_url, self.question_payload("x" * 1001))
        self.assertEqual(result.status_code, 200)
        self.assertIn("prompt_note", result.context["conversation_form"].errors)
        self.assertEqual(
            PersonalResponse.objects.get(user=self.user, response=self.response).nuance,
            note,
        )
        self.assertEqual(self.client.post(self.edit_url, {"action": "reset"}).status_code, 302)
        detail = self.client.get(self.detail_url)
        self.assertContains(detail, str(escape(self.dialogue.note)))
        self.assertNotContains(detail, note)
