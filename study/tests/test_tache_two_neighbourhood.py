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
            len(self.history["volunteer-local-association-information-office"]["revisions"]), 2,
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

    def test_visit_order_does_not_force_a_single_walkable_day(self):
        row = self.by_group["host-foreign-friends-city-advice"]
        self.assertEqual(
            row.questions[1].question, "Dans quel ordre me conseilles-tu de visiter ces lieux ?",
        )
        self.assertIn("without explaining a suitable visit order", row.questions[1].condition)
        self.assertIn("à pied", row.questions[6].question)
        self.assertIn("en transports en commun", row.questions[6].question)
        self.assertIn("acheter un pass à la journée", row.questions[7].question)
        self.assertEqual(row.questions[7].follow_up_to, 7)
        self.assertIn("réseaux couverts", row.questions[7].answer)
        self.assertNotIn("à pied", self.hints[row.group][1]["french"])
        self.assertNotIn("walkable day", self.hints[row.group][1]["english"])

    def test_rainy_day_questions_name_real_indoor_alternatives(self):
        city = self.by_group["host-foreign-friends-city-advice"]
        self.assertIn("quelles autres activités à l'intérieur", city.questions[3].question)
        self.assertIn("une exposition ou un spectacle", city.questions[3].question)
        self.assertIn("MOHAI", city.questions[2].answer)
        self.assertNotIn("MOHAI", city.questions[3].answer)
        self.assertIn("Museum of Pop Culture", city.questions[3].answer)
        self.assertIn("programmation", city.questions[3].answer)
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
        self.assertIn("sortie à midi", pet.questions[4].answer)
        self.assertIn("adapt walks and overnight presence", pet.note)
        paid = self.by_group["neighbor-dog-care-week-paid"]
        self.assertIn("présence la nuit", paid.questions[1].question)
        self.assertIn("Trois sorties", paid.questions[3].answer)
        self.assertIn("allergies", paid.questions[5].question)
        self.assertIn("séparément", paid.questions[7].answer)
        self.assertIn("avant de vous confirmer", paid.closing)

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
