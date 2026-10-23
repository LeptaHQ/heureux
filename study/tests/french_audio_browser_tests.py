from io import BytesIO, StringIO
import json
import os
import re
import wave
from unittest.mock import patch

import httpx

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from study.eo3_audio import NarrationError, narration_spec
from study.french_audio import resolve_sources, speech_spec
from study.models import Card, CardType, EO3Narration, FrenchNarration, FrenchNarrationBudget, PersonalTaskResponse, Prompt
from study.routing import prompt_detail_url, review_url
from study.tache_three_models import reviewed_model

from . import factories
from .browser_server import BrowserLiveServerThread
from .test_french_audio import SETTINGS
from .test_eo3_audio import AUDIO, AUDIO_PIN, TIMING, timed_upstream, upstream


LOCAL_SPEECH = """
window.__spoken = [];
const synthesis = {
  getVoices: () => [
    {name: "Audrey Premium", voiceURI: "local-fr", lang: "fr-FR", localService: true},
    {name: "Google French", voiceURI: "remote-fr", lang: "fr-FR", localService: false}
  ],
  addEventListener() {},
  cancel() {}, resume() {},
  speak(utterance) { window.__spoken.push({text: utterance.text, rate: utterance.rate, voice: utterance.voice && utterance.voice.name}); }
};
Object.defineProperty(window, "speechSynthesis", {value: synthesis, configurable: true});
Object.defineProperty(window, "SpeechSynthesisUtterance", {
  value: class { constructor(text) { this.text = text; } }, configurable: true
});
"""


