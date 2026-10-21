from io import BytesIO, StringIO
import os
from urllib.parse import urlsplit
import wave

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from study import catalogue
from study.account_services import provision_user_study_data
from study.eo3_audio import narration_spec
from study.models import EO3Narration, Prompt
from study.routing import prompt_detail_url, review_url

from . import factories
from .browser_server import BrowserLiveServerThread


@override_settings(
    EO3_AUDIO_ENABLED=True,
    ELEVENLABS_VOICE_ID="FrenchFemaleVoice",
    ELEVENLABS_MODEL_ID="eleven_multilingual_v2",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class EO3AudioBrowserTests(StaticLiveServerTestCase):
    server_thread_class = BrowserLiveServerThread

    @classmethod
    def setUpClass(cls):
        cls.previous_async_unsafe = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = getattr(
            cls.playwright, os.environ.get("PLAYWRIGHT_BROWSER", "chromium"),
        ).launch()

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
        call_command("import_content", stdout=StringIO())
        self.user = factories.make_user("audio-browser-user")
        provision_user_study_data(self.user)
        self.client.force_login(self.user)
        self.prompt = Prompt.objects.select_related("theme__task__part").get(content_key="culture:p1")
        self.spec = narration_spec(catalogue.tache_three_models()[self.prompt.response.semantic_group])
        EO3Narration.objects.create(
            fingerprint=self.spec.fingerprint, group=self.spec.group,
            voice_id=self.spec.voice_id, model_id=self.spec.model_id, audio=b"ID3-test",
        )
        self.context = self.browser.new_context(
            viewport={"width": 390, "height": 844}, is_mobile=True,
            has_touch=True, service_workers="block",
        )
        self.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        buffer = BytesIO()
        with wave.open(buffer, "wb") as recording:
            recording.setnchannels(1)
            recording.setsampwidth(2)
            recording.setframerate(8000)
            recording.writeframes(b"\x00\x00" * 8000 * 10)
        # Deterministic silence tests native media behavior, not AI voice quality.
        self.page.route(
            "**/expression/orale/tache-3/audio/**",
            lambda route: route.fulfill(body=buffer.getvalue(), content_type="audio/wav"),
        )

    def tearDown(self):
        self.context.close()

    def play(self):
        self.page.evaluate("""() => {
            window.__eo3TestPlaybackReady = false;
            window.__eo3TestPlaybackError = "";
            const button = document.createElement("button");
            button.id = "test-audio-play";
            button.textContent = "Test playback";
            button.onclick = () => document.querySelector("[data-eo3-audio]").play()
                .then(() => { window.__eo3TestPlaybackReady = true; })
                .catch(error => { window.__eo3TestPlaybackError = error.message; });
            document.body.appendChild(button);
        }""")
        self.page.locator("#test-audio-play").click()
        self.page.wait_for_function(
            "() => window.__eo3TestPlaybackReady || window.__eo3TestPlaybackError"
        )
        self.assertFalse(self.page.evaluate("window.__eo3TestPlaybackError"))
        self.page.locator("#test-audio-play").evaluate("button => button.remove()")

    def test_detail_defaults_to_slow_pitch_preserving_playback_and_coordinates_speech(self):
        requests = []
        self.page.on("request", lambda request: requests.append(urlsplit(request.url).path))
        self.page.goto(self.live_server_url + prompt_detail_url(self.prompt))
        audio = self.page.locator("[data-eo3-audio]")
        expect(audio).to_be_visible()
        self.assertEqual(audio.evaluate("audio => audio.playbackRate"), 0.85)
        self.assertTrue(audio.evaluate("audio => audio.preservesPitch"))
        self.assertFalse(any("/tache-3/audio/" in path for path in requests))
        self.assertEqual(self.page.evaluate(
            "() => document.documentElement.scrollWidth <= innerWidth"
        ), True)
        self.play()
        self.assertEqual(audio.evaluate("audio => audio.playbackRate"), 0.85)
        self.page.get_by_label("Vitesse de lecture", exact=True).select_option("0.75")
        self.assertEqual(audio.evaluate("audio => audio.playbackRate"), 0.75)
        self.page.get_by_role("button", name="Revenir au début").click()
        self.assertLess(audio.evaluate("audio => audio.currentTime"), 1)
        self.page.evaluate("""() => document.dispatchEvent(new CustomEvent(
            "heureux:speech-start", {detail: {source: "read-aloud"}}
        ))""")
        self.assertTrue(audio.evaluate("audio => audio.paused"))
        self.assertFalse(self.errors, self.errors)

    def test_practice_controls_do_not_flip_and_hiding_stops_playback(self):
        self.page.goto(self.live_server_url + review_url({
            "part": "eo", "task": "tache-3", "kind": "spine",
            "response": self.prompt.response_id, "prompt": self.prompt.pk,
        }))
        expect(self.page.locator("#card-front")).to_contain_text(self.prompt.text)
        self.page.locator("#reveal").click()
        audio = self.page.locator("[data-eo3-audio]")
        expect(audio).to_be_visible()
        self.assertEqual(audio.evaluate("audio => audio.playbackRate"), 0.85)
        self.page.get_by_label("Vitesse de lecture", exact=True).select_option("1")
        expect(self.page.locator("#card-back")).to_be_visible()
        self.page.get_by_role("button", name="Revenir au début").click()
        expect(self.page.locator("#card-back")).to_be_visible()
        self.play()
        self.page.locator("#reveal").click()
        self.assertTrue(audio.evaluate("audio => audio.paused"))
        expect(audio).not_to_be_visible()
        self.assertFalse(self.errors, self.errors)

    def test_audio_failure_is_visible_and_does_not_trigger_device_voice(self):
        self.page.add_init_script("""
            window.__eo3DeviceSpeechCount = 0;
            if (window.speechSynthesis) {
                window.speechSynthesis.speak = () => { window.__eo3DeviceSpeechCount++; };
            }
        """)
        self.page.goto(self.live_server_url + prompt_detail_url(self.prompt))
        self.page.locator("[data-eo3-audio]").evaluate(
            "audio => audio.dispatchEvent(new Event('error'))"
        )
        expect(self.page.locator("[data-eo3-audio-status]")).to_contain_text("Lecture indisponible")
        self.assertEqual(self.page.evaluate("window.__eo3DeviceSpeechCount"), 0)
        self.assertFalse(self.errors, self.errors)
