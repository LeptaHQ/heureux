from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
import json

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from study import catalogue, content_loader as content
from study.models import Annotation, AnnotationKind, PersonalResponse
from study.oral_highlights import (
    QuestionText, _project_location_annotation, _render_questions,
)
from study.oral_history import variant_annotation_key
from study.response_personalization import effective_response
from study.routing import prompt_detail_url
from study.tache_two_dialogues import dialogue_response
from study.tache_two_location_history import LOCATION_HISTORY_PATH, load_location_history

from . import factories


class TacheTwoLocationCorpusTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def test_original_arrival_models_are_unchanged_after_social_integration_reclassification(self):
        _, mapping = catalogue.tache_two_subject_themes()
        protected = {
            row.group for key, row in catalogue.tache_two_dialogues().items()
            if mapping[key] == "arrivee"
            and row.group != "newcomer-local-acquaintance-meet-people"
        }
        rows = [
            row for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
            if row["group"] in protected
        ]
        snapshot = json.dumps(
            sorted(rows, key=lambda row: row["group"]), ensure_ascii=False, sort_keys=True,
        ).encode()
        self.assertEqual(len(rows), 6)
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "b3f62225759c57d763f3af704a1a1756d7d83700d5b9c061b8b5b2de52304802",
        )

    def test_social_integration_and_all_equivalent_consignes_belong_to_arrival(self):
        _, mapping = catalogue.tache_two_subject_themes()
        dialogues = catalogue.tache_two_dialogues()
        keys = {
            key for key, row in dialogues.items()
            if row.group == "newcomer-local-acquaintance-meet-people"
        }
        self.assertEqual(keys, {
            "tache2:fevrier:batch-05:subject-24",
            "tache2:mars:batch-03:subject-14",
            "tache2:septembre:batch-03:subject-14",
            "tache2:octobre:batch-02:subject-09",
        })
        subjects = {
            content.tache_two_subject_content_key(month.slug, batch.number, subject.number): subject
            for month in catalogue.tache_two_subject_months()
            for batch in month.batches
            for subject in batch.subjects
        }
        for key in keys:
            with self.subTest(content_key=key):
                self.assertEqual(mapping[key], "arrivee")
                self.assertEqual(
                    [question.memory_number for question in subjects[key].questions], [1] * 15,
                )
        arrival = [row for key, row in dialogues.items() if mapping[key] == "arrivee"]
        self.assertEqual(len(arrival), 17)
        self.assertEqual(len({row.group for row in arrival}), 7)

    def test_all_new_resident_neighbourhood_equivalents_belong_to_arrival(self):
        _, mapping = catalogue.tache_two_subject_themes()
        keys = {
            key for key, row in catalogue.tache_two_dialogues().items()
            if row.group == "new-resident-neighbor-neighborhood-orientation"
        }
        self.assertEqual(keys, {
            "tache2:fevrier:batch-04:subject-20",
            "tache2:avril:batch-01:subject-03",
            "tache2:mai:batch-01:subject-05",
            "tache2:juin:batch-09:subject-43",
            "tache2:juillet:batch-01:subject-05",
            "tache2:juillet:batch-03:subject-15",
            "tache2:octobre:batch-10:subject-50",
            "tache2:decembre:batch-03:subject-13",
        })
        subjects = {
            content.tache_two_subject_content_key(month.slug, batch.number, subject.number): subject
            for month in catalogue.tache_two_subject_months()
            for batch in month.batches
            for subject in batch.subjects
        }
        for key in keys:
            with self.subTest(content_key=key):
                self.assertEqual(mapping[key], "arrivee")
                self.assertEqual(
                    [question.memory_number for question in subjects[key].questions], [1] * 15,
                )

    def test_arrival_history_contains_only_the_reclassified_social_integration_model(self):
        history = catalogue.tache_two_location_history()
        _, mapping = catalogue.tache_two_subject_themes()
        dialogues = catalogue.tache_two_dialogues()
        archived_arrival_groups = {
            current.group for key, current in dialogues.items()
            if mapping[key] == "arrivee" and current.group in history
        }
        self.assertEqual(
            archived_arrival_groups, {"newcomer-local-acquaintance-meet-people"},
        )

    def test_recorded_substitutions_reconstruct_current_or_archived_geographic_models(self):
        by_group = {item.group: item for item in catalogue.tache_two_dialogues().values()}
        for group, history in catalogue.tache_two_location_history().items():
            if not history.replacements:
                continue
            previous = history.revisions[0]
            old_fields = [
                previous.opening, *(row.question for row in previous.questions), previous.closing,
            ]
            translated = []
            for old in old_fields:
                for before, after in history.replacements:
                    old = old.replace(before, after)
                translated.append(old)
            matches = [
                row for row in (*history.revisions[1:], by_group[group])
                if [row.opening, *(question.question for question in row.questions), row.closing]
                == translated
            ]
            self.assertTrue(matches, group)
            for geographic in matches:
                self.assertEqual(
                    [row.topic for row in previous.questions],
                    [row.topic for row in geographic.questions], group,
                )
                self.assertEqual(
                    [row.follow_up_to for row in previous.questions],
                    [row.follow_up_to for row in geographic.questions], group,
                )

    def test_remaining_housing_models_keep_distinct_roles_and_practical_priority(self):
        by_group = {row.group: row for row in catalogue.tache_two_dialogues().values()}
        transport = by_group["help-transport-heavy-objects-no-vehicle"]
        self.assertIn("Quel jour et à quelle heure", transport.questions[0].question)
        self.assertIn("les plus encombrants ou les plus lourds", transport.questions[1].question)
        self.assertIn("peut-on retirer les pieds", transport.questions[2].question)
        self.assertEqual(transport.questions[2].follow_up_to, 2)
        self.assertIn("où doit-on déposer les objets", transport.questions[3].question)
        self.assertIn("stationner près des entrées", transport.questions[4].question)
        self.assertIn("budget", transport.questions[5].question)
        self.assertIn("chariot adapté aux escaliers", transport.questions[5].answer)
        self.assertNotIn("se démonte-t-il", transport.questions[2].question)
        self.assertIn("not necessarily move house", transport.note)
        apartment = by_group["estate-agent-advertised-apartment-unspecified"]
        self.assertEqual(
            apartment.questions[0].question,
            "Cet appartement est-il proposé à la vente ou à la location ?",
        )
        self.assertEqual(
            apartment.questions[1].question, "Quel est le prix demandé pour cet appartement ?",
        )
        self.assertIn("monthly rent and included charges", apartment.note)
        self.assertIn("mensuels", apartment.questions[6].question)
        self.assertIn("taxes foncières annuelles", apartment.questions[6].question)
        summer = by_group["colleague-summer-house-rental"]
        previous = catalogue.tache_two_location_history()[summer.group].revisions[-1]
        order = (6, 7, 8, 1, 2, 3, 4, 5)
        self.assertEqual(
            [row.question for row in summer.questions],
            [previous.questions[index - 1].question for index in order],
        )
        self.assertEqual(summer.questions[2].follow_up_to, 2)
        self.assertEqual(summer.questions[4].follow_up_to, 4)
        self.assertIsNone(summer.questions[7].follow_up_to)
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"]
        self.assertEqual(hints[transport.group][0]["english"], "Transport date and time")
        self.assertEqual(hints[transport.group][2]["english"], "Sofa dimensions and removable legs")
        self.assertEqual(
            hints[apartment.group][6]["english"],
            "Monthly condominium fees and annual property taxes",
        )
        self.assertEqual(hints[summer.group][0]["english"], "Available dates and minimum stay")
        self.assertEqual(
            hints[summer.group][7]["english"], "Park and shops on foot, downtown without a car",
        )
        for row in (transport, apartment, summer):
            old = catalogue.tache_two_location_history()[row.group].revisions[-1]
            self.assertEqual(row.opening, old.opening)
            self.assertEqual(row.closing, old.closing)

    def test_neighbourhood_coverage_excludes_the_reclassified_arrival_models(self):
        from study.tests.neighbourhood_fixtures import ALL_NEIGHBOURHOOD_GROUPS

        _, themes = catalogue.tache_two_subject_themes()
        publications = {
            key: row for key, row in catalogue.tache_two_dialogues().items()
            if row.group in ALL_NEIGHBOURHOOD_GROUPS
        }
        self.assertEqual(len(publications), 36)
        self.assertEqual(len({row.group for row in publications.values()}), 18)
        shared = [
            row for row in publications.values()
            if row.group == "new-resident-neighbor-neighborhood-orientation"
        ]
        self.assertEqual(shared, [])

    def test_neighbourhood_childcare_preserves_the_distinct_roles_and_known_facts(self):
        by_group = {row.group: row for row in catalogue.tache_two_dialogues().values()}
        referral = by_group["colleague-babysitter-referral-needs"]
        self.assertIn("neither applying nor interviewing", referral.note)
        self.assertIn("pour quelle durée", referral.questions[1].question)
        self.assertIn("Dans quel quartier", referral.questions[2].question)
        self.assertIn("sortie de l'école", referral.questions[3].question)
        self.assertEqual(referral.questions[4].follow_up_to, 4)
        self.assertIn("not been explained", referral.questions[4].condition)
        self.assertIn("aucun aliment interdit ni soin particulier", referral.questions[4].answer)
        self.assertIn("premiers secours", referral.questions[5].question)
        self.assertTrue(referral.questions[6].question.startswith("Quelle rémunération"))
        self.assertIn("comment et quand", referral.questions[6].question)
        self.assertIn("après chaque garde", referral.questions[6].answer)
        provider = by_group["neighbor-home-childcare-provider-referral"]
        self.assertIn("referrer rather than the provider", provider.note)
        self.assertIn("chez les parents ou chez elle", provider.questions[3].question)
        self.assertIn("quels jours et à quels horaires", provider.questions[4].question)
        self.assertIn("vérifier ses disponibilités actuelles avec elle", provider.questions[4].answer)
        self.assertIn("avec son accord", provider.questions[7].answer)
        day = by_group["neighbor-child-one-day-care"]
        self.assertEqual(
            day.questions[0].question,
            "Où se passera la garde, et de quelle heure à quelle heure ?",
        )
        self.assertIn("Quel âge a votre enfant", day.questions[1].question)
        self.assertIn("allergies ou des besoins de santé particuliers", day.questions[1].question)
        self.assertIn("s'entend-il bien avec les autres enfants", day.questions[2].question)
        self.assertIn("Age, gender and medical needs are unspecified", day.note)
        self.assertIn("mon enfant", day.questions[0].answer)
        self.assertIn("mon enfant", day.questions[6].answer)
        self.assertNotIn("votre enfant", day.questions[6].answer)
        self.assertEqual(day.questions[6].follow_up_to, 6)
        self.assertIn("consignes", day.questions[6].question)
        weekend = by_group["friend-three-year-old-weekend-care"]
        self.assertIn("already supplies timings", weekend.note)
        self.assertIn("allergies", weekend.questions[1].question)
        self.assertIn("dessin, les puzzles ou les histoires", weekend.questions[2].question)
        self.assertIn("précautions", weekend.questions[3].question)
        holiday = by_group["child-friends-family-holiday-invitation"]
        self.assertIn("authorizing care, not providing it", holiday.note)
        self.assertIn("équipements de sécurité", holiday.questions[3].question)
        self.assertIn("adaptés à l'âge", holiday.questions[3].answer)
        self.assertIn("joignable pendant tout le séjour", holiday.questions[7].question)
        self.assertIn("avoir des nouvelles", holiday.questions[7].question)

    def test_pet_care_distinguishes_feeding_goals_without_merging_paid_and_unpaid_roles(self):
        by_group = {row.group: row for row in catalogue.tache_two_dialogues().values()}
        paid = by_group["neighbor-dog-care-week-paid"]
        favour = by_group["trusted-person-temporary-pet-care"]
        self.assertEqual(paid.register, "vous")
        self.assertEqual(favour.register, "tu")
        self.assertIn("seeks paid care", paid.note)
        self.assertIn("No payment is stated", favour.note)
        self.assertEqual(
            favour.questions[0].question, "Quel animal vas-tu me confier, et quel âge a-t-il ?",
        )
        self.assertIn("Fournirez-vous sa nourriture ou devrai-je m'en occuper", paid.questions[2].question)
        self.assertIn("à quelles heures", paid.questions[2].question)
        self.assertIn("Côté alimentation", favour.questions[3].question)
        self.assertIn("me laisseras-tu sa nourriture ou devrai-je l'acheter", favour.questions[3].question)
        self.assertIn("À quelle fréquence", paid.questions[3].question)
        self.assertIn("pour chaque sortie", paid.questions[3].question)
        self.assertNotIn("laisse", paid.questions[3].answer)
        self.assertIn("laisse", paid.questions[4].answer)
        self.assertIsNone(favour.questions[4].follow_up_to)
        self.assertEqual(favour.questions[5].follow_up_to, 5)
        self.assertIn("adapt to the animal named", favour.questions[5].condition)
        self.assertFalse(any("rémunération" in row.question for row in favour.questions))

    def test_volunteer_relances_distinguish_mentoring_from_tasks_and_training(self):
        by_group = {row.group: row for row in catalogue.tache_two_dialogues().values()}
        meal = by_group["friend-homeless-meal-volunteering"]
        self.assertEqual(meal.questions[6].follow_up_to, 5)
        self.assertIn("bénévole expérimenté", meal.questions[6].question)
        self.assertNotEqual(meal.questions[6].question, meal.questions[4].question)
        self.assertIn("support", meal.questions[6].condition)
        office = by_group["volunteer-local-association-information-office"]
        self.assertIn("formation", office.questions[5].question)
        self.assertIn("renseignements", office.questions[6].question)
        self.assertIn("observer un atelier", office.questions[7].question)
        self.assertIn("sur rendez-vous", office.questions[7].answer)
        self.assertIn("l'association confirmera le créneau", office.questions[7].answer)
        self.assertIsNone(office.questions[7].follow_up_to)
        self.assertEqual(office.questions[1].follow_up_to, 1)
        environment = by_group["neighbor-environmental-association-volunteering"]
        self.assertIn("à quels horaires", environment.questions[2].question)
        self.assertIn("explications et un accompagnement", environment.questions[5].question)
        self.assertIn("bénévole expérimenté", environment.questions[5].answer)
        self.assertIn("contacter pour une première participation", environment.questions[6].question)
        self.assertIn("où faut-il se présenter", environment.questions[7].question)

    def test_neighbourhood_delivery_questions_cover_actual_service_constraints(self):
        by_group = {row.group: row for row in catalogue.tache_two_dialogues().values()}
        grocery = by_group["grocery-store-home-delivery"]
        self.assertIn("mon adresse est desservie", grocery.questions[0].question)
        self.assertIn("selon le montant des achats", grocery.questions[2].question)
        self.assertIn("gratuite à partir de 100 $", grocery.questions[2].answer)
        self.assertIn("commande passée avant midi", grocery.questions[3].answer)
        self.assertIn("après midi", grocery.questions[3].answer)
        self.assertEqual(grocery.questions[4].follow_up_to, 4)
        parcel = by_group["help-friend-post-parcel"]
        self.assertIn("jusqu'à quel montant", parcel.questions[3].question)
        self.assertIn("40 $", parcel.questions[3].answer)
        self.assertIn("emballé, étiqueté et affranchi", parcel.questions[6].question)
        self.assertIn("l'argent avant le dépôt", parcel.questions[6].question)
        self.assertIn("mais pas affranchi", parcel.questions[6].answer)
        watch = by_group["friend-holiday-apartment-watch"]
        self.assertIn("récupérer des colis", watch.questions[1].question)
        self.assertIn("code d'accès", watch.questions[4].question)
        self.assertIn("chauffage", watch.questions[5].answer)
        nephews = by_group["friend-entertain-visiting-nephews"]
        self.assertIn("différents âges", nephews.questions[3].question)
        self.assertIn("quel budget", nephews.questions[5].question)
        self.assertIn("parties courtes", nephews.questions[6].question)
        visit = by_group["visit-colleague-minor-accident"]
        self.assertIn("les courses, les repas ou vos déplacements", visit.questions[1].question)
        self.assertIn("je me repose à la maison", visit.questions[0].answer)

    def test_neighbourhood_pistes_follow_reordered_and_extended_questions(self):
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"]
        expected = {
            "colleague-babysitter-referral-needs": (
                "Number and ages of the children",
                "Days, hours, start date and duration of childcare",
                "Neighbourhood and care at the colleague's or caregiver's home",
                "School pickup, homework or meal preparation",
                "Allergies, foods to avoid and care needs to tell the recommended person",
                "Experience, training and first aid",
                "Proposed pay, payment method and timing",
                "Initial meeting with the children before confirming childcare",
            ),
            "grocery-store-home-delivery": (
                "Delivery area and checking coverage for your address",
                "Paying for groceries and delivery: checkout or driver, card or cash",
                "Delivery fees by basket value and minimum spend for free delivery",
                "Time from order to delivery",
                "Choosing a delivery window and its duration", "Transport of fresh and frozen groceries",
                "Missed delivery and any redelivery fee",
                "Reporting and getting a refund for a missing or damaged item",
            ),
            "neighbor-child-one-day-care": (
                "Childcare location and hours", "Child's age, allergies and special health needs",
                "Behaviour around unfamiliar people and getting along with other children",
                "Provided meal and snack or food to arrange, and eating times",
                "Nap or quiet time, timing and habits that help the child rest",
                "Favourite activities: drawing, building games or the park",
                "Permission and safety instructions for a park outing",
                "Parent's availability throughout care and contact if a problem arises",
            ),
        }
        for group, english in expected.items():
            with self.subTest(group=group):
                self.assertEqual(tuple(row["english"] for row in hints[group]), english)
        self.assertNotIn("return", hints["friend-holiday-apartment-watch"][2]["english"])
        self.assertNotIn("authorization", hints["trusted-person-temporary-pet-care"][7]["english"])
        self.assertEqual(
            hints["host-foreign-friends-city-advice"][0]["english"],
            "Activity about regional history and culture",
        )
        self.assertEqual(
            hints["neighbor-dog-care-week-paid"][2]["english"],
            "Who provides the food and feeding times",
        )
        self.assertEqual(
            hints["trusted-person-temporary-pet-care"][3]["english"],
            "Food left by the owner or to buy, and feeding times",
        )

    def test_apartment_condition_question_offers_work_or_ready_to_live_in(self):
        current = next(
            row for row in catalogue.tache_two_dialogues().values()
            if row.group == "estate-agent-advertised-apartment-purchase"
        )
        self.assertEqual(
            current.questions[2].question,
            "L'appartement nécessite-t-il des travaux, ou est-il prêt à être habité ?",
        )
        self.assertIn("habitable immédiatement", current.questions[2].answer)
        self.assertEqual(
            current.questions[7].question, "Quand pourrais-je passer voir l'appartement ?",
        )
        self.assertEqual(
            current.questions[5].question,
            "L'appartement dispose-t-il d'un balcon, d'un espace de rangement ou d'une place de stationnement ?",
        )
        self.assertIsNone(current.questions[5].follow_up_to)
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"][current.group]
        self.assertEqual(hints[5]["english"], "Balcony, storage space and parking")

    def test_delivery_price_precedes_access_solutions_and_pistes_follow_question_order(self):
        current = next(
            row for row in catalogue.tache_two_dialogues().values()
            if row.group == "furniture-delivery-service"
        )
        self.assertTrue(current.questions[1].question.startswith("Quel est votre tarif de base"))
        self.assertEqual(
            current.questions[2].question,
            "Si le canapé ne passe pas par l'escalier, quelles solutions proposez-vous ?",
        )
        self.assertEqual(current.questions[3].follow_up_to, 2)
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"][current.group]
        self.assertEqual(hints[1]["english"], "Base rate and distance, floor or access surcharges")
        self.assertEqual(hints[2]["french"], "Solutions si le canapé ne passe pas par l'escalier")
        self.assertNotIn("photos", current.closing)

    def test_quebec_agency_starts_with_offers_fees_then_availability_and_lease_length(self):
        current = next(
            row for row in catalogue.tache_two_dialogues().values()
            if row.group == "quebec-newcomer-estate-agency-housing-procedures"
        )
        self.assertEqual(
            current.questions[0].question,
            "Quels types de logements avez-vous actuellement à louer, et vos services sont-ils payants pour les locataires ?",
        )
        self.assertEqual(
            current.questions[1].question,
            "À partir de quand ces logements sont-ils disponibles, et quelle est la durée minimale du bail ?",
        )
        self.assertEqual(current.questions[1].follow_up_to, 1)
        self.assertIn("payés par le propriétaire", current.questions[0].answer)
        self.assertIn("immédiatement", current.questions[1].answer)
        self.assertIn("d'un an", current.questions[1].answer)
        previous = catalogue.tache_two_location_history()[current.group].revisions[-1]
        self.assertEqual(current.opening, previous.opening)
        self.assertEqual(current.closing, previous.closing)
        for number, (old, new) in enumerate(zip(previous.questions, current.questions), 1):
            if number == 7:
                continue
            self.assertEqual(old.question, new.question)
            self.assertEqual(old.follow_up_to, new.follow_up_to)
            self.assertEqual(old.topic, new.topic)
            self.assertEqual(old.condition, new.condition)
        self.assertEqual(
            current.questions[6].question,
            "Si je n'ai pas de références locatives au Québec, quels justificatifs puis-je fournir à la place, et faut-il un garant ?",
        )
        self.assertEqual(current.questions[6].follow_up_to, 6)
        self.assertIn("ancien propriétaire à l'étranger", current.questions[6].answer)
        self.assertIn("un garant peut être demandé selon", current.questions[6].answer)
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"][current.group]
        self.assertEqual(hints[0]["english"], "Available rental types and agency fees for tenants")
        self.assertEqual(hints[1]["english"], "Availability dates and minimum lease length")
        self.assertEqual(
            hints[6]["french"],
            "Justificatifs sans références locatives au Québec et nécessité d'un garant",
        )
        self.assertEqual(
            hints[6]["english"],
            "Alternative supporting documents without Quebec rental references and need for a guarantor",
        )

    def test_shared_room_combines_costs_and_separates_availability_from_lease_arrangements(self):
        current = next(
            row for row in catalogue.tache_two_dialogues().values()
            if row.group == "offered-room-in-existing-shared-apartment"
        )
        self.assertEqual(len(current.questions), 8)
        self.assertEqual(
            [row.question for row in current.questions[:3]],
            [
                "Combien coûterait la chambre par mois, et quelles charges et dépenses communes seraient comprises dans ce loyer ?",
                "À partir de quand la chambre sera-t-elle libre ?",
                "Signerais-je un bail ou une entente de sous-location, et pour quelle durée minimale ?",
            ],
        )
        self.assertIn("1 300 $ par mois", current.questions[0].answer)
        self.assertIn("chauffage, électricité et Internet compris", current.questions[0].answer)
        self.assertIn("produits ménagers", current.questions[0].answer)
        self.assertEqual(current.questions[1].answer, "Dès le premier du mois prochain.")
        self.assertIn("ajout au bail existant", current.questions[2].answer)
        self.assertIn("six mois", current.questions[2].answer)
        self.assertTrue(all(row.follow_up_to is None for row in current.questions[:3]))
        previous = catalogue.tache_two_location_history()[current.group].revisions[0]
        self.assertEqual(current.opening, previous.opening)
        self.assertEqual(current.closing, previous.closing)
        for old, new in zip(previous.questions[3:], current.questions[3:]):
            self.assertEqual(old.question, new.question)
            self.assertEqual(old.topic, new.topic)
            self.assertEqual(old.follow_up_to, new.follow_up_to)
            self.assertEqual(old.condition, new.condition)
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"][current.group]
        self.assertEqual(
            hints[:3],
            [
                {
                    "french": "Loyer mensuel, charges et dépenses communes comprises",
                    "english": "Monthly rent, included utilities and shared expenses",
                },
                {
                    "french": "Date de disponibilité de la chambre",
                    "english": "Room availability date",
                },
                {
                    "french": "Bail ou entente de sous-location et durée minimale",
                    "english": "Lease or sublet agreement and minimum term",
                },
            ],
        )

    def test_friend_housing_advice_has_two_procedure_questions_and_concrete_extra_costs(self):
        current = next(
            row for row in catalogue.tache_two_dialogues().values()
            if row.group == "friend-city-housing-search-advice"
        )
        previous = catalogue.tache_two_location_history()[current.group].revisions[0]
        self.assertEqual(len(current.questions), 8)
        self.assertEqual(
            [row.topic for row in current.questions],
            ["Quartiers"] * 3 + ["Budget"] * 2 + ["Recherche", "Démarches", "Démarches"],
        )
        self.assertEqual(current.opening, previous.opening)
        self.assertEqual(current.closing, previous.closing)
        for old_number, new_number in ((1, 1), (2, 2), (3, 3), (5, 4), (7, 6)):
            self.assertEqual(
                current.questions[new_number - 1].question,
                previous.questions[old_number - 1].question,
            )
        self.assertEqual(
            current.questions[4].question,
            "En plus du loyer, quels frais dois-je prévoir, par exemple pour le chauffage, Internet ou l'assurance habitation ?",
        )
        self.assertEqual(current.questions[4].follow_up_to, 4)
        self.assertIn("l'assurance habitation", current.questions[4].answer)
        self.assertEqual(
            current.questions[6].question,
            "Quels documents me conseillerais-tu de préparer pour déposer un dossier de location ?",
        )
        self.assertIn("les exigences varient selon le propriétaire", current.questions[6].answer)
        self.assertEqual(
            current.questions[7].question,
            "Si je n'ai pas de références locatives au Canada, quels justificatifs puis-je fournir à la place, et faut-il un garant ?",
        )
        self.assertEqual(current.questions[7].follow_up_to, 7)
        self.assertIn("Certains propriétaires", current.questions[7].answer)
        self.assertIn("d'autres peuvent demander un garant", current.questions[7].answer)
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"][current.group]
        self.assertEqual(hints[4]["english"], "Costs beyond rent: heating, Internet and home insurance")
        self.assertEqual(hints[6]["english"], "Documents to prepare for the rental application")
        self.assertEqual(
            hints[7]["english"], "Alternatives to Canadian rental references and need for a guarantor",
        )

    def test_newcomer_apartment_advice_adds_included_charges_and_guarantor_question(self):
        current = catalogue.tache_two_dialogues()["tache2:octobre:batch-03:subject-15"]
        previous = catalogue.tache_two_location_history()[current.group].revisions[0]
        self.assertEqual(current.opening, previous.opening)
        self.assertEqual(current.closing, previous.closing)
        for number, (old, new) in enumerate(zip(previous.questions, current.questions), 1):
            if number in (4, 7):
                continue
            self.assertEqual(old.question, new.question)
            self.assertEqual(old.topic, new.topic)
            self.assertEqual(old.follow_up_to, new.follow_up_to)
            self.assertEqual(old.condition, new.condition)
        self.assertEqual(
            current.questions[3].question,
            "Quel loyer moyen faut-il prévoir dans ces quartiers, et quelles charges sont comprises ?",
        )
        self.assertIn("1 500 et 1 900 $ par mois", current.questions[3].answer)
        self.assertIn("L'eau et le chauffage peuvent être inclus, selon l'annonce", current.questions[3].answer)
        self.assertEqual(current.questions[3].follow_up_to, 3)
        self.assertIn("rents and included charges", current.questions[3].condition)
        self.assertEqual(
            current.questions[6].question,
            "Sans références locatives canadiennes, comment pourrais-je renforcer mon dossier, et faut-il un garant ?",
        )
        self.assertIn("Une lettre d'employeur peut aider", current.questions[6].answer)
        self.assertIn("un garant n'est pas systématique", current.questions[6].answer)
        self.assertIn("selon le dossier", current.questions[6].answer)
        self.assertEqual(current.questions[6].follow_up_to, 6)
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"][current.group]
        self.assertEqual(
            hints[3],
            {
                "french": "Loyer moyen dans ces quartiers et charges comprises",
                "english": "Average rent in those neighbourhoods and included utilities",
            },
        )
        self.assertEqual(
            hints[6],
            {
                "french": "Renforcer le dossier sans références canadiennes et nécessité d'un garant",
                "english": "Strengthening an application without Canadian rental references and need for a guarantor",
            },
        )

    def test_holiday_letting_uses_concrete_questions_and_separates_management_from_fees(self):
        group = "owner-holiday-letting-estate-agency-advice"
        dialogues = catalogue.tache_two_dialogues()
        current = dialogues["tache2:septembre:batch-04:subject-20"]
        self.assertEqual(current, dialogues["tache2:novembre:batch-03:subject-15"])
        self.assertEqual(current.group, group)
        self.assertEqual(current.register, "vous")
        self.assertEqual(
            [row.topic for row in current.questions],
            ["Locataires et équipement"] * 2
            + ["Durée et tarif"] * 2
            + ["Démarches et protection"] * 2
            + ["Gestion et frais"] * 2,
        )
        self.assertEqual(
            [row.question for row in current.questions],
            [
                "Quel type de locataires me conseilleriez-vous de viser : des touristes, des familles ou des voyageurs d'affaires ?",
                "Pour accueillir ces locataires, quels meubles et équipements devrais-je prévoir, notamment pour la cuisine et les couchages ?",
                "Quelle durée de location vaut-il mieux privilégier : des courts séjours ou des séjours d'une semaine ou plus ?",
                "À quel prix pourrais-je proposer mon logement par nuit ?",
                "Quelles autorisations et quelles assurances dois-je vérifier avant de publier l'annonce ?",
                "Comment se passent l'état des lieux et le dépôt de garantie ?",
                "Qui s'occupe du ménage et de la remise des clés entre deux locations ?",
                "Quelle commission prenez-vous pour la gestion, et quels frais restent à ma charge ?",
            ],
        )
        self.assertNotIn("haute saison", json.dumps(asdict(current), ensure_ascii=False))
        self.assertIn("Ownership is not stated", current.note)
        self.assertIn("location, size and dates", current.note)
        self.assertIn("capacité d'accueil", current.questions[0].answer)
        self.assertEqual(current.questions[1].follow_up_to, 1)
        self.assertIn("without specifying the equipment", current.questions[1].condition)
        self.assertIn("fourchette indicative", current.questions[3].answer)
        self.assertIn("si vous êtes locataire", current.questions[4].answer)
        self.assertIn("lorsqu'un dépôt est autorisé", current.questions[5].answer)
        self.assertIn("à l'arrivée et au départ", current.questions[5].answer)
        self.assertNotIn("facturé", current.questions[6].answer)
        self.assertEqual(current.questions[7].follow_up_to, 7)
        self.assertIn("without explaining its fees", current.questions[7].condition)
        self.assertIn("15 %", current.questions[7].answer)
        self.assertIn("le ménage est facturé séparément", current.questions[7].answer)
        previous = catalogue.tache_two_location_history()[group].revisions[0]
        self.assertEqual(current.opening, previous.opening)
        self.assertEqual(current.closing, previous.closing)
        self.assertEqual(current.questions[3].question, previous.questions[0].question)
        self.assertEqual(current.questions[4].question, previous.questions[7].question)
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"][group]
        self.assertEqual(
            hints,
            [
                {
                    "french": "Public conseillé : touristes, familles ou voyageurs d'affaires",
                    "english": "Recommended guests: tourists, families or business travellers",
                },
                {
                    "french": "Mobilier et équipements adaptés aux locataires : cuisine et couchages",
                    "english": "Furniture and equipment for the guests: kitchen and sleeping arrangements",
                },
                {
                    "french": "Courts séjours ou séjours d'une semaine ou plus",
                    "english": "Short stays or stays of a week or longer",
                },
                {
                    "french": "Tarif conseillé par nuit",
                    "english": "Recommended nightly price",
                },
                {
                    "french": "Autorisations et assurances avant publication",
                    "english": "Authorizations and insurance before publishing",
                },
                {
                    "french": "État des lieux et dépôt de garantie",
                    "english": "Condition inspection and security deposit",
                },
                {
                    "french": "Responsables du ménage et de la remise des clés",
                    "english": "Who handles cleaning and key handover",
                },
                {
                    "french": "Commission de gestion et frais restant à votre charge",
                    "english": "Management commission and costs you still pay",
                },
            ],
        )

    def test_fixed_canadian_settings_and_francophone_roles_remain_valid(self):
        by_group = {item.group: item for item in catalogue.tache_two_dialogues().values()}
        for group, place in (
            ("friend-city-housing-search-advice", "Toronto"),
            ("colleague-montreal-work-week-transit", "Montréal"),
            ("edmonton-newcomer-neighbor-schools", "Edmonton"),
            ("canadian-friend-long-time-catch-up", "Calgary"),
        ):
            with self.subTest(group=group):
                self.assertIn(place, json.dumps(asdict(by_group[group]), ensure_ascii=False))
                self.assertNotIn("Seattle", json.dumps(asdict(by_group[group]), ensure_ascii=False))
        student = by_group["french-class-survey-francophone-student"]
        self.assertIn("du Canada", student.questions[0].answer)
        self.assertIn("du Québec", student.questions[0].answer)
        self.assertIn("Seattle", student.questions[1].answer)
        countries = by_group["friend-visited-countries-destination-choice"]
        self.assertIn("Le Canada et les États-Unis", countries.questions[0].answer)

    def test_history_rejects_invalid_replacements_and_follow_up_references(self):
        data = json.loads(LOCATION_HISTORY_PATH.read_text())
        first = next(iter(data["groups"].values()))
        for invalid in (["", "Seattle"], ["Calgary"], ["Calgary", "Calgary"]):
            first["replacements"][0] = invalid
            with patch("pathlib.Path.read_text", return_value=json.dumps(data)):
                with self.assertRaisesRegex(ValueError, "invalid replacement"):
                    load_location_history()
        data = json.loads(LOCATION_HISTORY_PATH.read_text())
        first = next(iter(data["groups"].values()))
        first["revisions"][0]["questions"][0]["follow_up_to"] = 2
        with patch("pathlib.Path.read_text", return_value=json.dumps(data)):
            with self.assertRaisesRegex(ValueError, "invalid follow-up"):
                load_location_history()

    def test_utf16_projection_preserves_a_selection_crossing_a_replaced_place(self):
        old = QuestionText("<div data-annotation-root>🎬 À Beltline, puis un café.</div>")
        new = QuestionText("<div data-annotation-root>🎬 À Capitol Hill, puis un café.</div>")
        quote = "À Beltline, puis"
        start = old.text.index(quote.encode("utf-16-le")) // 2
        anchor = SimpleNamespace(
            quote=quote, start_offset=start, end_offset=start + len(quote),
            prefix=old.slice(0, start), suffix=old.slice(start + len(quote), len(old.units)),
        )
        offsets = _project_location_annotation(anchor, old, new, (("Beltline", "Capitol Hill"),))
        self.assertIsNotNone(offsets)
        self.assertEqual(new.slice(*offsets), "À Capitol Hill, puis")
        altered = QuestionText("<div data-annotation-root>🎬 À Capitol Hill, puis le bus.</div>")
        self.assertIsNone(
            _project_location_annotation(anchor, old, altered, (("Beltline", "Capitol Hill"),))
        )


