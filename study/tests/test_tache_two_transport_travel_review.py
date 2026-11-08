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

    def test_transit_enquiry_covers_destinations_live_information_tickets_and_practical_help(self):
        row = self.by_group["newcomer-city-transit-service"]
        self.assertEqual(len(row.questions), 8)
        self.assertEqual(
            row.questions[1].question,
            "Lesquels desservent le centre-ville, la gare et les principaux sites touristiques ?",
        )
        for place in ("centre", "gare", "sites touristiques"):
            self.assertIn(place, row.questions[1].answer)
        for index, text in (
            (2, "prochains passages en temps réel"), (4, "valider"),
            (5, "comment savoir quand descendre"), (6, "circulent-ils le soir"),
            (7, "caméras de surveillance"),
        ):
            self.assertIn(text, row.questions[index].question)
        self.assertIn("prochains passages en temps réel", row.questions[2].answer)
        self.assertIsNone(row.questions[2].follow_up_to)
        self.assertIsNone(row.questions[4].follow_up_to)
        self.assertIn("guichet", row.questions[4].answer)
        self.assertIn("lecteur", row.questions[4].answer)
        self.assertIn("Achat du titre et validation", self.hints[row.group][4]["french"])
        self.assertIn("Buying the fare and validating", self.hints[row.group][4]["english"])
        self.assertIn("faut-il demander l'arrêt", row.questions[5].question)
        self.assertIn("annoncé et affiché", row.questions[5].answer)
        self.assertIn("bouton d'arrêt", row.questions[5].answer)
        self.assertIn("un peu avant le vôtre", row.questions[5].answer)
        self.assertIsNone(row.questions[5].follow_up_to)
        self.assertIn("demande d'arrêt", self.hints[row.group][5]["french"])
        self.assertIn("requesting a stop", self.hints[row.group][5]["english"])
        self.assertNotIn("pass sera encore valable", " ".join(q.question for q in row.questions))
        self.assertIn("qui peut-on contacter en cas de problème", row.questions[7].question)
        self.assertEqual(row.questions[7].question.count("?"), 1)
        self.assertIn("conducteur du bus", row.questions[7].answer)
        self.assertIn("agent en station", row.questions[7].answer)
        self.assertIn("interphones du métro", row.questions[7].answer)
        self.assertNotIn("24 heures sur 24", row.questions[7].question)
        self.assertIn("temps réel", self.hints[row.group][2]["french"])
        self.assertIn("personnes à contacter", self.hints[row.group][7]["french"])
        self.assertIn("whom to contact", self.hints[row.group][7]["english"])
        self.assertNotIn("agence", " ".join(q.question for q in row.questions))
        self.assertIn("illustrative, not verified local facts", row.note)

    def test_breakdown_covers_assistance_costs_and_late_arrival_followup(self):
        row = self.by_group["canada-car-breakdown-insurer"]
        self.assertIn("sur le bord de la route, devant la gare d'Ottawa", row.opening)
        self.assertEqual(row.questions[0].question, "Pouvez-vous envoyer un dépanneur sur place ?")
        self.assertIn("voir si la voiture peut repartir", row.questions[0].answer)
        self.assertIn("numéro de contrat", row.questions[0].answer)
        self.assertIn("un numéro où vous joindre", row.questions[0].answer)
        self.assertIn("délai", row.questions[1].question)
        self.assertIn("Si la voiture ne peut pas repartir", row.questions[2].question)
        self.assertIn("garage à proximité", row.questions[2].question)
        self.assertIn("dépannage, le remorquage, les réparations au garage", row.questions[3].question)
        self.assertIn("limite de 200", row.questions[3].answer)
        self.assertIn("réparations au garage ne sont pas couvertes", row.questions[3].answer)
        self.assertIn("devis du garage avant d'autoriser", row.questions[4].question)
        self.assertIn("l'accepter ou le refuser avant le début des travaux", row.questions[4].answer)
        self.assertIn("Si la voiture doit rester au garage", row.questions[5].question)
        self.assertIn("avant d'engager la dépense", row.questions[5].answer)
        self.assertIn("Si les réparations prennent plusieurs jours", row.questions[6].question)
        self.assertIn("mon contrat prévoit-il une voiture de remplacement", row.questions[6].question)
        self.assertIn("ne comprend pas de voiture de remplacement", row.questions[6].answer)
        self.assertIn("trouver une location", row.questions[6].answer)
        self.assertIn("à votre charge", row.questions[6].answer)
        self.assertEqual(row.questions[6].follow_up_to, 6)
        self.assertEqual(row.questions[6].topic, row.questions[5].topic)
        self.assertIn("help getting home", row.questions[6].condition)
        self.assertIn("replacement-vehicle cover", row.questions[6].condition)
        self.assertEqual(
            row.questions[7].question,
            "Si le dépanneur n'arrive pas dans le délai prévu, qui dois-je appeler ?",
        )
        self.assertIn("Rappelez-nous à ce numéro", row.questions[7].answer)
        self.assertIn("numéro de dossier", row.questions[7].answer)
        self.assertIn("contacterons le dépanneur", row.questions[7].answer)
        self.assertIn("immediate safety", row.note.casefold())
        self.assertIn("remorquage et des réparations", self.hints[row.group][3]["french"])
        self.assertIn("estimate before authorizing repairs", self.hints[row.group][4]["english"])
        self.assertIn("Aide au retour", self.hints[row.group][5]["french"])
        self.assertIn("Help getting home", self.hints[row.group][5]["english"])
        self.assertIn("Voiture de remplacement", self.hints[row.group][6]["french"])
        self.assertIn("Replacement car if repairs take several days", self.hints[row.group][6]["english"])
        self.assertIn("dépanneur est en retard", self.hints[row.group][7]["french"])
        self.assertIn("Who to call", self.hints[row.group][7]["english"])

    def test_private_car_has_history_and_proof_rather_than_a_scripted_tyre_only_route(self):
        row = self.by_group["private-owner-used-car-purchase"]
        self.assertIn("De quel modèle s'agit-il", row.questions[0].question)
        for index, text in ((2, "consomme"), (4, "accident"), (5, "factures"), (7, "contrôle indépendant")):
            self.assertIn(text, row.questions[index].question)
        self.assertIn("pneus ou les freins", row.questions[3].question)
        self.assertEqual(row.questions[5].follow_up_to, 4)
        self.assertIn("accrochage", row.questions[4].answer)
        self.assertIn("garantie transférable", row.questions[5].question)
        self.assertIn("garantie du constructeur est terminée", row.questions[5].answer)
        self.assertIn("pas pris d'extension", row.questions[5].answer)
        self.assertIn("transferable warranty", row.questions[5].condition)
        self.assertIn("garantie transférable", self.hints[row.group][5]["french"])
        self.assertIn("transferable warranty", self.hints[row.group][5]["english"])
        self.assertIn("contrôle indépendant", row.questions[7].answer)

    def test_rentals_cover_actual_extra_costs_and_returns_without_forcing_an_electric_bike(self):
        car = self.by_group["holiday-car-rental-agency"]
        self.assertIn("supplément", car.questions[2].question)
        self.assertIn("0,25 $", car.questions[2].answer)
        self.assertEqual(
            car.questions[4].question,
            "En cas de dégâts, est-ce que l'assurance paie tout ou est-ce que je dois payer une partie ?",
        )
        self.assertIn("franchise", car.questions[4].answer)
        self.assertIn("jusqu'à 1 000 $", car.questions[4].answer)
        self.assertIn("L'assurance paie le reste", car.questions[4].answer)
        self.assertEqual(car.questions[4].follow_up_to, 4)
        self.assertIn("malgré l'assurance", self.hints[car.group][4]["french"])
        self.assertIn("still pay", self.hints[car.group][4]["english"])
        self.assertIn("dépôt de garantie", car.questions[6].question)
        self.assertIn("carburant", car.questions[7].answer)
        bike = self.by_group["bicycle-rental-model-and-terms"]
        self.assertIn("types de vélos", bike.questions[0].question)
        self.assertIn("vélos tout-terrain", bike.questions[0].question)
        self.assertIn("vélos électriques", bike.questions[0].question)
        self.assertIn("quel modèle me conseillez-vous, et pourquoi", bike.questions[1].question)
        self.assertEqual(bike.questions[1].follow_up_to, 1)
        self.assertIn("je vous conseille le vélo de ville", bike.questions[1].answer)
        self.assertIn("à l'heure, à la journée ou autrement", bike.questions[2].question)
        for item in ("casque", "antivol", "sonnette", "lumières"):
            self.assertIn(item, bike.questions[3].question)
            self.assertIn(item, bike.questions[3].answer)
        self.assertEqual(bike.questions[3].follow_up_to, 3)
        self.assertIn("Quels documents dois-je apporter", bike.questions[4].question)
        self.assertIn("moyens de paiement acceptez-vous", bike.questions[4].question)
        self.assertIn("pièce d'identité", bike.questions[4].answer)
        self.assertIn("carte de crédit à votre nom", bike.questions[4].answer)
        self.assertIn("carte ou en espèces", bike.questions[4].answer)
        self.assertIn("150 $ de garantie", bike.questions[4].answer)
        self.assertIn("assurance contre le vol ou les dégâts", bike.questions[5].question)
        self.assertIn("5 $ par jour", bike.questions[5].answer)
        self.assertIn("si le vélo était attaché", bike.questions[5].answer)
        self.assertIn("jusqu'à 100 $ de franchise", bike.questions[5].answer)
        self.assertIn("retard", bike.questions[6].question)
        self.assertIn("à l'heure, respectez l'heure convenue", bike.questions[6].answer)
        self.assertIn("vous pouvez venir m'aider", bike.questions[7].question)
        self.assertIn("indiquez où vous êtes", bike.questions[7].answer)
        self.assertIn("panne ou une crevaison", bike.questions[7].answer)
        self.assertIn("10 km", bike.questions[7].answer)
        self.assertIn("réparer ou échanger", bike.questions[7].answer)
        self.assertNotIn("autonomie", " ".join(q.question for q in bike.questions))
        self.assertIn("battery range if you choose", self.raw[bike.group]["note"])
        self.assertIn("illustrative provider terms", self.raw[bike.group]["note"])
        for index, french, english in (
            (0, "tout-terrain", "mountain"),
            (1, "raisons du choix", "reasons for the choice"),
            (2, "autre formule", "other rental periods"),
            (3, "sonnette et lumières", "a bell and lights"),
            (4, "paiement acceptés", "accepted payment methods"),
            (5, "Assurance", "insurance"),
            (7, "Assistance sur place", "On-site assistance"),
        ):
            with self.subTest(cue=index + 1):
                self.assertIn(french, self.hints[bike.group][index]["french"])
                self.assertIn(english, self.hints[bike.group][index]["english"])
        variant = self.dialogues["tache2:decembre:batch-04:subject-16"]
        self.assertIn("purpose of the rental is not specified", variant.note)
        self.assertIn("insurance, return and assistance", variant.note)
        self.assertIn("illustrative", variant.note)

    def test_cycling_distinguishes_condition_road_sections_and_actual_battery_range(self):
        city = self.by_group["ottawa-newcomer-cycling-friend"]
        self.assertIn("grands axes", city.questions[1].question)
        self.assertIn("bien entretenues", city.questions[2].question)
        self.assertIn("rouler sur la route avec les voitures", city.questions[2].question)
        self.assertEqual(city.questions[2].follow_up_to, 2)
        self.assertIn("certains raccordements", city.questions[2].answer)
        self.assertEqual(
            city.questions[5].question,
            "Pour faire du vélo en ville, quel équipement me conseilles-tu, par exemple un casque ou un bon antivol ?",
        )
        self.assertIn("casque", city.questions[5].answer)
        self.assertIn("éclairage", city.questions[5].answer)
        self.assertIn("antivol", city.questions[5].answer)
        self.assertIn("route avec les voitures", self.hints[city.group][2]["french"])
        self.assertIn("shared with cars", self.hints[city.group][2]["english"])
        self.assertIn("vélo en ville", self.hints[city.group][5]["french"])
        self.assertIn("casque, bon antivol", self.hints[city.group][5]["french"])
        self.assertIn("cycling in the city", self.hints[city.group][5]["english"])
        self.assertIn("helmet, good bike lock", self.hints[city.group][5]["english"])
        self.assertEqual(
            city.questions[7].question,
            "Est-ce qu'il y a des supports à vélo dans le centre-ville pour stationner mon vélo en sécurité ?",
        )
        self.assertIn("supports", city.questions[7].answer)
        self.assertIn("Supports à vélo", self.hints[city.group][7]["french"])
        self.assertIn("Bike racks", self.hints[city.group][7]["english"])
        sale = self.by_group["friend-used-electric-bicycle-sale"]
        self.assertEqual(
            sale.questions[2].question,
            "Quel est son kilométrage, et quelle distance peut-on parcourir avec une charge complète ?",
        )
        self.assertEqual(sum("charge complète" in q.question for q in sale.questions), 1)
        for text in ("2 500 km", "60 km", "terrain plat", "assistance modérée", "70 km"):
            self.assertIn(text, sale.questions[2].answer)
        self.assertIn("facture d'achat et les factures d'entretien", sale.questions[4].question)
        self.assertIn("révision du printemps", sale.questions[4].answer)
        self.assertEqual(sale.questions[4].follow_up_to, 4)
        self.assertIn("Kilométrage et autonomie", self.hints[sale.group][2]["french"])
        self.assertIn("Mileage and current range", self.hints[sale.group][2]["english"])
        self.assertIn("factures d'entretien", self.hints[sale.group][4]["french"])
        self.assertIn("Purchase and maintenance invoices", self.hints[sale.group][4]["english"])
        self.assertNotIn("samedi", sale.closing)

    def test_carpools_distinguish_platform_booking_from_a_neighbourly_trial(self):
        friend = self.by_group["friend-carpooling-offer"]
        self.assertIn("d'Ottawa à Montréal", friend.opening)
        self.assertIn("prochain trajet vers Montréal", friend.questions[0].question)
        self.assertIn("samedi", friend.questions[0].answer.casefold())
        self.assertIn("8 h", friend.questions[0].answer)
        self.assertIn("Combien de temps", friend.questions[1].question)
        self.assertIn("où arrive-t-on", friend.questions[1].question)
        self.assertIn("gare Centrale de Montréal", friend.questions[1].answer)
        self.assertEqual(friend.questions[1].follow_up_to, 1)
        self.assertIn("places", friend.questions[2].question)
        self.assertIn("rendez-vous", friend.questions[3].question)
        self.assertIn("gare d'Ottawa", friend.questions[3].answer)
        self.assertIn("30 $", friend.questions[4].answer)
        self.assertIn("2 $ de frais de réservation", friend.questions[4].answer)
        self.assertIn("sac de voyage", friend.questions[5].question)
        self.assertIn("payer", friend.questions[6].question)
        self.assertIn("payer les 30 $ sur la plateforme", friend.questions[6].answer)
        self.assertIn("annuler", friend.questions[7].question)
        self.assertIn("vendredi à 18 h", friend.questions[7].answer)
        self.assertIn("récupérer 28 $", friend.questions[7].answer)
        self.assertIn("2 $ de réservation restent dus", friend.questions[7].answer)
        self.assertEqual(friend.questions[7].follow_up_to, 7)
        self.assertIn("prompt does not fix a route or driver role", friend.note)
        self.assertIn("illustrative, not universal rules", friend.note)
        self.assertIn("regarder l'annonce", friend.closing)
        self.assertIn("Prochain départ", self.hints[friend.group][0]["french"])
        self.assertIn("drop-off in Montréal", self.hints[friend.group][1]["english"])
        self.assertIn("travel bag", self.hints[friend.group][5]["english"])
        neighbour = self.by_group["neighbor-regular-carpool-invitation"]
        self.assertIn("entre Gatineau et le centre-ville d'Ottawa", neighbour.opening)
        self.assertEqual(neighbour.questions[0].question, "Quels jours de la semaine faites-vous ce trajet ?")
        self.assertIn("lundi au jeudi", neighbour.questions[0].answer)
        self.assertIn("retrouverions-nous", neighbour.questions[2].question)
        self.assertIn("devant chez vous", neighbour.questions[2].answer)
        self.assertIn("centre Rideau", neighbour.questions[2].answer)
        self.assertIn("partager les frais", neighbour.questions[4].question)
        self.assertIn("5 $ par aller-retour", neighbour.questions[4].answer)
        self.assertIn("trajets que nous avons faits ensemble", neighbour.questions[5].answer)
        self.assertIn("si je ne conduis pas", neighbour.questions[6].answer)
        self.assertIn("Si vous ne venez pas, je pars", neighbour.questions[6].answer)
        self.assertIn("essayer", neighbour.questions[7].question)
        self.assertIn("practice choices, not prompt facts", neighbour.note)
        self.assertIn("Gatineau-Ottawa", self.hints[neighbour.group][0]["french"])

    def test_montreal_plan_checks_work_route_calendar_validity_zones_and_late_returns(self):
        row = self.by_group["colleague-montreal-work-week-transit"]
        self.assertIn("hôtel est près du métro Berri-UQAM", row.opening)
        self.assertIn("réunions près de la station McGill", row.opening)
        self.assertIn("de mon hôtel au lieu de mes réunions", row.questions[0].question)
        self.assertIn("ligne verte à Berri-UQAM", row.questions[0].answer)
        self.assertIn("direction d'Angrignon", row.questions[0].answer)
        self.assertIn("descendez à McGill", row.questions[0].answer)
        self.assertIn("sans correspondance", row.questions[0].answer)
        self.assertIn("fréquence", row.questions[1].question)
        self.assertIn("deux à quatre minutes", row.questions[1].answer)
        self.assertTrue(row.questions[3].question.startswith("Si j'arrive"))
        self.assertIn("jusqu'au mardi suivant", row.questions[3].question)
        self.assertEqual(row.questions[3].follow_up_to, 3)
        self.assertIn("33,25 $", row.questions[2].answer)
        self.assertIn("hors carte OPUS", row.questions[2].answer)
        self.assertIn("lundi au dimanche", row.questions[2].answer)
        self.assertIn("non sept jours à partir de l'achat", row.questions[2].answer)
        self.assertNotIn("juillet 2026", row.questions[2].answer)
        self.assertIn("dimanche à 23 h 59", row.questions[3].answer)
        self.assertIn("semaine suivante", row.questions[3].answer)
        service = self.by_group["newcomer-city-transit-service"]
        self.assertEqual(
            row.questions[4].question,
            "Ce titre comprend-il les correspondances, et dans quelles zones est-il valable ?",
        )
        self.assertEqual(row.questions[4].follow_up_to, 3)
        self.assertIn("zone A", row.questions[4].answer)
        self.assertIn("Laval ou Longueuil en métro", row.questions[4].answer)
        self.assertIn("titre AB", row.questions[4].answer)
        self.assertEqual(row.questions[5].question, service.questions[4].question)
        self.assertIn("carte OPUS au guichet du métro", row.questions[5].answer)
        self.assertIn("lecteur", row.questions[5].answer)
        self.assertIn("portillon", row.questions[5].answer)
        self.assertIn("de McGill à Berri-UQAM", row.questions[6].question)
        self.assertIn("vers Honoré-Beaugrand", row.questions[6].answer)
        self.assertIn("0 h 50 en semaine", row.questions[6].answer)
        self.assertIn("1 h 21 le samedi", row.questions[6].answer)
        self.assertIn("vérifiez l'horaire", row.questions[6].answer)
        self.assertIn("comment pourrais-je rentrer à mon hôtel", row.questions[7].question)
        self.assertEqual(row.questions[7].follow_up_to, 7)
        self.assertIn("bus de nuit", row.questions[7].answer)
        self.assertIn("practice choices; adapt them", row.note)
        self.assertIn("fares and station times need reconfirming", row.note)
        self.assertIn("https://www.stm.info/en/fares-pricing/weekly-pass", row.note)
        self.assertIn("https://www.stm.info/en/schedules-and-routes/metro-McGill", row.note)
        self.assertIn("Berri-UQAM à McGill", self.hints[row.group][0]["french"])
        self.assertIn("Weekly-pass validity", self.hints[row.group][3]["english"])
        self.assertIn("limites de la zone A", self.hints[row.group][4]["french"])
        self.assertIn("OPUS", self.hints[row.group][5]["english"])
        self.assertIn("Last métro from McGill to Berri-UQAM", self.hints[row.group][6]["english"])

    def test_host_friend_variant_keeps_accommodation_and_short_visit_context(self):
        row = self.dialogues["tache2:decembre:batch-04:subject-17"]
        self.assertIn("accommodation is already arranged", row.note)
        self.assertIn("Use tu", row.note)
        self.assertIn("rather than assuming a monthly subscription", row.note)
        self.assertEqual(row.register, "tu")
        neighbour = self.by_group[row.group]
        service = self.by_group["newcomer-city-transit-service"]
        self.assertEqual(neighbour.questions[0].question, service.questions[0].question)
        self.assertIn("À part les billets à l'unité", neighbour.questions[3].question)
        self.assertIn("pass journée ou des abonnements", neighbour.questions[3].question)
        self.assertIn("trois trajets payants", neighbour.questions[3].answer)
        self.assertIn("sur un mois", neighbour.questions[3].answer)
        self.assertEqual(neighbour.questions[3].follow_up_to, 3)
        self.assertEqual(
            neighbour.questions[4].question,
            "Ces formules comprennent-elles les correspondances, et dans quelles zones sont-elles valables ?",
        )
        self.assertIn("zones éloignées", neighbour.questions[4].answer)
        self.assertEqual(neighbour.questions[4].follow_up_to, 4)
        self.assertIn("billets ou un abonnement", neighbour.questions[5].question)
        self.assertIn("carte rechargeable au guichet", neighbour.questions[5].answer)
        self.assertIn("fais-y charger l'abonnement", neighbour.questions[5].answer)
        self.assertIn("Pour les billets ou le pass journée", neighbour.questions[5].answer)
        self.assertEqual(neighbour.questions[5].follow_up_to, 4)
        self.assertEqual(neighbour.questions[6].question, "Comment valide-t-on un titre de transport ?")
        self.assertIn("jusqu'à quelle heure peut-on rentrer", neighbour.questions[7].question)
        self.assertIn("Included transfers", self.hints[row.group][4]["english"])
        self.assertIn("carte rechargeable", self.hints[row.group][5]["french"])

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