@override_settings(
    **SETTINGS, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class FrenchAudioBrowserTests(StaticLiveServerTestCase):
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
        self.user = factories.make_user("reader-browser")
        self.client.force_login(self.user)
        self.context = self.browser.new_context(
            viewport={"width": 390, "height": 844}, is_mobile=True,
            has_touch=True, service_workers="block",
        )
        self.context.add_cookies([{
            "name": settings.SESSION_COOKIE_NAME,
            "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            "url": self.live_server_url,
        }])
        self.context.add_init_script(LOCAL_SPEECH)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.requests = []
        self.page.on("request", lambda request: self.requests.append(request.url))
        self.resolve_path = reverse("study:french_audio_resolve")
        buffer = BytesIO()
        with wave.open(buffer, "wb") as recording:
            recording.setnchannels(1)
            recording.setsampwidth(2)
            recording.setframerate(8000)
            recording.writeframes(b"\x00\x00" * 8000 * 20)
        self.page.route(
            re.compile(r".*/audio/francais/[0-9a-f]{64}/$"),
            lambda route: route.fulfill(body=buffer.getvalue(), content_type="audio/wav"),
        )
        self.page.route(
            re.compile(r".*/expression/orale/tache-3/audio/[^/]+/[0-9a-f]{64}/$"),
            lambda route: route.fulfill(body=buffer.getvalue(), content_type="audio/wav"),
        )

    def tearDown(self):
        self.assertFalse(self.errors, self.errors)
        self.context.close()

    def enter_audio_pin(self, value=AUDIO_PIN):
        dialog = self.page.locator("[data-audio-pin-dialog]")
        expect(dialog).to_be_visible()
        expect(dialog.locator("[data-audio-pin-input]")).to_have_attribute("type", "password")
        dialog.locator("[data-audio-pin-input]").fill(value)
        dialog.get_by_role("button", name="Autoriser et générer l'audio", exact=True).click()

    def cached_theme(self, ready=()):
        call_command("import_content", stdout=StringIO())
        representatives = {}
        for prompt in Prompt.objects.filter(
            theme__slug="culture", is_active=True, response__is_active=True,
        ).select_related("response", "theme__task__part").order_by(
            "family__order", "family__name", "number", "pk",
        ):
            representatives.setdefault(prompt.response_id, prompt)
        prompts = list(representatives.values())
        specs = {}
        for index in ready:
            spec = narration_spec(reviewed_model(prompts[index].response, prompts[index]))
            specs[index] = spec
            EO3Narration.objects.create(
                fingerprint=spec.fingerprint, group=spec.group, voice_id=spec.voice_id,
                model_id=spec.model_id, audio=AUDIO,
            )
        return prompts, specs

    def writing(self, task="tache-1"):
        task = factories.make_task(factories.make_part("ee"), task)
        sujet = factories.make_writing_sujet(task, versions=("Bonjour, je vous invite à découvrir ma ville.",))
        self.page.goto(self.live_server_url + reverse(
            "study:writing_sujet_detail", args=["ee", task.slug, sujet.pk],
        ))
        return sujet

    def private_presentation(self):
        task = factories.make_task(factories.make_part("eo"), "tache-1")
        PersonalTaskResponse.objects.create(
            user=self.user, task=task, body="Bonjour, voici ma présentation privée.",
        )
        self.page.goto(self.live_server_url + reverse("study:eo_tache_one_response"))

    def cache(self, selector="[data-read-aloud-text]", selected=None):
        sources = self.page.locator(selector).evaluate_all("""nodes => nodes.map(node => ({
            grant: node.dataset.speechGrant
        }))""")
        if selected:
            for source in sources:
                source["text"] = selected
        text, owner = resolve_sources(sources, self.user.pk, consent=True)
        spec = speech_spec(text, owner)
        FrenchNarration.objects.get_or_create(
            fingerprint=spec.fingerprint, defaults={
                "owner_id": owner, "requested_by": self.user, "text": text,
                "voice_id": spec.voice_id, "model_id": spec.model_id,
                "status": "ready", "audio": b"ID3-test",
            },
        )
        return spec

    def playing(self):
        self.page.wait_for_function("""() => {
            const audio = document.querySelector("[data-narrator-audio]");
            return (audio && !audio.paused) || document.querySelector("[data-narrator-status]").textContent.includes("Appuyez sur Lecture");
        }""")
        audio = self.page.locator("[data-narrator-audio]")
        if audio.evaluate("audio => audio.paused"):
            self.page.locator("[data-narrator-toggle]").click()
        self.page.wait_for_function("() => !document.querySelector('[data-narrator-audio]').paused")
        return audio

    def select(self, selector, text):
        self.page.locator(selector).evaluate("""(node, text) => {
          const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
          let child;
          while ((child = walker.nextNode())) {
            const start = child.textContent.indexOf(text);
            if (start < 0) continue;
            const range = document.createRange();
            range.setStart(child, start); range.setEnd(child, start + text.length);
            const selection = window.getSelection();
            selection.removeAllRanges(); selection.addRange(range);
            return;
          }
          throw new Error("Missing selection fixture");
        }""", text)
        expect(self.page.locator("[data-read-selection]")).to_be_visible()

    def test_ee_one_and_two_use_cached_voice_speed_pause_resume_and_restart(self):
        for task in ("tache-1", "tache-2"):
            self.writing(task)
            self.cache()
            before = len([url for url in self.requests if self.resolve_path in url])
            self.page.locator(".writing-response-controls [data-read-aloud]").first.click()
            audio = self.playing()
            self.assertEqual(audio.evaluate("audio => audio.playbackRate"), 0.85)
            self.page.locator("[data-narrator-toggle]").click()
            self.assertTrue(audio.evaluate("audio => audio.paused"))
            self.page.locator("[data-narrator-speed]").select_option("2")
            self.page.locator("[data-narrator-toggle]").click()
            self.assertEqual(audio.evaluate("audio => audio.playbackRate"), 2)
            self.assertTrue(audio.evaluate("audio => audio.preservesPitch"))
            self.page.locator("[data-narrator-restart]").click()
            self.assertLess(audio.evaluate("audio => audio.currentTime"), 1)
            self.assertEqual(len([url for url in self.requests if self.resolve_path in url]), before + 1)
            self.assertEqual(self.page.evaluate("__spoken.length"), 0)
            self.page.locator("[data-narrator-close]").click()
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"))
            # A new page starts at the requested slow default, not synthesis slowdown.

    def test_public_eo_two_reads_only_visible_questions_not_aides_or_answers(self):
        call_command("import_content", stdout=StringIO())
        prompt = Prompt.objects.select_related("theme__task__part").filter(
            theme__task__part__slug="eo", theme__task__slug="tache-2",
        ).first()
        self.page.goto(self.live_server_url + prompt_detail_url(prompt))
        spec = self.cache()
        self.assertNotIn("Pour commencer", spec.text)
        self.assertNotIn("Questions et relances", spec.text)
        self.assertEqual(len(self.page.locator("[data-read-aloud-text]").all()), 10)
        self.page.get_by_role("button", name="Lire les questions en français").click()
        self.playing()
        self.assertEqual(self.page.evaluate("__spoken.length"), 0)
        self.page.evaluate("""() => document.dispatchEvent(new CustomEvent(
            "heureux:speech-start", {detail: {source: "eo3-narration"}}
        ))""")
        expect(self.page.locator("[data-narrator]")).to_be_hidden()

    def test_eo_one_stays_local_then_explicit_private_opt_in_and_revoke(self):
        self.private_presentation()
        self.cache()
        self.page.get_by_role("button", name="Lire ma présentation en français").click()
        self.assertFalse(any(self.resolve_path in url for url in self.requests))
        spoken = self.page.evaluate("__spoken")
        self.assertEqual(spoken[0]["voice"], "Audrey Premium")
        self.assertEqual(spoken[0]["rate"], 0.85)
        self.page.locator("[data-narrator-options] summary").click()
        expect(self.page.locator("[data-narrator-natural]")).to_be_disabled()
        self.page.locator("[data-narrator-consent]").check()
        self.page.locator("[data-narrator-natural]").click()
        audio = self.playing()
        self.assertEqual(len([url for url in self.requests if self.resolve_path in url]), 1)
        self.page.locator("[data-narrator-consent]").uncheck()
        expect(audio).to_be_hidden()
        self.assertTrue(audio.evaluate("audio => audio.paused"))
        expect(self.page.locator("[data-narrator-status]")).to_contain_text("Accord retiré")
        self.page.locator("[data-narrator-close]").click()
        self.page.get_by_role("button", name="Lire ma présentation en français").click()
        self.assertFalse(self.page.locator("[data-narrator-consent]").is_checked())
        self.assertEqual(len([url for url in self.requests if self.resolve_path in url]), 1)

    def test_private_read_does_not_use_a_remote_device_voice_without_consent(self):
        self.private_presentation()
        self.page.evaluate("""() => {
          speechSynthesis.getVoices = () => [{
            name: "Google French", lang: "fr-FR", localService: false
          }];
        }""")
        self.page.get_by_role("button", name="Lire ma présentation en français").click()
        expect(self.page.locator("[data-narrator-status]")).to_contain_text("Aucune voix française locale")
        self.assertEqual(self.page.evaluate("__spoken.length"), 0)
        self.assertFalse(any(self.resolve_path in url for url in self.requests))

    def test_public_selection_uses_its_signed_substring_and_shared_media(self):
        self.writing()
        self.cache(selected="je vous invite")
        self.select(".t1-response__body", "je vous invite")
        self.page.locator("[data-read-selection]").click()
        self.playing()
        self.page.locator("[data-narrator-toggle]").click()
        self.assertEqual(self.page.evaluate("__spoken.length"), 0)
        self.assertEqual(len([url for url in self.requests if self.resolve_path in url]), 1)
        self.assertEqual(self.page.evaluate("getSelection().toString()"), "je vous invite")

    def test_private_selection_and_shared_controls_keep_selection_and_consent(self):
        self.private_presentation()
        self.cache(selected="présentation privée")
        self.select(".eo1-response__body", "présentation privée")
        self.page.locator("[data-read-selection]").click()
        self.assertEqual(self.page.evaluate("__spoken[0].text"), "présentation privée")
        self.assertFalse(any(self.resolve_path in url for url in self.requests))
        self.page.locator("[data-narrator-options] summary").click()
        self.page.locator("[data-narrator-consent]").check()
        self.page.locator("[data-narrator-natural]").click()
        self.playing()
        self.assertEqual(self.page.evaluate("getSelection().toString()"), "présentation privée")
        self.assertEqual(len([url for url in self.requests if self.resolve_path in url]), 1)

    def test_comprehension_question_dialogue_share_transport_and_rate(self):
        from study.models import ComprehensionMode

        test = factories.make_comprehension_test(mode=ComprehensionMode.ORALE)
        self.page.goto(self.live_server_url + reverse(
            "study:comprehension_oral_question_study", args=[test.slug, 1],
        ))
        self.cache('[data-co-audio-text="dialogue"]')
        self.cache('[data-co-audio-text="question"]')
        dialogue = self.page.locator('[data-co-audio-target="dialogue"]')
        dialogue.click()
        audio = self.playing()
        dialogue.click()
        self.assertTrue(audio.evaluate("audio => audio.paused"))
        self.page.locator("[data-co-audio-rate]").select_option("2")
        self.assertEqual(self.page.locator("[data-narrator-speed]").input_value(), "2")
        dialogue.click()
        self.page.locator('[data-co-audio-target="question"]').click()
        audio = self.playing()
        self.assertEqual(audio.evaluate("audio => audio.playbackRate"), 2)
        self.page.locator("[data-co-audio-stop]").click()
        self.assertTrue(audio.evaluate("audio => audio.paused"))
        self.assertEqual(self.page.evaluate("__spoken.length"), 0)

    def test_premium_error_is_explicit_never_silently_switches_device(self):
        self.writing()
        self.page.route("**" + self.resolve_path, lambda route: route.fulfill(
            status=503, body=json.dumps({"message": "Quota fournisseur indisponible."}),
            content_type="application/json",
        ))
        self.page.locator(".writing-response-controls [data-read-aloud]").first.click()
        expect(self.page.locator("[data-narrator-status]")).to_have_text("Quota fournisseur indisponible.")
        self.assertEqual(self.page.evaluate("__spoken.length"), 0)
        self.page.locator("[data-narrator-options] summary").click()
        self.page.locator("[data-narrator-device]").click()
        self.assertEqual(self.page.evaluate("__spoken.length"), 1)

    def test_hidden_recall_and_late_response_after_card_flip_never_play(self):
        card = factories.make_spine_card(user=self.user)
        self.page.goto(self.live_server_url + review_url({"kind": "spine", "response": card.response_id}))
        expect(self.page.locator("#card-front .prompt-text")).to_be_visible()
        self.page.evaluate("""() => {
          const original = window.fetch;
          window.fetch = (url, options) => url.includes("/audio/francais/resoudre/") ?
            new Promise(resolve => { window.__resolveAudio = resolve; }) : original(url, options);
        }""")
        self.page.locator("[data-review-card] [data-read-aloud]").click()
        expect(self.page.locator("[data-narrator-status]")).to_contain_text("Recherche")
        self.page.locator("#reveal").click()
        self.page.evaluate("""() => window.__resolveAudio({
            ok: true, json: () => Promise.resolve({state: "ready", url: "/not-requested.mp3"})
        })""")
        expect(self.page.locator("[data-narrator]")).to_be_hidden()
        self.assertFalse(any("/not-requested.mp3" in url for url in self.requests))
        self.assertEqual(self.page.evaluate("__spoken.length"), 0)
        self.page.locator("#reveal").click()
        self.page.locator("#card-front .prompt-text").evaluate("node => node.setAttribute('inert', '')")
        self.page.locator("[data-review-card] [data-read-aloud]").click()
        self.assertEqual(self.page.evaluate("__spoken.length"), 0)

    @override_settings(ELEVENLABS_VOICE_ID="kENkNtk0xyzG09WW40xE")
    @patch("study.french_audio.synthesize", return_value=(AUDIO, TIMING))
    def test_confirmed_sample_prepares_in_app_and_returns_existing_native_player(self, provider):
        call_command("import_content", stdout=StringIO())
        prompt = Prompt.objects.select_related("theme__task__part").get(content_key="culture:p1")
        self.page.goto(self.live_server_url + prompt_detail_url(prompt))
        button = self.page.locator("[data-eo3-toggle]")
        expect(button).to_be_enabled()
        expect(self.page.locator("[data-eo3-player]")).to_be_visible()
        self.assertLessEqual(float(button.evaluate("button => getComputedStyle(button).opacity")), 0.4)
        completion = self.page.locator(".subject-progress-control [role=checkbox]")
        completion.click()
        expect(completion).to_have_attribute("aria-checked", "true")
        button.click()
        expect(self.page.locator("[data-confirm-dialog]")).to_be_visible()
        self.page.get_by_role("button", name="Annuler", exact=True).click()
        provider.assert_not_called()
        button.click()
        self.page.get_by_role("button", name="Confirmer et préparer cet extrait").click()
        self.enter_audio_pin()
        audio = self.page.locator("[data-eo3-audio]")
        expect(self.page.locator("[data-eo3-seek]")).to_be_visible()
        self.assertTrue(audio.evaluate("audio => audio.paused"))
        self.assertEqual(audio.evaluate("audio => audio.playbackRate"), 0.85)
        self.assertEqual(self.page.locator("[data-eo3-prepare]").count(), 0)
        expect(completion).to_have_attribute("aria-checked", "true")
        expect(self.page.locator("#eo3-response-player")).to_be_visible()
        button.click()
        self.page.wait_for_function("() => !document.querySelector('[data-eo3-audio]').paused")
        expect(button).to_have_attribute("aria-pressed", "true")
        provider.assert_called_once()

    @override_settings(ELEVENLABS_VOICE_ID="kENkNtk0xyzG09WW40xE")
    @patch("study.french_audio.synthesize", side_effect=NarrationError("Provider timeout; inspect usage."))
    def test_sample_preparation_failure_is_visible_from_the_header(self, provider):
        call_command("import_content", stdout=StringIO())
        prompt = Prompt.objects.select_related("theme__task__part").get(
            theme__task__part__slug="eo", theme__task__slug="tache-3", content_key="culture:p1",
        )
        self.page.goto(self.live_server_url + prompt_detail_url(prompt))
        self.page.locator("[data-eo3-toggle]").click()
        dialog = self.page.locator("[data-confirm-dialog]")
        dialog.get_by_role("button", name="Confirmer et préparer cet extrait", exact=True).click()
        self.enter_audio_pin()
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text("Provider timeout; inspect usage.")
        expect(self.page.locator("[data-eo3-toggle]")).to_be_disabled()
        dialog.locator("[data-confirm-accept]").click()
        self.assertEqual(self.page.locator("[data-eo3-audio]").count(), 0)
        provider.assert_called_once()

    @override_settings(ELEVENLABS_VOICE_ID="kENkNtk0xyzG09WW40xE")
    @patch("study.eo3_audio.httpx.HTTPTransport")
    def test_verified_plan_rejection_then_configured_voice_change_prepares_and_plays(self, factory):
        responses = [
            upstream(json.dumps({
                "detail": {"code": "free_users_not_allowed", "message": "private provider detail"},
            }).encode(), "application/json", 403),
        ]
        requests = []

        def handle(request):
            requests.append(request)
            return responses.pop(0) if responses else timed_upstream(json.loads(request.content)["text"])

        factory.return_value = httpx.MockTransport(handle)
        call_command("import_content", stdout=StringIO())
        prompt = Prompt.objects.select_related("theme__task__part").get(content_key="culture:p1")
        url = self.live_server_url + prompt_detail_url(prompt)
        self.page.goto(url)
        self.page.locator("[data-eo3-toggle]").click()
        dialog = self.page.locator("[data-confirm-dialog]")
        dialog.locator("[data-confirm-accept]").click()
        self.enter_audio_pin()
        expect(dialog).to_contain_text("voix par défaut")
        expect(dialog).not_to_contain_text("private provider detail")
        dialog.locator("[data-confirm-accept]").click()
        self.page.reload()
        expect(self.page.locator("[data-eo3-toggle]")).to_be_disabled()
        self.assertEqual(len(requests), 1)
        with self.settings(ELEVENLABS_VOICE_ID="DefaultVoice"):
            self.page.reload()
            toggle = self.page.locator("[data-eo3-toggle]")
            expect(toggle).to_be_enabled()
            toggle.click()
            expect(dialog).to_contain_text("DefaultVoice")
            dialog.get_by_role("button", name="Annuler", exact=True).click()
            self.assertEqual(len(requests), 1)
            toggle.click()
            dialog.locator("[data-confirm-accept]").click()
            self.enter_audio_pin()
            audio = self.page.locator("[data-eo3-audio]")
            expect(self.page.locator("[data-eo3-seek]")).to_be_visible()
            self.assertTrue(audio.evaluate("audio => audio.paused"))
            toggle.click()
            self.page.wait_for_function("() => document.querySelector('[data-eo3-audio]').currentTime > 0")
            expect(toggle).to_have_attribute("aria-pressed", "true")
            toggle.click()
            expect(toggle).to_have_attribute("aria-pressed", "false")
        self.assertEqual(len(requests), 2)
        self.assertIn("/DefaultVoice/with-timestamps?", str(requests[-1].url))

    @override_settings(FRENCH_AUDIO_GENERATION_ENABLED=True, FRENCH_AUDIO_CHARACTER_BUDGET=1_000_000)
    @patch("study.eo3_audio.httpx.HTTPTransport")
    def test_play_generates_missing_response_audio_then_plays_and_reuses_it(self, factory):
        requests = []

        def handle(request):
            requests.append(request)
            return timed_upstream(json.loads(request.content)["text"])

        factory.return_value = httpx.MockTransport(handle)
        call_command("import_content", stdout=StringIO())
        prompt = Prompt.objects.select_related("theme__task__part").exclude(
            content_key="culture:p1",
        ).filter(theme__task__part__slug="eo", theme__task__slug="tache-3").order_by("pk").first()
        self.page.goto(self.live_server_url + prompt_detail_url(prompt))
        toggle = self.page.locator("[data-eo3-toggle]")
        expect(toggle).to_be_enabled()
        toggle.click()
        expect(self.page.locator("[data-confirm-dialog]")).to_be_hidden()
        pin_dialog = self.page.locator("[data-audio-pin-dialog]")
        expect(pin_dialog).to_be_visible()
        self.assertEqual(len(requests), 0)
        self.page.set_viewport_size({"width": 390, "height": 360})
        submit_box = pin_dialog.locator("[type=submit]").bounding_box()
        self.assertGreaterEqual(submit_box["y"], 0)
        self.assertLessEqual(submit_box["y"] + submit_box["height"], 361)
        self.page.set_viewport_size({"width": 390, "height": 844})
        pin_dialog.locator("[data-audio-pin-cancel]").first.click()
        expect(toggle).to_be_enabled()
        expect(self.page.locator("[data-eo3-audio]")).to_have_count(0)
        toggle.click()
        self.enter_audio_pin("incorrect")
        expect(pin_dialog.locator("[data-audio-pin-error]")).to_contain_text("incorrect")
        self.assertEqual(len(requests), 0)
        self.enter_audio_pin()
        audio = self.page.locator("[data-eo3-audio]")
        expect(self.page.locator("[data-eo3-seek]")).to_be_visible()
        self.page.wait_for_function("() => document.querySelector('[data-eo3-audio]').currentTime > 0")
        expect(toggle).to_have_attribute("aria-pressed", "true")
        toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", "false")
        expect(pin_dialog.locator("[data-audio-pin-input]")).to_have_value("")
        self.assertFalse(any(AUDIO_PIN in url for url in self.requests))
        self.assertNotIn(AUDIO_PIN, self.page.evaluate("JSON.stringify({...localStorage, ...sessionStorage})"))
        with self.settings(ELEVENLABS_PIN=""):
            self.page.reload()
            expect(self.page.locator("[data-eo3-audio]")).to_have_count(1)
            self.page.locator("[data-eo3-toggle]").click()
            self.page.wait_for_function("() => document.querySelector('[data-eo3-audio]').currentTime > 0")
            expect(self.page.locator("[data-audio-pin-dialog]")).to_be_hidden()
        self.assertEqual(len(requests), 1)

    @override_settings(FRENCH_AUDIO_GENERATION_ENABLED=True, FRENCH_AUDIO_CHARACTER_BUDGET=100000)
    @patch("study.french_audio.synthesize", return_value=AUDIO)
    def test_private_reader_pin_cancel_retry_and_cached_playback(self, provider):
        self.private_presentation()
        read = self.page.get_by_role("button", name="Lire ma présentation en français")
        read.click()
        self.page.locator("[data-narrator-options] > summary").click()
        self.page.locator("[data-narrator-consent]").check()
        self.page.locator("[data-narrator-natural]").click()
        request = self.page.locator("[data-narrator-request]")
        expect(request).to_be_visible()
        request.click()
        self.page.locator("[data-confirm-accept]").click()
        pin_dialog = self.page.locator("[data-audio-pin-dialog]")
        expect(pin_dialog).to_be_visible()
        pin_dialog.locator("[data-audio-pin-cancel]").first.click()
        expect(self.page.locator("[data-narrator-status]")).to_contain_text("annulée")
        provider.assert_not_called()
        self.assertFalse(FrenchNarration.objects.exists())
        request.click()
        self.page.locator("[data-confirm-accept]").click()
        self.enter_audio_pin("incorrect")
        expect(pin_dialog.locator("[data-audio-pin-error]")).to_contain_text("incorrect")
        provider.assert_not_called()
        self.enter_audio_pin()
        self.playing()
        provider.assert_called_once()
        expect(pin_dialog.locator("[data-audio-pin-input]")).to_have_value("")
        self.page.locator("[data-narrator-close]").click()
        with self.settings(ELEVENLABS_PIN=""):
            read.click()
            self.page.locator("[data-narrator-options] > summary").click()
            self.page.locator("[data-narrator-consent]").check()
            self.page.locator("[data-narrator-natural]").click()
            self.playing()
            expect(pin_dialog).to_be_hidden()
        provider.assert_called_once()

    @override_settings(FRENCH_AUDIO_GENERATION_ENABLED=True, FRENCH_AUDIO_CHARACTER_BUDGET=100000)
    @patch("study.french_audio.synthesize", return_value=AUDIO)
    def test_stopping_the_reader_cancels_pending_pin_authorization(self, provider):
        self.private_presentation()
        self.page.get_by_role("button", name="Lire ma présentation en français").click()
        self.page.locator("[data-narrator-options] > summary").click()
        self.page.locator("[data-narrator-consent]").check()
        self.page.locator("[data-narrator-natural]").click()
        self.page.locator("[data-narrator-request]").click()
        self.page.locator("[data-confirm-accept]").click()
        dialog = self.page.locator("[data-audio-pin-dialog]")
        expect(dialog).to_be_visible()
        dialog.locator("[data-audio-pin-input]").fill(AUDIO_PIN)
        self.page.evaluate("""() => document.dispatchEvent(
            new CustomEvent("heureux:flashcard-change"))""")
        expect(dialog).to_be_hidden()
        expect(dialog.locator("[data-audio-pin-input]")).to_have_value("")
        provider.assert_not_called()
        self.assertFalse(FrenchNarration.objects.exists())

    @override_settings(
        FRENCH_AUDIO_GENERATION_ENABLED=True, FRENCH_AUDIO_CHARACTER_BUDGET=1000000,
        ELEVENLABS_PIN="",
    )
    @patch("study.french_audio.synthesize")
    def test_cached_series_advances_skips_and_finishes_without_generation(self, provider):
        prompts, specs = self.cached_theme(ready=(0, 2))
        for entry, seconds in ((0, 3), (2, 1)):
            buffer = BytesIO()
            with wave.open(buffer, "wb") as recording:
                recording.setnchannels(1)
                recording.setsampwidth(2)
                recording.setframerate(8000)
                recording.writeframes(b"\x00\x00" * 8000 * seconds)
            self.page.route(
                re.compile(r".*/" + specs[entry].fingerprint + r"/$"),
                lambda route, _request, body=buffer.getvalue(): route.fulfill(
                    body=body, content_type="audio/wav",
                ),
            )
        start = self.live_server_url + prompt_detail_url(prompts[0])
        self.page.goto(start)
        self.page.wait_for_load_state("networkidle")
        requests = []
        self.page.on("request", lambda r: requests.append((r.method, r.url)))
        toggle = self.page.locator("[data-eo3-series-toggle]")
        toggle.click()
        audio = self.page.locator("[data-eo3-series-audio]")
        self.page.wait_for_function("() => document.querySelector('[data-eo3-series-audio]').currentTime > 0")
        expect(self.page.locator("[data-eo3-series-title]")).to_contain_text(prompts[0].text)
        self.assertEqual(audio.evaluate("a => a.playbackRate"), 0.85)
        self.assertTrue(audio.evaluate("a => a.preservesPitch"))
        audio.evaluate("a => a.dataset.samePlayer = 'yes'")
        pause = self.page.locator("[data-eo3-series-pause]")
        pause.click()
        self.assertTrue(audio.evaluate("a => a.paused"))
        pause.click()
        self.page.wait_for_function("() => !document.querySelector('[data-eo3-series-audio]').paused")
        expect(self.page.locator("[data-eo3-series-title]")).to_contain_text(prompts[2].text)
        expect(self.page.locator("[data-eo3-series-skips]")).to_contain_text("1 sujet sans audio ignoré")
        self.assertEqual(audio.get_attribute("data-same-player"), "yes")
        self.assertEqual(self.page.url, start)
        self.page.wait_for_function("() => document.querySelector('[data-eo3-series-audio]').currentTime > 0")
        expect(toggle).to_have_attribute("aria-pressed", "false")
        expect(self.page.locator("[data-eo3-series-status]")).to_contain_text("Fin des enregistrements")
        self.assertTrue(all(method == "GET" for method, _ in requests), requests)
        self.assertFalse(any("/preparer/" in url or self.resolve_path in url for _, url in requests))
        self.assertEqual(sum("/audios-enregistres/" in url for _, url in requests), 1)
        expect(self.page.locator("[data-audio-pin-dialog]")).to_be_hidden()
        expect(self.page.locator("[data-confirm-dialog]")).to_be_hidden()
        self.assertFalse(FrenchNarration.objects.exists())
        self.assertFalse(FrenchNarrationBudget.objects.exists())
        provider.assert_not_called()

    @override_settings(
        FRENCH_AUDIO_GENERATION_ENABLED=True, FRENCH_AUDIO_CHARACTER_BUDGET=1000000,
        ELEVENLABS_PIN="",
    )
    @patch("study.french_audio.synthesize")
    def test_cached_series_with_no_audio_does_not_prepare_or_ask_for_pin(self, provider):
        prompts, _ = self.cached_theme()
        self.page.goto(self.live_server_url + prompt_detail_url(prompts[0]))
        before = len(self.requests)
        self.page.locator("[data-eo3-series-toggle]").click()
        expect(self.page.locator("[data-eo3-series-status]")).to_contain_text("Aucun audio enregistré")
        expect(self.page.locator("[data-eo3-series-toggle]")).to_have_attribute("aria-pressed", "false")
        expect(self.page.locator("[data-audio-pin-dialog]")).to_be_hidden()
        expect(self.page.locator("[data-confirm-dialog]")).to_be_hidden()
        self.assertFalse(any("/preparer/" in url for url in self.requests[before:]))
        self.assertFalse(FrenchNarration.objects.exists())
        self.assertFalse(FrenchNarrationBudget.objects.exists())
        provider.assert_not_called()

    @patch("study.french_audio.synthesize")
    def test_cached_series_skips_a_recording_that_becomes_unavailable(self, provider):
        prompts, specs = self.cached_theme(ready=(0, 1))
        self.page.route(
            re.compile(r".*/" + specs[0].fingerprint + r"/$"),
            lambda route: route.fulfill(status=404, body="Unavailable"),
        )
        self.page.goto(self.live_server_url + prompt_detail_url(prompts[0]))
        self.page.locator("[data-eo3-series-toggle]").click()
        expect(self.page.locator("[data-eo3-series-title]")).to_contain_text(prompts[1].text)
        self.page.wait_for_function("() => document.querySelector('[data-eo3-series-audio]').currentTime > 0")
        expect(self.page.locator("[data-eo3-series-skips]")).to_contain_text("1 sujet sans audio ignoré")
        self.page.locator("[data-eo3-series-toggle]").click()
        expect(self.page.locator("[data-eo3-series-panel]")).to_be_hidden()
        self.assertIsNone(self.page.locator("[data-eo3-series-audio]").get_attribute("src"))
        provider.assert_not_called()

    def test_cached_series_rejects_external_and_preparation_urls(self):
        prompts, _ = self.cached_theme()
        self.page.goto(self.live_server_url + prompt_detail_url(prompts[0]))
        endpoint = self.page.locator("[data-eo3-series-toggle]").get_attribute("data-eo3-series-url")
        for media in (
            "https://api.elevenlabs.io/v1/text-to-speech/unwanted",
            reverse("study:eo3_audio_prepare", args=["culture-p1", "0" * 64]),
        ):
            with self.subTest(media=media):
                self.page.route("**" + endpoint, lambda route: route.fulfill(
                    content_type="application/json", body=json.dumps({
                        "theme": "Culture", "start_position": 1, "total_subjects": 1,
                        "tracks": [{
                            "position": 1, "title": "Invalid media",
                            "source_url": prompt_detail_url(prompts[0]), "audio_url": media,
                        }],
                    }),
                ))
                before = len(self.requests)
                self.page.locator("[data-eo3-series-toggle]").click()
                expect(self.page.locator("[data-eo3-series-status]")).to_contain_text("accepte uniquement")
                self.assertFalse(any("elevenlabs.io" in url or "/preparer/" in url for url in self.requests[before:]))
                self.page.unroute("**" + endpoint)
