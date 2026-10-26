import hashlib
import json

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tests.housing_work_fixtures import ORIGINAL_HOUSING_GROUPS
from study.tests.neighbourhood_fixtures import ALL_NEIGHBOURHOOD_GROUPS


REVIEW_REVISIONS = {
    "animal-protection-association-invitation": 0,
    "child-friends-family-holiday-invitation": 1,
    "colleague-babysitter-referral-needs": 1,
    "friend-entertain-visiting-nephews": 1,
    "friend-holiday-apartment-watch": 1,
    "friend-homeless-meal-volunteering": 1,
    "friend-three-year-old-weekend-care": 2,
    "grocery-store-home-delivery": 2,
    "help-friend-post-parcel": 2,
    "host-foreign-friends-city-advice": 1,
    "medical-secretary-temporary-replacement-doctor": 1,
    "neighbor-child-one-day-care": 1,
    "neighbor-dog-care-week-paid": 1,
    "neighbor-environmental-association-volunteering": 1,
    "neighbor-home-childcare-provider-referral": 1,
    "newcomer-local-acquaintance-meet-people": 0,
    "trusted-person-temporary-pet-care": 1,
    "visit-colleague-minor-accident": 1,
}

DEVELOPMENT_REVISIONS = {
    "animal-protection-association-invitation": 1,
    "child-friends-family-holiday-invitation": 2,
    "colleague-babysitter-referral-needs": 2,
    "friend-entertain-visiting-nephews": 2,
    "friend-holiday-apartment-watch": 2,
    "friend-homeless-meal-volunteering": 2,
    "friend-three-year-old-weekend-care": 3,
    "grocery-store-home-delivery": 3,
    "help-friend-post-parcel": 3,
    "medical-secretary-temporary-replacement-doctor": 2,
    "neighbor-child-one-day-care": 2,
    "neighbor-environmental-association-volunteering": 2,
    "neighbor-home-childcare-provider-referral": 2,
    "visit-colleague-minor-accident": 2,
}


class TacheTwoNeighbourhoodCorpusTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.dialogues = catalogue.tache_two_dialogues()
        self.by_group = {row.group: row for row in self.dialogues.values()}
        _, self.themes = catalogue.tache_two_subject_themes()
        self.hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"]
        self.history = json.loads(
            (content.QUESTION_BANK_DIR / "dialogue_history/locations.json").read_text(),
        )["groups"]

    def test_review_covers_eighteen_neighbourhood_models_and_thirty_six_publications(self):
        publications = [
            row for row in self.dialogues.values() if row.group in ALL_NEIGHBOURHOOD_GROUPS
        ]
        groups = {row.group for row in publications}
        self.assertEqual(len(publications), 36)
        self.assertEqual(groups, (set(REVIEW_REVISIONS) - {
            "newcomer-local-acquaintance-meet-people",
        }) | {
            "volunteer-local-association-information-office",
        })
        for row in publications:
            with self.subTest(group=row.group):
                self.assertEqual(len(row.questions), 8)
                self.assertEqual(len(self.hints[row.group]), 8)
                self.assertIn("merci", row.closing.lower())

    def test_arrival_and_housing_outside_the_later_authorized_reviews_are_unchanged(self):
        raw = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        expected = {
            "arrivee": "eeb337d3fd34d07c863b10f58fa4da53bae6f1b91822e56eaa8042170a48e278",
            "logement": "5856b77b61128d6d2b988dd3a589762ca8d8a5a7a04b1c6f8a17a3ba4b73a744",
        }
        for theme, digest in expected.items():
            with self.subTest(theme=theme):
                groups = (
                    ORIGINAL_HOUSING_GROUPS if theme == "logement" else
                    {row.group for key, row in self.dialogues.items() if self.themes[key] == theme}
                )
                snapshot = json.dumps(
                    [raw[group] for group in sorted(groups)],
                    ensure_ascii=False, sort_keys=True,
                ).encode()
                self.assertEqual(hashlib.sha256(snapshot).hexdigest(), digest)
        self.assertNotIn("new-resident-neighbor-neighborhood-orientation", self.history)
        self.assertEqual(
            len(self.history["volunteer-local-association-information-office"]["revisions"]), 4,
        )

    def test_all_eighteen_exact_previous_layouts_are_archived_without_hidden_answers(self):
        snapshots = []
        for group, revision in sorted(REVIEW_REVISIONS.items()):
            before = self.history[group]["revisions"][revision]
            snapshots.append(before)
            with self.subTest(group=group):
                self.assertEqual(set(before), {"group", "opening", "closing", "questions"})
                self.assertEqual(len(before["questions"]), 8)
                for question in before["questions"]:
                    self.assertLessEqual(
                        set(question), {"topic", "question", "follow_up_to", "condition"},
                    )
        snapshot = json.dumps(snapshots, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "38daa5beaf13a09fcd8f09db4d648eb5bd7e7dab4070ce90cf127fd7fb9de63e",
        )

    def test_city_route_separates_visits_shared_activities_restaurants_and_transport(self):
        row = self.by_group["host-foreign-friends-city-advice"]
        self.assertEqual(
            [question.topic for question in row.questions],
            ["Visite culturelle"] * 2 + ["Activités à partager"] * 2
            + ["Restaurants et budget"] * 2 + ["Déplacements"] * 2,
        )
        self.assertIn("au bord de l'eau ou dans un parc", row.questions[2].question)
        for question in row.questions:
            self.assertNotIn("Dans quel ordre", question.question)
            self.assertNotIn("quels endroits", question.question)
        for question in row.questions[:6]:
            self.assertNotRegex(question.question, r"trajets|s'y rendre|transports en commun")
        self.assertIn("à pied", row.questions[6].question)
        self.assertIn("en transports en commun", row.questions[6].question)
        self.assertIn("acheter un pass à la journée", row.questions[7].question)
        self.assertEqual(row.questions[7].follow_up_to, 7)
        self.assertIn("aller-retour en bus", row.questions[7].answer)
        self.assertIn("lignes prévues", row.questions[7].answer)

    def test_developments_archive_all_fourteen_exact_published_layouts_once(self):
        snapshots = []
        for group, revision in sorted(DEVELOPMENT_REVISIONS.items()):
            with self.subTest(group=group):
                revisions = self.history[group]["revisions"]
                self.assertEqual(
                    len(revisions),
                    revision + (3 if group in {
                        "friend-holiday-apartment-watch", "grocery-store-home-delivery",
                        "visit-colleague-minor-accident",
                    } else 2 if group in {
                        "colleague-babysitter-referral-needs",
                        "friend-homeless-meal-volunteering",
                        "help-friend-post-parcel",
                        "child-friends-family-holiday-invitation",
                    } else 1),
                )
                previous = revisions[revision]
                self.assertEqual(revisions.count(previous), 1)
                self.assertEqual(set(previous), {"group", "opening", "closing", "questions"})
                self.assertEqual(len(previous["questions"]), 8)
                for question in previous["questions"]:
                    self.assertNotIn("answer", question)
                snapshots.append(previous)
        snapshot = json.dumps(snapshots, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "70c0d8597ac6451b3f4a1ecb89f47f579f8256c066f405eccd6acbd5fda44c8f",
        )

    def test_previously_developed_routes_keep_their_exact_approved_visible_wording(self):
        protected = {
            "host-foreign-friends-city-advice",
            "neighbor-dog-care-week-paid",
            "trusted-person-temporary-pet-care",
            "volunteer-local-association-information-office",
        }
        raw = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
            if row["group"] in protected
        }
        snapshots = [
            {
                "group": group, "opening": raw[group]["opening"], "closing": raw[group]["closing"],
                "questions": [
                    {key: value for key, value in question.items() if key != "answer"}
                    for question in raw[group]["questions"]
                ],
            }
            for group in sorted(protected)
        ]
        snapshot = json.dumps(snapshots, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "4e5389b996ea9bc7ca6975cdd89b6cc4281153c129c63fbb9b8a8211ac0b588c",
        )

    def test_previous_city_and_dog_layouts_are_archived_exactly(self):
        expected = {
            "host-foreign-friends-city-advice":
                "093bfa2c772f100ba890fd0bd4d11f80928fb979095a98d62d6296e6f40fc4ce",
            "neighbor-dog-care-week-paid":
                "aa3b80a62d55b3d69a78a18dc6e9369be1bf0fa27dcf4b8a029a636426b61902",
        }
        for group, digest in expected.items():
            with self.subTest(group=group):
                before = self.history[group]["revisions"][2]
                snapshot = json.dumps(before, ensure_ascii=False, sort_keys=True).encode()
                self.assertEqual(hashlib.sha256(snapshot).hexdigest(), digest)
                self.assertEqual(
                    len(self.history[group]["revisions"]),
                    4 if group == "neighbor-dog-care-week-paid" else 3,
                )

    def test_previous_friend_pet_and_office_layouts_are_archived_exactly(self):
        expected = {
            "trusted-person-temporary-pet-care":
                "02e0cc074fa1690558a88166b655e024c1aede017d8e044c2be6d3fea4f31210",
            "volunteer-local-association-information-office":
                "833b236ba0714be73c2a638bbe99d1707a8b70b28dd985caa95b279b5ef52c9b",
        }
        for group, digest in expected.items():
            with self.subTest(group=group):
                before = self.history[group]["revisions"][2]
                snapshot = json.dumps(before, ensure_ascii=False, sort_keys=True).encode()
                self.assertEqual(hashlib.sha256(snapshot).hexdigest(), digest)
                self.assertEqual(
                    len(self.history[group]["revisions"]),
                    4 if group == "volunteer-local-association-information-office" else 3,
                )

    def test_exact_food_aid_layout_is_archived_before_following_a_cultural_association(self):
        before = self.history["volunteer-local-association-information-office"]["revisions"][3]
        snapshot = json.dumps(before, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "b6581d4816f7e566429215aa30079321b39de48fd671c59a997bca3af994866e",
        )

    def test_city_visit_opens_with_culture_and_keeps_every_piste_aligned(self):
        row = self.by_group["host-foreign-friends-city-advice"]
        before = self.history[row.group]["revisions"][2]
        self.assertEqual(
            row.questions[0].question,
            "Quelle activité leur permettrait de mieux comprendre l'histoire et la culture de la région ?",
        )
        self.assertEqual(
            row.questions[0].question, before["questions"][2]["question"],
        )
        self.assertEqual(
            [cue["english"] for cue in self.hints[row.group]],
            [
                "Activity about regional history and culture",
                "Recommended activity's duration and advance booking",
                "Waterfront or park walk",
                "Activities to do together at home if it rains",
                "Welcoming restaurant serving local specialties",
                "Per-person meal budget including a drink, taxes and tip",
                "Recommended walking legs and public-transport legs",
                "Individual tickets or a day pass for the planned journeys",
            ],
        )
        self.assertEqual(len(self.history[row.group]["revisions"]), 3)
        self.assertIn("Seattle is an example", row.note)
        self.assertIn("with them, not this friend", row.note)
        self.assertIn("simulation examples to verify", row.note)
        self.assertEqual(row.questions[1].follow_up_to, 1)
        self.assertIn("combien de temps", row.questions[1].question)
        self.assertIn("réserver à l'avance", row.questions[1].question)
        self.assertIn("without its duration or advance-booking advice", row.questions[1].condition)
        self.assertIn("deux heures", row.questions[1].answer)
        self.assertIn("conditions pour vos dates", row.questions[1].answer)
        self.assertEqual(row.questions[5].follow_up_to, 5)
        self.assertIn("taxes et pourboire compris", row.questions[5].question)
        self.assertIn("dollars américains", row.questions[5].answer)
        self.assertIn("taxes et pourboire compris", row.questions[5].answer)
        self.assertIn("estimation", row.questions[5].answer)
        self.assertNotIn("journée autour", row.closing)

    def test_rainy_day_questions_distinguish_staying_home_from_indoor_outings(self):
        city = self.by_group["host-foreign-friends-city-advice"]
        self.assertIn("S'il pleut et qu'on préfère rester à la maison", city.questions[3].question)
        self.assertIn("ensemble", city.questions[3].question)
        self.assertIn("MOHAI", city.questions[0].answer)
        self.assertNotIn("MOHAI", city.questions[3].answer)
        self.assertIn("cuisiner ensemble", city.questions[3].answer)
        self.assertIn("jeu d'observation", city.questions[3].answer)
        self.assertIn("à la maison", self.hints[city.group][3]["french"])
        self.assertIn("at home", self.hints[city.group][3]["english"])
        nephews = self.by_group["friend-entertain-visiting-nephews"]
        self.assertIn("où pourrais-je les emmener", nephews.questions[4].question)
        self.assertIn("atelier ou une exposition interactive", nephews.questions[4].question)
        self.assertIn("cuisson", nephews.questions[0].answer)
        self.assertIn("indices dessinés", nephews.questions[2].answer)
        self.assertIn("without explaining the preparation", nephews.questions[1].condition)
        self.assertIn("Their ages and interests are not supplied", nephews.note)

    def test_pet_care_clarifies_presence_instead_of_implying_two_brief_daily_visits(self):
        pet = self.by_group["trusted-person-temporary-pet-care"]
        self.assertIn("quel âge", pet.questions[0].question)
        self.assertIn("combien de temps peut-il rester seul", pet.questions[2].question)
        for detail in ("la nuit", "présence en journée", "quatre heures"):
            self.assertIn(detail, pet.questions[2].answer)
        self.assertIn("sortie de dix minutes à midi", pet.questions[4].answer)
        self.assertIn("adapt walks and overnight presence", pet.note)
        paid = self.by_group["neighbor-dog-care-week-paid"]
        self.assertIn("présence la nuit", paid.questions[1].question)
        self.assertIn("Trois sorties", paid.questions[3].answer)
        self.assertIn("allergies", paid.questions[5].question)
        self.assertIn("soins particuliers", paid.questions[5].question)
        self.assertIn("aucun soin particulier", paid.questions[5].answer)
        self.assertIn("280 $ pour la semaine", paid.questions[7].answer)
        self.assertIn("dimanche soir, à mon retour", paid.questions[7].answer)
        self.assertIn("avant de vous confirmer", paid.closing)

    def test_friend_pet_care_uses_the_same_practical_goals_without_assuming_a_paid_dog_job(self):
        group = "trusted-person-temporary-pet-care"
        publications = [row for row in self.dialogues.values() if row.group == group]
        self.assertEqual(len(publications), 5)
        for row in publications:
            with self.subTest(note=row.note):
                self.assertEqual(row.register, "tu")
                self.assertEqual(
                    row.questions[0].question, "Quel animal vas-tu me confier, et quel âge a-t-il ?",
                )
                self.assertTrue(row.questions[3].question.startswith("Côté alimentation,"))
                self.assertIn("me laisseras-tu sa nourriture ou devrai-je l'acheter", row.questions[3].question)
                self.assertIn("à quelles heures", row.questions[3].question)
                self.assertIn("Je te laisserai ses croquettes", row.questions[3].answer)
                self.assertIn("8 h et à 18 h", row.questions[3].answer)
                self.assertIn("sorties ou de séances de jeu", row.questions[4].question)
                self.assertIn("combien de temps doit durer chacune", row.questions[4].question)
                self.assertIn("sortie de dix minutes à midi", row.questions[4].answer)
                self.assertIn("deux séances de jeu de dix minutes", row.questions[4].answer)
                self.assertIn("allergies à connaître", row.questions[6].question)
                self.assertIn("soins particuliers", row.questions[6].question)
                self.assertIn("ton absence", row.questions[6].question)
                self.assertIn("Aucune allergie connue", row.questions[6].answer)
                self.assertIn("sociable avec les personnes qu'il ne connaît pas", row.questions[5].question)
                self.assertIn("sociable avec les inconnus", row.questions[5].answer)
                self.assertEqual(row.questions[5].follow_up_to, 5)
                self.assertIn("without explaining behaviour around strangers", row.questions[5].condition)
                self.assertIn("adapt to the animal named", row.questions[5].condition)
                self.assertIn("vétérinaire", row.questions[7].question)
                self.assertEqual(
                    [question.topic for question in row.questions],
                    ["Organisation de la garde"] * 3 + ["Besoins quotidiens"] * 3
                    + ["Santé et urgence"] * 2,
                )
                self.assertFalse(any(
                    word in question.question.lower()
                    for question in row.questions for word in ("rémunération", "salaire", "paiement")
                ))
        self.assertEqual(
            [cue["english"] for cue in self.hints[group][3:7]],
            [
                "Food left by the owner or to buy, and feeding times",
                "Daily number of outings or play sessions and duration of each",
                "Behaviour on walks and sociability with unfamiliar people",
                "Known allergies, special care or treatment during the absence",
            ],
        )
        self.assertIn(
            "not yet agreed", self.dialogues["tache2:septembre:batch-05:subject-22"].note,
        )
        self.assertIn(
            "Do not assume walks or overnight care",
            self.dialogues["tache2:septembre:batch-06:subject-27"].note,
        )

    def test_volunteer_task_question_asks_about_assignments_within_the_officers_role(self):
        row = self.by_group["volunteer-local-association-information-office"]
        self.assertIn("associations culturelles", row.questions[0].answer)
        self.assertEqual(
            row.questions[1].question,
            "L'association culturelle m'intéresse. Quelles activités propose-t-elle, et à quel public s'adressent-elles ?",
        )
        self.assertEqual(row.questions[1].follow_up_to, 1)
        self.assertIn("If a cultural association is mentioned", row.questions[1].condition)
        for detail in ("ateliers de théâtre", "adolescents", "projections de films", "tous les habitants"):
            self.assertIn(detail, row.questions[1].answer)
        self.assertEqual(
            row.questions[2].question,
            "Quelles missions sont confiées aux bénévoles dans cette association ?",
        )
        self.assertIn("does not necessarily run", row.note)
        self.assertIn("cultural association mentioned by the officer", row.note)
        self.assertIn("otherwise adapt the choice", row.note)
        self.assertIn("simulation examples to confirm", row.note)
        self.assertIn("Préparer les salles", row.questions[2].answer)
        self.assertIn("les ateliers et les projections", row.questions[2].answer)
        self.assertIn("18 h à 20 h", row.questions[3].answer)
        self.assertIn("14 h à 17 h", row.questions[3].answer)
        self.assertEqual(
            row.questions[4].question,
            "Puis-je participer ponctuellement, sans m'engager pour plusieurs mois ?",
        )
        self.assertTrue(row.questions[4].answer.startswith("Pour ces missions, non :"))
        self.assertIn("pendant trois mois", row.questions[4].answer)
        self.assertIn("pour une aide ponctuelle", row.questions[4].answer)
        self.assertEqual(
            self.hints[row.group][1]["english"],
            "Cultural association's activities and intended audiences",
        )
        self.assertEqual(
            self.hints[row.group][2]["english"], "Tasks assigned to volunteers",
        )
        self.assertEqual(
            self.hints[row.group][4]["english"],
            "Possibility of occasional help without a commitment lasting several months",
        )
        self.assertEqual(
            row.questions[7].question,
            "Pourrais-je rencontrer l'équipe et observer un atelier avant de m'engager régulièrement ?",
        )
        self.assertIn("sur rendez-vous", row.questions[7].answer)
        self.assertIn("l'association confirmera le créneau", row.questions[7].answer)
        self.assertIn("les consignes avant votre venue", row.questions[7].answer)
        self.assertIsNone(row.questions[7].follow_up_to)
        self.assertEqual(row.questions[1].follow_up_to, 1)
        self.assertEqual(
            self.hints[row.group][7]["english"],
            "Meeting the team and observing a workshop before committing",
        )

    def test_paid_dog_routine_distinguishes_walk_frequency_from_behaviour_with_unfamiliar_people(self):
        row = self.by_group["neighbor-dog-care-week-paid"]
        self.assertEqual(
            row.questions[2].question,
            "Fournirez-vous sa nourriture ou devrai-je m'en occuper, et à quelles heures prend-il ses repas ?",
        )
        self.assertIn("Je fournirai ses croquettes", row.questions[2].answer)
        self.assertIn("8 h et à 18 h", row.questions[2].answer)
        self.assertEqual(
            self.hints[row.group][2]["english"],
            "Who provides the food and feeding times",
        )
        walks, behaviour = row.questions[3:5]
        self.assertEqual(
            walks.question,
            "À quelle fréquence faut-il le promener, et combien de temps prévoir pour chaque sortie ?",
        )
        self.assertIn("Trois sorties par jour", walks.answer)
        self.assertIn("trente minutes", walks.answer)
        self.assertIn("dix minutes vers midi", walks.answer)
        self.assertEqual(
            behaviour.question,
            "Comment se comporte-t-il pendant les promenades, et est-il sociable avec les personnes qu'il ne connaît pas ?",
        )
        self.assertEqual(behaviour.follow_up_to, 4)
        self.assertIn("has not been explained", behaviour.condition)
        self.assertIn("calme en laisse", behaviour.answer)
        self.assertIn("sociable avec les personnes", behaviour.answer)
        self.assertIn("nerveux avec les grands chiens", behaviour.answer)
        self.assertEqual(
            [cue["english"] for cue in self.hints[row.group][3:5]],
            [
                "Walk frequency and time to allow for each outing",
                "Behaviour on walks and sociability with unfamiliar people",
            ],
        )
        self.assertEqual(
            row.questions[7].question,
            "Quelle rémunération avez-vous prévue pour la garde, et sera-t-elle versée avant votre départ ou à votre retour ?",
        )
        self.assertEqual(
            self.hints[row.group][7]["english"], "Pay and payment before departure or on return",
        )

    def test_dog_health_and_payment_refinement_keeps_exact_previous_layout(self):
        before = self.history["neighbor-dog-care-week-paid"]["revisions"][3]
        snapshot = json.dumps(before, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "22e0da946de86941a1b8d100e6c28a6537c11ae4c1c3ea2793299bf6a857f92e",
        )

    def test_childcare_meal_and_sleep_arrangements_are_actionable(self):
        weekend = self.by_group["friend-three-year-old-weekend-care"]
        self.assertIn("fourniras-tu ses repas et ses goûters", weekend.questions[0].question)
        self.assertIn("devrai-je m'en occuper", weekend.questions[0].question)
        for timing in ("8 h", "midi", "18 h 30", "16 h"):
            self.assertIn(timing, weekend.questions[0].answer)
        self.assertIn("Puis-je l'emmener", weekend.questions[3].question)
        self.assertTrue(weekend.questions[3].answer.startswith("Oui"))
        day = self.by_group["neighbor-child-one-day-care"]
        self.assertIn("Fournirez-vous le repas et le goûter", day.questions[3].question)
        self.assertIn("devrai-je les prévoir", day.questions[3].question)
        self.assertIn("midi", day.questions[3].answer)
        self.assertIn("16 h", day.questions[3].answer)
        self.assertIn("sieste ou un temps calme", day.questions[4].question)
        self.assertIn("après le repas", day.questions[4].answer)
        self.assertIn("nos deux numéros", day.questions[7].answer)
        self.assertIn("already agreed", day.note)

    def test_childcare_referrals_cover_location_and_full_calendar_without_guarantees(self):
        colleague = self.by_group["colleague-babysitter-referral-needs"]
        for detail in ("Quels jours et horaires", "à partir de quand", "pour quelle durée"):
            self.assertIn(detail, colleague.questions[1].question)
        self.assertIn("Dans quel quartier", colleague.questions[2].question)
        self.assertIn("chez vous ou chez la personne recommandée", colleague.questions[2].question)
        provider = self.by_group["neighbor-home-childcare-provider-referral"]
        self.assertEqual(
            provider.questions[3].question,
            "Dans quels quartiers propose-t-elle ses services, et garde-t-elle les enfants chez les parents ou chez elle ?",
        )
        self.assertEqual(self.hints[provider.group][3], {
            "french": "Quartiers où elle propose ses services et lieu de garde",
            "english": "Neighbourhoods she covers and childcare at the parents' or caregiver's home",
        })
        self.assertIn("D'après ce que vous savez", provider.questions[4].question)
        self.assertIn("disponibilités actuelles", provider.questions[4].answer)
        self.assertIn("tarif actuel", provider.questions[6].answer)
        self.assertIn("avec son accord", provider.questions[7].answer)

    def test_babysitter_first_meeting_includes_children_before_confirming_care(self):
        row = self.by_group["colleague-babysitter-referral-needs"]
        self.assertEqual(
            row.questions[7].question,
            "Souhaitez-vous prévoir une première rencontre entre la personne et vos enfants avant de confirmer la garde ?",
        )
        self.assertTrue(row.questions[7].answer.startswith("Oui"))
        self.assertIn("avec les enfants", row.questions[7].answer)
        self.assertEqual(
            self.hints[row.group][7]["english"],
            "Initial meeting with the children before confirming childcare",
        )
        before = self.history[row.group]["revisions"][3]
        self.assertEqual(
            [question.question for question in row.questions[:7]],
            [question["question"] for question in before["questions"][:7]],
        )
        snapshot = json.dumps(before, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "db69186b38b31c111e404f88150dfc1c7297cc54f033d47c432b1ac98872a21e",
        )

    def test_holiday_child_safety_checks_actual_arrangements_not_only_reassurance(self):
        row = self.by_group["child-friends-family-holiday-invitation"]
        self.assertIn("quels équipements de sécurité", row.questions[3].question)
        self.assertIn("Combien d'enfants", row.questions[4].question)
        self.assertIn("quels adultes", row.questions[4].question)
        self.assertIn("Trois enfants", row.questions[4].answer)
        self.assertIn("chaque enfant", row.questions[6].question)
        self.assertIn("gilet de sauvetage adapté à sa taille", row.questions[6].question)
        self.assertIn("pendant toute l'activité", row.questions[6].answer)
        self.assertEqual(row.questions[6].follow_up_to, 6)

    def test_apartment_checks_include_plant_quantities_and_a_single_backup_contact_question(self):
        row = self.by_group["friend-holiday-apartment-watch"]
        self.assertIn("Quelles plantes dois-je arroser", row.questions[2].question)
        self.assertIn("quelle quantité d'eau", row.questions[2].question)
        self.assertIn("à chacune à chaque passage", row.questions[2].question)
        self.assertEqual(row.questions[2].follow_up_to, 2)
        self.assertIn("cactus", row.questions[2].answer)
        self.assertIn("code d'accès", row.questions[4].question)
        self.assertIn("qui pourrai-je contacter sur place", row.questions[6].question)
        self.assertNotIn("double des clés", " ".join(q.question for q in row.questions))
        self.assertIn("même si tout va bien", row.questions[7].question)
        self.assertEqual(
            self.hints[row.group][2]["english"],
            "Plants to water and amount per plant at each visit",
        )

    def test_apartment_watering_follows_tasks_and_keeps_the_exact_previous_layout(self):
        group = "friend-holiday-apartment-watch"
        publications = [row for row in self.dialogues.values() if row.group == group]
        self.assertEqual(len(publications), 3)
        before = self.history[group]["revisions"][3]
        for row in publications:
            with self.subTest(note=row.note):
                self.assertEqual(
                    row.questions[2].question,
                    "Quelles plantes dois-je arroser, et quelle quantité d'eau faut-il donner à chacune à chaque passage ?",
                )
                self.assertEqual(row.questions[2].follow_up_to, 2)
                self.assertIn("If watering is requested", row.questions[2].condition)
                self.assertIn("150 millilitres chacune à chaque passage", row.questions[2].answer)
                self.assertIn("N'arrose pas les cactus", row.questions[2].answer)
                self.assertEqual(row.questions[3].question, before["questions"][2]["question"])
                self.assertEqual(
                    [row.questions[index].question for index in (0, 1, 4)],
                    [before["questions"][index]["question"] for index in (0, 1, 4)],
                )
        self.assertEqual(
            self.hints[group][3]["english"], "Visit frequency and time needed for each visit",
        )
        snapshot = json.dumps(before, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "8c1d725384db04d318251f2a7f5f04386cc1be3bf74a6a23fd84bd5a2e815ef3",
        )

    def test_apartment_security_and_contacts_replace_the_exact_previous_wording(self):
        group = "friend-holiday-apartment-watch"
        before = self.history[group]["revisions"][4]
        snapshot = json.dumps(before, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "51319b1d2072ee386f5ebb689b732ff998d8b323d0dad4baee856ce9039a5783",
        )
        for row in (row for row in self.dialogues.values() if row.group == group):
            self.assertEqual(len(row.questions), 8)
            self.assertEqual(
                [q.question for q in row.questions[:5]],
                [q["question"] for q in before["questions"][:5]],
            )
            self.assertIn("après chaque visite", row.questions[5].question)
            self.assertIn("quelles consignes particulières", row.questions[5].question)
            self.assertEqual(
                row.questions[6].question,
                "Seras-tu joignable pendant ton absence et, sinon, qui pourrai-je contacter sur place en cas de problème ?",
            )
            self.assertIn("concierge", row.questions[6].answer)
            self.assertIn("même si tout va bien", row.questions[7].question)
        self.assertEqual(
            self.hints[group][7]["english"],
            "Routine updates after visits, even when nothing is wrong",
        )

    def test_volunteering_covers_real_shifts_commitment_and_arrival(self):
        meals = self.by_group["friend-homeless-meal-volunteering"]
        self.assertIn("Où ont lieu", meals.questions[0].question)
        self.assertIn("préparation et rangement compris", meals.questions[0].answer)
        animals = self.by_group["animal-protection-association-invitation"]
        self.assertIn("personnes qui souhaitent adopter", animals.questions[1].question)
        self.assertIn("ponctuellement", animals.questions[4].question)
        self.assertIn("durée minimale", animals.questions[4].question)
        self.assertIn("trois mois", animals.questions[4].answer)
        self.assertIn("sur place ou en ligne", animals.questions[6].question)
        self.assertEqual(animals.questions[6].follow_up_to, 6)
        environment = self.by_group["neighbor-environmental-association-volunteering"]
        self.assertIn("explications et un accompagnement", environment.questions[5].question)
        self.assertEqual(
            environment.questions[7].question,
            "Où est le point de rendez-vous, et comment serai-je prévenu en cas d'annulation ?",
        )
        self.assertEqual(self.hints[environment.group][7], {
            "french": "Point de rendez-vous et notification en cas d'annulation",
            "english": "Meeting point and how participants are notified of cancellation",
        })
        self.assertIn("quinze minutes avant 9 h", environment.questions[7].answer)
        self.assertIn("Confirmez ces détails lors de l'inscription", environment.questions[7].answer)

    def test_meal_volunteering_checks_availability_before_distinct_general_and_beginner_tasks(self):
        group = "friend-homeless-meal-volunteering"
        publications = [row for row in self.dialogues.values() if row.group == group]
        self.assertEqual(len(publications), 2)
        before = self.history[group]["revisions"][3]
        for row in publications:
            with self.subTest(note=row.note):
                self.assertEqual(
                    [question.topic for question in row.questions],
                    ["Lieu et disponibilités"] * 2 + ["Organisation et missions"] * 2
                    + ["Conditions et inscription"] * 4,
                )
                self.assertEqual(row.questions[0].question, before["questions"][2]["question"])
                self.assertEqual(row.questions[1].question, before["questions"][3]["question"])
                self.assertEqual(
                    row.questions[2].question,
                    "Les bénévoles participent-ils aussi à la préparation des repas, ou seulement à leur distribution ?",
                )
                self.assertIn("arrivent déjà cuisinés", row.questions[2].answer)
                self.assertIn("prépare les portions", row.questions[2].answer)
                self.assertEqual(row.questions[3].question, before["questions"][1]["question"])
                self.assertEqual(row.questions[3].follow_up_to, 3)
                self.assertIn("without specifying beginners' tasks", row.questions[3].condition)
                self.assertEqual(
                    [question.question for question in row.questions[4:]],
                    [question["question"] for question in before["questions"][4:]],
                )
                self.assertIn("First check location, full shifts and attendance notice", row.note)
                self.assertFalse(any("du début à la fin" in q.question for q in row.questions))
        self.assertEqual(
            self.hints[group][:4],
            [
                {
                    "french": "Lieu des distributions, jours et horaires de présence",
                    "english": "Distribution location, days and full volunteer shift",
                },
                {
                    "french": "Participation ponctuelle et délai pour confirmer sa présence",
                    "english": "Occasional participation and notice for confirming attendance",
                },
                {
                    "french": "Préparation des repas ou distribution uniquement",
                    "english": "Meal preparation or distribution only",
                },
                {
                    "french": "Première tâche confiée aux nouveaux",
                    "english": "First task given to new volunteers",
                },
            ],
        )
        snapshot = json.dumps(before, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "63cceefb4f3d85998007f59786782c9abf842a10696744bb9270d5d8c834e905",
        )

    def test_meeting_people_moves_from_recurring_groups_to_a_concrete_meeting(self):
        row = self.by_group["newcomer-local-acquaintance-meet-people"]
        self.assertIn("participer régulièrement", row.questions[2].question)
        self.assertIn("Je participe souvent aux randonnées", row.questions[2].answer)
        self.assertIn("essai avant d'adhérer", row.questions[5].question)
        self.assertEqual(row.questions[5].follow_up_to, 3)
        self.assertIn("quels sujets", row.questions[6].question)
        self.assertIn("Si vous allez", row.questions[7].question)
        self.assertIn("où et à quelle heure", row.questions[7].question)
        self.assertIn("dimanche à 9 h devant la bibliothèque", row.closing)

    def test_delivery_questions_cover_payment_and_a_concrete_delivery_window(self):
        row = self.by_group["grocery-store-home-delivery"]
        self.assertIn("les courses et les frais de livraison", row.questions[1].question)
        self.assertIn("en caisse ou auprès du livreur", row.questions[1].question)
        self.assertIn("par carte ou en espèces", row.questions[1].question)
        self.assertNotIn("passe-t-on commande", row.questions[1].question)
        self.assertNotIn("en ligne", row.questions[1].question)
        self.assertIn("en caisse, par carte ou en espèces", row.questions[1].answer)
        self.assertIn("ne proposons pas de paiement au livreur", row.questions[1].answer)
        self.assertEqual(
            row.questions[4].question,
            "Puis-je choisir un créneau de livraison, par exemple entre 14 h et 16 h ?",
        )
        self.assertNotIn("combien de temps dure", row.questions[4].question)
        self.assertIn("de 14 h à 16 h", row.questions[4].answer)
        self.assertIn("créneaux disponibles", row.questions[4].answer)
        self.assertNotIn("duration", row.questions[4].condition)
        self.assertEqual(row.questions[4].follow_up_to, 4)
        self.assertIn("nouvelle livraison coûte", row.questions[6].answer)

    def test_grocery_cost_question_checks_the_free_delivery_threshold_not_order_eligibility(self):
        row = self.by_group["grocery-store-home-delivery"]
        question = row.questions[2]
        self.assertIn("selon le montant des achats", question.question)
        self.assertIn("montant minimum pour bénéficier de la livraison gratuite", question.question)
        self.assertNotIn("minimum de commande", question.question)
        self.assertIn("7,99 $", question.answer)
        self.assertIn("gratuite à partir de 100 $", question.answer)
        self.assertNotIn("50 $", question.answer)
        self.assertIn("not how to order online", row.note)
        self.assertIn("free-delivery threshold", row.note)
        self.assertEqual(
            self.hints[row.group][2]["english"],
            "Delivery fees by basket value and minimum spend for free delivery",
        )

    def test_remuneration_development_distinguishes_employer_from_referrer_and_favours(self):
        colleague = self.by_group["colleague-babysitter-referral-needs"]
        self.assertEqual(
            colleague.questions[6].question,
            "Quelle rémunération proposez-vous pour cette garde, et comment et quand sera-t-elle versée ?",
        )
        self.assertIn("18 $ de l'heure", colleague.questions[6].answer)
        self.assertIn("par virement après chaque garde", colleague.questions[6].answer)
        self.assertNotIn("départ", colleague.questions[6].question)
        self.assertEqual(
            self.hints[colleague.group][6]["english"], "Proposed pay, payment method and timing",
        )
        referrer = self.by_group["neighbor-home-childcare-provider-referral"]
        self.assertIn("Savez-vous quel tarif", referrer.questions[6].question)
        self.assertIn("après chaque garde ou en fin de mois", referrer.questions[6].question)
        self.assertIn("D'après ce que vous savez", referrer.questions[5].question)
        self.assertIn("repas doivent-ils être fournis par les parents", referrer.questions[5].question)
        self.assertNotIn("chez vous", referrer.questions[5].question)
        self.assertIn("Do not assume the neighbour has employed this person", referrer.note)
        self.assertIn("par virement après chaque garde", referrer.questions[6].answer)
        self.assertIn("confirmera son tarif actuel", referrer.questions[6].answer)
        self.assertIn("ses modalités de paiement", referrer.questions[6].answer)
        for group in (
            "friend-three-year-old-weekend-care", "neighbor-child-one-day-care",
            "friend-holiday-apartment-watch", "trusted-person-temporary-pet-care",
            "help-friend-post-parcel",
        ):
            with self.subTest(group=group):
                for question in self.by_group[group].questions:
                    self.assertNotRegex(question.question.lower(), r"salaire|rémunération")
        parcel = self.by_group["help-friend-post-parcel"]
        self.assertIn("l'argent avant le dépôt", parcel.questions[6].question)
        self.assertIn("tu n'auras rien à avancer", parcel.questions[6].answer)
        self.assertIn("postage funding is not remuneration", parcel.note)

    def test_childcare_development_covers_behaviour_health_rest_and_parent_availability(self):
        weekend = self.by_group["friend-three-year-old-weekend-care"]
        self.assertEqual(
            [row.topic for row in weekend.questions],
            ["Repas et santé"] * 2 + ["Jeux, sorties et comportement"] * 3
            + ["Sommeil"] * 2 + ["Disponibilité et contacts"],
        )
        self.assertIn("soins particuliers", weekend.questions[1].question)
        self.assertIn("personnes qu'elle connaît peu", weekend.questions[4].question)
        self.assertIn("s'entend-elle bien avec les autres enfants", weekend.questions[4].question)
        self.assertIn("Seras-tu joignable pendant tout le week-end", weekend.questions[7].question)
        self.assertIn("qui pourrai-je contacter en cas de souci", weekend.questions[7].question)
        self.assertIn("sa grand-mère", weekend.questions[7].answer)
        day = self.by_group["neighbor-child-one-day-care"]
        self.assertIn("allergies", day.questions[1].question)
        self.assertIn("s'entend-il bien avec les autres enfants", day.questions[2].question)
        self.assertIn("habitudes pour aider votre enfant à se reposer", day.questions[4].question)
        self.assertIn("Pas de sieste", day.questions[4].answer)
        self.assertIn("joignable pendant toute la garde", day.questions[7].question)
        self.assertFalse(any("coucher" in row.question for row in day.questions))
        self.assertEqual(
            self.hints[weekend.group][4]["english"],
            self.hints[day.group][2]["english"],
        )

    def test_holiday_costs_are_a_contribution_with_inclusions_and_payment_timing(self):
        row = self.by_group["child-friends-family-holiday-invitation"]
        self.assertIn("dates du séjour", row.questions[0].question)
        self.assertIn("Où comptez-vous", row.questions[0].question)
        self.assertIn("Quel hébergement", row.questions[1].question)
        self.assertIn("réservation à faire de mon côté", row.questions[1].question)
        self.assertIn("déjà réservé", row.questions[1].answer)
        self.assertIn("rien à réserver", row.questions[1].answer)
        self.assertIn("Combien dois-je vous donner", row.questions[2].question)
        self.assertIn("quels frais sont compris", row.questions[2].question)
        self.assertIn("avant le départ", row.questions[2].question)
        for detail in ("150 $", "repas et toutes les activités", "transport et le chalet"):
            self.assertIn(detail, row.questions[2].answer)
        self.assertIn("Pas en permanence", row.questions[7].answer)
        self.assertIn("nos deux numéros", row.questions[7].answer)
        nephews = self.by_group["friend-entertain-visiting-nephews"]
        self.assertIn("entrées des enfants et des adultes", nephews.questions[5].question)
        self.assertIn("12 $ par enfant et 18 $ par adulte", nephews.questions[5].answer)

    def test_volunteer_developments_cover_places_shifts_supplies_notice_and_first_visit(self):
        animals = self.by_group["animal-protection-association-invitation"]
        self.assertIn("où se déroulent les missions", animals.questions[3].question)
        self.assertIn("jours et horaires", animals.questions[4].question)
        self.assertIn("10 h à 13 h", animals.questions[4].answer)
        self.assertIn("14 h à 16 h", animals.questions[4].answer)
        self.assertIn("rencontrer l'équipe sur place", animals.questions[7].question)
        meals = self.by_group["friend-homeless-meal-volunteering"]
        self.assertIn("combien de temps à l'avance", meals.questions[1].question)
        self.assertIn("deux jours avant", meals.questions[1].answer)
        self.assertIn("protections nécessaires sont-elles fournies", meals.questions[5].question)
        self.assertIn("observer une distribution", meals.questions[7].question)
        environment = self.by_group["neighbor-environmental-association-volunteering"]
        self.assertIn("matériel est fourni", environment.questions[1].question)
        self.assertIn("apporter soi-même", environment.questions[1].question)
        self.assertIn("8 h 45 à midi", environment.questions[2].answer)
        self.assertIn("deux jours avant", environment.questions[3].answer)
        self.assertIn("en cas d'annulation", environment.questions[7].question)
        self.assertIn("prévient les inscrits par message", environment.questions[7].answer)

    def test_delivery_refund_and_practical_handover_developments_remain_role_specific(self):
        grocery = self.by_group["grocery-store-home-delivery"]
        self.assertIn("produit manque ou arrive abîmé", grocery.questions[7].question)
        self.assertIn("remboursement", grocery.questions[7].question)
        self.assertIn("numéro de commande", grocery.questions[7].answer)
        self.assertIn("moyen de paiement utilisé", grocery.questions[7].answer)
        watch = self.by_group["friend-holiday-apartment-watch"]
        self.assertIn("combien de temps", watch.questions[3].question)
        self.assertIn("vingtaine de minutes", watch.questions[3].answer)
        self.assertIn("Seras-tu joignable", watch.questions[6].question)
        self.assertIn("concierge", watch.questions[6].answer)
        doctor = self.by_group["medical-secretary-temporary-replacement-doctor"]
        self.assertIn("transmettre des documents", doctor.questions[3].question)
        self.assertIn("documents faut-il apporter", doctor.questions[6].question)
        self.assertIn("pièce d'identité", doctor.questions[6].answer)
        visit = self.by_group["visit-colleague-minor-accident"]
        self.assertIn("quand pourrais-je vous le déposer", visit.questions[7].question)
        self.assertIn("demain après 17 h", visit.questions[7].answer)

    def test_pet_urgency_replies_do_not_require_waiting_for_the_owners_response(self):
        paid = self.by_group["neighbor-dog-care-week-paid"]
        self.assertIn("en cas d'urgence ou si je suis injoignable", paid.questions[6].answer)
        unpaid = self.by_group["trusted-person-temporary-pet-care"]
        self.assertIn("En urgence, contacte directement le vétérinaire", unpaid.questions[7].answer)

    def test_parcel_errand_checks_contents_arrival_and_feasibility_before_accepting(self):
        row = self.by_group["help-friend-post-parcel"]
        self.assertIn("Que contient le paquet", row.questions[1].question)
        self.assertIn("précautions", row.questions[1].question)
        self.assertIn("tasse fragile", row.questions[1].answer)
        self.assertEqual(
            row.questions[2].question,
            "Dans quelle ville faut-il envoyer le colis, et quand doit-il arriver au plus tard ?",
        )
        self.assertIn("poster le paquet", row.questions[0].question)
        self.assertIn("mardi prochain", row.questions[2].answer)
        self.assertIn("dépôt compris", row.questions[5].question)
        self.assertIn("avant de te confirmer", row.closing)
        self.assertIn("cannot guarantee", row.note)

    def test_doctor_route_distinguishes_experience_location_records_and_schedule(self):
        row = self.by_group["medical-secretary-temporary-replacement-doctor"]
        self.assertIn("depuis combien de temps exerce", row.questions[1].question)
        self.assertIn("même cabinet", row.questions[2].question)
        self.assertIn("accès à mon dossier", row.questions[3].question)
        self.assertEqual(row.questions[3].follow_up_to, 3)
        self.assertIn("Jusqu'à quelle date", row.questions[4].question)
        self.assertIn("Quels jours et à quelles heures", row.questions[5].question)
        self.assertIsNone(row.questions[5].follow_up_to)
        self.assertIn("not medical advice", row.note)

    def test_minor_accident_inquiry_uses_empathy_and_a_coherent_narrative(self):
        row = self.by_group["visit-colleague-minor-accident"]
        self.assertIn("pendant que vous vous reposez", row.questions[1].question)
        self.assertEqual(row.questions[2].question, "C'est arrivé quand, et à quel endroit exactement ?")
        self.assertEqual(row.questions[3].question, "Qu'est-ce qui s'est passé exactement ?")
        self.assertEqual(
            row.questions[4].question, "Est-ce que quelqu'un est venu vous aider sur place ?",
        )
        self.assertEqual(row.questions[4].follow_up_to, 4)
        self.assertIn("Un passant", row.questions[4].answer)
        self.assertEqual(
            row.questions[5].question,
            "Avez-vous consulté un médecin après l'accident et, si oui, que vous a-t-il conseillé ?",
        )
        self.assertIsNone(row.questions[5].follow_up_to)
        self.assertIn("quelques jours de repos", row.questions[5].answer)
        self.assertEqual(
            self.hints[row.group][5]["english"],
            "Whether a doctor was consulted and what advice they gave",
        )
        self.assertEqual(
            row.questions[6].question,
            "Avez-vous une idée de la date de votre retour au travail, et souhaitez-vous que je transmette un message à l'équipe ?",
        )
        self.assertIn("lundi prochain", row.questions[6].answer)
        self.assertIn("dites à l'équipe", row.questions[6].answer)
        self.assertEqual(row.questions[7].follow_up_to, 7)
        self.assertEqual(
            self.hints[row.group][6]["english"],
            "Possible return date and message to pass on to the team",
        )
        self.assertIn("explicitly minor", row.note)
        self.assertIn("without assuming an injury, diagnosis or treatment", row.note)
