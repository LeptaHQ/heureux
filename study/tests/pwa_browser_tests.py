import os

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from . import factories
from .browser_server import BrowserLiveServerThread


WORKER_FIXTURE = """
const worker = new EventTarget();
worker.state = "installed";
window.__updateMessages = [];
worker.postMessage = message => {
    if (window.__workerThrows) throw new DOMException("Worker is redundant", "InvalidStateError");
    window.__updateMessages.push(message);
};
const registration = new EventTarget();
registration.waiting = worker;
registration.update = () => Promise.resolve();
const service = new EventTarget();
service.controller = {};
service.register = () => Promise.resolve(registration);
service.getRegistration = () => Promise.resolve(registration);
Object.defineProperty(navigator, "serviceWorker", {value: service, configurable: true});
window.__updateFixture = {service, registration, worker};
"""


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PWAUpdateBrowserTests(StaticLiveServerTestCase):
    server_thread_class = BrowserLiveServerThread

    @classmethod
    def setUpClass(cls):
        cls.previous_async_unsafe = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = getattr(cls.playwright, os.environ.get("PLAYWRIGHT_BROWSER", "chromium")).launch()

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
        self.user = factories.make_user("update-banner-reader")
        self.client.force_login(self.user)
        self.context = self.browser.new_context(
            viewport={"width": 390, "height": 844}, service_workers="block",
        )
        self.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.context.add_init_script(WORKER_FIXTURE)
        self.page = self.context.new_page()
        self.page.clock.install()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.goto(self.live_server_url + "/")
        self.banner = self.page.locator("[data-pwa-update-banner]")
        self.button = self.page.locator("[data-pwa-update]")
        expect(self.banner).to_be_visible()

    def tearDown(self):
        self.assertFalse(self.errors, self.errors)
        self.context.close()

    def test_old_notification_remains_clickable_after_another_tab_activated_update(self):
        self.page.evaluate("""() => {
            __updateFixture.registration.waiting = null;
            __updateFixture.service.controller = {};
            __updateFixture.service.dispatchEvent(new Event("controllerchange"));
        }""")
        expect(self.button).to_be_enabled()
        expect(self.banner).to_contain_text("version est active")
        with self.page.expect_navigation():
            self.button.click()

    def test_disappeared_waiting_worker_reloads_instead_of_ignoring_click(self):
        self.page.evaluate("__updateFixture.registration.waiting = null")
        with self.page.expect_navigation():
            self.button.click()

    def test_unresponsive_worker_does_not_disable_button_forever(self):
        self.button.click()
        expect(self.button).to_be_disabled()
        self.assertEqual(self.page.evaluate("__updateMessages"), [{"type": "SKIP_WAITING"}])
        self.page.clock.fast_forward(15001)
        expect(self.button).to_be_enabled()
        expect(self.banner).to_contain_text("réessayer")
        self.page.evaluate("__updateFixture.registration.waiting = null")
        with self.page.expect_navigation():
            self.button.click()

    def test_worker_message_failure_is_visible_and_retryable(self):
        self.page.evaluate("window.__workerThrows = true")
        self.button.click()
        expect(self.button).to_be_enabled()
        expect(self.banner).to_contain_text("n’a pas abouti")
        self.assertEqual(self.page.evaluate("__updateMessages"), [])
        self.page.evaluate("__updateFixture.worker.state = 'redundant'")
        with self.page.expect_navigation():
            self.button.click()

    def test_registration_failure_does_not_leave_button_disabled(self):
        self.page.evaluate("""() => {
            __updateFixture.service.getRegistration = () => {
                throw new DOMException("Registration unavailable", "InvalidStateError");
            };
        }""")
        self.button.click()
        expect(self.button).to_be_enabled()
        expect(self.banner).to_contain_text("n’a pas abouti")

    def test_late_activation_after_timeout_does_not_reload_ongoing_work(self):
        self.button.click()
        expect(self.button).to_be_disabled()
        self.page.clock.fast_forward(15001)
        expect(self.button).to_be_enabled()
        self.page.evaluate("""() => {
            __updateFixture.registration.waiting = null;
            __updateFixture.service.controller = {};
            __updateFixture.service.dispatchEvent(new Event("controllerchange"));
        }""")
        expect(self.banner).to_contain_text("version est active")
        expect(self.button).to_be_enabled()

    def test_accepting_update_reloads_on_controller_change(self):
        self.button.click()
        expect(self.button).to_be_disabled()
        with self.page.expect_navigation():
            self.page.evaluate("""() => {
                __updateFixture.service.controller = {};
                __updateFixture.service.dispatchEvent(new Event("controllerchange"));
            }""")
