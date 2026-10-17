import hashlib
import json
from collections import defaultdict
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from study import catalogue, content_loader as content, srs
from study.account_services import provision_user_study_data
from study.models import (
    Annotation, AnnotationKind, Card, CardType, MemoryQuestionProgress,
    PersonalQuestionResponse, PersonalResponse, Phrase, Prompt, Rating,
    Response, ReviewLog, Theme, ThemeVocabularyProgress,
)
from study.tests import factories
from study.tests.culture_fixtures import (
    ALL_LEISURE_SPLIT_GROUPS, LEISURE_SPLIT_GROUPS, PREVIOUS_LEISURE_GROUPS,
)
from study.views.helpers import _memory_progress


ROOT = content.QUESTION_BANK_DIR
NUMBERS = {
    "sorties-spectacles": 9,
    "arts-loisirs": 10,
    "spectacles-festivals": 17,
    "loisirs-clubs-jeux": 18,
}


def read(path):
    return json.loads(path.read_text())


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
    ).hexdigest()


def previous_questions():
    questions = []
    for bank in read(ROOT / "question_bank_history/leisure.json")["memories"]:
        for section in bank["sections"]:
            for group in section["groups"]:
                for raw in group["questions"]:
                    row = {"text": raw} if isinstance(raw, str) else raw
                    identity_number = row.get("legacy_memory_number", bank["number"])
                    seed = row.get("legacy_text", row["text"]).casefold()
                    questions.append({
                        "key": (
                            f"memory:{identity_number}:question:"
                            f"{hashlib.sha256(seed.encode()).hexdigest()}"
                        ),
                        "text": row["text"],
                        "row": row,
                        "previous_number": bank["number"],
                        "identity_number": identity_number,
                    })
    return questions


class LeisureSplitCorpusTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def test_all_sixty_one_publications_follow_the_four_objectives(self):
        themes, mapping = catalogue.tache_two_subject_themes()
        dialogues = catalogue.tache_two_dialogues()
        self.assertEqual(len(themes), 18)
        self.assertEqual(len(dialogues), 348)
        self.assertEqual(len({row.group for row in dialogues.values()}), 164)
        self.assertEqual(len(ALL_LEISURE_SPLIT_GROUPS), 30)
        self.assertEqual(sum(map(len, LEISURE_SPLIT_GROUPS.values())), 30)
        expected_counts = {
            "sorties-spectacles": (18, 9),
            "arts-loisirs": (17, 7),
            "spectacles-festivals": (11, 5),
            "loisirs-clubs-jeux": (15, 9),
        }
        affected = set()
        for slug, groups in LEISURE_SPLIT_GROUPS.items():
            rows = {
                key: row for key, row in dialogues.items()
                if mapping[key] == slug
            }
            with self.subTest(theme=slug):
                self.assertEqual({row.group for row in rows.values()}, groups)
                self.assertEqual(
                    (len(rows), len(groups)), expected_counts[slug],
                )
                for key, row in dialogues.items():
                    if row.group in groups:
                        self.assertEqual(mapping[key], slug, key)
            affected.update(rows)
        self.assertEqual(len(affected), 61)
        self.assertEqual(
            fingerprint({
                key: slug for key, slug in mapping.items()
                if key not in affected
            }),
            "6800397dfb738da3d28a3042a6c3d3cd07ee0ebec91ac97334c1094372645bbd",
        )

    def test_all_previous_questions_keep_their_exact_text_and_identity(self):
        snapshot = read(ROOT / "question_bank_history/leisure.json")["memories"]
        self.assertEqual(
            fingerprint(snapshot),
            "bf1ad2bc6228cf5a76288b13e09ccf92122c5d4bebbc8a18e265bd079aeed10f",
        )
        current = [
            question for bank in content.load_question_banks()
            for section in bank.sections for group in section.groups
            for question in group.questions
        ]
        self.assertEqual(len(current), 936)
        self.assertEqual(len({question.content_key for question in current}), 936)
        self.assertEqual(len({question.text.casefold() for question in current}), 936)
        by_key = {question.content_key: question for question in current}
        originals = previous_questions()
        self.assertEqual(len(originals), 104)
        for original in originals:
            with self.subTest(question=original["key"]):
                question = by_key[original["key"]]
                self.assertEqual(question.text, original["text"])
                for field in ("note", "english", "legacy_text"):
                    self.assertEqual(
                        getattr(question, field),
                        original["row"].get(field, ""),
                    )

    def test_all_previous_vocabulary_dictionaries_survive_unchanged(self):
        snapshot = read(ROOT / "question_bank_history/leisure_vocabulary.json")["themes"]
        self.assertEqual(
            fingerprint(snapshot),
            "93e87927d494965c53884bc83a632eca8870f4c1a6a909e78935278e6e25213b",
        )
        entries = [
            entry for path in content.TACHE_TWO_THEME_VOCABULARY_DIR.glob("*.json")
            for entry in read(path)["entries"]
        ]
        self.assertEqual(len(entries), 810)
        by_id = {entry["id"]: entry for entry in entries}
        self.assertEqual(len(by_id), 810)
        originals = [entry for theme in snapshot for entry in theme["entries"]]
        self.assertEqual(len(originals), 90)
        for original in originals:
            self.assertEqual(by_id[original["id"]], original)

    def test_the_fourteen_unrelated_learning_collections_remain_exact(self):
        memories = {
            path.name: read(path)
            for path in ROOT.glob("master_question_bank_*.json")
            if int(path.stem.rsplit("_", 1)[1]) not in NUMBERS.values()
        }
        vocabulary = {
            path.name: read(path)
            for path in content.TACHE_TWO_THEME_VOCABULARY_DIR.glob("*.json")
            if path.stem not in NUMBERS
        }
        self.assertEqual(len(memories), 14)
        self.assertEqual(len(vocabulary), 14)
        self.assertEqual(
            fingerprint(memories),
            "9edb7ab6a41afc4c4e9d07f3dfd9749b38f05d9cf0730fd693e95973f18d788b",
        )
        self.assertEqual(
            fingerprint(vocabulary),
            "7ac9ee3ad225d4eeb58cb33e125a55fb905b1405782c14e49766ddbcd2b7c4f1",
        )


