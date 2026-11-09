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
                task.subtitle = f"Practice task {number}"
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

    def test_pathway_cards_keep_their_design_with_a_saved_table_preference(self):
        context = self.context()
        context.add_init_script("localStorage.setItem('collectionViewMode', 'table')")
        page = context.new_page()
        for width in (390, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            for part in ("orale", "ecrite"):
                with self.subTest(width=width, part=part):
                    page.goto(f"{self.live_server_url}/expression/{part}/")
                    cards = page.locator(".deck--task")
                    expect(cards).to_have_count(3)
                    for card in cards.all():
                        expect(card.locator(".deck__subtitle")).to_be_visible()
                        expect(card.locator(".deck__go")).to_be_visible()
                        self.assertGreaterEqual(card.locator(".deck__icon").bounding_box()["width"], 44)
                        if width == 1280:
                            self.assertGreaterEqual(
                                card.evaluate("node => node.offsetHeight"), 264,
                                card.evaluate("node => ({minHeight: getComputedStyle(node).minHeight, root: getComputedStyle(document.documentElement).fontSize})"),
                            )
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width,
                    )
                    self.assertEqual(page.evaluate("localStorage.getItem('collectionViewMode')"), "table")
                    expect(page.locator(".progress, .deck__meta")).to_have_count(0)

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
