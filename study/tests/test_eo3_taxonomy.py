from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from io import StringIO
import json
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils.html import escape

from study import catalogue, content_loader as content
from study.account_services import provision_user_study_data
from study.eo3_taxonomy import load_eo_tache_three_taxonomy
from study.models import Prompt, Response, Theme
from study.oral_highlights import AnnotationRootText
from study.routing import prompt_detail_url
from study.templatetags.study_links import subject_display_category
from study.views.library import _oral_subject_themes

from . import factories


class EO3TaxonomyTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.payload = json.loads(
            (content.CONTENT_DIR / "tache_3/subject_taxonomy.json").read_text()
        )

    def test_complete_immutable_partition_and_cache_lifecycle(self):
        taxonomy = catalogue.eo_tache_three_taxonomy()
        self.assertEqual((len(taxonomy.themes), len(taxonomy.by_group), len(taxonomy.by_source)),
                         (9, 131, 167))
        self.assertEqual(len({(v.theme.slug, v.slug) for v in taxonomy.by_group.values()}), 61)
        self.assertEqual(
            set(taxonomy.by_group),
            {response.semantic_group for response in content.parse_responses()},
        )
        self.assertIs(catalogue.eo_tache_three_taxonomy(), taxonomy)
        with self.assertRaises(TypeError):
            taxonomy.by_source["new"] = None
        with self.assertRaises(TypeError):
            taxonomy.by_group["new"] = None
        with self.assertRaises(FrozenInstanceError):
            taxonomy.themes[0].label = "Changed"
        catalogue.clear_catalogue_cache()
        self.assertIsNot(catalogue.eo_tache_three_taxonomy(), taxonomy)

    def test_failed_loads_are_not_cached(self):
        with patch("study.eo3_taxonomy.load_eo_tache_three_taxonomy",
                   side_effect=ValueError("Invalid manifest")) as load:
            for _ in range(2):
                with self.assertRaises(ValueError):
                    catalogue.eo_tache_three_taxonomy()
            self.assertEqual(load.call_count, 2)
        self.assertEqual(len(catalogue.eo_tache_three_taxonomy().by_source), 167)

    def test_row_labels_need_no_orm_relations_or_queries_for_any_task(self):
        taxonomy = catalogue.eo_tache_three_taxonomy()
        for key in ("culture:p6", "ee-tache-3:fixture", "tache2:fixture", "test:unknown"):
            prompt = Prompt(content_key=key)
            self.assertIs(subject_display_category(prompt), taxonomy.by_source.get(key))

    def test_requested_corrections_and_every_variant_share_the_group_category(self):
        taxonomy = catalogue.eo_tache_three_taxonomy()
        for key, theme in {
            "culture:p6": "education", "education:p8": "education",
            "education:p14": "culture", "education:p1": "immigration",
            "education:p5": "immigration",
        }.items():
            self.assertEqual(taxonomy.by_source[key].theme.slug, theme)
        for source in content.parse_responses():
            for prompt in source.prompts:
                self.assertIs(taxonomy.by_source[prompt.content_key],
                              taxonomy.by_group[source.semantic_group])

    def test_strict_manifest_rejects_invalid_structure_and_incomplete_partition(self):
        cases = []
        for field, value in (("version", True), ("version", 2), ("task", "wrong"),
                             ("themes", []), ("extra", True)):
            payload = deepcopy(self.payload)
            payload[field] = value
            cases.append(payload)
        for field, value in (("slug", "bad slug"), ("label", " "), ("order", True),
                             ("subthemes", []), ("extra", "invalid")):
            payload = deepcopy(self.payload)
            payload["themes"][0][field] = value
            cases.append(payload)
        for field, value in (("slug", "Bad"), ("label", ""), ("groups", []),
                             ("groups", ["eo/tache-3/unknown"]), ("extra", True)):
            payload = deepcopy(self.payload)
            payload["themes"][0]["subthemes"][0][field] = value
            cases.append(payload)
        missing = deepcopy(self.payload)
        missing["themes"][0]["subthemes"][0]["groups"].pop()
        cases.append(missing)
        duplicate = deepcopy(self.payload)
        duplicate["themes"][0]["subthemes"][1]["groups"].append(
            duplicate["themes"][0]["subthemes"][0]["groups"][0]
        )
        cases.append(duplicate)
        for payload in cases:
            with self.subTest(payload=str(payload)[:120]):
                with self.assertRaises(ValueError):
                    load_eo_tache_three_taxonomy(
                        Mock(read_text=Mock(return_value=json.dumps(payload)))
                    )
        with self.assertRaises(ValueError):
            load_eo_tache_three_taxonomy(
                Mock(read_text=Mock(return_value='{"version":1,"version":1}'))
            )


