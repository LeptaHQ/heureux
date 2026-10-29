import copy
import hashlib
import json

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tache_two_dialogues import dialogue_response
from study.tests.eo2_review_fixtures import (
    FOLLOWUP_GROUPS, FOLLOWUP_PROTECTED_SHA, remove_followup_archives,
)


GROUP = "newcomer-canada-friend-job-market"
KEY = "tache2:fevrier:batch-03:subject-15"


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
    ).hexdigest()


class SoftwareJobSearchReviewTests(SimpleTestCase):
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

    def test_models_and_cues_outside_the_authorized_followups_stay_exact(self):
        self.assertEqual(len(self.raw.keys() - FOLLOWUP_GROUPS), 152)
        self.assertEqual(
            fingerprint({
                "dialogues": {g: row for g, row in self.raw.items() if g not in FOLLOWUP_GROUPS},
                "hints": {g: row for g, row in self.hints.items() if g not in FOLLOWUP_GROUPS},
            }),
            FOLLOWUP_PROTECTED_SHA,
        )
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == GROUP}, {KEY},
        )
        self.assertEqual(self.dialogue.register, "tu")

    def test_published_layout_is_archived_once_and_every_earlier_record_stays_exact(self):
        revisions = self.history["groups"][GROUP]["revisions"]
        self.assertEqual(len(revisions), 3)
        self.assertEqual(
            fingerprint(revisions[2]),
            "5ec63f50541756a126d9f81173b8a2e638d80276749ff50f0cc3389ba5e8fdeb",
        )
        self.assertTrue(all("answer" not in q for q in revisions[2]["questions"]))
        previous = copy.deepcopy(self.history)
        remove_followup_archives(previous)
        self.assertEqual(
            fingerprint(previous),
            "36a1200196a6395e28183bbaf39dcc356af054a04fdaafffd49f2653e78ebd7b",
        )

    def test_candidate_states_the_software_goal_without_treating_it_as_a_prompt_fact(self):
        row = self.dialogue
        self.assertIn("poste en développement logiciel", row.opening)
        self.assertIn("your chosen field, not a prompt requirement", row.note)
        self.assertIn("Calgary is the example city", row.note)
        self.assertNotIn("service à la clientèle", json.dumps(self.raw[GROUP], ensure_ascii=False))

    def test_opening_questions_cover_developer_roles_and_specialist_search_channels(self):
        row = self.dialogue
        self.assertIn("profils de développeurs", row.questions[0].question)
        self.assertIn("offres d'emploi", row.questions[0].question)
        for channel in ("LinkedIn", "sites des entreprises", "recruteurs spécialisés"):
            self.assertIn(channel, row.questions[1].question)
        self.assertEqual(row.questions[1].follow_up_to, 1)

    def test_cv_question_asks_for_project_evidence_without_requiring_confidential_code(self):
        row = self.dialogue
        for detail in ("projets", "compétences techniques", "GitHub"):
            self.assertIn(detail, row.questions[2].question)
        self.assertIn("projets publics peut aider", row.questions[2].answer)
        self.assertIn("sans exposer de code confidentiel", row.questions[2].answer)

    def test_recruitment_question_covers_technical_assessment_without_guaranteeing_one_process(self):
        row = self.dialogue
        self.assertIn("étapes habituelles du recrutement", row.questions[3].question)
        self.assertIn("tests techniques", row.questions[3].question)
        self.assertEqual(row.questions[3].follow_up_to, 1)
        self.assertIn("recruitment stages", row.questions[3].condition)
        self.assertIn("varie selon l'entreprise", row.questions[3].answer)

    def test_work_authorization_and_social_insurance_questions_remain_as_published(self):
        row = self.dialogue
        old = self.history["groups"][GROUP]["revisions"][2]
        for index in (4, 5):
            self.assertEqual(row.questions[index].question, old["questions"][index]["question"])
            self.assertEqual(row.questions[index].follow_up_to, old["questions"][index]["follow_up_to"])
            self.assertEqual(row.questions[index].condition,
                             old["questions"][index].get("condition", ""))
        self.assertIn("IRCC", row.questions[4].answer)
        self.assertIn("Service Canada", row.questions[5].answer)
        self.assertIn("not hiring or legal guarantees", row.note)

    def test_salary_is_gross_annual_and_figures_are_explicitly_illustrative(self):
        row = self.dialogue
        self.assertIn("salaire annuel brut", row.questions[6].question)
        self.assertNotIn("horaire", row.questions[6].question)
        self.assertIn("dollars canadiens bruts par an", row.questions[6].answer)
        self.assertIn("Offers and salary figures are illustrative", row.note)

    def test_last_question_focuses_on_onsite_hybrid_and_fully_remote_work(self):
        row = self.dialogue
        for arrangement in ("sur place", "hybride", "entièrement en télétravail"):
            self.assertIn(arrangement, row.questions[7].question)
        self.assertNotIn("temps partiel", row.questions[7].question)
        self.assertIn("exigences de présence et de résidence", row.questions[7].answer)
        self.assertIn("fully remote", self.hints[GROUP][7]["english"])

    def test_eight_question_route_and_bilingual_cues_never_expose_examiner_replies(self):
        row = self.dialogue
        self.assertEqual(len(row.questions), 8)
        self.assertEqual(len(self.hints[GROUP]), 8)
        self.assertIn("merci", row.closing.casefold())
        response = dialogue_response(row)
        self.assertEqual([a.idea for a in response.arguments], [q.question for q in row.questions])
        self.assertTrue(all(
            not any((a.developpement, a.exemple, a.consequence)) for a in response.arguments
        ))
        for index, phrase in ((0, "Developer profiles"), (2, "GitHub"), (3, "technical assessments"),
                              (6, "annual salary"), (7, "remote work")):
            self.assertIn(phrase, self.hints[GROUP][index]["english"])
