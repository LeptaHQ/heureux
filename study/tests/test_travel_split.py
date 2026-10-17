import hashlib
import json
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
from study.tests.housing_work_fixtures import RECLASSIFIED_GROUPS
from study.tests.travel_fixtures import ALL_TRAVEL_GROUPS, TRAVEL_GROUPS
from study.views.helpers import _memory_progress


class TravelSplitCorpusTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def test_all_fifty_four_publications_follow_their_objective_and_keep_equivalents_together(self):
        themes, mapping = catalogue.tache_two_subject_themes()
        dialogues = catalogue.tache_two_dialogues()
        self.assertEqual(len(themes), 18)
        self.assertEqual(len(dialogues), 348)
        self.assertEqual(len(ALL_TRAVEL_GROUPS), 29)
        self.assertEqual(
            sum(row.group in ALL_TRAVEL_GROUPS for row in dialogues.values()), 54,
        )
        expected_counts = {
            "voyages": (32, 15),
            "escapades-tourisme": (14, 7),
            "hebergements-touristiques": (9, 6),
        }
        for slug, groups in TRAVEL_GROUPS.items():
            rows = [row for key, row in dialogues.items() if mapping[key] == slug]
            actual = {row.group for row in rows}
            with self.subTest(theme=slug):
                if slug in expected_counts:
                    expected_groups = groups
                    if slug == "hebergements-touristiques":
                        expected_groups = groups | RECLASSIFIED_GROUPS[slug]
                    self.assertEqual(actual, expected_groups)
                    self.assertEqual((len(rows), len(actual)), expected_counts[slug])
                else:
                    self.assertLessEqual(groups, actual)
                for key, row in dialogues.items():
                    if row.group in groups:
                        self.assertEqual(mapping[key], slug)

    def test_the_twenty_nine_travel_models_keep_the_latest_reviewed_content(self):
        raw = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        snapshot = json.dumps(
            [raw[group] for group in sorted(ALL_TRAVEL_GROUPS)],
            ensure_ascii=False, sort_keys=True,
        ).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "4927722f7518390b36c0103755201b76597d768b285b178fa2a8de8fb42a6145",
        )

    def test_every_old_memory_question_survives_once_with_its_exact_learning_key(self):
        original = json.loads((
            content.QUESTION_BANK_DIR / "question_bank_history/travel.json"
        ).read_text())["memories"][0]
        snapshot = json.dumps(original, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "908bc559498034d6de8d19440d7b9b910b99bbbfcf96c63f82bcf622da8e1658",
        )
        banks = content.load_question_banks()
        questions = [
            question for bank in banks for section in bank.sections
            for group in section.groups for question in group.questions
        ]
        self.assertEqual(len(questions), 936)
        self.assertEqual(len({q.content_key for q in questions}), 936)
        self.assertEqual(len({q.text.casefold() for q in questions}), 936)
        for section in original["sections"]:
            for group in section["groups"]:
                for text in group["questions"]:
                    matches = [q for q in questions if q.text == text]
                    self.assertEqual(len(matches), 1, text)
                    digest = hashlib.sha256(text.casefold().encode()).hexdigest()
                    self.assertEqual(matches[0].content_key, f"memory:7:question:{digest}")
        for bank in banks:
            if bank.number in {7, 14, 15}:
                self.assertEqual(bank.question_count, 52)
                self.assertEqual(bank.category_count, 13)

    def test_all_original_vocabulary_entries_keep_their_fields_and_ids(self):
        original = json.loads((
            content.QUESTION_BANK_DIR / "question_bank_history/travel_vocabulary.json"
        ).read_text())
        snapshot = json.dumps(original, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "eea88c0ad72419aba4dbe3f13548d2a6d7000ead2b03c4ba55b2f94e2d5d0943",
        )
        entries = [
            entry for path in content.TACHE_TWO_THEME_VOCABULARY_DIR.glob("*.json")
            for entry in json.loads(path.read_text())["entries"]
        ]
        by_id = {entry["id"]: entry for entry in entries}
        self.assertEqual(len(entries), 810)
        self.assertEqual(len(by_id), 810)
        for entry in original["entries"]:
            self.assertEqual(by_id[entry["id"]], entry)
        for slug in ("voyages", "escapades-tourisme", "hebergements-touristiques"):
            vocabulary = json.loads((
                content.TACHE_TWO_THEME_VOCABULARY_DIR / f"{slug}.json"
            ).read_text())
            self.assertEqual(len(vocabulary["entries"]), 45)


