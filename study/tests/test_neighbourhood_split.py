import hashlib
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from study import catalogue, content_loader as content, srs
from study.account_services import provision_user_study_data
from study.models import (
    Annotation, AnnotationKind, Card, CardType, MemoryQuestionProgress,
    PersonalQuestionResponse, PersonalResponse, Phrase, Prompt, Rating, Response,
    ReviewLog, Theme, ThemeVocabularyProgress,
)
from study.tests import factories
from study.tests.neighbourhood_fixtures import ALL_NEIGHBOURHOOD_GROUPS, NEIGHBOURHOOD_GROUPS
from study.views.helpers import _memory_progress


class NeighbourhoodSplitCorpusTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def test_source_consignes_and_questions_are_unchanged_apart_from_memory_links(self):
        rows = []
        for path in sorted(content.TACHE_TWO_SUBJECTS_DIR.glob("*/batch_*.json")):
            data = json.loads(path.read_text())
            for subject in data["subjects"]:
                for question in subject["questions"]:
                    if isinstance(question, dict):
                        question.pop("memory_number", None)
            rows.append(data)
        snapshot = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "7716c9b5400dbeea01d7230db97047c9379736918e0fa3eeffe691340c4316d5",
        )

    def test_each_equivalent_consigne_has_the_objective_based_theme(self):
        dialogues = catalogue.tache_two_dialogues()
        themes, mapping = catalogue.tache_two_subject_themes()
        self.assertEqual(len(themes), 13)
        expected_counts = {
            "vie-quartier": (9, 5),
            "garde-enfants-animaux": (15, 7),
            "benevolat-associations": (10, 4),
        }
        for slug, expected_groups in NEIGHBOURHOOD_GROUPS.items():
            rows = [row for key, row in dialogues.items() if mapping[key] == slug]
            groups = {row.group for row in rows}
            with self.subTest(theme=slug):
                if slug == "sorties-spectacles":
                    self.assertLessEqual(expected_groups, groups)
                else:
                    self.assertEqual(groups, expected_groups)
                    self.assertEqual((len(rows), len(groups)), expected_counts[slug])
                for key, row in dialogues.items():
                    if row.group in expected_groups:
                        self.assertEqual(mapping[key], slug)
        self.assertEqual(
            sum(row.group in ALL_NEIGHBOURHOOD_GROUPS for row in dialogues.values()), 36,
        )

    def test_the_three_split_collections_keep_the_exact_reviewed_dialogues(self):
        raw = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        expected = {
            "vie-quartier": "a9b6675d01a9e58630ca96a8a1051a55a4b59add3dfbc59e10b8d0db02f8c19f",
            "garde-enfants-animaux": "fd0d29214cb1ba88cd3f45b82cff5caf83a4b1851bfba564314f20df54615962",
            "benevolat-associations": "94acdfc8cdbb0c25b65987a65334833476c59f425409c11f469373b836266ca9",
        }
        for slug, digest in expected.items():
            snapshot = json.dumps(
                [raw[group] for group in sorted(NEIGHBOURHOOD_GROUPS[slug])],
                ensure_ascii=False, sort_keys=True,
            ).encode()
            self.assertEqual(hashlib.sha256(snapshot).hexdigest(), digest)

    def test_old_memory_questions_survive_once_with_their_exact_learning_keys(self):
        archive = content.QUESTION_BANK_DIR / "question_bank_history/neighbourhood.json"
        original = json.loads(archive.read_text())["memories"][0]
        snapshot = json.dumps(original, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "c8895ccfda5506c029fa0593f75088d885a9df4f678caee8c58d9b26a0982413",
        )
        questions = [
            question
            for bank in content.load_question_banks()
            for section in bank.sections for group in section.groups
            for question in group.questions
        ]
        self.assertEqual(len(questions), 676)
        self.assertEqual(len({question.content_key for question in questions}), 676)
        by_text = {question.text: question.content_key for question in questions}
        for section in original["sections"]:
            for group in section["groups"]:
                for text in group["questions"]:
                    digest = hashlib.sha256(text.casefold().encode()).hexdigest()
                    self.assertEqual(by_text[text], f"memory:3:question:{digest}")

    def test_original_vocabulary_entries_are_reassigned_without_changing_ids_or_wording(self):
        original = json.loads((
            content.QUESTION_BANK_DIR / "question_bank_history/neighbourhood_vocabulary.json"
        ).read_text())
        by_id = {
            entry["id"]: entry
            for path in content.TACHE_TWO_THEME_VOCABULARY_DIR.glob("*.json")
            for entry in json.loads(path.read_text())["entries"]
        }
        self.assertEqual(len(by_id), 585)
        for entry in original["entries"]:
            self.assertEqual(by_id[entry["id"]], entry)

    def test_legacy_memory_number_requires_a_positive_integer(self):
        original = json.loads(content.QUESTION_BANK_PATH.read_text())
        for value in (0, -1, True, "3", None):
            with self.subTest(value=value), TemporaryDirectory() as directory:
                original["sections"][0]["groups"][0]["questions"][0] = {
                    "text": "Ma question déplacée ?", "legacy_memory_number": value,
                }
                path = Path(directory) / "memory.json"
                path.write_text(json.dumps(original))
                with self.assertRaisesMessage(ValueError, "invalid legacy memory number"):
                    content.load_question_bank(path)

    def test_relocated_questions_cannot_duplicate_an_existing_learning_identity(self):
        original = json.loads(content.QUESTION_BANK_PATH.read_text())
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "1.json").write_text(json.dumps(original))
            original["number"] = 2
            first = original["sections"][0]["groups"][0]["questions"][0]
            moved = {"text": first} if isinstance(first, str) else dict(first)
            moved["legacy_memory_number"] = 1
            original["sections"][0]["groups"][0]["questions"][0] = moved
            (root / "2.json").write_text(json.dumps(original))
            with self.assertRaisesMessage(ValueError, "must not share question identities"):
                content.load_question_banks(root)


