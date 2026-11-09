"""Opt-in real-browser coverage for deferred Expression statistics."""

import os

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import Error as PlaywrightError, expect, sync_playwright

from . import factories
from .browser_server import BrowserLiveServerThread


class ExpressionStatsBrowserTests(StaticLiveServerTestCase):
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
            task = factories.make_task(factories.make_part(part), "tache-3")
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

    def test_navigation_is_ready_before_one_batch_and_focus_survives_resolution(self):
        context = self.context()
        for path in ("/expression/", "/expression/orale/", "/expression/ecrite/"):
            with self.subTest(path=path):
                page = context.new_page()
                pending = []
                page.route("**/*?stats=1", lambda route: pending.append(route))
                page.goto(self.live_server_url + path)
                expect(page.locator("[data-expression-stats-status]")).to_be_visible()
                links = page.locator("[data-expression-stats-content] a")
                expect(links.first).to_be_visible()
                href = links.first.get_attribute("href")
                links.first.focus()
                self.assertEqual(len(pending), 1)
                pending[0].continue_()
                expect(page.locator("[data-expression-stats-status]")).to_be_hidden()
                self.assertEqual(page.locator(":focus").get_attribute("href"), href)
                self.assertEqual(len(pending), 1)
                self.assertNotIn("en chargement", page.locator("[data-expression-stats-content]").inner_text())
                page.close()

    def test_failed_batch_keeps_navigation_and_retries_once_without_fake_progress(self):
        page = self.context().new_page()
        attempts = []

        def intercept(route):
            attempts.append(route)
            if len(attempts) == 1:
                route.fulfill(status=503, content_type="application/json", body='{"error":"unavailable"}')
            else:
                route.continue_()

        page.route("**/*?stats=1", intercept)
        page.goto(self.live_server_url + reverse("study:expression"))
        retry = page.get_by_role("button", name="Réessayer")
        expect(retry).to_be_visible()
        expect(page.get_by_text("La progression n’a pas pu être chargée.", exact=False)).to_be_visible()
        expect(page.locator("[data-expression-stats-content] a").first).to_be_visible()
        expect(page.get_by_text("Statistiques indisponibles").first).to_be_visible()
        self.assertNotIn("en chargement", page.locator("[data-expression-stats-content]").inner_text())
        self.assertNotIn("0/0", page.locator("[data-expression-stats-content]").inner_text())
        page.evaluate("""() => {
            const button = document.querySelector("[data-expression-stats-retry]");
            button.click();
            button.click();
        }""")
        expect(page.locator("[data-expression-stats-status]")).to_be_hidden()
        self.assertEqual(len(attempts), 2)

    def test_no_javascript_fallback_renders_real_statistics(self):
        page = self.context(javascript=False).new_page()
        page.goto(self.live_server_url + reverse("study:expression"))
        page.get_by_role("link", name="Afficher le contenu et la progression sans JavaScript").click()
        expect(page).to_have_url(self.live_server_url + "/expression/?stats=1")
        expect(page.locator("[data-expression-stats]")).to_have_count(0)
        expect(page.locator(".expression-path").first).to_be_visible()
        expect(page.locator("[data-expression-stats-metrics]")).not_to_contain_text("—")
        self.assertNotIn("en chargement", page.locator(".expression-paths").inner_text())

    def test_slow_batch_times_out_without_blocking_navigation(self):
        page = self.context().new_page()
        page.clock.install()
        pending = []
        page.route("**/*?stats=1", lambda route: pending.append(route))
        page.goto(self.live_server_url + "/expression/orale/")
        expect(page.locator("[data-expression-stats-content] a").first).to_be_visible()
        self.assertEqual(len(pending), 1)
        page.clock.fast_forward(30001)
        expect(page.get_by_role("button", name="Réessayer")).to_be_visible()
        expect(page.get_by_text("Statistiques indisponibles").first).to_be_visible()
        try:
            pending[0].abort()
        except PlaywrightError:
            pass
