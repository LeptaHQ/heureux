"""Opt-in real-browser coverage for compact pinned notes."""

import os

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from study.models import Annotation, AnnotationKind

from . import factories
from .browser_server import BrowserLiveServerThread


class NotePinningBrowserTests(StaticLiveServerTestCase):
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
        self.user = factories.make_user("pin-browser")
        self.note = Annotation.objects.create(
            user=self.user, kind=AnnotationKind.NOTE, is_pinned=True,
            title="Un repère important",
            body=("Un paragraphe à conserver.\n\n" * 24) + "**La dernière ligne complète.**",
        )
        self.client.force_login(self.user)
        self.url = self.live_server_url + reverse("study:custom_notes")

    def context(self, javascript=True, width=390):
        context = self.browser.new_context(
            viewport={"width": width, "height": 844},
            java_script_enabled=javascript, service_workers="block",
        )
        context.add_cookies([{
            "name": "sessionid", "value": self.client.cookies["sessionid"].value,
            "url": self.live_server_url,
        }])
        self.addCleanup(context.close)
        return context

    def test_compact_card_opens_full_scrollable_note_with_keyboard_and_mouse(self):
        for width in (390, 1280):
            with self.subTest(width=width):
                page = self.context(width=width).new_page()
                page.goto(self.url)
                card = page.locator(f"#note-{self.note.pk}")
                opener = card.locator("[data-pinned-note-open]")
                expect(opener).to_be_visible()
                self.assertLessEqual(card.bounding_box()["height"], 222)
                expect(card.locator(".annotation-card__pin-dot")).to_be_visible()
                opener.focus()
                page.keyboard.press("Enter")
                dialog = page.locator("#pinned-note-dialog")
                expect(dialog).to_be_visible()
                expect(dialog.locator("strong")).to_have_text("La dernière ligne complète.")
                self.assertTrue(dialog.locator("[data-pinned-note-content]").evaluate(
                    "(el) => el.scrollHeight > el.clientHeight"
                ))
                page.keyboard.press("Escape")
                expect(dialog).not_to_be_visible()
                expect(opener).to_be_focused()
                card.locator(".annotation-card__title").click()
                expect(dialog).to_be_visible()
                page.get_by_role("button", name="Fermer la note").click()
                expect(dialog).not_to_be_visible()
                self.assertEqual(page.evaluate(
                    "() => document.documentElement.scrollWidth <= innerWidth"
                ), True)

    def test_pin_unpin_and_edit_actions_do_not_open_reading_popup(self):
        page = self.context().new_page()
        page.goto(self.url)
        page.get_by_role("button", name="Modifier la note", exact=True).click()
        expect(page.locator("#note-edit-dialog")).to_be_visible()
        expect(page.locator("#pinned-note-dialog")).not_to_be_visible()
        page.keyboard.press("Escape")
        page.get_by_role("button", name="Désépingler la note", exact=True).click()
        expect(page.locator(".annotation-card--pinned")).to_have_count(0)
        page.get_by_role("button", name="Épingler la note", exact=True).click()
        expect(page.locator(".annotation-card--pinned")).to_have_count(1)
        expect(page.locator("[data-pinned-note-open]")).to_be_visible()
        page.reload()
        expect(page.locator(".annotation-card--pinned")).to_have_count(1)

    def test_no_javascript_keeps_full_note_and_working_pin_forms(self):
        page = self.context(javascript=False).new_page()
        page.goto(self.url)
        card = page.locator(f"#note-{self.note.pk}")
        self.assertGreater(card.bounding_box()["height"], 220)
        expect(card.locator("strong")).to_have_text("La dernière ligne complète.")
        expect(card.locator("[data-pinned-note-open]")).not_to_be_visible()
        page.get_by_role("button", name="Désépingler la note", exact=True).click()
        expect(page.locator(".annotation-card--pinned")).to_have_count(0)

    def test_refilled_pinned_cards_still_open_after_in_place_deletion(self):
        extra = Annotation.objects.bulk_create(
            Annotation(user=self.user, kind=AnnotationKind.NOTE, is_pinned=True,
                       title=f"Repère {index}", body=f"Corps {index}")
            for index in range(50)
        )
        page = self.context().new_page()
        page.goto(self.url)
        expect(page.locator("[data-pinned-note-open]")).to_have_count(50)
        page.locator(f"#note-{extra[-1].pk}").get_by_role(
            "button", name="Supprimer la note", exact=True
        ).click()
        page.locator("#app-confirm-dialog").get_by_role(
            "button", name="Supprimer", exact=True
        ).click()
        refreshed = page.locator(f"#note-{self.note.pk}")
        expect(refreshed).to_be_visible()
        expect(page.locator("[data-pinned-note-open]")).to_have_count(50)
        refreshed.locator("[data-pinned-note-open]").click()
        expect(page.locator("#pinned-note-dialog")).to_be_visible()
        expect(page.locator("#pinned-note-dialog strong")).to_have_text(
            "La dernière ligne complète."
        )

    def test_table_view_and_edited_content_keep_the_same_popup(self):
        page = self.context(width=1280).new_page()
        page.goto(self.url)
        page.get_by_role("button", name="Tableau", exact=True).click()
        opener = page.locator("[data-pinned-note-open]")
        expect(opener).to_be_visible()
        page.get_by_role("button", name="Modifier la note", exact=True).click()
        edit = page.locator("#note-edit-dialog")
        edit.locator("[data-annotation-edit-title]").fill("Titre mis à jour")
        edit.locator("[data-annotation-edit-body]").fill("**Contenu révisé.**")
        edit.get_by_role("button", name="Enregistrer", exact=True).click()
        expect(edit).not_to_be_visible()
        opener.click()
        dialog = page.locator("#pinned-note-dialog")
        expect(dialog).to_be_visible()
        expect(dialog.locator("h3")).to_have_text("Titre mis à jour")
        expect(dialog.locator("strong")).to_have_text("Contenu révisé.")
        page.keyboard.press("Escape")
        page.get_by_role("button", name="Cartes", exact=True).click()
        self.assertLessEqual(page.locator(f"#note-{self.note.pk}").bounding_box()["height"], 222)

    def test_action_circles_and_hover_backgrounds_are_uniform(self):
        page = self.context(width=1280).new_page()
        page.goto(self.url)
        actions = page.locator(".annotation-card .annotation-action:visible")
        self.assertGreaterEqual(actions.count(), 5)
        for action in actions.all():
            action.hover()
            shape = action.evaluate("""(button) => {
                const icon = button.querySelector(".annotation-action__icon, .read-aloud-action__icon");
                const style = getComputedStyle(button);
                const rect = icon.getBoundingClientRect();
                return {
                    width: rect.width, height: rect.height,
                    buttonWidth: button.getBoundingClientRect().width,
                    buttonHeight: button.getBoundingClientRect().height,
                    background: style.backgroundColor,
                    radius: getComputedStyle(icon).borderRadius
                };
            }""")
            self.assertEqual((shape["width"], shape["height"]), (36, 36))
            self.assertEqual((shape["buttonWidth"], shape["buttonHeight"]), (44, 44))
            self.assertEqual(shape["radius"], "50%")
            self.assertEqual(shape["background"], "rgba(0, 0, 0, 0)")

    def test_pin_precedes_note_and_remaining_table_actions_fit(self):
        Annotation.objects.create(
            user=self.user, kind=AnnotationKind.NOTE, title="Autre note", body="À retenir."
        )
        for width in (1024, 1280):
            with self.subTest(width=width):
                page = self.context(width=width).new_page()
                page.goto(self.url)
                page.get_by_role("button", name="Tableau", exact=True).click()
                for card in page.locator(".annotation-card--notes").all():
                    pin = card.locator(".annotation-card__head .annotation-card__pin")
                    expect(pin).to_be_visible()
                    self.assertTrue(pin.evaluate("""(form) =>
                        Boolean(form.compareDocumentPosition(
                            form.parentElement.querySelector(".annotation-card__kind")
                        ) & Node.DOCUMENT_POSITION_FOLLOWING)
                    """))
                    self.assertEqual(card.locator(".annotation-card__actions [name='is_pinned']").count(), 0)
                    fits = card.evaluate("""(card) => {
                        const column = card.querySelector(".annotation-card__actions").getBoundingClientRect();
                        const edge = card.getBoundingClientRect().right;
                        return Array.from(card.querySelectorAll(".annotation-card__actions button"))
                            .filter(button => button.getClientRects().length)
                            .every(button => {
                                const box = button.getBoundingClientRect();
                                return box.left >= column.left && box.right <= column.right + 1 &&
                                    box.right <= edge + 1;
                            });
                    }""")
                    self.assertTrue(fits)

    def test_popup_actions_share_loading_state_and_update_the_original_note(self):
        page = self.context().new_page()
        pending = []
        page.route("**/notes/*/etudier/", lambda route: pending.append(route))
        page.goto(self.url)
        page.locator("[data-pinned-note-open]").click()
        dialog = page.locator("#pinned-note-dialog")
        study = dialog.get_by_role("button", name="Ajouter à étudier", exact=True)
        study.click()
        expect(study).to_be_disabled()
        done = dialog.get_by_role("button", name="Marquer comme terminé", exact=True)
        expect(done).to_be_disabled()
        self.assertEqual(len(pending), 1)
        pending[0].continue_()
        study = dialog.get_by_role("button", name="Retirer de l’étude", exact=True)
        expect(study).to_be_enabled()
        expect(study).to_have_attribute("aria-pressed", "true")
        expect(study).to_be_focused()
        done.click()
        expect(dialog.get_by_role("button", name="Marquer comme à faire")).to_have_attribute(
            "aria-pressed", "true"
        )
        expect(dialog).to_be_visible()
        page.keyboard.press("Escape")
        card = page.locator(f"#note-{self.note.pk}")
        expect(card.locator(".annotation-card__study")).to_be_visible()
        expect(card.locator(".annotation-card__done")).to_be_visible()

    def test_popup_can_edit_and_unpin_without_duplicate_forms(self):
        page = self.context().new_page()
        page.goto(self.url)
        page.locator("[data-pinned-note-open]").click()
        dialog = page.locator("#pinned-note-dialog")
        self.assertEqual(dialog.locator("form").count(), 0)
        dialog.get_by_role("button", name="Modifier la note", exact=True).click()
        expect(dialog).not_to_be_visible()
        edit = page.locator("#note-edit-dialog")
        expect(edit).to_be_visible()
        edit.locator("[data-annotation-edit-body]").fill("Une note corrigée.")
        edit.get_by_role("button", name="Enregistrer", exact=True).click()
        expect(edit).not_to_be_visible()
        page.locator("[data-pinned-note-open]").click()
        expect(dialog).to_contain_text("Une note corrigée.")
        dialog.get_by_role("button", name="Désépingler la note", exact=True).click()
        expect(page.locator(".annotation-card--pinned")).to_have_count(0)
        expect(page.get_by_role("button", name="Épingler la note", exact=True)).to_be_visible()

    def test_popup_closes_when_a_filtered_action_removes_the_note(self):
        page = self.context().new_page()
        page.goto(self.url + "?status=todo")
        page.locator("[data-pinned-note-open]").click()
        dialog = page.locator("#pinned-note-dialog")
        dialog.get_by_role("button", name="Marquer comme terminé", exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(page.locator(f"#note-{self.note.pk}")).to_have_count(0)

    def test_popup_shows_failed_actions_without_changing_note_state(self):
        page = self.context().new_page()
        page.route("**/notes/*/etudier/", lambda route: route.fulfill(
            status=503, content_type="application/json",
            body='{"error": "Enregistrement impossible."}',
        ))
        page.goto(self.url)
        page.locator("[data-pinned-note-open]").click()
        dialog = page.locator("#pinned-note-dialog")
        study = dialog.get_by_role("button", name="Ajouter à étudier", exact=True)
        study.click()
        expect(dialog.get_by_role("alert")).to_have_text("Enregistrement impossible.")
        expect(study).to_be_enabled()
        expect(study).to_have_attribute("aria-pressed", "false")
        expect(dialog).to_be_visible()

    def test_popup_reading_uses_original_control_and_delete_uses_confirmation(self):
        page = self.context().new_page()
        page.goto(self.url)
        page.evaluate("""() => {
            window.noteReadTargets = [];
            document.addEventListener("click", event => {
                const button = event.target.closest("[data-read-aloud]");
                if (!button) return;
                window.noteReadTargets.push(button.closest("[data-annotation-item]").id);
                event.preventDefault();
                event.stopImmediatePropagation();
            }, true);
        }""")
        page.locator("[data-pinned-note-open]").click()
        dialog = page.locator("#pinned-note-dialog")
        dialog.get_by_role("button", name="Lire le français", exact=True).click()
        self.assertEqual(page.evaluate("window.noteReadTargets"), [f"note-{self.note.pk}"])
        expect(dialog).to_be_visible()
        dialog.get_by_role("button", name="Supprimer la note", exact=True).click()
        expect(dialog).not_to_be_visible()
        confirm = page.locator("#app-confirm-dialog")
        expect(confirm).to_be_visible()
        confirm.get_by_role("button", name="Supprimer", exact=True).click()
        expect(page.locator(f"#note-{self.note.pk}")).to_have_count(0)
