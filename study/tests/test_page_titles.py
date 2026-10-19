"""Browser-tab titles follow one format: ``Page · Context · Heureux``."""

import html
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from study.card_presentation import scope_title_segments
from study.models import ComprehensionMode
from study.routing import response_detail_url

from . import factories

TITLE_BLOCK = re.compile(r"{% block title %}(.*?){% endblock %}", re.DOTALL)
TITLE_TAG = re.compile(r"<title>(.*?)</title>", re.DOTALL)
BASE_TEMPLATES = {"base.html", "auth/base.html"}


def rendered_title(response):
    match = TITLE_TAG.search(response.content.decode())
    return html.unescape(match.group(1)).strip() if match else None


class TitleTemplateTests(TestCase):
    def test_every_title_names_the_page_and_ends_with_the_site(self):
        roots = [Path(settings.BASE_DIR) / "templates", Path(settings.BASE_DIR) / "study" / "templates"]
        blocks = {}
        for root in roots:
            for path in root.rglob("*.html"):
                for block in TITLE_BLOCK.findall(path.read_text()):
                    blocks[str(path.relative_to(root))] = block
        self.assertGreater(len(blocks), 50)
        for name, block in blocks.items():
            with self.subTest(template=name):
                if name.removeprefix("study/") in BASE_TEMPLATES:
                    self.assertEqual(block, "Heureux")
                    continue
                self.assertTrue(block.endswith(" · Heureux"), block)
                self.assertNotIn("truncatechars", block)
                self.assertNotIn("task.name", block)


class RenderedTitleTests(TestCase):
    def setUp(self):
        self.user = factories.make_user()
        self.part = factories.make_part("eo")
        self.task = factories.make_task(self.part, "tache-3")
        self.theme = factories.make_theme("culture", task=self.task)
        self.response = factories.make_response(theme=self.theme)
        self.client.force_login(self.user)
        self.task_label = self.task.short_label

    def assertTitle(self, url, expected):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(rendered_title(response), expected)

    def test_task_label_names_the_exam_part(self):
        self.assertEqual(self.task_label, f"EO {self.task.name}")

    def test_subject_page_titles_use_the_subject_position_not_the_prompt(self):
        self.assertTitle(
            response_detail_url(self.response),
            f"Sujet 1 · Culture · {self.task_label} · Heureux",
        )

    def test_scoped_pages_name_their_task_or_part(self):
        cases = (
            (reverse("study:stats"), "Progression · Heureux"),
            (
                reverse("study:part_stats", args=[self.part.slug]),
                "Progression · Expression orale · Heureux",
            ),
            (
                reverse("study:task_stats", args=[self.part.slug, self.task.slug]),
                f"Progression · {self.task_label} · Heureux",
            ),
            (
                reverse("study:task_notes", args=[self.part.slug, self.task.slug]),
                f"Notes · {self.task_label} · Heureux",
            ),
            (
                reverse(
                    "study:task_annotation_study",
                    args=[self.part.slug, self.task.slug],
                ),
                f"Flashcards · Notes · {self.task_label} · Heureux",
            ),
            (reverse("study:custom_notes"), "Notes personnelles · Notes · Heureux"),
        )
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertTitle(url, expected)

    def test_review_titles_name_the_deck_and_its_task(self):
        cases = (
            (
                reverse("study:task_review", args=[self.part.slug, self.task.slug])
                + "?kind=spine&theme=culture",
                f"Révision · Culture · {self.task_label} · Heureux",
            ),
            (
                reverse("study:part_review", args=[self.part.slug]) + "?kind=spine",
                "Révision · Expression orale · Heureux",
            ),
            (
                reverse("study:review") + "?kind=weak&content=spine",
                "Révision · Points à renforcer · Heureux",
            ),
        )
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertTitle(url, expected)

    def test_review_title_segments_for_vocabulary_decks(self):
        test = factories.make_comprehension_test(mode=ComprehensionMode.ORALE)
        self.assertEqual(
            scope_title_segments({"kind": "vocab", "test": test.slug, "batch": 2}),
            ["Révision du vocabulaire", test.title, "Compréhension orale"],
        )
        self.assertEqual(
            scope_title_segments({
                "part": self.part.slug,
                "task": self.task.slug,
                "kind": "revisit",
            }),
            ["Révision", "Liste à revoir", self.task_label],
        )
        self.assertEqual(scope_title_segments({}), ["Révision"])
