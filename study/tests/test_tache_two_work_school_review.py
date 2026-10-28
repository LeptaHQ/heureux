import copy
import hashlib
import json

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tache_two_dialogues import dialogue_response
from study.tests.eo2_review_fixtures import (
    PUBLISHED_ARCHIVE_INDEX, SCHOOL_GROUPS, TRANSPORT_TRAVEL_GROUPS, WORK_GROUPS,
    WORK_SCHOOL_GROUPS as REVIEWED_GROUPS, remove_latest_review_archives,
)


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
    ).hexdigest()


class WorkSchoolDialogueReviewTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        catalogue.clear_catalogue_cache()
        cls.dialogues = catalogue.tache_two_dialogues()
        cls.by_group = {row.group: row for row in cls.dialogues.values()}
        _, cls.themes = catalogue.tache_two_subject_themes()
        cls.raw = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        cls.hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"]
        cls.history_document = json.loads(
            (content.QUESTION_BANK_DIR / "dialogue_history/locations.json").read_text(),
        )

    @classmethod
    def tearDownClass(cls):
        catalogue.clear_catalogue_cache()
        super().tearDownClass()

    def test_current_themes_keep_all_twenty_four_models_and_forty_seven_publications(self):
        for theme, groups, count in (
            ("travail", WORK_GROUPS, 28), ("ecole-etudes", SCHOOL_GROUPS, 19),
        ):
            rows = [row for key, row in self.dialogues.items() if self.themes[key] == theme]
            self.assertEqual({row.group for row in rows}, groups)
            self.assertEqual(len(rows), count)
            for row in rows:
                self.assertEqual(len(row.questions), 8)
                self.assertEqual(len(self.hints[row.group]), 8)
                self.assertIn("merci", row.closing.casefold())

    def test_dialogues_and_cues_outside_both_authorized_reviews_remain_as_published(self):
        reviewed = REVIEWED_GROUPS | TRANSPORT_TRAVEL_GROUPS
        unrelated = {
            "dialogues": {key: row for key, row in self.raw.items() if key not in reviewed},
            "hints": {key: rows for key, rows in self.hints.items() if key not in reviewed},
        }
        self.assertEqual(
            fingerprint(unrelated),
            "a39e746bb692e82887b661246479ba54e6d3a38f9c1e7301e084c760ba4cbad5",
        )
        self.assertEqual(
            fingerprint(sorted((key, row["register"]) for key, row in self.raw.items())),
            "11b2868eb895bf97db1f6d38f4e757d9f2d2d0a0c859de9c3bad6e866c21e9d4",
        )

    def test_exact_previous_published_layouts_are_archived_without_internal_replies(self):
        snapshots = [
            self.history_document["groups"][group]["revisions"][PUBLISHED_ARCHIVE_INDEX[group]]
            for group in sorted(REVIEWED_GROUPS)
        ]
        self.assertEqual(
            fingerprint(snapshots),
            "520927a18855e58fe036fc03fba1c4cea18189be742bddbb70a3a02255e589bd",
        )
        for snapshot in snapshots:
            self.assertEqual(len(snapshot["questions"]), 8)
            for question in snapshot["questions"]:
                self.assertNotIn("answer", question)

    def test_every_earlier_archive_and_geographic_substitution_is_untouched(self):
        previous = copy.deepcopy(self.history_document)
        remove_latest_review_archives(previous)
        self.assertEqual(
            fingerprint(previous),
            "774c33725f0ef5bee59983fcc44f222c824abc6b3b3e75d5e680911e8e810a8d",
        )

    def test_none_of_the_twenty_four_learner_models_contains_examiner_replies(self):
        for group in REVIEWED_GROUPS:
            dialogue = self.by_group[group]
            value = dialogue_response(dialogue)
            self.assertEqual([a.idea for a in value.arguments], [q.question for q in dialogue.questions])
            self.assertTrue(all(
                not any((a.developpement, a.exemple, a.consequence)) for a in value.arguments
            ))
            self.assertFalse(value.position)
            self.assertFalse(value.position_claire)
            self.assertFalse(value.nuance)

    def test_career_rephrase_changes_only_the_requested_question_and_keeps_all_cues(self):
        group = "friend-planned-canadian-studies"
        row = copy.deepcopy(self.raw[group])
        self.assertEqual(
            row["questions"][3]["question"],
            "Qu'est-ce que cette formation apportera à ta carrière ?",
        )
        row["questions"][3]["question"] = "<reviewed-career-question>"
        self.assertEqual(
            fingerprint({"dialogue": row, "hints": self.hints[group]}),
            "a0e0e4f557fe556b7976f8292d0d064c133320f5003dfec7c9d2192590a5f6f4",
        )
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == group},
            {"tache2:octobre:batch-09:subject-42"},
        )

    def test_career_rephrase_preserves_all_other_163_models_and_their_cues(self):
        group = "friend-planned-canadian-studies"
        self.assertEqual(len(self.raw) - 1, 163)
        self.assertEqual(
            fingerprint({
                "dialogues": {g: row for g, row in self.raw.items() if g != group},
                "hints": {g: cues for g, cues in self.hints.items() if g != group},
            }),
            "829e79a3fd3731eac051eb213fcdbf0004995230f775d12d0a770067693c63fc",
        )

    def test_career_rephrase_archives_the_published_layout_without_replies_or_older_changes(self):
        group = "friend-planned-canadian-studies"
        revisions = self.history_document["groups"][group]["revisions"]
        self.assertEqual(len(revisions), 4)
        self.assertEqual(
            fingerprint(revisions[3]),
            "700180a0ab97570a826e4e9b8dc2b9fb93e762c99d9c2e21d7e8d9cf10529c31",
        )
        self.assertTrue(all("answer" not in q for q in revisions[3]["questions"]))
        previous = copy.deepcopy(self.history_document)
        previous["groups"][group]["revisions"].pop()
        self.assertEqual(
            fingerprint(previous),
            "a8e2f902a91d7c1c16cbc506cae2f6f65d9e5a38f7e8e2a8d5e403a3c0c7917d",
        )

    def test_first_day_has_an_actual_difficulty_and_a_response_to_it(self):
        row = self.by_group["friend-first-workday-report"]
        self.assertIn("première journée", row.questions[0].question)
        self.assertIn("premières tâches", row.questions[4].question)
        self.assertIn("quelqu'un t'a montré", row.questions[4].question)
        self.assertNotIn("logiciel", row.questions[4].question)
        self.assertIn("modifier une commande", row.questions[5].answer)
        self.assertNotIn("rappelé", row.questions[5].answer)
        self.assertEqual(row.questions[6].follow_up_to, 6)
        self.assertIn("dans ce cas-là", row.questions[6].question)
        self.assertIn("rappelé le client ensemble", row.questions[6].answer)
        self.assertNotIn("encourageant", row.closing)

    def test_recruiter_and_friend_are_asked_different_preparation_questions(self):
        recruiter = self.by_group["recruiter-scheduled-interview-preparation"]
        friend = self.by_group["friend-upcoming-job-interview-advice"]
        self.assertIn("sur place ou à distance", recruiter.questions[0].question)
        self.assertIn("mise en situation", recruiter.questions[5].answer)
        self.assertEqual(recruiter.questions[6].follow_up_to, 6)
        self.assertIn("préparer quelque chose à l'avance", recruiter.questions[6].question)
        self.assertIn("CV", recruiter.questions[7].question)
        self.assertIn("motivation ou mes points faibles", friend.questions[2].question)
        self.assertIn("question me surprend", friend.questions[5].question)
        self.assertIn("reformuler", friend.questions[5].answer)
        self.assertNotIn("questions du recruteur", recruiter.questions[6].question)

    def test_association_work_explores_actual_work_without_assuming_unpaid_status(self):
        row = self.by_group["friend-association-work-experience"]
        self.assertIn("principales tâches", row.questions[1].question)
        self.assertEqual(row.questions[2].follow_up_to, 2)
        self.assertIn("bénévole se désiste", row.questions[2].question)
        self.assertIn("adaptons l'activité", row.questions[2].answer)
        self.assertIn("rémunéré", row.questions[6].question)
        self.assertIn("bénévolement", row.questions[6].question)
        self.assertIn("emploi salarié", row.questions[6].answer)
        self.assertIn("sentiment d'être utile", row.questions[7].question)

    def test_internal_move_keeps_coordination_remote_work_and_bonus_criteria_distinct(self):
        row = self.by_group["colleague-internal-job-change"]
        self.assertIn("coordonne les projets", row.questions[0].answer)
        self.assertNotIn("service client", row.questions[0].answer)
        self.assertIn("avec quels services", row.questions[1].question)
        self.assertIn("télétravail", row.questions[3].question)
        self.assertIn("décision urgente", row.questions[3].question)
        self.assertNotIn("délais", row.questions[4].answer)
        self.assertEqual(row.questions[5].follow_up_to, 5)
        self.assertIn("résultats de vos projets", row.questions[5].question)

    def test_newcomer_conditions_are_advertised_examples_not_countrywide_promises(self):
        row = self.by_group["newcomer-canada-friend-job-market"]
        self.assertIn("profils de développeurs", row.questions[0].question)
        self.assertIn("tests techniques", row.questions[3].question)
        self.assertIn("IRCC", row.questions[4].answer)
        self.assertIn("Service Canada", row.questions[5].answer)
        self.assertIn("brut", row.questions[6].question)
        self.assertIn("annuel", row.questions[6].question)
        for detail in ("sur place", "hybride", "télétravail"):
            self.assertIn(detail, row.questions[7].question)
        self.assertIn("salary figures are illustrative", row.note)

    def test_private_teacher_and_school_separate_method_qualification_and_booking(self):
        private = self.by_group["newcomer-canada-private-french-teacher"]
        school = self.by_group["language-school-new-language"]
        self.assertIn("formation avez-vous suivie", private.questions[0].question)
        self.assertIn("mieux parler au quotidien", private.questions[1].question)
        self.assertIn("rejouons la conversation", private.questions[1].answer)
        self.assertIn("niveau au départ", private.questions[2].question)
        self.assertIn("annuler ou déplacer", private.questions[7].question)
        self.assertEqual(private.questions[7].follow_up_to, 7)
        self.assertIn("formation", school.questions[2].question)
        self.assertIn("jeux de rôle", school.questions[3].question)
        self.assertIn("sur place ou en ligne", school.questions[4].question)

    def test_school_and_parent_information_stays_with_the_actual_interlocutor(self):
        neighbour = self.by_group["edmonton-newcomer-neighbor-schools"]
        parent = self.by_group["parent-after-school-activity-advice"]
        self.assertIn("D'après votre expérience", neighbour.questions[3].question)
        self.assertIn("nouveaux élèves", neighbour.questions[4].question)
        self.assertIsNone(neighbour.questions[4].follow_up_to)
        self.assertIn("conseil scolaire", neighbour.questions[0].answer)
        self.assertIn("faites confirmer la liste", neighbour.questions[7].answer)
        self.assertIn("D'après ce que vous avez vu", parent.questions[4].question)
        self.assertIn("j'ai vu l'animatrice", parent.questions[4].answer)
        self.assertIn("tarifs actuels", parent.questions[7].answer)

    def test_child_stay_and_study_project_use_experience_not_guaranteed_admission(self):
        stay = self.by_group["friend-child-language-stay-abroad"]
        project = self.by_group["friend-planned-canadian-studies"]
        self.assertIn("Tom est-il parti", stay.questions[2].question)
        self.assertIn("combien de temps", stay.questions[2].question)
        self.assertIn("hébergement logeait Tom", stay.questions[4].question)
        self.assertEqual(stay.questions[5].follow_up_to, 5)
        self.assertIn("il nous disait", stay.questions[5].answer.lower())
        self.assertIn("Quel programme", project.questions[0].question)
        self.assertIn("ville", project.questions[1].question)
        self.assertIn("conditionnelle", project.questions[4].answer)
        self.assertIn("si je l'obtiens", project.questions[5].answer)
        self.assertNotIn("maîtrise", project.questions[3].question)

    def test_game_and_survey_establish_format_before_following_the_reply(self):
        game = self.by_group["french-teacher-language-school-student-game"]
        survey = self.by_group["french-class-survey-francophone-student"]
        self.assertIn("principe du jeu", game.questions[0].question)
        self.assertIn("niveaux", game.questions[1].question)
        self.assertEqual(game.questions[2].follow_up_to, 1)
        self.assertEqual(game.questions[3].follow_up_to, 1)
        self.assertIn("points", game.questions[3].question)
        self.assertIn("date", game.questions[5].question)
        self.assertIn("où la pratiquez-vous", survey.questions[5].question)
        self.assertEqual(survey.questions[6].follow_up_to, 6)
        self.assertIn("cette activité", survey.questions[6].question)
        self.assertNotIn("chorale", survey.questions[6].question)
