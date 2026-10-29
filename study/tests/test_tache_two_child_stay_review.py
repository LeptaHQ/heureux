import copy
import hashlib
import json
import re

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tache_two_dialogues import dialogue_response
from study.tests.eo2_review_fixtures import (
    CAREER_QUESTION_FOLLOWUP_FIELDS, DAILY_DUTIES_FOLLOWUP_FIELDS, PUBLISHED_ARCHIVE_INDEX,
    SCHOOL_NEIGHBOUR_FOLLOWUP_FIELDS, SESSION_EXTENT_FOLLOWUP_FIELDS, SURVEY_ROUTINE_FOLLOWUP_FIELDS,
    WORK_COMPARISON_CLOSING_FIELDS,
)


GROUP = "friend-child-language-stay-abroad"


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
    ).hexdigest()


class ChildLanguageStayReviewTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        catalogue.clear_catalogue_cache()
        cls.dialogues = catalogue.tache_two_dialogues()
        cls.dialogue = next(row for row in cls.dialogues.values() if row.group == GROUP)
        cls.raw = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        cls.hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"]
        cls.history = json.loads((
            content.QUESTION_BANK_DIR / "dialogue_history/locations.json"
        ).read_text())

    @classmethod
    def tearDownClass(cls):
        catalogue.clear_catalogue_cache()
        super().tearDownClass()

    def test_other_models_and_cues_except_the_authorized_later_followups_are_exact(self):
        edited = (
            {GROUP} | SCHOOL_NEIGHBOUR_FOLLOWUP_FIELDS.keys() | CAREER_QUESTION_FOLLOWUP_FIELDS.keys()
            | SURVEY_ROUTINE_FOLLOWUP_FIELDS.keys()
            | SESSION_EXTENT_FOLLOWUP_FIELDS.keys()
            | WORK_COMPARISON_CLOSING_FIELDS.keys()
            | DAILY_DUTIES_FOLLOWUP_FIELDS.keys()
        )
        self.assertEqual(len(self.raw.keys() - edited), 157)
        self.assertEqual(
            fingerprint({
                "dialogues": {g: row for g, row in self.raw.items() if g not in edited},
                "hints": {g: cues for g, cues in self.hints.items() if g not in edited},
            }),
            "8bbb4765ef69232385256d82ea8b03282d5645044ec708fae7be3709c91907d0",
        )
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == GROUP},
            {"tache2:juin:batch-06:subject-27", "tache2:decembre:batch-05:subject-22"},
        )
        self.assertEqual(self.dialogue.register, "tu")

    def test_names_and_known_destination_are_explicit_without_reasking_age_or_country(self):
        row = self.dialogue
        self.assertIn("Tom a fait un séjour linguistique au Canada", row.opening)
        self.assertIn("pour Jerry", row.opening)
        self.assertIn("avec Jerry", row.closing)
        self.assertIn("Tom is your friend's child; Jerry is yours", row.note)
        self.assertIn("not supplied by the consigne", row.note)
        questions = " ".join(q.question for q in row.questions).casefold()
        self.assertNotIn("âge", questions)
        self.assertNotIn("quel pays", questions)
        self.assertNotIn("où est-ce", questions)
        self.assertIn("Confirm Jerry's requirements with the provider", row.note)

    def test_organizer_is_established_before_asking_what_help_it_provides(self):
        row = self.dialogue
        self.assertTrue(row.questions[0].question.startswith("Tu connais un organisme"))
        self.assertIn("pour Jerry", row.questions[0].question)
        self.assertIn("coordonnées", row.questions[0].answer)
        self.assertEqual(row.questions[1].follow_up_to, 1)
        self.assertIn("If an organizer is recommended", row.questions[1].condition)
        self.assertIn("otherwise ask about independent planning", row.questions[1].condition)
        self.assertIn("préparer le séjour de Tom", row.questions[1].question)
        self.assertIn("dossier d'inscription", row.questions[1].answer)

    def test_period_and_length_replace_the_age_and_starting_level_question(self):
        row = self.dialogue
        self.assertIn("À quelle période Tom est-il parti", row.questions[2].question)
        self.assertIn("combien de temps", row.questions[2].question)
        self.assertIn("Trois semaines", row.questions[2].answer)
        self.assertIn("juillet", row.questions[2].answer)
        self.assertIn("Timing and length of Tom's stay", self.hints[GROUP][2]["english"])

    def test_hosting_checks_use_the_past_before_the_past_stay_without_imposing_a_host_family(self):
        row = self.dialogue
        self.assertIn("type d'hébergement logeait Tom", row.questions[4].question)
        self.assertIn("avait-il vérifié", row.questions[4].question)
        self.assertNotIn("famille d'accueil", row.questions[4].question)
        self.assertIn("avant le séjour", row.questions[4].answer)
        self.assertIn("avec qui Tom pouvait-il pratiquer", row.questions[5].question)
        self.assertEqual(row.questions[5].follow_up_to, 5)
        self.assertNotIn("host family", row.questions[5].condition)

    def test_programme_supervision_and_cost_questions_remain_as_published(self):
        old = self.history["groups"][GROUP]["revisions"][5]
        for index in (3, 6, 7):
            self.assertEqual(self.dialogue.questions[index].question,
                             old["questions"][index]["question"])
        self.assertIn("responsable du séjour", self.dialogue.questions[6].answer)
        self.assertIn("jour et nuit", self.dialogue.questions[6].answer)

    def test_total_cost_includes_the_package_and_extra_spending_consistently(self):
        answer = self.dialogue.questions[7].answer
        amounts = [
            int(value.replace(" ", ""))
            for value in re.findall(r"(\d[\d ]*) (?:dollars canadiens|\$)", answer)
        ]
        self.assertEqual(amounts, [4500, 4300, 200])
        self.assertEqual(amounts[0], sum(amounts[1:]))
        for included in ("voyage", "cours", "hébergement", "repas", "excursions"):
            self.assertIn(included, answer)

    def test_exact_published_layout_is_appended_without_rewriting_any_older_history(self):
        revisions = self.history["groups"][GROUP]["revisions"]
        self.assertEqual(len(revisions), 6)
        self.assertEqual(
            fingerprint(revisions[5]),
            "a8ac8364b80bbe6cc5d778920a0662880be0da50693da0dc26c80f4c4a541182",
        )
        self.assertTrue(all("answer" not in q for q in revisions[5]["questions"]))
        previous = copy.deepcopy(self.history)
        previous["groups"][GROUP]["revisions"].pop()
        for group in (
            SCHOOL_NEIGHBOUR_FOLLOWUP_FIELDS | CAREER_QUESTION_FOLLOWUP_FIELDS
            | SURVEY_ROUTINE_FOLLOWUP_FIELDS
            | SESSION_EXTENT_FOLLOWUP_FIELDS
            | WORK_COMPARISON_CLOSING_FIELDS
            | DAILY_DUTIES_FOLLOWUP_FIELDS
        ):
            previous["groups"][group]["revisions"] = (
                previous["groups"][group]["revisions"][:PUBLISHED_ARCHIVE_INDEX[group] + 1]
            )
        self.assertEqual(
            fingerprint(previous),
            "678c813dcd8f8b1d015b47b2ffbc8c6d68fe247c40a185782db958024b2bbeda",
        )

    def test_eight_question_model_has_matching_named_cues_and_no_examiner_replies(self):
        row = self.dialogue
        self.assertEqual(len(row.questions), 8)
        self.assertEqual(len(self.hints[GROUP]), 8)
        self.assertIn("Jerry", self.hints[GROUP][0]["english"])
        for index in (1, 2, 4, 5):
            self.assertIn("Tom", self.hints[GROUP][index]["english"])
        response = dialogue_response(row)
        self.assertEqual([a.idea for a in response.arguments], [q.question for q in row.questions])
        self.assertTrue(all(
            not any((a.developpement, a.exemple, a.consequence)) for a in response.arguments
        ))
        self.assertIn("merci", row.closing.casefold())
