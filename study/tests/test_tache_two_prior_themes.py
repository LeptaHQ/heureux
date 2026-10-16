import hashlib
import json

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tests.housing_work_fixtures import ORIGINAL_HOUSING_GROUPS, ORIGINAL_WORK_GROUPS
from study.tests.neighbourhood_fixtures import ALL_NEIGHBOURHOOD_GROUPS


class TacheTwoPriorThemeReviewTests(SimpleTestCase):
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

    def test_review_keeps_all_thirty_three_models_and_sixty_six_publications(self):
        for theme, publications, groups in (("vie-quartier", 36, 18), ("travail", 30, 15)):
            rows = [
                row for key, row in self.dialogues.items()
                if (row.group in ALL_NEIGHBOURHOOD_GROUPS if theme == "vie-quartier"
                    else row.group in ORIGINAL_WORK_GROUPS)
            ]
            with self.subTest(theme=theme):
                self.assertEqual(len(rows), publications)
                self.assertEqual(len({row.group for row in rows}), groups)
                for row in rows:
                    self.assertEqual(len(row.questions), 8)
                    self.assertEqual(len(self.hints[row.group]), 8)
                    self.assertIn("merci", row.closing.lower())

    def test_excluded_themes_and_latest_education_pass_remain_exactly_unchanged(self):
        rows = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        expected = {
            "arrivee": "eeb337d3fd34d07c863b10f58fa4da53bae6f1b91822e56eaa8042170a48e278",
            "logement": "e650f8cfbd4e5c653958e7601692e2d4d0549302f09a4e9b9bdfa7f53f240847",
            "ecole-etudes": "b6c49581312a9e3dda84699ce4a24e371dcd46c20fd789a7bd86f60e0f952142",
        }
        for theme, digest in expected.items():
            with self.subTest(theme=theme):
                groups = ORIGINAL_HOUSING_GROUPS if theme == "logement" else {
                    row.group for key, row in self.dialogues.items() if self.themes[key] == theme
                }
                snapshot = json.dumps(
                    [rows[group] for group in sorted(groups)],
                    ensure_ascii=False, sort_keys=True,
                ).encode()
                self.assertEqual(hashlib.sha256(snapshot).hexdigest(), digest)
        self.assertNotIn("new-resident-neighbor-neighborhood-orientation", self.history)

    def test_exact_pre_review_visible_layouts_remain_archived_without_simulated_answers(self):
        indices = {
            "friend-three-year-old-weekend-care": 1,
            "grocery-store-home-delivery": 1,
            "help-friend-post-parcel": 1,
            "medical-secretary-temporary-replacement-doctor": 0,
            "volunteer-local-association-information-office": 1,
            "friend-association-work-experience": 1,
            "supervisor-overseas-job-offer": 2,
            "recruiter-scheduled-interview-preparation": 1,
        }
        snapshots = []
        for group, index in sorted(indices.items()):
            before = self.history[group]["revisions"][index]
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
            "2388de9b8fc8e776ef171005cc48755fbab9043517af0e66e0a7f12ad6239342",
        )

    def test_sleep_timings_are_distinct_from_previously_supplied_care_timings(self):
        weekend = self.by_group["friend-three-year-old-weekend-care"]
        self.assertIn("already supplies timings", weekend.note)
        self.assertIn("fait-elle une sieste", weekend.questions[5].question)
        self.assertIn("se couche-t-elle et se réveille-t-elle", weekend.questions[5].question)
        self.assertNotIn("s'endormir", weekend.questions[5].question)
        self.assertIn("13 h 30 à 15 h", weekend.questions[5].answer)
        self.assertIn("19 h 30", weekend.questions[5].answer)
        self.assertIn("7 h", weekend.questions[5].answer)
        self.assertIn("pour la sieste et le soir", weekend.questions[6].question)
        self.assertIn("se réveille la nuit", weekend.questions[6].question)
        self.assertIn("doudou", weekend.questions[6].answer)
        self.assertIn("veilleuse", weekend.questions[6].answer)
        self.assertEqual(weekend.questions[6].follow_up_to, 6)
        self.assertIn("skip nap details if she does not nap", weekend.note)
        self.assertEqual(
            self.hints[weekend.group][5]["english"], "Bedtime, waking time and whether she naps",
        )
        self.assertEqual(
            self.hints[weekend.group][6]["english"],
            "Nap and bedtime routines, and comfort during night waking",
        )

    def test_parcel_size_and_weight_leave_room_for_the_errands_actual_time_burden(self):
        parcel = self.by_group["help-friend-post-parcel"]
        self.assertIn("dimensions", parcel.questions[4].question)
        self.assertIn("pèse", parcel.questions[4].question)
        self.assertIn("boîte à chaussures", parcel.questions[4].answer)
        self.assertIn("deux kilos", parcel.questions[4].answer)
        self.assertIn("bureau de poste", parcel.questions[5].question)
        self.assertIn("aller-retour", parcel.questions[5].question)
        self.assertIn("à dix minutes à pied", parcel.questions[5].answer)
        self.assertIn("demi-heure au total", parcel.questions[5].answer)
        self.assertIn("attente au guichet", parcel.questions[5].answer)
        self.assertEqual(parcel.questions[3].follow_up_to, 3)
        self.assertIn("cannot guarantee", parcel.note)
        self.assertEqual(
            self.hints[parcel.group][4]["english"], "Approximate parcel dimensions and weight",
        )
        self.assertEqual(
            self.hints[parcel.group][5]["english"],
            "Suggested post office and round-trip time including the deposit",
        )

    def test_volunteer_feasibility_covers_actual_hours_and_optional_versus_regular_commitment(self):
        office = self.by_group["volunteer-local-association-information-office"]
        self.assertIn("does not necessarily run", office.note)
        self.assertIn("jours et à quelles heures", office.questions[3].question)
        self.assertIn("18 h à 20 h", office.questions[3].answer)
        self.assertIn("14 h à 17 h", office.questions[3].answer)
        self.assertIn("confirmera les places disponibles", office.questions[3].answer)
        self.assertIn("ponctuellement", office.questions[4].question)
        self.assertIn("sans m'engager pour plusieurs mois", office.questions[4].question)
        self.assertIn("Pour ces missions, non", office.questions[4].answer)
        self.assertIn("toutes les deux semaines", office.questions[4].answer)
        self.assertIn("trois mois", office.questions[4].answer)
        self.assertIn("vérifiez", office.questions[4].answer)
        self.assertEqual(
            self.hints[office.group][4]["english"],
            "Possibility of occasional help without a commitment lasting several months",
        )

    def test_replacement_doctor_question_checks_location_not_already_confirmed_coverage(self):
        doctor = self.by_group["medical-secretary-temporary-replacement-doctor"]
        self.assertIn("already covers your family doctor's absence", doctor.note)
        self.assertIn("not medical advice", doctor.note)
        self.assertEqual(
            doctor.questions[2].question,
            "Consulte-t-elle dans le même cabinet que mon médecin habituel ?",
        )
        self.assertIsNone(doctor.questions[2].follow_up_to)
        self.assertEqual(doctor.questions[3].follow_up_to, 3)
        self.assertIn("Quels jours et à quelles heures", doctor.questions[5].question)
        self.assertEqual(
            self.hints[doctor.group][2]["english"], "Where the replacement doctor sees patients",
        )

    def test_redelivery_is_not_implicitly_free_or_left_outside_the_cold_chain(self):
        grocery = self.by_group["grocery-store-home-delivery"]
        self.assertIn("une nouvelle livraison est-elle payante", grocery.questions[6].question)
        self.assertIn("reviennent au magasin", grocery.questions[6].answer)
        self.assertIn("nouvelle livraison coûte", grocery.questions[6].answer)
        self.assertIn("7,99 $", grocery.questions[6].answer)
        self.assertEqual(
            self.hints[grocery.group][6]["english"], "Missed delivery and any redelivery fee",
        )
        self.assertNotIn("7,99", self.hints[grocery.group][6]["french"])

    def test_interview_format_precedes_arrival_and_access_without_rewriting_learned_questions(self):
        recruiter = self.by_group["recruiter-scheduled-interview-preparation"]
        before = self.history[recruiter.group]["revisions"][1]
        self.assertNotIn("ma venue", recruiter.opening)
        for old, new in ((2, 1), (1, 2), (3, 3)):
            self.assertEqual(
                before["questions"][old - 1]["question"], recruiter.questions[new - 1].question,
            )
        self.assertEqual(recruiter.questions[1].follow_up_to, 1)
        self.assertIn("connection time", recruiter.questions[1].condition)
        self.assertEqual(recruiter.questions[2].follow_up_to, 1)
        self.assertIn("online", recruiter.questions[2].condition)
        self.assertIn("connection time and link", recruiter.note)
        self.assertEqual(
            [row["english"] for row in self.hints[recruiter.group][:2]],
            ["In-person or remote interview", "Arrival time on interview day"],
        )

    def test_overtime_and_overseas_pay_questions_do_not_presuppose_extra_pay_or_adjustments(self):
        association = self.by_group["friend-association-work-experience"]
        self.assertIn("décales ton horaire", association.questions[5].question)
        self.assertIn("heures supplémentaires", association.questions[6].question)
        self.assertIn("paiement", association.questions[6].question)
        self.assertIn("temps de repos", association.questions[6].question)
        self.assertEqual(association.questions[6].follow_up_to, 6)
        self.assertIn("extra hours", association.questions[6].condition)
        self.assertEqual(
            self.hints[association.group][6]["english"], "Choice of overtime pay or time off",
        )
        supervisor = self.by_group["supervisor-overseas-job-offer"]
        self.assertIn("dans quelle devise", supervisor.questions[4].question)
        self.assertIn("dollars américains", supervisor.questions[4].answer)
        self.assertIn("taux de conversion", supervisor.questions[4].answer)
        self.assertIn("pourrait-elle être réévaluée", supervisor.questions[5].question)
        self.assertIn("sur quels critères", supervisor.questions[5].question)
        self.assertEqual(supervisor.questions[5].follow_up_to, 5)
        self.assertIn("l'assurance santé", supervisor.questions[6].question)
        self.assertIn("assurance santé collective", supervisor.questions[6].answer)
        self.assertIn("devise", self.hints[supervisor.group][4]["french"])
        self.assertIn("health insurance", self.hints[supervisor.group][6]["english"])

    def test_hidden_replies_cover_feeding_times_expense_limits_and_all_named_visits(self):
        pet = self.by_group["trusted-person-temporary-pet-care"]
        self.assertIn("8 h et à 18 h", pet.questions[3].answer)
        self.assertIn("portions mesurées", pet.questions[3].answer)
        training = self.by_group["director-canada-fortnight-training"]
        self.assertIn("paie le vol et l'hôtel", training.questions[5].answer)
        self.assertIn("déplacements professionnels sur justificatifs", training.questions[5].answer)
        self.assertIn("60 $ par jour", training.questions[5].answer)
        self.assertIn("week-ends compris", training.questions[5].answer)
        orientation = self.by_group["new-employee-company-orientation"]
        self.assertIn("Mme Martin", orientation.questions[0].answer)
        self.assertIn("Mme Martin", orientation.questions[3].answer)
        visits = self.by_group["host-foreign-friends-city-advice"]
        for place in (
            "Pike Place Market", "Olympic Sculpture Park", "MOHAI", "front de mer",
        ):
            self.assertIn(place, visits.questions[6].answer)
        self.assertIn("bus", visits.questions[7].answer)
        self.assertIn("lignes prévues", visits.questions[7].answer)
