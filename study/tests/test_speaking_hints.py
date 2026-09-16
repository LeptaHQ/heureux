import copy
import json
import re
from dataclasses import FrozenInstanceError, replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from study import catalogue
from study import content_loader as content
from study.account_services import provision_user_study_data
from study.models import Annotation, AnnotationKind, Card, CardType, PersonalResponse, Prompt
from study.routing import prompt_detail_url

from . import factories


def plan_cues(plan):
    return (
        plan.introduction,
        *(cue for argument in plan.arguments for cue in (argument.point, argument.example)),
        plan.nuance,
        plan.conclusion,
    )


class SpeakingHintsContentTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.responses = content.parse_responses()
        cls.payload = json.loads(content.TACHE_THREE_SUBJECT_HINTS_PATH.read_text(encoding="utf-8"))

    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def load(self, payload):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "hints.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return content.load_tache_three_subject_hints(path, responses=self.responses)

    def test_all_groups_have_distinct_compact_bilingual_plans(self):
        plans = content.load_tache_three_subject_hints(responses=self.responses)
        self.assertEqual(len(plans), 131)
        self.assertEqual(sum(len(response.prompts) for response in self.responses), 167)
        self.assertEqual(set(plans), {response.semantic_group for response in self.responses})
        self.assertEqual(len(set(plans.values())), len(plans))
        for identity, plan in plans.items():
            with self.subTest(group=identity):
                self.assertEqual(len(plan.arguments), 3)
                self.assertEqual(len(plan_cues(plan)), 9)
                self.assertLessEqual(sum(len(cue.french.split()) for cue in plan_cues(plan)), 140)
                for cue in plan_cues(plan):
                    self.assertNotEqual(cue.french.casefold(), cue.english.casefold())
                for language in ("french", "english"):
                    self.assertTrue(all(getattr(cue, language).strip() for cue in plan_cues(plan)))
                    for field in ("point", "example"):
                        self.assertEqual(
                            len({getattr(getattr(argument, field), language) for argument in plan.arguments}),
                            3,
                        )

    def test_semantic_identity_not_body_hash_selects_the_plan(self):
        plans = catalogue.tache_three_subject_hints()
        by_body = {}
        for response in self.responses:
            for prompt in response.prompts:
                by_body.setdefault(prompt.model_content["body_hash"], set()).add(response.semantic_group)
        split_models = [identities for identities in by_body.values() if len(identities) > 1]
        self.assertTrue(split_models)
        for identities in split_models:
            self.assertEqual(len({plans[identity] for identity in identities}), len(identities))

    def test_distinct_actors_and_question_scopes_are_preserved(self):
        plans = catalogue.tache_three_subject_hints()
        self.assertIn("adultes", plans["eo/tache-3/culture-p2"].introduction.french)
        self.assertIn("personnes âgées", plans["eo/tache-3/culture-p8"].introduction.french)
        self.assertIn("vendeur", plans["eo/tache-3/sante-p11"].introduction.french)
        self.assertIn("vente", plans["eo/tache-3/sante-p10"].introduction.french)
        self.assertNotIn(
            "téléphone fixe",
            " ".join(cue.french for cue in plan_cues(plans["eo/tache-3/technologie-p11"])),
        )
        country_plan = plans["eo/tache-3/environnement-p11"]
        self.assertIn("faits locaux vérifiés", country_plan.introduction.french)
        self.assertIn("réelle", country_plan.arguments[0].example.french)
        medical_plan = plans["eo/tache-3/sante-p23"]
        self.assertIn("sans avis médical", medical_plan.nuance.french)

    def test_plans_and_nested_arguments_are_cached_and_immutable(self):
        with patch.object(content, "load_tache_three_subject_hints", wraps=content.load_tache_three_subject_hints) as loader:
            plans = catalogue.tache_three_subject_hints()
            self.assertIs(catalogue.tache_three_subject_hints(), plans)
            loader.assert_called_once_with()
            key, plan = next(iter(plans.items()))
            with self.assertRaises(TypeError):
                plans[key] = plan
            with self.assertRaises(FrozenInstanceError):
                plan.introduction.french = "Changed"
            with self.assertRaises(FrozenInstanceError):
                plan.arguments[0].example.english = "Changed"
            catalogue.clear_catalogue_cache()
            self.assertEqual(catalogue.tache_three_subject_hints(), plans)
            self.assertEqual(loader.call_count, 2)

    def test_missing_unknown_and_duplicate_groups_are_rejected(self):
        for remove in (True, False):
            invalid = copy.deepcopy(self.payload)
            if remove:
                invalid["groups"].pop(next(iter(invalid["groups"])))
            else:
                invalid["groups"]["unknown-subject"] = next(iter(invalid["groups"].values()))
            with self.subTest(remove=remove), self.assertRaisesMessage(ValueError, "group coverage"):
                self.load(invalid)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "hints.json"
            with self.assertRaises(FileNotFoundError):
                content.load_tache_three_subject_hints(path, responses=self.responses)
            path.write_text('{"groups":{"culture-p1":{},"culture-p1":{}}}', encoding="utf-8")
            with self.assertRaisesMessage(ValueError, "Duplicate field"):
                content.load_tache_three_subject_hints(path, responses=self.responses)

    def test_rejects_wrong_tasks_sections_and_missing_examples(self):
        for field, value in (("version", True), ("version", 2), ("task", "ee/tache-3"), ("groups", [])):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load({**self.payload, field: value})
        for field in ("introduction", "arguments", "nuance", "conclusion"):
            invalid = copy.deepcopy(self.payload)
            next(iter(invalid["groups"].values())).pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load(invalid)
        for change in ("missing", "extra", "point-only", "duplicate-point", "duplicate-example"):
            invalid = copy.deepcopy(self.payload)
            arguments = next(iter(invalid["groups"].values()))["arguments"]
            if change == "missing":
                arguments.pop()
            elif change == "extra":
                arguments.append(copy.deepcopy(arguments[0]))
            elif change == "point-only":
                arguments[0].pop("example")
            else:
                field = change.removeprefix("duplicate-")
                arguments[1][field] = copy.deepcopy(arguments[0][field])
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.load(invalid)

    def test_rejects_blank_translations_overlong_cues_and_long_plans(self):
        for language in ("french", "english"):
            for value in (None, 1, "", " ", " Padded ", "Two\nlines", "A question ?"):
                invalid = copy.deepcopy(self.payload)
                next(iter(invalid["groups"].values()))["introduction"][language] = value
                with self.subTest(language=language, value=value), self.assertRaises(ValueError):
                    self.load(invalid)
            for field, limit in (("introduction", 170), ("nuance", 150), ("conclusion", 130), ("point", 120), ("example", 140)):
                invalid = copy.deepcopy(self.payload)
                plan = next(iter(invalid["groups"].values()))
                target = plan["arguments"][0] if field in ("point", "example") else plan
                target[field][language] = "x" * (limit + 1)
                with self.subTest(language=language, field=field), self.assertRaises(ValueError):
                    self.load(invalid)
        invalid = copy.deepcopy(self.payload)
        plan = next(iter(invalid["groups"].values()))
        for field in ("introduction", "nuance", "conclusion"):
            plan[field]["french"] = " ".join(["un"] * 40)
        with self.assertRaisesMessage(ValueError, "140 French words"):
            self.load(invalid)

    def test_rejects_invalid_source_groups_and_does_not_cache_failures(self):
        for sources in (
            [], self.responses * 2,
            [replace(self.responses[0], semantic_group="eo/tache-2/foreign")],
        ):
            with self.assertRaises(ValueError):
                content.load_tache_three_subject_hints(responses=sources)
        with patch.object(content, "load_tache_three_subject_hints", side_effect=ValueError("Invalid plan")) as loader:
            for _ in range(2):
                with self.assertRaisesMessage(ValueError, "Invalid plan"):
                    catalogue.tache_three_subject_hints()
            self.assertEqual(loader.call_count, 2)


class SpeakingHintsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("speaking-hints")
        provision_user_study_data(cls.user)

    def setUp(self):
        self.client.force_login(self.user)

    def prompt(self, key):
        return Prompt.objects.select_related("response", "theme__task__part").get(content_key=key)

    def test_equivalent_polarities_share_one_plan_without_replacing_their_models(self):
        canonical, alias = self.prompt("culture:p3"), self.prompt("economie:p5")
        self.assertEqual(canonical.response_id, alias.response_id)
        expected = catalogue.tache_three_subject_hints()[canonical.response.semantic_group]
        for prompt in (canonical, alias):
            for selection in ({}, {"deduplicate": "0"}):
                page = self.client.get(prompt_detail_url(prompt), selection)
                self.assertEqual(page.status_code, 200)
                self.assertIs(page.context["subject_hints"], expected)
                self.assertContains(page, "Exemple possible", count=3)
                self.assertContains(page, 'class="subject-hints__french"', count=9)
                self.assertContains(page, 'class="subject-hints__english"', count=9)
                self.assertEqual(
                    [argument.idea for argument in page.context["arguments"]],
                    [argument["idea"] for argument in prompt.model_content["arguments"]],
                )
                for key in ("model", "personal"):
                    self.assertEqual(self.client.get(prompt_detail_url(prompt), {key: "1"}).status_code, 404)

    def test_personal_responses_and_progress_do_not_change_the_shared_plan(self):
        prompt = self.prompt("culture:p3")
        personal = PersonalResponse.objects.create(
            user=self.user, response=prompt.response, source_prompt=prompt,
            position="Ma propre position", position_claire="Mon introduction personnelle.",
        )
        Card.objects.filter(user=self.user, response=prompt.response, card_type=CardType.SPINE).update(
            subject_completed_at=timezone.now(), reps=8,
        )
        mark = Annotation.objects.create(
            user=self.user, task=prompt.theme.task, kind=AnnotationKind.HIGHLIGHT,
            source_path=prompt_detail_url(prompt), source_key="subject-sidebar:culture:p3",
            quote="Progression du sujet", start_offset=0, end_offset=19,
        )
        before_personal = PersonalResponse.objects.filter(pk=personal.pk).values().get()
        before_cards = list(Card.objects.filter(user=self.user, response=prompt.response).values())
        before_mark = Annotation.objects.filter(pk=mark.pk).values().get()
        expected = catalogue.tache_three_subject_hints()[prompt.response.semantic_group]
        page = self.client.get(prompt_detail_url(prompt))
        self.assertContains(page, "Ma propre position")
        self.assertIs(page.context["subject_hints"], expected)
        self.assertTrue(page.context["subject_progress"].explicitly_completed)
        self.assertEqual(PersonalResponse.objects.filter(pk=personal.pk).values().get(), before_personal)
        self.assertEqual(list(Card.objects.filter(user=self.user, response=prompt.response).values()), before_cards)
        self.assertEqual(Annotation.objects.filter(pk=mark.pk).values().get(), before_mark)
        self.client.force_login(factories.make_user("other-speaking-hints"))
        other = self.client.get(prompt_detail_url(prompt))
        self.assertIs(other.context["subject_hints"], expected)
        self.assertNotContains(other, "Ma propre position")
        self.assertFalse(other.context["subject_progress"].explicitly_completed)

    def test_existing_annotated_sidebar_markup_remains_identical(self):
        url = prompt_detail_url(self.prompt("culture:p1"))
        page = self.client.get(url)
        with patch("study.views.library.catalogue.tache_three_subject_hints", return_value={}):
            baseline = self.client.get(url)

        def sidebar(response):
            match = re.search(r'<aside class="detail-side" data-annotation-root.*?</aside>', response.content.decode(), re.S)
            self.assertIsNotNone(match)
            return re.sub(r'(name="csrfmiddlewaretoken" value=")[^"]+', r'\1CSRF', match.group())

        self.assertEqual(sidebar(page), sidebar(baseline))
        self.assertNotIn("subject-hints", sidebar(page))
        self.assertContains(page, "Pratiquer cette réponse")
        self.assertContains(page, "Vocabulaire de ce sujet")
        self.assertContains(page, "data-subject-completion-form")

    def test_warm_hint_requests_do_not_reread_sources_or_add_queries(self):
        url = prompt_detail_url(self.prompt("culture:p1"))
        self.client.get(url)
        with patch.object(content, "load_tache_three_subject_hints", side_effect=AssertionError("Uncached hints")):
            with patch.object(content, "parse_responses", side_effect=AssertionError("Uncached source")):
                with CaptureQueriesContext(connection) as with_hints:
                    page = self.client.get(url)
                with patch("study.views.library.catalogue.tache_three_subject_hints", return_value={}):
                    with CaptureQueriesContext(connection) as without_hints:
                        self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(with_hints), len(without_hints))

    def test_other_tasks_and_nonbundled_responses_do_not_receive_eo3_hints(self):
        custom = factories.make_spine_card(
            user=self.user,
            theme=factories.make_theme(slug="adhoc-speaking-hints", task=factories.make_task()),
        )
        for identity in ("", "eo/tache-3/adhoc-speaking-hints"):
            custom.response.semantic_group = identity
            custom.response.save(update_fields=["semantic_group"])
            page = self.client.get(prompt_detail_url(custom.response.canonical_prompt))
            self.assertEqual(page.status_code, 200)
            self.assertNotContains(page, "subject-hints--speaking")
        writing = Prompt.objects.select_related("theme__task__part").filter(
            theme__task__part__slug="ee", theme__task__slug="tache-3", is_active=True,
        ).first()
        with patch("study.views.library.catalogue.tache_three_subject_hints", side_effect=AssertionError("EO3 lookup on EE")):
            page = self.client.get(prompt_detail_url(writing))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "subject-hints--speaking")
        self.assertContains(page, "Documents sources")
