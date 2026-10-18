import hashlib
import json
from collections import defaultdict
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils.html import escape

from study import catalogue, content_loader as content, srs
from study.account_services import provision_user_study_data
from study.models import (
    Annotation, AnnotationKind, Card, CardType, MemoryQuestionProgress,
    PersonalQuestionResponse, PersonalResponse, Phrase, Prompt, Rating,
    Response, ReviewLog, Theme, ThemeVocabularyProgress,
)
from study.tests import factories
from study.tests.culture_fixtures import (
    ALL_CULTURE_GROUPS, CULTURE_GROUPS, ORIGINAL_ARTS_GROUPS,
)
from study.views.helpers import _memory_progress


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
    ).hexdigest()


class CultureSplitCorpusTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def test_all_eighty_five_publications_and_equivalents_follow_their_objective(self):
        themes, mapping = catalogue.tache_two_subject_themes()
        dialogues = catalogue.tache_two_dialogues()
        self.assertEqual(len(themes), 18)
        self.assertEqual(len(dialogues), 348)
        self.assertEqual(len({row.group for row in dialogues.values()}), 164)
        self.assertEqual(len(ALL_CULTURE_GROUPS), 41)
        self.assertEqual(sum(map(len, CULTURE_GROUPS.values())), 41)
        self.assertEqual(
            sum(row.group in ALL_CULTURE_GROUPS for row in dialogues.values()), 85,
        )
        expected = {
            "arts-loisirs": (17, 7),
            "culture-medias": (24, 11),
            "sorties-spectacles": (18, 9),
            "spectacles-festivals": (11, 5),
            "loisirs-clubs-jeux": (15, 9),
        }
        for slug, groups in CULTURE_GROUPS.items():
            rows = [row for key, row in dialogues.items() if mapping[key] == slug]
            self.assertEqual({row.group for row in rows}, groups)
            self.assertEqual((len(rows), len(groups)), expected[slug])
            for key, row in dialogues.items():
                if row.group in groups:
                    self.assertEqual(mapping[key], slug, key)

    def test_all_reviewed_dialogues_keep_their_exact_content(self):
        raw = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        self.assertEqual(
            fingerprint([raw[group] for group in sorted(ALL_CULTURE_GROUPS)]),
            "e41bb0e9069658f9280837b2791610b564bab0379b752827faf84bb0b443672b",
        )

    def test_museum_visit_develops_the_practical_details_and_aligns_every_piste(self):
        publications = {
            key: row for key, row in catalogue.tache_two_dialogues().items()
            if row.group == "museum-group-visit-reception"
        }
        self.assertEqual(set(publications), {
            "tache2:janvier:batch-03:subject-14",
            "tache2:mai:batch-03:subject-14",
            "tache2:aout:batch-04:subject-19",
            "tache2:octobre:batch-01:subject-04",
            "tache2:octobre:batch-06:subject-30",
        })
        row = next(iter(publications.values()))
        self.assertTrue(all(item == row for item in publications.values()))
        self.assertEqual(
            row.opening,
            "Bonjour ! Nous aimerions visiter votre musée. J'aurais quelques questions pour préparer notre venue.",
        )
        self.assertEqual([question.topic for question in row.questions], [
            "Horaires",
            *(["Expositions et visite guidée"] * 3),
            *(["Tarifs et réservation"] * 4),
        ])
        goals = (
            ("jours et horaires", None),
            ("laquelle nous conseilleriez-vous", None),
            ("à quels horaires a-t-elle lieu", 2),
            ("visiter le reste du musée librement", 3),
            ("proposez-vous des tarifs réduits", None),
            ("À partir de combien de personnes", 5),
            ("sinon, quel supplément faut-il prévoir par personne", 5),
            ("combien de temps à l'avance", 7),
        )
        for question, (goal, reference) in zip(row.questions, goals, strict=True):
            self.assertIn(goal, question.question)
            self.assertEqual(question.follow_up_to, reference)
            if reference is not None:
                self.assertTrue(question.condition)
        self.assertIn("quatorze heures", row.questions[2].answer)
        self.assertIn("une heure", row.questions[3].answer)
        self.assertIn("jusqu'à la fermeture", row.questions[3].answer)
        self.assertIn("dix personnes", row.questions[5].answer)
        self.assertIn("8 $ par personne", row.questions[5].answer)
        self.assertIn("5 $ par personne", row.questions[6].answer)
        self.assertIn("au moins deux jours", row.questions[7].answer)
        self.assertIn("only if a group rate is offered", row.note)
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"][row.group]
        self.assertEqual(hints, [
            {"french": "Jours et horaires d'ouverture du musée", "english": "Museum opening days and hours"},
            {"french": "Expositions en cours et conseil pour choisir", "english": "Current exhibitions and recommended choice"},
            {"french": "Disponibilité d'une visite guidée et horaires", "english": "Guided-tour availability and times"},
            {"french": "Durée de la visite guidée et visite libre ensuite", "english": "Guided-tour duration and independent access afterwards"},
            {"french": "Prix d'entrée et réductions proposées", "english": "Admission price and available discounts"},
            {"french": "Nombre minimum de participants et prix du tarif de groupe", "english": "Minimum group size and price per person"},
            {"french": "Visite guidée comprise ou supplément par personne", "english": "Whether the guided tour is included or costs extra per person"},
            {"french": "Réservation de la visite guidée et délai pour réserver", "english": "How and how far ahead to book the guided tour"},
        ])
        previous = json.loads((
            content.QUESTION_BANK_DIR / "dialogue_history/locations.json"
        ).read_text())["groups"][row.group]["revisions"]
        self.assertEqual(len(previous), 1)
        self.assertEqual(
            fingerprint(previous[0]),
            "c3eee20c1ad8cdaa4d65502245375da2e417618f794c6fa7b35d8b256136780d",
        )

    def test_evening_outings_follow_the_neighbours_recommendations_without_assuming_night_transport(self):
        publications = {
            key: row for key, row in catalogue.tache_two_dialogues().items()
            if row.group == "new-neighbor-evening-entertainment"
        }
        self.assertEqual(set(publications), {"tache2:fevrier:batch-02:subject-07"})
        row = next(iter(publications.values()))
        self.assertEqual(row.register, "vous")
        self.assertIn("accommodation is already arranged", row.note)
        self.assertIn("not official booking guarantees", row.note)
        self.assertEqual([question.topic for question in row.questions], [
            *(["Lieux, activités et ambiance"] * 4),
            *(["Budget et organisation"] * 3),
            "Retour",
        ])
        goals = (
            ("et qu'est-ce qu'on peut y faire", None),
            ("plutôt calme ou animée", 1),
            ("quels styles de musique", 1),
            ("séances suivies d'une discussion", 1),
            ("un concert au café et pour une séance de cinéma", None),
            ("sorties gratuites ou des tarifs réduits", None),
            ("consulter le programme", None),
            ("rentrer à pied", None),
        )
        for question, (goal, reference) in zip(row.questions, goals, strict=True):
            self.assertIn(goal, question.question)
            self.assertEqual(question.follow_up_to, reference)
            if reference is not None:
                self.assertTrue(question.condition)
        self.assertIn("soirées jeux", row.questions[0].answer)
        self.assertIn("films récents", row.questions[0].answer)
        self.assertIn("vers vingt heures", row.questions[2].answer)
        self.assertIn("hors consommations", row.questions[4].answer)
        self.assertIn("il faut prévoir sa consommation", row.questions[5].answer)
        self.assertIn("Je réserve", row.questions[6].answer)
        self.assertIn("vérifiez l'heure du dernier passage", row.questions[7].answer)
        self.assertIn("Do not assume night buses run", row.note)
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"][row.group]
        self.assertEqual(hints, [
            {"french": "Lieux conseillés pour sortir le soir et activités proposées", "english": "Recommended evening venues and activities available there"},
            {"french": "Ambiance calme ou animée selon les lieux et les soirées", "english": "Quiet or lively atmosphere depending on the venue and evening"},
            {"french": "Styles de musique et soirs des concerts du café", "english": "Music styles and concert nights at the café"},
            {"french": "Séances spéciales et animations au cinéma", "english": "Special screenings and activities at the cinema"},
            {"french": "Budget à prévoir pour les concerts et le cinéma", "english": "Approximate budget for concerts and cinema"},
            {"french": "Sorties gratuites et tarifs réduits selon les jours", "english": "Free outings and cheaper rates on certain days"},
            {"french": "Programme des soirées et activités à réserver", "english": "Where to find the programme and which activities to book"},
            {"french": "Retour à pied ou transport à prévoir après la soirée", "english": "Walking home or arranging transport after the evening"},
        ])
        previous = json.loads((
            content.QUESTION_BANK_DIR / "dialogue_history/locations.json"
        ).read_text())["groups"][row.group]["revisions"]
        self.assertEqual(len(previous), 1)
        self.assertEqual(
            fingerprint(previous[0]),
            "7925b87de27afa6e2c67e2c345ab75041f6f07c4fe1e1a8c4e7ece8c6ac7de98",
        )

    def test_all_104_original_questions_keep_their_wording_and_learning_identity(self):
        originals = json.loads((
            content.QUESTION_BANK_DIR / "question_bank_history/culture.json"
        ).read_text())["memories"]
        expected = {
            9: "71b2fb0c5bba4746529a1fc36753f930b3f656415dfd7b0c11f75718ae66915f",
            10: "fe5b45311c239171f1a227126e926bb0a3510ca419ce1449ed2d8380e7ba992a",
        }
        questions = [
            question for bank in content.load_question_banks()
            for section in bank.sections for group in section.groups
            for question in group.questions
        ]
        self.assertEqual(len(questions), 936)
        self.assertEqual(len({q.content_key for q in questions}), 936)
        self.assertEqual(len({q.text.casefold() for q in questions}), 936)
        count = 0
        for original in originals:
            self.assertEqual(fingerprint(original), expected[original["number"]])
            for section in original["sections"]:
                for group in section["groups"]:
                    for text in group["questions"]:
                        count += 1
                        matches = [q for q in questions if q.text == text]
                        self.assertEqual(len(matches), 1, text)
                        digest = hashlib.sha256(text.casefold().encode()).hexdigest()
                        self.assertEqual(
                            matches[0].content_key,
                            f"memory:{original['number']}:question:{digest}",
                        )
        self.assertEqual(count, 104)

    def test_the_thirteen_unrelated_memories_remain_exact(self):
        banks = [
            json.loads(path.read_text())
            for path in sorted(content.QUESTION_BANK_DIR.glob("master_question_bank_*.json"))
            if path.stem not in {
                "master_question_bank_9", "master_question_bank_10", "master_question_bank_16",
                "master_question_bank_17", "master_question_bank_18",
            }
        ]
        self.assertEqual(len(banks), 13)
        self.assertEqual(
            fingerprint(banks),
            "26512e7e292f64b95518de03cb6f5ebcef4d24329aaab9a3e814040e954bd358",
        )

    def test_all_ninety_original_vocabulary_entries_keep_their_exact_fields_and_ids(self):
        originals = json.loads((
            content.QUESTION_BANK_DIR / "question_bank_history/culture_vocabulary.json"
        ).read_text())["themes"]
        self.assertEqual(
            fingerprint(originals),
            "2462fbda3143e2ec1c0573d5fb6ed01990e82df6593ba7aa8a9f46afe1f1784d",
        )
        entries = [
            entry for path in content.TACHE_TWO_THEME_VOCABULARY_DIR.glob("*.json")
            for entry in json.loads(path.read_text())["entries"]
        ]
        by_id = {entry["id"]: entry for entry in entries}
        self.assertEqual(len(entries), 810)
        self.assertEqual(len(by_id), 810)
        count = 0
        for original in originals:
            for entry in original["entries"]:
                count += 1
                self.assertEqual(by_id[entry["id"]], entry)
        self.assertEqual(count, 90)


