import hashlib
import json
import re

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tache_two_dialogues import dialogue_response
from study.tests.housing_work_fixtures import RECLASSIFIED_GROUPS
from study.tests.eo2_review_fixtures import REVIEWED_GROUPS, remove_latest_review_archives
from study.tests.travel_fixtures import TRAVEL_GROUPS


ACCOMMODATION_GROUPS = (
    TRAVEL_GROUPS["hebergements-touristiques"]
    | RECLASSIFIED_GROUPS["hebergements-touristiques"]
)
EARLIER_REFINEMENTS = {
    "neighbor-home-childcare-provider-referral",
    "neighbor-environmental-association-volunteering",
}


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
    ).hexdigest()


class AccommodationDevelopmentTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.dialogues = catalogue.tache_two_dialogues()
        self.by_group = {row.group: row for row in self.dialogues.values()}
        self.raw = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        self.hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"]

    def test_six_models_keep_all_nine_publications_and_their_classification(self):
        _, mapping = catalogue.tache_two_subject_themes()
        keys = {key for key, row in self.dialogues.items() if row.group in ACCOMMODATION_GROUPS}
        self.assertEqual(keys, {
            "tache2:avril:batch-02:subject-09",
            "tache2:mai:batch-02:subject-07",
            "tache2:juin:batch-04:subject-20",
            "tache2:aout:batch-02:subject-07",
            "tache2:aout:batch-03:subject-12",
            "tache2:octobre:batch-05:subject-25",
            "tache2:octobre:batch-07:subject-32",
            "tache2:novembre:batch-01:subject-05",
            "tache2:decembre:batch-09:subject-42",
        })
        self.assertEqual(len(ACCOMMODATION_GROUPS), 6)
        for key in keys:
            self.assertEqual(mapping[key], "hebergements-touristiques")

    def test_every_model_has_eight_cues_and_renders_questions_without_worked_answers(self):
        for group in sorted(ACCOMMODATION_GROUPS):
            with self.subTest(group=group):
                row = self.by_group[group]
                response = dialogue_response(row)
                self.assertEqual(len(row.questions), 8)
                self.assertEqual(len(self.hints[group]), 8)
                self.assertEqual(
                    [argument.idea for argument in response.arguments],
                    [question.question for question in row.questions],
                )
                self.assertTrue(all(argument.developpement == "" for argument in response.arguments))
                self.assertEqual(row.register, "vous")
                self.assertIn("merci", row.closing.lower())

    def test_hotel_services_develop_prices_access_and_procedures_without_a_room_booking(self):
        row = self.by_group["hotel-host-services"]
        self.assertEqual(
            sum("petit-déjeuner" in question.question for question in row.questions), 1,
        )
        expected = (
            ("compris dans le prix", "Available services and what the room price includes"),
            ("à quel prix et à quels horaires", "Breakfast format, price per person and serving times"),
            ("restaurant ou un service en chambre", "Lunch and dinner options and prices"),
            ("quel est le délai", "Laundry prices and turnaround time"),
            ("navette pour l'aéroport ou la gare", "Airport or station shuttle availability and price per person"),
            ("Le jour du départ, jusqu'à quelle heure", "Luggage collection deadline on departure day"),
            ("comment peut-on s'y connecter", "Wifi coverage and how to connect"),
            ("comment peut-on le faire", "Services needing advance booking and how to arrange them"),
        )
        for index, (question_fragment, cue) in enumerate(expected):
            with self.subTest(question=index + 1):
                self.assertIn(question_fragment, row.questions[index].question)
                self.assertEqual(self.hints[row.group][index]["english"], cue)
        self.assertEqual(row.questions[2].follow_up_to, 2)
        self.assertEqual(
            sum(bool(re.search(r"blanchisserie|linge", q.question)) for q in row.questions), 1,
        )
        self.assertIn("Combien coûte", row.questions[3].question)
        self.assertIn("5 $ pour une chemise", row.questions[3].answer)
        self.assertIn("le lendemain à partir de 18 h", row.questions[3].answer)
        self.assertTrue(row.questions[4].question.startswith("Proposez-vous"))
        self.assertIn("tarif par personne", row.questions[4].question)
        self.assertIn("15 $ par personne", row.questions[4].answer)
        self.assertNotIn("avant de prendre", row.questions[5].question)
        self.assertIn("20 h", row.questions[5].answer)
        self.assertNotRegex(
            " ".join(q.question for q in row.questions), r"\b(?:chambre libre|suite|spa)\b",
        )
        self.assertNotIn("spa", row.questions[7].answer)
        self.assertIn("la navette au moins deux heures avant", row.questions[7].answer)
        self.assertIn("not automatically to book a room", row.note)

    def test_hotel_booking_compares_real_options_and_checks_the_whole_stay_cost_before_payment(self):
        row = self.by_group["hotel-reception-room-booking"]
        self.assertIn("deux nuits", row.questions[0].question)
        self.assertEqual(row.questions[1].follow_up_to, 1)
        self.assertIn("ces chambres", row.questions[1].question)
        self.assertNotIn("suite", row.questions[1].question)
        self.assertIn("montant total, taxes comprises", row.questions[2].question)
        self.assertIn("standard coûte 320 $", row.questions[2].answer)
        self.assertIn("supérieure 400 $", row.questions[2].answer)
        self.assertEqual(row.questions[3].follow_up_to, 3)
        nightly_parking, stay_parking = map(
            int, re.findall(r"(\d+) \$", row.questions[3].answer),
        )
        self.assertEqual(stay_parking, nightly_parking * 2)
        self.assertIn("chambre n'est pas encore prête", row.questions[4].question)
        self.assertIn("arrivée est retardée", row.questions[5].question)
        self.assertIn("code", row.questions[5].answer)
        self.assertIn("80 $ déduit du total", row.questions[6].answer)
        self.assertIn("48 heures", row.questions[7].answer)
        self.assertIn("tarif des nouvelles dates", row.questions[7].answer)
        self.assertEqual(
            self.hints[row.group][5]["english"],
            "Late arrival, key collection and notifying reception",
        )
        self.assertIn("illustrative choice", row.note)

    def test_tourist_office_compares_accommodation_without_promising_provider_terms(self):
        row = self.by_group["quebec-region-accommodation-tourist-office"]
        self.assertIn("un gîte, un hôtel ou un chalet", row.questions[0].question)
        self.assertEqual(row.questions[1].follow_up_to, 1)
        self.assertIn("préparer ses repas", row.questions[1].question)
        self.assertIn("si je viens sans voiture", row.questions[2].question)
        self.assertIn("par personne ou par logement", row.questions[3].question)
        self.assertIn("la chambre pour deux", row.questions[3].answer)
        self.assertIn("le chalet entier", row.questions[3].answer)
        self.assertEqual(row.questions[4].follow_up_to, 4)
        self.assertIn("80 $ de ménage par séjour", row.questions[4].answer)
        self.assertIn("durée minimale", row.questions[5].question)
        self.assertIn("ils confirmeront leurs disponibilités", row.questions[6].answer)
        self.assertIn("Directement auprès de l'hébergeur", row.questions[7].answer)
        self.assertNotIn("sans frais", row.questions[7].answer)
        self.assertIn("Quebec is given", row.note)
        self.assertIn("individual providers confirm", row.note)
        self.assertEqual(
            self.hints[row.group][7]["english"],
            "Who handles the booking and which terms to check before payment",
        )

    def test_camping_distinguishes_pitch_people_hookups_and_actual_service_limits(self):
        row = self.by_group["camping-reception-stay-preparation"]
        self.assertIn("tente ou un véhicule récréatif", row.questions[0].question)
        self.assertEqual(row.questions[1].follow_up_to, 1)
        self.assertIn("taille des emplacements", row.questions[1].question)
        self.assertIn("nombre de personnes ou les branchements", row.questions[2].question)
        self.assertIn("Pour deux adultes", row.questions[2].answer)
        self.assertIn("8 $ par nuit", row.questions[2].answer)
        self.assertEqual(row.questions[3].follow_up_to, 3)
        self.assertIn("douches", row.questions[3].question)
        self.assertIn("conserver les aliments au frais", row.questions[4].question)
        self.assertIn("ni cuisine collective ni réfrigérateur", row.questions[4].answer)
        self.assertIn("le calme est-il demandé", row.questions[5].question)
        self.assertIn("25 % du total", row.questions[6].answer)
        self.assertIn("déduit de la facture", row.questions[6].answer)
        self.assertIn("sept jours avant l'arrivée", row.questions[7].answer)
        self.assertIn("ensuite, il est conservé", row.questions[7].answer)
        self.assertEqual(self.hints[row.group][1]["english"], "Pitch size, shade and quiet surroundings")
        self.assertIn("tent branch is illustrative", row.note)

    def test_seaside_rental_uses_a_us_example_and_open_stay_length_and_equipment_questions(self):
        row = self.by_group["neighbor-seaside-house-rental"]
        self.assertIn("quartier de Seattle", row.questions[0].question)
        self.assertIn("combien de temps", row.questions[0].question)
        self.assertIn("en voiture", row.questions[0].answer)
        self.assertIn("durée du séjour est-elle flexible", row.questions[1].question)
        self.assertNotIn("au moins une semaine", row.questions[1].question)
        self.assertIn("300 $, déduit du loyer", row.questions[2].answer)
        self.assertEqual(row.questions[3].follow_up_to, 3)
        self.assertIn("distincte de l'acompte", row.questions[3].answer)
        self.assertTrue(row.questions[5].question.startswith("Quels équipements"))
        self.assertIn("par exemple", row.questions[5].question)
        self.assertIn("la plage et les commerces à pied", row.questions[6].question)
        self.assertIn("obtenir par écrit", row.questions[7].question)
        self.assertIn("remise des clés", row.questions[7].question)
        self.assertIn("not help finding your main home", row.note)
        self.assertNotRegex(
            " ".join((row.opening, *(q.question for q in row.questions))),
            r"Carleton|Gaspésie",
        )
        self.assertEqual(
            self.hints[row.group][1]["english"], "Available dates and flexibility of stay length",
        )

    def test_colleague_rental_keeps_availability_first_and_distinguishes_advance_and_damage_deposits(self):
        row = self.by_group["colleague-summer-house-rental"]
        previous = catalogue.tache_two_location_history()[row.group].revisions[-1]
        for before, after in ((6, 1), (4, 6), (5, 7)):
            self.assertEqual(
                previous.questions[before - 1].question, row.questions[after - 1].question,
            )
        self.assertIn("durée minimale", row.questions[0].question)
        self.assertIn("400 $, déduit du loyer", row.questions[1].answer)
        self.assertEqual(row.questions[2].follow_up_to, 2)
        self.assertIn("le ménage coûte 100 $", row.questions[2].answer)
        self.assertIn("300 $, distincte de l'acompte", row.questions[2].answer)
        self.assertIn("couchages", row.questions[3].question)
        self.assertTrue(row.questions[4].question.startswith("Quels équipements"))
        self.assertIn("Ballard", row.questions[5].question)
        self.assertIn("sans voiture", row.questions[6].question)
        self.assertIn("obtenir par écrit", row.questions[7].question)
        self.assertIn("trente jours", row.questions[7].answer)
        self.assertEqual(
            self.hints[row.group][7]["english"],
            "Viewing and written cancellation and key-handover terms",
        )
        self.assertIn("Do not assume a seaside setting", row.note)

    def test_unrelated_models_cues_and_complete_historical_layouts_remain_exact(self):
        changed = ACCOMMODATION_GROUPS | EARLIER_REFINEMENTS | REVIEWED_GROUPS
        protected = {group: row for group, row in self.raw.items() if group not in changed}
        self.assertEqual(len(protected), 106)
        self.assertEqual(
            fingerprint({
                "dialogues": protected,
                "hints": {group: row for group, row in self.hints.items() if group not in changed},
            }),
            "605141a1d60ca9ce3d49bf8dfa1058b0e8b3ada71812345be2548353e6b99f29",
        )
        history = json.loads((
            content.QUESTION_BANK_DIR / "dialogue_history/locations.json"
        ).read_text())
        remove_latest_review_archives(history)
        self.assertEqual(
            fingerprint(history),
            "774c33725f0ef5bee59983fcc44f222c824abc6b3b3e75d5e680911e8e810a8d",
        )
