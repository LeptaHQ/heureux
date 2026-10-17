import hashlib
import json

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tests.housing_work_fixtures import ORIGINAL_HOUSING_GROUPS, ORIGINAL_WORK_GROUPS
from study.tests.neighbourhood_fixtures import ALL_NEIGHBOURHOOD_GROUPS


class TacheTwoWorkCorpusTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.dialogues = catalogue.tache_two_dialogues()
        self.by_group = {row.group: row for row in self.dialogues.values()}
        self.hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"]

    def test_original_work_review_keeps_thirty_publications_and_fifteen_archived_models(self):
        publications = {
            key: row for key, row in self.dialogues.items() if row.group in ORIGINAL_WORK_GROUPS
        }
        groups = {row.group for row in publications.values()}
        self.assertEqual(len(publications), 30)
        self.assertEqual(len(groups), 15)
        history = catalogue.tache_two_location_history()
        for group in groups:
            with self.subTest(group=group):
                before = history[group].revisions[-1]
                after = self.by_group[group]
                self.assertEqual(len(before.questions), 8)
                if group == "recruiter-scheduled-interview-preparation":
                    self.assertIn("ma venue", before.opening)
                    self.assertNotIn("ma venue", after.opening)
                else:
                    self.assertEqual(before.opening, after.opening)
                self.assertEqual(before.closing, after.closing)
                self.assertEqual(len(self.hints[group]), 8)

    def test_earlier_themes_remain_exactly_as_approved(self):
        _, themes = catalogue.tache_two_subject_themes()
        rows = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        expected = {
            "arrivee": "eeb337d3fd34d07c863b10f58fa4da53bae6f1b91822e56eaa8042170a48e278",
            "logement": "e650f8cfbd4e5c653958e7601692e2d4d0549302f09a4e9b9bdfa7f53f240847",
            "vie-quartier": "66a3ba25a77c86084bbe086370589b16b07d95e44ae16920194a4c9f7dbeb51a",
        }
        for theme, digest in expected.items():
            with self.subTest(theme=theme):
                groups = (
                    ALL_NEIGHBOURHOOD_GROUPS if theme == "vie-quartier" else
                    ORIGINAL_HOUSING_GROUPS if theme == "logement" else
                    {row.group for key, row in self.dialogues.items() if themes[key] == theme}
                )
                snapshot = json.dumps(
                    sorted((rows[group] for group in groups), key=lambda row: row["group"]),
                    ensure_ascii=False, sort_keys=True,
                ).encode()
                self.assertEqual(hashlib.sha256(snapshot).hexdigest(), digest)

    def test_questions_name_concrete_information_without_assuming_the_role(self):
        expected = {
            "new-employee-company-orientation": {
                4: ("responsable", "réunion d'équipe"),
                7: ("paie-t-on", "budget"),
                8: ("faire connaissance",),
            },
            "director-canada-fortnight-training": {
                1: ("ville", "dates"), 5: ("aéroport", "centre de formation"),
                6: ("vol", "hébergement", "repas", "déplacements"),
            },
            "friend-first-workday-report": {1: ("s'est passée", "à l'aise", "perdue")},
            "newcomer-canada-friend-job-market": {
                3: ("mettre en avant", "éviter"), 4: ("statut", "renseignements fiables"),
                5: ("numéro d'assurance sociale", "demande", "documents"),
                8: ("soir", "week-end", "horaires variables"),
            },
            "canadian-work-hours-home-country-comparison": {
                1: ("jours", "de quelle heure"), 3: ("pause déjeuner", "comptée"),
                7: ("ferme-t-elle", "équipes"),
            },
            "former-colleague-new-job-to-change-employment": {
                1: ("secteur", "poste"), 7: ("recrute", "consulter les offres"),
            },
            "new-colleague-quebec-career-migration": {
                5: ("logement", "démarches", "réseau"), 8: ("Québec", "réunions", "décisions"),
            },
            "recruiter-scheduled-interview-preparation": {
                5: ("étapes", "mise en situation"), 7: ("CV", "références", "réalisations"),
            },
            "colleague-internal-job-change": {
                1: ("tâches", "journées"), 2: ("combien de réunions", "journée"),
                3: ("horaires", "ancienne équipe"),
                5: ("Si ce n'est pas indiscret",),
            },
            "friend-upcoming-job-interview-advice": {
                3: ("questions du recruteur", "motivation", "points faibles"),
                6: ("sans donner l'impression de réciter",), 8: ("poser à la fin",),
            },
            "acquaintance-new-job-overall-experience": {
                6: ("assurance santé", "congés", "transports"), 7: ("Quelle part",),
            },
            "retirement-party-invitation": {6: ("Pour quand", "comment vous prévenir")},
            "supervisor-overseas-job-offer": {
                6: ("réévaluée", "coût de la vie"), 8: ("poste actuel", "poste équivalent"),
            },
            "friend-association-work-experience": {
                2: ("principales tâches",), 5: ("combien d'heures", "le soir"),
                6: ("s'ajoutent", "décales"), 8: ("sentiment d'être utile",),
            },
            "colleague-management-promotion-party": {6: ("venir accompagné", "réservée")},
        }
        for group, questions in expected.items():
            for number, phrases in questions.items():
                with self.subTest(group=group, question=number):
                    for phrase in phrases:
                        self.assertIn(phrase, self.by_group[group].questions[number - 1].question)

    def test_first_day_and_association_reorders_keep_clear_response_dependent_routes(self):
        day = self.by_group["friend-first-workday-report"]
        previous = catalogue.tache_two_location_history()[day.group].revisions[-1]
        for before, after in ((2, 4), (3, 5), (4, 2), (5, 3), (6, 6), (7, 7), (8, 8)):
            self.assertEqual(previous.questions[before - 1].question, day.questions[after - 1].question)
        self.assertEqual(day.questions[2].follow_up_to, 2)
        self.assertEqual(day.questions[4].follow_up_to, 4)
        self.assertIn("ne connaissais pas encore", day.questions[3].answer)
        self.assertEqual(
            [self.hints[day.group][index]["english"] for index in (1, 2, 3, 4)],
            [
                "How colleagues welcomed her", "Atmosphere within the team",
                "First tasks assigned to Ève", "Support with using the new software",
            ],
        )
        association = self.by_group["friend-association-work-experience"]
        self.assertEqual(association.questions[2].follow_up_to, 2)
        self.assertEqual(association.questions[5].follow_up_to, 5)
        self.assertEqual(association.questions[6].follow_up_to, 6)
        self.assertNotIn("recrutement", association.questions[1].question)
        self.assertNotIn("difficile", association.questions[7].question)
        self.assertIn("heures supplémentaires", association.questions[5].answer)
        self.assertEqual(
            self.hints[association.group][4]["english"], "Weekly working hours and evening work",
        )

    def test_advice_and_official_checks_keep_information_boundaries(self):
        friend = self.by_group["friend-upcoming-job-interview-advice"]
        recruiter = self.by_group["recruiter-scheduled-interview-preparation"]
        self.assertIn("they are not interviewing you", friend.note)
        self.assertIn("already scheduled", recruiter.note)
        self.assertIsNone(friend.questions[1].follow_up_to)
        self.assertNotEqual(friend.questions[2].question, friend.questions[7].question)
        newcomer = self.by_group["newcomer-canada-friend-job-market"]
        self.assertIn("not legal guarantees", newcomer.note)
        self.assertIn("IRCC", newcomer.questions[3].answer)
        self.assertIn("Service Canada", newcomer.questions[4].answer)
        self.assertIn("selon ton statut", newcomer.questions[4].answer)
        self.assertIn("liste complète", newcomer.questions[4].answer)
        self.assertEqual(newcomer.questions[4].follow_up_to, 4)
        self.assertNotIn("soir", newcomer.questions[6].answer)
        comparison = self.by_group["canadian-work-hours-home-country-comparison"]
        self.assertIn("not present one employer's arrangements as nationwide", comparison.note)
        self.assertIn("already work at this company", self.by_group[
            "new-employee-company-orientation"
        ].note)
        self.assertIn("within the same company", self.by_group["colleague-internal-job-change"].note)

    def test_training_replies_leave_the_transport_and_free_time_relances_open(self):
        row = self.by_group["director-canada-fortnight-training"]
        self.assertIn("voyages compris", row.questions[0].answer)
        self.assertNotIn("navette", row.questions[3].answer)
        self.assertIn("taxi", row.questions[4].answer)
        self.assertIn("navette", row.questions[4].answer)
        self.assertNotIn("soirées", row.questions[6].answer)
        self.assertEqual(row.questions[7].follow_up_to, 7)
        self.assertIn("16 h 30", row.questions[7].answer)