class CultureSplitPreservationTests(TestCase):
    def test_import_twice_preserves_old_collection_ids_private_material_and_learning(self):
        call_command("import_content", stdout=StringIO())
        dialogues = catalogue.tache_two_dialogues()
        keys = {key for key, row in dialogues.items() if row.group in ALL_CULTURE_GROUPS}
        old_themes = {
            slug: Theme.objects.get(slug=f"tache-2-{slug}")
            for slug in ("arts-loisirs", "sorties-spectacles")
        }
        for slug, label in (
            ("arts-loisirs", "Arts & loisirs"),
            ("sorties-spectacles", "Sorties & spectacles"),
        ):
            old = old_themes[slug]
            old.name = f"Tâche 2 · {label}"
            old.display_name = label
            old.save(update_fields=["name", "display_name"])
        for index, prompt in enumerate(Prompt.objects.filter(content_key__in=keys), 1):
            group = dialogues[prompt.content_key].group
            slug = "arts-loisirs" if group in ORIGINAL_ARTS_GROUPS else "sorties-spectacles"
            old = old_themes[slug]
            Prompt.objects.filter(pk=prompt.pk).update(theme=old, number=1_000_000 + index)
            Response.objects.filter(pk=prompt.response_id).update(theme=old)
        self.assertEqual(Prompt.objects.filter(content_key__in=keys, theme=old_themes["arts-loisirs"]).count(), 48)
        self.assertEqual(Prompt.objects.filter(content_key__in=keys, theme=old_themes["sorties-spectacles"]).count(), 37)
        prompt_ids = dict(Prompt.objects.values_list("content_key", "pk"))
        response_ids = dict(Prompt.objects.filter(content_key__in=keys).values_list(
            "content_key", "response_id",
        ))
        user = factories.make_user("split-culture")
        provision_user_study_data(user)
        prompt = Prompt.objects.get(content_key=next(
            key for key, row in dialogues.items()
            if row.group == "friend-reading-for-literary-review"
        ))
        task = old_themes["arts-loisirs"].task
        card = Card.objects.get(user=user, response=prompt.response, card_type=CardType.SPINE)
        srs.review(card, Rating.GOOD)
        personal = PersonalResponse.objects.create(
            user=user, response=prompt.response, source_prompt=prompt,
            nuance="My private reading note.", conclusion="Mes questions sur ce roman.",
        )
        annotation = Annotation.objects.create(
            user=user, task=task, kind=AnnotationKind.HIGHLIGHT,
            source_key=f"response:{prompt.response.content_key}:back",
            source_path="/expression/orale/tache-2/", quote="Mon passage appris.",
            start_offset=0, end_offset=18, body="My saved culture note.", study_later=True,
        )
        records = [card, personal, annotation]
        reviewed_cards = [card]
        vocabulary = {}
        for phrase_id, slug in (("artmc08", "culture-medias"), ("soreu13", "arts-loisirs")):
            marker = ThemeVocabularyProgress.objects.create(
                user=user, phrase=Phrase.objects.get(phrase_id=phrase_id),
            )
            phrase_card = Card.objects.get(
                user=user, phrase=marker.phrase, card_type=CardType.PHRASE_PRODUCTION,
            )
            srs.review(phrase_card, Rating.GOOD)
            reviewed_cards.append(phrase_card)
            records.extend([marker, phrase_card])
            vocabulary[marker.phrase_id] = slug
        learned = defaultdict(set)
        banks = {bank.number: bank for bank in content.load_question_banks()}
        for destination, origin in ((9, 10), (18, 9), (16, 9), (16, 10)):
            key = next(
                key for key in banks[destination].question_keys
                if key.startswith(f"memory:{origin}:")
            )
            learned[destination].add(key)
            records.extend([
                MemoryQuestionProgress.objects.create(
                    user=user, memory_number=origin, question_key=key,
                ),
                PersonalQuestionResponse.objects.create(
                    user=user, task=task, question_key=key,
                    body=f"My private answer for {destination}, originally {origin}.",
                ),
            ])
        before = [type(row).objects.filter(pk=row.pk).values().get() for row in records]
        reviews = list(ReviewLog.objects.filter(card__in=reviewed_cards).values())

        call_command("import_content", stdout=StringIO())
        call_command("import_content", stdout=StringIO())

        self.assertEqual(dict(Prompt.objects.values_list("content_key", "pk")), prompt_ids)
        self.assertEqual(dict(Prompt.objects.filter(content_key__in=keys).values_list(
            "content_key", "response_id",
        )), response_ids)
        for row, expected in zip(records, before):
            self.assertEqual(type(row).objects.filter(pk=row.pk).values().get(), expected)
        self.assertEqual(
            list(ReviewLog.objects.filter(card__in=reviewed_cards).values()), reviews,
        )
        _, mapping = catalogue.tache_two_subject_themes()
        for current in Prompt.objects.filter(content_key__in=keys).select_related("theme"):
            self.assertEqual(current.theme.slug, f"tache-2-{mapping[current.content_key]}")
        for slug, expected in (
            ("arts-loisirs", "Cours & ateliers"),
            ("sorties-spectacles", "Sorties, visites & bonnes adresses"),
        ):
            old_themes[slug].refresh_from_db()
            self.assertEqual(old_themes[slug].display_name, expected)
        states = _memory_progress(user, content.load_question_banks())
        for number, expected in learned.items():
            self.assertEqual(states[number]["completed_keys"], expected)
        for phrase_pk, slug in vocabulary.items():
            self.assertEqual(
                set(Phrase.objects.get(pk=phrase_pk).source_prompts.values_list(
                    "theme__slug", flat=True,
                )),
                {f"tache-2-{slug}"},
            )

    def test_the_five_collection_names_and_vocabulary_routes_are_available(self):
        call_command("import_content", stdout=StringIO())
        user = factories.make_user("culture-directory")
        provision_user_study_data(user)
        self.client.force_login(user)
        directory = self.client.get(reverse("study:tache_two_theme_vocabulary"))
        subjects = self.client.get(reverse("study:task_browse", args=["eo", "tache-2"]))
        for slug, label in (
            ("arts-loisirs", "Cours & ateliers"),
            ("culture-medias", "Culture, lectures & médias"),
            ("sorties-spectacles", "Sorties, visites & bonnes adresses"),
            ("spectacles-festivals", "Cinéma, spectacles & festivals"),
            ("loisirs-clubs-jeux", "Loisirs, clubs & jeux"),
        ):
            with self.subTest(theme=slug):
                self.assertContains(directory, escape(label))
                self.assertContains(subjects, escape(label))
                detail = self.client.get(reverse(
                    "study:tache_two_theme_vocabulary_detail", args=[slug],
                ))
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.context["phrase_count"], 45)
                self.assertEqual(len(detail.context["review_batches"]), 3)
