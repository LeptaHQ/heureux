import hashlib
import json

from django.test import SimpleTestCase

from study import catalogue, content_loader as content


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

    def test_review_covers_twenty_models_and_all_forty_four_publications(self):
        publications = [
            row for key, row in self.dialogues.items() if self.themes[key] == "vie-quartier"
        ]
        groups = {row.group for row in publications}
        self.assertEqual(len(publications), 44)
        self.assertEqual(groups, set(REVIEW_REVISIONS) | {
            "new-resident-neighbor-neighborhood-orientation",
            "volunteer-local-association-information-office",
        })
        for row in publications:
            with self.subTest(group=row.group):
                self.assertEqual(len(row.questions), 8)
                self.assertEqual(len(self.hints[row.group]), 8)
                self.assertIn("merci", row.closing.lower())

    def test_other_completed_themes_remain_exactly_unchanged(self):
        raw = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        expected = {
            "arrivee": "b3f62225759c57d763f3af704a1a1756d7d83700d5b9c061b8b5b2de52304802",
            "logement": "e650f8cfbd4e5c653958e7601692e2d4d0549302f09a4e9b9bdfa7f53f240847",
            "travail": "5529b40e35c4d3fd44ca29e4fc103345feebe67ca35618a24091b59d716b8752",
            "ecole-etudes": "2fdd745d22e7b18c13bf1ffb59ba3b1aa85a67a33932b0e3412851a7fe2d43e1",
        }
        for theme, digest in expected.items():
            with self.subTest(theme=theme):
                groups = {
                    row.group for key, row in self.dialogues.items() if self.themes[key] == theme
                }
                snapshot = json.dumps(
                    [raw[group] for group in sorted(groups)],
                    ensure_ascii=False, sort_keys=True,
                ).encode()
                self.assertEqual(hashlib.sha256(snapshot).hexdigest(), digest)
        self.assertNotIn("new-resident-neighbor-neighborhood-orientation", self.history)
        self.assertEqual(
            len(self.history["volunteer-local-association-information-office"]["revisions"]), 3,
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
                self.assertEqual(len(self.history[group]["revisions"]), 3)

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
        self.assertEqual(
            row.questions[2].question,
            "Quelles missions sont confiées aux bénévoles dans cette association ?",
        )
        self.assertIn("does not necessarily run", row.note)
        self.assertIn("Préparer les paniers", row.questions[2].answer)
        self.assertEqual(
            self.hints[row.group][2]["english"], "Tasks assigned to volunteers",
        )
        self.assertEqual(
            row.questions[7].question,
            "Pourrais-je rencontrer l'équipe et observer une distribution avant de m'engager régulièrement ?",
        )
        self.assertIn("sur rendez-vous", row.questions[7].answer)
        self.assertIn("l'association confirmera le créneau", row.questions[7].answer)
        self.assertIn("les consignes avant votre venue", row.questions[7].answer)
        self.assertIsNone(row.questions[7].follow_up_to)
        self.assertEqual(row.questions[1].follow_up_to, 1)
        self.assertEqual(
            self.hints[row.group][7]["english"],
            "Meeting the team and observing a distribution before committing",
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
        self.assertIn("repas et son goûter", weekend.questions[0].question)
        for timing in ("8 h", "midi", "18 h 30", "16 h"):
            self.assertIn(timing, weekend.questions[0].answer)
        self.assertIn("Puis-je l'emmener", weekend.questions[3].question)
        self.assertTrue(weekend.questions[3].answer.startswith("Oui"))
        day = self.by_group["neighbor-child-one-day-care"]
        self.assertIn("me laisserez-vous les aliments", day.questions[3].question)
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
        self.assertIn("Dans quel secteur", provider.questions[3].question)
        self.assertIn("chez les parents ou chez elle", provider.questions[3].question)
        self.assertIn("D'après ce que vous savez", provider.questions[4].question)
        self.assertIn("disponibilités actuelles", provider.questions[4].answer)
        self.assertIn("tarif actuel", provider.questions[6].answer)
        self.assertIn("avec son accord", provider.questions[7].answer)

    def test_holiday_child_safety_checks_actual_arrangements_not_only_reassurance(self):
        row = self.by_group["child-friends-family-holiday-invitation"]
        self.assertIn("quels équipements de sécurité", row.questions[3].question)
        self.assertIn("Combien d'enfants", row.questions[4].question)
        self.assertIn("quels adultes", row.questions[4].question)
        self.assertIn("Trois enfants", row.questions[4].answer)
        self.assertIn("un adulte sera-t-il", row.questions[6].question)
        self.assertIn("quels équipements de sécurité", row.questions[6].question)
        self.assertEqual(row.questions[6].follow_up_to, 6)

    def test_apartment_checks_include_plant_quantities_and_moved_emergency_relance(self):
        row = self.by_group["friend-holiday-apartment-watch"]
        self.assertIn("quelle quantité d'eau", row.questions[3].question)
        self.assertIn("à ne pas arroser", row.questions[3].question)
        self.assertEqual(row.questions[3].follow_up_to, 2)
        self.assertIn("cactus", row.questions[3].answer)
        self.assertIn("code d'accès", row.questions[4].question)
        self.assertIn("qui pourrait m'aider", row.questions[7].question)
        self.assertEqual(row.questions[7].follow_up_to, 7)
        self.assertEqual(
            self.hints[row.group][3]["english"],
            "Water quantity per plant and plants not to water",
        )

    def test_volunteering_covers_real_shifts_commitment_and_arrival(self):
        meals = self.by_group["friend-homeless-meal-volunteering"]
        self.assertIn("Où ont lieu", meals.questions[2].question)
        self.assertIn("préparation et rangement compris", meals.questions[2].answer)
        animals = self.by_group["animal-protection-association-invitation"]
        self.assertIn("personnes qui souhaitent adopter", animals.questions[1].question)
        self.assertIn("ponctuellement", animals.questions[4].question)
        self.assertIn("durée minimale", animals.questions[4].question)
        self.assertIn("trois mois", animals.questions[4].answer)
        self.assertIn("sur place ou en ligne", animals.questions[6].question)
        self.assertEqual(animals.questions[6].follow_up_to, 6)
        environment = self.by_group["neighbor-environmental-association-volunteering"]
        self.assertIn("explications et un accompagnement", environment.questions[5].question)
        self.assertIn("où faut-il se présenter", environment.questions[7].question)
        self.assertIn("quinze minutes avant 9 h", environment.questions[7].answer)
        self.assertIn("vérifiez le point de rendez-vous", environment.questions[7].answer)

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

    def test_delivery_questions_cover_payment_and_window_length(self):
        row = self.by_group["grocery-store-home-delivery"]
        self.assertIn("moyens de paiement", row.questions[1].question)
        self.assertIn("par carte au livreur", row.questions[1].answer)
        self.assertIn("combien de temps dure", row.questions[5].question)
        self.assertIn("deux heures", row.questions[5].answer)
        self.assertIn("créneaux disponibles", row.questions[5].answer)
        self.assertEqual(row.questions[5].follow_up_to, 5)
        self.assertIn("nouvelle livraison coûte", row.questions[7].answer)

    def test_parcel_errand_checks_contents_arrival_and_feasibility_before_accepting(self):
        row = self.by_group["help-friend-post-parcel"]
        self.assertIn("Que contient le paquet", row.questions[1].question)
        self.assertIn("précautions", row.questions[1].question)
        self.assertIn("tasse fragile", row.questions[1].answer)
        self.assertIn("pour quelle date au plus tard", row.questions[2].question)
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
        self.assertEqual(row.questions[2].question, "Quand et où l'accident s'est-il produit ?")
        self.assertEqual(row.questions[3].question, "Qu'est-ce qui s'est passé exactement ?")
        self.assertIn("vous aider sur place", row.questions[4].question)
        self.assertEqual(row.questions[4].follow_up_to, 4)
        self.assertIn("Un passant", row.questions[4].answer)
        self.assertIn("explicitly minor", row.note)
