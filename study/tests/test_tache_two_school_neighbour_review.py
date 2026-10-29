import copy
import hashlib
import json
import re

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tache_two_dialogues import dialogue_response
from study.tests.eo2_review_fixtures import (
    CAREER_QUESTION_FOLLOWUP_FIELDS, DAILY_DUTIES_FOLLOWUP_FIELDS, PUBLISHED_ARCHIVE_INDEX,
    SESSION_EXTENT_FOLLOWUP_FIELDS, SURVEY_ROUTINE_FOLLOWUP_FIELDS,
    WORK_COMPARISON_CLOSING_FIELDS,
)


GROUP = "edmonton-newcomer-neighbor-schools"


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
    ).hexdigest()


class SchoolNeighbourReviewTests(SimpleTestCase):
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

    def test_other_models_and_cues_except_the_authorized_later_changes_are_exact(self):
        edited = (
            {GROUP} | CAREER_QUESTION_FOLLOWUP_FIELDS.keys() | SURVEY_ROUTINE_FOLLOWUP_FIELDS.keys()
            | SESSION_EXTENT_FOLLOWUP_FIELDS.keys()
            | WORK_COMPARISON_CLOSING_FIELDS.keys()
            | DAILY_DUTIES_FOLLOWUP_FIELDS.keys()
        )
        self.assertEqual(len(self.raw.keys() - edited), 158)
        self.assertEqual(
            fingerprint({
                "dialogues": {g: row for g, row in self.raw.items() if g not in edited},
                "hints": {g: cues for g, cues in self.hints.items() if g not in edited},
            }),
            "db8e8ca6388706ab1b0abe31384c731c48247f0c8c5e27071b39cb451059d620",
        )
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == GROUP},
            {"tache2:juillet:batch-04:subject-19", "tache2:juillet:batch-05:subject-24"},
        )
        self.assertEqual(self.dialogue.register, "vous")
        self.assertIn("Edmonton", self.dialogue.note)

    def test_local_school_and_address_check_are_combined_once_at_the_start(self):
        row = self.dialogue
        self.assertEqual(
            row.questions[0].question,
            "Où puis-je vérifier à quelles écoles du quartier je peux inscrire "
            "mes enfants en fonction de notre adresse ?",
        )
        self.assertEqual(sum(bool(re.search(r"\badresse\b", q.question)) for q in row.questions), 1)
        self.assertIn("conseil scolaire", row.questions[0].answer)
        self.assertIn("confirmer si vous en dépendez", row.questions[0].answer)
        self.assertIn("First check which schools serve your address", row.note)
        self.assertIn("not admissions rules or verified current fees", row.note)

    def test_transport_remains_a_short_separate_question_before_teachers(self):
        row = self.dialogue
        self.assertEqual(
            row.questions[2].question,
            "Où se trouvent ces écoles, et peut-on s'y rendre à pied ou en bus ?",
        )
        self.assertEqual(row.questions[2].topic, row.questions[0].topic)
        self.assertIn("à pied", row.questions[2].answer)
        self.assertIn("en bus", row.questions[2].answer)
        self.assertIn("près du parc", row.questions[2].answer)
        self.assertIn("près de la bibliothèque", row.questions[2].answer)
        self.assertEqual(
            self.hints[GROUP][2]["english"], "School locations and getting there on foot or by bus",
        )

    def test_teacher_quality_asks_for_experience_not_unverifiable_qualifications(self):
        self.assertEqual(
            self.dialogue.questions[3].question,
            "D'après votre expérience, comment trouvez-vous les enseignants, "
            "notamment leur façon d'expliquer et d'aider les élèves ?",
        )
        self.assertIn("Mes enfants disent", self.dialogue.questions[3].answer)
        self.assertIn("expliquent clairement", self.dialogue.questions[3].answer)
        self.assertIn("besoin d'aide", self.dialogue.questions[3].answer)
        self.assertIn("explanations and help", self.hints[GROUP][3]["english"])

    def test_welcome_question_is_open_and_keeps_classmate_and_teacher_examples(self):
        self.assertEqual(
            self.dialogue.questions[4].question,
            "Comment les nouveaux élèves sont-ils accompagnés pendant leurs premiers "
            "jours à l'école, par exemple par un camarade ou un enseignant ?",
        )
        self.assertIsNone(self.dialogue.questions[4].follow_up_to)
        self.assertEqual(
            self.raw[GROUP]["questions"][4]["answer"],
            "Dans l'école de mes enfants, un camarade montre les lieux et les habitudes ; "
            "l'enseignant prend aussi le temps de vérifier que tout se passe bien.",
        )
        self.assertIn("classmate or teacher", self.hints[GROUP][4]["english"])

    def test_other_questions_cues_and_fees_are_retained_with_correct_relance_parent(self):
        before = self.history["groups"][GROUP]["revisions"][4]
        for old_index, new_index in ((1, 1), (4, 5), (5, 6), (7, 7)):
            self.assertEqual(
                self.dialogue.questions[new_index].question,
                before["questions"][old_index]["question"],
            )
        self.assertEqual(self.dialogue.questions[6].follow_up_to, 6)
        self.assertIn("after-school gaps", self.dialogue.questions[6].condition)
        self.assertIn("l'an dernier", self.dialogue.questions[6].answer)
        self.assertIn("Confirmez le tarif actuel", self.dialogue.questions[6].answer)

    def test_published_snapshot_is_appended_without_touching_any_older_history(self):
        revisions = self.history["groups"][GROUP]["revisions"]
        self.assertEqual(len(revisions), 5)
        self.assertEqual(
            fingerprint(revisions[4]),
            "59fa956aa028aae48e0f78fda4a03902a84ddec77b879ac2f8e0326bc0abc7ad",
        )
        self.assertTrue(all("answer" not in q for q in revisions[4]["questions"]))
        previous = copy.deepcopy(self.history)
        previous["groups"][GROUP]["revisions"].pop()
        for group in (
            CAREER_QUESTION_FOLLOWUP_FIELDS | SURVEY_ROUTINE_FOLLOWUP_FIELDS
            | SESSION_EXTENT_FOLLOWUP_FIELDS
            | WORK_COMPARISON_CLOSING_FIELDS
            | DAILY_DUTIES_FOLLOWUP_FIELDS
        ):
            previous["groups"][group]["revisions"] = (
                previous["groups"][group]["revisions"][:PUBLISHED_ARCHIVE_INDEX[group] + 1]
            )
        self.assertEqual(
            fingerprint(previous),
            "d811433ec9e1df7d5388c7efba5d62718e8d2caa2635e17fc1f733d5beef75fb",
        )

    def test_questions_only_shape_and_eight_aligned_cues_are_preserved(self):
        row = self.dialogue
        self.assertEqual(len(row.questions), 8)
        self.assertEqual(len(self.hints[GROUP]), 8)
        response = dialogue_response(row)
        self.assertEqual([a.idea for a in response.arguments], [q.question for q in row.questions])
        self.assertTrue(all(
            not any((a.developpement, a.exemple, a.consequence)) for a in response.arguments
        ))
        self.assertIn("merci", row.closing.casefold())
