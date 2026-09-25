"""Opt-in browser coverage using the project's existing Playwright setup."""

import os

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from study.models import Annotation, MemoryQuestionProgress
from . import factories
from .formulation_fixtures import formulation_catalog, mock_catalog


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class FormulationBrowserTests(StaticLiveServerTestCase):
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
        self.user = factories.make_user()
        self.task = factories.make_task(factories.make_part("ee"))
        theme = factories.make_theme("ee-tache-3-education", task=self.task)
        response = factories.make_response(theme=theme)
        self.catalog = formulation_catalog(response.content_key)
        self.mocks = mock_catalog(self.catalog)
        self.addCleanup(self.mocks.close)
        self.client.force_login(self.user)
        self.url = self.live_server_url + reverse("study:ee_formulations")

    def context(self, javascript=True):
        context = self.browser.new_context(
            viewport={"width": 390, "height": 844}, java_script_enabled=javascript,
            service_workers="block",
        )
        context.add_cookies([{
            "name": "sessionid", "value": self.client.cookies["sessionid"].value,
            "url": self.live_server_url,
        }])
        self.addCleanup(context.close)
        return context

    def test_list_copy_keyboard_recall_and_mobile_layout(self):
        context = self.context()
        context.add_init_script("""
            Object.defineProperty(navigator, "clipboard", {
              value: { writeText: async text => { window.copiedFormulation = text; } }
            });
        """)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(self.url)
        expect(page.locator(".formulation-directory-table")).to_have_count(2)
        expect(page.locator(".formulation-list")).to_have_count(0)
        subdivision = page.locator(
            '[data-formulation-subdivision]',
            has_text="Affirmation",
        )
        subdivision.locator("summary").click()
        expect(
            subdivision.locator("[data-formulation-topic-row] a"),
        ).to_have_count(2)
        subdivision.locator("[data-formulation-topic-row] a").first.click()
        expect(page.locator(".formulation-entry-lesson")).to_be_visible()
        expect(page.locator(".formulation-list")).to_have_count(0)
        expect(page.locator(".formulation-topic-sidebar")).to_have_count(0)
        expect(page.locator("[data-formulation-practice]")).to_have_count(0)
        page.locator("[data-prompt-copy]").first.click()
        self.assertEqual(page.evaluate("window.copiedFormulation"), self.catalog.entries[0].french)
        original_url = page.url
        page.get_by_role(
            "button", name="Je sais reproduire et adapter", exact=False,
        ).click()
        expect(page.get_by_role(
            "button", name="Remettre à apprendre", exact=False,
        )).to_be_visible()
        self.assertEqual(page.url, original_url)
        for width in (320, 390, 1280):
            page.set_viewport_size({"width": width, "height": 844})
            self.assertTrue(page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
            ))
        layout = page.locator(".formulation-entry-page").evaluate("""
            element => {
              const parent = element.parentElement;
              const parentStyle = getComputedStyle(parent);
              const expectedWidth = parent.clientWidth
                - parseFloat(parentStyle.paddingLeft)
                - parseFloat(parentStyle.paddingRight);
              return {
                width: element.getBoundingClientRect().width,
                expectedWidth,
                transform: getComputedStyle(element).transform,
              };
            }
        """)
        self.assertAlmostEqual(layout["width"], layout["expectedWidth"], delta=1)
        self.assertEqual(layout["transform"], "none")
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(self.live_server_url + reverse(
            "study:ee_formulation_function", args=["affirmation"],
        ))
        page.get_by_role("link", name="Pratiquer cette subdivision").click()
        expect(page.locator("[data-flashcard-front]")).to_be_visible()
        expect(page.locator("[data-flashcard-back]")).to_be_hidden()
        page.locator("[data-flashcard-card]").focus()
        page.keyboard.press("Space")
        expect(page.locator("[data-flashcard-back]")).to_be_visible()
        expect(page.locator("[data-flashcard-front]")).to_be_hidden()
        self.assertTrue(page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
        ))
        page.keyboard.press("ArrowRight")
        expect(page.locator("[data-formulation-practice]")).to_contain_text("Formulation 2 sur 2")
        expect(page.locator("[data-flashcard-front]")).to_be_visible()
        page.get_by_role("button", name="Je sais reproduire et adapter", exact=False).click()
        expect(page.get_by_role("button", name="Remettre à apprendre", exact=False)).to_be_visible()
        self.assertTrue(MemoryQuestionProgress.objects.filter(
            user=self.user, question_key=self.catalog.entries[1].content_key,
        ).exists())
        self.assertEqual(errors, [])

    def test_no_javascript_filters_disclosure_progress_and_next(self):
        page = self.context(javascript=False).new_page()
        page.goto(
            self.live_server_url
            + reverse("study:ee_formulation_function", args=["affirmation"])
        )
        page.get_by_role("searchbox", name="Rechercher").fill("PREVENTION")
        page.get_by_role("button", name="Rechercher", exact=True).click()
        expect(page.locator("#formulation-results-title")).to_have_text("2 formulations")
        page.get_by_role("link", name="Pratiquer cette subdivision").click()
        expect(page.locator("[data-flashcard-back]")).to_be_hidden()
        page.get_by_text("Révéler la formulation et l’exemple", exact=True).click()
        expect(page.locator("[data-flashcard-back]")).to_be_visible()
        page.get_by_role("button", name="Je sais reproduire et adapter", exact=False).click()
        self.assertIn("q=PREVENTION", page.url)
        expect(page.get_by_role("button", name="Remettre à apprendre", exact=False)).to_be_visible()
        page.get_by_role("link", name="Suivante", exact=True).click()
        expect(page.locator("[data-formulation-practice]")).to_contain_text("Formulation 2 sur 2")

    def test_language_checkmark_updates_without_navigation_and_persists(self):
        page = self.context().new_page()
        page.goto(self.live_server_url + reverse(
            "study:ee_formulation_language", args=["education"],
        ))
        original_url = page.url
        checkmark = page.get_by_role(
            "checkbox", name="Marquer comme apprise", exact=False,
        ).first
        expect(checkmark).to_have_attribute("aria-checked", "false")
        checkmark.click()
        checkmark = page.get_by_role(
            "checkbox", name="Remettre à apprendre", exact=False,
        ).first
        expect(checkmark).to_have_attribute("aria-checked", "true")
        expect(page.locator(".tache-two-subject-detail__meta")).to_contain_text(
            "1/",
        )
        self.assertEqual(page.url, original_url)
        page.reload()
        expect(page.get_by_role(
            "checkbox", name="Remettre à apprendre", exact=False,
        ).first).to_have_attribute("aria-checked", "true")

    def test_highlight_updates_lesson_status_without_navigation(self):
        page = self.context().new_page()
        page.goto(self.live_server_url + reverse(
            "study:ee_formulation_entry",
            args=[self.catalog.entries[0].slug],
        ))
        status = page.locator("[data-formulation-status]")
        expect(status).to_have_text("À apprendre")
        original_url = page.url
        page.locator(".formulation-entry-focus__text").evaluate("""
            element => {
              const selection = window.getSelection();
              const range = document.createRange();
              range.selectNodeContents(element);
              selection.removeAllRanges();
              selection.addRange(range);
              element.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
            }
        """)
        page.locator("[data-highlight-selection]").click()
        expect(status).to_have_text("En cours")
        expect(status).to_have_class(
            "progress-status progress-status--active",
        )
        self.assertEqual(page.url, original_url)
        self.assertTrue(Annotation.objects.filter(
            user=self.user,
            source_key=self.catalog.entries[0].content_key,
        ).exists())
        page.reload()
        expect(page.locator("[data-formulation-status]")).to_have_text(
            "En cours",
        )