class LeisureSplitPreservationTests(TestCase):
    def test_reimport_preserves_ids_private_material_and_moved_learning_state(self):
        call_command("import_content", stdout=StringIO())
        dialogues = catalogue.tache_two_dialogues()
        previous_slug = {
            group: slug for slug, groups in PREVIOUS_LEISURE_GROUPS.items()
            for group in groups
        }
        keys = {
            key for key, row in dialogues.items()
            if row.group in ALL_LEISURE_SPLIT_GROUPS
        }
        old_themes = {
            slug: Theme.objects.get(slug=f"tache-2-{slug}")
            for slug in PREVIOUS_LEISURE_GROUPS
        }
        for index, prompt in enumerate(Prompt.objects.filter(content_key__in=keys), 1):
            theme = old_themes[previous_slug[dialogues[prompt.content_key].group]]
            Prompt.objects.filter(pk=prompt.pk).update(
                theme=theme, number=1_000_000 + index,
            )
            Response.objects.filter(pk=prompt.response_id).update(theme=theme)
        prompt_ids = dict(Prompt.objects.values_list("content_key", "pk"))
        response_ids = dict(Prompt.objects.filter(content_key__in=keys).values_list(
            "content_key", "response_id",
        ))
        user = factories.make_user("focused-leisure-preservation")
        provision_user_study_data(user)
        task = old_themes["arts-loisirs"].task
        records = []
        reviewed_cards = []
        now = timezone.now()
        for group in (
            "canada-cinema-employee-friend",
            "friend-tv-game-participation",
            "friend-entertain-visiting-nephews",
        ):
            prompt = Prompt.objects.get(content_key=next(
                key for key in keys if dialogues[key].group == group
            ))
            card = Card.objects.get(
                user=user, response=prompt.response, card_type=CardType.SPINE,
            )
            srs.review(card, Rating.GOOD)
            card.response_practice_started_at = now
            card.subject_completed_at = now
            card.save(update_fields=[
                "response_practice_started_at", "subject_completed_at",
            ])
            personal = PersonalResponse.objects.create(
                user=user, response=prompt.response, source_prompt=prompt,
                arguments=[{"idea": f"My private question for {group}"}],
            )
            annotation = Annotation.objects.create(
                user=user, task=task, kind=AnnotationKind.HIGHLIGHT,
                source_key=f"response:{prompt.response.content_key}:back",
                source_path="/expression/orale/tache-2/",
                quote="Mon passage appris.", start_offset=0, end_offset=19,
                body="My saved personal note.", study_later=True,
            )
            records.extend([card, personal, annotation])
            reviewed_cards.append(card)

        banks = content.load_question_banks()
        destination_by_key = {
            key: bank.number for bank in banks for key in bank.question_keys
        }
        originals = previous_questions()
        selected = [
            next(row for row in originals if destination_by_key[row["key"]] == number)
            for number in NUMBERS.values()
        ]
        multi_hop = next(
            row for row in originals
            if row["identity_number"] != row["previous_number"]
            and destination_by_key[row["key"]] != row["previous_number"]
        )
        if multi_hop not in selected:
            selected.append(multi_hop)
        learned = defaultdict(set)
        for row in selected:
            learned[destination_by_key[row["key"]]].add(row["key"])
            records.extend([
                MemoryQuestionProgress.objects.create(
                    user=user, memory_number=row["previous_number"],
                    question_key=row["key"],
                ),
                PersonalQuestionResponse.objects.create(
                    user=user, task=task, question_key=row["key"],
                    body="My private answer before the second split.",
                ),
            ])

        destination_by_phrase = {
            entry["id"]: path.stem
            for path in content.TACHE_TWO_THEME_VOCABULARY_DIR.glob("*.json")
            for entry in read(path)["entries"]
        }
        vocabulary_destinations = {}
        snapshots = read(ROOT / "question_bank_history/leisure_vocabulary.json")["themes"]
        for snapshot in snapshots:
            old_prompt = Prompt.objects.filter(
                content_key__in=keys, theme=old_themes[snapshot["theme"]],
            ).first()
            for entry in snapshot["entries"]:
                slug = destination_by_phrase[entry["id"]]
                if slug in vocabulary_destinations.values():
                    continue
                phrase = Phrase.objects.get(phrase_id=entry["id"])
                phrase.source_prompts.set([old_prompt])
                marker = ThemeVocabularyProgress.objects.create(user=user, phrase=phrase)
                card = Card.objects.get(
                    user=user, phrase=phrase, card_type=CardType.PHRASE_PRODUCTION,
                )
                srs.review(card, Rating.GOOD)
                records.extend([marker, card])
                reviewed_cards.append(card)
                vocabulary_destinations[phrase.pk] = slug
        self.assertEqual(set(vocabulary_destinations.values()), set(NUMBERS))
        before = [type(row).objects.filter(pk=row.pk).values().get() for row in records]
        reviews = list(ReviewLog.objects.filter(card__in=reviewed_cards).values())

        call_command("import_content", stdout=StringIO())
        call_command("import_content", stdout=StringIO())

        self.assertEqual(dict(Prompt.objects.values_list("content_key", "pk")), prompt_ids)
        self.assertEqual(
            dict(Prompt.objects.filter(content_key__in=keys).values_list(
                "content_key", "response_id",
            )),
            response_ids,
        )
        for row, expected in zip(records, before):
            self.assertEqual(type(row).objects.filter(pk=row.pk).values().get(), expected)
        self.assertEqual(
            list(ReviewLog.objects.filter(card__in=reviewed_cards).values()), reviews,
        )
        _, mapping = catalogue.tache_two_subject_themes()
        for prompt in Prompt.objects.filter(content_key__in=keys).select_related("theme"):
            self.assertEqual(prompt.theme.slug, f"tache-2-{mapping[prompt.content_key]}")
        states = _memory_progress(user, banks)
        for number, expected in learned.items():
            self.assertEqual(states[number]["completed_keys"], expected)
        for phrase_pk, slug in vocabulary_destinations.items():
            self.assertEqual(
                set(Phrase.objects.get(pk=phrase_pk).source_prompts.values_list(
                    "theme__slug", flat=True,
                )),
                {f"tache-2-{slug}"},
            )
        self.client.force_login(user)
        page = self.client.get(reverse("study:task_browse", args=["eo", "tache-2"]))
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["theme_count"], 18)
        self.assertEqual(page.context["subject_count"], 164)
