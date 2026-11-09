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