class NeighbourhoodSplitPreservationTests(TestCase):
    def test_reclassification_import_preserves_ids_private_material_and_all_learning_state(self):
        call_command("import_content", stdout=StringIO())
        dialogues = catalogue.tache_two_dialogues()
        keys = {key for key, row in dialogues.items() if row.group in ALL_NEIGHBOURHOOD_GROUPS}
        prompts = list(Prompt.objects.filter(content_key__in=keys).select_related("response"))
        legacy_theme = Theme.objects.get(slug="tache-2-vie-quartier")
        legacy_theme.name = "Tâche 2 · Vie de quartier & entraide"
        legacy_theme.display_name = "Vie de quartier & entraide"
        legacy_theme.save(update_fields=["name", "display_name"])
        for index, prompt in enumerate(prompts, start=1):
            Prompt.objects.filter(pk=prompt.pk).update(
                theme=legacy_theme, number=1_000_000 + index,
            )
        response_ids = {prompt.response_id for prompt in prompts}
        Response.objects.filter(pk__in=response_ids).update(theme=legacy_theme)
        prompt_ids = dict(Prompt.objects.values_list("content_key", "pk"))
        response_keys = dict(Prompt.objects.filter(content_key__in=keys).values_list(
            "content_key", "response_id",
        ))
        user = factories.make_user("split-neighbourhood")
        provision_user_study_data(user)
        prompt = Prompt.objects.get(content_key="tache2:fevrier:batch-06:subject-26")
        card = Card.objects.get(user=user, response=prompt.response, card_type=CardType.SPINE)
        srs.review(card, Rating.GOOD)
        personal = PersonalResponse.objects.create(
            user=user, response=prompt.response, source_prompt=prompt,
            nuance="My private childcare note.", conclusion="Mes questions personnelles.",
        )
        mark = Annotation.objects.create(
            user=user, task=legacy_theme.task, kind=AnnotationKind.HIGHLIGHT,
            source_key=f"response:{prompt.response.content_key}:back",
            source_path="/expression/orale/tache-2/", quote="Mon passage appris.",
            start_offset=0, end_offset=18, body="Ma note privée.", study_later=True,
        )
        care = next(bank for bank in content.load_question_banks() if bank.number == 12)
        learned_key = next(key for key in care.question_keys if key.startswith("memory:3:"))
        memory = MemoryQuestionProgress.objects.create(
            user=user, memory_number=3, question_key=learned_key,
        )
        private_question = PersonalQuestionResponse.objects.create(
            user=user, task=legacy_theme.task, question_key=learned_key,
            body="My private response to this learned question.",
        )
        vocabulary = ThemeVocabularyProgress.objects.create(
            user=user, phrase=Phrase.objects.get(phrase_id="quamc07"),
        )
        records = [card, personal, mark, memory, private_question, vocabulary]
        before = [type(row).objects.filter(pk=row.pk).values().get() for row in records]
        reviews = list(ReviewLog.objects.filter(card=card).values())

        call_command("import_content", stdout=StringIO())
        call_command("import_content", stdout=StringIO())

        self.assertEqual(dict(Prompt.objects.values_list("content_key", "pk")), prompt_ids)
        self.assertEqual(dict(Prompt.objects.filter(content_key__in=keys).values_list(
            "content_key", "response_id",
        )), response_keys)
        for row, expected in zip(records, before):
            self.assertEqual(type(row).objects.filter(pk=row.pk).values().get(), expected)
        self.assertEqual(list(ReviewLog.objects.filter(card=card).values()), reviews)
        _, mapping = catalogue.tache_two_subject_themes()
        for current in Prompt.objects.filter(content_key__in=keys).select_related("theme"):
            self.assertEqual(current.theme.slug, f"tache-2-{mapping[current.content_key]}")
        legacy_theme.refresh_from_db()
        self.assertEqual(legacy_theme.name, "Tâche 2 · Services du quotidien & entraide")
        states = _memory_progress(user, content.load_question_banks())
        self.assertEqual(states[12]["completed_keys"], {learned_key})
        self.assertNotIn(learned_key, states[3]["completed_keys"])
