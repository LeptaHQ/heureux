import hashlib
import json

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tache_two_dialogues import dialogue_response
from study.tests.eo2_review_fixtures import (
    assert_review_preservation, pre_realness_history, PUBLISHED_ARCHIVE_INDEX,
    remove_followup_archives,
)
from study.tests.transport_travel_review_fixtures import (
    REVIEWED_GROUPS, TRANSPORT_GROUPS, remove_transport_travel_review_archives,
)
from study.tests.travel_fixtures import TRAVEL_GROUPS


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
    ).hexdigest()


class TransportTravelDialogueReviewTests(SimpleTestCase):
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
        cls.history = json.loads(
            (content.QUESTION_BANK_DIR / "dialogue_history/locations.json").read_text(),
        )

    @classmethod
    def tearDownClass(cls):
        catalogue.clear_catalogue_cache()
        super().tearDownClass()

    def test_current_themes_keep_twenty_six_models_and_fifty_eight_publications(self):
        for theme, groups, count in (
            ("transports", TRANSPORT_GROUPS, 26),
            ("voyages", TRAVEL_GROUPS["voyages"], 32),
        ):
            rows = [row for key, row in self.dialogues.items() if self.themes[key] == theme]
            self.assertEqual({row.group for row in rows}, groups)
            self.assertEqual(len(rows), count)
            for row in rows:
                self.assertEqual(len(row.questions), 8)
                self.assertEqual(len(self.hints[row.group]), 8)
                self.assertIn("merci", row.closing.casefold())

    def test_original_public_editions_and_reviewed_registers_remain_available(self):
        assert_review_preservation(self)
        self.assertEqual(
            fingerprint(sorted((key, row["register"]) for key, row in self.raw.items())),
            "d37ae3561719f64c5a211ccb93012d37b90a08f2ec832397605ccac871d9755a",
        )

    def test_all_twenty_six_exact_published_layouts_are_archived_without_answers(self):
        snapshots = [
            self.history["groups"][group]["revisions"][PUBLISHED_ARCHIVE_INDEX[group]]
            for group in sorted(REVIEWED_GROUPS)
        ]
        self.assertEqual(
            fingerprint(snapshots),
            "94a340d94b77f109fa7be154b77a659e9d9ae7e89f97705599cc6d37bc09f1fe",
        )
        for snapshot in snapshots:
            self.assertEqual(set(snapshot), {"group", "opening", "closing", "questions"})
            self.assertTrue(all("answer" not in question for question in snapshot["questions"]))
            current = self.by_group[snapshot["group"]]
            self.assertNotEqual(
                [q["question"] for q in snapshot["questions"]],
                [q.question for q in current.questions],
            )

    def test_every_prior_archive_and_geographic_substitution_is_exact(self):
        previous = pre_realness_history(self.history)
        remove_followup_archives(previous)
        remove_transport_travel_review_archives(previous)
        self.assertEqual(
            fingerprint(previous),
            "5bece082c3b664febac661f60224f7c443bbc90b33b41dccd8b799bdd9626865",
        )

    def test_internal_replies_never_enter_learner_models(self):
        for group in REVIEWED_GROUPS:
            row = self.by_group[group]
            value = dialogue_response(row)
            self.assertEqual([a.idea for a in value.arguments], [q.question for q in row.questions])
            self.assertTrue(all(
                not any((a.developpement, a.exemple, a.consequence)) for a in value.arguments
            ))
            self.assertFalse(value.position)
            self.assertFalse(value.position_claire)
            self.assertFalse(value.nuance)

    def test_all_theme_review_preserves_public_editions_beyond_old_leaf_scopes(self):
        assert_review_preservation(self)

    def test_transit_enquiry_covers_destinations_live_information_tickets_and_safety_hours(self):
        row = self.by_group["newcomer-city-transit-service"]
        self.assertEqual(len(row.questions), 8)
        self.assertEqual(
            row.questions[1].question,
            "Lesquels desservent le centre-ville, la gare et les principaux sites touristiques ?",
        )
        for place in ("centre", "gare", "sites touristiques"):
            self.assertIn(place, row.questions[1].answer)
        for index, text in (
            (2, "prochains passages en temps réel"), (4, "correspondances"),
            (5, "valider"), (6, "circulent-ils le soir"), (7, "caméras de surveillance"),
        ):
            self.assertIn(text, row.questions[index].question)
        self.assertIn("prochains passages en temps réel", row.questions[2].answer)
        self.assertIsNone(row.questions[2].follow_up_to)
        self.assertEqual(row.questions[4].follow_up_to, 4)
        self.assertIn("guichet", row.questions[5].answer)
        self.assertIn("lecteur", row.questions[5].answer)
        self.assertIn("si vous proposez un service", row.questions[7].question)
        self.assertIn(
            "ce service est-il joignable 24 heures sur 24", row.questions[7].question,
        )
        self.assertEqual(row.questions[7].question.count("?"), 1)
        self.assertIn("à toute heure", row.questions[7].answer)
        self.assertIn("numéro affiché", row.questions[7].answer)
        self.assertIn("temps réel", self.hints[row.group][2]["french"])
        self.assertIn("24/7", self.hints[row.group][7]["english"])
        self.assertNotIn("agence", " ".join(q.question for q in row.questions))
        self.assertIn("only if that service exists", row.note)

    def test_breakdown_assistance_and_authorization_precede_reimbursement_paperwork(self):
        row = self.by_group["canada-car-breakdown-insurer"]
        self.assertIn("position", row.questions[0].question)
        self.assertIn("localisation précise", row.questions[0].answer)
        self.assertIn("délai", row.questions[1].question)
        self.assertIn("remorquer", row.questions[2].question)
        self.assertIn("Avant d'autoriser", row.questions[4].question)
        self.assertIn("limite de 200", row.questions[3].answer)
        self.assertIn("ne sont pas couvertes", row.questions[4].answer)
        self.assertIn("avancer", row.questions[5].question)
        self.assertIn("réglons directement", row.questions[5].answer)
        self.assertIn("avant d'engager la dépense", row.questions[6].answer)
        self.assertIn("justificatifs", row.questions[7].question)
        self.assertIn("immediate safety", row.note)

    def test_private_car_has_history_and_proof_rather_than_a_scripted_tyre_only_route(self):
        row = self.by_group["private-owner-used-car-purchase"]
        for index, text in ((2, "consomme"), (4, "accident"), (5, "factures"), (7, "contrôle indépendant")):
            self.assertIn(text, row.questions[index].question)
        self.assertIn("pneus ou les freins", row.questions[3].question)
        self.assertEqual(row.questions[5].follow_up_to, 4)
        self.assertIn("accrochage", row.questions[4].answer)
        self.assertIn("contrôle indépendant", row.questions[7].answer)

    def test_rentals_cover_actual_extra_costs_and_returns_without_forcing_an_electric_bike(self):
        car = self.by_group["holiday-car-rental-agency"]
        self.assertIn("supplément", car.questions[2].question)
        self.assertIn("0,25 $", car.questions[2].answer)
        self.assertIn("franchise", car.questions[4].answer)
        self.assertIn("dépôt de garantie", car.questions[6].question)
        self.assertIn("carburant", car.questions[7].answer)
        bike = self.by_group["bicycle-rental-model-and-terms"]
        self.assertIn("différences", bike.questions[1].question)
        self.assertIn("casque", bike.questions[3].question)
        self.assertIn("dépôt", bike.questions[5].question)
        self.assertIn("retard", bike.questions[6].question)
        self.assertIn("crevais", bike.questions[7].question)
        self.assertNotIn("autonomie", " ".join(q.question for q in bike.questions))
        self.assertIn("battery range if you choose", self.raw[bike.group]["note"])

    def test_cycling_distinguishes_condition_road_sections_and_actual_battery_range(self):
        city = self.by_group["ottawa-newcomer-cycling-friend"]
        self.assertIn("grands axes", city.questions[1].question)
        self.assertIn("bon état", city.questions[2].question)
        self.assertIn("séparées", city.questions[2].question)
        self.assertIn("certains raccordements", city.questions[2].answer)
        sale = self.by_group["friend-used-electric-bicycle-sale"]
        self.assertIn("kilomètres", sale.questions[2].question)
        self.assertIn("charge complète", sale.questions[4].question)
        self.assertIn("assistance modérée", sale.questions[4].answer)
        self.assertNotIn("samedi", sale.closing)

    def test_carpools_distinguish_platform_booking_from_a_neighbourly_trial(self):
        friend = self.by_group["friend-carpooling-offer"]
        self.assertIn("places", friend.questions[2].question)
        self.assertIn("rendez-vous", friend.questions[3].question)
        self.assertIn("bagages", friend.questions[5].question)
        self.assertIn("payer", friend.questions[6].question)
        self.assertIn("annuler", friend.questions[7].question)
        self.assertIn("No commute, vehicle ownership or driver role", friend.note)
        neighbour = self.by_group["neighbor-regular-carpool-invitation"]
        self.assertIn("retrouverions-nous", neighbour.questions[2].question)
        self.assertIn("partager les frais", neighbour.questions[4].question)
        self.assertIn("essayer", neighbour.questions[7].question)

    def test_montreal_plan_checks_work_route_calendar_validity_zones_and_late_returns(self):
        row = self.by_group["colleague-montreal-work-week-transit"]
        self.assertIn("lieu de travail", row.questions[0].question)
        self.assertIn("hébergement", row.questions[0].question)
        self.assertIn("deux adresses", row.questions[0].answer)
        self.assertIn("fréquence", row.questions[1].question)
        self.assertTrue(row.questions[3].question.startswith("Si j'arrive"))
        self.assertEqual(row.questions[3].follow_up_to, 3)
        self.assertIn("lundi au dimanche", row.questions[2].answer)
        self.assertIn("semaine suivante", row.questions[3].answer)
        self.assertIn("zones", row.questions[4].question)
        self.assertIn("zone A", row.questions[4].answer)
        self.assertIn("OPUS", row.questions[5].question)
        self.assertEqual(row.questions[7].follow_up_to, 7)
        self.assertIn("bus de nuit", row.questions[7].answer)

    def test_host_friend_variant_keeps_accommodation_and_short_visit_context(self):
        row = self.dialogues["tache2:decembre:batch-04:subject-17"]
        self.assertIn("accommodation is already arranged", row.note)
        self.assertIn("Use tu", row.note)
        self.assertIn("rather than assuming a monthly subscription", row.note)
        self.assertEqual(row.register, "tu")
        neighbour = self.by_group[row.group]
        self.assertIn("jusqu'à quelle heure peut-on rentrer", neighbour.questions[2].question)
        self.assertIn("nombre de trajets prévus", neighbour.questions[5].question)
        self.assertIn("zones", neighbour.questions[6].question)
        self.assertIn("acheter la formule choisie", neighbour.questions[7].question)
        self.assertEqual(neighbour.questions[7].follow_up_to, 6)

    def test_agencies_establish_dates_before_costs_and_do_not_invent_school_holidays(self):
        for group in (
            "travel-agency-choose-holiday-destination",
            "travel-agency-canada-stay", "travel-agency-canada-cruise",
        ):
            row = self.by_group[group]
            self.assertIn("disponibles" if group.endswith("cruise") else "places",
                          row.questions[2].question)
            self.assertNotIn("vacances scolaires", " ".join(q.question for q in row.questions))
            self.assertIn("simulated", row.note)
        cruise = self.by_group["travel-agency-canada-cruise"]
        self.assertIn("cabine intérieure partagée", cruise.questions[3].answer)
        self.assertIn("français", cruise.questions[6].question)
        self.assertIn("visiter librement", cruise.questions[7].question)

    def test_completed_tours_use_experience_and_actual_extra_spending(self):
        row = self.by_group["colleague-canada-tour-next-summer"]
        self.assertIn("fatigant", row.questions[2].question)
        self.assertIn("hébergements", row.questions[3].question)
        self.assertIn("non compris", row.questions[6].question)
        self.assertIn("en plus des 1 500", row.questions[6].answer)
        self.assertIn("l'été prochain", row.questions[7].question)
        colleague = self.by_group["colleague-canada-trip-report"]
        self.assertIn("combien de temps", colleague.questions[0].question)
        self.assertNotIn("Si tu as changé", colleague.questions[3].question)
        self.assertIn("comprenait le vol", colleague.questions[7].question)

    def test_joint_countryside_planning_does_not_require_an_unprompted_activity_list(self):
        row = self.by_group["invite-friend-countryside-stay"]
        self.assertIn("m'accompagner", row.questions[0].question)
        self.assertNotIn("marcher", row.questions[3].answer)
        self.assertIn("tu préférerais marcher", row.questions[4].question)
        self.assertIsNone(row.questions[4].follow_up_to)
        self.assertIn("If they decline", row.note)
        self.assertIn("stop joint planning", row.note)

    def test_weather_backups_and_mountaineering_plans_do_not_repeat_or_assume_skiing(self):
        region = self.by_group["colleague-known-region-holiday"]
        self.assertIn("sans trop d'allers-retours", region.questions[3].question)
        self.assertIn("s'il pleut", region.questions[5].question)
        december = self.by_group["visit-friend-canada-december-preparation"]
        self.assertIn("à l'intérieur", december.questions[5].question)
        self.assertEqual(december.questions[7].follow_up_to, 7)
        mountain = self.by_group["interlocutor-planned-mountain-trip"]
        self.assertIn("activités avez-vous prévu", mountain.questions[2].question)
        self.assertIn("ski", mountain.questions[2].answer)
        self.assertIn("solution de rechange", mountain.questions[7].question)

    def test_birthday_season_and_upcoming_trip_costs_remain_consistent_with_the_route(self):
        birthday = self.by_group["friend-canada-partner-birthday-trip"]
        self.assertIn("nature", birthday.questions[0].question)
        self.assertIn("période", birthday.questions[1].question)
        self.assertIn("voiture", birthday.questions[2].question)
        self.assertNotIn("hiver", birthday.questions[2].question)
        self.assertIn("pour nous deux", birthday.questions[5].question)
        upcoming = self.by_group["friend-upcoming-canada-trip-advice"]
        self.assertIn("excursion", upcoming.questions[0].answer)
        self.assertIn("depuis Toronto", upcoming.questions[6].answer)
        self.assertIn("sans compter le vol", upcoming.questions[7].question)
        self.assertIn("entre les villes", upcoming.questions[7].answer)

    def test_social_trip_report_and_country_comparison_keep_different_information_goals(self):
        party = self.by_group["party-new-acquaintance-trip-report"]
        self.assertIn("donné envie", party.questions[2].question)
        self.assertIn("feriez autrement", party.questions[7].question)
        self.assertNotIn("budget", " ".join(q.question for q in party.questions))
        countries = self.by_group["friend-visited-countries-destination-choice"]
        self.assertIn("déjà visités", countries.questions[0].question)
        self.assertIn("séjour comparable", countries.questions[7].question)
        self.assertIn("lié à mes dates", countries.questions[7].answer)
        self.assertNotIn("vol aller-retour", countries.questions[7].question)
