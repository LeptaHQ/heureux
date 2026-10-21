import hashlib
import json
from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from study import catalogue, content_loader as content, srs
from study.account_services import provision_user_study_data
from study.models import (
    Annotation, AnnotationKind, Card, CardType, MemoryQuestionProgress,
    PersonalQuestionResponse, PersonalResponse, Phrase, Prompt, Rating,
    Response, ReviewLog, Theme,
)
from study.tests import factories
from study.tests.housing_work_fixtures import RECLASSIFIED_GROUPS


class HousingWorkClassificationTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def test_all_twelve_publications_and_their_equivalents_move_together(self):
        _, mapping = catalogue.tache_two_subject_themes()
        dialogues = catalogue.tache_two_dialogues()
        self.assertEqual(len(dialogues), 348)
        self.assertEqual(len({row.group for row in dialogues.values()}), 164)
        for slug, groups in RECLASSIFIED_GROUPS.items():
            keys = [key for key, row in dialogues.items() if row.group in groups]
            self.assertEqual(len(keys), 2 if slug == "fetes" else 5)
            for key in keys:
                self.assertEqual(mapping[key], slug, key)
        for slug, expected in (
            ("travail", (28, 13)), ("logement", (25, 11)),
            ("vie-quartier", (14, 7)), ("hebergements-touristiques", (9, 6)),
        ):
            rows = [row for key, row in dialogues.items() if mapping[key] == slug]
            self.assertEqual((len(rows), len({row.group for row in rows})), expected)
        legacy = next(
            group for group in content.load_tache_two_equivalent_groups()
            if group.id == "travail-fete-collegue"
        )
        self.assertEqual(legacy.theme, "fetes")
        self.assertEqual(legacy.canonical, "tache2:octobre:batch-04:subject-17")
        self.assertEqual(set(legacy.members), {
            "tache2:octobre:batch-04:subject-17",
            "tache2:decembre:batch-10:subject-48",
        })

    def test_property_income_employment_and_actual_household_moves_stay_in_their_themes(self):
        _, mapping = catalogue.tache_two_subject_themes()
        expected = {
            "owner-holiday-letting-estate-agency-advice": "logement",
            "friend-association-work-experience": "travail",
            "help-friend-moving-day": "logement",
            "offered-room-in-existing-shared-apartment": "logement",
            "director-canada-fortnight-training": "travail",
        }
        found = set()
        for key, row in catalogue.tache_two_dialogues().items():
            if row.group in expected:
                self.assertEqual(mapping[key], expected[row.group], key)
                found.add(row.group)
        self.assertEqual(found, set(expected))

    def test_the_six_reclassified_models_keep_the_latest_reviewed_content(self):
        groups = set().union(*RECLASSIFIED_GROUPS.values())
        raw = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        snapshot = json.dumps(
            [raw[group] for group in sorted(groups)],
            ensure_ascii=False, sort_keys=True,
        ).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "213acc8af48532adec26daf90a811b4091898da02f13de1a4c0571b474a1fcee",
        )


class HousingWorkImportPreservationTests(TestCase):
    def test_import_twice_moves_themes_without_replacing_content_or_private_learning_data(self):
        call_command("import_content", stdout=StringIO())
        dialogues = catalogue.tache_two_dialogues()
        destinations = {
            key: slug for slug, groups in RECLASSIFIED_GROUPS.items()
            for key, row in dialogues.items() if row.group in groups
        }
        originals = {
            slug: Theme.objects.get(slug=f"tache-2-{slug}")
            for slug in ("logement", "travail")
        }
        prompts = list(Prompt.objects.filter(content_key__in=destinations).select_related("response"))
        for index, prompt in enumerate(prompts, 1):
            destination = destinations[prompt.content_key]
            original = originals["travail" if destination == "fetes" else "logement"]
            Prompt.objects.filter(pk=prompt.pk).update(theme=original, number=1_000_000 + index)
            Response.objects.filter(pk=prompt.response_id).update(theme=original)
        prompt_ids = dict(Prompt.objects.values_list("content_key", "pk"))
        response_ids = dict(Prompt.objects.filter(content_key__in=destinations).values_list(
            "content_key", "response_id",
        ))
        phrase_ids = dict(Phrase.objects.values_list("phrase_id", "pk"))
        user = factories.make_user("housing-work-reclassification")
        provision_user_study_data(user)
        records, cards = [], []
        seen = set()
        for groups in RECLASSIFIED_GROUPS.values():
            for group in sorted(groups):
                prompt = next(p for p in prompts if dialogues[p.content_key].group == group)
                if prompt.response_id in seen:
                    continue
                seen.add(prompt.response_id)
                card = Card.objects.get(user=user, response=prompt.response, card_type=CardType.SPINE)
                srs.review(card, Rating.GOOD)
                cards.append(card)
                records.extend([
                    card,
                    PersonalResponse.objects.create(
                        user=user, response=prompt.response, source_prompt=prompt,
                        nuance=f"My private note for {group}.",
                        conclusion="Mes questions personnelles.",
                    ),
                    Annotation.objects.create(
                        user=user, task=originals["logement"].task,
                        kind=AnnotationKind.HIGHLIGHT,
                        source_key=f"response:{prompt.response.content_key}:back",
                        source_path="/expression/orale/tache-2/",
                        quote="Mon passage appris.", start_offset=0, end_offset=18,
                        body=f"My saved highlight for {group}.", study_later=True,
                    ),
                ])
        bank = next(bank for bank in content.load_question_banks() if bank.number == 2)
        key = bank.question_keys[0]
        records.extend([
            MemoryQuestionProgress.objects.create(
                user=user, memory_number=2, question_key=key,
            ),
            PersonalQuestionResponse.objects.create(
                user=user, task=originals["logement"].task, question_key=key,
                body="My saved answer to an unchanged housing question.",
            ),
        ])
        before = [type(row).objects.filter(pk=row.pk).values().get() for row in records]
        reviews = list(ReviewLog.objects.filter(card__in=cards).values())

        call_command("import_content", stdout=StringIO())
        call_command("import_content", stdout=StringIO())

        self.assertEqual(dict(Prompt.objects.values_list("content_key", "pk")), prompt_ids)
        self.assertEqual(dict(Prompt.objects.filter(content_key__in=destinations).values_list(
            "content_key", "response_id",
        )), response_ids)
        self.assertEqual(dict(Phrase.objects.values_list("phrase_id", "pk")), phrase_ids)
        for row, expected in zip(records, before):
            self.assertEqual(type(row).objects.filter(pk=row.pk).values().get(), expected)
        self.assertEqual(list(ReviewLog.objects.filter(card__in=cards).values()), reviews)
        for prompt in Prompt.objects.filter(content_key__in=destinations).select_related(
            "theme", "response__theme",
        ):
            expected = f"tache-2-{destinations[prompt.content_key]}"
            self.assertEqual(prompt.theme.slug, expected)
            self.assertEqual(prompt.response.theme.slug, expected)
