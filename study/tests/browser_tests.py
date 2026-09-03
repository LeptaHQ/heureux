from __future__ import annotations

import json
import os
from unittest import mock

from django.contrib.sessions.models import Session
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from django.utils import timezone

from study import content_loader as content
from study.content_loader import load_sections
from study.management.commands.import_content import Command
from study.models import (
    Annotation,
    AnnotationKind,
    CardState,
    CardType,
    ComprehensionMode,
    ComprehensionQuestionStudy,
    PhraseCategory,
    PhraseTier,
    PersonalResponse,
    Rating,
    ReviewLog,
    ReviewSession,
    Task,
)
from study.routing import response_detail_url, theme_detail_url

from . import factories


@override_settings(
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]
)
class BrowserTests(StaticLiveServerTestCase):
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
        self.user = factories.make_user("browser-user", pin="482731")
        self.part = factories.make_part("eo")
        self.task = factories.make_task(self.part, "tache-3")
        self.theme = factories.make_theme("culture", task=self.task)
        self.first = factories.make_spine_card(
            user=self.user,
            theme=self.theme,
        )
        self.second = factories.make_spine_card(
            user=self.user,
            theme=self.theme,
        )
        self.context = self.browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
            service_workers="block",
        )
        self.page = self.context.new_page()
        self.page.goto(self.live_server_url + reverse("study:login"))
        self.page.locator("#id_username").fill("browser-user")
        self.page.locator("#id_pin").fill("482731")
        self.page.get_by_role("button", name="Continuer").click()
        self.page.wait_for_url(self.live_server_url + "/")

    def tearDown(self):
        self.context.close()

    def disable_service_worker(self):
        """Serve assets straight from the live server for this page.

        The cached app shell can race a freshly versioned script, which makes
        progressive-enhancement assertions flaky without changing behavior.
        """
        self.page.evaluate(
            """
            () => {
              if (!navigator.serviceWorker) return null;
              return navigator.serviceWorker
                .getRegistrations()
                .then(registrations => Promise.all(
                  registrations.map(registration => registration.unregister())
                ))
                .then(() => null);
            }
            """
        )

    def open_new_tab(self, click):
        """Run ``click`` and return the tab it opens, sized like the current one."""
        viewport = self.page.viewport_size
        with self.context.expect_page() as popup:
            click()
        opened = popup.value
        if viewport:
            opened.set_viewport_size(viewport)
        opened.wait_for_load_state()
        return opened

    def follow_new_tab_link(self, name, **kwargs):
        """Click an exercise link and continue in the tab it opens.

        Exercise rows use ``target="_blank"``, so the assertions that follow
        belong to the popup rather than the page that was clicked.
        """
        self.page = self.open_new_tab(
            lambda: self.page.get_by_role("link", name=name, **kwargs).click()
        )
        return self.page

    def assert_opens_new_tab(self, click, path, follow=False):
        """Assert a row hit area opens ``path`` in its own tab."""
        opened = self.open_new_tab(click)
        self.assertEqual(opened.url, self.live_server_url + path)
        if follow:
            self.page = opened
            return opened
        opened.close()
        return None

    def assert_no_horizontal_overflow(self):
        fits = self.page.evaluate(
            "document.documentElement.scrollWidth <= "
            "document.documentElement.clientWidth + 1"
        )
        overflowing = self.page.locator("body *").evaluate_all(
            """
            elements => {
              const viewportWidth = document.documentElement.clientWidth;
              return elements
              .map(element => {
                const rect = element.getBoundingClientRect();
                return {
                  tag: element.tagName,
                  className: element.className,
                  text: (element.textContent || "").trim().slice(0, 80),
                  left: Math.round(rect.left),
                  right: Math.round(rect.right),
                  width: Math.round(rect.width),
                  overflow: Math.max(
                    rect.right - viewportWidth,
                    -rect.left,
                    0
                  ),
                };
              })
              .filter(item => item.overflow > 1)
              .sort((left, right) => right.overflow - left.overflow)
              .slice(0, 6);
            }
            """
        )
        self.assertTrue(fits, f"{self.page.url}: {overflowing}")

    def touch_swipe(self, locator, from_x, to_x, y):
        locator.evaluate(
            """
            (element, points) => {
              const event = (type, x, buttons) => new PointerEvent(type, {
                bubbles: true,
                cancelable: true,
                pointerId: 91,
                pointerType: "touch",
                isPrimary: true,
                button: 0,
                buttons,
                clientX: x,
                clientY: points.y,
              });
              element.dispatchEvent(event("pointerdown", points.fromX, 1));
              for (let step = 1; step <= 5; step += 1) {
                const x = points.fromX
                  + ((points.toX - points.fromX) * step / 5);
                element.dispatchEvent(event("pointermove", x, 1));
              }
              element.dispatchEvent(event("pointerup", points.toX, 0));
            }
            """,
            {"fromX": from_x, "toX": to_x, "y": y},
        )
        self.page.wait_for_timeout(250)

    def _import_ee_tache_three_content(self):
        command = Command()
        months = content.load_ee_tache_three_months()
        task_by_slug = command._import_sections(load_sections())
        theme_by_name = command._import_themes(
            content.ee_tache_three_themes(months),
            task_by_slug,
        )
        family_by_name = command._import_families(
            content.ee_tache_three_families(months)
        )
        responses = content.parse_ee_tache_three_responses(months)
        response_by_key = command._import_responses(
            responses,
            theme_by_name,
            family_by_name,
        )
        command._import_prompts(
            responses,
            response_by_key,
            theme_by_name,
            family_by_name,
        )
        task = task_by_slug["ee/tache-3"]
        return months, task

    def _import_ee_writing_content(self):
        command = Command()
        task_by_slug = command._import_sections(load_sections())
        for tache in (1, 2):
            command._import_writing_sujets(
                content.load_ee_writing_categories(tache),
                task_by_slug,
                task_key=f"ee/tache-{tache}",
            )
        return {
            tache: task_by_slug[f"ee/tache-{tache}"]
            for tache in (1, 2)
        }

    def _import_eo_tache_two_content(self):
        command = Command()
        task_by_slug = command._import_sections(load_sections())
        months = content.load_tache_two_subject_months()
        theme_by_name = command._import_themes(
            content.tache_two_themes(months),
            task_by_slug,
        )
        family_by_name = command._import_families(
            content.tache_two_families(months)
        )
        responses = content.parse_tache_two_responses(months)
        response_by_key = command._import_responses(
            responses,
            theme_by_name,
            family_by_name,
        )
        prompt_index = command._import_prompts(
            responses,
            response_by_key,
            theme_by_name,
            family_by_name,
        )
        command._import_phrases(
            content.parse_tache_two_theme_vocabulary(responses),
            prompt_index,
        )
        command._sync_cards(response_by_key, user=self.user)
        return task_by_slug["eo/tache-2"]

    def test_ee_tache_three_overview_table_has_bounded_hover_content(self):
        _, task = self._import_ee_tache_three_content()
        overview_url = reverse(
            "study:task_detail",
            args=[task.part.slug, task.slug],
        )

        self.page.set_viewport_size({"width": 1183, "height": 844})
        self.page.goto(
            self.live_server_url + reverse("study:dashboard")
        )
        spotlight = self.page.locator(".home-spotlight")
        spotlight.hover()
        self.assertEqual(
            spotlight.evaluate(
                "entry => getComputedStyle(entry).textDecorationLine"
            ),
            "none",
        )
        self.page.goto(self.live_server_url + overview_url)
        self.page.get_by_role("button", name="Tableau").click()
        overview_entries = self.page.locator(
            "[data-ee-tache-three-overview-entry]"
        )
        overview_entries.first.hover()
        self.assertEqual(
            overview_entries.first.evaluate(
                "entry => getComputedStyle(entry).textDecorationLine"
            ),
            "none",
        )
        overflowing_cells = overview_entries.evaluate_all(
            """
            entries => entries.flatMap(entry =>
              [...entry.children]
                .filter(cell => cell.scrollWidth > cell.clientWidth + 1)
                .map(cell => ({
                  className: cell.className,
                  clientWidth: cell.clientWidth,
                  scrollWidth: cell.scrollWidth,
                }))
            )
            """
        )
        self.assertEqual(overflowing_cells, [])
        self.assert_no_horizontal_overflow()

    def test_ee_tache_three_theme_directory_is_collapsible_and_responsive(self):
        _months, task = self._import_ee_tache_three_content()
        themes = content.load_ee_subject_themes(3)[0]
        overview_url = reverse(
            "study:task_detail",
            args=[task.part.slug, task.slug],
        )
        subjects_url = reverse(
            "study:task_browse",
            args=[task.part.slug, task.slug],
        )

        self.page.goto(self.live_server_url + overview_url)

        self.assertEqual(
            self.page.locator(
                "[data-ee-tache-three-overview-entry]"
            ).count(),
            2,
        )
        self.assertEqual(
            self.page.locator(".ee-t3-month-group").count(),
            0,
        )
        self.page.get_by_role("button", name="Tableau").click()
        self.assertEqual(
            self.page.locator("html").get_attribute(
                "data-collection-view-mode"
            ),
            "table",
        )

        self.page.goto(self.live_server_url + subjects_url)

        self.assertEqual(
            self.page.locator("html").get_attribute(
                "data-collection-view-mode"
            ),
            "table",
        )
        self.assertEqual(
            self.page.locator("[data-t1-table-theme]").count(),
            len(themes),
        )
        self.assertEqual(
            self.page.locator(
                "[data-collection-view-panel='table'] "
                "[data-ee-tache-three-subject-row]:visible"
            ).count(),
            0,
        )
        self.assertEqual(
            self.page.get_by_text("Par famille de sujets").count(),
            0,
        )
        first_theme = self.page.locator("[data-t1-table-theme]").first
        first_theme.locator("summary").click()
        self.assertEqual(
            first_theme.get_attribute("open"),
            "",
        )
        self.assertGreater(
            first_theme.locator(
                "[data-ee-tache-three-subject-row]:visible"
            ).count(),
            0,
        )
        first_table = first_theme.locator("[data-nested-sort-table]")
        first_rows = first_table.locator("[data-nested-sort-row]")
        original_titles = first_rows.locator(
            ".subject-table-row-link"
        ).all_inner_texts()
        subject_sort = first_table.locator(
            '[data-nested-table-sort="subject"]'
        )
        subject_sort.click()
        expected_titles = self.page.evaluate(
            """
            values => values.slice().sort(
              new Intl.Collator("fr", {
                sensitivity: "base",
                numeric: true,
              }).compare
            )
            """,
            original_titles,
        )
        self.assertEqual(
            first_rows.locator(".subject-table-row-link").all_inner_texts(),
            expected_titles,
        )
        self.assertEqual(
            subject_sort.locator("xpath=..").get_attribute("aria-sort"),
            "ascending",
        )
        self.assert_no_horizontal_overflow()

        for width in (390, 1024):
            with self.subTest(width=width):
                self.page.set_viewport_size(
                    {"width": width, "height": 844}
                )
                self.assert_no_horizontal_overflow()
                if width == 390:
                    nav_rows = self.page.locator(
                        ".task-nav--ee-t3 a"
                    ).evaluate_all(
                        "links => new Set("
                        "links.map(link => Math.round("
                        "link.getBoundingClientRect().top"
                        "))).size"
                    )
                    self.assertEqual(nav_rows, 1)

        self.page.get_by_role("button", name="Cartes").click()
        self.assertEqual(
            self.page.locator("html").get_attribute(
                "data-collection-view-mode"
            ),
            "cards",
        )
        self.assert_no_horizontal_overflow()

        self.page.set_viewport_size({"width": 1024, "height": 844})
        self.page.get_by_role("button", name="Tableau").click()
        first_theme = self.page.locator("[data-t1-table-theme]").first
        if first_theme.get_attribute("open") is None:
            first_theme.locator("summary").click()
        first_row = first_theme.locator(
            "[data-ee-tache-three-subject-row]:visible"
        ).first
        completion = first_row.locator(
            "[data-subject-completion-form] button"
        )
        response_id = first_row.get_attribute("data-subject-progress-row")
        progress_buttons = self.page.locator(
            f'[data-subject-progress-row="{response_id}"] '
            "[data-subject-completion-form] button"
        )
        expected_checked = progress_buttons.count()
        self.assertTrue(
            completion.evaluate(
                """
                button => Boolean(button.form.querySelector(
                  "input[name='csrfmiddlewaretoken']"
                ))
                """
            )
        )
        with self.page.expect_response(
            lambda response: "/progression/" in response.url
        ) as completion_response:
            completion.click()
        self.assertTrue(completion_response.value.ok)
        self.page.wait_for_function(
            """
            expected => document.querySelectorAll(
              '[data-subject-completion-form] '
              + 'button[aria-checked="true"]'
            ).length === expected
            """,
            arg=expected_checked,
        )
        self.assertEqual(self.page.url, self.live_server_url + subjects_url)
        self.assertEqual(
            self.page.locator(
                '[data-subject-completion-form] '
                'button[aria-checked="true"]'
            ).count(),
            expected_checked,
        )

        first_theme = self.page.locator("[data-t1-table-theme]").first
        if first_theme.get_attribute("open") is None:
            first_theme.locator("summary").click()
        first_row = first_theme.locator(
            "[data-ee-tache-three-subject-row]:visible"
        ).first
        subject_link = first_row.locator(".subject-table-row-link")
        detail_path = subject_link.get_attribute("href")
        self.assert_opens_new_tab(
            subject_link.click,
            detail_path,
        )

    def test_ee_writing_tables_reuse_scoped_sorting_on_mobile(self):
        tasks = self._import_ee_writing_content()

        for tache, task in tasks.items():
            with self.subTest(tache=tache):
                subjects_url = reverse(
                    "study:task_browse",
                    args=[task.part.slug, task.slug],
                )
                self.page.set_viewport_size(
                    {"width": 1183, "height": 844}
                )
                self.page.goto(self.live_server_url + subjects_url)
                if (
                    self.page.locator("html").get_attribute(
                        "data-collection-view-mode"
                    )
                    != "table"
                ):
                    self.page.get_by_role("button", name="Tableau").click()

                groups = self.page.locator("[data-t1-table-theme]")
                self.assertEqual(groups.count(), 11)
                first_group = groups.first
                second_group = groups.nth(1)
                first_group.locator("summary").click()
                first_table = first_group.locator(
                    "[data-nested-sort-table]"
                )
                first_rows = first_table.locator("[data-nested-sort-row]")
                second_titles_before = second_group.locator(
                    "[data-nested-sort-row] .subject-table-row-link"
                ).all_inner_texts()
                original_titles = first_rows.locator(
                    ".subject-table-row-link"
                ).all_inner_texts()

                subject_sort = first_table.locator(
                    '[data-nested-table-sort="subject"]'
                )
                subject_sort.click()
                expected_titles = self.page.evaluate(
                    """
                    values => values.slice().sort(
                      new Intl.Collator("fr", {
                        sensitivity: "base",
                        numeric: true,
                      }).compare
                    )
                    """,
                    original_titles,
                )
                self.assertEqual(
                    first_rows.locator(
                        ".subject-table-row-link"
                    ).all_inner_texts(),
                    expected_titles,
                )
                self.assertEqual(
                    subject_sort.locator("xpath=..").get_attribute(
                        "aria-sort"
                    ),
                    "ascending",
                )

                first_rows.evaluate_all(
                    """
                    rows => rows.forEach(row => {
                      const status = row.querySelector(
                        "[data-writing-sujet-progress-status]"
                      );
                      status.classList.remove(
                        "progress-status--done",
                        "progress-status--active"
                      );
                      status.classList.add("progress-status--new");
                    })
                    """
                )
                progress_target = first_rows.last
                progress_target.evaluate(
                    """
                    row => {
                      row.dataset.sortTestTarget = "true";
                      const status = row.querySelector(
                        "[data-writing-sujet-progress-status]"
                      );
                      status.classList.remove("progress-status--new");
                      status.classList.add("progress-status--done");
                    }
                    """
                )
                progress_sort = first_table.locator(
                    '[data-nested-table-sort="progress"]'
                )
                progress_sort.click()
                self.assertEqual(
                    first_rows.first.get_attribute("data-sort-test-target"),
                    "true",
                )
                self.assertEqual(
                    progress_sort.locator("xpath=..").get_attribute(
                        "aria-sort"
                    ),
                    "descending",
                )
                self.assertEqual(
                    second_group.locator(
                        "[data-nested-sort-row] .subject-table-row-link"
                    ).all_inner_texts(),
                    second_titles_before,
                )

                self.page.set_viewport_size(
                    {"width": 320, "height": 700}
                )
                self.assertFalse(
                    first_group.locator(".t1-table-shell").evaluate(
                        "element => "
                        "element.scrollWidth > element.clientWidth"
                    )
                )
                self.assert_no_horizontal_overflow()

    def test_ee_tache_one_rows_navigate_without_completion_click_through(self):
        ee_part = factories.make_part("ee")
        writing_task = factories.make_task(ee_part, "tache-1")
        sujet = factories.make_writing_sujet(
            writing_task,
            slug="invitation-chateau",
            category="invitations",
            category_label="Invitations",
            prompt="Invitez Cédric au château.",
            versions=("Bonjour Cédric, venez visiter le château.",),
        )
        subjects_path = reverse(
            "study:task_browse",
            args=["ee", "tache-1"],
        )
        detail_path = reverse(
            "study:writing_sujet_detail",
            args=["ee", "tache-1", sujet.pk],
        )

        self.page.set_viewport_size({"width": 1183, "height": 844})
        self.page.goto(self.live_server_url + subjects_path)
        card_row = self.page.locator(
            f'.t1-row:has(a[href="{detail_path}"])'
        ).first
        completion = card_row.locator(
            "[data-writing-sujet-completion-form] button"
        )
        with self.page.expect_response(
            lambda response: "/progression/" in response.url
        ) as completion_response:
            completion.click()
        self.assertTrue(completion_response.value.ok)
        self.page.wait_for_function(
            """
            () => document.querySelectorAll(
              '[data-writing-sujet-completion-form] '
              + 'button[aria-checked="true"]'
            ).length === 2
            """
        )
        self.assertEqual(self.page.url, self.live_server_url + subjects_path)
        self.assertEqual(
            self.page.locator(
                '[data-writing-sujet-completion-form] '
                'button[aria-checked="true"]'
            ).count(),
            2,
        )

        card_row = self.page.locator(
            f'.t1-row:has(a[href="{detail_path}"])'
        ).first
        status = card_row.locator(".progress-status").bounding_box()
        self.assert_opens_new_tab(
            lambda: self.page.mouse.click(
                status["x"] + status["width"] / 2,
                status["y"] + status["height"] / 2,
            ),
            detail_path,
        )

        self.page.goto(self.live_server_url + subjects_path)
        self.page.get_by_role("button", name="Tableau").click()
        table_group = self.page.locator(
            f'[data-t1-table-theme]:has(a[href="{detail_path}"])'
        )
        self.assertFalse(table_group.evaluate("group => group.open"))
        table_group.locator("summary").click()
        table_row = table_group.locator(
            f'[data-t1-table-subject]:has(a.subject-table-row-link[href="{detail_path}"])'
        )
        completion = table_row.locator(
            "[data-writing-sujet-completion-form] button"
        )
        with self.page.expect_response(
            lambda response: "/progression/" in response.url
        ) as completion_response:
            completion.click()
        self.assertTrue(completion_response.value.ok)
        self.page.wait_for_function(
            """
            () => document.querySelectorAll(
              '[data-writing-sujet-completion-form] '
              + 'button[aria-checked="true"]'
            ).length === 0
            """
        )
        self.assertEqual(self.page.url, self.live_server_url + subjects_path)
        self.assertEqual(
            self.page.locator(
                '[data-writing-sujet-completion-form] '
                'button[aria-checked="true"]'
            ).count(),
            0,
        )

        table_group = self.page.locator(
            f'[data-t1-table-theme]:has(a[href="{detail_path}"])'
        )
        if not table_group.evaluate("group => group.open"):
            table_group.locator("summary").click()
        table_row = table_group.locator(
            f'[data-t1-table-subject]:has(a.subject-table-row-link[href="{detail_path}"])'
        )
        content_cell = table_row.locator("td").nth(1).bounding_box()
        self.assert_opens_new_tab(
            lambda: self.page.mouse.click(
                content_cell["x"] + content_cell["width"] / 2,
                content_cell["y"] + content_cell["height"] / 2,
            ),
            detail_path,
            follow=True,
        )

        response_body = self.page.locator(
            f'[data-annotation-source-key="writing-sujet:{sujet.pk}:model-1"]'
        )
        response_body.evaluate(
            """
            element => {
              const range = document.createRange();
              range.selectNodeContents(element);
              const selection = window.getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              document.dispatchEvent(new Event("selectionchange"));
            }
            """
        )
        highlight_button = self.page.locator("[data-highlight-selection]")
        highlight_button.wait_for(state="visible")
        with self.page.expect_response(
            lambda response: reverse("study:annotation_create") in response.url
        ) as highlight_response:
            highlight_button.click()
        self.assertIn(highlight_response.value.status, (200, 201))
        self.page.locator(
            f'[data-writing-sujet-progress-status="{sujet.pk}"]',
            has_text="En cours",
        ).wait_for()

    def test_primary_navigation_is_structured_on_mobile_and_desktop(self):
        self.page.set_viewport_size({"width": 320, "height": 568})
        toggle = self.page.get_by_role("button", name="Ouvrir le menu")

        toggle.click()

        navigation = self.page.locator("#primary-navigation")
        navigation.get_by_text("Apprendre", exact=True).wait_for()
        navigation.get_by_text("Mes outils", exact=True).wait_for()
        self.assertEqual(
            navigation.locator(".nav__primary-link").count(),
            5,
        )
        self.assertEqual(
            navigation.get_by_role(
                "link",
                name="Accueil",
                exact=True,
            ).get_attribute("aria-current"),
            "page",
        )
        mobile_active_style = navigation.get_by_role(
            "link",
            name="Accueil",
            exact=True,
        ).evaluate(
            """
            element => {
              const style = getComputedStyle(element);
              return {
                background: style.backgroundColor,
                borderLeftWidth: style.borderLeftWidth,
                borderRadius: style.borderRadius,
              };
            }
            """
        )
        self.assertEqual(mobile_active_style["background"], "rgba(0, 0, 0, 0)")
        self.assertEqual(mobile_active_style["borderLeftWidth"], "3px")
        self.assertEqual(mobile_active_style["borderRadius"], "0px"        )
        navigation.get_by_text("Vue d'ensemble", exact=True).wait_for()
        navigation.get_by_text("Notes et surlignages", exact=True).wait_for()
        navigation.get_by_text("Suivre mes progrès", exact=True).wait_for()
        self.assert_no_horizontal_overflow()

        self.page.keyboard.press("Escape")
        navigation.wait_for(state="hidden")
        self.assertEqual(toggle.get_attribute("aria-expanded"), "false")

        for width in (761, 800, 900, 901, 1024):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 768})
                navigation.get_by_role(
                    "link",
                    name="Notes",
                    exact=True,
                ).wait_for()
                self.assertFalse(toggle.is_visible())
                self.assert_no_horizontal_overflow()
        desktop_active_style = navigation.get_by_role(
            "link",
            name="Accueil",
            exact=True,
        ).evaluate(
            """
            element => {
              const style = getComputedStyle(element);
              return {
                background: style.backgroundColor,
                borderBottomWidth: style.borderBottomWidth,
                borderRadius: style.borderRadius,
              };
            }
            """
        )
        self.assertEqual(desktop_active_style["background"], "rgba(0, 0, 0, 0)")
        self.assertEqual(desktop_active_style["borderBottomWidth"], "2px")
        self.assertEqual(desktop_active_style["borderRadius"], "0px")

    @override_settings(DEBUG=False)
    def test_unknown_url_uses_custom_not_found_page(self):
        self.page.set_viewport_size({"width": 320, "height": 568})

        response = self.page.goto(
            self.live_server_url + "/chemin-introuvable/"
        )

        self.assertEqual(response.status, 404)
        self.page.get_by_role(
            "heading",
            name="Cette page n’existe pas",
        ).wait_for()
        self.page.locator(
            '.not-found-page__icon .ui-icon[data-icon="compass"]'
        ).wait_for()
        self.page.get_by_role(
            "link",
            name="Retour à l’accueil",
        ).wait_for()
        self.assert_no_horizontal_overflow()

    def test_dynamic_content_icons_load_from_the_svg_sprite(self):
        self.page.goto(
            self.live_server_url
            + reverse(
                "study:task_detail",
                args=[self.part.slug, self.task.slug],
            )
        )

        icon = self.page.locator(".title-with-icon__glyph .ui-icon")
        icon.wait_for()
        use = icon.locator("use")
        self.assertTrue(
            use.get_attribute("href").endswith(
                f"#icon-{self.task.icon}"
            )
        )
        self.assertTrue(
            use.evaluate(
                """
                element => {
                  const box = element.getBBox();
                  return box.width > 0 && box.height > 0;
                }
                """
            )
        )
        self.assertEqual(icon.get_attribute("data-icon"), self.task.icon)
        self.assertNotEqual(
            icon.evaluate("element => getComputedStyle(element).color"),
            self.page.locator(
                ".title-with-icon > span:last-child"
            ).evaluate("element => getComputedStyle(element).color"),
        )
        self.assertEqual(
            self.page.locator(".task-hero").evaluate(
                "element => getComputedStyle(element).backgroundColor"
            ),
            "rgba(0, 0, 0, 0)",
        )
        self.assertEqual(
            self.page.locator(".task-nav a.is-active").evaluate(
                "element => getComputedStyle(element).backgroundColor"
            ),
            "rgba(0, 0, 0, 0)",
        )
        self.assertEqual(
            self.page.locator(".task-nav a.is-active").evaluate(
                "element => getComputedStyle(element).borderBottomWidth"
            ),
            "3px",
        )

    def test_tache_two_theme_vocabulary_is_structured_on_desktop_and_mobile(
        self,
    ):
        self._import_eo_tache_two_content()
        part_path = reverse("study:part_detail", args=["eo"])
        overview_path = reverse("study:task_detail", args=["eo", "tache-2"])
        directory_path = reverse("study:tache_two_theme_vocabulary")
        subjects_path = reverse("study:task_browse", args=["eo", "tache-2"])
        expected_detail_path = reverse(
            "study:tache_two_theme_vocabulary_detail",
            args=["arrivee"],
        )

        self.page.set_viewport_size({"width": 1280, "height": 850})
        self.page.goto(self.live_server_url + part_path)
        task_card = self.page.locator(
            f'.deck[href="{overview_path}"]'
        ).first
        task_card.wait_for()
        self.assertEqual(
            task_card.locator(".deck__progress-copy").inner_text(),
            "0/33 lots terminés · 0/348 sujets terminés",
        )

        self.context.add_init_script(
            """
            Object.defineProperty(navigator, "clipboard", {
              configurable: true,
              value: {
                writeText: text => {
                  window.__aiPracticePromptCopied = text;
                  return Promise.resolve();
                },
              },
            });
            """
        )
        self.page.goto(self.live_server_url + overview_path)
        self.page.get_by_role(
            "heading",
            name="Tâche 2",
            exact=True,
        ).wait_for()
        prompt_button = self.page.get_by_role(
            "button",
            name="Copy AI Practice Prompt",
            exact=True,
        )
        self.assertEqual(prompt_button.inner_text(), "AI Practice Prompt")
        prompt_button.click()
        self.page.get_by_text("Copied!", exact=True).wait_for()
        self.assertEqual(
            self.page.evaluate("window.__aiPracticePromptCopied"),
            content.load_ai_examiner_prompt(),
        )
        overview_panels = self.page.locator(
            "[data-tache-two-overview-panel]"
        )
        self.assertEqual(overview_panels.count(), 2)
        self.assertEqual(
            len(
                self.page.locator(".tache-two-overview-grid").evaluate(
                    "element => getComputedStyle(element)"
                    ".gridTemplateColumns.split(' ')"
                )
            ),
            2,
        )
        self.assertEqual(
            overview_panels.nth(0).get_by_role(
                "heading",
                name="Vocabulaire par thème",
                exact=True,
            ).count(),
            1,
        )
        self.assertEqual(
            overview_panels.nth(1).get_by_role(
                "heading",
                name="Sujets",
                exact=True,
            ).count(),
            1,
        )
        self.assertEqual(
            overview_panels.nth(0).get_attribute("href"),
            directory_path,
        )
        self.assertEqual(
            overview_panels.nth(1).get_attribute("href"),
            subjects_path,
        )
        overview_nav = self.page.locator(".task-nav")
        self.assertEqual(overview_nav.locator("a").count(), 3)
        self.assertEqual(
            overview_nav.locator("a.is-active").inner_text(),
            "Vue d'ensemble",
        )
        self.assertEqual(
            self.page.locator("[data-collection-view-toggle]").count(),
            0,
        )

        self.page.set_viewport_size({"width": 320, "height": 700})
        self.assertEqual(
            len(
                self.page.locator(".tache-two-overview-grid").evaluate(
                    "element => getComputedStyle(element)"
                    ".gridTemplateColumns.split(' ')"
                )
            ),
            1,
        )
        self.assert_no_horizontal_overflow()

        self.page.set_viewport_size({"width": 1280, "height": 850})
        overview_panels.nth(0).click()
        self.page.wait_for_url(self.live_server_url + directory_path)
        self.page.get_by_role(
            "heading",
            name="Vocabulaire par thème",
            exact=True,
        ).wait_for()
        self.assertEqual(
            [int(value) for value in self.page.locator(
                ".memory-overview-hero__metrics dd"
            ).all_text_contents()],
            [11, 495, 33],
        )
        directory_nav = self.page.locator(".task-nav")
        self.assertEqual(directory_nav.locator("a").count(), 3)
        self.assertEqual(
            directory_nav.locator("a.is-active").inner_text(),
            "Vocabulaire par thème",
        )
        cards_toggle = self.page.get_by_role("button", name="Cartes")
        table_toggle = self.page.get_by_role("button", name="Tableau")
        table_header = self.page.locator(".collection-table-header--memories")
        self.assertEqual(cards_toggle.get_attribute("aria-pressed"), "true")
        self.assertEqual(
            self.page.locator("html").get_attribute(
                "data-collection-view-mode"
            ),
            "cards",
        )
        theme_entries = self.page.locator(".theme-vocabulary-entry.memory-entry")
        self.assertEqual(theme_entries.count(), 11)
        first_theme_entry = theme_entries.first
        self.assertLess(
            first_theme_entry.bounding_box()["width"],
            self.page.locator("main").bounding_box()["width"] * 0.65,
        )
        self.assertEqual(
            first_theme_entry.get_attribute("href"),
            expected_detail_path,
        )
        self.assert_no_horizontal_overflow()

        table_toggle.click()
        self.assertEqual(table_toggle.get_attribute("aria-pressed"), "true")
        self.assertEqual(
            self.page.locator("html").get_attribute(
                "data-collection-view-mode"
            ),
            "table",
        )
        self.assertTrue(table_header.is_visible())
        self.assertLessEqual(first_theme_entry.bounding_box()["height"], 170)
        self.assert_no_horizontal_overflow()

        self.page.set_viewport_size({"width": 320, "height": 700})
        self.assertEqual(theme_entries.count(), 11)
        self.assert_no_horizontal_overflow()

        self.page.set_viewport_size({"width": 1280, "height": 850})
        first_theme_title = first_theme_entry.locator("h2").inner_text()
        first_theme_entry.click()
        self.page.wait_for_url(self.live_server_url + expected_detail_path)
        self.page.get_by_role("heading", name=first_theme_title).wait_for()
        detail_nav = self.page.locator(".task-nav")
        self.assertEqual(detail_nav.locator("a").count(), 3)
        self.assertEqual(
            detail_nav.locator("a.is-active").inner_text(),
            "Vocabulaire par thème",
        )
        self.assertEqual(self.page.locator(".batch-card").count(), 3)
        batch_layout = self.page.locator(".batch-card").evaluate_all(
            """
            cards => cards.map(card => {
              const cardBox = card.getBoundingClientRect();
              const statusBox = card.querySelector(
                '.batch-card__status'
              ).getBoundingClientRect();
              return {
                width: cardBox.width,
                statusContained:
                  statusBox.left >= cardBox.left
                  && statusBox.right <= cardBox.right,
              };
            })
            """
        )
        self.assertTrue(
            all(item["width"] > 250 for item in batch_layout)
        )
        self.assertTrue(
            all(item["statusContained"] for item in batch_layout)
        )
        self.assertEqual(
            self.page.locator(".theme-vocabulary-group").count(),
            3,
        )
        self.assertEqual(
            self.page.locator(".theme-vocabulary-group__count")
            .all_text_contents(),
            ["15 fiches", "15 fiches", "15 fiches"],
        )
        self.assertEqual(
            self.page.locator(".theme-vocabulary-phrase").count(),
            45,
        )
        learned_forms = self.page.locator(
            "[data-theme-vocabulary-progress-form]"
        )
        self.assertEqual(learned_forms.count(), 45)
        first_learned_button = learned_forms.first.locator("button")
        self.assertEqual(
            first_learned_button.get_attribute("aria-checked"),
            "false",
        )
        self.assertEqual(
            self.page.locator(".theme-vocabulary-phrase [data-read-aloud]")
            .count(),
            45,
        )
        self.assertTrue(
            self.page.locator(
                ".theme-vocabulary-phrase [data-read-aloud]"
            ).first.is_enabled()
        )
        with self.page.expect_response(
            lambda response: "/progression/" in response.url
        ) as learned_response:
            first_learned_button.click()
        self.assertTrue(learned_response.value.ok)
        self.page.wait_for_function(
            """
            () => document.querySelector(
              '[data-theme-vocabulary-progress-form] button'
            )?.getAttribute('aria-checked') === 'true'
            """
        )
        self.assertTrue(
            self.page.locator(".theme-vocabulary-phrase").first.evaluate(
                "card => card.classList.contains('is-learned')"
            )
        )
        self.assertEqual(
            self.page.locator(
                "[data-theme-vocabulary-learned-count]"
            ).inner_text(),
            "1",
        )
        self.page.evaluate(
            """
            () => {
              const originalFetch = window.fetch.bind(window);
              window.__themeProgressActive = 0;
              window.__themeProgressMaxActive = 0;
              window.fetch = (input, init) => {
                const url = typeof input === "string" ? input : input.url;
                if (!url.includes("/progression/")) {
                  return originalFetch(input, init);
                }
                window.__themeProgressActive += 1;
                window.__themeProgressMaxActive = Math.max(
                  window.__themeProgressMaxActive,
                  window.__themeProgressActive
                );
                return new Promise(resolve => setTimeout(resolve, 80))
                  .then(() => originalFetch(input, init))
                  .finally(() => {
                    window.__themeProgressActive -= 1;
                  });
              };
            }
            """
        )
        learned_forms.nth(1).locator("button").click()
        learned_forms.nth(2).locator("button").click()
        self.page.wait_for_function(
            """
            () => document.querySelector(
              '[data-theme-vocabulary-learned-count]'
            )?.textContent.trim() === '3'
            """
        )
        self.assertEqual(
            self.page.evaluate("window.__themeProgressMaxActive"),
            1,
        )
        detail_table_toggle = self.page.get_by_role("button", name="Tableau")
        detail_cards_toggle = self.page.get_by_role("button", name="Cartes")
        self.assertEqual(
            detail_table_toggle.get_attribute("aria-pressed"),
            "true",
        )
        self.assertTrue(
            self.page.locator(
                ".theme-vocabulary-catalog [data-collection-table-header]"
            ).first.is_visible()
        )
        self.assert_no_horizontal_overflow()

        recall_controls = self.page.locator(
            "[data-theme-vocabulary-recall]"
        )
        french_recall = self.page.locator(
            '[data-theme-vocabulary-recall-column="french"]'
        )
        meaning_recall = self.page.locator(
            '[data-theme-vocabulary-recall-column="meaning"]'
        )
        first_french = self.page.locator(
            '[data-theme-vocabulary-recall-cell="french"]'
        ).first
        first_meaning = self.page.locator(
            '[data-theme-vocabulary-recall-cell="meaning"]'
        ).first
        first_french_content = first_french.locator(
            ".theme-vocabulary-recall__content"
        )
        first_meaning_content = first_meaning.locator(
            ".theme-vocabulary-recall__content"
        )
        self.assertTrue(recall_controls.is_visible())
        french_recall.click()
        self.assertEqual(french_recall.get_attribute("aria-pressed"), "true")
        self.assertEqual(first_french.get_attribute("role"), "button")
        self.assertEqual(first_french.get_attribute("aria-pressed"), "false")
        first_phrase_read = self.page.locator(
            ".theme-vocabulary-phrase [data-read-aloud]"
        ).first
        self.assertTrue(first_phrase_read.is_enabled())
        first_phrase_read.click()
        self.assertEqual(first_french.get_attribute("aria-pressed"), "false")
        first_phrase_read.click()
        self.assertNotEqual(
            first_french_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        first_french.click()
        self.assertEqual(first_french.get_attribute("aria-pressed"), "true")
        self.assertTrue(first_phrase_read.is_enabled())
        self.assertEqual(
            first_french_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )

        meaning_recall.click()
        self.assertEqual(french_recall.get_attribute("aria-pressed"), "false")
        self.assertEqual(meaning_recall.get_attribute("aria-pressed"), "true")
        self.assertIsNone(first_french.get_attribute("role"))
        self.assertEqual(first_meaning.get_attribute("aria-pressed"), "false")
        self.assertNotEqual(
            first_meaning_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        first_meaning.focus()
        self.page.keyboard.press("Enter")
        self.assertEqual(first_meaning.get_attribute("aria-pressed"), "true")
        self.assertEqual(
            first_meaning_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )

        detail_cards_toggle.click()
        self.assertEqual(
            self.page.locator("html").get_attribute(
                "data-collection-view-mode"
            ),
            "cards",
        )
        self.page.locator(
            "[data-theme-vocabulary-deck] [data-flashcard-flip]"
        ).click()
        self.assertTrue(first_meaning.is_visible())
        self.assertTrue(recall_controls.is_visible())
        self.assertEqual(first_meaning.get_attribute("role"), "button")
        self.assertEqual(
            first_meaning_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        visible_example = self.page.locator(
            ".theme-vocabulary-phrase:not("
            ".theme-vocabulary-card--inactive) "
            "[data-flashcard-back] .phrase__ex"
        ).inner_text()
        self.page.evaluate(
            """
            () => {
              window.__themeVocabularySpoken = [];
              window.speechSynthesis.cancel = () => {};
              window.speechSynthesis.resume = () => {};
              window.speechSynthesis.speak = utterance => {
                window.__themeVocabularySpoken.push(utterance.text);
              };
            }
            """
        )
        first_phrase_read.click()
        self.page.wait_for_function(
            "() => window.__themeVocabularySpoken.length > 0"
        )
        self.assertEqual(
            self.page.evaluate("window.__themeVocabularySpoken.join(' ')"),
            visible_example,
        )
        first_phrase_read.click()
        meaning_recall.click()
        meaning_recall.click()
        self.assertEqual(first_meaning.get_attribute("aria-pressed"), "false")
        self.assertNotEqual(
            first_meaning_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        first_meaning.click()
        self.assertTrue(
            self.page.locator(
                ".theme-vocabulary-phrase:not("
                ".theme-vocabulary-card--inactive) [data-flashcard-back]"
            ).is_visible()
        )
        self.assertEqual(
            first_meaning_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        visible_cards = self.page.locator(
            ".theme-vocabulary-phrase"
        ).evaluate_all(
            """
            cards => cards.filter(card => (
              getComputedStyle(card).display !== 'none'
              && card.getClientRects().length
            )).length
            """
        )
        self.assertEqual(visible_cards, 1)
        active_card_box = self.page.locator(
            ".theme-vocabulary-phrase:not("
            ".theme-vocabulary-card--inactive)"
        ).bounding_box()
        main_box = self.page.locator("main").bounding_box()
        self.assertLessEqual(
            active_card_box["x"] + active_card_box["width"],
            main_box["x"] + main_box["width"] + 1,
        )
        self.assert_no_horizontal_overflow()

        self.page.set_viewport_size({"width": 320, "height": 700})
        self.assertEqual(
            self.page.locator(".theme-vocabulary-phrase").evaluate_all(
                """
                cards => cards.filter(card => (
                  getComputedStyle(card).display !== 'none'
                  && card.getClientRects().length
                )).length
                """
            ),
            1,
        )
        self.assertTrue(
            self.page.locator(
                "[data-theme-vocabulary-previous]"
            ).is_visible()
        )
        self.assertTrue(
            self.page.locator("[data-theme-vocabulary-next]").is_visible()
        )
        self.assert_no_horizontal_overflow()

        self.page.set_viewport_size({"width": 1280, "height": 850})
        self.page.get_by_role("link", name="Tous les thèmes").click()
        self.page.wait_for_url(self.live_server_url + directory_path)
        self.assertEqual(cards_toggle.get_attribute("aria-pressed"), "true")
        self.assert_no_horizontal_overflow()

    def test_tache_two_subjects_have_practice_and_vocabulary_flow(self):
        command = Command()
        task_map = command._import_sections(load_sections())
        months = content.load_tache_two_subject_months()
        theme_map = command._import_themes(
            content.tache_two_themes(months),
            task_map,
        )
        family_map = command._import_families(
            content.tache_two_families(months)
        )
        responses = content.parse_tache_two_responses(months)
        response_map = command._import_responses(
            responses,
            theme_map,
            family_map,
        )
        prompt_index = command._import_prompts(
            responses,
            response_map,
            theme_map,
            family_map,
        )
        command._import_phrases(
            content.parse_tache_two_subject_vocabulary(responses),
            prompt_index,
        )
        command._sync_cards(response_map, user=self.user)
        overview_path = reverse(
            "study:task_detail",
            args=["eo", "tache-2"],
        )
        index_path = reverse(
            "study:task_browse",
            args=["eo", "tache-2"],
        )
        subject_path = reverse(
            "study:task_subject_detail",
            args=["eo", "tache-2", "janvier", 1, 1],
        )

        self.context.add_init_script(
            """
            Object.defineProperty(navigator, "clipboard", {
              configurable: true,
              value: {
                writeText: text => {
                  window.__subjectPromptCopied = text;
                  return Promise.resolve();
                },
              },
            });
            """
        )
        self.page.set_viewport_size({"width": 1280, "height": 850})
        self.page.goto(self.live_server_url + overview_path)
        theme_vocabulary_heading = self.page.get_by_role(
            "heading",
            name="Vocabulaire par thème",
            exact=True,
        )
        subject_heading = self.page.get_by_role(
            "heading",
            name="Sujets",
            exact=True,
        )
        theme_vocabulary_heading.wait_for()
        subject_heading.wait_for()
        self.assertLess(
            abs(
                theme_vocabulary_heading.bounding_box()["y"]
                - subject_heading.bounding_box()["y"]
            ),
            2,
        )
        self.assertEqual(
            self.page.locator("[data-tache-two-subject-batch]").count(),
            0,
        )
        self.assertEqual(
            self.page.locator(
                ".tache-two-overview-panel "
                ".tache-two-progress-summary"
            ).count(),
            2,
        )

        self.page.goto(self.live_server_url + index_path)
        self.page.get_by_role(
            "heading",
            name="Sujets par thème",
            exact=True,
        ).wait_for()
        directory_metrics = [
            int(value)
            for value in self.page.locator(
                ".memory-overview-hero__metrics dd"
            ).all_text_contents()
        ]
        theme_count, subject_count, _ = directory_metrics
        self.assertEqual(theme_count, 11)
        self.assertEqual(subject_count, 348)
        self.assertEqual(
            self.page.locator(".t1-themes .t1-row__link").count(),
            subject_count,
        )
        self.assertEqual(self.page.get_by_role("note").count(), 0)
        prompt_payload = json.loads(
            self.page.locator("#tache-two-theme-prompts").text_content()
        )
        card_copy = self.page.locator(
            '[data-collection-view-panel="cards"] [data-prompt-copy]'
        ).first
        card_prompt_key = card_copy.get_attribute("data-prompt-copy-key")
        card_copy.click()
        self.page.wait_for_function(
            "expected => window.__subjectPromptCopied === expected",
            arg=prompt_payload[card_prompt_key],
        )
        self.assertEqual(
            self.page.evaluate("window.__subjectPromptCopied"),
            prompt_payload[card_prompt_key],
        )
        self.assertEqual(self.page.url, self.live_server_url + index_path)

        self.page.set_viewport_size({"width": 320, "height": 700})
        self.assert_no_horizontal_overflow()
        self.page.set_viewport_size({"width": 1280, "height": 850})
        self.page.get_by_role("button", name="Tableau").click()
        table_group = self.page.locator(
            f'[data-t1-table-theme]:has(a[href="{subject_path}"])'
        )
        table_group.locator("summary").click()
        first_row = table_group.locator(
            f'[data-t1-table-subject]:has(a[href="{subject_path}"])'
        )
        table_copy = first_row.locator("[data-prompt-copy]")
        table_prompt_key = table_copy.get_attribute("data-prompt-copy-key")
        self.page.evaluate("window.__subjectPromptCopied = null")
        table_copy.click()
        self.page.wait_for_function(
            "expected => window.__subjectPromptCopied === expected",
            arg=prompt_payload[table_prompt_key],
        )
        self.assertEqual(self.page.url, self.live_server_url + index_path)
        completion_gap = first_row.evaluate(
            """
            row => {
              const status = row.querySelector('.progress-status')
                .getBoundingClientRect();
              const button = row.querySelector(
                '[data-subject-completion-form] button'
              ).getBoundingClientRect();
              return button.left - status.right;
            }
            """
        )
        self.assertGreaterEqual(completion_gap, 0)
        self.assertLessEqual(completion_gap, 8)
        completion = first_row.locator(
            "[data-subject-completion-form] button"
        )
        with self.page.expect_response(
            lambda response: "/progression/" in response.url
        ) as completion_response:
            completion.click()
        self.assertTrue(completion_response.value.ok)
        self.page.wait_for_function(
            """
            () => document.querySelectorAll(
              '[data-subject-completion-form] '
              + 'button[aria-checked="true"]'
            ).length === 2
            """
        )
        self.assertEqual(self.page.url, self.live_server_url + index_path)
        self.assertEqual(
            self.page.locator(
                '[data-subject-completion-form] '
                'button[aria-checked="true"]'
            ).count(),
            2,
        )

        table_group = self.page.locator(
            f'[data-t1-table-theme]:has(a[href="{subject_path}"])'
        )
        if not table_group.evaluate("group => group.open"):
            table_group.locator("summary").click()
        first_row = table_group.locator(
            f'[data-t1-table-subject]:has(a[href="{subject_path}"])'
        )
        questions_cell = first_row.locator(
            ".t1-table__questions"
        ).bounding_box()
        self.assert_opens_new_tab(
            lambda: self.page.mouse.click(
                questions_cell["x"] + questions_cell["width"] / 2,
                questions_cell["y"] + questions_cell["height"] / 2,
            ),
            subject_path,
            follow=True,
        )
        self.page.get_by_role(
            "heading",
            name="Achat d'objets avant un déménagement",
            exact=True,
        ).wait_for()
        self.assertEqual(
            self.page.locator("[data-tache-two-question]").count(),
            14,
        )
        self.assertEqual(
            self.page.locator(".tache-two-question__memory").count(),
            0,
        )
        self.page.get_by_text("Progression du sujet", exact=True).wait_for()
        self.page.get_by_role(
            "link",
            name="Pratiquer ce sujet",
            exact=True,
        ).wait_for()
        vocabulary_link = self.page.get_by_role(
            "link",
            name="Pratiquer les vocabs",
            exact=True,
        )
        vocabulary_link.wait_for()
        vocabulary_review_path = vocabulary_link.get_attribute("href")
        self.assertTrue(vocabulary_review_path)
        self.assertEqual(
            self.page.locator("#subject-vocabulary .response-batch").count(),
            3,
        )
        detail_prompt = json.loads(
            self.page.locator("#tache-two-subject-prompt").text_content()
        )
        self.page.evaluate("window.__subjectPromptCopied = null")
        self.page.locator(".tache-two-consigne [data-prompt-copy]").click()
        self.page.wait_for_function(
            "expected => window.__subjectPromptCopied === expected",
            arg=detail_prompt,
        )
        self.assertEqual(
            self.page.evaluate("window.__subjectPromptCopied"),
            detail_prompt,
        )
        self.page.get_by_text(
            "Consigne copiée dans le presse-papiers.",
            exact=True,
        ).wait_for()
        self.page.set_viewport_size({"width": 320, "height": 700})
        self.assert_no_horizontal_overflow()
        self.page.set_viewport_size({"width": 1280, "height": 850})

        self.page.get_by_role(
            "link",
            name="Personnaliser les questions",
            exact=True,
        ).click()
        self.page.get_by_role(
            "heading",
            name="Modifier mes questions",
            exact=True,
        ).wait_for()
        question_rows = self.page.locator(
            "[data-question-list] [data-question-form]"
        )
        self.assertEqual(question_rows.count(), 14)
        self.page.set_viewport_size({"width": 320, "height": 700})
        self.assert_no_horizontal_overflow()
        control_sizes = self.page.locator(
            "[data-tache-two-question-editor]"
        ).evaluate(
            """
            editor => {
              const add = editor.querySelector('[data-question-add]')
                .getBoundingClientRect();
              const remove = editor.querySelector('[data-question-remove]')
                .getBoundingClientRect();
              return {
                addHeight: add.height,
                removeWidth: remove.width,
                removeHeight: remove.height,
              };
            }
            """
        )
        self.assertGreaterEqual(control_sizes["addHeight"], 48)
        self.assertGreaterEqual(control_sizes["removeWidth"], 48)
        self.assertGreaterEqual(control_sizes["removeHeight"], 48)
        question_rows.locator("textarea[name$='-question']").first.fill(
            "Quel est votre prix pour la table ?"
        )
        self.page.get_by_role(
            "button",
            name="Ajouter une question",
            exact=True,
        ).click()
        self.assertEqual(question_rows.count(), 15)
        question_rows.locator("textarea[name$='-question']").last.fill(
            "Quand puis-je venir chercher les meubles ?"
        )
        question_rows.locator("textarea[name$='-response']").last.fill(
            "Samedi après-midi serait idéal."
        )
        self.page.get_by_role(
            "button",
            name="Enregistrer mes questions",
            exact=True,
        ).click()
        self.page.wait_for_url(
            self.live_server_url + subject_path + "?saved=1"
        )
        self.assertEqual(
            self.page.locator("[data-tache-two-question]").count(),
            15,
        )
        self.page.get_by_text(
            "Quand puis-je venir chercher les meubles ?",
            exact=True,
        ).wait_for()
        self.page.locator(
            ".tache-two-question__prepared-response",
            has_text="Samedi après-midi serait idéal.",
        ).wait_for()
        self.page.get_by_text("Version personnelle", exact=True).wait_for()
        self.assert_no_horizontal_overflow()
        self.page.set_viewport_size({"width": 1280, "height": 850})

        self.page.get_by_role(
            "link",
            name="Pratiquer ce sujet",
            exact=True,
        ).click()
        self.page.get_by_text(
            "Questions d'interaction",
            exact=True,
        ).wait_for()
        self.page.locator("[data-review-card]").click()
        self.page.get_by_text(
            "Quand puis-je venir chercher les meubles ?",
            exact=True,
        ).wait_for()
        self.page.locator(
            ".flashcard-question-list__response",
            has_text="Samedi après-midi serait idéal.",
        ).wait_for()
        self.assertNotIn("3 arguments", self.page.locator("main").inner_text())

        self.page.goto(self.live_server_url + vocabulary_review_path)
        self.page.get_by_text(
            "Vocabulaire du sujet",
            exact=True,
        ).wait_for()
        self.assert_no_horizontal_overflow()

    def test_tache_two_table_groups_subjects_by_theme(self):
        self._import_eo_tache_two_content()
        index_url = self.live_server_url + reverse(
            "study:task_browse",
            args=["eo", "tache-2"],
        )

        self.page.set_viewport_size({"width": 1183, "height": 844})
        self.page.goto(index_url)
        self.page.get_by_role("heading", name="Sujets par thème").wait_for()
        self.page.get_by_role("button", name="Tableau").click()

        groups = self.page.locator("[data-t1-table-theme]")
        self.assertEqual(groups.count(), 11)
        self.assertEqual(
            self.page.locator("[data-t1-table-subject]").count(),
            348,
        )
        self.assertEqual(self.page.locator(".t1-table__theme").count(), 0)
        table_layout = self.page.locator(".t1-table-groups").evaluate(
            """
            table => {
              const groups = table.querySelectorAll('[data-t1-table-theme]');
              const first = groups[0].getBoundingClientRect();
              const second = groups[1].getBoundingClientRect();
              return {
                borderWidth: parseFloat(getComputedStyle(table).borderTopWidth),
                firstRadius: parseFloat(
                  getComputedStyle(groups[0]).borderTopLeftRadius
                ),
                rowGap: second.top - first.bottom,
                headerDisplay: getComputedStyle(
                  table.querySelector('.t1-table-groups__head')
                ).display,
              };
            }
            """
        )
        self.assertEqual(table_layout["borderWidth"], 1)
        self.assertEqual(table_layout["firstRadius"], 0)
        self.assertLessEqual(abs(table_layout["rowGap"]), 1)
        self.assertEqual(table_layout["headerDisplay"], "grid")
        self.assertTrue(
            all(
                not groups.nth(index).evaluate("group => group.open")
                for index in range(groups.count())
            )
        )

        first_group = groups.first
        second_group = groups.nth(1)
        first_group.locator("summary").click()
        self.assertTrue(first_group.evaluate("group => group.open"))
        self.assertTrue(
            first_group.locator("[data-t1-table-subject]").first.is_visible()
        )
        self.assertFalse(
            second_group.locator("[data-t1-table-subject]").first.is_visible()
        )

        first_table = first_group.locator("[data-nested-sort-table]")
        first_rows = first_table.locator("[data-nested-sort-row]")
        second_titles_before = second_group.locator(
            "[data-nested-sort-row] .subject-table-row-link"
        ).all_inner_texts()
        subject_sort = first_table.locator(
            '[data-nested-table-sort="subject"]'
        )
        original_titles = first_rows.locator(
            ".subject-table-row-link"
        ).all_inner_texts()
        original_dates = first_rows.locator(
            ".t1-table__subject-date"
        ).all_inner_texts()
        month_order = {
            month: index
            for index, month in enumerate(
                (
                    "Janvier",
                    "Février",
                    "Mars",
                    "Avril",
                    "Mai",
                    "Juin",
                    "Juillet",
                    "Août",
                    "Septembre",
                    "Octobre",
                    "Novembre",
                    "Décembre",
                )
            )
        }
        default_months = [
            month_order[label.split(" · ", 1)[0]]
            for label in original_dates
        ]
        self.assertEqual(default_months, sorted(default_months))
        subject_sort.click()
        expected_titles = self.page.evaluate(
            """
            values => values.slice().sort(
              new Intl.Collator("fr", {
                sensitivity: "base",
                numeric: true,
              }).compare
            )
            """,
            original_titles,
        )
        self.assertEqual(
            first_rows.locator(".subject-table-row-link").all_inner_texts(),
            expected_titles,
        )
        self.assertEqual(
            subject_sort.locator("xpath=..").get_attribute("aria-sort"),
            "ascending",
        )
        subject_sort.click()
        expected_titles_desc = self.page.evaluate(
            """
            values => {
              const collator = new Intl.Collator("fr", {
                sensitivity: "base",
                numeric: true,
              });
              return values.slice().sort((left, right) =>
                -collator.compare(left, right)
              );
            }
            """,
            original_titles,
        )
        self.assertEqual(
            first_rows.locator(".subject-table-row-link").all_inner_texts(),
            expected_titles_desc,
        )
        subject_sort.click()
        self.assertEqual(
            first_rows.locator(".subject-table-row-link").all_inner_texts(),
            original_titles,
        )
        self.assertEqual(
            first_rows.locator(".t1-table__subject-date").all_inner_texts(),
            original_dates,
        )
        self.assertEqual(
            subject_sort.locator("xpath=..").get_attribute("aria-sort"),
            "none",
        )

        first_rows.evaluate_all(
            """
            rows => rows.forEach(row => {
              const status = row.querySelector(
                "[data-subject-progress-status]"
              );
              status.classList.remove(
                "progress-status--done",
                "progress-status--active"
              );
              status.classList.add("progress-status--new");
            })
            """
        )
        progress_target = first_rows.nth(2)
        progress_target.evaluate(
            """
            row => {
              row.dataset.sortTestTarget = "true";
              const status = row.querySelector(
                "[data-subject-progress-status]"
              );
              status.classList.remove("progress-status--new");
              status.classList.add("progress-status--done");
            }
            """
        )
        progress_sort = first_table.locator(
            '[data-nested-table-sort="progress"]'
        )
        progress_sort.click()
        self.assertEqual(
            first_rows.first.get_attribute("data-sort-test-target"),
            "true",
        )
        self.assertEqual(
            progress_sort.locator("xpath=..").get_attribute("aria-sort"),
            "descending",
        )
        progress_sort.click()
        self.assertEqual(
            first_rows.last.get_attribute("data-sort-test-target"),
            "true",
        )
        progress_sort.click()
        self.assertEqual(
            first_rows.locator(".subject-table-row-link").all_inner_texts(),
            original_titles,
        )
        self.assertEqual(
            second_group.locator(
                "[data-nested-sort-row] .subject-table-row-link"
            ).all_inner_texts(),
            second_titles_before,
        )

        neighborhood_group = groups.filter(
            has_text="Vie de quartier & entraide"
        )
        neighborhood_group.locator("summary").click()
        childcare_anchor = neighborhood_group.locator(
            '[data-t1-table-subject]:has('
            'a[href*="/sujets/fevrier/batch-6/26/"])'
        )
        childcare_response_id = childcare_anchor.get_attribute(
            "data-subject-progress-row"
        )
        childcare_rows = neighborhood_group.locator(
            "[data-t1-table-subject]"
            f'[data-subject-progress-row="{childcare_response_id}"]'
        )
        self.assertEqual(childcare_rows.count(), 5)
        self.assertEqual(
            set(childcare_rows.locator(".t1-table__questions").all_inner_texts()),
            {"15"},
        )
        self.assertEqual(
            neighborhood_group.locator(".t1-table__related-group").count(),
            0,
        )
        neighborhood_table = neighborhood_group.locator(
            "[data-nested-sort-table]"
        )
        neighborhood_rows = neighborhood_table.locator(
            "[data-nested-sort-row]"
        )
        neighborhood_titles = neighborhood_rows.locator(
            ".subject-table-row-link"
        ).all_inner_texts()
        neighborhood_table.locator(
            '[data-nested-table-sort="subject"]'
        ).click()
        expected_neighborhood_titles = self.page.evaluate(
            """
            values => values.slice().sort(
              new Intl.Collator("fr", {
                sensitivity: "base",
                numeric: true,
              }).compare
            )
            """,
            neighborhood_titles,
        )
        self.assertEqual(
            neighborhood_rows.locator(
                ".subject-table-row-link"
            ).all_inner_texts(),
            expected_neighborhood_titles,
        )

        self.page.set_viewport_size({"width": 320, "height": 700})
        table_shell = first_group.locator(".t1-table-shell")
        self.assertFalse(
            table_shell.evaluate(
                "element => element.scrollWidth > element.clientWidth"
            )
        )
        progress_alignment = first_group.locator(
            "[data-t1-table-subject]"
        ).first.locator(
            ".t1-table__progress"
        ).evaluate(
            "cell => getComputedStyle(cell).justifyContent"
        )
        self.assertEqual(progress_alignment, "flex-end")
        first_mobile_row = first_group.locator(
            "[data-t1-table-subject]"
        ).first
        self.assertFalse(
            first_mobile_row.locator(".t1-table__questions").is_visible()
        )
        mobile_cells = first_mobile_row.evaluate(
            """
            row => {
              const subject = row.querySelector('.t1-table__subject')
                .getBoundingClientRect();
              const status = row.querySelector(
                '[data-subject-progress-status]'
              );
              const box = status.getBoundingClientRect();
              const style = getComputedStyle(status);
              return {
                subjectWidth: subject.width,
                statusWidth: box.width,
                statusHeight: box.height,
                statusFontSize: style.fontSize,
                statusRadius: style.borderRadius,
                statusGlyph: getComputedStyle(status, '::before').content,
              };
            }
            """
        )
        self.assertGreater(mobile_cells["subjectWidth"], 180)
        self.assertAlmostEqual(mobile_cells["statusWidth"], 28, delta=1)
        self.assertAlmostEqual(mobile_cells["statusHeight"], 28, delta=1)
        self.assertEqual(mobile_cells["statusFontSize"], "0px")
        self.assertEqual(mobile_cells["statusRadius"], "50%")
        self.assertIn("○", mobile_cells["statusGlyph"])
        self.assertFalse(
            self.page.locator(".t1-table-groups__head").is_visible()
        )
        self.assertTrue(subject_sort.is_visible())
        self.assertTrue(progress_sort.is_visible())
        self.assertIn(
            "état",
            progress_sort.get_attribute("aria-label").lower(),
        )
        self.assert_no_horizontal_overflow()

    def test_tache_three_theme_vocabulary_is_complete_and_responsive(self):
        self.page.set_viewport_size({"width": 1120, "height": 760})
        prompt = self.first.response.prompts.get(is_canonical=True)
        lot_order = 0
        for category_order, category_name in enumerate(
            content.EO_TACHE_THREE_THEME_VOCABULARY_CATEGORIES.values(),
            start=1,
        ):
            category = PhraseCategory.objects.create(
                slug=f"browser-t3-theme-{category_order}",
                name=category_name,
                content_key=f"browser:t3-theme-{category_order}",
                order=category_order,
            )
            for _ in range(15):
                lot_order += 1
                phrase = factories.make_phrase(
                    category=category,
                    tier=PhraseTier.THEME,
                    lot_order=lot_order,
                )
                phrase.source_prompts.add(prompt)
                factories.make_phrase_card(
                    phrase=phrase,
                    user=self.user,
                )

        task_overview_url = reverse(
            "study:task_detail",
            args=[self.part.slug, self.task.slug],
        )
        self.page.goto(self.live_server_url + task_overview_url)
        self.page.locator('[data-task-choice="vocabulary"]').click()
        self.page.wait_for_url(
            self.live_server_url
            + reverse(
                "study:task_phrases",
                args=[self.part.slug, self.task.slug],
            )
        )
        summary_layout = self.page.evaluate(
            """() => {
              const hero = document.querySelector(
                '.memory-overview > .memory-overview-hero'
              ).getBoundingClientRect();
              const progress = document.querySelector(
                '.task-vocabulary-directory__toolbar > '
                + '.tache-two-progress-summary'
              ).getBoundingClientRect();
              const toolbar = document.querySelector(
                '.task-vocabulary-directory__toolbar > '
                + '.collection-view-toolbar'
              ).getBoundingClientRect();
              return {
                heroGap: progress.top - hero.bottom,
                sharesRow: toolbar.top < progress.bottom &&
                  toolbar.bottom > progress.top,
              };
            }"""
        )
        self.assertLessEqual(summary_layout["heroGap"], 24)
        self.assertTrue(summary_layout["sharesRow"])
        self.assertEqual(
            [
                int(value)
                for value in self.page.locator(
                    ".memory-overview-hero__metrics dd"
                ).all_text_contents()
            ],
            [1, 60, 4],
        )
        self.assertEqual(
            self.page.locator(".task-vocabulary-theme-entry").count(),
            1,
        )
        active_filter = self.page.locator(
            '[data-theme-vocabulary-directory-filter="active"]'
        )
        active_filter.click()
        self.assertTrue(
            self.page.locator(
                "[data-theme-vocabulary-directory-empty]"
            ).is_visible()
        )
        self.assertFalse(
            self.page.locator(".task-vocabulary-theme-entry").is_visible()
        )
        self.page.locator(
            '[data-theme-vocabulary-directory-filter="all"]'
        ).click()
        self.assertTrue(
            self.page.locator(".task-vocabulary-theme-entry").is_visible()
        )
        self.assert_no_horizontal_overflow()

        self.page.get_by_role(
            "link",
            name=f"Ouvrir le vocabulaire du thème {self.theme.display_name}",
            exact=True,
        ).click()
        self.page.wait_for_url(
            self.live_server_url
            + reverse(
                "study:task_vocabulary_theme",
                args=[
                    self.part.slug,
                    self.task.slug,
                    self.theme.slug,
                ],
            )
        )
        self.page.get_by_role(
            "heading",
            name="Quatre parcours complémentaires",
            exact=True,
        ).wait_for()
        self.assertEqual(
            self.page.locator(".batch-card").count(),
            4,
        )
        self.assertEqual(
            self.page.locator(".theme-vocabulary-group").count(),
            4,
        )
        self.assertEqual(
            self.page.locator(
                ".theme-vocabulary-group__count"
            ).all_text_contents(),
            ["15 fiches"] * 4,
        )
        self.assertEqual(
            self.page.locator(".theme-vocabulary-phrase").count(),
            60,
        )

        first_progress = self.page.locator(
            "[data-theme-vocabulary-progress-form]"
        ).first
        with self.page.expect_response(
            lambda response: "/progression/" in response.url
        ) as progress_response:
            first_progress.locator("button").click()
        self.assertTrue(progress_response.value.ok)
        self.assertEqual(
            first_progress.locator("button").get_attribute("aria-checked"),
            "true",
        )
        self.assertEqual(
            self.page.locator(
                '[data-theme-vocabulary-filter-count="learned"]'
            ).inner_text(),
            "1",
        )
        self.assertEqual(
            self.page.locator(
                '[data-theme-vocabulary-filter-count="learning"]'
            ).inner_text(),
            "59",
        )

        learned_filter = self.page.locator(
            '[data-theme-vocabulary-status-filter="learned"]'
        )
        learned_filter.click()
        self.assertEqual(
            self.page.locator(
                "[data-theme-vocabulary-filter-result]"
            ).inner_text(),
            "1 fiche affichée",
        )
        self.assertEqual(
            self.page.locator(
                ".theme-vocabulary-phrase:not("
                ".theme-vocabulary-filtered-out)"
            ).count(),
            1,
        )
        self.assertEqual(
            self.page.locator(
                "[data-theme-vocabulary-deck-progress]"
            ).inner_text(),
            "1 / 1",
        )
        self.assertTrue(
            self.page.locator("[data-theme-vocabulary-next]").is_disabled()
        )

        self.page.locator(
            '[data-theme-vocabulary-status-filter="all"]'
        ).click()
        active_card = self.page.locator(
            ".theme-vocabulary-phrase:not("
            ".theme-vocabulary-card--inactive)"
        )
        first_card_id = active_card.get_attribute("id")
        active_card.focus()
        self.page.keyboard.press("ArrowDown")
        self.assertTrue(
            active_card.locator("[data-flashcard-back]").is_visible()
        )
        self.assertTrue(
            active_card.locator("[data-read-aloud]").is_visible()
        )
        self.page.keyboard.press("ArrowUp")
        self.assertTrue(
            active_card.locator("[data-flashcard-front]").is_visible()
        )
        self.page.keyboard.press("ArrowRight")
        self.assertNotEqual(active_card.get_attribute("id"), first_card_id)
        self.page.keyboard.press("ArrowLeft")
        self.assertEqual(active_card.get_attribute("id"), first_card_id)

        card_box = active_card.bounding_box()
        swipe_y = card_box["y"] + card_box["height"] * 0.65
        swipe_start = card_box["x"] + card_box["width"] - 20
        swipe_end = card_box["x"] + 20
        self.touch_swipe(active_card, swipe_start, swipe_end, swipe_y)
        self.assertNotEqual(active_card.get_attribute("id"), first_card_id)

        table_toggle = self.page.get_by_role("button", name="Tableau")
        cards_toggle = self.page.get_by_role("button", name="Cartes")
        table_toggle.click()
        self.assertEqual(table_toggle.get_attribute("aria-pressed"), "true")
        self.assertTrue(
            self.page.locator(
                ".theme-vocabulary-catalog "
                "[data-collection-table-header]"
            ).first.is_visible()
        )
        french_recall = self.page.locator(
            '[data-theme-vocabulary-recall-column="french"]'
        )
        first_french_content = self.page.locator(
            '[data-theme-vocabulary-recall-cell="french"] '
            ".theme-vocabulary-recall__content"
        ).first
        french_recall.click()
        self.assertNotEqual(
            first_french_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        cards_toggle.click()
        self.assertEqual(cards_toggle.get_attribute("aria-pressed"), "true")
        self.assertNotEqual(
            first_french_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )

        self.page.set_viewport_size({"width": 320, "height": 700})
        table_toggle.click()
        self.assertEqual(table_toggle.get_attribute("aria-pressed"), "true")
        self.assertTrue(french_recall.is_visible())
        self.assert_no_horizontal_overflow()

    def test_theme_vocabulary_group_heads_use_readable_small_type(self):
        self._import_eo_tache_two_content()
        self.page.set_viewport_size({"width": 1280, "height": 800})
        self.page.goto(
            self.live_server_url
            + reverse(
                "study:tache_two_theme_vocabulary_detail",
                args=["arrivee"],
            )
        )
        # Group heads label the table view; card mode folds them into cards.
        self.page.get_by_role("button", name="Tableau").first.click()
        group_head = self.page.locator(".theme-vocabulary-group__head").first
        group_head.wait_for()

        typography = group_head.evaluate(
            """
            element => {
              const title = element.querySelector('h3');
              const description = element.querySelector('p');
              const count = element.querySelector(
                '.theme-vocabulary-group__count'
              );
              return {
                titleSize: parseFloat(getComputedStyle(title).fontSize),
                descriptionSize: parseFloat(
                  getComputedStyle(description).fontSize
                ),
                descriptionLineHeight: parseFloat(
                  getComputedStyle(description).lineHeight
                ),
                countSize: parseFloat(getComputedStyle(count).fontSize),
              };
            }
            """
        )

        self.assertGreaterEqual(typography["titleSize"], 16)
        self.assertGreaterEqual(typography["descriptionSize"], 13)
        self.assertGreaterEqual(
            typography["descriptionLineHeight"],
            typography["descriptionSize"] * 1.3,
        )
        self.assertGreaterEqual(typography["countSize"], 12)
        self.assert_no_horizontal_overflow()

    def test_subject_completion_checkbox_is_explicit_on_mobile(self):
        page_errors = []
        self.page.on("pageerror", lambda error: page_errors.append(str(error)))
        response_id = self.first.response_id
        completion_path = reverse(
            "study:subject_completion",
            args=[self.part.slug, self.task.slug, response_id],
        )
        self.page.goto(
            self.live_server_url + response_detail_url(self.first.response)
        )
        checkbox = self.page.locator(
            "[data-subject-completion-form] button"
        )
        status = self.page.locator(
            f'[data-subject-progress-status="{response_id}"]'
        )

        self.assertEqual(checkbox.get_attribute("aria-checked"), "false")
        self.assertEqual(
            checkbox.evaluate(
                "element => getComputedStyle(element).borderRadius"
            ),
            "50%",
        )
        self.page.get_by_text("J’ai terminé ce sujet", exact=True).wait_for()

        with self.page.expect_response(
            lambda response: completion_path in response.url
        ):
            checkbox.click()
        self.assertFalse(
            page_errors,
            f"Subject completion JavaScript failed: {page_errors}",
        )
        self.page.locator(
            f'[data-subject-progress-status="{response_id}"]',
            has_text="Terminé",
        ).wait_for()
        self.assertEqual(checkbox.get_attribute("aria-checked"), "true")
        self.first.refresh_from_db()
        self.assertIsNotNone(self.first.subject_completed_at)

        self.first.response_practice_started_at = timezone.now()
        self.first.save(update_fields=["response_practice_started_at"])
        with self.page.expect_response(
            lambda response: completion_path in response.url
        ):
            checkbox.click()
        self.page.locator(
            f'[data-subject-progress-status="{response_id}"]',
            has_text="En cours",
        ).wait_for()
        self.assertEqual(checkbox.get_attribute("aria-checked"), "false")
        self.first.refresh_from_db()
        self.assertIsNone(self.first.subject_completed_at)
        self.assertEqual(status.inner_text(), "En cours")
        self.assert_no_horizontal_overflow()

        theme_url = self.live_server_url + theme_detail_url(self.theme)
        self.page.goto(theme_url)
        row = self.page.locator(
            f'[data-subject-progress-row="{response_id}"]'
        )
        row_checkbox = row.locator(
            "[data-subject-completion-form] button"
        )
        with self.page.expect_navigation(wait_until="networkidle"):
            row_checkbox.click()
        self.assertEqual(self.page.url, theme_url)
        self.assertEqual(row_checkbox.get_attribute("aria-checked"), "true")
        self.page.get_by_text("1 terminé.", exact=False).wait_for()
        self.assert_no_horizontal_overflow()

        self.assert_opens_new_tab(
            lambda: row.locator(".subject-row-hit-area").click(),
            response_detail_url(self.first.response),
        )

    def save_current_prompt_highlight(self):
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.evaluate(
            """
            element => {
              const range = document.createRange();
              range.selectNodeContents(element);
              const selection = window.getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              document.dispatchEvent(new Event("selectionchange"));
            }
            """
        )
        self.page.locator("[data-highlight-selection]").wait_for(
            state="visible"
        )
        with self.page.expect_response(
            lambda response: reverse("study:annotation_create") in response.url
        ) as response_info:
            self.page.locator("[data-highlight-selection]").click()
        self.assertIn(response_info.value.status, (200, 201))

    def select_prompt(self, *, start=None, end=None):
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.evaluate(
            """
            (element, offsets) => {
              const range = document.createRange();
              if (offsets.start === null) {
                range.selectNodeContents(element);
              } else {
                const walker = document.createTreeWalker(
                  element,
                  NodeFilter.SHOW_TEXT
                );
                const boundary = target => {
                  let node;
                  let offset = target;
                  while ((node = walker.nextNode())) {
                    if (offset <= node.data.length) return [node, offset];
                    offset -= node.data.length;
                  }
                  throw new Error("Selection offset is outside the prompt.");
                };
                const startBoundary = boundary(offsets.start);
                walker.currentNode = element;
                const endBoundary = boundary(offsets.end);
                range.setStart(startBoundary[0], startBoundary[1]);
                range.setEnd(endBoundary[0], endBoundary[1]);
              }
              const selection = window.getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              document.dispatchEvent(new Event("selectionchange"));
            }
            """,
            {"start": start, "end": end},
        )
        self.page.locator("[data-highlight-selection]").wait_for(
            state="visible"
        )

    def test_mobile_review_highlights_and_final_previous(self):
        first_prompt = self.first.response.prompts.get(is_canonical=True)
        for path in (
            reverse("study:dashboard"),
            reverse("study:settings"),
            response_detail_url(self.first.response),
            reverse(
                "study:edit_response",
                args=[self.part.slug, self.task.slug, first_prompt.pk],
            ),
        ):
            self.page.goto(self.live_server_url + path)
            self.assert_no_horizontal_overflow()

        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        self.page.locator("#card-front .prompt-text").wait_for()
        first_prompt = self.page.locator(
            "#card-front .prompt-text"
        ).text_content()
        self.save_current_prompt_highlight()
        self.page.locator("#reveal").click()
        for selector in (
            ".grade__icon",
            ".grade__key",
            ".kbd-hint kbd",
        ):
            self.assertEqual(
                self.page.locator(selector).first.evaluate(
                    "element => getComputedStyle(element).borderRadius"
                ),
                "50%",
            )
        self.page.locator('[data-action="correct"]').click()
        self.page.wait_for_function(
            """
            previous => {
              const prompt = document.querySelector("#card-front .prompt-text");
              return prompt && prompt.textContent !== previous;
            }
            """,
            arg=first_prompt,
        )
        self.save_current_prompt_highlight()

        self.page.locator("#reveal").click()
        self.page.locator('[data-action="correct"]').click()
        self.page.locator("#done-zone:not(.hidden)").wait_for()
        previous = self.page.locator("#previous-card")
        self.assertTrue(previous.is_enabled())
        previous.click()
        self.page.locator("#previous-card-label:not(.hidden)").wait_for()
        self.assert_no_horizontal_overflow()

        highlights = Annotation.objects.filter(
            user=self.user,
            kind=AnnotationKind.HIGHLIGHT,
        )
        self.assertEqual(highlights.count(), 2)
        self.assertEqual(
            highlights.values("source_key").distinct().count(),
            2,
        )

    def test_vocabulary_flashcards_flip_on_tap_and_reverse(self):
        phrase = factories.make_phrase(
            tier=PhraseTier.SUBJECT,
            lot_order=1,
        )
        phrase.source_prompts.add(
            self.first.response.prompts.get(is_canonical=True)
        )
        factories.make_phrase_card(user=self.user, phrase=phrase)
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + f"?kind=vocab&response={self.first.response_id}"
        )

        card = self.page.locator("[data-review-card]")
        front = self.page.locator("#card-front")
        back = self.page.locator("#card-back")
        face_label = self.page.locator("[data-flashcard-face-label]")
        front.get_by_text(phrase.english_cue, exact=True).wait_for()
        self.assertEqual(face_label.inner_text(), "Recto")
        self.assertTrue(front.is_visible())
        self.assertFalse(back.is_visible())
        switches = self.page.locator("[data-flashcard-order]")
        self.assertEqual(switches.count(), 2)

        card.click(position={"x": 20, "y": 20})

        back.locator(".spine-text", has_text=phrase.expression).wait_for()
        self.assertEqual(face_label.inner_text(), "Verso")
        self.assertFalse(front.is_visible())
        self.page.locator("#grades:not(.hidden)").wait_for()

        card.click(position={"x": 20, "y": 20})

        front.get_by_text(phrase.english_cue, exact=True).wait_for()
        self.assertEqual(face_label.inner_text(), "Recto")
        self.page.locator("#reveal:not(.hidden)").wait_for()

        self.page.locator('[data-flashcard-order="back"]').click()

        back.locator(".spine-text", has_text=phrase.expression).wait_for()
        self.assertEqual(face_label.inner_text(), "Verso")
        self.assertEqual(
            self.page.locator('[data-flashcard-order="back"]').get_attribute(
                "aria-pressed"
            ),
            "true",
        )
        self.assertTrue(self.page.locator("#grades").is_hidden())

        card.click(position={"x": 20, "y": 20})

        front.get_by_text(phrase.english_cue, exact=True).wait_for()
        self.assertEqual(face_label.inner_text(), "Recto")
        self.page.locator('[data-action="correct"]').click()
        self.page.locator("#done-zone:not(.hidden)").wait_for()
        self.assert_no_horizontal_overflow()

    def test_shared_review_deck_swipes_reveal_grade_and_visit_history(self):
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        first_prompt = prompt.inner_text()
        card = self.page.locator("[data-review-card]")
        self.assertEqual(
            card.evaluate("element => getComputedStyle(element).touchAction"),
            "pan-y",
        )

        def swipe(direction):
            box = card.bounding_box()
            centre_x = box["x"] + box["width"] / 2
            centre_y = box["y"] + box["height"] / 2
            distance = min(100, box["width"] / 3)
            start_x = centre_x + (distance if direction == "left" else -distance)
            end_x = centre_x + (-distance if direction == "left" else distance)
            self.touch_swipe(card, start_x, end_x, centre_y)

        swipe("left")
        self.page.locator("#card-back:not(.hidden)").wait_for()
        self.page.locator("#grades:not(.hidden)").wait_for()

        with self.page.expect_response(
            lambda response: reverse("study:review_answer") in response.url
        ) as answer_response:
            swipe("left")
        self.assertTrue(answer_response.value.ok)
        self.page.wait_for_function(
            """
            previous => {
              const prompt = document.querySelector("#card-front .prompt-text");
              return prompt && prompt.textContent.trim() !== previous;
            }
            """,
            arg=first_prompt,
        )
        current_prompt = prompt.inner_text()
        self.assertEqual(
            ReviewLog.objects.filter(user=self.user).latest("id").rating,
            Rating.GOOD,
        )

        with self.page.expect_response(
            lambda response: reverse("study:review_previous") in response.url
        ) as previous_response:
            swipe("right")
        self.assertTrue(previous_response.value.ok)
        self.page.locator("#previous-card-label:not(.hidden)").wait_for()
        self.assertEqual(prompt.inner_text(), first_prompt)

        swipe("left")
        self.page.locator("#previous-card-label").wait_for(state="hidden")
        self.assertEqual(prompt.inner_text(), current_prompt)
        self.assert_no_horizontal_overflow()

    def test_mouse_drag_selects_review_text_without_revealing_or_grading(self):
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        box = prompt.bounding_box()
        y = box["y"] + min(24, box["height"] / 2)
        self.page.mouse.move(box["x"] + 12, y)
        self.page.mouse.down()
        self.page.mouse.move(box["x"] + box["width"] - 12, y, steps=8)
        self.page.mouse.up()
        self.page.wait_for_timeout(150)

        selection = self.page.evaluate(
            "window.getSelection().toString().trim()"
        )
        self.assertTrue(selection)
        self.assertTrue(self.page.locator("#card-front").is_visible())
        self.assertTrue(self.page.locator("#grades").is_hidden())
        self.assertFalse(ReviewLog.objects.filter(user=self.user).exists())

    def test_mobile_highlight_expands_then_toggles_off(self):
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        self.page.wait_for_load_state("networkidle")
        prompt_text = prompt.text_content()
        highlight_button = self.page.locator("[data-highlight-selection]")

        self.select_prompt(start=0, end=12)
        with self.page.expect_response(
            lambda response: reverse("study:annotation_create") in response.url
        ):
            highlight_button.click()
        prompt.locator("mark.user-highlight").wait_for()

        self.select_prompt(start=6, end=len(prompt_text))
        self.assertEqual(
            highlight_button.get_attribute("aria-label"),
            "Highlight selected text",
        )
        with self.page.expect_response(
            lambda response: reverse("study:annotation_create") in response.url
        ):
            highlight_button.click()
        self.page.wait_for_function(
            """
            expected => {
              const marks = document.querySelectorAll(
                "#card-front .prompt-text mark.user-highlight"
              );
              return marks.length === 1 && marks[0].textContent === expected;
            }
            """,
            arg=prompt_text,
        )
        highlight = Annotation.objects.get(
            user=self.user,
            kind=AnnotationKind.HIGHLIGHT,
        )
        self.assertEqual(highlight.quote, prompt_text)

        self.select_prompt()
        self.assertEqual(
            highlight_button.get_attribute("aria-label"),
            "Unhighlight selected text",
        )
        with self.page.expect_response(
            lambda response: (
                "/notes/" in response.url
                and "/supprimer/" in response.url
            )
        ):
            highlight_button.click()
        self.page.wait_for_function(
            """
            !document.querySelector(
              "#card-front .prompt-text mark.user-highlight"
            )
            """
        )
        self.assertFalse(
            Annotation.objects.filter(
                user=self.user,
                kind=AnnotationKind.HIGHLIGHT,
            ).exists()
        )

    def test_selection_toolbar_stays_open_until_outside_click(self):
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        self.page.wait_for_load_state("networkidle")
        self.select_prompt(start=0, end=12)
        toolbar = self.page.locator("[data-selection-translate]")

        with self.page.expect_response(
            lambda response: reverse("study:annotation_create") in response.url
        ):
            self.page.locator("[data-highlight-selection]").click()
        prompt.locator("mark.user-highlight").wait_for()
        self.assertTrue(toolbar.is_visible())

        self.page.locator("[data-copy-selection]").click()
        self.assertTrue(toolbar.is_visible())

        self.page.locator("[data-translate-selection]").click()
        translation_panel = self.page.locator("[data-translation-panel]")
        translation_panel.wait_for()
        self.assertTrue(toolbar.is_visible())
        translation_panel.get_by_role("button", name="Fermer").click()
        translation_panel.wait_for(state="hidden")
        self.assertTrue(toolbar.is_visible())

        self.page.locator("[data-translate-selection]").evaluate(
            "button => button.click()"
        )
        translation_panel.wait_for()
        translation_panel.locator("[data-translation-close]").first.click()
        translation_panel.wait_for(state="hidden")
        self.assertTrue(toolbar.is_visible())

        self.page.locator("[data-note-selection]").evaluate(
            "button => button.click()"
        )
        self.page.locator("[data-note-panel]").wait_for()
        self.assertTrue(toolbar.is_visible())
        self.page.locator("[data-note-cancel]").click()
        self.assertTrue(toolbar.is_visible())

        self.page.locator(".review__top").click(position={"x": 4, "y": 4})
        toolbar.wait_for(state="hidden")

    def test_selection_toolbar_keyboard_shortcuts(self):
        self.context.add_init_script(
            """
            (() => {
              const synthesis = {
                getVoices: () => [],
                addEventListener: () => {},
                cancel: () => {},
                resume: () => {},
                speak: utterance => {
                  window.__shortcutSpokenText = utterance.text;
                },
              };
              class FakeUtterance {
                constructor(text) {
                  this.text = text;
                  this.lang = "";
                  this.rate = 1;
                  this.pitch = 1;
                  this.voice = null;
                }
              }
              Object.defineProperty(window, "speechSynthesis", {
                configurable: true,
                value: synthesis,
              });
              Object.defineProperty(window, "SpeechSynthesisUtterance", {
                configurable: true,
                value: FakeUtterance,
              });
              Object.defineProperty(navigator, "clipboard", {
                configurable: true,
                value: {
                  writeText: text => {
                    window.__shortcutCopiedText = text;
                    return Promise.resolve();
                  },
                },
              });
            })();
            """
        )
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        self.page.wait_for_load_state("networkidle")
        prompt_text = prompt.text_content()
        self.page.locator('[data-flashcard-order="back"]').click()
        self.page.locator("#reveal").click()

        toolbar = self.page.locator("[data-selection-translate]")
        shortcuts = {
            "[data-copy-selection]": "C",
            "[data-read-selection]": "R",
            "[data-translate-selection]": "T",
            "[data-note-selection]": "N",
            "[data-highlight-selection]": "H",
        }
        for selector, key in shortcuts.items():
            self.assertEqual(
                toolbar.locator(selector).get_attribute("aria-keyshortcuts"),
                key,
            )

        self.select_prompt(start=0, end=12)
        selected = self.page.evaluate(
            "window.getSelection().toString().trim()"
        )
        self.page.keyboard.press("c")
        self.page.wait_for_function(
            "expected => window.__shortcutCopiedText === expected",
            arg=selected,
        )
        self.assertEqual(
            self.page.locator("[data-copy-selection-label]").inner_text(),
            "Copied",
        )
        self.assertEqual(
            ReviewLog.objects.filter(user=self.user).count(),
            0,
        )

        self.select_prompt(start=0, end=12)
        self.page.keyboard.press("r")
        self.page.wait_for_function(
            "expected => window.__shortcutSpokenText === expected",
            arg=selected,
        )
        self.page.wait_for_timeout(150)
        self.assertEqual(prompt.text_content(), prompt_text)
        self.assertEqual(
            ReviewLog.objects.filter(user=self.user).count(),
            0,
        )
        self.page.keyboard.press("Escape")

        self.select_prompt(start=0, end=12)
        with self.page.expect_response(
            lambda response: reverse("study:annotation_create") in response.url
        ):
            self.page.keyboard.press("h")
        prompt.locator("mark.user-highlight").wait_for()

        self.select_prompt(start=0, end=12)
        self.page.keyboard.press("n")
        note_panel = self.page.locator("[data-note-panel]")
        note_panel.wait_for()
        note_body = note_panel.locator("[data-note-body]")
        self.page.wait_for_function(
            "() => document.querySelector('[data-note-body]') "
            "=== document.activeElement"
        )
        self.page.keyboard.press("h")
        self.assertEqual(note_body.input_value(), "h")
        self.assertEqual(
            Annotation.objects.filter(
                user=self.user,
                kind=AnnotationKind.HIGHLIGHT,
            ).count(),
            1,
        )
        self.page.keyboard.press("Escape")
        self.page.evaluate(
            "document.activeElement && document.activeElement.blur()"
        )

        self.select_prompt(start=0, end=12)
        self.page.keyboard.press("t")
        self.page.locator("[data-translation-panel]").wait_for()

    def test_selection_note_paste_button_inserts_clipboard_at_cursor(self):
        self.context.add_init_script(
            """
            Object.defineProperty(navigator, "clipboard", {
              configurable: true,
              value: {
                readText: () => Promise.resolve("texte collé"),
              },
            });
            """
        )
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        self.page.wait_for_load_state("networkidle")
        self.select_prompt(start=0, end=12)
        self.page.locator("[data-note-selection]").click()

        panel = self.page.locator("[data-note-panel]")
        panel.wait_for()
        note_body = panel.locator("[data-note-body]")
        note_body.fill("Avant  après")
        note_body.evaluate("element => element.setSelectionRange(6, 6)")
        paste_button = panel.get_by_role(
            "button",
            name="Coller depuis le presse-papiers",
        )

        paste_button.click()

        panel.get_by_text("Texte collé.", exact=True).wait_for()
        self.assertEqual(note_body.input_value(), "Avant texte collé après")
        self.assertIn(
            "ui-icons.svg?v=3#icon-clipboard-paste",
            paste_button.locator("use").get_attribute("href"),
        )
        paste_box = paste_button.bounding_box()
        self.assertGreaterEqual(paste_box["width"], 44)
        self.assertGreaterEqual(paste_box["height"], 44)
        self.assert_no_horizontal_overflow()

    def test_translation_panel_saves_the_translation_as_a_note(self):
        self.context.add_init_script(
            """
            window.Translator = {
              create: () => Promise.resolve({
                translate: (text) => Promise.resolve("EN: " + text),
              }),
            };
            """
        )
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        self.page.wait_for_load_state("networkidle")
        quote = prompt.inner_text()[:12]
        self.select_prompt(start=0, end=12)
        self.page.locator("[data-translate-selection]").click()

        panel = self.page.locator("[data-translation-panel]")
        panel.wait_for()
        note_button = panel.locator("[data-translation-note]")
        note_button.wait_for()

        with self.page.expect_response(
            lambda response: reverse("study:annotation_create") in response.url
        ) as create_response:
            note_button.click()

        self.assertEqual(create_response.value.status, 201)
        panel.wait_for(state="hidden")
        self.page.get_by_text(
            "Note enregistrée et passage surligné.", exact=True
        ).wait_for()
        note = Annotation.objects.get(
            user=self.user,
            kind=AnnotationKind.NOTE,
        )
        self.assertEqual(note.quote, quote)
        self.assertEqual(note.body, "EN: " + quote)
        highlight = Annotation.objects.get(
            user=self.user,
            kind=AnnotationKind.HIGHLIGHT,
        )
        self.assertEqual(highlight.quote, quote)

    def test_translation_falls_back_to_google_without_an_on_device_engine(self):
        self.context.add_init_script("delete window.Translator;")
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        self.page.wait_for_load_state("networkidle")
        self.select_prompt(start=0, end=12)
        self.page.locator("[data-translate-selection]").click()

        panel = self.page.locator("[data-translation-panel]")
        panel.wait_for()
        fallback = panel.locator("[data-translation-fallback]")
        panel.get_by_text(
            "On-device translation isn't available in this browser.",
            exact=True,
        ).wait_for()
        self.assertIn("is-suggested", fallback.get_attribute("class"))
        self.assertEqual(
            fallback.locator("[data-translation-fallback-label]").inner_text(),
            "Open Google Translate",
        )
        self.assertIn("translate.google.com", fallback.get_attribute("href"))

    def test_translation_uses_the_server_when_the_device_cannot_translate(self):
        class FakeResponse:
            def read(self):
                return json.dumps({"translatedText": "Hello there"}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        self.context.add_init_script("delete window.Translator;")
        with override_settings(
            TRANSLATION_API_URL="http://translate.test/translate"
        ), mock.patch(
            "study.views.notes.urllib.request.urlopen",
            lambda request, timeout=None: FakeResponse(),
        ):
            self.page.goto(
                self.live_server_url
                + reverse("study:review")
                + "?kind=spine&reset=1"
            )
            prompt = self.page.locator("#card-front .prompt-text")
            prompt.wait_for()
            self.page.wait_for_load_state("networkidle")
            self.select_prompt(start=0, end=12)
            self.page.locator("[data-translate-selection]").click()

            panel = self.page.locator("[data-translation-panel]")
            panel.wait_for()
            panel.get_by_text("Hello there", exact=True).wait_for()
            panel.get_by_text("Translated on the server.", exact=True).wait_for()

    def test_selection_note_paste_and_close_saves_and_highlights(self):
        self.context.add_init_script(
            """
            Object.defineProperty(navigator, "clipboard", {
              configurable: true,
              value: {
                readText: () => Promise.resolve("texte collé"),
              },
            });
            """
        )
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        self.page.wait_for_load_state("networkidle")
        self.select_prompt(start=0, end=12)
        self.page.locator("[data-note-selection]").click()

        panel = self.page.locator("[data-note-panel]")
        panel.wait_for()
        self.assertEqual(panel.locator("[data-note-save]").count(), 0)
        self.assertEqual(panel.locator("[data-note-undo]").count(), 0)
        panel.locator("[data-note-body]").fill("Avant ")

        with self.page.expect_response(
            lambda response: reverse("study:annotation_create") in response.url
        ) as create_response:
            panel.locator("[data-note-paste-close]").click()

        self.assertEqual(create_response.value.status, 201)
        panel.wait_for(state="hidden")
        self.page.get_by_text(
            "Note enregistrée et passage surligné.",
            exact=True,
        ).wait_for()
        self.assertEqual(
            Annotation.objects.get(
                user=self.user,
                kind=AnnotationKind.NOTE,
            ).body,
            "Avant texte collé",
        )
        highlight = Annotation.objects.get(
            user=self.user,
            kind=AnnotationKind.HIGHLIGHT,
        )
        self.assertEqual(highlight.quote, prompt.inner_text()[:12])
        prompt.locator("mark.user-highlight").wait_for()

    def test_selection_note_save_and_close_stores_note_and_highlight(self):
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        self.page.wait_for_load_state("networkidle")
        self.select_prompt(start=0, end=12)
        self.page.locator("[data-note-selection]").click()

        panel = self.page.locator("[data-note-panel]")
        panel.wait_for()
        panel.locator("[data-note-body]").fill("À retenir avec **attention**.")

        with self.page.expect_response(
            lambda response: reverse("study:annotation_create") in response.url
        ) as save_close_response:
            panel.locator("[data-note-save-close]").click()

        self.assertEqual(save_close_response.value.status, 201)
        panel.wait_for(state="hidden")
        self.page.get_by_text(
            "Note enregistrée et passage surligné.",
            exact=True,
        ).wait_for()
        self.assertEqual(
            Annotation.objects.get(
                user=self.user,
                kind=AnnotationKind.NOTE,
            ).body,
            "À retenir avec **attention**.",
        )
        highlight = Annotation.objects.get(
            user=self.user,
            kind=AnnotationKind.HIGHLIGHT,
        )
        self.assertEqual(highlight.quote, prompt.inner_text()[:12])
        prompt.locator("mark.user-highlight").wait_for()

    def test_stale_selection_note_save_does_not_close_a_new_note_panel(self):
        self.context.add_init_script(
            """
            (() => {
              const originalFetch = window.fetch.bind(window);
              window.__releaseSelectionNoteSave = [];
              window.__heldSelectionNoteSave = false;
              window.fetch = (url, options) => {
                const body = String((options && options.body) || "");
                if (
                  !window.__heldSelectionNoteSave
                  && body.includes("kind=note")
                ) {
                  window.__heldSelectionNoteSave = true;
                  return new Promise((resolve, reject) => {
                    window.__releaseSelectionNoteSave.push(() => {
                      originalFetch(url, options).then(resolve, reject);
                    });
                  });
                }
                return originalFetch(url, options);
              };
            })();
            """
        )
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        self.page.wait_for_load_state("networkidle")

        self.select_prompt(start=0, end=12)
        self.page.locator("[data-note-selection]").click()
        panel = self.page.locator("[data-note-panel]")
        panel.wait_for()
        panel.locator("[data-note-body]").fill("Première note.")
        panel.locator("[data-note-save-close]").click()
        self.page.wait_for_function(
            "() => window.__releaseSelectionNoteSave.length === 1"
        )

        panel.locator("[data-note-cancel]").click()
        panel.wait_for(state="hidden")
        self.select_prompt(start=1, end=10)
        self.page.locator("[data-note-selection]").click()
        panel.wait_for()
        panel.locator("[data-note-body]").fill("Nouvelle note non enregistrée.")

        self.page.evaluate("window.__releaseSelectionNoteSave[0]()")
        self.page.get_by_text(
            "Note enregistrée et passage surligné.",
            exact=True,
        ).wait_for()
        self.assertTrue(panel.is_visible())
        self.assertEqual(
            panel.locator("[data-note-body]").input_value(),
            "Nouvelle note non enregistrée.",
        )
        self.assertEqual(
            Annotation.objects.filter(
                user=self.user,
                kind=AnnotationKind.NOTE,
            ).count(),
            1,
        )
        self.assertEqual(
            Annotation.objects.filter(
                user=self.user,
                kind=AnnotationKind.HIGHLIGHT,
            ).count(),
            1,
        )

    def test_selection_toolbar_reads_with_premium_french_voice(self):
        self.context.add_init_script(
            """
            (() => {
              window.__speechClickTask = false;
              document.addEventListener("click", () => {
                window.__speechClickTask = true;
                setTimeout(() => {
                  window.__speechClickTask = false;
                }, 0);
              }, true);
              const voices = [
                {
                  name: "Audrey Premium",
                  voiceURI: "com.apple.voice.premium.fr-FR.Audrey",
                  lang: "fr-FR",
                  localService: true,
                  default: false,
                },
                {
                  name: "English",
                  voiceURI: "english",
                  lang: "en-US",
                  localService: true,
                  default: true,
                },
              ];
              const synthesis = {
                getVoices: () => voices,
                addEventListener: () => {},
                cancel: () => {
                  window.__speechCancelCount =
                    (window.__speechCancelCount || 0) + 1;
                },
                resume: () => {},
                speak: utterance => {
                  if (!window.__speechClickTask) return;
                  window.__spokenFrench = {
                    text: utterance.text,
                    lang: utterance.lang,
                    rate: utterance.rate,
                    voice: utterance.voice && utterance.voice.name,
                    startedInClick: window.__speechClickTask,
                  };
                },
              };
              class FakeUtterance {
                constructor(text) {
                  this.text = text;
                  this.lang = "";
                  this.rate = 1;
                  this.pitch = 1;
                  this.voice = null;
                }
              }
              Object.defineProperty(window, "speechSynthesis", {
                configurable: true,
                value: synthesis,
              });
              Object.defineProperty(window, "SpeechSynthesisUtterance", {
                configurable: true,
                value: FakeUtterance,
              });
            })();
            """
        )
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        self.page.wait_for_load_state("networkidle")
        card_read = self.page.locator("[data-review-card] [data-read-aloud]")
        card_read.click()
        self.page.wait_for_function("() => Boolean(window.__spokenFrench)")
        self.assertEqual(card_read.get_attribute("aria-pressed"), "true")
        self.page.evaluate("window.__spokenFrench = null")
        self.select_prompt(start=0, end=12)
        selected = self.page.evaluate("window.getSelection().toString().trim()")
        read_button = self.page.locator("[data-read-selection]")

        read_button.click()
        self.page.wait_for_function("() => Boolean(window.__spokenFrench)")
        self.assertEqual(read_button.get_attribute("aria-pressed"), "true")
        self.assertEqual(
            self.page.evaluate("window.__spokenFrench"),
            {
                "text": selected,
                "lang": "fr-FR",
                "rate": 0.92,
                "voice": "Audrey Premium",
                "startedInClick": True,
            },
        )
        self.assertGreaterEqual(
            self.page.evaluate("window.__speechCancelCount || 0"),
            1,
        )
        self.assertEqual(card_read.get_attribute("aria-pressed"), "false")
        self.assertEqual(
            self.page.evaluate("window.getSelection().toString().trim()"),
            selected,
        )

        read_button.click()
        self.assertEqual(read_button.get_attribute("aria-pressed"), "false")

    def test_pen_approach_keeps_touch_toolbar_stationary(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        self.page.locator("#card-front .prompt-text").wait_for()
        self.page.wait_for_load_state("networkidle")
        self.select_prompt()

        metrics = self.page.locator("[data-selection-translate]").evaluate(
            """
            async toolbar => {
              const html = document.documentElement;
              delete html.dataset.inputMode;
              const before = toolbar.getBoundingClientRect();
              toolbar.querySelector('button').dispatchEvent(
                new PointerEvent('pointerover', {
                  bubbles: true,
                  pointerId: 61,
                  pointerType: 'pen',
                  isPrimary: true,
                  clientX: before.left + 24,
                  clientY: before.top + 24,
                })
              );
              await new Promise(resolve =>
                requestAnimationFrame(() => requestAnimationFrame(resolve))
              );
              const after = toolbar.getBoundingClientRect();
              const dot = document.querySelector('[data-pen-cursor]');
              return {
                inputMode: html.dataset.inputMode || '',
                leftDelta: Math.abs(after.left - before.left),
                topDelta: Math.abs(after.top - before.top),
                widthDelta: Math.abs(after.width - before.width),
                dotVisible: dot.classList.contains('is-visible'),
                dotBackground: getComputedStyle(dot).backgroundColor,
              };
            }
            """
        )

        self.assertEqual(metrics["inputMode"], "")
        self.assertLessEqual(metrics["leftDelta"], 1)
        self.assertLessEqual(metrics["topDelta"], 1)
        self.assertLessEqual(metrics["widthDelta"], 1)
        self.assertTrue(metrics["dotVisible"])
        self.assertEqual(metrics["dotBackground"], "rgb(227, 38, 59)")

    def test_pen_pointer_is_red_stable_and_recovers_after_cancel(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        self.page.wait_for_load_state("networkidle")
        self.select_prompt()

        metrics = prompt.evaluate(
            """
            async prompt => {
              const html = document.documentElement;
              const toolbar = document.querySelector(
                '[data-selection-translate]'
              );
              const dot = document.querySelector('[data-pen-cursor]');
              delete html.dataset.inputMode;
              html.classList.remove('pen-cursor-hidden');
              dot.classList.remove('is-visible', 'is-pressed');
              const rootMutations = [];
              const toolbarMutations = [];
              const dotMutations = [];
              const rootObserver = new MutationObserver(records => {
                rootMutations.push(...records);
              });
              const toolbarObserver = new MutationObserver(records => {
                toolbarMutations.push(...records);
              });
              const dotObserver = new MutationObserver(records => {
                dotMutations.push(...records);
              });
              rootObserver.observe(html, {
                attributes: true,
                attributeFilter: ['data-input-mode', 'class'],
              });
              toolbarObserver.observe(toolbar, {
                attributes: true,
                attributeFilter: ['style'],
              });
              dotObserver.observe(dot, {
                attributes: true,
                attributeFilter: ['style'],
              });

              for (let index = 0; index < 120; index += 1) {
                prompt.dispatchEvent(new PointerEvent('pointermove', {
                  bubbles: true,
                  pointerId: 71,
                  pointerType: 'pen',
                  isPrimary: true,
                  clientX: 80 + index,
                  clientY: 180 + (index % 4),
                }));
              }
              await new Promise(resolve =>
                requestAnimationFrame(() => requestAnimationFrame(resolve))
              );

              const originalRangeRect = Range.prototype.getBoundingClientRect;
              const viewport = window.visualViewport;
              const viewportBottom = viewport
                ? viewport.offsetTop + viewport.height
                : window.innerHeight;
              const highFrequency = {
                inputModeMutations: rootMutations.filter(
                  mutation => mutation.attributeName === 'data-input-mode'
                ).length,
                cursorClassMutations: rootMutations.filter(
                  mutation => mutation.attributeName === 'class'
                ).length,
                toolbarStyleMutations: toolbarMutations.length,
                dotStyleMutations: dotMutations.length,
              };
              let rangeTop = 300;
              Range.prototype.getBoundingClientRect = function () {
                return new DOMRect(40, rangeTop, 310, 20);
              };
              window.dispatchEvent(new Event('resize'));
              await new Promise(resolve =>
                requestAnimationFrame(() => requestAnimationFrame(resolve))
              );
              const primaryToolbarRect = toolbar.getBoundingClientRect();
              const primaryGap = primaryToolbarRect.top - (rangeTop + 20);
              const primaryCenterDelta = Math.abs(
                (primaryToolbarRect.left + primaryToolbarRect.right) / 2 - 195
              );

              rangeTop = viewportBottom - 34;
              window.dispatchEvent(new Event('resize'));
              await new Promise(resolve =>
                requestAnimationFrame(() => requestAnimationFrame(resolve))
              );
              prompt.dispatchEvent(new PointerEvent('pointerdown', {
                bubbles: true,
                pointerId: 72,
                pointerType: 'pen',
                isPrimary: true,
                button: 0,
                clientX: 120,
                clientY: viewportBottom - 24,
              }));
              prompt.dispatchEvent(new PointerEvent('pointercancel', {
                bubbles: true,
                pointerId: 72,
                pointerType: 'pen',
                isPrimary: true,
                clientX: 120,
                clientY: viewportBottom - 24,
              }));
              await new Promise(resolve => setTimeout(resolve, 100));
              prompt.dispatchEvent(new PointerEvent('pointermove', {
                bubbles: true,
                pointerId: 71,
                pointerType: 'pen',
                isPrimary: true,
                clientX: 205,
                clientY: 205,
              }));
              await new Promise(resolve => setTimeout(resolve, 400));

              const toolbarRect = toolbar.getBoundingClientRect();
              const dotStyle = getComputedStyle(dot);
              const stable = {
                inputModeMutations: highFrequency.inputModeMutations,
                cursorClassMutations: highFrequency.cursorClassMutations,
                toolbarStyleMutations: highFrequency.toolbarStyleMutations,
                dotStyleMutations: highFrequency.dotStyleMutations,
                inputMode: html.dataset.inputMode,
                cursorHidden: html.classList.contains('pen-cursor-hidden'),
                mainCursor: getComputedStyle(
                  document.getElementById('main')
                ).cursor,
                dotBackground: dotStyle.backgroundColor,
                dotOpacity: dotStyle.opacity,
                dotTransform: dot.style.transform,
                dotPressed: dot.classList.contains('is-pressed'),
                toolbarBorder: getComputedStyle(toolbar).borderColor,
                toolbarVisible: !toolbar.classList.contains('hidden'),
                toolbarBottom: toolbarRect.bottom,
                selectionTop: viewportBottom - 34,
                viewportBottom,
                primaryGap,
                primaryCenterDelta,
                targets: [...toolbar.querySelectorAll(
                  'button:not([hidden])'
                )].map(button => {
                  const rect = button.getBoundingClientRect();
                  return {
                    width: rect.width,
                    height: rect.height,
                    touchAction: getComputedStyle(button).touchAction,
                  };
                }),
              };
              Range.prototype.getBoundingClientRect = originalRangeRect;

              document.dispatchEvent(new PointerEvent('pointerout', {
                bubbles: true,
                pointerId: 71,
                pointerType: 'pen',
                isPrimary: true,
                relatedTarget: null,
              }));
              await new Promise(resolve => setTimeout(resolve, 500));
              stable.cursorReleased =
                !html.classList.contains('pen-cursor-hidden');
              stable.dotHidden = !dot.classList.contains('is-visible');
              rootObserver.disconnect();
              toolbarObserver.disconnect();
              dotObserver.disconnect();
              return stable;
            }
            """
        )

        self.assertEqual(metrics["inputModeMutations"], 1)
        self.assertEqual(metrics["cursorClassMutations"], 1)
        self.assertLessEqual(metrics["toolbarStyleMutations"], 2)
        self.assertLessEqual(metrics["dotStyleMutations"], 2)
        self.assertEqual(metrics["inputMode"], "pen")
        self.assertTrue(metrics["cursorHidden"])
        self.assertEqual(metrics["mainCursor"], "none")
        self.assertEqual(metrics["dotBackground"], "rgb(227, 38, 59)")
        self.assertEqual(metrics["dotOpacity"], "1")
        self.assertIn("translate3d(205px, 205px", metrics["dotTransform"])
        self.assertFalse(metrics["dotPressed"])
        self.assertEqual(metrics["toolbarBorder"], "rgb(227, 38, 59)")
        self.assertTrue(metrics["toolbarVisible"])
        self.assertGreaterEqual(metrics["primaryGap"], 27)
        self.assertLessEqual(metrics["primaryGap"], 29)
        self.assertLessEqual(metrics["primaryCenterDelta"], 1)
        self.assertLessEqual(
            metrics["toolbarBottom"],
            metrics["viewportBottom"] - 8,
        )
        self.assertGreaterEqual(
            metrics["selectionTop"] - metrics["toolbarBottom"],
            27,
        )
        self.assertTrue(
            all(
                target["width"] >= 48
                and target["height"] >= 48
                and target["touchAction"] == "manipulation"
                for target in metrics["targets"]
            )
        )
        self.assertTrue(metrics["cursorReleased"])
        self.assertTrue(metrics["dotHidden"])

    def test_selection_toolbar_hides_after_selection_collapses(self):
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        self.page.wait_for_load_state("networkidle")
        self.select_prompt()

        hidden = prompt.evaluate(
            """
            async prompt => {
              const rangeRect = window.getSelection()
                .getRangeAt(0)
                .getBoundingClientRect();
              const eventData = {
                bubbles: true,
                pointerId: 81,
                pointerType: 'pen',
                isPrimary: true,
                clientX: rangeRect.left + Math.min(20, rangeRect.width / 2),
                clientY: rangeRect.top + Math.min(10, rangeRect.height / 2),
              };
              prompt.dispatchEvent(new PointerEvent('pointerdown', {
                ...eventData,
                button: 0,
              }));
              window.getSelection().removeAllRanges();
              document.dispatchEvent(new Event('selectionchange'));
              prompt.dispatchEvent(new PointerEvent('pointerup', eventData));
              await new Promise(resolve => setTimeout(resolve, 120));
              return document.querySelector(
                '[data-selection-translate]'
              ).classList.contains('hidden');
            }
            """
        )

        self.assertTrue(hidden)

    def test_expired_session_does_not_fake_unhighlight_success(self):
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        self.page.wait_for_load_state("networkidle")
        self.save_current_prompt_highlight()
        prompt.locator("mark.user-highlight").wait_for()

        self.select_prompt()
        highlight_button = self.page.locator("[data-highlight-selection]")
        self.assertEqual(
            highlight_button.get_attribute("aria-label"),
            "Unhighlight selected text",
        )
        session_key = next(
            cookie["value"]
            for cookie in self.context.cookies()
            if cookie["name"] == "sessionid"
        )
        Session.objects.filter(session_key=session_key).delete()

        with self.page.expect_response(
            lambda response: (
                "/notes/" in response.url
                and "/supprimer/" in response.url
            )
        ):
            highlight_button.click()
        self.page.locator(
            "[data-annotation-toast]",
            has_text="Votre session a expiré",
        ).wait_for()
        self.assertEqual(prompt.locator("mark.user-highlight").count(), 1)
        self.assertTrue(
            Annotation.objects.filter(
                user=self.user,
                kind=AnnotationKind.HIGHLIGHT,
            ).exists()
        )

    def test_legacy_response_highlight_renders_inside_new_annotation_root(self):
        response = self.first.response
        detail_url = response_detail_url(response)
        quote = response.arguments.get().exemple
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote=quote,
            source_path=detail_url,
            source_key="",
            start_offset=0,
            end_offset=len(quote),
        )

        self.page.goto(self.live_server_url + detail_url)
        self.page.wait_for_load_state("networkidle")
        restored = self.page.locator(
            ".answer-columns mark.user-highlight",
            has_text=quote,
        )

        restored.wait_for(timeout=5000)
        self.assertEqual(restored.text_content(), quote)

    def test_personalized_response_keeps_unchanged_text_highlighted(self):
        response = self.first.response
        detail_url = response_detail_url(response)
        self.page.goto(self.live_server_url + detail_url)
        target = self.page.locator(".arg__part p").first
        target.wait_for()
        quote = target.text_content()
        target.evaluate(
            """
            element => {
              const range = document.createRange();
              range.selectNodeContents(element);
              const selection = window.getSelection();
              selection.removeAllRanges();
              selection.addRange(range);
              document.dispatchEvent(new Event("selectionchange"));
            }
            """
        )
        highlight_button = self.page.locator("[data-highlight-selection]")
        highlight_button.wait_for(state="visible")
        with self.page.expect_response(
            lambda browser_response: (
                reverse("study:annotation_create") in browser_response.url
            )
        ):
            highlight_button.click()
        target.locator("mark.user-highlight").wait_for()
        saved = Annotation.objects.get(
            user=self.user,
            kind=AnnotationKind.HIGHLIGHT,
        )

        argument = response.arguments.get()
        PersonalResponse.objects.create(
            user=self.user,
            response=response,
            reformulation=(
                "Une nouvelle reformulation beaucoup plus longue déplace "
                "le reste de la réponse."
            ),
            position="Ma position personnelle ajoute encore du texte.",
            position_claire="Une introduction personnelle détaillée.",
            arguments=[
                {
                    "order": argument.order,
                    "idea": "Mon idée personnalisée.",
                    "developpement": "Un développement ajouté avant l'exemple.",
                    "exemple": argument.exemple,
                    "consequence": "Une conséquence personnalisée.",
                }
            ],
            nuance="Ma nuance personnelle.",
            conclusion="Ma conclusion personnelle.",
        )

        self.page.goto(self.live_server_url + detail_url + "?saved=1")
        restored = self.page.locator(
            "mark.user-highlight",
            has_text=quote,
        )
        restored.wait_for()
        self.assertEqual(restored.text_content(), quote)
        saved.refresh_from_db()
        self.assertEqual(saved.quote, quote)

    def test_mobile_review_recovers_a_rotated_presentation_token(self):
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        first_prompt = prompt.text_content()
        self.page.locator("#reveal").click()

        session = ReviewSession.load(self.user)
        active_card = session.current_card
        session.presentation_token = "replacement-token"
        session.save(update_fields=["presentation_token"])

        self.page.locator('[data-action="revisit"]').click()
        self.page.wait_for_function(
            """
            previous => {
              const current = document.querySelector("#card-front .prompt-text");
              return current && current.textContent !== previous;
            }
            """,
            arg=first_prompt,
        )

        active_card.refresh_from_db()
        self.assertTrue(active_card.needs_revisit)
        self.assertEqual(
            ReviewLog.objects.filter(card=active_card).count(),
            1,
        )

    def test_mobile_highlights_group_by_date_with_source_chips(self):
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Une note personnelle.",
        )
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Passage retenu dans une réponse.",
            source_path=response_detail_url(self.first.response),
            source_key="response:culture:p1:back",
            start_offset=1,
            end_offset=33,
        )
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Passage retenu dans une expression.",
            source_path=reverse("study:review") + "?kind=phrase",
            source_key="phrase:expr-1:phrase_production:back",
            start_offset=1,
            end_offset=35,
        )

        notes_url = (
            self.live_server_url
            + reverse(
                "study:task_notes",
                args=[self.part.slug, self.task.slug],
            )
        )
        self.page.goto(notes_url)
        self.page.locator(
            ".annotation-card__body",
            has_text="Une note personnelle.",
        ).wait_for()
        tab_styles = self.page.locator(".notes-tabs").evaluate(
            """
            tabs => {
              const active = tabs.querySelector('.notes-tab.is-active');
              const inactive = tabs.querySelector(
                '.notes-tab:not(.is-active)'
              );
              const probe = document.createElement('span');
              probe.style.background = 'var(--primary-soft)';
              document.body.appendChild(probe);
              const primarySoft = getComputedStyle(probe).backgroundColor;
              probe.remove();
              return {
                shellBackground: getComputedStyle(tabs).backgroundColor,
                shellBorder: getComputedStyle(tabs).borderTopWidth,
                shellRadius: parseFloat(
                  getComputedStyle(tabs).borderRadius
                ),
                activeBackground: getComputedStyle(active).backgroundColor,
                activeRadius: parseFloat(
                  getComputedStyle(active).borderRadius
                ),
                segmentGap: inactive.getBoundingClientRect().left
                  - active.getBoundingClientRect().right,
                primarySoft,
              };
            }
            """
        )
        self.assertNotEqual(
            tab_styles["shellBackground"],
            "rgba(0, 0, 0, 0)",
        )
        self.assertEqual(tab_styles["shellBorder"], "1px")
        self.assertGreater(tab_styles["shellRadius"], 100)
        self.assertEqual(
            tab_styles["activeBackground"],
            tab_styles["primarySoft"],
        )
        self.assertGreater(tab_styles["activeRadius"], 100)
        self.assertLessEqual(tab_styles["segmentGap"], 4)
        self.assertFalse(
            self.page.locator(
                ".collection-table--annotations [data-collection-table-header]"
            ).first.is_visible()
        )
        # Card mode renders exactly one node for the note.
        self.assertEqual(self.page.locator("[data-annotation-item]").count(), 1)
        action_icons = self.page.locator(
            ".annotation-card",
            has_text="Une note personnelle.",
        ).locator(".annotation-action__icon")
        # No selected passage on this note, so no read control.
        self.assertEqual(action_icons.count(), 4)

        self.page.get_by_role("button", name="Tableau").click()
        notes_table = self.page.locator(".collection-table--annotations")
        notes_table.locator(
            ".annotation-card__body",
            has_text="Une note personnelle.",
        ).wait_for()
        # The very same node becomes the row: the toggle never duplicates it.
        self.assertEqual(self.page.locator("[data-annotation-item]").count(), 1)
        self.assertEqual(
            notes_table.evaluate("table => getComputedStyle(table).display"),
            "flex",
        )
        self.assertEqual(
            notes_table.locator(".annotation-card").evaluate(
                "row => getComputedStyle(row).display"
            ),
            "grid",
        )
        action_icons = self.page.locator(
            ".annotation-card",
            has_text="Une note personnelle.",
        ).locator(".annotation-action__icon")
        # No selected passage on this note, so no read control.
        self.assertEqual(action_icons.count(), 4)
        icon_styles = action_icons.evaluate_all(
            """
            icons => icons.map(icon => {
              const style = getComputedStyle(icon);
              return {
                color: style.color,
                background: style.backgroundColor,
              };
            })
            """
        )
        self.assertGreaterEqual(
            len({style["color"] for style in icon_styles}),
            4,
        )
        self.assertTrue(
            all(
                style["background"] != "rgba(0, 0, 0, 0)"
                for style in icon_styles
            )
        )
        self.assertEqual(
            self.page.locator("#notes-tab").get_attribute("aria-selected"),
            "true",
        )
        self.assertEqual(
            self.page.get_by_text("Passage retenu dans une réponse.").count(),
            0,
        )

        self.page.locator("#highlights-tab").click()
        self.page.wait_for_url("**tab=highlights")
        self.assertEqual(
            self.page.locator("#highlights-tab").get_attribute(
                "aria-selected"
            ),
            "true",
        )

        today_section = self.page.locator(
            '[aria-labelledby="highlights-today-heading"]'
        )
        today_section.get_by_text(
            "Passage retenu dans une réponse."
        ).wait_for()
        today_section.get_by_text(
            "Passage retenu dans une expression."
        ).wait_for()

        response_card = self.page.locator(
            ".annotation-card",
            has_text="Passage retenu dans une réponse.",
        )
        expression_card = self.page.locator(
            ".annotation-card",
            has_text="Passage retenu dans une expression.",
        )
        self.assertEqual(
            response_card.locator(".annotation-card__origin")
            .text_content()
            .strip(),
            "Réponse",
        )
        self.assertEqual(
            expression_card.locator(".annotation-card__origin")
            .text_content()
            .strip(),
            "Expression",
        )
        self.assert_no_horizontal_overflow()

        self.page.set_viewport_size({"width": 1200, "height": 800})
        self.page.reload()
        highlights_table = self.page.locator(".collection-table--annotations")
        header = highlights_table.locator("[data-collection-table-header]")
        header.wait_for(state="visible")
        self.assertEqual(
            header.locator("span").nth(1).inner_text().strip(),
            "Passage",
        )
        rows = highlights_table.locator("[data-collection-item]")
        self.assertEqual(rows.count(), 2)
        header_tracks = header.evaluate(
            "element => getComputedStyle(element).gridTemplateColumns"
        )
        self.assertEqual(
            rows.evaluate_all(
                "elements => elements.map("
                "element => getComputedStyle(element).gridTemplateColumns)"
            ),
            [header_tracks, header_tracks],
        )
        self.assertEqual(
            rows.first.evaluate("row => getComputedStyle(row).display"),
            "grid",
        )
        row_edge_offsets = self.page.evaluate(
            """
            () => {
              const headerCells = [
                ...document.querySelectorAll(
                  '.collection-table--annotations '
                  + '[data-collection-table-header] > span'
                )
              ];
              return [
                ...document.querySelectorAll(
                  '.collection-table--annotations [data-collection-item]'
                )
              ].map(row => [...row.children].map((cell, index) => {
                return Math.abs(
                  cell.getBoundingClientRect().left
                  - headerCells[index].getBoundingClientRect().left
                );
              }));
            }
            """
        )
        self.assertTrue(
            all(
                offset <= 1
                for row_offsets in row_edge_offsets
                for offset in row_offsets
            )
        )
        self.assertEqual(
            highlights_table.locator(
                ".annotation-card__actions"
            ).first.evaluate(
                "actions => getComputedStyle(actions).justifyContent"
            ),
            "flex-start",
        )
        self.page.get_by_role("button", name="Cartes").click()
        self.page.locator(
            ".annotation-card",
            has_text="Passage retenu dans une réponse.",
        ).wait_for()
        self.assertFalse(header.is_visible())
        self.assertEqual(rows.count(), 2)
        self.assert_no_horizontal_overflow()

    def test_collection_view_choice_persists_across_catalogs(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Préférence globale d’affichage.",
        )
        self.page.set_viewport_size({"width": 1200, "height": 800})
        task_url = self.live_server_url + reverse(
            "study:task_browse",
            args=[self.part.slug, self.task.slug],
        )
        self.page.goto(task_url)

        collection = self.page.locator(
            ".grid--decks[data-collection-view='adaptive']"
        )
        collection.locator("[data-collection-item]").first.wait_for()
        self.assertEqual(
            collection.evaluate(
                "element => getComputedStyle(element).display"
            ),
            "grid",
        )
        self.assertEqual(
            self.page.get_by_role("button", name="Cartes").get_attribute(
                "aria-pressed"
            ),
            "true",
        )

        self.page.get_by_role("button", name="Tableau").click()
        header = collection.locator("[data-collection-table-header]")
        self.assertTrue(header.is_visible())
        self.assertEqual(
            header.locator("span").all_text_contents(),
            ["Thème", "Contenu", "Progression", "État"],
        )
        self.assertEqual(
            collection.evaluate(
                "element => getComputedStyle(element).display"
            ),
            "flex",
        )
        self.assertEqual(
            collection.locator("[data-collection-item]").first.evaluate(
                "item => getComputedStyle(item).borderRadius"
            ),
            "0px",
        )
        self.assertEqual(
            header.evaluate("element => getComputedStyle(element).gridTemplateColumns"),
            collection.locator(".deck__body").first.evaluate(
                "element => getComputedStyle(element).gridTemplateColumns"
            ),
        )
        self.assertLess(
            collection.locator("[data-collection-item]")
            .first.bounding_box()["height"],
            80,
        )
        self.assertEqual(
            self.page.evaluate(
                "localStorage.getItem('collectionViewMode')"
            ),
            "table",
        )
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertFalse(header.is_visible())
        self.assert_no_horizontal_overflow()

        self.page.set_viewport_size({"width": 1200, "height": 800})
        self.page.goto(
            self.live_server_url
            + theme_detail_url(self.theme)
        )
        response_list = self.page.locator(
            ".qlist[data-collection-view='adaptive']"
        )
        response_list.locator("[data-collection-item]").first.wait_for()
        self.assertEqual(
            response_list.evaluate(
                "element => getComputedStyle(element).display"
            ),
            "flex",
        )
        self.assertEqual(
            response_list.locator("[data-collection-item]").first.evaluate(
                "item => getComputedStyle(item).borderRadius"
            ),
            "0px",
        )
        response_header = response_list.locator(
            "[data-collection-table-header]"
        )
        self.assertEqual(
            response_header.evaluate(
                "element => getComputedStyle(element).gridTemplateColumns"
            ),
            response_list.locator("[data-collection-item]").first.evaluate(
                "element => getComputedStyle(element).gridTemplateColumns"
            ),
        )

        self.page.goto(
            self.live_server_url
            + reverse(
                "study:task_notes",
                args=[self.part.slug, self.task.slug],
            )
        )
        note_table = self.page.locator(".collection-table--annotations")
        note_table.locator(
            ".annotation-card__body",
            has_text="Préférence globale d’affichage.",
        ).wait_for()
        note_header = note_table.locator("[data-collection-table-header]")
        self.assertTrue(note_header.is_visible())
        self.assertEqual(
            self.page.get_by_role("button", name="Tableau").get_attribute(
                "aria-pressed"
            ),
            "true",
        )

        self.page.get_by_role("button", name="Cartes").click()
        self.page.locator(
            ".annotation-card",
            has_text="Préférence globale d’affichage.",
        ).wait_for()
        self.assertFalse(note_header.is_visible())
        # The anchor resolves against the one node, in either view mode.
        self.page.goto(
            self.page.url.split("#", 1)[0] + f"#note-{note.id}"
        )
        note_card = self.page.locator(f"#note-{note.id}")
        self.assertEqual(
            self.page.locator(f'[data-annotation-item="{note.id}"]').count(),
            1,
        )
        self.assertTrue(
            note_card.evaluate(
                "card => card.classList.contains('is-annotation-anchor')"
            )
        )
        self.page.get_by_role("button", name="Tableau").click()
        self.assertTrue(
            note_card.evaluate(
                "row => row.classList.contains('is-annotation-anchor')"
            )
        )
        self.page.get_by_role("button", name="Cartes").click()
        self.page.goto(task_url)
        self.assertEqual(
            collection.evaluate(
                "element => getComputedStyle(element).display"
            ),
            "grid",
        )
        self.assert_no_horizontal_overflow()

    def test_comprehension_table_uses_real_compact_columns(self):
        first = factories.make_comprehension_test(
            number=1,
            question_count=31,
            mode=ComprehensionMode.ORALE,
        )
        factories.make_comprehension_test(
            number=4,
            question_count=24,
            mode=ComprehensionMode.ORALE,
        )
        factories.make_comprehension_test(
            number=5,
            question_count=28,
            mode=ComprehensionMode.ORALE,
        )
        factories.make_comprehension_attempt(
            user=self.user,
            test=first,
            answered_questions=3,
        )

        self.page.set_viewport_size({"width": 1440, "height": 900})
        self.page.goto(
            self.live_server_url
            + reverse("study:comprehension_oral_group", args=[1])
        )
        self.page.get_by_role("button", name="Tableau").click()
        table = self.page.locator(".collection-table--tests")
        header = table.locator("[data-collection-table-header]")
        first_row = table.locator("[data-collection-item]").first

        self.assertEqual(
            header.locator("span").all_text_contents(),
            ["Test", "Détails", "Questions", "Progression", "Action"],
        )
        self.assertEqual(
            header.evaluate(
                "element => getComputedStyle(element).gridTemplateColumns"
            ),
            first_row.evaluate(
                "element => getComputedStyle(element).gridTemplateColumns"
            ),
        )
        self.assertLessEqual(first_row.bounding_box()["height"], 88)
        aligned_edges = self.page.evaluate(
            """
            () => {
              const headerCells = [
                ...document.querySelectorAll(
                  '.collection-table--tests [data-collection-table-header] > span'
                )
              ];
              const rowCells = [
                ...document.querySelector(
                  '.collection-table--tests [data-collection-item]'
                ).children
              ];
              return headerCells.map((cell, index) => {
                const headerRect = cell.getBoundingClientRect();
                const rowRect = rowCells[index].getBoundingClientRect();
                return Math.abs(headerRect.left - rowRect.left);
              });
            }
            """
        )
        self.assertTrue(all(offset <= 1 for offset in aligned_edges))
        self.assert_no_horizontal_overflow()

        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertFalse(header.is_visible())
        mobile_rows = table.locator("[data-collection-item]")
        mobile_heights = mobile_rows.evaluate_all(
            "rows => rows.map(row => row.getBoundingClientRect().height)"
        )
        self.assertLessEqual(max(mobile_heights), 214)
        self.assertLessEqual(mobile_heights[1], 120)
        self.assertNotEqual(
            mobile_rows.first.evaluate(
                "row => getComputedStyle(row).borderRadius"
            ),
            "0px",
        )
        self.assert_no_horizontal_overflow()

    def test_annotation_search_rows_keep_identical_columns(self):
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="Alignement principal",
            body="Contenu pour vérifier les colonnes.",
            source_path=response_detail_url(self.first.response),
        )
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="Alignement secondaire",
            body="Une ligne sans lien de source.",
        )
        self.page.set_viewport_size({"width": 1200, "height": 800})
        self.page.goto(
            self.live_server_url
            + reverse("study:annotation_search")
            + "?q=alignement"
        )
        self.page.get_by_role("button", name="Tableau").click()

        table = self.page.locator(".collection-table--annotation-search")
        header = table.locator("[data-collection-table-header]")
        rows = table.locator("[data-collection-item]")
        self.assertEqual(rows.count(), 2)
        header_tracks = header.evaluate(
            "element => getComputedStyle(element).gridTemplateColumns"
        )
        self.assertEqual(
            rows.evaluate_all(
                "elements => elements.map("
                "element => getComputedStyle(element).gridTemplateColumns)"
            ),
            [header_tracks, header_tracks],
        )
        row_edge_offsets = self.page.evaluate(
            """
            () => {
              const headerCells = [
                ...document.querySelectorAll(
                  '.collection-table--annotation-search '
                  + '[data-collection-table-header] > span'
                )
              ];
              return [
                ...document.querySelectorAll(
                  '.collection-table--annotation-search '
                  + '[data-collection-item]'
                )
              ].map(row => [...row.children].map((cell, index) => {
                return Math.abs(
                  cell.getBoundingClientRect().left
                  - headerCells[index].getBoundingClientRect().left
                );
              }));
            }
            """
        )
        self.assertTrue(
            all(
                offset <= 1
                for row_offsets in row_edge_offsets
                for offset in row_offsets
            )
        )
        self.assert_no_horizontal_overflow()

    def test_mobile_note_dialogs_create_and_edit_cleanly(self):
        self.disable_service_worker()
        notes_url = (
            self.live_server_url
            + reverse(
                "study:task_notes",
                args=[self.part.slug, self.task.slug],
            )
        )
        self.page.goto(notes_url)
        self.page.get_by_role("button", name="Nouvelle note").click()

        create_dialog = self.page.locator("#note-create-dialog")
        create_dialog.wait_for(state="visible")
        dialog_box = create_dialog.bounding_box()
        viewport = self.page.viewport_size
        self.assertIsNotNone(dialog_box)
        self.assertLess(
            abs(
                dialog_box["x"]
                + dialog_box["width"] / 2
                - viewport["width"] / 2
            ),
            4,
        )
        self.assertLess(
            abs(
                dialog_box["y"]
                + dialog_box["height"] / 2
                - viewport["height"] / 2
            ),
            24,
        )

        create_dialog.get_by_label("Titre (facultatif)").fill(
            "Note créée dans la fenêtre"
        )
        create_dialog.get_by_label("Votre note").fill(
            "Première version avec **un point important**."
        )
        create_dialog.get_by_role("button", name="Enregistrer").click()

        note_card = self.page.locator(
            ".annotation-card",
            has_text="Note créée dans la fenêtre",
        )
        note_card.wait_for()
        note_card.locator(
            "strong",
            has_text="un point important",
        ).wait_for()
        self.assertTrue(self.page.url.split("#")[-1].startswith("note-"))

        note_card.get_by_role("button", name="Modifier la note").click()
        edit_dialog = self.page.locator("#note-edit-dialog")
        edit_dialog.wait_for(state="visible")
        self.assertEqual(
            edit_dialog.get_by_label("Titre (facultatif)").input_value(),
            "Note créée dans la fenêtre",
        )
        self.assertEqual(
            edit_dialog.get_by_label("Votre note").input_value(),
            "Première version avec **un point important**.",
        )
        edit_dialog.get_by_label("Votre note").fill("")
        edit_dialog.get_by_role("button", name="Enregistrer").click()
        edit_dialog.get_by_text(
            "Corrigez la note avant de l'enregistrer."
        ).wait_for()
        self.assertTrue(edit_dialog.is_visible())
        edit_dialog.get_by_label("Votre note").fill(
            "Version *corrigée* depuis la fenêtre."
        )
        edit_dialog.get_by_role("button", name="Enregistrer").click()
        self.page.locator(
            ".annotation-card__body",
            has_text="Version corrigée depuis la fenêtre.",
        ).wait_for()
        self.page.locator(
            ".annotation-card__body em",
            has_text="corrigée",
        ).wait_for()

        self.page.get_by_role("button", name="Tableau").click()
        note_row = self.page.locator(
            ".annotation-card",
            has_text="Version corrigée depuis la fenêtre.",
        )
        note_row.wait_for()
        # The edit updated the one node the table mode reuses.
        self.assertEqual(note_row.count(), 1)
        action_buttons = note_row.locator(".annotation-action")
        # A free-standing note reads its optional French title.
        self.assertEqual(action_buttons.count(), 5)
        self.assertTrue(
            all(
                44 <= size["width"] <= 46 and 44 <= size["height"] <= 46
                for size in action_buttons.evaluate_all(
                    """
                    buttons => buttons.map(button => {
                      const rect = button.getBoundingClientRect();
                      return {width: rect.width, height: rect.height};
                    })
                    """
                )
            )
        )
        self.assert_no_horizontal_overflow()

    def test_mobile_annotation_search_study_and_weak_drill(self):
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="Nuance utile",
            body="Le mot toujours est trop fort.",
            study_later=True,
        )
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Cependant, il faut reconnaître cette limite.",
            source_path=response_detail_url(self.first.response),
            start_offset=0,
            end_offset=45,
            study_later=True,
        )
        self.first.state = CardState.REVIEW
        self.first.due = timezone.now() + timezone.timedelta(days=20)
        self.first.interval_days = 8
        self.first.reps = 3
        self.first.last_rating = Rating.AGAIN
        self.first.save(
            update_fields=[
                "state",
                "due",
                "interval_days",
                "reps",
                "last_rating",
            ]
        )
        self.page.set_viewport_size({"width": 320, "height": 568})

        self.page.goto(
            self.live_server_url + reverse("study:annotation_search")
        )
        self.assert_no_horizontal_overflow()
        self.page.locator('input[name="q"]').fill("toujours")
        self.page.get_by_role("button", name="Rechercher").click()
        self.page.wait_for_url("**?q=toujours**")
        self.page.get_by_text("Le mot toujours est trop fort.").wait_for()
        self.assert_no_horizontal_overflow()

        self.page.goto(
            self.live_server_url + reverse("study:annotation_study")
        )
        self.page.locator("[data-study-card]:not(.hidden)").wait_for()
        self.assert_no_horizontal_overflow()
        for _ in range(2):
            self.page.locator("[data-study-reveal]").click()
            self.page.locator(
                "[data-study-card]:not(.hidden) [data-study-back]:not(.hidden)"
            ).wait_for()
            self.page.locator("[data-study-next]").click()
        self.page.locator("[data-study-done]:not(.hidden)").wait_for()
        self.assert_no_horizontal_overflow()

        self.page.goto(
            self.live_server_url
            + reverse(
                "study:task_review_hub",
                args=[self.part.slug, self.task.slug],
            )
        )
        self.page.get_by_text("Réponses fragiles").wait_for()
        self.assert_no_horizontal_overflow()
        self.page.get_by_role("link", name="Entraîner").click()
        self.page.locator("#card-front .prompt-text").wait_for()
        self.assert_no_horizontal_overflow()

    def test_query_flashcards_flip_and_can_start_with_the_note(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            quote="séance",
            body="showing",
        )
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            quote="autre passage",
            body="unrelated note",
        )
        self.page.set_viewport_size({"width": 320, "height": 568})
        self.page.goto(
            self.live_server_url
            + reverse(
                "study:task_notes",
                args=[self.part.slug, self.task.slug],
            )
            + "?q=showing"
        )
        self.page.get_by_role("link", name="Flashcards").click()
        self.page.wait_for_url("**?mode=all&tab=notes&q=showing")

        card = self.page.locator("[data-study-card]")
        self.assertEqual(card.count(), 1)
        self.assertEqual(card.get_attribute("data-study-id"), str(note.pk))
        front = self.page.locator("[data-study-front]")
        back = self.page.locator("[data-study-back]")
        face_label = card.locator("[data-flashcard-face-label]")
        face_switch = self.page.locator("[data-flashcard-order]")
        self.assertEqual(face_switch.count(), 2)
        switch_boxes = face_switch.evaluate_all(
            """
            buttons => buttons.map(button => {
              const rect = button.getBoundingClientRect();
              return {width: rect.width, height: rect.height};
            })
            """
        )
        self.assertAlmostEqual(
            switch_boxes[0]["width"],
            switch_boxes[1]["width"],
            delta=1,
        )
        self.assertTrue(
            all(box["height"] >= 44 for box in switch_boxes)
        )
        previous_box = self.page.locator(
            "[data-study-previous]"
        ).bounding_box()
        reveal_box = self.page.locator("[data-study-reveal]").bounding_box()
        next_box = self.page.locator("[data-study-next]").bounding_box()
        self.assertAlmostEqual(previous_box["y"], reveal_box["y"], delta=1)
        self.assertAlmostEqual(next_box["y"], reveal_box["y"], delta=1)
        self.assertAlmostEqual(
            previous_box["height"], reveal_box["height"], delta=1
        )
        self.assertAlmostEqual(
            previous_box["width"], reveal_box["width"], delta=1
        )
        self.assertAlmostEqual(
            next_box["width"], reveal_box["width"], delta=1
        )
        self.assertGreater(next_box["x"], reveal_box["x"])
        front.get_by_text("séance", exact=True).wait_for()
        self.assertEqual(face_label.inner_text(), "Recto")
        self.assertFalse(back.get_by_text("showing", exact=True).is_visible())

        card.click()

        back.get_by_text("showing", exact=True).wait_for()
        self.assertEqual(face_label.inner_text(), "Verso")
        # Revealing the answer never changes the control row: the deck only
        # ever offers Précédente / Retourner / Suivante.
        control_boxes = self.page.locator(
            "[data-flashcard-controls] .btn:not(.hidden)"
        ).evaluate_all(
            """
            buttons => buttons.map(button => {
              const rect = button.getBoundingClientRect();
              return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
            })
            """
        )
        self.assertEqual(len(control_boxes), 3)
        self.assertTrue(
            all(
                abs(box["y"] - control_boxes[0]["y"]) <= 1
                and abs(box["width"] - control_boxes[0]["width"]) <= 1
                and abs(box["height"] - control_boxes[0]["height"]) <= 1
                for box in control_boxes
            )
        )
        self.assertEqual(self.page.locator("[data-study-keep]").count(), 0)
        self.assertEqual(
            self.page.locator("[data-study-learned]").count(), 0
        )
        self.assertFalse(front.is_visible())
        self.assertFalse(
            front.get_by_text("séance", exact=True).is_visible()
        )

        # Click the answer text itself: the middle of the card is occupied by
        # the card action buttons, which must never flip the card.
        back.get_by_text("showing", exact=True).click()
        front.get_by_text("séance", exact=True).wait_for()
        self.assertEqual(face_label.inner_text(), "Recto")
        self.assertFalse(back.is_visible())

        self.page.locator('[data-flashcard-order="back"]').click()
        self.assertEqual(
            self.page.locator(
                '[data-flashcard-order="back"]'
            ).get_attribute("aria-pressed"),
            "true",
        )
        back.get_by_text("showing", exact=True).wait_for()
        self.assertEqual(face_label.inner_text(), "Verso")
        self.assertFalse(front.is_visible())

        back.get_by_text("showing", exact=True).click()
        front.get_by_text("séance", exact=True).wait_for()
        self.assertEqual(face_label.inner_text(), "Recto")
        self.assertFalse(back.is_visible())
        self.assert_no_horizontal_overflow()

    def test_personal_notes_are_split_and_flashcards_use_arrow_keys(self):
        older = Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            title="Objectif ancien",
            body="Relire mes expressions.",
        )
        newer = Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            title="Objectif récent",
            body="Pratiquer dix minutes.",
        )
        general = Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            quote="Expression générale",
            body="Note rattachée à une source.",
            source_path="/vocabulaire/",
        )

        self.page.goto(self.live_server_url + reverse("study:general_notes"))
        self.page.get_by_text(general.body, exact=True).first.wait_for()
        self.assertEqual(
            self.page.get_by_text(newer.body, exact=True).count(),
            0,
        )
        self.page.locator(".notes-mobile-scope summary").click()
        self.page.get_by_role(
            "link",
            name="Personnelles 2",
            exact=True,
        ).click()
        self.page.wait_for_url(
            self.live_server_url + reverse("study:custom_notes")
        )
        self.page.get_by_text(newer.body, exact=True).first.wait_for()
        self.assertEqual(
            self.page.get_by_text(general.body, exact=True).count(),
            0,
        )
        self.assertEqual(self.page.locator("#highlights-tab").count(), 0)

        self.page.get_by_role("link", name="Flashcards", exact=True).click()
        visible_card = self.page.locator("[data-study-card]:not(.hidden)")
        face_label = visible_card.locator("[data-flashcard-face-label]")
        self.assertEqual(visible_card.get_attribute("data-study-id"), str(newer.pk))
        self.assertIn(
            "ArrowUp",
            visible_card.get_attribute("aria-keyshortcuts"),
        )

        self.page.keyboard.press("ArrowDown")
        self.assertEqual(face_label.inner_text(), "Verso")
        self.page.keyboard.press("ArrowUp")
        self.assertEqual(face_label.inner_text(), "Recto")
        self.page.keyboard.press("ArrowRight")
        self.assertEqual(
            visible_card.get_attribute("data-study-id"),
            str(older.pk),
        )
        self.page.keyboard.press("ArrowLeft")
        self.assertEqual(
            visible_card.get_attribute("data-study-id"),
            str(newer.pk),
        )
        self.page.locator('[data-flashcard-order="front"]').click()
        self.page.keyboard.press("ArrowRight")
        self.assertEqual(
            visible_card.get_attribute("data-study-id"),
            str(older.pk),
        )

        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        prompt = self.page.locator("#card-front .prompt-text")
        prompt.wait_for()
        first_prompt = prompt.text_content()
        shared_card = self.page.locator("[data-review-card]")
        shared_face = self.page.locator("[data-flashcard-face-label]")
        self.assertIn(
            "ArrowDown",
            shared_card.get_attribute("aria-keyshortcuts"),
        )

        self.page.locator('[data-flashcard-order="front"]').click()
        self.page.keyboard.press("ArrowDown")
        self.assertEqual(shared_face.inner_text(), "Verso")
        self.page.keyboard.press("ArrowUp")
        self.assertEqual(shared_face.inner_text(), "Recto")
        self.page.keyboard.press("ArrowDown")
        self.page.keyboard.press("ArrowRight")
        self.page.wait_for_function(
            """
            previous => {
              const prompt = document.querySelector("#card-front .prompt-text");
              return prompt && prompt.textContent !== previous;
            }
            """,
            arg=first_prompt,
        )
        current_prompt = prompt.text_content()

        self.page.keyboard.press("ArrowLeft")
        self.page.wait_for_function(
            """
            expected => {
              const prompt = document.querySelector("#card-front .prompt-text");
              return prompt && prompt.textContent === expected;
            }
            """,
            arg=first_prompt,
        )
        self.page.keyboard.press("ArrowRight")
        self.page.wait_for_function(
            """
            expected => {
              const prompt = document.querySelector("#card-front .prompt-text");
              return prompt && prompt.textContent === expected;
            }
            """,
            arg=current_prompt,
        )

    def test_note_and_highlight_actions_read_the_visible_item(self):
        self.context.add_init_script(
            """
            (() => {
              window.__annotationSpoken = "";
              const voices = [{
                name: "Audrey Premium",
                voiceURI: "fr-premium",
                lang: "fr-FR",
                localService: true,
                default: true,
              }];
              const synthesis = {
                getVoices: () => voices,
                addEventListener: () => {},
                cancel: () => {},
                resume: () => {},
                speak: utterance => {
                  window.__annotationSpoken = utterance.text;
                },
              };
              class FakeUtterance {
                constructor(text) {
                  this.text = text;
                  this.lang = "";
                  this.rate = 1;
                  this.pitch = 1;
                  this.voice = null;
                }
              }
              Object.defineProperty(window, "speechSynthesis", {
                configurable: true,
                value: synthesis,
              });
              Object.defineProperty(window, "SpeechSynthesisUtterance", {
                configurable: true,
                value: FakeUtterance,
              });
            })();
            """
        )
        selected_note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="Rappel important",
            quote="Il faut nuancer cette affirmation.",
            body="Employer cependant pour nuancer.",
        )
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Cependant, il faut reconnaître cette limite.",
            source_path=response_detail_url(self.first.response),
            start_offset=0,
            end_offset=45,
        )
        notes_url = reverse(
            "study:task_notes",
            args=[self.part.slug, self.task.slug],
        )

        self.page.goto(self.live_server_url + notes_url)
        note_card = self.page.locator(
            ".annotation-card",
            has_text="Rappel important",
        )
        note_read = note_card.locator("[data-read-aloud]")
        self.assertEqual(
            note_read.get_attribute("aria-label"), "Lire le français"
        )
        self.assertGreaterEqual(note_read.bounding_box()["width"], 44)
        note_read.click()
        self.page.wait_for_function(
            "() => window.__annotationSpoken.includes('nuancer cette affirmation')"
        )
        spoken_note = self.page.evaluate("window.__annotationSpoken")
        self.assertEqual(
            spoken_note,
            f"{selected_note.quote} — {selected_note.title}",
        )
        self.assertIn("Rappel important", spoken_note)
        self.assertNotIn("cependant", spoken_note)
        self.assertEqual(note_read.get_attribute("aria-pressed"), "true")
        note_read.click()
        self.assertEqual(note_read.get_attribute("aria-pressed"), "false")

        self.page.goto(self.live_server_url + notes_url + "?tab=highlights")
        highlight_card = self.page.locator(
            ".annotation-card",
            has_text="Cependant, il faut reconnaître cette limite.",
        )
        highlight_read = highlight_card.locator(
            "[data-read-aloud]"
        )
        self.assertEqual(
            highlight_read.get_attribute("aria-label"),
            "Lire le français",
        )
        highlight_read.click()
        self.page.wait_for_function(
            "() => window.__annotationSpoken.includes('reconnaître cette limite')"
        )
        self.assertEqual(highlight_read.get_attribute("aria-pressed"), "true")

        # A free-standing note can read its optional French title.
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="Note libre",
            body="A reminder written in my own words.",
        )
        self.page.goto(self.live_server_url + notes_url)
        free_note = self.page.locator(
            ".annotation-card",
            has_text="Note libre",
        )
        self.assertEqual(
            free_note.locator("[data-read-aloud]").count(), 1
        )

    def test_study_deck_removes_only_known_cards_at_the_end(self):
        Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            title="Première",
            body="Contenu un",
            study_later=True,
        )
        Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            title="Deuxième",
            body="Contenu deux",
            study_later=True,
        )
        self.page.goto(
            self.live_server_url + reverse("study:annotation_study")
        )
        self.page.locator("[data-study-card]:not(.hidden)").wait_for()

        # Tick the first card off as « terminé », leave the second alone.
        with self.page.expect_response(
            lambda response: "/terminer/" in response.url
        ):
            self.page.locator(
                "[data-study-card]:not(.hidden) "
                '[data-study-flag="completed"]'
            ).click()
        self.page.locator("[data-study-next]").click()
        self.page.locator("[data-study-next]").click()

        self.page.locator("[data-study-done]:not(.hidden)").wait_for()
        clear = self.page.locator("[data-study-clear]")
        clear.wait_for(state="visible")
        self.assertIn("1", clear.inner_text())

        # Nothing leaves the pack before the learner confirms.
        self.assertEqual(
            Annotation.objects.filter(
                user=self.user, study_later=True
            ).count(),
            2,
        )

        clear.click()
        self.page.locator("[data-study-clear]").wait_for(state="hidden")

        # Only the « Je le connais » card is removed; the kept one stays.
        self.assertEqual(
            Annotation.objects.filter(
                user=self.user, study_later=True
            ).count(),
            1,
        )

    def test_notes_custom_select_filters_and_custom_confirm_deletes(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="À supprimer",
            body="Contenu supprimable",
        )
        notes_url = reverse(
            "study:task_notes", args=[self.part.slug, self.task.slug]
        )
        self.page.goto(self.live_server_url + notes_url)

        mobile_filters = self.page.locator(".notes-status-filter")
        self.assertEqual(mobile_filters.count(), 4)
        self.assertTrue(
            all(
                box["height"] >= 44
                for box in mobile_filters.evaluate_all(
                    """
                    filters => filters.map(filter => {
                      const rect = filter.getBoundingClientRect();
                      return {height: rect.height};
                    })
                    """
                )
            )
        )
        self.page.locator(
            '.notes-status-filter[data-status="done"]'
        ).click()
        self.page.wait_for_url("**status=done**")

        # Desktop retains the accessible custom listbox.
        self.page.set_viewport_size({"width": 900, "height": 720})
        self.page.goto(self.live_server_url + notes_url)
        self.assertEqual(
            self.page.locator("#notes-status").get_attribute("aria-hidden"),
            "true",
        )
        trigger = self.page.locator(".custom-select__button")
        trigger.wait_for(state="visible")
        trigger.click()
        self.page.locator(".custom-select__list:not([hidden])").wait_for()
        self.page.locator(
            '.custom-select__option[data-value="done"]'
        ).click()
        self.page.wait_for_url("**status=done**")

        # Deleting a note now happens in place — no full page reload.
        self.page.goto(self.live_server_url + notes_url)
        url_before = self.page.url
        self.page.locator(
            f'.annotation-card[data-annotation-item="{note.pk}"]'
        ).wait_for(state="visible")
        self.page.locator(
            'form[action$="/supprimer/"] button[type="submit"]'
        ).first.click()
        dialog = self.page.locator("[data-confirm-dialog]")
        dialog.wait_for(state="visible")
        self.page.get_by_text("Supprimer cette note ?").wait_for()
        self.page.locator("[data-confirm-accept]").click()
        self.page.locator(
            f'[data-annotation-item="{note.pk}"]'
        ).first.wait_for(state="detached")
        self.assertEqual(self.page.url, url_before)
        self.assertFalse(
            Annotation.objects.filter(pk=note.pk).exists()
        )
        self.page.locator("[data-notes-recall]").wait_for(state="hidden")

    def test_notes_recall_matches_language_in_cards_and_table(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="Titre facultatif",
            quote="Passage capturé en français.",
            body="The written note is in English.",
        )
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Un surlignage français.",
        )
        notes_url = reverse(
            "study:task_notes", args=[self.part.slug, self.task.slug]
        )
        self.page.goto(self.live_server_url + notes_url)

        controls = self.page.locator("[data-notes-recall]")
        french_button = controls.locator('[data-recall-column="french"]')
        english_button = controls.locator('[data-recall-column="english"]')
        card = self.page.locator(f'[data-annotation-item="{note.pk}"]')
        french_cells = card.locator('[data-recall-cell="french"]')
        french_content = french_cells.locator("[data-recall-content]")
        english_cell = card.locator('[data-recall-cell="english"]')
        english_content = english_cell.locator("[data-recall-content]")

        self.assertTrue(controls.is_visible())
        self.assertTrue(french_button.is_visible())
        self.assertTrue(english_button.is_visible())
        self.assertEqual(
            card.locator("h3.annotation-card__title").inner_text(),
            "Passage capturé en français.",
        )
        self.assertEqual(
            card.locator(".annotation-card__subtitle").inner_text(),
            "Titre facultatif",
        )
        self.assertEqual(card.locator("blockquote").count(), 0)
        self.assertEqual(french_cells.count(), 2)

        french_button.click()
        self.assertTrue(
            all(
                value != "none"
                for value in french_content.evaluate_all(
                    "elements => elements.map(element => "
                    "getComputedStyle(element).filter)"
                )
            )
        )
        french_cells.first.click()
        self.assertTrue(
            all(
                value == "none"
                for value in french_content.evaluate_all(
                    "elements => elements.map(element => "
                    "getComputedStyle(element).filter)"
                )
            )
        )

        english_button.click()
        self.assertEqual(french_button.get_attribute("aria-pressed"), "false")
        self.assertNotEqual(
            english_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        english_cell.focus()
        self.page.keyboard.press("Space")
        self.assertEqual(
            english_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )

        self.page.get_by_role("button", name="Tableau").click()
        # One node per annotation, so table mode keeps the recall state the
        # card was left in.
        table_row = self.page.locator(f'[data-annotation-item="{note.pk}"]')
        self.assertEqual(table_row.count(), 1)
        table_english = table_row.locator('[data-recall-cell="english"]')
        table_english_content = table_english.locator("[data-recall-content]")
        table_row.wait_for(state="visible")
        self.assertEqual(
            table_english_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )

        english_button.click()
        english_button.click()
        self.assertNotEqual(
            table_english_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        table_english.click()
        self.assertEqual(
            english_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        self.page.get_by_role("button", name="Cartes").click()
        self.assert_no_horizontal_overflow()

        self.page.goto(self.live_server_url + notes_url + "?tab=highlights")
        controls = self.page.locator("[data-notes-recall]")
        self.assertTrue(
            controls.locator('[data-recall-column="french"]').is_visible()
        )
        self.assertFalse(
            controls.locator('[data-recall-column="english"]').is_visible()
        )

    def test_new_note_paste_and_close_saves_clipboard_in_body(self):
        self.context.add_init_script(
            """
            Object.defineProperty(navigator, "clipboard", {
              configurable: true,
              value: {
                readText: () => Promise.resolve(
                  "Clipboard text for **Votre note**."
                ),
              },
            });
            """
        )
        notes_url = reverse(
            "study:task_notes", args=[self.part.slug, self.task.slug]
        )
        self.page.goto(self.live_server_url + notes_url)
        self.page.get_by_role("button", name="Nouvelle note").click()

        dialog = self.page.locator("#note-create-dialog")
        dialog.wait_for(state="visible")
        dialog.get_by_label("Titre (facultatif)").fill("Titre français")
        paste_close = dialog.get_by_role(
            "button",
            name="Coller et fermer",
            exact=True,
        )
        self.assertIn(
            "ui-icons.svg?v=3#icon-clipboard-paste",
            paste_close.locator("use").get_attribute("href"),
        )
        paste_close.click()

        note_card = self.page.locator(
            ".annotation-card",
            has_text="Clipboard text for Votre note.",
        )
        note_card.wait_for(state="visible")
        self.assertEqual(
            Annotation.objects.get(
                user=self.user,
                title="Titre français",
            ).body,
            "Clipboard text for **Votre note**.",
        )
        self.assertFalse(dialog.is_visible())
        self.assert_no_horizontal_overflow()

    def test_new_note_ignores_clipboard_read_from_closed_dialog(self):
        self.context.add_init_script(
            """
            Object.defineProperty(navigator, "clipboard", {
              configurable: true,
              value: {
                readText: () => new Promise(resolve => {
                  window.__clipboardResolvers =
                    window.__clipboardResolvers || [];
                  window.__clipboardResolvers.push(resolve);
                }),
              },
            });
            """
        )
        notes_url = reverse(
            "study:task_notes", args=[self.part.slug, self.task.slug]
        )
        self.page.goto(self.live_server_url + notes_url)
        self.page.get_by_role("button", name="Nouvelle note").click()

        dialog = self.page.locator("#note-create-dialog")
        dialog.wait_for(state="visible")
        dialog.get_by_label("Titre (facultatif)").fill("Ancienne session")
        dialog.get_by_role(
            "button",
            name="Coller et fermer",
            exact=True,
        ).click()
        self.page.wait_for_function(
            "() => (window.__clipboardResolvers || []).length === 1"
        )
        dialog.get_by_role("button", name="Annuler", exact=True).click()
        dialog.wait_for(state="hidden")

        self.page.get_by_role("button", name="Nouvelle note").click()
        dialog.wait_for(state="visible")
        dialog.get_by_label("Titre (facultatif)").fill("Nouvelle session")
        note_body = dialog.get_by_label("Votre note")
        note_body.fill("")
        self.page.evaluate(
            "window.__clipboardResolvers[0]('Texte devenu obsolète.')"
        )
        self.page.wait_for_timeout(100)

        self.assertTrue(dialog.is_visible())
        self.assertEqual(note_body.input_value(), "")
        self.assertFalse(
            Annotation.objects.filter(user=self.user).exists()
        )

        dialog.get_by_role(
            "button",
            name="Coller et fermer",
            exact=True,
        ).click()
        self.page.wait_for_function(
            "() => window.__clipboardResolvers.length === 2"
        )
        self.page.evaluate(
            "window.__clipboardResolvers[1]('Texte de la nouvelle session.')"
        )
        self.page.locator(
            ".annotation-card",
            has_text="Texte de la nouvelle session.",
        ).wait_for()
        self.assertEqual(
            Annotation.objects.get(
                user=self.user,
                title="Nouvelle session",
            ).body,
            "Texte de la nouvelle session.",
        )

    def test_notes_actions_apply_in_place(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="Note vivante",
            body="corps",
        )
        notes_url = reverse(
            "study:task_notes", args=[self.part.slug, self.task.slug]
        )
        self.page.goto(self.live_server_url + notes_url)
        url_before = self.page.url

        card = self.page.locator(
            f'.annotation-card[data-annotation-item="{note.pk}"]'
        )
        card.wait_for(state="visible")
        study_hero = self.page.locator('[data-hero-count="study"]')
        self.assertEqual(study_hero.inner_text().strip(), "0")

        # "À étudier" toggles in place: badge appears, hero count grows,
        # and the page never navigates.
        study_button = card.locator(
            'form[data-annotation-action="study"] button'
        )
        study_button.click()
        card.locator(".annotation-card__study").wait_for(state="visible")
        self.assertEqual(self.page.url, url_before)
        self.assertEqual(study_hero.inner_text().strip(), "1")
        note.refresh_from_db()
        self.assertTrue(note.study_later)

        # Toggling back removes the badge and decrements the count.
        study_button.click()
        card.locator(".annotation-card__study").wait_for(state="detached")
        self.assertEqual(study_hero.inner_text().strip(), "0")
        note.refresh_from_db()
        self.assertFalse(note.study_later)

        # "Terminé" adds the done badge in place as well.
        done_button = card.locator(
            'form[data-annotation-action="complete"] button'
        )
        done_button.click()
        card.locator(".annotation-card__done").wait_for(state="visible")
        self.assertEqual(self.page.url, url_before)
        note.refresh_from_db()
        self.assertTrue(note.completed)

    def test_notes_actions_apply_in_place_in_table_mode(self):
        recent = [
            Annotation.objects.create(
                user=self.user,
                task=self.task,
                kind=AnnotationKind.NOTE,
                title=f"Ligne {index}",
                body=f"corps {index}",
            )
            for index in range(2)
        ]
        older = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="Ligne ancienne",
            body="corps ancien",
        )
        Annotation.objects.filter(pk=older.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=30)
        )
        notes_url = reverse(
            "study:task_notes", args=[self.part.slug, self.task.slug]
        )
        self.page.set_viewport_size({"width": 1200, "height": 900})
        self.page.goto(self.live_server_url + notes_url)
        self.page.get_by_role("button", name="Tableau").click()
        url_before = self.page.url

        row = self.page.locator(
            f'[data-annotation-item="{recent[0].pk}"]'
        )
        row.wait_for(state="visible")
        # Table mode reuses the card node, so there is still only one of it.
        self.assertEqual(row.count(), 1)
        self.assertEqual(
            row.evaluate("element => getComputedStyle(element).display"),
            "grid",
        )
        sections = self.page.locator(".notes-date-section")
        self.assertEqual(sections.count(), 2)
        self.assertEqual(
            sections.first.locator(".notes-date-section__count")
            .inner_text()
            .strip(),
            "2",
        )

        study_hero = self.page.locator('[data-hero-count="study"]')
        row.locator('form[data-annotation-action="study"] button').click()
        row.locator(".annotation-card__study").wait_for(state="visible")
        self.assertEqual(study_hero.inner_text().strip(), "1")
        self.assertEqual(self.page.url, url_before)

        row.locator('form[data-annotation-action="complete"] button').click()
        row.locator(".annotation-card__done").wait_for(state="visible")
        recent[0].refresh_from_db()
        self.assertTrue(recent[0].completed)

        # The edit dialog reads its values from the same node.
        row.get_by_role("button", name="Modifier la note").click()
        edit_dialog = self.page.locator("#note-edit-dialog")
        edit_dialog.wait_for(state="visible")
        self.assertEqual(
            edit_dialog.get_by_label("Titre (facultatif)").input_value(),
            "Ligne 0",
        )
        edit_dialog.get_by_role("button", name="Annuler", exact=True).click()
        edit_dialog.wait_for(state="hidden")

        # Deleting drops the one node and recounts its date section.
        row.locator('form[data-annotation-action="delete"] button').click()
        self.page.locator("[data-confirm-accept]").click()
        row.wait_for(state="detached")
        self.assertEqual(
            sections.first.locator(".notes-date-section__count")
            .inner_text()
            .strip(),
            "1",
        )
        self.assertEqual(
            self.page.locator('[data-tab-count="notes"]').inner_text().strip(),
            "2",
        )
        self.assertEqual(self.page.url, url_before)

        # Emptying a section removes it; emptying the tab shows the empty state.
        for annotation in (recent[1], older):
            node = self.page.locator(
                f'[data-annotation-item="{annotation.pk}"]'
            )
            node.locator('form[data-annotation-action="delete"] button').click()
            self.page.locator("[data-confirm-accept]").click()
            node.wait_for(state="detached")
        self.assertEqual(sections.count(), 0)
        self.page.locator("#notes-panel .empty").wait_for(state="visible")
        self.assertEqual(
            self.page.locator("[data-collection-view-toggle]").count(),
            0,
        )
        self.assertEqual(self.page.url, url_before)
        self.assert_no_horizontal_overflow()

    def test_notes_status_filter_removes_toggled_item_in_place(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="À classer",
            body="corps",
        )
        notes_url = reverse(
            "study:task_notes", args=[self.part.slug, self.task.slug]
        )
        self.page.goto(self.live_server_url + notes_url + "?status=todo")
        url_before = self.page.url
        card = self.page.locator(
            f'.annotation-card[data-annotation-item="{note.pk}"]'
        )
        card.wait_for(state="visible")
        tab = self.page.locator('[data-tab-count="notes"]')
        self.assertEqual(tab.inner_text().strip(), "1")

        # Marking it done drops it from the "À faire" filter, no reload.
        card.locator(
            'form[data-annotation-action="complete"] button'
        ).click()
        self.page.locator(
            f'[data-annotation-item="{note.pk}"]'
        ).first.wait_for(state="detached")
        self.assertEqual(self.page.url, url_before)
        self.assertEqual(tab.inner_text().strip(), "0")
        self.page.locator("#notes-panel .empty").wait_for(state="visible")
        note.refresh_from_db()
        self.assertTrue(note.completed)

    def test_mobile_expression_lots_and_highlighted_answers(self):
        category = PhraseCategory.objects.create(
            slug="browser-vocab",
            name="Vocabulaire mobile",
            content_key="test-category:browser-vocab",
            order=1,
        )
        prompt = self.first.response.prompts.get(is_canonical=True)
        for _ in range(16):
            phrase = factories.make_phrase(
                category=category,
                tier="response",
            )
            phrase.source_prompts.add(prompt)
            factories.make_phrase_card(user=self.user, phrase=phrase)

        for _ in range(50):
            phrase = factories.make_phrase(
                category=category,
                tier="subject",
            )
            phrase.source_prompts.add(prompt)
            factories.make_phrase_card(user=self.user, phrase=phrase)

        shared_phrases = []
        for _ in range(16):
            phrase = factories.make_phrase(
                category=category,
                tier="shared",
            )
            shared_phrases.append(phrase)
            factories.make_phrase_card(user=self.user, phrase=phrase)
            factories.make_phrase_card(
                user=self.user,
                phrase=phrase,
                card_type=CardType.PHRASE_RECOGNITION,
            )

        self.page.set_viewport_size({"width": 320, "height": 568})
        response_url = response_detail_url(self.first.response)
        self.page.goto(self.live_server_url + response_url)
        self.page.get_by_role(
            "link",
            name="Lot 1 · 10 expressions",
        ).wait_for()
        self.page.get_by_role(
            "link",
            name="Lot 2 · 6 expressions",
        ).wait_for()
        vocabulary_lots = self.page.locator(
            ".response-batches--vocabulary .response-batch"
        )
        self.assertEqual(vocabulary_lots.count(), 5)
        self.assertEqual(
            self.page.locator(
                ".response-batches--expressions .response-batch"
            ).count(),
            2,
        )
        lot_layouts = vocabulary_lots.evaluate_all(
            """
            lots => lots.map(lot => {
              const style = getComputedStyle(lot);
              return {
                fits: lot.scrollWidth <= lot.clientWidth + 1,
                height: lot.getBoundingClientRect().height,
                borders: [
                  style.borderTopColor,
                  style.borderRightColor,
                  style.borderBottomColor,
                  style.borderLeftColor,
                ],
                pseudoContent: getComputedStyle(lot, '::before').content,
              };
            })
            """
        )
        self.assertTrue(all(item["fits"] for item in lot_layouts))
        self.assertTrue(all(item["height"] <= 72 for item in lot_layouts))
        self.assertTrue(
            all(len(set(item["borders"])) == 1 for item in lot_layouts)
        )
        self.assertTrue(
            all(item["pseudoContent"] == "none" for item in lot_layouts)
        )

        subject_controls = self.page.locator(
            '[data-recall-controls="response-subject-vocabulary-recall-catalog"]'
        )
        related_controls = self.page.locator(
            '[data-recall-controls="response-related-vocabulary-recall-catalog"]'
        )
        subject_controls.wait_for()
        related_controls.wait_for()
        subject_french = self.page.locator(
            '#response-subject-vocabulary-recall-catalog '
            '[data-recall-cell="french"]'
        ).first
        subject_french_content = subject_french.locator(
            "[data-recall-content]"
        )
        related_french_content = self.page.locator(
            '#response-related-vocabulary-recall-catalog '
            '[data-recall-cell="french"] [data-recall-content]'
        ).first
        subject_controls.locator(
            '[data-recall-column="french"]'
        ).click()
        self.assertNotEqual(
            subject_french_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        self.assertEqual(
            related_french_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        subject_french.click()
        self.assertEqual(
            subject_french_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        self.assert_no_horizontal_overflow()

        for phrase in shared_phrases:
            phrase.source_prompts.add(prompt)
        category_url = reverse(
            "study:task_vocabulary_category",
            args=[
                prompt.theme.task.part.slug,
                prompt.theme.task.slug,
                category.slug,
            ],
        )
        self.page.goto(self.live_server_url + category_url)
        self.page.get_by_role(
            "heading",
            name="Choisir un lot de 10",
        ).wait_for()
        self.assertEqual(
            self.page.locator(".batch-card").count(),
            2,
        )
        self.assertEqual(
            self.page.locator(".phrase__ex mark").count(),
            len(shared_phrases),
        )

        recall_controls = self.page.locator(
            '[data-recall-controls="vocabulary-recall-catalog"]'
        )
        recall_controls.wait_for()
        cards_button = self.page.locator(
            '[data-collection-view-option="cards"]'
        )
        table_button = self.page.locator(
            '[data-collection-view-option="table"]'
        )
        cards_button.click()
        french_cell = self.page.locator(
            '#vocabulary-recall-catalog [data-recall-cell="french"]'
        ).first
        french_content = french_cell.locator("[data-recall-content]")
        recall_controls.locator('[data-recall-column="french"]').click()
        self.assertNotEqual(
            french_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        table_button.click()
        self.assertNotEqual(
            french_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        french_cell.click()
        self.assertEqual(
            french_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        cards_button.click()
        self.assertEqual(
            french_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )

        recall_controls.locator('[data-recall-column="meaning"]').click()
        meaning_cell = self.page.locator(
            '#vocabulary-recall-catalog [data-recall-cell="meaning"]'
        ).first
        meaning_content = meaning_cell.locator("[data-recall-content]")
        self.assertNotEqual(
            meaning_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        meaning_cell.press("Enter")
        self.assertEqual(
            meaning_content.evaluate(
                "element => getComputedStyle(element).filter"
            ),
            "none",
        )
        self.assert_no_horizontal_overflow()

        batch_url = self.page.locator(".batch-card").first.get_attribute("href")
        self.assertTrue(batch_url)
        self.page.goto(self.live_server_url + batch_url)
        self.page.locator("#card-front > *").first.wait_for()
        self.assert_no_horizontal_overflow()
        self.page.locator("#reveal").click()
        self.page.wait_for_function(
            "() => !document.querySelector('#card-back').classList.contains('hidden')"
        )
        highlighted = self.page.locator("#card-back mark").first
        self.assertGreater(self.page.locator("#card-back mark").count(), 0)
        self.assertEqual(
            highlighted.text_content(),
            shared_phrases[0].anchor,
        )
        self.assert_no_horizontal_overflow()

    def test_home_command_center_is_compact_and_scannable(self):
        factories.make_comprehension_test()
        dashboard_url = self.live_server_url + reverse("study:dashboard")

        self.page.set_viewport_size({"width": 1110, "height": 700})
        self.page.goto(dashboard_url)
        views_metric = self.page.locator(".home-hero__metrics dd").nth(1)
        views_metric.evaluate(
            """
            element => {
              element.firstChild.textContent = "188";
              element.querySelector(".hero-metric__total").textContent = "/ 9900";
            }
            """
        )
        self.assertLessEqual(
            views_metric.evaluate("element => element.scrollWidth"),
            views_metric.evaluate("element => element.clientWidth"),
        )

        # "Aujourd\u2019hui" is one surface: the action and the goal share it
        # side by side instead of reading as two unrelated panels.
        desktop_today = self.page.locator(".home-today__body").evaluate(
            """
            body => {
              const action = body.querySelector('.home-today__action')
                .getBoundingClientRect();
              const goal = body.querySelector('.home-today__goal')
                .getBoundingClientRect();
              return {
                actionTop: action.top,
                goalTop: goal.top,
                actionRight: action.right,
                goalLeft: goal.left,
              };
            }
            """
        )
        self.assertAlmostEqual(
            desktop_today["actionTop"], desktop_today["goalTop"], delta=1
        )
        self.assertAlmostEqual(
            desktop_today["actionRight"], desktop_today["goalLeft"], delta=1
        )
        neutral_home_surfaces = self.page.locator(
            ".home-today, .home-today__action"
        ).evaluate_all(
            """
            elements => elements.map(element => ({
              backgroundImage: getComputedStyle(element).backgroundImage,
              borderLeftWidth: getComputedStyle(element).borderLeftWidth,
            }))
            """
        )
        self.assertTrue(
            all(
                item["backgroundImage"] == "none"
                for item in neutral_home_surfaces
            ),
            neutral_home_surfaces,
        )
        self.assertEqual(
            neutral_home_surfaces[-1]["borderLeftWidth"],
            "0px",
        )

        # The activity queue is a single scannable list of compact rows.
        queue_rows = self.page.locator(".home-queue__item").evaluate_all(
            """
            rows => rows.map(row => {
              const box = row.getBoundingClientRect();
              return {
                x: box.x,
                y: box.y,
                width: box.width,
                height: box.height,
                eyebrow: getComputedStyle(
                  row.querySelector('.eyebrow')
                ).color,
                primary: Boolean(row.querySelector('.btn')),
                secondary: Boolean(
                  row.querySelector('.home-queue__secondary')
                ),
              };
            })
            """
        )
        self.assertEqual(len(queue_rows), 3)
        self.assertLessEqual(max(row["height"] for row in queue_rows), 120)
        self.assertEqual(len({row["x"] for row in queue_rows}), 1)
        self.assertEqual(
            len({row["eyebrow"] for row in queue_rows}),
            len(queue_rows),
        )
        self.assertTrue(all(row["primary"] for row in queue_rows))
        self.assertTrue(all(row["secondary"] for row in queue_rows))
        surface_color = self.page.evaluate(
            """
            () => {
              const probe = document.createElement("div");
              probe.style.background = "var(--surface)";
              document.body.append(probe);
              const color = getComputedStyle(probe).backgroundColor;
              probe.remove();
              return color;
            }
            """
        )
        self.assertEqual(
            self.page.locator(".home-queue__list").evaluate(
                "list => getComputedStyle(list).backgroundColor"
            ),
            surface_color,
        )

        # Progress is one panel of rows, not a repeated grid of cards.
        skill_rows = self.page.locator("[data-home-skill]").evaluate_all(
            """
            skills => skills.map(skill => {
              const box = skill.getBoundingClientRect();
              return {x: box.x, y: box.y, width: box.width};
            })
            """
        )
        self.assertGreaterEqual(len(skill_rows), 2)
        self.assertEqual(len({row["x"] for row in skill_rows}), 1)
        self.assertEqual(len({round(row["y"]) for row in skill_rows}), len(skill_rows))
        self.assert_no_horizontal_overflow()

        for width in (1024, 900, 861):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 700})
                self.assertLessEqual(
                    views_metric.evaluate("element => element.scrollWidth"),
                    views_metric.evaluate("element => element.clientWidth"),
                )
                self.assert_no_horizontal_overflow()

        for width in (390, 320):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 640})
                self.assert_no_horizontal_overflow()

        views_metric.evaluate(
            """
            element => {
              element.firstChild.textContent = "159";
              element.querySelector(".hero-metric__total").textContent = "/ 9700";
            }
            """
        )
        self.assertLessEqual(
            views_metric.evaluate("element => element.scrollWidth"),
            views_metric.evaluate("element => element.clientWidth"),
        )
        mobile_hero_layout = self.page.locator(".home-hero").evaluate(
            """hero => {
              const heroBox = hero.getBoundingClientRect();
              const copyBox = hero.querySelector(
                '.home-hero__copy'
              ).getBoundingClientRect();
              const metrics = hero.querySelector('.home-hero__metrics');
              const metricsBox = metrics.getBoundingClientRect();
              const metricsStyle = getComputedStyle(metrics);
              const heroStyle = getComputedStyle(hero);
              return {
                height: heroBox.height,
                metricsWidth: metricsBox.width,
                heroWidth: heroBox.width,
                heroContentWidth: hero.clientWidth -
                  parseFloat(heroStyle.paddingLeft) -
                  parseFloat(heroStyle.paddingRight),
                verticalGap: metricsBox.top - copyBox.bottom,
                columns: metricsStyle.gridTemplateColumns.split(' ').length,
                backgroundImage: heroStyle.backgroundImage,
                radius: parseFloat(heroStyle.borderTopLeftRadius),
              };
            }"""
        )
        self.assertLessEqual(
            mobile_hero_layout["height"], 190, mobile_hero_layout
        )
        self.assertAlmostEqual(
            mobile_hero_layout["metricsWidth"],
            mobile_hero_layout["heroContentWidth"],
            delta=1,
        )
        self.assertLessEqual(mobile_hero_layout["verticalGap"], 12)
        self.assertEqual(mobile_hero_layout["columns"], 3)
        self.assertNotEqual(
            mobile_hero_layout["backgroundImage"],
            "none",
            mobile_hero_layout,
        )
        self.assertGreaterEqual(mobile_hero_layout["radius"], 12)

        mobile_queue = self.page.locator(".home-queue__item").evaluate_all(
            """
            rows => rows.map(row => {
              const box = row.getBoundingClientRect();
              const secondary = row.querySelector('.home-queue__secondary')
                .getBoundingClientRect();
              return {
                height: box.height,
                width: box.width,
                secondaryWidth: secondary.width,
                secondaryHeight: secondary.height,
              };
            })
            """
        )
        self.assertEqual(len(mobile_queue), 3)
        self.assertLessEqual(max(row["height"] for row in mobile_queue), 180)
        for row in mobile_queue:
            self.assertAlmostEqual(
                row["secondaryWidth"], row["secondaryHeight"], delta=1
            )
            self.assertGreaterEqual(row["secondaryHeight"], 34)

        mobile_skill_rows = self.page.locator(
            "[data-home-skill]"
        ).evaluate_all(
            """
            skills => skills.map(skill => {
              const box = skill.getBoundingClientRect();
              return {x: box.x, y: box.y, width: box.width};
            })
            """
        )
        self.assertGreaterEqual(len(mobile_skill_rows), 2)
        self.assertEqual(len({row["x"] for row in mobile_skill_rows}), 1)
        self.assertNotAlmostEqual(
            mobile_skill_rows[0]["y"],
            mobile_skill_rows[1]["y"],
            delta=1,
        )

        mobile_today = self.page.locator(".home-today__body").evaluate(
            """
            body => {
              const action = body.querySelector('.home-today__action')
                .getBoundingClientRect();
              const goal = body.querySelector('.home-today__goal')
                .getBoundingClientRect();
              return {
                actionBottom: action.bottom,
                goalTop: goal.top,
              };
            }
            """
        )
        self.assertAlmostEqual(
            mobile_today["actionBottom"],
            mobile_today["goalTop"],
            delta=1,
        )
        self.assert_no_horizontal_overflow()

    def test_mobile_notes_scope_picker_reveals_the_active_scope(self):
        for order, slug in enumerate(
            ("tache-0", "tache-1", "tache-2"),
            start=1,
        ):
            task = factories.make_task(part=self.part, slug=slug)
            task.order = order
            task.save(update_fields=["order"])
        self.task.order = 99
        self.task.save(update_fields=["order"])

        self.page.set_viewport_size({"width": 320, "height": 568})
        self.page.goto(
            self.live_server_url
            + reverse(
                "study:task_notes",
                args=[self.part.slug, self.task.slug],
            )
        )
        self.assertFalse(self.page.locator(".notes-scope-nav").is_visible())
        picker = self.page.locator(".notes-mobile-scope")
        picker.wait_for(state="visible")
        self.assertIn(
            "EO · Tache 3",
            picker.locator("summary").inner_text(),
        )
        picker.locator("summary").click()
        self.page.wait_for_function(
            """() => {
              const menu = document.querySelector(
                '.notes-mobile-scope__menu'
              );
              const active = menu && menu.querySelector('.is-active');
              if (!active) return false;
              const menuBox = menu.getBoundingClientRect();
              const activeBox = active.getBoundingClientRect();
              return activeBox.top >= menuBox.top - 1 &&
                activeBox.bottom <= menuBox.bottom + 1;
            }"""
        )
        scope_layout = picker.locator(
            ".notes-mobile-scope__menu"
        ).evaluate(
            """menu => {
              const menuBox = menu.getBoundingClientRect();
              const activeBox = menu.querySelector(
                '.is-active'
              ).getBoundingClientRect();
              return {
                menuTop: menuBox.top,
                menuBottom: menuBox.bottom,
                activeTop: activeBox.top,
                activeBottom: activeBox.bottom,
                activeHeight: activeBox.height,
              };
            }"""
        )
        self.assertGreaterEqual(
            scope_layout["activeTop"],
            scope_layout["menuTop"] - 1,
        )
        self.assertLessEqual(
            scope_layout["activeBottom"],
            scope_layout["menuBottom"] + 1,
        )
        self.assertGreaterEqual(scope_layout["activeHeight"], 48)
        self.assert_no_horizontal_overflow()

    def test_mobile_oral_audio_controls_are_circular_and_operable(self):
        oral_test = factories.make_comprehension_test(
            question_count=1,
            mode=ComprehensionMode.ORALE,
        )
        self.page.add_init_script(
            """
            class FakeSpeechSynthesisUtterance {
              constructor(text) {
                this.text = text;
              }
            }
            const fakeSpeechSynthesis = {
              speaking: false,
              pending: false,
              paused: false,
              getVoices() {
                return [{
                  name: 'Amélie',
                  voiceURI: 'test-fr',
                  lang: 'fr-FR',
                  localService: true,
                  default: true,
                }];
              },
              addEventListener() {},
              speak(utterance) {
                this.lastUtterance = utterance;
                this.speaking = true;
              },
              cancel() {
                this.speaking = false;
                this.pending = false;
                this.paused = false;
              },
              resume() {
                this.paused = false;
              },
            };
            Object.defineProperty(window, 'speechSynthesis', {
              configurable: true,
              value: fakeSpeechSynthesis,
            });
            Object.defineProperty(window, 'SpeechSynthesisUtterance', {
              configurable: true,
              value: FakeSpeechSynthesisUtterance,
            });
            """
        )
        self.page.set_viewport_size({"width": 320, "height": 568})
        self.page.goto(
            self.live_server_url
            + reverse(
                "study:comprehension_oral_question_study",
                args=[oral_test.slug, 1],
            )
        )

        dialogue = self.page.locator(
            '[data-co-audio-play][data-co-audio-target="dialogue"]'
        )
        dialogue.wait_for()
        dialogue.dispatch_event(
            "pointerdown",
            {
                "pointerId": 51,
                "pointerType": "pen",
                "isPrimary": True,
                "button": 0,
            },
        )
        dialogue.dispatch_event(
            "pointerup",
            {
                "pointerId": 51,
                "pointerType": "pen",
                "isPrimary": True,
                "button": 0,
            },
        )
        self.assertEqual(
            dialogue.get_attribute("aria-label"),
            "Écouter le dialogue en français",
        )
        stop = self.page.get_by_role("button", name="Arrêter la lecture")
        stop_metrics = stop.evaluate(
            """element => {
              const style = getComputedStyle(element);
              return {
                width: parseFloat(style.width),
                height: parseFloat(style.height),
                radius: style.borderTopLeftRadius,
              };
            }"""
        )
        self.assertGreaterEqual(stop_metrics["width"], 48)
        self.assertAlmostEqual(
            stop_metrics["width"],
            stop_metrics["height"],
            delta=0.5,
        )
        self.assertEqual(stop_metrics["radius"], "50%")
        self.assertGreaterEqual(dialogue.bounding_box()["height"], 48)
        self.assertGreaterEqual(
            self.page.get_by_label("Vitesse de lecture").bounding_box()["height"],
            48,
        )

        self.assertTrue(dialogue.is_enabled())
        self.assertFalse(stop.is_enabled())
        dialogue.click()
        self.assertEqual(dialogue.get_attribute("aria-pressed"), "true")
        self.assertTrue(stop.is_enabled())
        stop.click()
        self.assertEqual(dialogue.get_attribute("aria-pressed"), "false")
        self.assertFalse(stop.is_enabled())
        self.assert_no_horizontal_overflow()

    def test_written_expression_sections_and_notes_tabs_are_centered(self):
        Command()._import_sections(load_sections())
        self.page.set_viewport_size({"width": 1200, "height": 800})

        self.page.goto(self.live_server_url + reverse("study:expression"))
        self.page.locator(
            ".expression-path--ee",
            has_text="Écrite",
        ).click()
        self.page.locator("h1", has_text="Expression écrite").wait_for()
        self.assertEqual(self.page.locator(".deck--soon").count(), 0)
        self.assertEqual(
            self.page.locator(".deck:not(.deck--soon)").count(),
            3,
        )
        self.assert_no_horizontal_overflow()

        self.page.goto(
            self.live_server_url + reverse("study:notes_overview")
        )
        tabs_box = self.page.locator(".notes-tabs").bounding_box()
        main_box = self.page.locator("#main").bounding_box()
        self.assertAlmostEqual(
            tabs_box["x"] + tabs_box["width"] / 2,
            main_box["x"] + main_box["width"] / 2,
            delta=1,
        )
        self.assert_no_horizontal_overflow()

    def test_text_and_icon_controls_have_distinct_shapes(self):
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Note utilisée pour vérifier les contrôles mobiles.",
        )
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Passage utilisé pour vérifier les contrôles mobiles.",
            source_path="/",
            start_offset=0,
            end_offset=53,
        )
        self.page.set_viewport_size({"width": 1200, "height": 800})
        self.page.goto(
            self.live_server_url + reverse("study:notes_overview")
        )

        compose_metrics = self.page.get_by_role(
            "button", name="Nouvelle note"
        ).evaluate(
            """element => {
              const style = getComputedStyle(element);
              return {
                height: parseFloat(style.height),
                radius: parseFloat(style.borderTopLeftRadius),
              };
            }"""
        )
        self.assertGreaterEqual(
            compose_metrics["radius"], compose_metrics["height"] / 2 - 1
        )

        search_metrics = self.page.locator(".search-form .btn--icon").evaluate(
            """element => {
              const style = getComputedStyle(element);
              return {
                width: parseFloat(style.width),
                height: parseFloat(style.height),
                radius: style.borderTopLeftRadius,
                color: style.color,
                iconColor: getComputedStyle(
                  element.querySelector('.btn__icon')
                ).color,
              };
            }"""
        )
        self.assertAlmostEqual(
            search_metrics["width"], search_metrics["height"], delta=0.5
        )
        self.assertEqual(search_metrics["radius"], "50%")
        self.assertNotEqual(
            search_metrics["iconColor"], search_metrics["color"]
        )

        tab_metrics = self.page.locator(".notes-tab").first.evaluate(
            """element => {
              const style = getComputedStyle(element);
              return {
                height: parseFloat(style.height),
                radius: parseFloat(style.borderTopLeftRadius),
              };
            }"""
        )
        self.assertGreaterEqual(
            tab_metrics["radius"], tab_metrics["height"] / 2 - 1
        )

        self.page.set_viewport_size({"width": 320, "height": 568})
        search_input_box = self.page.locator(
            ".notes-toolbar .search-form__input"
        ).bounding_box()
        search_button = self.page.locator(
            ".notes-toolbar .search-form .btn--icon"
        )
        search_button_box = search_button.bounding_box()
        self.assertGreaterEqual(search_input_box["width"], 200)
        self.assertLess(search_input_box["x"], search_button_box["x"])
        self.assertAlmostEqual(
            search_input_box["y"] + search_input_box["height"] / 2,
            search_button_box["y"] + search_button_box["height"] / 2,
            delta=1,
        )
        self.assertAlmostEqual(
            search_button_box["width"], search_button_box["height"], delta=0.5
        )
        self.assertEqual(
            search_button.evaluate(
                "element => getComputedStyle(element).borderTopLeftRadius"
            ),
            "50%",
        )

        action_boxes = self.page.locator(
            ".notes-toolbar__actions .btn"
        ).evaluate_all(
            """elements => elements.map(element => {
              const rect = element.getBoundingClientRect();
              return {
                y: rect.y,
                width: rect.width,
                height: rect.height,
              };
            })"""
        )
        self.assertEqual(len(action_boxes), 2)
        self.assertAlmostEqual(action_boxes[0]["y"], action_boxes[1]["y"], delta=1)
        self.assertAlmostEqual(
            action_boxes[0]["width"], action_boxes[1]["width"], delta=1
        )
        status_boxes = self.page.locator(
            ".notes-status-filter"
        ).evaluate_all(
            """elements => elements.map(element => {
              const rect = element.getBoundingClientRect();
              return {width: rect.width, height: rect.height};
            })"""
        )
        self.assertEqual(len(status_boxes), 4)
        self.assertTrue(
            all(
                box["width"] >= 120 and box["height"] >= 44
                for box in status_boxes
            )
        )

        tabs_box = self.page.locator(".notes-tabs").bounding_box()
        view_toolbar_box = self.page.locator(
            ".notes-view-controls > .collection-view-toolbar"
        ).bounding_box()
        self.assertAlmostEqual(
            tabs_box["y"] + tabs_box["height"] / 2,
            view_toolbar_box["y"] + view_toolbar_box["height"] / 2,
            delta=1,
        )
        view_button_metrics = self.page.locator(
            ".notes-view-controls .collection-view-toggle button"
        ).evaluate_all(
            """elements => elements.map(element => {
              const style = getComputedStyle(element);
              return {
                width: parseFloat(style.width),
                height: parseFloat(style.height),
                radius: style.borderTopLeftRadius,
              };
            })"""
        )
        self.assertEqual(len(view_button_metrics), 2)
        self.assertTrue(
            all(
                abs(item["width"] - item["height"]) <= 0.5
                and item["radius"] == "50%"
                for item in view_button_metrics
            )
        )
        self.assert_no_horizontal_overflow()

        self.page.goto(
            self.live_server_url
            + reverse("study:notes_overview")
            + "?tab=highlights"
        )
        self.assertEqual(
            self.page.locator("#highlights-tab").get_attribute(
                "aria-selected"
            ),
            "true",
        )
        highlight_action = self.page.locator(
            ".notes-toolbar__actions--highlights .btn"
        )
        self.assertEqual(highlight_action.count(), 1)
        self.assertGreaterEqual(highlight_action.bounding_box()["width"], 280)
        self.assertGreaterEqual(
            self.page.locator(
                ".notes-toolbar .search-form__input"
            ).bounding_box()["width"],
            200,
        )
        self.assert_no_horizontal_overflow()

        self.page.set_viewport_size({"width": 1200, "height": 800})
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        # Deck controls are the shared rounded rectangles of the Notes
        # standard: same height and radius, and clearly not icon circles.
        reveal = self.page.locator("#reveal")
        control_metrics = self.page.locator(
            "#previous-card, #reveal"
        ).evaluate_all(
            """elements => elements.map(element => {
              const style = getComputedStyle(element);
              return {
                height: parseFloat(style.height),
                radius: parseFloat(style.borderTopLeftRadius),
              };
            })"""
        )
        self.assertEqual(len(control_metrics), 2)
        self.assertEqual(
            len({metrics["radius"] for metrics in control_metrics}), 1
        )
        self.assertEqual(
            len({metrics["height"] for metrics in control_metrics}), 1
        )
        for metrics in control_metrics:
            self.assertGreaterEqual(metrics["radius"], 10)
            self.assertLess(metrics["radius"], metrics["height"] / 2 - 1)
        reveal.click()
        grade_metrics = self.page.locator(".grade").first.evaluate(
            """element => {
              const style = getComputedStyle(element);
              return {
                height: parseFloat(style.height),
                radius: parseFloat(style.borderTopLeftRadius),
              };
            }"""
        )
        self.assertEqual(grade_metrics["radius"], control_metrics[0]["radius"])
        self.assertEqual(grade_metrics["height"], control_metrics[0]["height"])

        self.page.set_viewport_size({"width": 320, "height": 568})
        toggle = self.page.get_by_role("button", name="Ouvrir le menu")
        toggle_metrics = toggle.evaluate(
            """element => {
              const style = getComputedStyle(element);
              return {
                width: parseFloat(style.width),
                height: parseFloat(style.height),
                radius: style.borderTopLeftRadius,
              };
            }"""
        )
        self.assertAlmostEqual(
            toggle_metrics["width"], toggle_metrics["height"], delta=0.5
        )
        self.assertEqual(toggle_metrics["radius"], "50%")
        self.assert_no_horizontal_overflow()

    def test_stats_dashboard_stays_balanced_on_desktop_and_mobile(self):
        self.page.set_viewport_size({"width": 1110, "height": 700})
        self.page.goto(self.live_server_url + reverse("study:stats"))

        grid_box = self.page.locator(".stats-kpis").bounding_box()
        tiles = self.page.locator(".stats-kpi")
        self.assertEqual(tiles.count(), 3)
        last_tile_box = tiles.last.bounding_box()
        self.assertAlmostEqual(
            last_tile_box["x"] + last_tile_box["width"],
            grid_box["x"] + grid_box["width"],
            delta=1,
        )
        chart_panels = self.page.locator(".stats-chart-grid .stats-panel")
        self.assertEqual(chart_panels.count(), 2)
        self.assertAlmostEqual(
            chart_panels.first.bounding_box()["y"],
            chart_panels.last.bounding_box()["y"],
            delta=1,
        )
        self.assertEqual(
            self.page.locator(".stats-theme").first.evaluate(
                "row => getComputedStyle(row, '::before').content"
            ),
            "none",
        )
        self.assert_no_horizontal_overflow()

        self.page.set_viewport_size({"width": 320, "height": 568})
        self.assertEqual(
            self.page.locator(".stats-kpis").evaluate(
                "grid => getComputedStyle(grid).gridTemplateColumns.split(' ').length"
            ),
            1,
        )
        self.assertLessEqual(
            self.page.locator(".stats-hero").evaluate(
                "hero => hero.scrollWidth"
            ),
            self.page.locator(".stats-hero").evaluate(
                "hero => hero.clientWidth"
            ),
        )
        self.assert_no_horizontal_overflow()

    def test_mobile_comprehension_quiz_correction_and_results(self):
        self.disable_service_worker()
        test = factories.make_comprehension_test(question_count=2)
        self.page.set_viewport_size({"width": 320, "height": 568})

        self.page.goto(self.live_server_url + reverse("study:dashboard"))
        self.page.get_by_role("button", name="Ouvrir le menu").click()
        self.page.get_by_role(
            "link",
            name="Compréhension",
            exact=True,
        ).click()
        self.page.get_by_role(
            "heading",
            name="Compréhension",
            exact=True,
        ).wait_for()
        self.assert_no_horizontal_overflow()

        self.page.locator(
            ".expression-path--available",
            has_text="Écrite",
        ).click()
        self.page.get_by_role(
            "heading",
            name="Compréhension écrite",
            exact=True,
        ).wait_for()
        self.assertEqual(self.page.locator(".ce-group-card").count(), 8)
        self.assert_no_horizontal_overflow()

        self.page.get_by_role("link", name="Batch 1").click()
        self.page.get_by_role(
            "heading",
            name="Batch 01",
        ).wait_for()
        self.assertEqual(self.page.locator(".ce-group-test-row").count(), 5)
        row_checkbox = self.page.locator(
            "[data-comprehension-completion-form] button"
        ).first
        self.assertEqual(row_checkbox.get_attribute("aria-checked"), "false")
        checkbox_metrics = row_checkbox.evaluate(
            """element => {
              const style = getComputedStyle(element);
              return {
                width: parseFloat(style.width),
                height: parseFloat(style.height),
                radius: style.borderTopLeftRadius,
              };
            }"""
        )
        self.assertAlmostEqual(
            checkbox_metrics["width"],
            checkbox_metrics["height"],
            delta=0.5,
        )
        self.assertEqual(checkbox_metrics["radius"], "50%")
        row_checkbox.click()
        self.page.wait_for_load_state("networkidle")
        row_checkbox = self.page.locator(
            "[data-comprehension-completion-form] button"
        ).first
        self.assertEqual(row_checkbox.get_attribute("aria-checked"), "true")
        self.assert_no_horizontal_overflow()

        self.follow_new_tab_link("Découvrir le test")
        self.disable_service_worker()
        self.page.get_by_role("heading", name=test.title).wait_for()
        detail_checkbox = self.page.locator(
            "[data-comprehension-completion-form] button"
        )
        self.assertEqual(detail_checkbox.get_attribute("aria-checked"), "true")
        detail_checkbox.click()
        self.page.get_by_text("À commencer", exact=True).wait_for()
        self.assertEqual(detail_checkbox.get_attribute("aria-checked"), "false")
        self.assertEqual(
            self.page.locator(".ce-study-question-row").count(),
            2,
        )
        self.assert_no_horizontal_overflow()

        self.page.locator(".ce-study-question-row").first.click()
        self.page.get_by_text("Choix et correction").wait_for()
        self.assertFalse(
            self.page.get_by_text("Correct explanation 1.").is_visible()
        )
        self.page.get_by_text(
            "Voir les choix et explications en anglais"
        ).click()
        self.page.get_by_text("Correct explanation 1.").wait_for()
        self.assert_no_horizontal_overflow()

        self.page.get_by_role("button", name="Pratiquer ce test").click()
        self.page.get_by_role("heading", name="Question 1 sur 2").wait_for()
        self.assertEqual(
            self.page.get_by_text("English passage 1.").count(),
            0,
        )
        self.assert_no_horizontal_overflow()
        question_buttons = self.page.locator(".ce-question-map__grid > *")
        question_box = question_buttons.first.bounding_box()
        self.assertLessEqual(question_box["width"], 34)
        self.assertAlmostEqual(
            question_box["width"],
            question_box["height"],
            delta=1,
        )
        self.page.locator(".ce-choice", has_text="Choix B français 1").click()
        self.page.get_by_role(
            "heading",
            name="A · Choix A français 1",
        ).wait_for()
        explanation = self.page.locator(".ce-rationales--explanation")
        self.assertTrue(explanation.evaluate("element => element.open"))
        self.assertGreaterEqual(
            self.page.locator(".ce-choice__text").first.evaluate(
                "element => parseFloat(getComputedStyle(element).fontSize)"
            ),
            16,
        )
        self.assertGreaterEqual(
            explanation.locator("summary").evaluate(
                "element => parseFloat(getComputedStyle(element).fontSize)"
            ),
            15,
        )
        self.assertGreaterEqual(
            explanation.locator("p").first.evaluate(
                "element => parseFloat(getComputedStyle(element).fontSize)"
            ),
            16,
        )
        header_box = self.page.locator(".ce-correction__head").bounding_box()
        explanation_box = explanation.bounding_box()
        self.assertGreaterEqual(
            explanation_box["y"] - header_box["y"] - header_box["height"],
            8,
        )
        self.page.get_by_text(
            "Pourquoi votre choix B ne convient pas"
        ).wait_for()
        self.page.get_by_text("Voir la traduction anglaise").click()
        self.page.get_by_text("English passage 1.").wait_for()
        self.assert_no_horizontal_overflow()

        self.page.get_by_role("link", name="Question suivante").click()
        correct_choice = self.page.locator(
            ".ce-choice",
            has_text="Choix A français 2",
        )
        correct_choice.focus()
        correct_choice.press("Enter")
        self.page.get_by_role("link", name="Voir mes résultats").wait_for()
        self.assert_no_horizontal_overflow()

        self.page.get_by_role("link", name="Voir mes résultats").click()
        self.page.get_by_role("heading", name="Correction détaillée").wait_for()
        self.page.get_by_text("Tentative terminée").wait_for()
        results_checkbox = self.page.locator(
            "[data-comprehension-completion-form] button"
        )
        self.assertEqual(results_checkbox.get_attribute("aria-checked"), "false")
        results_checkbox.click()
        self.page.get_by_text("Terminé", exact=True).wait_for()
        self.assertEqual(results_checkbox.get_attribute("aria-checked"), "true")
        self.assertEqual(self.page.locator(".ce-review-item").count(), 2)
        map_cells = self.page.locator(".ce-results-map__grid a").evaluate_all(
            """
            cells => cells.map(cell => {
              const box = cell.getBoundingClientRect();
              return { width: box.width, height: box.height };
            })
            """
        )
        self.assertTrue(map_cells)
        self.assertLessEqual(max(cell["width"] for cell in map_cells), 44)
        self.assertTrue(
            all(abs(cell["width"] - cell["height"]) <= 1 for cell in map_cells)
        )
        summary_heights = self.page.locator(
            ".ce-review-item > summary"
        ).evaluate_all(
            "summaries => summaries.map(item => item.getBoundingClientRect().height)"
        )
        self.assertLessEqual(max(summary_heights), 96)
        self.assert_no_horizontal_overflow()

    def test_mobile_oral_completion_control_uses_the_shared_flow(self):
        test = factories.make_comprehension_test(
            question_count=2,
            mode=ComprehensionMode.ORALE,
        )
        self.page.set_viewport_size({"width": 320, "height": 568})
        self.page.goto(
            self.live_server_url
            + reverse("study:comprehension_oral_group", args=[1])
        )

        checkbox = self.page.locator(
            "[data-comprehension-completion-form] button"
        ).first
        self.assertEqual(checkbox.get_attribute("aria-checked"), "false")
        checkbox.click()
        self.page.wait_for_load_state("networkidle")
        checkbox = self.page.locator(
            "[data-comprehension-completion-form] button"
        ).first
        self.assertEqual(checkbox.get_attribute("aria-checked"), "true")
        self.assert_no_horizontal_overflow()

        self.follow_new_tab_link("Découvrir le test")
        self.disable_service_worker()
        self.page.get_by_role("heading", name=test.title).wait_for()
        self.assertEqual(
            self.page.locator(
                "[data-comprehension-completion-form] button"
            ).get_attribute("aria-checked"),
            "true",
        )
        self.assert_no_horizontal_overflow()


    def test_last_question_highlights_in_full_when_selection_spills_out(self):
        command = Command()
        task_map = command._import_sections(load_sections())
        months = content.load_tache_two_subject_months()
        theme_map = command._import_themes(
            content.tache_two_themes(months),
            task_map,
        )
        family_map = command._import_families(
            content.tache_two_families(months)
        )
        responses = content.parse_tache_two_responses(months)
        response_map = command._import_responses(
            responses,
            theme_map,
            family_map,
        )
        command._import_prompts(
            responses,
            response_map,
            theme_map,
            family_map,
        )
        command._sync_cards(response_map, user=self.user)

        self.page.set_viewport_size({"width": 1280, "height": 850})
        self.page.goto(
            self.live_server_url
            + reverse(
                "study:task_subject_detail",
                args=["eo", "tache-2", "janvier", 1, 1],
            )
        )
        self.page.wait_for_load_state("networkidle")

        target = (
            self.page.locator("[data-tache-two-question]")
            .last.locator(".tache-two-question__content p")
            .first
        )
        expected = target.inner_text()

        # Triple-clicking the final question makes the browser end the range
        # in the sidebar, outside the annotation root.
        target.click(click_count=3)
        self.page.wait_for_timeout(300)
        self.assertNotEqual(
            self.page.evaluate("() => window.getSelection().toString()"),
            expected,
            "the selection is expected to spill past the question",
        )

        button = self.page.locator("[data-highlight-selection]")
        self.assertEqual(button.inner_text().strip(), "Highlight")
        with self.page.expect_response(
            lambda response: reverse("study:annotation_create") in response.url
        ) as created:
            button.click()
        self.assertEqual(created.value.status, 201)

        self.page.wait_for_timeout(600)
        self.assertEqual(
            self.page.locator("[data-user-highlight]").all_inner_texts(),
            [expected],
        )
        highlight = Annotation.objects.get(
            user=self.user,
            kind=AnnotationKind.HIGHLIGHT,
        )
        self.assertEqual(highlight.quote, expected)

    DECK_METRICS = """
        () => {
          const round = value => Math.round(value);
          const deck = document.querySelector('[data-flashcard-deck]');
          const toolbar = deck.querySelector('.flashcard-deck__toolbar');
          const controls = deck.querySelector('[data-flashcard-controls]');
          const card = deck.querySelector(
            '[data-flashcard-card]:not(.hidden):not(' +
            '.theme-vocabulary-card--inactive):not(' +
            '.comprehension-vocabulary-phrase--inactive)'
          );
          const buttons = [...controls.querySelectorAll(
            '.flashcard-deck__control'
          )].filter(button => button.offsetParent !== null);
          const buttonStyle = getComputedStyle(buttons[0]);
          const controlStyle = getComputedStyle(controls);
          return {
            toolbarWidth: round(toolbar.getBoundingClientRect().width),
            controlsWidth: round(controls.getBoundingClientRect().width),
            cardWidth: round(card.getBoundingClientRect().width),
            cardMinHeight: getComputedStyle(card).minHeight,
            columns: controlStyle.gridTemplateColumns.split(' ').length,
            buttonCount: buttons.length,
            buttonRows: new Set(
              buttons.map(button => round(
                button.getBoundingClientRect().top
              ))
            ).size,
            buttonHeight: buttonStyle.height,
            buttonRadius: buttonStyle.borderTopLeftRadius,
            faceLabel: Boolean(
              card.querySelector('[data-flashcard-face-label]')
            ),
            flipHint: Boolean(card.querySelector('.flashcard-deck__flip-hint')),
            progressLive: deck.querySelector(
              '[data-flashcard-progress]'
            ).getAttribute('aria-live'),
            progressText: deck.querySelector(
              '[data-flashcard-progress]'
            ).textContent.trim(),
            faceSwitch: deck.querySelectorAll('[data-flashcard-order]').length,
            keyboardHint: Boolean(
              deck.querySelector('[data-flashcard-keyboard-hint]')
            ),
          };
        }
    """

    def _deck_metrics(self, url, before=None):
        self.page.goto(self.live_server_url + url)
        self.page.wait_for_load_state("networkidle")
        if before:
            before()
        self.page.locator(
            "[data-flashcard-card]:not(.hidden):not("
            ".theme-vocabulary-card--inactive):not("
            ".comprehension-vocabulary-phrase--inactive)"
        ).first.wait_for()
        return self.page.evaluate(self.DECK_METRICS)

    def _make_comprehension_vocabulary(self, mode, number, per_group=2):
        """A published test whose questions carry two vocabulary groups."""
        test = factories.make_comprehension_test(
            number=number,
            question_count=per_group * 2,
            mode=mode,
        )
        questions = list(test.questions.order_by("number"))
        categories = [
            PhraseCategory.objects.get_or_create(
                slug=f"comprehension-{label}",
                defaults={
                    "name": f"Compréhension · {title}",
                    "content_key": f"test-category:comprehension-{label}",
                    "order": 90 + index,
                },
            )[0]
            for index, (label, title) in enumerate(
                (("mots", "Mots-clés"), ("reformulations", "Reformulations"))
            )
        ]
        phrases = []
        for index, question in enumerate(questions):
            phrase = factories.make_phrase(
                category=categories[index // per_group],
                tier="comprehension",
                lot_order=index + 1,
            )
            phrase.source_questions.add(question)
            factories.make_phrase_card(phrase=phrase, user=self.user)
            phrases.append(phrase)
        return test, phrases

    def _comprehension_deck_state(self):
        return self.page.evaluate(
            """
            () => {
              const deck = document.querySelector(
                '[data-comprehension-vocabulary-deck]'
              );
              const cards = [...deck.querySelectorAll(
                '[data-comprehension-vocabulary-phrase]'
              )];
              const visible = cards.filter(card => (
                getComputedStyle(card).display !== 'none'
                && card.getClientRects().length
              ));
              const active = visible[0] || null;
              const faceVisible = face => Boolean(
                face
                && getComputedStyle(face).display !== 'none'
                && face.getClientRects().length
              );
              const chrome = [...document.querySelectorAll(
                '.comprehension-vocabulary-flashcard-only'
              )].filter(node => (
                getComputedStyle(node).display !== 'none'
                && node.getClientRects().length
              ));
              return {
                total: cards.length,
                visible: visible.length,
                progress: deck.querySelector(
                  '[data-flashcard-progress]'
                ).textContent.trim(),
                fill: deck.querySelector(
                  '[data-flashcard-progress-bar]'
                ).style.width,
                previousDisabled: deck.querySelector(
                  '[data-flashcard-previous]'
                ).disabled,
                nextDisabled: deck.querySelector(
                  '[data-flashcard-next]'
                ).disabled,
                chromeVisible: chrome.length,
                front: active
                  ? faceVisible(active.querySelector('[data-flashcard-front]'))
                  : false,
                back: active
                  ? faceVisible(active.querySelector('[data-flashcard-back]'))
                  : false,
                text: active ? active.innerText.replace(/\\s+/g, ' ').trim() : '',
                faceLabel: active
                  ? active.querySelector(
                      '[data-flashcard-face-label]'
                    ).textContent.trim()
                  : '',
                width: active
                  ? Math.round(active.getBoundingClientRect().width)
                  : 0,
              };
            }
            """
        )

    def _swipe_active_comprehension_card(self, dx):
        box = self.page.locator(
            ".comprehension-vocabulary-phrase:not("
            ".comprehension-vocabulary-phrase--inactive)"
        ).bounding_box()
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2
        self.page.evaluate(
            """
            ([x, y, dx]) => {
              const card = document.querySelector(
                '.comprehension-vocabulary-phrase:not(' +
                '.comprehension-vocabulary-phrase--inactive)'
              );
              const send = (type, clientX) => card.dispatchEvent(
                new PointerEvent(type, {
                  bubbles: true,
                  cancelable: true,
                  pointerId: 7,
                  pointerType: 'touch',
                  isPrimary: true,
                  clientX,
                  clientY: y,
                })
              );
              send('pointerdown', x);
              send('pointermove', x + dx / 2);
              send('pointermove', x + dx);
              send('pointerup', x + dx);
            }
            """,
            [start_x, start_y, dx],
        )

    def test_comprehension_vocabulary_deck_studies_one_card_at_a_time(self):
        cases = (
            (
                ComprehensionMode.ECRITE,
                "study:comprehension_test_vocabulary",
                31,
            ),
            (
                ComprehensionMode.ORALE,
                "study:comprehension_oral_test_vocabulary",
                32,
            ),
        )
        for mode, url_name, number in cases:
            with self.subTest(mode=mode):
                test, phrases = self._make_comprehension_vocabulary(
                    mode,
                    number=number,
                )
                total = len(phrases)
                self.page.set_viewport_size({"width": 1280, "height": 900})
                self.page.goto(
                    self.live_server_url + reverse(url_name, args=[test.slug])
                )
                self.page.wait_for_load_state("networkidle")
                self.page.get_by_role("button", name="Cartes").first.click()
                self.page.wait_for_timeout(200)

                state = self._comprehension_deck_state()
                self.assertEqual(state["total"], total, state)
                self.assertEqual(state["visible"], 1, state)
                self.assertEqual(state["progress"], f"1 / {total}", state)
                self.assertTrue(state["previousDisabled"], state)
                self.assertFalse(state["nextDisabled"], state)
                self.assertTrue(state["front"], state)
                self.assertFalse(state["back"], state)
                self.assertEqual(state["faceLabel"], "Recto", state)
                self.assertIn(phrases[0].expression, state["text"])
                self.assertIn("Mots-clés", state["text"])
                self.assertNotIn(phrases[0].english_cue, state["text"])
                self.assertGreaterEqual(state["chromeVisible"], 3, state)
                self.assertLessEqual(state["width"], 820)

                flip = self.page.locator(
                    "[data-comprehension-vocabulary-deck] [data-flashcard-flip]"
                )
                flip.click()
                state = self._comprehension_deck_state()
                self.assertFalse(state["front"], state)
                self.assertTrue(state["back"], state)
                self.assertEqual(state["faceLabel"], "Verso", state)
                self.assertIn(phrases[0].english_cue, state["text"])
                self.assertIn(test.title, state["text"])

                # Verso first swaps the face order without losing the card.
                self.page.get_by_role("button", name="Verso", exact=True).click()
                state = self._comprehension_deck_state()
                self.assertTrue(state["back"], state)
                self.assertFalse(state["front"], state)
                self.assertEqual(state["progress"], f"1 / {total}", state)
                flip.click()
                state = self._comprehension_deck_state()
                self.assertTrue(state["front"], state)
                self.page.get_by_role(
                    "button", name="Recto", exact=True
                ).click()

                self.page.locator(
                    "[data-comprehension-vocabulary-deck] "
                    "[data-flashcard-next]"
                ).click()
                state = self._comprehension_deck_state()
                self.assertEqual(state["progress"], f"2 / {total}", state)
                self.assertEqual(state["visible"], 1, state)
                self.assertTrue(state["front"], state)
                self.assertIn(phrases[1].expression, state["text"])
                self.assertFalse(state["previousDisabled"], state)

                self.page.locator(
                    "[data-comprehension-vocabulary-deck] "
                    "[data-flashcard-previous]"
                ).click()
                self.assertEqual(
                    self._comprehension_deck_state()["progress"],
                    f"1 / {total}",
                )

                self.page.keyboard.press("ArrowRight")
                self.assertEqual(
                    self._comprehension_deck_state()["progress"],
                    f"2 / {total}",
                )
                self.page.keyboard.press("ArrowLeft")
                self.assertEqual(
                    self._comprehension_deck_state()["progress"],
                    f"1 / {total}",
                )

                # A left swipe advances, a right swipe steps back.
                self._swipe_active_comprehension_card(-140)
                self.assertEqual(
                    self._comprehension_deck_state()["progress"],
                    f"2 / {total}",
                )
                self._swipe_active_comprehension_card(140)
                state = self._comprehension_deck_state()
                self.assertEqual(state["progress"], f"1 / {total}", state)
                self.assertAlmostEqual(
                    float(state["fill"].rstrip("%")),
                    100 / total,
                    places=2,
                )

                read_aloud = self.page.locator(
                    ".comprehension-vocabulary-phrase:not("
                    ".comprehension-vocabulary-phrase--inactive) "
                    "[data-read-aloud]"
                )
                self.assertTrue(read_aloud.is_visible())
                self.assertTrue(read_aloud.is_enabled())
                self.page.evaluate(
                    """
                    () => {
                      window.__comprehensionSpoken = [];
                      window.speechSynthesis.cancel = () => {};
                      window.speechSynthesis.resume = () => {};
                      window.speechSynthesis.speak = utterance => {
                        window.__comprehensionSpoken.push(utterance.text);
                      };
                    }
                    """
                )
                read_aloud.click()
                self.page.wait_for_function(
                    "() => window.__comprehensionSpoken.length > 0"
                )
                self.assertIn(
                    phrases[0].expression,
                    self.page.evaluate(
                        "window.__comprehensionSpoken.join(' ')"
                    ),
                )
                read_aloud.click()

                # Recall blur keeps working inside the card.
                french_recall = self.page.locator(
                    '[data-recall-controls="vocabulary-recall-catalog"] '
                    '[data-recall-column="french"]'
                )
                french_cell = self.page.locator(
                    ".comprehension-vocabulary-phrase:not("
                    ".comprehension-vocabulary-phrase--inactive) "
                    '[data-recall-cell="french"]'
                )
                french_content = french_cell.locator("[data-recall-content]")
                french_recall.click()
                self.assertEqual(
                    french_cell.get_attribute("aria-pressed"), "false"
                )
                self.assertNotEqual(
                    french_content.evaluate(
                        "element => getComputedStyle(element).filter"
                    ),
                    "none",
                )
                french_cell.click()
                self.assertEqual(
                    french_cell.get_attribute("aria-pressed"), "true"
                )
                self.assertEqual(
                    french_content.evaluate(
                        "element => getComputedStyle(element).filter"
                    ),
                    "none",
                )
                self.assertEqual(
                    self._comprehension_deck_state()["progress"],
                    f"1 / {total}",
                )
                french_recall.click()

                self.assert_no_horizontal_overflow()

                # Table view returns every row, with every column intact.
                self.page.get_by_role("button", name="Tableau").first.click()
                self.page.wait_for_timeout(200)
                table = self.page.evaluate(
                    """
                    () => {
                      const rows = [...document.querySelectorAll(
                        '[data-comprehension-vocabulary-phrase]'
                      )];
                      const visible = rows.filter(row => (
                        getComputedStyle(row).display !== 'none'
                        && row.getClientRects().length
                      ));
                      const chrome = [...document.querySelectorAll(
                        '.comprehension-vocabulary-flashcard-only'
                      )].filter(node => (
                        getComputedStyle(node).display !== 'none'
                        && node.getClientRects().length
                      ));
                      const cellText = selector => visible.map(row => (
                        (row.querySelector(selector) || {}).textContent || ''
                      ).trim());
                      const stage = document.querySelector(
                        '.comprehension-vocabulary-stage'
                      );
                      return {
                        visible: visible.length,
                        chromeVisible: chrome.length,
                        expressions: cellText('.phrase__expr'),
                        cues: cellText('.phrase__cue'),
                        examples: cellText('.phrase__ex'),
                        links: visible.map(row => row.querySelectorAll(
                          '.phrase__foot a'
                        ).length),
                        headers: [...document.querySelectorAll(
                          '.comprehension-vocabulary-group '
                          + '[data-collection-table-header]'
                        )].filter(node => (
                          getComputedStyle(node).display !== 'none'
                        )).length,
                        stageWidth: Math.round(
                          stage.getBoundingClientRect().width
                        ),
                        rowWidth: Math.round(
                          visible[0].getBoundingClientRect().width
                        ),
                      };
                    }
                    """
                )
                self.assertEqual(table["visible"], total, table)
                self.assertEqual(table["chromeVisible"], 0, table)
                self.assertEqual(table["headers"], 2, table)
                self.assertGreater(table["stageWidth"], 820, table)
                self.assertGreater(table["rowWidth"], 820, table)
                for index, phrase in enumerate(phrases):
                    self.assertIn(phrase.expression, table["expressions"][index])
                    self.assertIn(phrase.english_cue, table["cues"][index])
                    self.assertTrue(table["examples"][index], table)
                    self.assertGreaterEqual(table["links"][index], 1, table)
                self.assert_no_horizontal_overflow()

                # Returning to cards keeps a single valid active card.
                self.page.get_by_role("button", name="Cartes").first.click()
                self.page.wait_for_timeout(200)
                state = self._comprehension_deck_state()
                self.assertEqual(state["visible"], 1, state)
                self.assertEqual(state["progress"], f"1 / {total}", state)
                self.assertTrue(state["front"], state)

                self.page.set_viewport_size({"width": 320, "height": 700})
                self.page.wait_for_timeout(150)
                state = self._comprehension_deck_state()
                self.assertEqual(state["visible"], 1, state)
                self.assertLessEqual(state["width"], 320)
                self.assertTrue(
                    self.page.locator(
                        "[data-comprehension-vocabulary-deck] "
                        "[data-flashcard-previous]"
                    ).is_visible()
                )
                self.assertTrue(
                    self.page.locator(
                        "[data-comprehension-vocabulary-deck] "
                        "[data-flashcard-next]"
                    ).is_visible()
                )
                self.assert_no_horizontal_overflow()
                self.page.set_viewport_size({"width": 1280, "height": 900})

    def test_comprehension_vocabulary_directory_has_no_direct_deck(self):
        test, _ = self._make_comprehension_vocabulary(
            ComprehensionMode.ECRITE,
            number=33,
        )
        self.page.set_viewport_size({"width": 1280, "height": 900})
        self.page.goto(
            self.live_server_url + reverse("study:comprehension_vocabulary")
        )
        self.page.wait_for_load_state("networkidle")

        self.assertEqual(
            self.page.locator("[data-comprehension-vocabulary-deck]").count(),
            0,
        )
        self.assertEqual(
            self.page.locator("[data-flashcard-deck]").count(),
            0,
        )
        self.page.get_by_role(
            "link",
            name=f"Voir les 50 entrées de {test.title}",
        ).click()
        self.page.wait_for_url(
            self.live_server_url
            + reverse(
                "study:comprehension_test_vocabulary",
                args=[test.slug],
            )
        )
        self.page.locator("[data-comprehension-vocabulary-deck]").wait_for()
        self.assert_no_horizontal_overflow()

    def test_every_deck_follows_the_notes_flashcard_standard(self):
        for index in range(3):
            Annotation.objects.create(
                user=self.user,
                task=self.task,
                kind=AnnotationKind.NOTE,
                quote="recto %d" % index,
                body="verso %d" % index,
                study_later=True,
            )
        self._import_eo_tache_two_content()
        vocabulary_url = reverse(
            "study:tache_two_theme_vocabulary_detail",
            args=["arrivee"],
        )
        written_test, _ = self._make_comprehension_vocabulary(
            ComprehensionMode.ECRITE,
            number=41,
        )
        oral_test, _ = self._make_comprehension_vocabulary(
            ComprehensionMode.ORALE,
            number=42,
        )
        comprehension_urls = {
            "comprehension-written": reverse(
                "study:comprehension_test_vocabulary",
                args=[written_test.slug],
            ),
            "comprehension-oral": reverse(
                "study:comprehension_oral_test_vocabulary",
                args=[oral_test.slug],
            ),
        }

        def choose_cards():
            self.page.get_by_role("button", name="Cartes").first.click()
            self.page.wait_for_timeout(300)

        for width, height in ((1110, 900), (390, 844)):
            with self.subTest(width=width):
                self.page.set_viewport_size(
                    {"width": width, "height": height}
                )
                notes = self._deck_metrics(reverse("study:annotation_study"))
                review = self._deck_metrics(
                    reverse("study:review") + "?kind=spine&reset=1"
                )
                vocabulary = self._deck_metrics(
                    vocabulary_url, before=choose_cards
                )
                decks = {
                    "notes": notes,
                    "review": review,
                    "vocabulary": vocabulary,
                }
                for name, url in comprehension_urls.items():
                    decks[name] = self._deck_metrics(
                        url, before=choose_cards
                    )

                for name, metrics in decks.items():
                    with self.subTest(deck=name):
                        # Same toolbar shell, card shell, and control grid.
                        self.assertEqual(metrics["columns"], 3, metrics)
                        self.assertEqual(metrics["buttonCount"], 3, metrics)
                        self.assertEqual(metrics["buttonRows"], 1, metrics)
                        self.assertTrue(metrics["faceLabel"], metrics)
                        self.assertTrue(metrics["flipHint"], metrics)
                        self.assertTrue(metrics["keyboardHint"], metrics)
                        self.assertEqual(metrics["faceSwitch"], 2, metrics)
                        self.assertEqual(
                            metrics["progressLive"], "polite", metrics
                        )
                        self.assertRegex(
                            metrics["progressText"], r"^\d+ / \d+$"
                        )
                        self.assertEqual(
                            metrics["buttonHeight"],
                            notes["buttonHeight"],
                            metrics,
                        )
                        self.assertEqual(
                            metrics["buttonRadius"],
                            notes["buttonRadius"],
                            metrics,
                        )
                        self.assertEqual(
                            metrics["cardMinHeight"],
                            notes["cardMinHeight"],
                            metrics,
                        )
                        for key in (
                            "toolbarWidth",
                            "controlsWidth",
                            "cardWidth",
                        ):
                            self.assertAlmostEqual(
                                metrics[key], notes[key], delta=1
                            )
                self.assert_no_horizontal_overflow()

        # The review deck swaps the same row for grading after the reveal.
        self.page.set_viewport_size({"width": 1110, "height": 900})
        self.page.goto(
            self.live_server_url
            + reverse("study:review")
            + "?kind=spine&reset=1"
        )
        self.page.locator("#card-front .prompt-text").wait_for()
        self.page.locator("#reveal").click()
        self.page.locator("#grades:not(.hidden)").wait_for()
        grading = self.page.evaluate(
            """
            () => {
              const row = document.querySelector('.review__controls');
              const visible = [...row.querySelectorAll('button')].filter(
                button => button.offsetParent !== null
              );
              return {
                labels: visible.map(button => button.textContent.trim()),
                rows: new Set(
                  visible.map(
                    button => Math.round(
                      button.getBoundingClientRect().top
                    )
                  )
                ).size,
                heights: new Set(
                  visible.map(
                    button => Math.round(
                      button.getBoundingClientRect().height
                    )
                  )
                ).size,
              };
            }
            """
        )
        self.assertEqual(grading["rows"], 1, grading)
        self.assertEqual(grading["heights"], 1, grading)
        self.assertEqual(len(grading["labels"]), 3, grading)
        self.assertTrue(self.page.locator("#previous-card").is_hidden())
        self.assertTrue(self.page.locator("#forward-locked").is_hidden())
        self.assert_no_horizontal_overflow()

    def test_study_deck_navigates_with_next_button_and_swipe(self):
        for index in range(3):
            Annotation.objects.create(
                user=self.user,
                task=self.task,
                kind=AnnotationKind.NOTE,
                quote="recto %d" % index,
                body="verso %d" % index,
                study_later=True,
            )
        self.page.goto(
            self.live_server_url + reverse("study:annotation_study")
        )
        progress = self.page.locator("[data-study-progress]")
        self.page.locator("[data-study-card]:not(.hidden)").wait_for()
        self.assertEqual(progress.inner_text(), "1 / 3")
        self.assertTrue(
            self.page.locator("[data-study-previous]").is_disabled()
        )

        # « Suivante » moves on without grading the card.
        self.page.locator("[data-study-next]").click()
        self.assertEqual(progress.inner_text(), "2 / 3")
        self.page.locator("[data-study-previous]").click()
        self.assertEqual(progress.inner_text(), "1 / 3")

        # « Retourner » flips both ways.
        reveal = self.page.locator("[data-study-reveal]")
        back = self.page.locator(
            "[data-study-card]:not(.hidden) [data-study-back]"
        )
        reveal.click()
        back.wait_for()
        reveal.click()
        back.wait_for(state="hidden")

        box = self.page.locator("[data-study-card]:not(.hidden)").bounding_box()
        middle_y = box["y"] + box["height"] / 2

        centre = box["x"] + box["width"] / 2
        self.touch_swipe(
            self.page.locator("[data-study-card]:not(.hidden)"),
            centre + 90,
            centre - 90,
            middle_y,
        )
        self.assertEqual(progress.inner_text(), "2 / 3")
        self.touch_swipe(
            self.page.locator("[data-study-card]:not(.hidden)"),
            centre - 90,
            centre + 90,
            middle_y,
        )
        self.assertEqual(progress.inner_text(), "1 / 3")

        # A swipe must not also flip the card.
        self.assertTrue(
            self.page.locator(
                "[data-study-card]:not(.hidden) [data-study-back]"
            ).is_hidden()
        )

    def test_study_deck_edits_a_note_without_losing_your_place(self):
        first = Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            quote="Premier passage.",
            title="Titre initial",
            body="Contenu initial.",
            study_later=True,
        )
        Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            quote="Second passage.",
            body="Contenu second.",
            study_later=True,
        )
        self.page.goto(
            self.live_server_url + reverse("study:annotation_study")
        )
        card = self.page.locator(
            '[data-study-card][data-study-id="%d"]' % first.pk
        )
        card.wait_for(state="attached")
        progress = self.page.locator("[data-study-progress]")
        if card.is_hidden():
            self.page.locator("[data-study-next]").click()
        card.wait_for()
        position = progress.inner_text()

        card.locator("[data-annotation-edit]").click()
        dialog = self.page.locator("#note-edit-dialog")
        dialog.wait_for()
        title_input = dialog.locator("[data-annotation-edit-title]")
        body_input = dialog.locator("[data-annotation-edit-body]")
        self.assertEqual(title_input.input_value(), "Titre initial")
        self.assertEqual(body_input.input_value(), "Contenu initial.")

        title_input.fill("Titre révisé")
        body_input.fill("Contenu **révisé**.")
        with self.page.expect_response(
            lambda response: "/modifier/" in response.url
        ):
            dialog.get_by_role("button", name="Enregistrer").click()

        dialog.wait_for(state="hidden")
        self.page.locator("[data-study-reveal]").click()
        card.locator(
            ".annotation-study__body strong", has_text="révisé"
        ).wait_for()
        card.get_by_text("Titre révisé", exact=True).wait_for()
        # The deck never reloads, so the queue position is preserved.
        self.assertEqual(progress.inner_text(), position)
        first.refresh_from_db()
        self.assertEqual(first.title, "Titre révisé")
        self.assertEqual(first.body, "Contenu **révisé**.")

    def test_study_deck_reads_the_selected_passage_of_a_note(self):
        self.context.add_init_script(
            """
            (() => {
              window.__annotationSpoken = "";
              const voices = [{
                name: "Audrey Premium",
                voiceURI: "fr-premium",
                lang: "fr-FR",
                localService: true,
                default: true,
              }];
              const synthesis = {
                getVoices: () => voices,
                addEventListener: () => {},
                cancel: () => {},
                resume: () => {},
                speak: utterance => {
                  window.__annotationSpoken = utterance.text;
                },
              };
              class FakeUtterance {
                constructor(text) {
                  this.text = text;
                  this.lang = "";
                  this.rate = 1;
                  this.pitch = 1;
                  this.voice = null;
                }
              }
              Object.defineProperty(window, "speechSynthesis", {
                configurable: true,
                value: synthesis,
              });
              Object.defineProperty(window, "SpeechSynthesisUtterance", {
                configurable: true,
                value: FakeUtterance,
              });
            })();
            """
        )
        note = Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            quote="Je tiens à souligner ce point.",
            title="À réutiliser",
            body="Handy opener for giving an opinion.",
            study_later=True,
        )
        self.page.goto(
            self.live_server_url + reverse("study:annotation_study")
        )
        card = self.page.locator(
            '[data-study-card][data-study-id="%d"]' % note.pk
        )
        card.wait_for()
        read = card.locator("[data-read-aloud]")
        self.assertEqual(read.count(), 1)
        self.assertEqual(read.get_attribute("aria-label"), "Lire cette face")

        read.click()
        self.page.wait_for_function(
            "() => window.__annotationSpoken"
            " && window.__annotationSpoken.length > 0"
        )

        spoken = self.page.evaluate("window.__annotationSpoken")
        # Only the French passage is spoken — never the English note.
        self.assertIn("Je tiens à souligner ce point", spoken)
        self.assertNotIn("Handy opener", spoken)
        self.assertNotIn("À réutiliser", spoken)

    def test_study_deck_cards_can_be_read_aloud_and_deleted(self):
        self.context.add_init_script(
            """
            (() => {
              window.__annotationSpoken = "";
              const voices = [{
                name: "Audrey Premium",
                voiceURI: "fr-premium",
                lang: "fr-FR",
                localService: true,
                default: true,
              }];
              const synthesis = {
                getVoices: () => voices,
                addEventListener: () => {},
                cancel: () => {},
                resume: () => {},
                speak: utterance => {
                  window.__annotationSpoken = utterance.text;
                },
              };
              class FakeUtterance {
                constructor(text) {
                  this.text = text;
                  this.lang = "";
                  this.rate = 1;
                  this.pitch = 1;
                  this.voice = null;
                }
              }
              Object.defineProperty(window, "speechSynthesis", {
                configurable: true,
                value: synthesis,
              });
              Object.defineProperty(window, "SpeechSynthesisUtterance", {
                configurable: true,
                value: FakeUtterance,
              });
            })();
            """
        )
        Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            title="Première",
            body="Contenu un",
            study_later=True,
        )
        highlight = Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Contenu deux",
            study_later=True,
        )
        self.page.goto(
            self.live_server_url + reverse("study:annotation_study")
        )
        card = self.page.locator("[data-study-card]:not(.hidden)")
        card.wait_for()
        progress = self.page.locator("[data-study-progress]")
        self.assertEqual(progress.inner_text(), "1 / 2")

        # A note with no selected passage can still read its French title.
        note_card = self.page.locator(
            '[data-study-card]:not([data-study-id="%d"])' % highlight.pk
        )
        self.assertEqual(
            note_card.locator("[data-read-aloud]").count(), 1
        )

        highlight_card = self.page.locator(
            '[data-study-card][data-study-id="%d"]' % highlight.pk
        )
        if highlight_card.is_hidden():
            self.page.locator("[data-study-next]").click()
        card = highlight_card
        visible_id = str(highlight.pk)
        self.page.locator("[data-study-reveal]").click()
        read = card.locator("[data-read-aloud]")
        read.click()
        self.page.wait_for_function(
            "() => window.__annotationSpoken"
            " && window.__annotationSpoken.length > 0"
        )
        self.assertIn(
            self.page.evaluate("window.__annotationSpoken").strip(". "),
            card.locator("[data-read-aloud-text]").inner_text(),
        )
        self.assertEqual(read.get_attribute("aria-pressed"), "true")

        with self.page.expect_response(
            lambda response: "/supprimer/" in response.url
        ):
            card.locator("[data-study-delete]").click()
            self.page.locator("[data-confirm-accept]").click()

        self.page.wait_for_function(
            "() => document.querySelectorAll('[data-study-card]').length === 1"
        )
        self.assertEqual(progress.inner_text(), "1 / 1")
        self.assertFalse(
            Annotation.objects.filter(pk=int(visible_id)).exists()
        )

    def test_written_question_study_marker_syncs_across_surfaces(self):
        self.disable_service_worker()
        test = factories.make_comprehension_test(number=1, question_count=3)
        first = test.questions.get(number=1)

        self.page.goto(
            self.live_server_url
            + reverse("study:comprehension_test", args=[test.slug])
        )
        row = self.page.locator(
            '[data-question-study-row="%d"]' % first.pk
        )
        marker = row.locator("[data-question-study-button]")
        marker.wait_for()
        self.assertEqual(marker.get_attribute("aria-pressed"), "false")
        box = marker.bounding_box()
        self.assertGreaterEqual(box["width"], 44)
        self.assertGreaterEqual(box["height"], 44)
        self.assert_no_horizontal_overflow()

        with self.page.expect_response(
            lambda response: "/a-etudier/" in response.url
        ):
            marker.click()
        self.page.wait_for_function(
            "() => document.querySelector("
            "'[data-question-study-row=\"%d\"] [data-question-study-button]')"
            ".getAttribute('aria-pressed') === 'true'" % first.pk
        )
        self.assertEqual(marker.get_attribute("aria-pressed"), "true")
        self.assertIn("is-to-study", row.get_attribute("class"))
        self.assertEqual(
            self.page.locator(
                '[data-question-study-test-count="%s"]' % test.slug
            ).inner_text(),
            "1",
        )
        self.assertTrue(
            ComprehensionQuestionStudy.objects.filter(
                user=self.user,
                question=first,
            ).exists()
        )
        self.assert_no_horizontal_overflow()

        # The row is no longer a single anchor, so the marker must not
        # navigate while the rest of the row still opens the study page.
        row.click()
        self.page.get_by_text("Choix et correction").wait_for()
        self.assertEqual(
            self.page.url,
            self.live_server_url
            + reverse(
                "study:comprehension_question_study",
                args=[test.slug, 1],
            ),
        )
        side_marker = self.page.locator(
            ".detail-side [data-question-study-button]"
        )
        self.assertEqual(side_marker.get_attribute("aria-pressed"), "true")
        self.assert_no_horizontal_overflow()

        self.page.goto(
            self.live_server_url
            + reverse("study:comprehension_overview")
        )
        self.assertEqual(
            self.page.locator(
                '[data-question-study-mode-count="ecrite"]'
            ).first.inner_text(),
            "1",
        )
        self.page.get_by_role(
            "link",
            name="Questions à étudier",
        ).click()
        self.page.get_by_role(
            "heading",
            name="Questions à étudier",
            exact=True,
        ).wait_for()
        self.assertEqual(
            self.page.locator(".ce-study-library__row").count(),
            1,
        )
        self.assertTrue(
            self.page.get_by_text("Question française 1 ?").first.is_visible()
        )
        self.assert_no_horizontal_overflow()

        list_marker = self.page.locator(
            '[data-question-study-row="%d"] [data-question-study-button]'
            % first.pk
        )
        with self.page.expect_navigation(wait_until="domcontentloaded"):
            list_marker.click()
        self.page.get_by_role(
            "heading",
            name="Aucune question à étudier",
        ).wait_for()
        self.assertFalse(
            ComprehensionQuestionStudy.objects.filter(
                user=self.user,
            ).exists()
        )
        self.assertEqual(
            self.page.locator(
                '[data-question-study-mode-count="ecrite"]'
            ).first.inner_text(),
            "0",
        )
        self.assertEqual(
            self.page.locator(".ce-study-library__row").count(),
            0,
        )
        self.assert_no_horizontal_overflow()

    def test_oral_attempt_marker_updates_map_and_results_without_reload(self):
        self.disable_service_worker()
        test = factories.make_comprehension_test(
            number=1,
            question_count=2,
            mode=ComprehensionMode.ORALE,
        )
        first = test.questions.get(number=1)

        self.page.goto(
            self.live_server_url
            + reverse("study:comprehension_oral_test", args=[test.slug])
        )
        self.page.get_by_role("button", name="Pratiquer ce test").click()
        self.page.get_by_role("heading", name="Question 1 sur 2").wait_for()
        marker = self.page.locator(
            ".ce-answer-card [data-question-study-button]"
        )
        self.assertEqual(marker.get_attribute("aria-pressed"), "false")
        self.assert_no_horizontal_overflow()

        with self.page.expect_response(
            lambda response: "/a-etudier/" in response.url
        ):
            marker.click()
        self.page.wait_for_function(
            "() => document.querySelector("
            "'.ce-answer-card [data-question-study-button]')"
            ".getAttribute('aria-pressed') === 'true'"
        )
        map_item = self.page.locator(
            '[data-question-study-map="%d"]' % first.pk
        )
        self.assertIn("is-to-study", map_item.get_attribute("class"))
        self.assertIn("à étudier", map_item.get_attribute("aria-label"))
        self.assertEqual(
            marker.locator("[data-question-study-text]").inner_text().strip(),
            "Retirer de l’étude",
        )
        self.assert_no_horizontal_overflow()

        # Answering keeps the marker: it is question state, not attempt state.
        self.page.locator(".ce-choice", has_text="Choix A français 1").click()
        self.page.get_by_text("Bonne réponse").first.wait_for()
        self.assertEqual(
            self.page.locator(
                ".ce-answer-card [data-question-study-button]"
            ).get_attribute("aria-pressed"),
            "true",
        )

        self.page.get_by_role("link", name="Question suivante").click()
        self.page.get_by_role("heading", name="Question 2 sur 2").wait_for()
        self.page.locator(".ce-choice", has_text="Choix A français 2").click()
        self.page.get_by_role("link", name="Voir mes résultats").click()
        self.page.get_by_role("heading", name=test.title).wait_for()
        self.assertIn(
            "is-to-study",
            self.page.locator(
                '[data-question-study-map="%d"]' % first.pk
            ).get_attribute("class"),
        )
        results_study_count = self.page.locator(
            "[data-question-study-results-count]"
        )
        self.assertTrue(results_study_count.is_visible())
        self.assertEqual(
            results_study_count.locator(
                "[data-question-study-results-value]"
            ).inner_text(),
            "1",
        )
        review_item = self.page.locator(
            'details[data-question-study-row="%d"]' % first.pk
        )
        self.assertIn("is-to-study", review_item.get_attribute("class"))
        review_item.locator("summary").first.click()
        review_marker = review_item.locator("[data-question-study-button]")
        self.assertEqual(review_marker.get_attribute("aria-pressed"), "true")
        self.assert_no_horizontal_overflow()

        with self.page.expect_response(
            lambda response: "/a-etudier/" in response.url
        ):
            review_marker.click()
        self.page.wait_for_function(
            "() => document.querySelector("
            "'details[data-question-study-row=\"%d\"]"
            " [data-question-study-button]')"
            ".getAttribute('aria-pressed') === 'false'" % first.pk
        )
        self.assertNotIn(
            "is-to-study",
            review_item.get_attribute("class"),
        )
        self.assertNotIn(
            "à étudier",
            self.page.locator(
                '[data-question-study-map="%d"]' % first.pk
            ).get_attribute("aria-label"),
        )
        self.assertFalse(results_study_count.is_visible())
        self.assertFalse(
            ComprehensionQuestionStudy.objects.filter(user=self.user).exists()
        )
        self.assert_no_horizontal_overflow()

        self.page.goto(
            self.live_server_url
            + reverse("study:comprehension_oral_study_list")
        )
        self.page.get_by_text("Aucune question à étudier").wait_for()
        self.assert_no_horizontal_overflow()
