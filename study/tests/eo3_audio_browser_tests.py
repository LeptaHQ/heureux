import re
from unittest.mock import patch
from io import BytesIO, StringIO
import os
from urllib.parse import urlsplit
import wave

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from study import catalogue
from study.account_services import provision_user_study_data
from study.eo3_audio import narration_spec, word_timings
from study.models import Annotation, AnnotationKind, EO3Narration, OralStateSnapshot, PersonalResponse, Prompt
from study.routing import prompt_detail_url, review_url
from study.tache_three_models import response_text

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
        audio = buffer.getvalue()

        def serve_audio(route):
            if route.request.method != "GET":
                route.continue_()
                return
            headers = {"Accept-Ranges": "bytes"}
            requested = re.fullmatch(r"bytes=(\d+)-(\d*)", route.request.headers.get("range", ""))
            if requested:
                start = int(requested[1])
                end = min(int(requested[2]) if requested[2] else len(audio) - 1, len(audio) - 1)
                headers["Content-Range"] = f"bytes {start}-{end}/{len(audio)}"
                body, status = audio[start:end + 1], 206
            else:
                body, status = audio, 200
            headers["Content-Length"] = str(len(body))
            route.fulfill(status=status, body=body, headers=headers, content_type="audio/wav")

        self.page.route("**/expression/orale/tache-3/audio/**", serve_audio)

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
        expect(self.page.locator("[data-eo3-time] .eo3-audio__total")).to_be_hidden()
        self.page.set_viewport_size({"width": 320, "height": 740})
        self.assertEqual(self.page.evaluate(
            "() => document.documentElement.scrollWidth <= innerWidth"
        ), True)
        player = self.page.locator("[data-eo3-player]").bounding_box()
        self.assertLessEqual(player["x"] + player["width"], 320)
        self.assertTrue(self.page.locator("[data-eo3-player]").evaluate(
            "player => [...player.querySelectorAll('*')].every(node => node.getBoundingClientRect().right <= innerWidth + 0.5)"
        ))
        self.page.set_viewport_size({"width": 390, "height": 844})
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
        loop.hover()
        loop.focus()
        self.assertEqual(
            loop.evaluate("button => getComputedStyle(button).backgroundColor"), "rgb(201, 154, 18)",
        )
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

    def test_read_along_highlights_the_spoken_word_without_changing_the_text(self):
        characters = list(self.spec.text)
        step = 9 / len(characters)
        timing = word_timings(
            self.spec.text, characters,
            [index * step for index in range(len(characters))],
            [(index + 1) * step for index in range(len(characters))],
        )
        EO3Narration.objects.filter(pk=self.spec.fingerprint).update(timing=timing)
        self.page.goto(self.live_server_url + prompt_detail_url(self.prompt))
        root = self.page.locator(".answer-columns")
        before = root.inner_html()
        highlighted = """() => {
            const paint = CSS.highlights.get('eo3-reading');
            const range = paint && [...paint][0];
            if (!range) return null;
            const host = range.startContainer.parentElement;
            return {
                text: range.toString(),
                field: Boolean(host.closest('[data-response-field]')),
                prompt: Boolean(host.closest('[data-eo3-read-prompt]')),
            };
        }"""
        self.page.locator("[data-eo3-toggle]").click()
        self.page.wait_for_function(f"() => ({highlighted})() !== null")
        first = self.page.evaluate(highlighted)
        self.assertTrue(first["prompt"] or first["field"], first)
        self.assertRegex(first["text"], r"^[\w’'-]+$")
        self.page.wait_for_function(
            "() => document.querySelector('[data-eo3-audio]').currentTime > 0"
        )
        self.page.locator("[data-eo3-toggle]").click()
        self.page.locator("[data-eo3-audio]").evaluate("audio => { audio.currentTime = audio.duration * 0.6; }")
        self.page.wait_for_function(f"() => {{ const word = ({highlighted})(); return word && word.field; }}")
        position = self.page.locator("[data-eo3-audio]").evaluate("audio => audio.currentTime * 1000")
        expected = next(word for word, start, end in reversed(
            [item for paragraph in timing for item in paragraph]
        ) if start <= position)
        self.assertEqual(self.page.evaluate(highlighted)["text"], expected)
        self.assertEqual(root.inner_html(), before)
        switch = self.page.get_by_role("button", name="Surligner le mot lu")
        expect(switch).to_have_attribute("aria-pressed", "true")
        switch.click()
        expect(switch).to_have_attribute("aria-pressed", "false")
        self.assertIsNone(self.page.evaluate(highlighted))
        self.page.reload()
        expect(switch).to_have_attribute("aria-pressed", "false")
        self.page.locator("[data-eo3-toggle]").click()
        self.page.wait_for_function(
            "() => document.querySelector('[data-eo3-audio]').currentTime > 0.5"
        )
        self.assertIsNone(self.page.evaluate(highlighted))
        switch.click()
        expect(switch).to_have_attribute("aria-pressed", "true")
        self.page.wait_for_function(f"() => ({highlighted})() !== null")
        self.page.locator("[data-eo3-toggle]").click()
        self.page.set_viewport_size({"width": 320, "height": 740})
        self.assertEqual(self.page.locator("[data-eo3-player]").evaluate(
            "player => [...player.querySelectorAll('*')].filter(node => node.getBoundingClientRect().right > innerWidth + 0.5).map(node => node.className.baseVal ?? node.className + ':' + Math.round(node.getBoundingClientRect().right) + '/' + innerWidth)"
        ), [])
        self.page.set_viewport_size({"width": 390, "height": 844})
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

    @override_settings(
        ELEVENLABS_API_KEY="test-key",
        ELEVENLABS_PIN="test-audio-pin",
        FRENCH_AUDIO_GENERATION_ENABLED=True, FRENCH_AUDIO_CHARACTER_BUDGET=1_000_000,
    )
    @patch("study.french_audio.synthesize", return_value=(b"ID3-test", []))
    def test_next_asks_before_generating_missing_audio(self, provider):
        start = self.live_server_url + prompt_detail_url(self.prompt)
        self.page.goto(start)
        self.page.get_by_role("link", name="Sujet suivant et lecture").click()
        self.page.wait_for_url(lambda url: url != start)
        dialog = self.page.locator("[data-confirm-dialog]")
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text("pas encore prêt")
        dialog.get_by_role("button", name="Annuler", exact=True).click()
        expect(self.page.locator("[data-eo3-toggle]")).not_to_have_attribute("aria-busy", "true")
        provider.assert_not_called()
        self.page.go_back()
        self.page.wait_for_url(start)
        self.page.get_by_role("link", name="Sujet suivant et lecture").click()
        self.page.wait_for_url(lambda url: url != start)
        dialog.locator("[data-confirm-accept]").click()
        pin_dialog = self.page.locator("[data-audio-pin-dialog]")
        expect(pin_dialog).to_be_visible()
        pin_dialog.locator("[data-audio-pin-input]").fill("test-audio-pin")
        pin_dialog.get_by_role("button", name="Autoriser et générer l'audio", exact=True).click()
        expect(self.page.locator("[data-eo3-seek]")).to_be_visible()
        provider.assert_called_once()
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

    def select_response_field(self, field):
        target = self.page.locator(f'.answer-columns [data-response-field="{field}"]')
        target.evaluate("""element => {
            const range = document.createRange();
            range.selectNodeContents(element);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            document.dispatchEvent(new Event("selectionchange"));
        }""")
        return target

    def test_response_edits_keep_unchanged_highlights_notes_and_practice_pistes(self):
        self._assert_response_edits_keep_unchanged_highlights_notes_and_practice_pistes()

    @override_settings(EO3_AUDIO_ENABLED=False)
    def test_famille_response_edits_keep_highlights_notes_and_practice_pistes(self):
        self.prompt = Prompt.objects.select_related(
            "response", "theme__task__part",
        ).get(content_key="famille:p13")
        self._assert_response_edits_keep_unchanged_highlights_notes_and_practice_pistes()

    def _assert_response_edits_keep_unchanged_highlights_notes_and_practice_pistes(self):
        path = prompt_detail_url(self.prompt)
        self.page.goto(self.live_server_url + path)
        self.page.wait_for_load_state("networkidle")
        root = self.page.locator(".answer-columns[data-annotation-root]")
        original_key = root.get_attribute("data-annotation-source-key")
        saved = []
        for field in ("introduction", "argument-2-exemple", "argument-1-exemple"):
            target = self.select_response_field(field)
            quote = target.text_content()
            with self.page.expect_response(
                lambda response: reverse("study:annotation_create") in response.url,
            ) as created:
                self.page.locator("[data-highlight-selection]").click()
            self.assertIn(created.value.status, (200, 201))
            saved.append((created.value.json()["id"], quote))
            expect(target.locator("mark.user-highlight")).to_have_text(quote)
        self.select_response_field("conclusion")
        self.page.locator("[data-note-selection]").click()
        panel = self.page.locator("[data-note-panel]")
        panel.locator("[data-note-body]").fill("My note must survive both edits.")
        panel.get_by_role("button", name="Enregistrer sans surligner", exact=True).click()
        expect(panel).to_be_hidden()
        note = Annotation.objects.get(user=self.user, kind=AnnotationKind.NOTE)
        note_before = (note.quote, note.body, note.created_at)

        edit_path = reverse("study:edit_response", args=["eo", "tache-3", self.prompt.pk])
        self.page.goto(self.live_server_url + edit_path)
        expect(self.page.get_by_text("Version personnelle", exact=True)).to_have_count(0)
        edited = "Un nouvel exemple personnel qui conserve tous mes autres passages."
        self.page.locator("[name=argument_1_exemple]").fill(edited)
        with self.page.expect_navigation():
            self.page.get_by_role("button", name="Enregistrer la réponse", exact=True).click()
        expect(root).to_have_attribute("data-annotation-source-key", original_key)
        expect(root.locator("mark.user-highlight")).to_have_count(2)
        for identity, quote in saved[:2]:
            expect(root.locator(f'mark[data-highlight-id="{identity}"]')).to_have_text(quote)
        expect(self.page.locator('[data-response-field="argument-1-exemple"]')).to_have_text(edited)
        expect(self.page.locator("[data-eo3-player]")).to_have_count(0)
        personal = PersonalResponse.objects.get(user=self.user, response=self.prompt.response)
        self.assertFalse(OralStateSnapshot.objects.filter(user=self.user).exists())
        self.page.reload()
        expect(root.locator("mark.user-highlight")).to_have_count(2)

        self.page.goto(self.live_server_url + edit_path)
        expect(self.page.locator("[name=argument_1_exemple]")).to_have_value(edited)
        self.page.locator("[name=nuance]").fill("Une nouvelle nuance sans changer les passages surlignés.")
        with self.page.expect_navigation():
            self.page.get_by_role("button", name="Enregistrer la réponse", exact=True).click()
        expect(root.locator("mark.user-highlight")).to_have_count(2)
        current = PersonalResponse.objects.get(user=self.user, response=self.prompt.response)
        self.assertEqual((current.pk, current.created_at), (personal.pk, personal.created_at))
        self.assertFalse(OralStateSnapshot.objects.filter(user=self.user).exists())
        note.refresh_from_db()
        self.assertEqual((note.quote, note.body, note.created_at), note_before)
        self.assertEqual(note.source_key, original_key)
        self.assertEqual(note.response_anchor["field"], "conclusion")
        self.assertEqual(Annotation.objects.filter(user=self.user).count(), 4)

        self.page.goto(self.live_server_url + review_url({
            "part": "eo", "task": "tache-3", "kind": "spine",
            "response": self.prompt.response_id, "prompt": self.prompt.pk,
        }))
        self.page.wait_for_load_state("networkidle")
        self.page.locator("#reveal").click()
        back = self.page.locator("#card-back")
        expect(back).to_be_visible()
        expect(back.locator(".subject-hints--speaking")).to_be_visible()
        expect(back.locator("[data-response-field]")).to_have_count(0)
        expect(back).not_to_contain_text(edited)
        expect(back.get_by_role("link", name="Ouvrir la fiche")).to_be_visible()
        expect(back.locator("[data-eo3-player]")).to_have_count(0)
        self.assertFalse(self.errors, self.errors)

    def test_copy_subject_and_response_uses_current_text_without_touching_highlights(self):
        self.context.add_init_script("""
            window.__eo3Copied = [];
            Object.defineProperty(navigator, "clipboard", {
                configurable: true,
                value: {writeText: text => {
                    window.__eo3Copied.push(text);
                    return Promise.resolve();
                }}
            });
        """)
        self.page.goto(self.live_server_url + prompt_detail_url(self.prompt))
        self.page.wait_for_load_state("networkidle")
        prompt_copy = self.page.locator(
            '.detail-head [data-prompt-copy-source="eo3-subject-content"]',
        )
        response_copy = self.page.locator(
            '.answer-columns .section-card__tools [data-prompt-copy-source="eo3-response-content"]',
        )
        for control in (prompt_copy, response_copy):
            expect(control).to_have_class("icon-button prompt-copy-button")
            expect(control.locator("[data-prompt-copy-label]")).to_have_class("sr-only")
            self.assertLessEqual(control.bounding_box()["width"], 36)
        edit_bounds = self.page.locator(".answer-columns [data-response-edit]").bounding_box()
        copy_bounds = response_copy.bounding_box()
        self.assertGreaterEqual(copy_bounds["x"] - edit_bounds["x"] - edit_bounds["width"], 7)
        self.select_response_field("introduction")
        self.page.locator("[data-highlight-selection]").click()
        expect(self.page.locator(".answer-columns mark.user-highlight")).to_have_count(1)
        annotations = list(Annotation.objects.filter(user=self.user).values())
        self.page.get_by_role("button", name="Copier le sujet", exact=True).click()
        expect(self.page.locator("[data-prompt-copy-toast]")).to_have_text(
            "Consigne copiée dans le presse-papiers.",
        )
        model = catalogue.tache_three_models()[self.prompt.response.semantic_group].response
        copied = response_text(model)
        button = self.page.locator('[data-prompt-copy-source="eo3-response-content"]')
        button.click()
        expect(button).to_have_class(re.compile("is-copied"))
        self.assertEqual(self.page.evaluate("window.__eo3Copied"), [self.prompt.text, copied])
        self.page.set_viewport_size({"width": 320, "height": 740})
        self.assertTrue(self.page.evaluate(
            "() => document.documentElement.scrollWidth <= innerWidth",
        ))
        self.page.evaluate("""() => {
            window.HeureuxClipboard.writeText = () => Promise.reject(new Error("Clipboard denied"));
        }""")
        button.click()
        expect(button).to_have_class(re.compile("is-copy-error"))
        expect(self.page.locator("[data-prompt-copy-toast]")).to_have_text(
            "Impossible de copier la réponse.",
        )
        self.assertEqual(list(Annotation.objects.filter(user=self.user).values()), annotations)

        edit_path = reverse("study:edit_response", args=["eo", "tache-3", self.prompt.pk])
        self.page.goto(self.live_server_url + edit_path)
        edited = "Par exemple, je retrouve mes amis le samedi et je conserve mes notes."
        self.page.locator("[name=argument_1_exemple]").fill(edited)
        with self.page.expect_navigation():
            self.page.get_by_role("button", name="Enregistrer la réponse", exact=True).click()
        self.page.locator('[data-prompt-copy-source="eo3-response-content"]').click()
        expect(self.page.locator("[data-prompt-copy-toast]")).to_have_text(
            "Réponse copiée dans le presse-papiers.",
        )
        self.assertEqual(
            self.page.evaluate("window.__eo3Copied"),
            [copied.replace(model.arguments[0].exemple, edited, 1)],
        )
        expect(self.page.locator(".answer-columns mark.user-highlight")).to_have_count(1)
        self.assertFalse(self.errors, self.errors)
