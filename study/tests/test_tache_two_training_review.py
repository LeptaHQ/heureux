import hashlib
import json

from django.test import SimpleTestCase

from study.catalogue import registry as catalogue
from study.catalogue import loader as content
from study.expression.eo.tache_2.dialogues import dialogue_response
from study.tests.eo2_review_fixtures import (
    FOLLOWUP_GROUPS, remove_followup_archives,
    assert_review_preservation, pre_realness_history,
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

    def test_original_public_editions_and_training_publication_remain_available(self):
        edited = FOLLOWUP_GROUPS
        self.assertEqual(len(self.raw.keys() - edited), 147)
        assert_review_preservation(self)
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == GROUP}, {KEY},
        )
        self.assertEqual(self.dialogue.register, "vous")

    def test_exact_published_layout_is_added_once_and_all_earlier_history_stays_exact(self):
        revisions = self.history["groups"][GROUP]["revisions"]
        self.assertEqual(len(revisions), 4)
        self.assertEqual(
            fingerprint(revisions[2]),
            "8917bc14509ae9ed4b94c52dff816463e2101a95157a6fe723a34c875ba0b366",
        )
        self.assertEqual(set(revisions[2]), {"group", "opening", "closing", "questions"})
        self.assertTrue(all("answer" not in q for q in revisions[2]["questions"]))
        self.assertEqual(
            revisions[3]["questions"][1]["question"],
            "Quels sujets seront abordés pendant la formation, et y aura-t-il une partie pratique ?",
        )
        previous = pre_realness_history(self.history)
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
            ["Formation"] * 4 + ["Frais, hébergement et transport"] * 3 + ["Temps libre"],
        )
        old = self.history["groups"][GROUP]["revisions"][2]
        for before, after in ((1, 1), (6, 5), (4, 6), (7, 8)):
            self.assertEqual(old["questions"][before - 1]["question"],
                             row.questions[after - 1].question)
        self.assertIn("merci", row.closing.casefold())
        self.assertIn("professionnels", row.questions[4].answer)

    def test_programme_and_timetable_do_not_assume_software_or_group_exercises(self):
        row = self.dialogue
        self.assertIn("sujets", row.questions[1].question)
        self.assertIn("exercices pratiques ou des études de cas", row.questions[1].question)
        self.assertIn("cas concrets", row.questions[1].answer)
        self.assertIn("horaires", row.questions[2].question)
        self.assertIn("week-end", row.questions[2].question)
        self.assertEqual(row.questions[2].follow_up_to, 2)
        self.assertIn("9 h à 16 h 30", row.questions[2].answer)
        self.assertNotIn("logiciel", " ".join(q.question for q in row.questions))
        self.assertNotIn("petits groupes", " ".join(q.question for q in row.questions))
        self.assertIn("No software topic is given", row.note)

    def test_transport_distinguishes_arrival_transfer_from_daily_return_journeys(self):
        question = self.dialogue.questions[6]
        for text in ("viendra me chercher", "aéroport", "allers-retours quotidiens", "mon logement", "centre"):
            self.assertIn(text, question.question)
        self.assertIn("taxi", question.answer)
        self.assertIn("allers-retours quotidiens", question.answer)

    def test_completion_document_does_not_promise_a_professional_certification(self):
        row = self.dialogue
        question = row.questions[3]
        self.assertIn("recevrai-je une attestation de participation ou un certificat", question.question)
        self.assertIsNone(question.follow_up_to)
        self.assertIn("pas une certification professionnelle", question.answer)
        self.assertIn("Quelles activités", row.questions[7].question)
        self.assertIsNone(row.questions[7].follow_up_to)

    def test_cues_match_the_new_order_and_distinct_question_goals(self):
        cues = self.hints[GROUP]
        for index, french, english in (
            (1, "Sujets", "Training topics"),
            (2, "Horaires", "Training hours"),
            (3, "Attestation de participation", "Proof of attendance"),
            (4, "Prise en charge", "Coverage of flights"),
            (5, "hébergement", "Accommodation type"),
            (6, "allers-retours quotidiens", "daily accommodation-to-training"),
            (7, "Activités", "Activities outside training hours"),
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
