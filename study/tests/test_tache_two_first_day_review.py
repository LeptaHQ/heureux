import hashlib
import json

from django.test import SimpleTestCase

from study.catalogue import registry as catalogue
from study.catalogue import loader as content
from study.expression.eo.tache_2.dialogues import dialogue_response
from study.tests.eo2_review_fixtures import (
    assert_review_preservation, FOLLOWUP_GROUPS,
)


GROUP = "friend-first-workday-report"


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
    ).hexdigest()


class FirstWorkdayFollowupTests(SimpleTestCase):
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

    def test_original_public_editions_and_first_day_publications_remain_available(self):
        self.assertEqual(len(self.raw.keys() - FOLLOWUP_GROUPS), 147)
        assert_review_preservation(self)
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == GROUP},
            {
                "tache2:fevrier:batch-03:subject-12",
                "tache2:septembre:batch-04:subject-16",
                "tache2:novembre:batch-03:subject-11",
            },
        )
        self.assertEqual(self.dialogue.register, "tu")

    def test_previous_first_day_layouts_are_preserved_exactly(self):
        revisions = self.history["groups"][GROUP]["revisions"]
        self.assertEqual(len(revisions), 7)
        self.assertEqual(
            fingerprint(revisions[:-1]),
            "db00e471e2678e8830e1f5c51acbf1ab6de04dc07696782c4f4e45953b90f225",
        )
        self.assertEqual(
            fingerprint(revisions[-1]),
            "8ed003275627db31a1df481921cb67ff05cfe667a0d9e8620e6b10834d0440f1",
        )
        self.assertTrue(all("answer" not in q for q in revisions[-1]["questions"]))

    def test_q5_follows_up_on_the_task_without_assuming_training(self):
        question = self.dialogue.questions[4]
        self.assertIn("une formation ou on t'a montré", question.question)
        self.assertNotIn("logiciel", question.question)
        self.assertNotIn("clients", question.question)
        self.assertEqual(question.follow_up_to, 4)
        self.assertIn("unless she has already explained how she learned it", question.condition)
        self.assertIn("courte formation", question.answer)
        self.assertIn("restée à côté", question.answer)

    def test_rewrite_keeps_the_welcome_atmosphere_and_work_question_wording(self):
        old = self.history["groups"][GROUP]["revisions"][-1]
        self.assertEqual(
            [q.question for q in self.dialogue.questions[1:4]],
            [q["question"] for q in old["questions"][1:4]],
        )
        self.assertEqual(self.dialogue.opening, old["opening"])
        self.assertEqual(self.dialogue.closing, old["closing"])

    def test_tasks_assigned_are_distinct_from_what_she_started_doing(self):
        question = self.dialogue.questions[3]
        self.assertIn("qu'est-ce qu'on t'a confié", question.question)
        self.assertIn("tu as déjà eu le temps de faire", question.question)
        self.assertIn("On m'a demandé", question.answer)
        self.assertIn("J'ai commencé par retrouver des commandes", question.answer)
        self.assertIn("tasks assigned and work already done", self.hints[GROUP][3]["english"])

    def test_q5_cues_point_to_learning_the_named_task(self):
        cue = self.hints[GROUP][4]
        self.assertEqual(cue["french"], "Formation ou apprentissage au fur et à mesure")
        self.assertEqual(cue["english"], "Training session or being shown what to do as she went along")

    def test_learner_model_is_still_questions_only(self):
        response = dialogue_response(self.dialogue)
        self.assertEqual(
            [argument.idea for argument in response.arguments],
            [question.question for question in self.dialogue.questions],
        )
        self.assertTrue(all(
            not any((a.developpement, a.exemple, a.consequence)) for a in response.arguments
        ))
