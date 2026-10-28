import copy
import hashlib
import json

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tache_two_dialogues import dialogue_response
from study.tests.eo2_review_fixtures import (
    FOLLOWUP_GROUPS, FOLLOWUP_PROTECTED_SHA, remove_followup_archives,
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

    def test_models_and_cues_outside_the_authorized_followups_stay_exact(self):
        self.assertEqual(len(self.raw.keys() - FOLLOWUP_GROUPS), 156)
        self.assertEqual(
            fingerprint({
                "dialogues": {g: row for g, row in self.raw.items() if g not in FOLLOWUP_GROUPS},
                "hints": {g: row for g, row in self.hints.items() if g not in FOLLOWUP_GROUPS},
            }),
            FOLLOWUP_PROTECTED_SHA,
        )
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == GROUP},
            {
                "tache2:fevrier:batch-03:subject-12",
                "tache2:septembre:batch-04:subject-16",
                "tache2:novembre:batch-03:subject-11",
            },
        )
        self.assertEqual(self.dialogue.register, "tu")

    def test_exact_published_first_day_layout_is_archived_once(self):
        revisions = self.history["groups"][GROUP]["revisions"]
        self.assertEqual(len(revisions), 3)
        self.assertEqual(
            fingerprint(revisions[2]),
            "349c2575d10ca5208d12b3b1054b05dcd76e62ca06952f6865a89464baa87d9e",
        )
        self.assertTrue(all("answer" not in q for q in revisions[2]["questions"]))
        previous = copy.deepcopy(self.history)
        remove_followup_archives(previous)
        self.assertEqual(
            fingerprint(previous),
            "36a1200196a6395e28183bbaf39dcc356af054a04fdaafffd49f2653e78ebd7b",
        )

    def test_q5_asks_about_support_for_actual_tasks_not_software_or_clients(self):
        question = self.dialogue.questions[4]
        self.assertEqual(
            question.question,
            "Pour tes premières tâches, quelqu'un t'a montré comment faire ou tu as dû te débrouiller seule ?",
        )
        self.assertNotIn("logiciel", question.question)
        self.assertNotIn("clients", question.question)
        self.assertEqual(question.follow_up_to, 4)
        self.assertIn("unless guidance has already been explained", question.condition)
        self.assertIn("Une collègue m'a montré", question.answer)
        self.assertIn("restée à côté", question.answer)

    def test_all_seven_other_questions_stay_as_published(self):
        old = self.history["groups"][GROUP]["revisions"][2]
        for index, question in enumerate(self.dialogue.questions):
            if index == 4:
                continue
            archived = old["questions"][index]
            self.assertEqual(question.question, archived["question"])
            self.assertEqual(question.topic, archived["topic"])
            self.assertEqual(question.follow_up_to, archived["follow_up_to"])
            self.assertEqual(question.condition, archived.get("condition", ""))
        self.assertEqual(len(self.dialogue.questions), 8)
        self.assertEqual(self.dialogue.opening, old["opening"])
        self.assertEqual(self.dialogue.closing, old["closing"])

    def test_q5_cues_name_guidance_and_independence_instead_of_software_practice(self):
        cue = self.hints[GROUP][4]
        self.assertEqual(cue["french"], "Accompagnement ou autonomie pour les premières tâches")
        self.assertEqual(cue["english"], "Guidance or independence with the first tasks")

    def test_learner_model_is_still_questions_only(self):
        response = dialogue_response(self.dialogue)
        self.assertEqual(
            [argument.idea for argument in response.arguments],
            [question.question for question in self.dialogue.questions],
        )
        self.assertTrue(all(
            not any((a.developpement, a.exemple, a.consequence)) for a in response.arguments
        ))