class PublishedTacheTwoHighlightTests(TestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.user = factories.make_user("location-highlights")
        self.task = factories.make_task(factories.make_part("eo"), "tache-2")
        self.response = factories.make_response(theme=factories.make_theme(task=self.task))
        self.prompt = self.response.prompts.get()
        self.configure_group("estate-agent-housing-options")
        self.client.force_login(self.user)

    def configure_group(self, group):
        key, self.current = next(
            (key, value) for key, value in catalogue.tache_two_dialogues().items()
            if value.group == group
        )
        self.response.content_key = key
        self.response.semantic_group = self.current.group
        self.response.save(update_fields=["content_key", "semantic_group"])
        self.prompt.content_key = key
        self.prompt.model_content = {"storage_key": key}
        self.prompt.save(update_fields=["content_key", "model_content"])
        self.old = catalogue.tache_two_location_history()[self.current.group].revisions[0]
        self.path = prompt_detail_url(self.prompt)

    def highlight(self, number, quote=None, *, surface="detail", **overrides):
        previous = dialogue_response(self.old)
        rendered = _render_questions(
            self.prompt, previous, surface, [self.prompt], dialogue=self.old,
        )
        start, end = rendered.fields[(number, "question")]
        if quote is not None:
            start = rendered.text.index(quote.encode("utf-16-le"), start * 2, end * 2) // 2
            end = start + len(quote.encode("utf-16-le")) // 2
        return Annotation.objects.create(**({
            "user": self.user, "task": self.task, "kind": AnnotationKind.HIGHLIGHT,
            "source_path": self.path,
            "source_key": variant_annotation_key(
                self.prompt, previous, tache_two_dialogue=self.old,
            ) + (":back" if surface == "back" else ""),
            "quote": rendered.slice(start, end), "start_offset": start, "end_offset": end,
            "prefix": rendered.slice(max(0, start - 160), start),
            "suffix": rendered.slice(end, end + 160),
        } | overrides))

    def fetch(self, path=None):
        response = self.client.get(
            reverse("study:annotations_for_source"), {"source_path": path or self.path},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["highlights"]

    def assert_current(self, annotation, surface="detail"):
        annotation.refresh_from_db()
        current = effective_response(self.response, self.user, prompt=self.prompt)
        key = variant_annotation_key(self.prompt, current) + (":back" if surface == "back" else "")
        self.assertEqual(annotation.source_key, key)
        rendered = _render_questions(self.prompt, current, surface, [self.prompt])
        self.assertEqual(
            rendered.slice(annotation.start_offset, annotation.end_offset), annotation.quote,
        )
        self.assertTrue(rendered.slice(0, annotation.start_offset).endswith(annotation.prefix))
        self.assertTrue(
            rendered.slice(annotation.end_offset, len(rendered.units)).startswith(annotation.suffix)
        )

    def test_saved_key_matches_original_published_layout(self):
        previous = dialogue_response(self.old)
        with patch("study.tache_two_dialogues.published_dialogue", return_value=self.old):
            self.assertEqual(
                variant_annotation_key(self.prompt, previous),
                variant_annotation_key(self.prompt, previous, tache_two_dialogue=self.old),
            )

    def test_unchanged_and_replaced_highlights_remain_visible_and_keep_notes(self):
        marks = [
            self.highlight(1),
            self.highlight(3, "Beltline"),
            self.highlight(3),
            self.highlight(8, body="My learned phrase.", title="Review", study_later=True),
        ]
        highlights = self.fetch()
        self.assertEqual(len(highlights), len(marks))
        for mark in marks:
            self.assert_current(mark)
        self.assertEqual(marks[1].quote, "Capitol Hill")
        self.assertIn("Capitol Hill et Ballard", marks[2].quote)
        self.assertEqual(
            (marks[3].body, marks[3].title, marks[3].study_later),
            ("My learned phrase.", "Review", True),
        )
        revisions = [mark.updated_at for mark in marks]
        self.fetch()
        for mark, timestamp in zip(marks, revisions):
            mark.refresh_from_db()
            self.assertEqual(mark.updated_at, timestamp)

    def test_review_front_and_back_are_preserved(self):
        path = reverse("study:task_review", args=["eo", "tache-2"]) + "?kind=spine"
        back = self.highlight(3, "Bridgeland", surface="back", source_path=path)
        front = self.highlight(
            1, source_path=path,
            source_key=variant_annotation_key(
                self.prompt, dialogue_response(self.old), tache_two_dialogue=self.old,
            ) + ":front",
        )
        self.fetch(path)
        self.assert_current(back, "back")
        front.refresh_from_db()
        self.assertEqual(
            front.source_key, variant_annotation_key(self.prompt, dialogue_response(self.current)) + ":front",
        )

    def test_delivery_reorder_recovers_unchanged_questions_but_not_rewritten_wording(self):
        self.configure_group("furniture-delivery-service")
        marks = [
            self.highlight(1),
            self.highlight(3, body="My price vocabulary."),
            self.highlight(4),
            self.highlight(7),
        ]
        changed = self.highlight(2)
        old_key = changed.source_key
        review_path = reverse("study:task_review", args=["eo", "tache-2"]) + "?kind=spine"
        back = self.highlight(3, surface="back", source_path=review_path)
        self.fetch()
        self.fetch(review_path)
        for mark in marks:
            self.assert_current(mark)
        self.assert_current(back, "back")
        rendered = _render_questions(
            self.prompt, dialogue_response(self.current), "detail", [self.prompt],
        )
        self.assertEqual(
            (marks[1].start_offset, marks[1].end_offset), rendered.fields[(2, "question")],
        )
        self.assertEqual(marks[1].body, "My price vocabulary.")
        changed.refresh_from_db()
        self.assertEqual(changed.source_key, old_key)
        self.assertIn("mesures et de photos", changed.quote)
        self.assertEqual(Annotation.objects.count(), 6)

    def test_apartment_rewrite_preserves_other_highlights_from_both_published_revisions(self):
        self.configure_group("estate-agent-advertised-apartment-purchase")
        marks = [self.highlight(1), self.highlight(7)]
        previous = dialogue_response(self.old)
        rendered = _render_questions(
            self.prompt, previous, "detail", [self.prompt], dialogue=self.old,
        )
        quote = "Beltline"
        start = rendered.text.index(quote.encode("utf-16-le")) // 2
        location = Annotation.objects.create(
            user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
            source_path=self.path,
            source_key=variant_annotation_key(self.prompt, previous, tache_two_dialogue=self.old),
            quote=quote, start_offset=start, end_offset=start + len(quote),
            prefix=rendered.slice(max(0, start - 160), start),
            suffix=rendered.slice(start + len(quote), start + len(quote) + 160),
        )
        self.old = catalogue.tache_two_location_history()[self.current.group].revisions[-1]
        marks.append(self.highlight(4))
        changed = self.highlight(3, body="My original work-needed note.")
        old_key = changed.source_key
        self.fetch()
        for mark in (*marks, location):
            self.assert_current(mark)
        self.assertEqual(location.quote, "Capitol Hill")
        changed.refresh_from_db()
        self.assertEqual(changed.source_key, old_key)
        self.assertEqual(changed.body, "My original work-needed note.")

    def test_quebec_agency_rewrite_preserves_highlights_from_original_revision(self):
        self.configure_group("quebec-newcomer-estate-agency-housing-procedures")
        unchanged = [self.highlight(number) for number in (3, 4, 5, 6, 8)]
        changed = [self.highlight(number) for number in (1, 2, 7)]
        old_keys = [mark.source_key for mark in changed]
        self.fetch()
        for mark in unchanged:
            self.assert_current(mark)
        for mark, old_key in zip(changed, old_keys):
            mark.refresh_from_db()
            self.assertEqual(mark.source_key, old_key)
        self.assertEqual(Annotation.objects.count(), 8)

    def test_quebec_agency_guarantor_edit_preserves_other_highlights_and_archived_note(self):
        self.configure_group("quebec-newcomer-estate-agency-housing-procedures")
        self.old = catalogue.tache_two_location_history()[self.current.group].revisions[-1]
        unchanged = [self.highlight(number) for number in (1, 2, 3, 4, 5, 6, 8)]
        changed = self.highlight(7, body="My rental references note.", study_later=True)
        old_key = changed.source_key
        self.fetch()
        for mark in unchanged:
            self.assert_current(mark)
        changed.refresh_from_db()
        self.assertEqual(changed.source_key, old_key)
        self.assertEqual(changed.body, "My rental references note.")
        self.assertTrue(changed.study_later)
        self.assertEqual(Annotation.objects.count(), 8)

    def test_shared_room_combination_preserves_unchanged_highlights_and_archived_notes(self):
        self.configure_group("offered-room-in-existing-shared-apartment")
        unchanged = [self.highlight(number) for number in range(4, 9)]
        changed = [
            self.highlight(number, body=f"My original question {number} note.", study_later=True)
            for number in range(1, 4)
        ]
        old_keys = [mark.source_key for mark in changed]
        self.fetch()
        for mark in unchanged:
            self.assert_current(mark)
        for number, (mark, old_key) in enumerate(zip(changed, old_keys), 1):
            mark.refresh_from_db()
            self.assertEqual(mark.source_key, old_key)
            self.assertEqual(mark.body, f"My original question {number} note.")
            self.assertTrue(mark.study_later)
        self.assertEqual(Annotation.objects.count(), 8)

    def test_friend_housing_topic_split_preserves_unchanged_and_moved_question_highlights(self):
        self.configure_group("friend-city-housing-search-advice")
        unchanged = [
            self.highlight(number, body=f"My learned question {number}.")
            for number in (1, 2, 3, 5, 7)
        ]
        changed = [self.highlight(number) for number in (4, 6, 8)]
        old_keys = [mark.source_key for mark in changed]
        self.fetch()
        rendered = _render_questions(
            self.prompt, dialogue_response(self.current), "detail", [self.prompt],
        )
        for mark, new_number in zip(unchanged, (1, 2, 3, 4, 6)):
            self.assert_current(mark)
            self.assertEqual(
                (mark.start_offset, mark.end_offset), rendered.fields[(new_number, "question")],
            )
            self.assertTrue(mark.body.startswith("My learned question "))
        for mark, old_key in zip(changed, old_keys):
            mark.refresh_from_db()
            self.assertEqual(mark.source_key, old_key)
        self.assertEqual(Annotation.objects.count(), 8)

    def assert_revision_highlights_preserved(self, group, moved, *, revision=-1):
        self.configure_group(group)
        self.old = catalogue.tache_two_location_history()[group].revisions[revision]
        marks = {
            number: self.highlight(number, body=f"My question {number} note.", study_later=True)
            for number in range(1, 9)
        }
        old_keys = {number: mark.source_key for number, mark in marks.items()}
        self.fetch()
        rendered = _render_questions(
            self.prompt, dialogue_response(self.current), "detail", [self.prompt],
        )
        for number, mark in marks.items():
            mark.refresh_from_db()
            if number in moved:
                self.assert_current(mark)
                self.assertEqual(
                    (mark.start_offset, mark.end_offset), rendered.fields[(moved[number], "question")],
                )
            else:
                self.assertEqual(mark.source_key, old_keys[number])
            self.assertEqual(mark.body, f"My question {number} note.")
            self.assertTrue(mark.study_later)
        self.assertEqual(Annotation.objects.count(), 8)

    def test_heavy_transport_reorder_preserves_unchanged_questions_and_archived_notes(self):
        self.assert_revision_highlights_preserved(
            "help-transport-heavy-objects-no-vehicle", {5: 1, 1: 2, 7: 7},
        )

    def test_blue_audit_keeps_every_learned_question_or_its_exact_archived_revision(self):
        manifest = json.loads(Path(__file__).with_name("blue_audit_fixtures.json").read_text())
        dialogues = {row.group: row for row in catalogue.tache_two_dialogues().values()}
        histories = catalogue.tache_two_location_history()
        for group, audit in manifest["reviewed"].items():
            if audit["archive_index"] is None:
                continue
            with self.subTest(group=group):
                before = histories[group].revisions[audit["archive_index"]]
                positions = {
                    row.question: number for number, row in enumerate(dialogues[group].questions, 1)
                }
                moved = {
                    number: positions[row.question]
                    for number, row in enumerate(before.questions, 1) if row.question in positions
                }
                self.assert_revision_highlights_preserved(
                    group, moved, revision=audit["archive_index"],
                )
            Annotation.objects.filter(user=self.user).delete()

    def test_blue_audit_does_not_replace_private_questions_explanations_or_saved_notes(self):
        manifest = json.loads(Path(__file__).with_name("blue_audit_fixtures.json").read_text())
        for theme, groups in manifest["themes"].items():
            candidates = [
                group for group in groups
                if manifest["reviewed"][group]["archive_index"] is not None
            ]
            if not candidates:
                continue
            group = candidates[0]
            with self.subTest(theme=theme, group=group):
                self.configure_group(group)
                index = manifest["reviewed"][group]["archive_index"]
                self.old = catalogue.tache_two_location_history()[group].revisions[index]
                values = asdict(dialogue_response(self.old))
                values.pop("is_personal")
                values["arguments"] = list(values["arguments"])
                values["arguments"][0]["idea"] = "Ma question personnelle pour cette situation ?"
                values["nuance"] = f"My private explanation for {theme}."
                personal = PersonalResponse.objects.create(
                    user=self.user, response=self.response, source_prompt=self.prompt, **values,
                )
                mark = self.highlight(2, body=f"My learned {theme} note.", study_later=True)
                self.fetch()
                personal.refresh_from_db()
                mark.refresh_from_db()
                self.assertEqual(personal.arguments, values["arguments"])
                self.assertEqual(personal.nuance, values["nuance"])
                self.assertTrue(personal.is_active)
                self.assertEqual(mark.body, f"My learned {theme} note.")
                self.assertTrue(mark.study_later)
                current = effective_response(self.response, self.user, prompt=self.prompt)
                self.assertTrue(current.is_personal)
                self.assertEqual([asdict(row) for row in current.arguments], values["arguments"])
            PersonalResponse.objects.filter(user=self.user).delete()
            Annotation.objects.filter(user=self.user).delete()

    def test_work_rewrites_preserve_unchanged_questions_and_archive_learned_wording(self):
        mappings = {
            "new-employee-company-orientation": {1: 1, 2: 2, 3: 3},
            "director-canada-fortnight-training": {2: 2, 3: 3, 7: 7},
            "friend-first-workday-report": {2: 4, 3: 5, 4: 2, 5: 3, 6: 6, 7: 7, 8: 8},
            "newcomer-canada-friend-job-market": {7: 7},
            "canadian-work-hours-home-country-comparison": {4: 4, 5: 5, 6: 6},
            "former-colleague-new-job-to-change-employment": {2: 2, 5: 5},
            "new-colleague-quebec-career-migration": {3: 3, 4: 4, 6: 6},
            "recruiter-scheduled-interview-preparation": {1: 2, 2: 1, 3: 3, 4: 4, 6: 6, 8: 8},
            "colleague-internal-job-change": {4: 4, 6: 6, 7: 7, 8: 8},
            "friend-upcoming-job-interview-advice": {4: 4, 5: 5, 7: 7},
            "acquaintance-new-job-overall-experience": {2: 2, 5: 5, 8: 8},
            "retirement-party-invitation": {1: 1, 2: 2, 4: 4},
            "supervisor-overseas-job-offer": {1: 1, 2: 2, 3: 3, 4: 4},
            "friend-association-work-experience": {1: 1, 3: 4, 5: 3},
            "colleague-management-promotion-party": {1: 1, 2: 2, 3: 3, 4: 4, 7: 7, 8: 8},
        }
        for group, mapping in mappings.items():
            with self.subTest(group=group):
                revision = 1 if group == "supervisor-overseas-job-offer" else 0
                self.assert_revision_highlights_preserved(group, mapping, revision=revision)
            Annotation.objects.filter(user=self.user).delete()

    def test_education_rewrites_preserve_unchanged_questions_and_archive_learned_wording(self):
        mappings = {
            "newcomer-canada-private-french-teacher": {2: 2, 3: 3},
            "french-teacher-study-abroad-advice": {8: 8},
            "language-school-new-language": {1: 1, 2: 2, 5: 4},
            "parent-after-school-activity-advice": {2: 2, 3: 3, 5: 5, 6: 6, 7: 7, 8: 8},
            "friend-child-language-stay-abroad": {1: 1, 3: 4, 7: 8},
            "edmonton-newcomer-neighbor-schools": {2: 2, 7: 8, 8: 7},
            "french-teacher-language-school-student-game": {2: 3, 3: 4, 4: 6, 7: 1},
            "friend-planned-canadian-studies": {1: 1, 2: 3, 4: 2, 6: 6, 7: 7, 8: 8},
            "fellow-parent-first-school-fete": {1: 1, 2: 2, 4: 4, 5: 5, 8: 8},
            "french-class-survey-francophone-student": {1: 1, 7: 7, 8: 8},
            "calgary-university-adult-language-courses": {1: 1, 2: 2, 3: 3, 7: 7, 8: 8},
        }
        for group, mapping in mappings.items():
            with self.subTest(group=group):
                revision = 1 if group == "friend-child-language-stay-abroad" else 0
                self.assert_revision_highlights_preserved(group, mapping, revision=revision)
            Annotation.objects.filter(user=self.user).delete()

    def test_second_education_pass_preserves_the_first_review_and_its_moved_highlights(self):
        mappings = {
            "calgary-university-adult-language-courses": {
                1: 1, 2: 2, 3: 3, 5: 5, 6: 6, 7: 7, 8: 8,
            },
            "edmonton-newcomer-neighbor-schools": {
                2: 2, 3: 3, 4: 4, 7: 7, 8: 8,
            },
            "fellow-parent-first-school-fete": {1: 1, 2: 2, 4: 4, 5: 5, 7: 7, 8: 8},
            "french-class-survey-francophone-student": {
                1: 1, 2: 2, 3: 3, 4: 4, 6: 6, 7: 7, 8: 8,
            },
            "french-teacher-language-school-student-game": {
                2: 3, 3: 4, 4: 5, 5: 6, 7: 1, 8: 8,
            },
            "french-teacher-study-abroad-advice": {3: 3, 4: 4, 6: 6, 7: 7, 8: 8},
            "friend-child-language-stay-abroad": {1: 1, 2: 2, 3: 4, 5: 6, 6: 3, 7: 7, 8: 8},
            "friend-planned-canadian-studies": {1: 1, 2: 2, 3: 3, 6: 6, 7: 7, 8: 8},
            "language-school-new-language": {1: 1, 2: 2, 4: 5, 5: 4, 6: 6, 7: 7, 8: 8},
        }
        for group, mapping in mappings.items():
            with self.subTest(group=group):
                revision = 2 if group == "friend-child-language-stay-abroad" else 1
                self.assert_revision_highlights_preserved(group, mapping, revision=revision)
            Annotation.objects.filter(user=self.user).delete()

    def test_specificity_pass_preserves_the_second_review_and_its_learned_questions(self):
        mappings = {
            "newcomer-canada-private-french-teacher": {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 8: 7},
            "edmonton-newcomer-neighbor-schools": {2: 2, 3: 3, 4: 4, 7: 7, 8: 8},
            "fellow-parent-first-school-fete": {1: 1, 2: 2, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8},
            "language-school-new-language": {1: 1, 2: 2, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8},
        }
        for group, mapping in mappings.items():
            with self.subTest(group=group):
                self.assert_revision_highlights_preserved(group, mapping)
            Annotation.objects.filter(user=self.user).delete()

    def test_education_reorder_does_not_replace_private_questions_or_prompt_notes(self):
        cases = (
            ("edmonton-newcomer-neighbor-schools", 0, 8, "Quelle école conviendrait à mes enfants ?"),
            ("language-school-new-language", 1, 4, "Proposez-vous aussi des cours intensifs ?"),
            ("newcomer-canada-private-french-teacher", 1, 8, "Comment préparez-vous vos cours particuliers ?"),
        )
        for group, revision, number, question in cases:
            with self.subTest(group=group):
                self.configure_group(group)
                self.old = catalogue.tache_two_location_history()[group].revisions[revision]
                values = asdict(dialogue_response(self.old))
                values.pop("is_personal")
                values["arguments"] = list(values["arguments"])
                values["arguments"][0]["idea"] = question
                values["nuance"] = "My private explanation of this education enquiry."
                personal = PersonalResponse.objects.create(
                    user=self.user, response=self.response, source_prompt=self.prompt, **values,
                )
                mark = self.highlight(number, body="My learned education question.", study_later=True)
                self.fetch()
                self.assert_current(mark)
                personal.refresh_from_db()
                self.assertEqual(personal.arguments, values["arguments"])
                self.assertEqual(personal.nuance, values["nuance"])
                self.assertTrue(personal.is_active)
                current = effective_response(self.response, self.user, prompt=self.prompt)
                self.assertTrue(current.is_personal)
                self.assertEqual([asdict(row) for row in current.arguments], values["arguments"])
                self.assertEqual(mark.body, "My learned education question.")
                self.assertTrue(mark.study_later)
            PersonalResponse.objects.filter(user=self.user).delete()
            Annotation.objects.filter(user=self.user).delete()

    def test_work_reorder_does_not_replace_private_questions_or_prompt_notes(self):
        self.configure_group("friend-first-workday-report")
        self.old = catalogue.tache_two_location_history()[self.current.group].revisions[-1]
        values = asdict(dialogue_response(self.old))
        values.pop("is_personal")
        values["arguments"] = list(values["arguments"])
        values["arguments"][0]["idea"] = "Ma question personnelle sur cette première journée ?"
        values["nuance"] = "My private first-day explanation."
        personal = PersonalResponse.objects.create(
            user=self.user, response=self.response, source_prompt=self.prompt, **values,
        )
        mark = self.highlight(4, body="My learned welcome question.", study_later=True)
        self.fetch()
        self.assert_current(mark)
        personal.refresh_from_db()
        self.assertEqual(personal.arguments, values["arguments"])
        self.assertEqual(personal.nuance, values["nuance"])
        self.assertTrue(personal.is_active)
        current = effective_response(self.response, self.user, prompt=self.prompt)
        self.assertTrue(current.is_personal)
        self.assertEqual([asdict(row) for row in current.arguments], values["arguments"])
        self.assertEqual(mark.body, "My learned welcome question.")
        self.assertTrue(mark.study_later)

    def test_babysitter_referral_reorder_preserves_unchanged_questions_and_archived_notes(self):
        self.assert_revision_highlights_preserved(
            "colleague-babysitter-referral-needs", {1: 1}, revision=0,
        )

    def test_grocery_fee_before_timing_reorder_preserves_unchanged_question_highlights(self):
        self.assert_revision_highlights_preserved(
            "grocery-store-home-delivery", {4: 4, 7: 6},
            revision=0,
        )

    def test_grocery_payment_and_free_delivery_refinements_preserve_other_learned_questions(self):
        self.assert_revision_highlights_preserved(
            "grocery-store-home-delivery", {1: 1, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8},
            revision=4,
        )

    def test_childcare_logistics_insertion_preserves_moved_questions_and_archived_notes(self):
        self.assert_revision_highlights_preserved(
            "neighbor-child-one-day-care", {}, revision=0,
        )

    def test_neighbourhood_wording_changes_preserve_other_highlights_and_archived_notes(self):
        mappings = {
            "neighbor-dog-care-week-paid": {1: 1, 7: 7},
            "trusted-person-temporary-pet-care": {2: 2, 8: 8},
            "volunteer-local-association-information-office": {1: 1},
            "friend-three-year-old-weekend-care": {},
            "friend-holiday-apartment-watch": {1: 1},
            "friend-homeless-meal-volunteering": {2: 4, 5: 5},
            "friend-entertain-visiting-nephews": {2: 2, 8: 8},
            "visit-colleague-minor-accident": {1: 1, 6: 6, 7: 7},
            "child-friends-family-holiday-invitation": {3: 2, 6: 6},
            "neighbor-environmental-association-volunteering": {1: 1},
            "neighbor-home-childcare-provider-referral": {1: 1, 2: 2, 3: 3, 8: 8},
            "help-friend-post-parcel": {1: 1, 8: 8},
            "host-foreign-friends-city-advice": {3: 1},
        }
        for group, mapping in mappings.items():
            with self.subTest(group=group):
                self.assert_revision_highlights_preserved(
                    group, mapping, revision=0,
                )
            Annotation.objects.filter(user=self.user).delete()

    def test_prior_theme_second_pass_preserves_all_learned_questions_and_archived_notes(self):
        mappings = {
            "friend-three-year-old-weekend-care": {3: 3},
            "grocery-store-home-delivery": {1: 1, 5: 4, 7: 6},
            "help-friend-post-parcel": {1: 1, 4: 4, 8: 8},
            "medical-secretary-temporary-replacement-doctor": {
                1: 1, 4: 5, 8: 8,
            },
            "volunteer-local-association-information-office": {
                1: 1, 6: 6, 7: 7,
            },
            "friend-association-work-experience": {
                1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 8: 8,
            },
            "supervisor-overseas-job-offer": {1: 1, 2: 2, 3: 3, 4: 4, 8: 8},
            "recruiter-scheduled-interview-preparation": {
                1: 2, 2: 1, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8,
            },
        }
        for group, mapping in mappings.items():
            with self.subTest(group=group):
                revision = 0 if group == "medical-secretary-temporary-replacement-doctor" else 1
                if group == "supervisor-overseas-job-offer":
                    revision = 2
                self.assert_revision_highlights_preserved(group, mapping, revision=revision)
            Annotation.objects.filter(user=self.user).delete()

    def test_prior_and_current_neighbourhood_passes_preserve_private_versions_and_highlights(self):
        cases = (
            ("help-friend-post-parcel", 1, 7, "À quel guichet puis-je déposer ton paquet ?"),
            ("recruiter-scheduled-interview-preparation", 1, 2, "Quel matériel dois-je tester avant l'entretien ?"),
            ("supervisor-overseas-job-offer", 2, 8, "Quelles conditions faudrait-il négocier avant le départ ?"),
            ("friend-holiday-apartment-watch", 1, 4, "Pourrais-tu me montrer les plantes avant ton départ ?"),
            ("friend-holiday-apartment-watch", 3, 4, "Pourrais-tu marquer les pots des plantes à arroser ?"),
            ("friend-holiday-apartment-watch", 4, 7, "Pourrais-tu me laisser un contact local avant de partir ?"),
            ("friend-homeless-meal-volunteering", 3, 3, "Les repas sont-ils cuisinés par l'association ou par un partenaire ?"),
            ("medical-secretary-temporary-replacement-doctor", 1, 3, "Comment pourrai-je transmettre mes résultats ?"),
            ("trusted-person-temporary-pet-care", 1, 5, "Quels jouets préfères-tu laisser à ton animal ?"),
            ("trusted-person-temporary-pet-care", 2, 4, "Tu pourrais me montrer comment préparer ses repas ?"),
            ("volunteer-local-association-information-office", 2, 8, "Est-ce que je peux venir observer une mission avec un ami ?"),
            ("volunteer-local-association-information-office", 3, 2, "Cette association propose-t-elle des ateliers pour les enfants ?"),
            ("volunteer-local-association-information-office", 3, 5, "Puis-je aider seulement pendant les vacances scolaires ?"),
            ("newcomer-local-acquaintance-meet-people", 0, 2, "Quelle association correspondrait à mes loisirs ?"),
            ("host-foreign-friends-city-advice", 2, 3, "Quels quartiers se prêtent à une visite avec des amis ?"),
            ("neighbor-dog-care-week-paid", 2, 4, "Comment puis-je vérifier les consignes avant votre départ ?"),
            ("friend-three-year-old-weekend-care", 3, 2, "Quels repas faciles puis-je préparer si elle refuse ce que tu as prévu ?"),
            ("friend-three-year-old-weekend-care", 3, 8, "Pourrais-tu me laisser un autre numéro si ton téléphone est éteint ?"),
            ("colleague-babysitter-referral-needs", 2, 7, "La personne sera-t-elle payée après chaque garde ?"),
            ("colleague-babysitter-referral-needs", 3, 8, "Pourriez-vous rencontrer cette personne à la sortie de l'école ?"),
            ("neighbor-home-childcare-provider-referral", 2, 7, "Comment régliez-vous les heures supplémentaires ?"),
            ("neighbor-child-one-day-care", 2, 3, "Qu'est-ce qui rassure votre enfant avec de nouvelles personnes ?"),
            ("grocery-store-home-delivery", 3, 4, "Quels frais sont inclus dans le total annoncé ?"),
            ("child-friends-family-holiday-invitation", 2, 3, "Quelles dépenses dois-je prévoir pour mon enfant ?"),
        )
        for group, revision, number, question in cases:
            with self.subTest(group=group):
                self.configure_group(group)
                self.old = catalogue.tache_two_location_history()[group].revisions[revision]
                values = asdict(dialogue_response(self.old))
                values.pop("is_personal")
                values["arguments"] = list(values["arguments"])
                values["arguments"][0]["idea"] = question
                values["nuance"] = "My private explanation of this neighbourhood or work enquiry."
                personal = PersonalResponse.objects.create(
                    user=self.user, response=self.response, source_prompt=self.prompt, **values,
                )
                mark = self.highlight(number, body="My learned private question.", study_later=True)
                self.fetch()
                self.assert_current(mark)
                personal.refresh_from_db()
                self.assertEqual(personal.arguments, values["arguments"])
                self.assertEqual(personal.nuance, values["nuance"])
                self.assertTrue(personal.is_active)
                current = effective_response(self.response, self.user, prompt=self.prompt)
                self.assertTrue(current.is_personal)
                self.assertEqual([asdict(row) for row in current.arguments], values["arguments"])
                self.assertEqual(mark.body, "My learned private question.")
                self.assertTrue(mark.study_later)
            Annotation.objects.filter(user=self.user).delete()
            PersonalResponse.objects.filter(user=self.user).delete()

    def test_three_pass_neighbourhood_review_preserves_every_previous_question_highlight(self):
        cases = {
            "animal-protection-association-invitation": (0, {3: 3, 6: 6}),
            "child-friends-family-holiday-invitation": (1, {3: 2, 6: 6}),
            "colleague-babysitter-referral-needs": (1, {1: 1, 4: 4, 6: 6}),
            "friend-entertain-visiting-nephews": (1, {2: 2, 4: 4, 7: 7, 8: 8}),
            "friend-holiday-apartment-watch": (1, {1: 1, 2: 2, 4: 5}),
            "friend-homeless-meal-volunteering": (1, {2: 4, 5: 5, 7: 7}),
            "friend-three-year-old-weekend-care": (2, {3: 3}),
            "grocery-store-home-delivery": (2, {1: 1, 5: 4, 7: 6, 8: 7}),
            "help-friend-post-parcel": (2, {1: 1, 4: 4, 5: 5, 8: 8}),
            "host-foreign-friends-city-advice": (1, {3: 1}),
            "medical-secretary-temporary-replacement-doctor": (1, {1: 1, 2: 3, 4: 5, 8: 8}),
            "neighbor-child-one-day-care": (1, {1: 1, 6: 6, 7: 7}),
            "neighbor-dog-care-week-paid": (1, {1: 1, 7: 7}),
            "neighbor-environmental-association-volunteering": (1, {1: 1, 3: 3}),
            "neighbor-home-childcare-provider-referral": (1, {1: 1, 2: 2, 3: 3, 8: 8}),
            "newcomer-local-acquaintance-meet-people": (0, {1: 1, 2: 2, 4: 4, 5: 5}),
            "trusted-person-temporary-pet-care": (1, {2: 2, 8: 8}),
            "visit-colleague-minor-accident": (1, {1: 1, 6: 6, 7: 7}),
        }
        for group, (revision, mapping) in cases.items():
            with self.subTest(group=group):
                self.assert_revision_highlights_preserved(group, mapping, revision=revision)
            Annotation.objects.filter(user=self.user).delete()

    def test_archived_food_highlight_is_not_guessed_onto_a_privately_rewritten_question(self):
        self.configure_group("friend-three-year-old-weekend-care")
        self.old = catalogue.tache_two_location_history()[self.current.group].revisions[3]
        values = asdict(dialogue_response(self.old))
        values.pop("is_personal")
        values["arguments"] = list(values["arguments"])
        values["arguments"][0]["idea"] = (
            "Quels repas faciles puis-je préparer si elle refuse ce que tu as prévu ?"
        )
        values["nuance"] = "My personal childcare explanation."
        personal = PersonalResponse.objects.create(
            user=self.user, response=self.response, source_prompt=self.prompt, **values,
        )
        mark = self.highlight(1, body="My note on the published food question.", study_later=True)
        old_key = mark.source_key
        self.fetch()
        mark.refresh_from_db()
        personal.refresh_from_db()
        self.assertEqual(mark.source_key, old_key)
        self.assertEqual(mark.quote, self.old.questions[0].question)
        self.assertEqual(mark.body, "My note on the published food question.")
        self.assertTrue(mark.study_later)
        self.assertEqual(personal.arguments, values["arguments"])
        self.assertEqual(personal.nuance, values["nuance"])
        self.assertTrue(personal.is_active)

    def test_city_rewrite_preserves_retained_questions_and_archives_rewritten_highlights(self):
        self.assert_revision_highlights_preserved(
            "host-foreign-friends-city-advice",
            {3: 1, 7: 7, 8: 8},
            revision=2,
        )

    def test_practical_developments_preserve_retained_questions_from_every_latest_layout(self):
        cases = {
            "animal-protection-association-invitation": (1, {1: 1, 2: 2, 3: 3, 6: 6, 7: 7}),
            "child-friends-family-holiday-invitation": (2, {3: 2, 4: 4, 5: 5, 6: 6, 7: 7}),
            "colleague-babysitter-referral-needs": (2, {1: 1, 2: 2, 3: 3, 4: 4, 6: 6}),
            "friend-entertain-visiting-nephews": (2, {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 7: 7, 8: 8}),
            "friend-holiday-apartment-watch": (2, {1: 1, 2: 2, 5: 5}),
            "friend-homeless-meal-volunteering": (2, {2: 4, 3: 1, 5: 5, 7: 7}),
            "friend-three-year-old-weekend-care": (3, {3: 3, 4: 4}),
            "grocery-store-home-delivery": (3, {1: 1, 5: 4, 6: 5, 7: 6, 8: 7}),
            "help-friend-post-parcel": (3, {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 8: 8}),
            "medical-secretary-temporary-replacement-doctor": (2, {1: 1, 2: 2, 3: 3, 5: 5, 6: 6, 8: 8}),
            "neighbor-child-one-day-care": (2, {1: 1, 6: 6, 7: 7}),
            "neighbor-environmental-association-volunteering": (2, {1: 1, 3: 3, 5: 5, 6: 6}),
            "neighbor-home-childcare-provider-referral": (2, {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 8: 8}),
            "visit-colleague-minor-accident": (2, {number: number for number in range(1, 8)}),
        }
        for group, (revision, mapping) in cases.items():
            with self.subTest(group=group):
                self.assert_revision_highlights_preserved(group, mapping, revision=revision)
            Annotation.objects.filter(user=self.user).delete()

    def test_dog_routine_rewrite_preserves_other_questions_and_archives_changed_highlights(self):
        self.assert_revision_highlights_preserved(
            "neighbor-dog-care-week-paid",
            {1: 1, 2: 2, 7: 7},
            revision=2,
        )

    def test_babysitter_first_meeting_refinement_preserves_all_other_question_highlights(self):
        self.assert_revision_highlights_preserved(
            "colleague-babysitter-referral-needs",
            {number: number for number in range(1, 8)},
            revision=3,
        )

    def test_apartment_watering_refinement_preserves_moved_visit_question_and_other_highlights(self):
        self.assert_revision_highlights_preserved(
            "friend-holiday-apartment-watch",
            {1: 1, 2: 2, 3: 4, 5: 5},
            revision=3,
        )

    def test_apartment_contact_merger_keeps_other_highlights_and_archives_rewritten_questions(self):
        self.assert_revision_highlights_preserved(
            "friend-holiday-apartment-watch",
            {number: number for number in range(1, 6)},
            revision=4,
        )

    def test_meal_volunteering_reorder_preserves_moved_questions_and_archives_the_broad_question(self):
        self.assert_revision_highlights_preserved(
            "friend-homeless-meal-volunteering",
            {2: 4, 3: 1, 4: 2, 5: 5, 6: 6, 7: 7, 8: 8},
            revision=3,
        )

    def test_dog_care_and_payment_refinements_preserve_other_questions_and_archive_previous_wording(self):
        self.assert_revision_highlights_preserved(
            "neighbor-dog-care-week-paid",
            {number: number for number in (1, 2, 3, 4, 5, 7)},
            revision=3,
        )

    def test_friend_pet_care_upgrade_preserves_unchanged_questions_and_archives_rewritten_highlights(self):
        self.assert_revision_highlights_preserved(
            "trusted-person-temporary-pet-care",
            {1: 1, 2: 2, 3: 3, 8: 8},
            revision=2,
        )

    def test_volunteer_tasks_and_first_visit_preserve_other_questions_and_archive_previous_wording(self):
        self.assert_revision_highlights_preserved(
            "volunteer-local-association-information-office",
            {number: number for number in (1, 4, 6, 7)},
            revision=2,
        )

    def test_cultural_volunteering_choice_preserves_other_questions_and_archives_previous_wording(self):
        self.assert_revision_highlights_preserved(
            "volunteer-local-association-information-office",
            {number: number for number in (1, 3, 4, 6, 7)},
            revision=3,
        )

    def test_unspecified_apartment_revision_preserves_other_questions_and_archived_notes(self):
        self.assert_revision_highlights_preserved(
            "estate-agent-advertised-apartment-unspecified",
            {number: number for number in (1, 3, 4, 5, 6, 8)},
        )

    def test_summer_house_priority_reorder_recovers_current_and_pre_geography_highlights(self):
        self.assert_revision_highlights_preserved(
            "colleague-summer-house-rental", {1: 4, 2: 5, 3: 6, 4: 7, 5: 8, 6: 1, 7: 2, 8: 3},
        )
        self.old = catalogue.tache_two_location_history()[self.current.group].revisions[0]
        legacy = self.highlight(4, "Bowness", body="My original neighbourhood note.")
        self.fetch()
        self.assert_current(legacy)
        self.assertEqual(legacy.quote, "Ballard")
        self.assertEqual(legacy.body, "My original neighbourhood note.")
        self.assertEqual(Annotation.objects.count(), 9)

    def test_newcomer_rent_and_guarantor_extensions_preserve_other_question_highlights(self):
        self.configure_group("canada-newcomer-apartment-procedure-unspecified-adviser")
        unchanged = [self.highlight(number) for number in (1, 2, 3, 5, 6, 8)]
        changed = [
            self.highlight(number, body=f"My original question {number}.", study_later=True)
            for number in (4, 7)
        ]
        old_keys = [mark.source_key for mark in changed]
        self.fetch()
        for mark in unchanged:
            self.assert_current(mark)
        for number, mark, old_key in zip((4, 7), changed, old_keys):
            mark.refresh_from_db()
            self.assertEqual(mark.source_key, old_key)
            self.assertEqual(mark.body, f"My original question {number}.")
            self.assertTrue(mark.study_later)
        self.assertEqual(Annotation.objects.count(), 8)

    def test_holiday_letting_rewrite_recovers_moved_questions_and_archives_changed_wording(self):
        self.configure_group("owner-holiday-letting-estate-agency-advice")
        unchanged = [
            self.highlight(number, body=f"My learned question {number}.")
            for number in (1, 8)
        ]
        changed = [
            self.highlight(number, body=f"My original question {number}.", study_later=True)
            for number in range(2, 8)
        ]
        old_keys = [mark.source_key for mark in changed]
        review_path = reverse("study:task_review", args=["eo", "tache-2"]) + "?kind=spine"
        back = self.highlight(1, surface="back", source_path=review_path)
        self.fetch()
        self.fetch(review_path)
        rendered = _render_questions(
            self.prompt, dialogue_response(self.current), "detail", [self.prompt],
        )
        for mark, new_number in zip(unchanged, (4, 5)):
            self.assert_current(mark)
            self.assertEqual(
                (mark.start_offset, mark.end_offset), rendered.fields[(new_number, "question")],
            )
            self.assertTrue(mark.body.startswith("My learned question "))
        self.assert_current(back, "back")
        for number, (mark, old_key) in enumerate(zip(changed, old_keys), 2):
            mark.refresh_from_db()
            self.assertEqual(mark.source_key, old_key)
            self.assertEqual(mark.body, f"My original question {number}.")
            self.assertTrue(mark.study_later)
        self.assertEqual(Annotation.objects.count(), 9)

    def test_holiday_letting_upgrade_does_not_replace_a_longer_personal_version(self):
        self.configure_group("owner-holiday-letting-estate-agency-advice")
        values = asdict(dialogue_response(self.old))
        values.pop("is_personal")
        values["arguments"] = list(values["arguments"])
        values["arguments"].extend(
            values["arguments"][0] | {"idea": f"Ma question personnelle supplémentaire {number} ?"}
            for number in range(1, 8)
        )
        values["nuance"] = "My private holiday-letting explanation."
        personal = PersonalResponse.objects.create(
            user=self.user, response=self.response, source_prompt=self.prompt, **values,
        )
        self.fetch()
        personal.refresh_from_db()
        self.assertEqual(personal.arguments, values["arguments"])
        self.assertEqual(personal.nuance, values["nuance"])
        self.assertTrue(personal.is_active)
        current = effective_response(self.response, self.user, prompt=self.prompt)
        self.assertTrue(current.is_personal)
        self.assertEqual(len(current.arguments), 15)
        self.assertEqual([asdict(row) for row in current.arguments], values["arguments"])
        self.assertEqual(current.nuance, values["nuance"])

    def test_old_personal_model_and_private_note_are_not_rewritten(self):
        previous = dialogue_response(self.old)
        values = asdict(previous)
        values.pop("is_personal")
        values["arguments"] = list(values["arguments"])
        values["nuance"] = "My private prompt explanation."
        personal = PersonalResponse.objects.create(
            user=self.user, response=self.response, source_prompt=self.prompt, **values,
        )
        mark = self.highlight(3)
        self.fetch()
        self.assert_current(mark)
        self.assertIn("Beltline et Bridgeland", mark.quote)
        personal.refresh_from_db()
        self.assertEqual(personal.arguments, values["arguments"])
        self.assertEqual(personal.nuance, values["nuance"])

    def test_personal_edits_remain_unchanged_and_only_unmodified_fields_recover(self):
        previous = dialogue_response(self.old)
        values = asdict(previous)
        values.pop("is_personal")
        values["arguments"] = list(values["arguments"])
        values["arguments"][2]["idea"] = "Ma question personnelle sur le quartier ?"
        personal = PersonalResponse.objects.create(
            user=self.user, response=self.response, source_prompt=self.prompt, **values,
        )
        unchanged = self.highlight(8)
        changed = self.highlight(3, "Beltline")
        old_key = changed.source_key
        self.fetch()
        self.assert_current(unchanged)
        changed.refresh_from_db()
        self.assertEqual(changed.source_key, old_key)
        personal.refresh_from_db()
        self.assertEqual(personal.arguments, values["arguments"])

    def test_other_users_invalid_context_and_unknown_revisions_are_untouched(self):
        other = self.highlight(1, user=factories.make_user("other-location-reader"))
        invalid = self.highlight(2, prefix="Not the saved source context")
        unknown = self.highlight(8, source_key=f"response:{self.prompt.content_key}:variant-0000000000000000")
        keys = {mark.pk: mark.source_key for mark in (other, invalid, unknown)}
        self.fetch()
        for mark in (other, invalid, unknown):
            mark.refresh_from_db()
            self.assertEqual(mark.source_key, keys[mark.pk])
        self.assertEqual(Annotation.objects.count(), 3)