class EO3TaxonomyViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("taxonomy-owner")
        cls.other = factories.make_user("taxonomy-other")
        provision_user_study_data(cls.user)
        provision_user_study_data(cls.other)

    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.client.force_login(self.user)
        self.directory = reverse("study:task_browse", args=["eo", "tache-3"])

    def test_full_corpus_counts_categories_progress_and_query_free_grouping(self):
        self.assertEqual(
            Theme.objects.filter(task__part__slug="eo", task__slug="tache-3").count(), 7
        )
        prompt = Prompt.objects.get(content_key="culture:p6")
        self.client.post(
            reverse("study:subject_completion", args=["eo", "tache-3", prompt.response_id]),
            {"completed": "1"},
        )
        source_links = set()
        for deduplicate, count in (("1", 131), ("0", 167)):
            page = self.client.get(self.directory, {"deduplicate": deduplicate})
            self.assertEqual(page.status_code, 200)
            self.assertEqual(page.context["theme_count"], 9)
            self.assertEqual(page.context["prompt_count"], count)
            self.assertEqual(page.context["response_count"], 131)
            self.assertEqual(page.context["subject_summary"]["total"], 131)
            self.assertEqual(page.context["subject_summary"]["completed"], 1)
            groups = page.context["subject_themes"]
            self.assertEqual(sum(len(g["families"]) for g in groups), 61)
            self.assertEqual(sum(g["subject_count"] for g in groups), count)
            rows = [row for group in groups for row in group["subjects"]]
            for group in groups:
                for family in group["families"]:
                    for row in family["subjects"]:
                        category = catalogue.eo_tache_three_taxonomy().by_source[
                            row["prompt"].content_key
                        ]
                        self.assertEqual(category.theme.slug, group["slug"])
                        self.assertEqual(category.slug, family["slug"])
                        self.assertEqual(category.label, family["name"])
                        source_links.add(prompt_detail_url(row["prompt"]))
            if deduplicate == "0":
                with self.assertNumQueries(0):
                    _oral_subject_themes(
                        page.context["themes"],
                        {row["prompt"].response_id: row["progress"] for row in rows},
                        prompts=[row["prompt"] for row in rows],
                    )
        self.assertEqual(len(source_links), 167)
        overview = self.client.get(reverse("study:task_detail", args=["eo", "tache-3"]))
        self.assertEqual(overview.context["theme_count"], 9)
        self.assertEqual(overview.context["prompt_count"], 167)
        self.assertEqual(overview.context["response_stats"]["total"], 131)
        self.client.force_login(self.other)
        page = self.client.get(self.directory)
        self.assertEqual(page.context["subject_summary"]["completed"], 0)

    def test_unknown_fixture_keys_keep_source_categories_in_a_mixed_catalogue(self):
        source = Prompt.objects.select_related("theme", "family").get(content_key="culture:p6")
        Prompt.objects.create(
            content_key="synthetic:unlisted-taxonomy-subject",
            response=source.response, theme=source.theme, family=source.family,
            number=1000, text="Sujet synthétique hors du corpus.",
        )
        page = self.client.get(self.directory, {"deduplicate": "0"})
        rows = [
            row for group in page.context["subject_themes"] for row in group["subjects"]
            if row["prompt"].content_key == "synthetic:unlisted-taxonomy-subject"
        ]
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["display_category"])
        self.assertContains(page, escape(source.family.name))
        self.assertEqual(page.context["response_count"], 131)
        self.assertEqual(page.context["subject_summary"]["total"], 131)

    def test_breadcrumbs_search_and_annotation_root_preserve_source_content(self):
        taxonomy = catalogue.eo_tache_three_taxonomy()
        before = list(Response.objects.filter(semantic_group__startswith="eo/tache-3/")
                      .values_list("pk", "content_key", "theme_id", "family_id", "body"))
        prompt_fields = (
            "pk", "content_key", "theme_id", "family_id", "response_id", "number",
            "text", "model_content", "is_canonical",
        )
        prompt_sources = Prompt.objects.filter(theme__task__slug="tache-3",
                                                theme__task__part__slug="eo")
        before_prompts = list(prompt_sources.values_list(*prompt_fields))
        prompt = Prompt.objects.select_related(
            "theme__task__part", "family", "response",
        ).get(content_key="culture:p6")
        page = self.client.get(prompt_detail_url(prompt))
        category = taxonomy.by_source[prompt.content_key]
        self.assertContains(page, f"#theme-education-family-{category.slug}")
        self.assertEqual(page.context["eo3_display_category"], category)
        with patch("study.catalogue.eo_tache_three_taxonomy",
                   return_value=replace(taxonomy, by_source={})):
            old_display = self.client.get(prompt_detail_url(prompt))
        self.assertEqual(
            AnnotationRootText(page.content.decode()).text,
            AnnotationRootText(old_display.content.decode()).text,
        )
        search = self.client.get(
            reverse("study:task_search", args=["eo", "tache-3"]),
            {"q": prompt.text, "scope": "subjects", "deduplicate": "0"},
        )
        self.assertContains(search, escape(category.label))
        self.assertContains(search, "Source : Culture P6")
        self.assertEqual(
            before,
            list(Response.objects.filter(semantic_group__startswith="eo/tache-3/")
                 .values_list("pk", "content_key", "theme_id", "family_id", "body")),
        )
        self.assertEqual(before_prompts, list(prompt_sources.values_list(*prompt_fields)))
