import re
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
from study.models import Annotation, AnnotationKind, EO3Narration, Prompt
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

    def set_speed(self, value):
        self.page.locator("[data-eo3-speed-toggle]").click()
        self.page.locator(f'[data-eo3-speed="{value}"]').click()
        expect(self.page.locator("[data-eo3-speed-toggle]")).to_have_attribute("aria-expanded", "false")

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
        expect(self.page.locator("[data-eo3-seek]")).to_be_visible()
        self.assertEqual(audio.evaluate("audio => audio.playbackRate"), 0.85)
        self.assertTrue(audio.evaluate("audio => audio.preservesPitch"))
        expect(self.page.locator("[data-eo3-time]")).to_have_text(re.compile(r"^0:00 / \d+:\d\d$"))
        self.assertEqual(self.page.evaluate(
            "() => document.documentElement.scrollWidth <= innerWidth"
        ), True)
        toggle = self.page.locator("[data-eo3-toggle]")
        expect(toggle).to_be_visible()
        expect(toggle).to_be_enabled()
        expect(self.page.locator(".subject-progress-control__action > span")).to_have_class("sr-only")
        toggle.click()
        self.page.wait_for_function(
            "() => document.querySelector('[data-eo3-audio]').currentTime > 0"
        )
        expect(toggle).to_have_attribute("aria-pressed", "true")
        expect(toggle.locator("[data-eo3-pause-icon]")).to_be_visible()
        toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", "false")
        expect(toggle.locator("[data-eo3-play-icon]")).to_be_visible()
        self.assertTrue(audio.evaluate("audio => audio.paused"))
        toggle.click()
        self.page.wait_for_function(
            "() => !document.querySelector('[data-eo3-audio]').paused"
        )
        self.assertEqual(audio.evaluate("audio => audio.playbackRate"), 0.85)
        self.set_speed("0.75")
        self.assertEqual(audio.evaluate("audio => audio.playbackRate"), 0.75)
        self.set_speed("2")
        self.assertEqual(audio.evaluate("audio => audio.playbackRate"), 2)
        self.assertTrue(audio.evaluate("audio => audio.preservesPitch"))
        loop = self.page.get_by_role("button", name="Répéter en boucle")
        loop.click()
        expect(loop).to_have_attribute("aria-pressed", "true")
        self.assertTrue(audio.evaluate("audio => audio.loop"))
        loop.click()
        expect(loop).to_have_attribute("aria-pressed", "false")
        self.assertFalse(audio.evaluate("audio => audio.loop"))
        self.page.get_by_role("button", name="Revenir au début").click()
        self.assertLess(audio.evaluate("audio => audio.currentTime"), 1)
        self.page.evaluate("""() => document.dispatchEvent(new CustomEvent(
            "heureux:speech-start", {detail: {source: "read-aloud"}}
        ))""")
        self.assertTrue(audio.evaluate("audio => audio.paused"))
        expect(toggle).to_have_attribute("aria-pressed", "false")
        self.assertFalse(self.errors, self.errors)

    def test_next_and_previous_navigate_and_continue_reading_with_same_settings(self):
        for model in catalogue.tache_three_models().values():
            spec = narration_spec(model)
            EO3Narration.objects.get_or_create(fingerprint=spec.fingerprint, defaults={
                "group": spec.group, "voice_id": spec.voice_id,
                "model_id": spec.model_id, "audio": b"ID3-test",
            })
        start = self.live_server_url + prompt_detail_url(self.prompt)
        self.page.goto(start)
        expect(self.page.get_by_role("link", name="Sujet précédent et lecture")).to_have_count(0)
        self.set_speed("1.25")
        self.page.get_by_role("button", name="Répéter en boucle").click()
        self.page.get_by_role("link", name="Sujet suivant et lecture").click()
        self.page.wait_for_url(lambda url: url != start)
        audio = self.page.locator("[data-eo3-audio]")
        expect(self.page.locator("[data-eo3-speed-toggle]")).to_have_text("1,25×")
        expect(self.page.get_by_role("button", name="Répéter en boucle")).to_have_attribute("aria-pressed", "true")
        self.assertEqual(audio.evaluate("audio => audio.playbackRate"), 1.25)
        self.page.wait_for_function("""() => {
            const audio = document.querySelector('[data-eo3-audio]');
            const status = document.querySelector('[data-eo3-audio-status]').textContent;
            return audio.currentTime > 0 || status === 'Touchez lecture pour écouter.';
        }""")
        self.page.get_by_role("link", name="Sujet précédent et lecture").click()
        self.page.wait_for_url(start)
        expect(self.page.locator("[data-eo3-speed-toggle]")).to_have_text("1,25×")
        self.page.reload()
        expect(self.page.locator("[data-eo3-speed-toggle]")).to_have_text("0,85×")
        self.assertTrue(self.page.locator("[data-eo3-audio]").evaluate("audio => audio.paused"))
        self.assertFalse(self.errors, self.errors)

    @override_settings(EO3_AUDIO_SAMPLE_ENABLED=False, FRENCH_AUDIO_GENERATION_ENABLED=False)
    def test_pending_header_enables_after_preparation_and_preserves_completion(self):
        EO3Narration.objects.all().delete()
        self.page.goto(self.live_server_url + prompt_detail_url(self.prompt))
        pending = self.page.locator("[data-eo3-toggle]")
        expect(pending).to_be_disabled()
        self.assertLessEqual(
            float(pending.evaluate("button => getComputedStyle(button).opacity")), 0.4,
        )
        expect(self.page.locator("[data-eo3-player]")).not_to_be_visible()
        expect(self.page.locator("[data-eo3-player]")).to_contain_text("n'est pas encore prête")
        completion = self.page.locator(".subject-progress-control [role=checkbox]")
        expect(completion).to_have_attribute("aria-checked", "false")
        completion.click()
        expect(completion).to_have_attribute("aria-checked", "true")
        expect(self.page.locator(".subject-progress-control")).to_contain_text("Terminé")
        EO3Narration.objects.create(
            fingerprint=self.spec.fingerprint, group=self.spec.group,
            voice_id=self.spec.voice_id, model_id=self.spec.model_id, audio=b"ID3-test",
        )
        self.page.evaluate("""async () => {
            const response = await fetch(location.href);
            const documentCopy = new DOMParser().parseFromString(await response.text(), "text/html");
            document.querySelector("[data-eo3-player]").replaceWith(
                documentCopy.querySelector("[data-eo3-player]")
            );
            document.dispatchEvent(new CustomEvent("heureux:audio-prepared"));
        }""")
        toggle = self.page.locator("[data-eo3-toggle]")
        expect(toggle).to_be_enabled()
        self.assertFalse(toggle.evaluate("button => button.hasAttribute('data-eo3-unavailable')"))
        toggle.click()
        self.page.wait_for_function(
            "() => document.querySelector('[data-eo3-audio]').currentTime > 0"
        )
        expect(toggle).to_have_attribute("aria-pressed", "true")
        expect(completion).to_have_attribute("aria-checked", "true")
        self.assertFalse(self.errors, self.errors)

    def test_practice_controls_do_not_flip_and_hiding_stops_playback(self):
        self.page.goto(self.live_server_url + review_url({
            "part": "eo", "task": "tache-3", "kind": "spine",
            "response": self.prompt.response_id, "prompt": self.prompt.pk,
        }))
        expect(self.page.locator("#card-front")).to_contain_text(self.prompt.text)
        self.page.locator("#reveal").click()
        audio = self.page.locator("[data-eo3-audio]")
        expect(self.page.locator("[data-eo3-seek]")).to_be_visible()
        self.assertEqual(audio.evaluate("audio => audio.playbackRate"), 0.85)
        self.set_speed("2")
        self.assertEqual(audio.evaluate("audio => audio.playbackRate"), 2)
        expect(self.page.locator("#card-back")).to_be_visible()
        self.page.get_by_role("button", name="Revenir au début").click()
        expect(self.page.locator("#card-back")).to_be_visible()
        self.play()
        self.page.locator("#reveal").click()
        self.assertTrue(audio.evaluate("audio => audio.paused"))
        expect(audio).not_to_be_visible()
        self.assertFalse(self.errors, self.errors)

    def test_reset_clears_highlight_paint_but_preserves_saved_annotations(self):
        url = prompt_detail_url(self.prompt)
        self.page.goto(self.live_server_url + url)
        root = self.page.locator(".answer-columns[data-annotation-root]")
        anchor = root.evaluate("""root => {
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
                acceptNode: node => node.parentElement.closest("[data-annotation-exclude]")
                    ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT
            });
            let text = "", node;
            while ((node = walker.nextNode())) text += node.data;
            const quote = root.querySelector("p").textContent.trim();
            const start = text.indexOf(quote), end = start + quote.length;
            return {text, quote, start, end, key: root.dataset.annotationSourceKey,
                prefix: text.slice(Math.max(0, start - 160), start),
                suffix: text.slice(end, end + 160)};
        }""")
        self.assertGreaterEqual(anchor["start"], 0)
        marks = [
            Annotation.objects.create(
                user=self.user, task=self.prompt.theme.task, kind=kind,
                source_path=url, source_key=anchor["key"], quote=anchor["quote"],
                start_offset=anchor["start"], end_offset=anchor["end"],
                prefix=anchor["prefix"], suffix=anchor["suffix"],
                body="Keep this note after resetting." if kind == AnnotationKind.NOTE else "",
            )
            for kind in (AnnotationKind.NOTE, AnnotationKind.HIGHLIGHT)
        ]
        self.page.reload()
        expect(root.locator(f'mark[data-highlight-id="{marks[1].pk}"]')).to_be_visible()
        saved = list(Annotation.objects.filter(pk__in=[mark.pk for mark in marks]).values())
        completion = self.page.locator(".subject-progress-control [role=checkbox]")
        reset = self.page.locator("[data-subject-reset-form] button")
        status = self.page.locator(
            f'[data-subject-progress-status="{self.prompt.response_id}"]'
        )
        expect(reset).to_be_visible()
        expect(reset).to_have_accessible_name(
            f"Remettre ce sujet à commencer : {' '.join(self.prompt.text.split())}"
        )
        self.assertTrue(reset.evaluate("""button => Boolean(
            button.compareDocumentPosition(
                button.closest(".subject-progress-control").querySelector("[role=checkbox]")
            ) & Node.DOCUMENT_POSITION_FOLLOWING
        )"""))
        completion.click()
        expect(completion).to_have_attribute("aria-checked", "true")
        expect(status).to_have_text("Terminé")
        reset_url = self.live_server_url + self.page.locator(
            "[data-subject-reset-form]"
        ).get_attribute("action")
        with self.page.expect_response(
            lambda response: response.url == reset_url and response.request.method == "POST"
        ) as reset_response:
            reset.click()
        self.assertEqual(reset_response.value.status, 200)
        expect(completion).to_have_attribute("aria-checked", "false")
        expect(status).to_have_text("À commencer")
        expect(root.locator("mark.user-highlight")).to_have_count(0)
        self.page.reload()
        expect(completion).to_have_attribute("aria-checked", "false")
        expect(status).to_have_text("À commencer")
        expect(root.locator("mark.user-highlight")).to_have_count(0)
        reset.click()
        expect(reset).to_be_enabled()
        expect(status).to_have_text("À commencer")
        self.assertEqual(root.text_content(), anchor["text"])
        self.assertEqual(
            list(Annotation.objects.filter(pk__in=[mark.pk for mark in marks]).values()),
            [
                {**row, "hidden_on_source": row["kind"] == AnnotationKind.HIGHLIGHT}
                for row in saved
            ],
        )
        root.locator("p").first.evaluate("""paragraph => {
            const range = document.createRange();
            range.selectNodeContents(paragraph);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            document.dispatchEvent(new Event("selectionchange"));
        }""")
        self.page.locator("[data-highlight-selection]").click()
        expect(root.locator("mark.user-highlight")).to_be_visible()
        fresh = Annotation.objects.get(
            user=self.user, kind=AnnotationKind.HIGHLIGHT, hidden_on_source=False,
        )
        self.assertNotEqual(fresh.pk, marks[1].pk)
        self.page.reload()
        expect(root.locator(f'mark[data-highlight-id="{fresh.pk}"]')).to_be_visible()
        expect(root.locator(f'mark[data-highlight-id="{marks[1].pk}"]')).to_have_count(0)
        self.client.post(
            reset_url.removeprefix(self.live_server_url),
            {"completed": "0", "action": "reset"},
        )
        reset.click()
        expect(root.locator("mark.user-highlight")).to_have_count(0)
        fresh.refresh_from_db()
        self.assertTrue(fresh.hidden_on_source)
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