class TravelSplitPreservationTests(TestCase):
    def test_import_is_idempotent_and_preserves_old_travel_learning_and_private_data(self):
        call_command("import_content", stdout=StringIO())
        dialogues = catalogue.tache_two_dialogues()
        keys = {key for key, row in dialogues.items() if row.group in ALL_TRAVEL_GROUPS}
        prompts = list(Prompt.objects.filter(content_key__in=keys))
        old_theme = Theme.objects.get(slug="tache-2-voyages")
        old_theme.name = "Tâche 2 · Voyages & vacances"
        old_theme.display_name = "Voyages & vacances"
        old_theme.save(update_fields=["name", "display_name"])
        for index, prompt in enumerate(prompts, start=1):
            Prompt.objects.filter(pk=prompt.pk).update(
                theme=old_theme, number=1_000_000 + index,
            )
        Response.objects.filter(pk__in={p.response_id for p in prompts}).update(theme=old_theme)
        prompt_ids = dict(Prompt.objects.values_list("content_key", "pk"))
        response_ids = dict(Prompt.objects.filter(content_key__in=keys).values_list(
            "content_key", "response_id",
        ))
        user = factories.make_user("split-travel")
        provision_user_study_data(user)
        prompt = Prompt.objects.get(content_key="tache2:juin:batch-04:subject-20")
        card = Card.objects.get(user=user, response=prompt.response, card_type=CardType.SPINE)
        srs.review(card, Rating.GOOD)
        personal = PersonalResponse.objects.create(
            user=user, response=prompt.response, source_prompt=prompt,
            nuance="My private hotel note.", conclusion="Mes questions de réservation.",
        )
        annotation = Annotation.objects.create(
            user=user, task=old_theme.task, kind=AnnotationKind.HIGHLIGHT,
            source_key=f"response:{prompt.response.content_key}:back",
            source_path="/expression/orale/tache-2/", quote="Mon passage appris.",
            start_offset=0, end_offset=18, body="My saved travel note.", study_later=True,
        )
        vocabulary = ThemeVocabularyProgress.objects.create(
            user=user, phrase=Phrase.objects.get(phrase_id="voymc04"),
        )
        vocabulary_card = Card.objects.get(
            user=user, phrase=vocabulary.phrase, card_type=CardType.PHRASE_PRODUCTION,
        )
        srs.review(vocabulary_card, Rating.GOOD)
        records = [card, personal, annotation, vocabulary, vocabulary_card]
        learned = {}
        for bank in content.load_question_banks():
            if bank.number not in {14, 15}:
                continue
            key = next(key for key in bank.question_keys if key.startswith("memory:7:"))
            learned[bank.number] = key
            records.extend([
                MemoryQuestionProgress.objects.create(
                    user=user, memory_number=7, question_key=key,
                ),
                PersonalQuestionResponse.objects.create(
                    user=user, task=old_theme.task, question_key=key,
                    body=f"My saved response for relocated question {bank.number}.",
                ),
            ])
        before = [type(row).objects.filter(pk=row.pk).values().get() for row in records]
        reviews = list(ReviewLog.objects.filter(card__in=[card, vocabulary_card]).values())

        call_command("import_content", stdout=StringIO())
        call_command("import_content", stdout=StringIO())

        self.assertEqual(dict(Prompt.objects.values_list("content_key", "pk")), prompt_ids)
        self.assertEqual(dict(Prompt.objects.filter(content_key__in=keys).values_list(
            "content_key", "response_id",
        )), response_ids)
        for row, expected in zip(records, before):
            self.assertEqual(type(row).objects.filter(pk=row.pk).values().get(), expected)
        self.assertEqual(
            list(ReviewLog.objects.filter(card__in=[card, vocabulary_card]).values()), reviews,
        )
        _, mapping = catalogue.tache_two_subject_themes()
        for current in Prompt.objects.filter(content_key__in=keys).select_related("theme"):
            self.assertEqual(current.theme.slug, f"tache-2-{mapping[current.content_key]}")
        old_theme.refresh_from_db()
        self.assertEqual(old_theme.display_name, "Voyages & circuits")
        states = _memory_progress(user, content.load_question_banks())
        for number, key in learned.items():
            self.assertEqual(states[number]["completed_keys"], {key})
            self.assertNotIn(key, states[7]["completed_keys"])
        self.assertEqual(
            set(vocabulary.phrase.source_prompts.values_list("theme__slug", flat=True)),
            {"tache-2-hebergements-touristiques"},
        )

    def test_new_theme_directories_and_vocabulary_are_available(self):
        call_command("import_content", stdout=StringIO())
        user = factories.make_user("travel-directory")
        provision_user_study_data(user)
        self.client.force_login(user)
        directory = self.client.get(reverse("study:tache_two_theme_vocabulary"))
        subjects = self.client.get(reverse("study:task_browse", args=["eo", "tache-2"]))
        for slug, name in (
            ("voyages", "Voyages & circuits"),
            ("escapades-tourisme", "Escapades & tourisme régional"),
            ("hebergements-touristiques", "Hébergements touristiques"),
        ):
            with self.subTest(theme=slug):
                self.assertContains(directory, escape(name))
                self.assertContains(subjects, escape(name))
                detail = self.client.get(reverse(
                    "study:tache_two_theme_vocabulary_detail", args=[slug],
                ))
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.context["phrase_count"], 45)
                self.assertEqual(len(detail.context["review_batches"]), 3)
