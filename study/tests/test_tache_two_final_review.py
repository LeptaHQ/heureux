import json
import re

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tests.eo2_review_fixtures import (
    FINAL_PASS_FIELDS, PUBLISHED_ARCHIVE_INDEX, PUBLISHED_LAYOUT_SHA, REVIEWED_GROUPS,
)
from study.tests.test_tache_two_work_school_review import fingerprint


class FinalEo2ReviewTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        catalogue.clear_catalogue_cache()
        cls.dialogues = catalogue.tache_two_dialogues()
        cls.by_group = {row.group: row for row in cls.dialogues.values()}
        cls.hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"]

    @classmethod
    def tearDownClass(cls):
        catalogue.clear_catalogue_cache()
        super().tearDownClass()

    def test_final_scope_keeps_all_fifty_models_and_their_one_hundred_five_publications(self):
        self.assertEqual(len(REVIEWED_GROUPS), 50)
        self.assertEqual(len(FINAL_PASS_FIELDS), 13)
        self.assertLessEqual(FINAL_PASS_FIELDS.keys(), REVIEWED_GROUPS)
        self.assertEqual(
            sum(row.group in REVIEWED_GROUPS for row in self.dialogues.values()), 105,
        )
        for group in REVIEWED_GROUPS:
            row = self.by_group[group]
            self.assertEqual(len(row.questions), 8)
            self.assertEqual(len(self.hints[group]), 8)
            self.assertIn("merci", row.closing.casefold())

    def test_all_exact_published_layouts_keep_fixed_archive_positions(self):
        history = json.loads((
            content.QUESTION_BANK_DIR / "dialogue_history/locations.json"
        ).read_text())["groups"]
        self.assertEqual(PUBLISHED_ARCHIVE_INDEX.keys(), REVIEWED_GROUPS)
        snapshots = [
            history[group]["revisions"][PUBLISHED_ARCHIVE_INDEX[group]]
            for group in sorted(REVIEWED_GROUPS)
        ]
        self.assertEqual(fingerprint(snapshots), PUBLISHED_LAYOUT_SHA)
        for snapshot in snapshots:
            self.assertTrue(all("answer" not in q for q in snapshot["questions"]))

    def test_activity_survey_starts_with_studies_not_an_unneeded_origin_question(self):
        row = self.by_group["french-class-survey-francophone-student"]
        self.assertEqual(row.questions[0].question, "Qu'est-ce que vous étudiez en ce moment ?")
        self.assertEqual(row.questions[0].answer, "J'étudie le génie informatique.")
        self.assertIn("Current field of study", self.hints[row.group][0]["english"])
        self.assertNotIn("Quebec student", row.note)

    def test_colleague_comparison_does_not_assume_employment_in_quebec(self):
        row = self.by_group["new-colleague-quebec-career-migration"]
        self.assertIn("précédents emplois", row.questions[7].question)
        self.assertNotIn("Québec", row.questions[7].question)
        self.assertIn("proposition écrite", row.questions[7].answer)

    def test_salary_question_is_tactful_personal_and_precise_about_gross_annual_pay(self):
        row = self.by_group["former-colleague-new-job-to-change-employment"]
        self.assertIn("Si tu es d'accord", row.questions[4].question)
        self.assertIn("ton salaire annuel brut", row.questions[4].question)
        self.assertIn("fourchette", row.questions[4].question)
        self.assertIn("hors primes", row.questions[4].answer)

    def test_private_car_motorization_question_does_not_force_a_petrol_diesel_binary(self):
        row = self.by_group["private-owner-used-car-purchase"]
        self.assertIn("motorisation", row.questions[2].question)
        self.assertNotIn("essence ou diesel", row.questions[2].question)
        self.assertIn("Powertrain", self.hints[row.group][2]["english"])

    def test_carpool_fare_discloses_booking_fees_before_cancellation_terms(self):
        row = self.by_group["friend-carpooling-offer"]
        self.assertIn("12 $ pour l'aller", row.questions[4].answer)
        self.assertIn("dont 2 $ de frais", row.questions[4].answer)
        self.assertIn("hors frais de service", row.questions[7].answer)

    def test_countryside_companion_is_asked_about_transport_without_assuming_car_ownership(self):
        row = self.by_group["invite-friend-countryside-stay"]
        self.assertIn("m'accompagner", row.questions[0].question)
        self.assertIn("tu aurais une voiture", row.questions[7].question)
        self.assertIn("autre solution", row.questions[7].question)
        self.assertIn("ma voiture", row.questions[7].answer)
        self.assertIn("parts égales", row.questions[7].answer)

    def test_international_tour_fare_names_the_quoted_currency(self):
        row = self.by_group["travel-agency-choose-holiday-destination"]
        self.assertIn("devise", row.questions[3].question)
        self.assertIn("dollars canadiens", row.questions[3].answer)
        self.assertIn("currency", self.hints[row.group][3]["english"])

    def test_cruise_question_checks_the_shared_cabin_basis_of_the_price(self):
        row = self.by_group["travel-agency-canada-cruise"]
        self.assertIn("cabine partagée", row.questions[3].question)
        self.assertIn("supplément", row.questions[3].answer)
        self.assertIn("shared cabin", self.hints[row.group][3]["english"])

    def test_electric_bike_test_ride_includes_a_hill_to_try_the_assistance(self):
        row = self.by_group["friend-used-electric-bicycle-sale"]
        self.assertIn("dans une côte", row.questions[7].question)
        self.assertIn("assistance électrique", row.questions[7].question)
        self.assertIn("une montée", row.questions[7].answer)
        self.assertIn("on a hill", self.hints[row.group][7]["english"])

    def test_birthday_activity_price_has_both_a_duration_and_a_two_person_basis(self):
        row = self.by_group["friend-canada-partner-birthday-trip"]
        self.assertIn("une heure de canot", row.questions[5].answer)
        self.assertIn("deux personnes", row.questions[5].answer)
        self.assertIn("vérifier le tarif", row.questions[5].answer)

    def test_ski_budget_reply_accounts_for_the_actual_amount_paid_not_unused_gate_prices(self):
        row = self.by_group["interlocutor-planned-mountain-trip"]
        self.assertIn("nous espérons", row.questions[1].answer)
        answer = row.questions[6].answer
        amounts = [int(value.replace(" ", "")) for value in re.findall(r"(\d[\d ]*) \$", answer)]
        self.assertEqual(amounts, [500, 2000])
        self.assertEqual(amounts[0] * 4, amounts[1])
        self.assertIn("un quart", answer)
        self.assertIn("cinq jours de ski", answer)
        self.assertIn("à l'avance", answer)

    def test_seaside_reply_identifies_a_region_and_keeps_the_personal_budget_basis(self):
        row = self.by_group["friend-seaside-holiday-advice"]
        self.assertIn("Gaspésie", row.questions[0].answer)
        self.assertIn("près de Percé", row.questions[0].answer)
        self.assertIn("dollars canadiens pour moi", row.questions[3].answer)
        self.assertIn("hors trajet", row.questions[3].answer)
