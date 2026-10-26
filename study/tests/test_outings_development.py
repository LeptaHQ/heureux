import copy
import hashlib
import json
import re
from pathlib import Path

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tache_two_dialogues import dialogue_response
from study.tests.eo2_review_fixtures import REVIEWED_GROUPS, remove_latest_review_archives


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
        protected = affected | REVIEWED_GROUPS
        self.assertEqual(len(self.raw.keys() - protected), 107)
        self.assertEqual(
            fingerprint({
                "dialogues": {g: row for g, row in self.raw.items() if g not in protected},
                "hints": {g: row for g, row in self.hints.items() if g not in protected},
            }),
            "a43e1ffdbd0030f1f7b93033fc7ad34221c7533d6643c14fbcda5fea38f1d51b",
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
        remove_latest_review_archives(original)
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

    def test_evening_question_suggests_options_and_budget_includes_admission_and_a_drink(self):
        group = "new-neighbor-evening-entertainment"
        row = self.raw[group]
        record = self.fixture["groups"][group]
        previous = self.history["groups"][group]["revisions"][record["archive_index"]]
        self.assertEqual(
            row["questions"][0]["question"],
            "Pour sortir le soir dans le quartier, quels endroits me conseilleriez-vous, par exemple un cinéma ou un café qui propose des concerts ?",
        )
        self.assertEqual(row["opening"], previous["opening"])
        self.assertEqual(row["closing"], previous["closing"])
        self.assertIn("avec l'entrée et une boisson", row["questions"][4]["question"])
        self.assertIn("25 $ pour le concert et une boisson", row["questions"][4]["answer"])
        self.assertEqual(record["retained_questions"], {
            str(number): number for number in (2, 3, 4, 6, 7, 8)
        })
        for number in (2, 3, 4, 6, 7, 8):
            self.assertEqual(
                {key: value for key, value in row["questions"][number - 1].items() if key != "answer"},
                previous["questions"][number - 1],
            )

    def test_cultural_staff_cover_citywide_activities_access_and_pass_exclusions(self):
        group = "municipal-cultural-service-city-activities"
        row = self.by_group[group]
        self.assertEqual(row.register, "vous")
        self.assertEqual([question.topic for question in row.questions], [
            *(["Lieux et expositions"] * 2),
            *(["Ateliers et horaires"] * 2),
            *(["Tarifs, accès et inscriptions"] * 4),
        ])
        self.assertEqual([question.question for question in row.questions[:4]], [
            "Quels lieux culturels me conseilleriez-vous de découvrir dans la ville, par exemple des musées, des galeries ou des centres culturels ?",
            "Dans les lieux que vous conseillez, quelles expositions peut-on voir en ce moment, et jusqu'à quand sont-elles proposées ?",
            "Propose-t-on aussi des ateliers pour débutants, par exemple en dessin ou en photographie, et qu'est-ce qu'on y apprend ?",
            "Quels sont les horaires de visite de ces lieux, et quels jours ont lieu les ateliers ?",
        ])
        self.assertIn("options, not assumed services", row.note)
        self.assertIn("actual recommendations", row.note)
        self.assertIn("ask only for missing details", row.note)
        self.assertEqual([question.follow_up_to for question in row.questions[:4]], [
            None, 1, None, 3,
        ])
        for index in (1, 3):
            self.assertIn("remain unclear", row.questions[index].condition)
        self.assertIn("permanente", row.questions[1].answer)
        self.assertIn("croquis et l'aquarelle", row.questions[2].answer)
        self.assertIn("dix-huit heures", row.questions[3].answer)
        self.assertIn("dix-sept heures", row.questions[3].answer)
        for index, text in {
            4: "que comprend le tarif",
            5: "personne à mobilité réduite",
            6: "combien de temps à l'avance",
            7: "plus intéressant que des billets séparés",
        }.items():
            self.assertIn(text, row.questions[index].question)
        self.assertIn("matériel compris", row.questions[4].answer)
        self.assertIn("fiches précisent", row.questions[5].answer)
        self.assertIn("Les ateliers ne sont pas inclus", row.questions[7].answer)
        record = self.fixture["groups"][group]
        self.assertEqual(
            fingerprint(self.raw[group]["questions"][4:]),
            record["preserved_final_questions_sha"],
        )
        self.assertEqual(
            fingerprint(self.hints[group][4:]),
            record["preserved_final_hints_sha"],
        )
        self.assertEqual(self.hints[group][:4], [
            {
                "french": "Lieux conseillés : musées, galeries ou centres culturels",
                "english": "Recommended venues: museums, galleries or cultural centres",
            },
            {
                "french": "Expositions en cours dans les lieux conseillés et dates de fin",
                "english": "Current exhibitions at the recommended venues and their end dates",
            },
            {
                "french": "Ateliers pour débutants : dessin ou photographie et apprentissages",
                "english": "Beginner workshops: drawing or photography and what participants learn",
            },
            {
                "french": "Horaires de visite des lieux conseillés et jours des ateliers",
                "english": "Visiting hours at the recommended venues and workshop days",
            },
        ])

    def test_municipal_outings_neighbour_gives_experience_not_live_booking_guarantees(self):
        row = self.by_group["neighbor-municipal-cultural-outings"]
        self.assertEqual(row.register, "vous")
        self.assertIn("they do not organise", row.note)
        self.assertIn("déjà participé", row.questions[0].question)
        self.assertIn("le plus plu", row.questions[0].question)
        self.assertIn("combien de temps faut-il prévoir au total", row.questions[2].question)
        self.assertIn("trajet compris", row.questions[2].answer)
        self.assertIn("Le repas reste à notre charge", row.questions[3].answer)
        self.assertEqual(
            row.questions[4].question,
            "Pour le départ en car, où est le point de rendez-vous, et à quelle heure faut-il être sur place ?",
        )
        self.assertEqual(row.questions[4].follow_up_to, 4)
        self.assertIn("If coach travel is included", row.questions[4].condition)
        self.assertEqual(self.hints[row.group][4], {
            "french": "Point de rendez-vous et heure d'arrivée pour le départ en car",
            "english": "Meeting point and required arrival time for the coach departure",
        })
        self.assertEqual(
            row.questions[5].question,
            "D'après votre expérience, comment est l'ambiance dans le groupe : les participants font-ils facilement connaissance ?",
        )
        self.assertIn("Dans le car et pendant les pauses", row.questions[5].answer)
        self.assertEqual(self.hints[row.group][5], {
            "french": "Ambiance du groupe et échanges entre participants",
            "english": "Group atmosphere and interaction between participants",
        })
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
        self.assertEqual(
            row.questions[6].question,
            "Pour rentrer après une sortie le soir, jusqu'à quelle heure les bus circulent-ils ?",
        )
        self.assertEqual(row.questions[6].follow_up_to, 6)
        self.assertIn("If bus travel is relevant", row.questions[6].condition)
        self.assertIn("Ça dépend de la ligne et du jour", row.questions[6].answer)
        self.assertIn("vérifie l'horaire du retour", row.questions[6].answer)
        self.assertIn("actual route and day", row.note)
        self.assertIn("do not assume late service", row.note)
        self.assertEqual(self.hints[row.group][6], {
            "french": "Dernier bus pour rentrer le soir selon la ligne et le jour",
            "english": "Last bus home after an evening outing, depending on the route and day",
        })
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
        self.assertEqual(
            row.questions[4].question,
            "Pendant le concert, est-ce qu'on peut s'asseoir ou est-ce qu'on reste debout ?",
        )
        self.assertEqual(row.questions[4].follow_up_to, 4)
        self.assertIn("without clarifying seating arrangements", row.questions[4].condition)
        self.assertIn("places assises sont limitées", row.questions[4].answer)
        self.assertIn("rester debout", row.questions[4].answer)
        self.assertEqual(self.hints[row.group][4], {
            "french": "Places assises ou public debout pendant le concert",
            "english": "Seating or standing during the concert",
        })
        self.assertIn("s'il reste des places pour ce soir", row.questions[5].question)
        self.assertEqual(
            row.questions[6].question,
            "Pour aller au bar et rentrer après le concert, quel moyen de transport nous coûterait le moins cher ?",
        )
        self.assertEqual(self.hints[row.group][6], {
            "french": "Transport économique pour l'aller-retour au concert",
            "english": "Affordable transport to the concert and back",
        })
        self.assertEqual(
            row.questions[7].question,
            "Où et à quelle heure est-ce qu'on se retrouve pour aller au concert ensemble ?",
        )
        self.assertEqual(self.hints[row.group][7], {
            "french": "Lieu et heure de rendez-vous pour partir ensemble",
            "english": "Meeting place and time to travel together",
        })
        self.assertIn("vingt heures quarante-cinq", row.questions[7].answer)
        self.assertNotRegex(
            " ".join(f"{q.question} {q.answer}" for q in row.questions),
            r"\b(?:manger|repas|pizzeria)\b",
        )

    def test_tourist_office_balances_city_discovery_options_and_practical_arrangements(self):
        row = self.by_group["tourist-office-city-discovery-with-friends"]
        self.assertEqual(row.register, "vous")
        self.assertEqual([question.topic for question in row.questions], [
            *(["Lieux et activités"] * 4),
            *(["Horaires et tarifs"] * 2),
            *(["Accès et réservation"] * 2),
        ])
        for index, goal in enumerate((
            "Quels quartiers et monuments",
            "visites guidées ou un parcours à suivre à notre rythme",
            "par exemple une balade en bateau ou un atelier de cuisine locale",
            "en soirée pour découvrir la vie culturelle",
            "les jours et les horaires de ces activités",
            "des réductions pour les groupes",
            "à pied depuis l'office",
            "Pour quelles activités faut-il réserver à l'avance",
        )):
            self.assertIn(goal, row.questions[index].question)
        self.assertEqual(row.questions[1].follow_up_to, 1)
        self.assertIn("guided and independent options remain unclear", row.questions[1].condition)
        self.assertIn("un plan gratuit", row.questions[1].answer)
        self.assertIn("on les déguste ensemble", row.questions[2].answer)
        self.assertIn("musiciens locaux", row.questions[3].answer)
        self.assertIn("combien de temps dure chacune", row.questions[4].question)
        self.assertIn("tous les jours", row.questions[4].answer)
        self.assertIn("samedi", row.questions[4].answer)
        self.assertIn("vendredi", row.questions[4].answer)
        self.assertEqual(
            [int(value) for value in re.findall(r"(\d+)\s*\$", row.questions[5].answer)],
            [12, 25, 15, 9],
        )
        self.assertIn("Dès six participants", row.questions[5].answer)
        self.assertIn("la visite guidée revient à 9 $", row.questions[5].answer)
        self.assertIn("La visite part d'ici", row.questions[6].answer)
        self.assertIn("à cinq minutes à pied", row.questions[6].answer)
        self.assertIn("quinze minutes de tramway", row.questions[6].answer)
        self.assertIn("au moins la veille", row.questions[7].answer)
        self.assertIn("s'il reste des billets", row.questions[7].answer)
        self.assertIn("without committing to every suggestion", row.note)
        self.assertIn("Ask only for missing details", row.note)
        self.assertIn("Do not assume your group qualifies for a discount", row.note)
        self.assertNotRegex(
            json.dumps(self.raw[row.group], ensure_ascii=False).casefold(),
            r"vélo|casque|cycling|billet combiné|deux visites",
        )
        self.assertEqual([hint["french"] for hint in self.hints[row.group]], [
            "Quartiers et monuments à découvrir en priorité",
            "Visites guidées ou découverte à notre rythme",
            "Activités entre amis, par exemple bateau ou cuisine locale",
            "Vie culturelle en soirée : spectacles ou concerts",
            "Jours, horaires et durée des activités proposées",
            "Tarifs par personne et réductions pour les groupes",
            "Accès aux lieux depuis l'office, à pied ou en transports",
            "Activités à réserver à l'avance et moyens de réservation",
        ])
