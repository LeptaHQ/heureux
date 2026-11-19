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

    def test_original_public_editions_and_job_search_publication_remain_available(self):
        self.assertEqual(len(self.raw.keys() - FOLLOWUP_GROUPS), 147)
        assert_review_preservation(self)
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == GROUP}, {KEY},
        )
        self.assertEqual(self.dialogue.register, "tu")

    def test_published_layout_is_archived_once_and_every_earlier_record_stays_exact(self):
        revisions = self.history["groups"][GROUP]["revisions"]
        self.assertEqual(len(pre_realness_history(self.history)["groups"][GROUP]["revisions"]), 3)
        self.assertEqual(
            fingerprint(revisions[2]),
            "5ec63f50541756a126d9f81173b8a2e638d80276749ff50f0cc3389ba5e8fdeb",
        )
        self.assertTrue(all("answer" not in q for q in revisions[2]["questions"]))
        previous = pre_realness_history(self.history)
        remove_followup_archives(previous)
        self.assertEqual(
            fingerprint(previous),
            "36a1200196a6395e28183bbaf39dcc356af054a04fdaafffd49f2653e78ebd7b",
        )

    def test_candidate_states_the_software_goal_without_treating_it_as_a_prompt_fact(self):
        row = self.dialogue
        self.assertIn("poste en développement logiciel", row.opening)
        self.assertIn("field and Calgary are example choices, not prompt requirements", row.note)
        self.assertNotIn("service à la clientèle", json.dumps(self.raw[GROUP], ensure_ascii=False))

    def test_developer_roles_and_search_channels_follow_authorization_check(self):
        row = self.dialogue
        for specialism in ("front-end", "back-end", "full stack"):
            self.assertIn(specialism, row.questions[1].question)
            self.assertIn(specialism, row.questions[1].answer)
        for channel in ("LinkedIn", "sites des entreprises", "recruteurs spécialisés"):
            self.assertIn(channel, row.questions[3].question)
        self.assertEqual(row.questions[3].follow_up_to, 2)

    def test_employer_priorities_are_observed_requirements_not_cv_presentation_advice(self):
        question = self.dialogue.questions[2]
        for detail in ("D'après les offres que tu vois", "diplôme en informatique",
                       "expérience professionnelle", "projets réalisés"):
            self.assertIn(detail, question.question)
        self.assertIn("offres que j'ai vues", question.answer)
        self.assertIsNone(question.follow_up_to)
        self.assertIn("Sur le CV", self.dialogue.questions[4].question)
        self.assertIn("Employer priorities", self.hints[GROUP][2]["english"])

    def test_cv_question_asks_for_project_evidence_without_requiring_confidential_code(self):
        row = self.dialogue
        for detail in ("projets", "compétences techniques", "GitHub"):
            self.assertIn(detail, row.questions[4].question)
        self.assertIn("projets publics peut aider", row.questions[4].answer)
        self.assertIn("sans exposer de code confidentiel", row.questions[4].answer)

    def test_recruitment_question_covers_technical_assessment_without_guaranteeing_one_process(self):
        row = self.dialogue
        self.assertIn("Après l'envoi du CV", row.questions[5].question)
        self.assertIn("plusieurs entretiens et un test de programmation", row.questions[5].question)
        self.assertEqual(row.questions[5].follow_up_to, 2)
        self.assertIn("recruitment stages", row.questions[5].condition)
        self.assertIn("varie selon l'entreprise", row.questions[5].answer)

    def test_authorization_check_still_leads_the_route(self):
        row = self.dialogue
        old = self.history["groups"][GROUP]["revisions"][2]
        self.assertEqual(row.questions[0].question, old["questions"][4]["question"])
        self.assertIsNone(row.questions[0].follow_up_to)
        self.assertIn("IRCC", row.questions[0].answer)
        self.assertIn("Verify unresolved eligibility before proceeding", row.note)
        self.assertIn("not hiring or legal guarantees", row.note)

    def test_salary_is_gross_annual_and_figures_are_explicitly_illustrative(self):
        row = self.dialogue
        self.assertIn("salaire annuel brut", row.questions[6].question)
        self.assertNotIn("horaire", row.questions[6].question)
        self.assertNotIn("vois", row.questions[6].question)
        self.assertIn("dollars canadiens bruts par an", row.questions[6].answer)
        self.assertIn("Offers and salary figures are illustrative", row.note)

    def test_last_question_focuses_on_onsite_hybrid_and_fully_remote_work(self):
        row = self.dialogue
        for arrangement in ("bureau tous les jours", "à distance certains jours", "toute la semaine"):
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
        for index, phrase in ((1, "Front-end"), (2, "Employer priorities"),
                              (4, "GitHub"), (5, "programming test"),
                              (6, "annual salary"), (7, "remote work")):
            self.assertIn(phrase, self.hints[GROUP][index]["english"])
