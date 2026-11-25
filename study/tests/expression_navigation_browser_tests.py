"""Opt-in browser coverage for metadata-only Expression navigation."""

import os

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from . import factories
from .browser_server import BrowserLiveServerThread


class ExpressionNavigationBrowserTests(StaticLiveServerTestCase):
    server_thread_class = BrowserLiveServerThread

    @classmethod
    def setUpClass(cls):
        cls.previous_async_unsafe = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()
        if cls.previous_async_unsafe is None:
            os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
        else:
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = cls.previous_async_unsafe

    def setUp(self):
        self.user = factories.make_user("expression-browser")
        for part in ("eo", "ee"):
            for number in (1, 2, 3):
                task = factories.make_task(factories.make_part(part), f"tache-{number}")
                task.subtitle = (
                    "Comparer des points de vue puis présenter et défendre sa propre opinion"
                    if number == 3 else f"Practice task {number}"
                )
                task.save(update_fields=["subtitle"])
            factories.make_spine_card(user=self.user, theme=factories.make_theme(f"{part}-landing", task=task))
        self.client.force_login(self.user)

    def context(self, javascript=True):
        context = self.browser.new_context(
            viewport={"width": 390, "height": 844},
            java_script_enabled=javascript, service_workers="block",
        )
        context.add_cookies([{
            "name": "sessionid", "value": self.client.cookies["sessionid"].value,
            "url": self.live_server_url,
        }])
        self.addCleanup(context.close)
        return context

    def test_navigation_has_no_statistics_or_background_request_with_or_without_javascript(self):
        for javascript in (False, True):
            context = self.context(javascript=javascript)
            for path in (reverse("study:expression"), "/expression/orale/", "/expression/ecrite/"):
                with self.subTest(javascript=javascript, path=path):
                    page = context.new_page()
                    batches = []
                    page.on("request", lambda request: batches.append(request.url) if "?stats=1" in request.url else None)
                    page.goto(self.live_server_url + path)
                    links = page.locator(".expression-path--available, .deck--task")
                    expect(links.first).to_be_visible()
                    links.first.focus()
                    self.assertEqual(page.locator(":focus").get_attribute("href"), links.first.get_attribute("href"))
                    expect(page.locator(".area-hero__metrics, .progress, [data-expression-stats]")).to_have_count(0)
                    self.assertNotIn("en chargement", page.locator("main").inner_text())
                    self.assertEqual(batches, [])
                    page.close()

    def test_compact_task_cards_keep_their_layout_with_a_saved_table_preference(self):
        context = self.context()
        context.add_init_script("localStorage.setItem('collectionViewMode', 'table')")
        page = context.new_page()
        for width in (320, 390, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            for part in ("orale", "ecrite"):
                with self.subTest(width=width, part=part):
                    page.goto(f"{self.live_server_url}/expression/{part}/")
                    cards = page.locator(".deck--task")
                    expect(cards).to_have_count(3)
                    icon_colors = cards.locator(".deck__icon .ui-icon").evaluate_all(
                        "icons => icons.map(icon => getComputedStyle(icon).color)"
                    )
                    self.assertEqual(len(set(icon_colors)), 3)
                    bounds = []
                    for index, card in enumerate(cards.all()):
                        expect(card).to_have_css("border-top-width", "0px")
                        expect(card.locator(".deck__subtitle")).to_be_visible()
                        arrow = card.locator(".deck__go")
                        expect(arrow).to_be_visible()
                        self.assertEqual(arrow.evaluate("el => getComputedStyle(el).borderTopWidth"), "0px")
                        bounds.append(card.bounding_box())
                        self.assertLessEqual(bounds[-1]["height"], 112 if width == 320 and index == 2 else 96)
                    if width == 1280:
                        self.assertAlmostEqual(bounds[0]["y"], bounds[2]["y"], delta=1)
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width,
                    )
                    self.assertEqual(page.evaluate("localStorage.getItem('collectionViewMode')"), "table")
                    expect(page.locator(".progress, .deck__meta")).to_have_count(0)

    def test_simulation_uses_the_compact_task_links_with_its_own_formats_and_destinations(self):
        page = self.context().new_page()
        tracks = (
            ("ee", ("60–120 mots", "120–150 mots", "120–180 mots"), "ee1_subject_picker"),
            ("eo", ("2 min + 3 min 30", "4 min 30 · sans préparation"), "eo2_topic_picker"),
        )
        for width in (320, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            for part, formats, picker in tracks:
                with self.subTest(width=width, part=part):
                    page.goto(self.live_server_url + reverse("study:simulation_track", args=[part]))
                    links = page.locator(".grid--tasks").get_by_role("link")
                    expect(links).to_have_count(len(formats))
                    for link, format_label in zip(links.all(), formats):
                        expect(link).to_contain_text(format_label)
                        expect(link).to_have_css("border-top-width", "0px")
                    first, last = links.first.bounding_box(), links.last.bounding_box()
                    if width == 1280:
                        self.assertAlmostEqual(first["y"], last["y"], delta=1)
                        self.assertLessEqual(last["height"], 72)
                    else:
                        self.assertGreater(last["y"], first["y"])
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                    links.first.focus()
                    expect(links.first.locator(".deck__go")).to_have_css("opacity", "1")
                    page.keyboard.press("Enter")
                    expect(page).to_have_url(self.live_server_url + reverse(f"study:{picker}"))

    def test_oral_task_two_keeps_cards_without_statistics_or_retired_practice(self):
        page = self.context().new_page()
        for width in (390, 1280):
            with self.subTest(width=width):
                page.set_viewport_size({"width": width, "height": 900})
                page.goto(f"{self.live_server_url}/expression/orale/tache-2/")
                panels = page.locator("[data-tache-two-overview-panel]")
                expect(panels).to_have_count(2)
                for panel in panels.all():
                    bounds = panel.bounding_box()
                    action = panel.locator(".tache-two-overview-panel__action").bounding_box()
                    self.assertGreaterEqual(bounds["height"], 200)
                    self.assertLess(bounds["x"] + bounds["width"] - action["x"] - action["width"], 24)
                expect(page.locator("[data-prompt-copy], .eo2-guidelines")).to_have_count(0)
                expect(page.locator(".tache-two-overview-panel__facts, .progress-summary")).to_have_count(0)
