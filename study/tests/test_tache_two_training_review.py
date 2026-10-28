import copy
import hashlib
import json

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tache_two_dialogues import dialogue_response
from study.tests.eo2_review_fixtures import (
    FOLLOWUP_GROUPS, FOLLOWUP_PROTECTED_SHA, remove_followup_archives,
)


GROUP = "director-canada-fortnight-training"
KEY = "tache2:fevrier:batch-02:subject-06"


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
    ).hexdigest()


class DirectorTrainingReviewTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        catalogue.clear_catalogue_cache()
        cls.dialogues = catalogue.tache_two_dialogues()
        cls.dialogue = cls.dialogues[KEY]
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

    def test_models_and_cues_outside_the_authorized_followups_are_exact(self):
        edited = FOLLOWUP_GROUPS
        self.assertEqual(len(self.raw.keys() - edited), 156)
        self.assertEqual(
            fingerprint({
                "dialogues": {g: row for g, row in self.raw.items() if g not in edited},
                "hints": {g: row for g, row in self.hints.items() if g not in edited},
            }),
            FOLLOWUP_PROTECTED_SHA,
        )
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == GROUP}, {KEY},
        )
        self.assertEqual(self.dialogue.register, "vous")

    def test_exact_published_layout_is_added_once_and_all_earlier_history_stays_exact(self):
        revisions = self.history["groups"][GROUP]["revisions"]
        self.assertEqual(len(revisions), 3)
        self.assertEqual(
            fingerprint(revisions[2]),
            "8917bc14509ae9ed4b94c52dff816463e2101a95157a6fe723a34c875ba0b366",
        )
        self.assertEqual(set(revisions[2]), {"group", "opening", "closing", "questions"})
        self.assertTrue(all("answer" not in q for q in revisions[2]["questions"]))
        previous = copy.deepcopy(self.history)
        remove_followup_archives(previous)
        self.assertEqual(
            fingerprint(previous),
            "36a1200196a6395e28183bbaf39dcc356af054a04fdaafffd49f2653e78ebd7b",
        )

    def test_route_keeps_eight_questions_with_funding_before_accommodation_and_transport(self):
        row = self.dialogue
        self.assertEqual(len(row.questions), 8)
        self.assertEqual(len(self.hints[GROUP]), 8)
        self.assertEqual(
            [q.topic for q in row.questions],
            ["Formation"] * 3 + ["Frais, hébergement et transport"] * 3 + ["Temps libre"] * 2,
        )
        old = self.history["groups"][GROUP]["revisions"][2]
        for before, after in ((1, 1), (6, 4), (4, 5), (7, 7)):
            self.assertEqual(old["questions"][before - 1]["question"],
                             row.questions[after - 1].question)
        self.assertIn("merci", row.closing.casefold())

    def test_programme_and_timetable_do_not_assume_software_or_group_exercises(self):
        row = self.dialogue
        self.assertIn("sujets", row.questions[1].question)
        self.assertIn("partie pratique", row.questions[1].question)
        self.assertIn("horaires", row.questions[2].question)
        self.assertIn("week-end", row.questions[2].question)
        self.assertEqual(row.questions[2].follow_up_to, 2)
        self.assertIn("9 h à 16 h 30", row.questions[2].answer)
        self.assertNotIn("logiciel", " ".join(q.question for q in row.questions))
        self.assertNotIn("petits groupes", " ".join(q.question for q in row.questions))
        self.assertIn("No software topic is given", row.note)

    def test_transport_distinguishes_arrival_transfer_from_daily_return_journeys(self):
        question = self.dialogue.questions[5]
        for text in ("transfert", "aéroport", "trajets quotidiens", "logement", "centre"):
            self.assertIn(text, question.question)
        self.assertIn("taxi", question.answer)
        self.assertIn("allers-retours quotidiens", question.answer)

    def test_last_followup_adds_activity_costs_without_repeating_the_free_time_question(self):
        row = self.dialogue
        self.assertEqual(row.questions[7].follow_up_to, 7)
        self.assertIn("who pays", row.questions[7].condition)
        self.assertIn("budget personnel", row.questions[7].question)
        self.assertNotIn("moments resteront libres", row.questions[7].question)
        self.assertNotIn("comprise", row.questions[6].answer)
        self.assertIn("comprise dans le stage", row.questions[7].answer)
        self.assertIn("à votre charge", row.questions[7].answer)
        self.assertIn("professionnels", row.questions[3].answer)

    def test_cues_match_the_new_order_and_distinct_question_goals(self):
        cues = self.hints[GROUP]
        for index, french, english in (
            (1, "Sujets", "Training topics"),
            (2, "Horaires", "Training hours"),
            (3, "Prise en charge", "Coverage of flights"),
            (4, "hébergement", "Accommodation type"),
            (5, "trajets quotidiens", "daily accommodation-to-training"),
            (7, "budget personnel", "personal leisure budget"),
        ):
            self.assertIn(french, cues[index]["french"])
            self.assertIn(english, cues[index]["english"])

    def test_learner_model_keeps_a_separate_opening_thanks_and_no_examiner_replies(self):
        row = self.dialogue
        old = self.history["groups"][GROUP]["revisions"][2]
        self.assertEqual(row.opening, old["opening"])
        self.assertEqual(row.closing, old["closing"])
        response = dialogue_response(row)
        self.assertEqual([a.idea for a in response.arguments], [q.question for q in row.questions])
        self.assertTrue(all(
            not any((a.developpement, a.exemple, a.consequence)) for a in response.arguments
        ))
