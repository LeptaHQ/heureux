import copy
import hashlib
import json
import re
from pathlib import Path

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tache_two_dialogues import dialogue_response


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
    ).hexdigest()


class OutingsDevelopmentCorpusTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.fixture = json.loads(
            Path(__file__).with_name("outings_development_fixtures.json").read_text(),
        )
        self.raw = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        self.hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"]
        self.history = json.loads((
            content.QUESTION_BANK_DIR / "dialogue_history/locations.json"
        ).read_text())
        self.dialogues = catalogue.tache_two_dialogues()
        self.by_group = {row.group: row for row in self.dialogues.values()}

    def test_first_two_displayed_models_and_all_unrelated_content_remain_exact(self):
        _, mapping = catalogue.tache_two_subject_themes()
        ordered, seen = [], set()
        for month in catalogue.tache_two_subject_months():
            for batch in month.batches:
                for subject in batch.subjects:
                    key = content.tache_two_subject_content_key(
                        month.slug, batch.number, subject.number,
                    )
                    group = self.dialogues[key].group
                    if mapping[key] == self.fixture["theme"] and group not in seen:
                        ordered.append(group)
                        seen.add(group)
        self.assertEqual(len(ordered), 9)
        self.assertEqual(ordered[:2], self.fixture["preserved_first_two"])
        affected = set(self.fixture["groups"])
        self.assertEqual(set(ordered[2:]), affected)
        self.assertEqual(
            fingerprint({g: row for g, row in self.raw.items() if g not in affected}),
            self.fixture["protected_models_sha"],
        )
        self.assertEqual(
            fingerprint({g: row for g, row in self.hints.items() if g not in affected}),
            self.fixture["protected_hints_sha"],
        )

    def test_all_twelve_publications_use_the_seven_reviewed_models_in_the_same_theme(self):
        _, mapping = catalogue.tache_two_subject_themes()
        keys = {
            key for key, row in self.dialogues.items()
            if row.group in self.fixture["groups"]
        }
        self.assertEqual(keys, {
            "tache2:fevrier:batch-02:subject-07",
            "tache2:fevrier:batch-06:subject-28",
            "tache2:juin:batch-07:subject-33",
            "tache2:septembre:batch-02:subject-08",
            "tache2:avril:batch-01:subject-02",
            "tache2:juin:batch-09:subject-42",
            "tache2:decembre:batch-03:subject-12",
            "tache2:mai:batch-05:subject-20",
            "tache2:aout:batch-02:subject-06",
            "tache2:octobre:batch-07:subject-31",
            "tache2:octobre:batch-08:subject-40",
            "tache2:decembre:batch-10:subject-50",
        })
        self.assertEqual(len(self.fixture["groups"]), 7)
        self.assertEqual(len(self.dialogues), 348)
        self.assertEqual(len(self.by_group), 164)
        for key in keys:
            self.assertEqual(mapping[key], self.fixture["theme"])

    def test_every_developed_model_and_its_eight_bilingual_pistes_are_approved(self):
        for group, record in self.fixture["groups"].items():
            with self.subTest(group=group):
                self.assertEqual(fingerprint(self.raw[group]), record["after_sha"])
                self.assertEqual(fingerprint(self.hints[group]), record["after_hints_sha"])
                row = self.by_group[group]
                self.assertEqual(len(row.questions), 8)
                self.assertEqual(len(self.hints[group]), 8)
                response = dialogue_response(row)
                self.assertEqual(
                    [argument.idea for argument in response.arguments],
                    [question.question for question in row.questions],
                )
                self.assertTrue(
                    all(argument.developpement == "" for argument in response.arguments),
                )

    def test_exact_preceding_layouts_and_every_older_history_entry_are_preserved(self):
        original = copy.deepcopy(self.history)
        for group, record in self.fixture["groups"].items():
            with self.subTest(group=group):
                index = record["archive_index"]
                revisions = self.history["groups"][group]["revisions"]
                self.assertEqual(len(revisions), index + 1)
                previous = revisions[index]
                self.assertEqual(fingerprint(previous), record["before_visible_sha"])
                self.assertEqual(set(previous), {"group", "opening", "closing", "questions"})
                self.assertTrue(all("answer" not in q for q in previous["questions"]))
                if index:
                    original["groups"][group]["revisions"] = revisions[:index]
                else:
                    self.assertEqual(original["groups"].pop(group)["replacements"], [])
        self.assertEqual(fingerprint(original), self.fixture["original_history_sha"])

    def test_evening_opener_is_retained_and_budget_includes_admission_and_a_drink(self):
        group = "new-neighbor-evening-entertainment"
        row = self.raw[group]
        record = self.fixture["groups"][group]
        previous = self.history["groups"][group]["revisions"][record["archive_index"]]
        self.assertEqual(
            row["questions"][0]["question"],
            "Quels endroits me conseilleriez-vous pour sortir le soir dans le quartier, et qu'est-ce qu'on peut y faire ?",
        )
        self.assertEqual(row["opening"], previous["opening"])
        self.assertEqual(row["closing"], previous["closing"])
        self.assertIn("avec l'entrée et une boisson", row["questions"][4]["question"])
        self.assertIn("25 $ pour le concert et une boisson", row["questions"][4]["answer"])
        self.assertEqual(record["retained_questions"], {
            str(number): number for number in (1, 2, 3, 4, 6, 7, 8)
        })
        for number in (1, 2, 3, 4, 6, 7, 8):
            self.assertEqual(
                {key: value for key, value in row["questions"][number - 1].items() if key != "answer"},
                previous["questions"][number - 1],
            )

    def test_cultural_staff_cover_citywide_activities_access_and_pass_exclusions(self):
        row = self.by_group["municipal-cultural-service-city-activities"]
        self.assertEqual(row.register, "vous")
        for index, text in {
            0: "expositions et quels musées",
            1: "jusqu'à quand",
            2: "débutants",
            3: "jours proposés et la durée",
            4: "que comprend le tarif",
            5: "personne à mobilité réduite",
            6: "combien de temps à l'avance",
            7: "plus intéressant que des billets séparés",
        }.items():
            self.assertIn(text, row.questions[index].question)
        self.assertIn("matériel compris", row.questions[4].answer)
        self.assertIn("fiches précisent", row.questions[5].answer)
        self.assertIn("Les ateliers ne sont pas inclus", row.questions[7].answer)

    def test_municipal_outings_neighbour_gives_experience_not_live_booking_guarantees(self):
        row = self.by_group["neighbor-municipal-cultural-outings"]
        self.assertEqual(row.register, "vous")
        self.assertIn("they do not organise", row.note)
        self.assertIn("déjà participé", row.questions[0].question)
        self.assertIn("le plus plu", row.questions[0].question)
        self.assertIn("trajet compris", row.questions[2].answer)
        self.assertIn("Le repas reste à notre charge", row.questions[3].answer)
        self.assertIn("combien de temps avant", row.questions[4].question)
        self.assertEqual(row.questions[4].follow_up_to, 4)
        self.assertIn("si l'on vient seul", row.questions[5].question)
        self.assertIn("Le service culturel pourra vous confirmer", row.questions[6].answer)
        self.assertIn("programme des prochaines sorties", row.questions[7].question)

    def test_ottawa_restaurant_uses_actual_experience_and_does_not_promise_allergen_safety(self):
        row = self.by_group["friend-new-ottawa-restaurant"]
        self.assertEqual(row.register, "tu")
        self.assertIn("Ottawa", row.questions[0].question)
        self.assertIn("tu as commandé", row.questions[2].question)
        self.assertIn("plu ou déçu", row.questions[2].question)
        self.assertIn("comment s'est passé le service", row.questions[3].question)
        self.assertIn("Comme tu as attendu", row.questions[4].question)
        self.assertEqual(row.questions[4].follow_up_to, 4)
        self.assertIn("taxes et pourboire compris", row.questions[5].answer)
        self.assertIn("carte et les horaires à jour", row.questions[7].question)
        self.assertIn("Confirm dietary needs directly with the restaurant", row.note)

    def test_low_budget_outings_include_weather_route_choices_and_real_total_costs(self):
        row = self.by_group["new-city-friend-low-budget-outings"]
        self.assertEqual(row.register, "tu")
        self.assertIn("sans payer d'entrée", row.questions[0].question)
        self.assertIn("parcours", row.questions[1].question)
        self.assertIn("S'il pleut", row.questions[2].question)
        self.assertIn("l'exposition concernée", row.questions[4].answer)
        self.assertIn("lesquels peut-on rejoindre à pied", row.questions[5].question)
        self.assertIn("un billet à l'unité, un pass à la journée ou un abonnement", row.questions[6].question)
        self.assertIn("budget total", row.questions[7].question)
        self.assertIn("si tu achètes un en-cas", row.questions[7].answer)
        self.assertNotIn(
            "Les musées sont gratuits le premier dimanche",
            " ".join(question.answer for question in row.questions),
        )

    def test_tonight_plan_does_not_repeat_the_start_time_or_call_a_concert_a_session(self):
        row = self.by_group["friend-choose-tonight-outing"]
        self.assertEqual(row.register, "tu")
        self.assertIn("vingt et une heures", row.questions[0].answer)
        self.assertIn("dure à peu près combien de temps", row.questions[2].question)
        self.assertNotIn("séance", " ".join(q.question for q in row.questions))
        self.assertIn("budget", row.questions[3].question)
        self.assertIn("s'il reste des places pour ce soir", row.questions[5].question)
        self.assertIn("rentrer après le concert", row.questions[6].question)
        self.assertIn("avoir le temps de manger", row.questions[7].question)

    def test_tourist_office_compares_actual_prices_and_checks_cycling_requirements(self):
        row = self.by_group["tourist-office-city-discovery-with-friends"]
        self.assertEqual(row.register, "vous")
        self.assertIn("quel niveau faut-il", row.questions[2].question)
        self.assertIn("savoir rouler et freiner", row.questions[2].answer)
        self.assertIn("d'où part chacune", row.questions[6].question)
        self.assertIn("tous les jours", row.questions[6].answer)
        self.assertIn("du jeudi au samedi", row.questions[6].answer)
        regular, group, evening = [
            int(value) for value in re.findall(r"(\d+)\s*\$", row.questions[4].answer)
        ]
        combined, = [
            int(value) for value in re.findall(r"(\d+)\s*\$", row.questions[5].answer)
        ]
        self.assertLess(group + evening, combined)
        self.assertLess(combined, regular + evening)
        self.assertIn("non cumulable avec le tarif de groupe", row.questions[5].answer)
        self.assertIn("les billets séparés sont donc moins chers", row.questions[5].answer)
