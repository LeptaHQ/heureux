import json
import re
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect

from study.models import LiveSimulation, OralEvaluationJob
from study.simulation import live_conversation, oral_jobs
from study.views.helpers import tache_two_publication

from . import factories


PILOT_PIN = "test-audio-pin"


class LiveConversationBrowserMixin:
    def choose_oral_grader(self, name):
        self.page.locator("#lv-assess").click()
        self.page.get_by_role("group", name="Modèles d’évaluation").get_by_role("button", name=name).click()

    @override_settings(
        GEMINI_API_KEY="fixture-gemini", GROQ_API_KEY="fixture-groq", AI_PIN=PILOT_PIN,
        CLOUDFLARE_WORKERS_API_KEY="fixture-workers", CLOUDFLARE_ACCOUNT_ID="0123456789abcdef" * 2,
    )
    def test_oral_bilan_reuses_the_model_picker_and_keeps_a_failed_switch_private(self):
        factories.make_task(self.part, "tache-2")
        rows = [{"speaker": "user", "text": "Bonjour, j’ai une question."}]
        groq = {"score": 12, "scoreStatus": "scored", "nclc": "8", "cefr": "B2", "reason": "Bilan Groq.",
                "criteria": [], "evidence": [], "annotations": [], "next": "", "proposal": []}
        workers = {**groq, "score": 10, "nclc": "7", "reason": "Bilan Workers."}
        saved = LiveSimulation.objects.create(
            user=self.user, rows=rows, report=groq, provider_reports={"cloudflare": workers},
            snapshot={"prompt": "Demandez des renseignements sur les ateliers."},
        )
        posts = []
        endpoint = reverse("study:eo_tache_two_live_evaluation")

        def reject_gemini(route):
            posts.append(route.request.post_data_json)
            route.fulfill(status=503, json={"error": "Gemini indisponible."})

        self.page.route(f"**{endpoint}", reject_gemini)
        url = reverse("study:eo_tache_two_live", query={"simulation": saved.pk})
        self.page.goto(self.live_server_url + url)
        level = self.page.locator("#lv-level")
        expect(level).to_have_text("12/20 · NCLC 8 · B2")
        sparkle = self.page.locator(".lv-title-row").get_by_role("button", name="Choisir le modèle d’évaluation")
        expect(sparkle.locator('[data-icon="sparkles"]')).to_be_visible()
        sparkle.click()
        menu = self.page.get_by_role("group", name="Modèles d’évaluation")
        expect(menu.get_by_role("button")).to_have_text(["Groq", "Gemini", "Workers"])
        expect(menu.get_by_role("button", name="Groq")).to_have_attribute("aria-pressed", "true")
        menu.get_by_role("button", name="Workers").click()
        expect(level).to_have_text("10/20 · NCLC 7 · B2")
        self.choose_oral_grader("Gemini")
        pin = self.page.locator("[data-audio-pin-dialog]")
        expect(pin).to_contain_text("envoyée à Gemini")
        self.assertEqual(posts, [])
        pin.get_by_label("Code", exact=True).fill(PILOT_PIN)
        pin.get_by_role("button", name="Demander le bilan").click()
        expect(self.page.get_by_role("status").filter(has_text="Gemini indisponible.")).to_be_visible()
        expect(level).to_have_text("10/20 · NCLC 7 · B2")
        sparkle.click()
        expect(menu.get_by_role("button", name="Workers")).to_have_attribute("aria-pressed", "true")
        self.page.keyboard.press("Escape")
        expect(sparkle).to_be_focused()
        self.choose_oral_grader("Groq")
        expect(level).to_have_text("12/20 · NCLC 8 · B2")
        self.assertEqual(posts, [{
            "consent": True, "provider": "gemini", "pin": PILOT_PIN, "simulation": str(saved.pk), "rows": rows,
        }])

    def open_live_pilot(self, *, subject_args=(), opinion=False, workers=False):
        """Real Web Audio and worklet; synthetic input and a local stand-in for Gemini."""
        self.enterContext(override_settings(
            GROQ_API_KEY="fixture-groq-key", GEMINI_API_KEY="fixture-not-a-key", AI_PIN=PILOT_PIN,
            CLOUDFLARE_WORKERS_API_KEY="fixture-workers" if workers else "",
            CLOUDFLARE_ACCOUNT_ID="0123456789abcdef" * 2 if workers else "",
        ))
        self.opinion = opinion
        studio = "study:eo_tache_three_live" if opinion else "study:eo_tache_two_live"
        factories.make_task(self.part, "tache-3" if opinion else "tache-2")
        self.page.add_init_script("""
        window.probe = {calls:0, readers:[], sockets:[], played:[], sent:[], readingMessages:[]};
        const p = window.probe;
        window.AudioContext = class extends window.AudioContext {
          constructor(...args) { super(...args); p.audio = this; }
          createBufferSource() {
            const node = super.createBufferSource();
            const stop = node.stop.bind(node);
            node.stop = () => { node.wasStopped = true; stop(); };
            p.played.push(node);
            return node;
          }
        };
        Object.defineProperty(navigator, 'mediaDevices', {value: {getUserMedia: async () => {
          p.calls++;
          if (p.deny) throw new DOMException('Denied', 'NotAllowedError');
          const out = p.audio.createMediaStreamDestination(), tone = p.audio.createOscillator();
          if (!p.silent) tone.connect(out);
          tone.start();
          p.track = out.stream.getAudioTracks()[0];
          if (p.wait) {
            document.documentElement.dataset.waiting='true';
            await new Promise(resolve => p.release = resolve);
          }
          return out.stream;
        }}});
        window.WebSocket = class {
          static OPEN = 1;
          constructor(url) {
            this.url=url; this.readyState=1; this.bufferedAmount=0;
            this.reading=decodeURIComponent(url).endsWith('auth_tokens/reader');
            (this.reading ? p.readers : p.sockets).push(this);
            queueMicrotask(() => this.onopen?.());
          }
          send(value) {
            const message = JSON.parse(value);
            (this.reading ? p.readingMessages : p.sent).push(message);
            if (message.setup) document.documentElement.dataset[this.reading ? 'reader' : 'handshake']='true';
            if (message.realtimeInput?.audio && !document.documentElement.dataset.hasAudio &&
                /[^\\x00]/.test(atob(message.realtimeInput.audio.data)))
              document.documentElement.dataset.hasAudio='true';
          }
          receive(value) {
            this.onmessage?.({data:new TextEncoder().encode(JSON.stringify(value)).buffer});
          }
          close() { this.readyState=3; }
        };""")
        self.token_requests = []
        self.token_replies = {}
        self.mint_status = 200

        def fake_token(route):
            body = route.request.post_data_json
            self.token_requests.append(body)
            if self.mint_status != 200:
                route.fulfill(status=self.mint_status, json={})
                return
            purpose = body["purpose"]
            token = "auth_tokens/exchange" if purpose == "exchange" else "auth_tokens/reader"
            with patch.object(live_conversation, "_request_token", return_value=token):
                response = route.fetch()
            if response.ok:
                self.token_replies[purpose] = response.json()
            route.fulfill(response=response)

        self.page.route("**" + reverse(studio + "_token", args=subject_args), fake_token)
        self.page.route("**" + reverse(studio + "_evaluation", args=subject_args), lambda route: route.fulfill(
            status=503, json={"error": "Le service de bilan est indisponible."},
        ))
        if opinion and subject_args:
            details = reverse("study:response_detail", args=("eo", "tache-3", *subject_args))
            self.page.goto(self.live_server_url + details)
            self.page.get_by_role("link", name="Simuler la tâche 3 sur ce sujet").click()
        elif subject_args:
            details = reverse("study:task_subject_detail", args=("eo", "tache-2", *subject_args))
            self.page.goto(self.live_server_url + details)
            self.selected_consigne = self.page.locator("#tache-two-subject-prompt").text_content()
            prompt = self.page.locator(".tache-two-consigne")
            launch = prompt.get_by_role("link", name="Lancer la conversation sur ce sujet")
            copy = prompt.locator("[data-prompt-copy]")
            expect(copy).to_have_accessible_name(re.compile(r"^Copier la consigne"))
            self.assertEqual(prompt.locator(".tache-two-consigne__actions [data-icon]").evaluate_all(
                "icons => icons.map(icon => icon.dataset.icon)"), ["headphones", "copy"])
            expect(launch).to_have_text("")
            expect(copy.locator("[data-prompt-copy-label]")).to_have_class("sr-only")
            self.assertLess(launch.bounding_box()["x"], copy.bounding_box()["x"])
            self.page.evaluate("""Object.defineProperty(navigator, 'clipboard', {
                configurable:true, value:{writeText: async text => { window.copiedPrompt = text; }}
            })""")
            copy.click()
            expect(copy).to_have_class(re.compile(r"\bis-copied\b"))
            self.assertEqual(self.page.evaluate("window.copiedPrompt"), json.loads(self.selected_consigne))
            self.assert_no_horizontal_overflow()
            launch.click()
        else:
            self.page.goto(self.live_server_url + reverse(studio))
        self.start = self.page.locator("#lv-start")
        self.pin_dialog = self.page.locator("[data-audio-pin-dialog]")

    def submit_live_pin(self, pin=PILOT_PIN):
        expect(self.pin_dialog.get_by_role("heading")).to_have_text("Autoriser la simulation")
        self.pin_dialog.get_by_label("Code", exact=True).fill(pin)
        self.pin_dialog.get_by_role("button", name="Autoriser cette simulation").click()

    def finish_prompt(self):
        expect(self.page.locator("html")).to_have_attribute("data-reader", "true")
        self.page.evaluate("""() => {
          delete document.documentElement.dataset.reader;
          const ws = probe.readers.at(-1);
          ws.receive({setupComplete:{}});
          ws.receive({serverContent:{modelTurn:{parts:[{inlineData:{
            mimeType:'audio/pcm;rate=24000',data:btoa('\\x01\\x00'.repeat(240))
          }}]},turnComplete:true}});
        }""")
        if not self.opinion:
            expect(self.page.locator("#lv-prep")).to_be_visible()

    def start_preparation(self):
        self.start.click()
        self.submit_live_pin()
        self.finish_prompt()

    def test_native_voice_subject_launch_uses_exact_consigne_and_retains_return_link(self):
        task = self._import_eo_tache_two_content()
        args = ("octobre", 5, 21)
        self.open_live_pilot(subject_args=args)
        subject = tache_two_publication(*args)[2]
        expect(self.page).to_have_title(f"Simulation · {task.short_label} · {subject.title} · Heureux")
        expect(self.page.get_by_role("heading", level=1)).to_have_text("Simulation")
        expect(self.start).to_have_accessible_name("Démarrer")
        expect(self.start).to_have_text("Démarrer")
        expect(self.start.locator('[data-icon="play"]')).to_be_visible()
        expect(self.page.locator(".lv-selected-subject")).to_be_visible()
        expect(self.page.get_by_role("navigation", name="Fil d’Ariane")).to_contain_text("EO")
        expect(self.page.get_by_role("navigation", name="Navigation entre les sujets")).to_be_visible()
        expect(self.page.locator("#prompt-select-top option[selected]")).to_contain_text(subject.title)
        self.page.set_viewport_size({"width": 1280, "height": 850})
        self.assertLess(self.page.locator("#lv-title").bounding_box()["y"], self.page.locator(".lv-steps").bounding_box()["y"])
        expect(self.pin_dialog).to_be_hidden()  # The PIN waits for « Démarrer ».
        self.assertEqual(self.token_requests, [])
        self.start.click()
        self.submit_live_pin()
        self.finish_prompt()
        heading = self.page.get_by_role("heading", level=1)
        expect(heading).to_have_text("Votre consigne")
        expect(heading).to_be_focused()
        # Reproduce keyboard modality: the phase heading stays plain, controls keep their ring.
        self.page.keyboard.press("Tab")
        expect(self.page.locator("#lv-notepad summary")).to_be_focused()
        expect(self.page.locator("#lv-notepad summary")).to_have_css("outline-style", "solid")
        heading.focus()
        expect(heading).to_have_css("outline-style", "none")
        expect(self.page.locator("#lv-prompt")).to_have_text(json.loads(self.selected_consigne))
        self.assertEqual(self.page.evaluate("probe.calls"), 0)
        self.page.locator("#lv-skip").click()
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.page.locator("#lv-end").click()
        self.page.locator("#lv-done").get_by_role("link", name="Étudier ce sujet").click()
        expect(self.page).to_have_url(self.live_server_url + reverse("study:task_subject_detail", args=("eo", "tache-2", *args)))

    def test_native_voice_opinion_reads_then_listens_until_deadline_and_keeps_last_words(self):
        prompt = self.first.response.prompts.get()
        prompt.text = "Vaut-il mieux découvrir une ville à pied plutôt qu’en voiture ?"
        prompt.save(update_fields=["text"])
        args = (prompt.pk,)
        self.open_live_pilot(opinion=True, subject_args=args, workers=True)
        expect(self.page).to_have_title(f"Simulation · {self.task.short_label} · {prompt.text} · Heureux")
        expect(self.page.get_by_role("heading", level=1)).to_have_text("Simulation")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.evaluate("document.documentElement.dataset.theme = 'dark'")
        self.assertLess(self.page.locator("#lv-title").bounding_box()["y"], self.page.locator(".lv-steps").bounding_box()["y"])
        self.assert_no_horizontal_overflow()
        expect(self.page).to_have_url(self.live_server_url + reverse("study:eo_tache_three_live", args=args))
        paragraphs = [
            "Je préfère découvrir une ville à pied. En marchant, je peux m’arrêter et remarquer des détails. "
            "C’est comme ça que j’ai découvert une cour derrière le marché.",
            "Cela dit, la marche ne convient pas à tout le monde. Ma sœur ne peut pas marcher longtemps, "
            "alors quand je visite une ville avec elle, nous prenons la voiture.",
        ]
        spoken = "Moi, je préfère marcher, parce qu’on peut s’arrêter, euh, on voit les petits détails. "
        last_words = "Une fois, j’ai vu une cour derrière le marché. Mais ma sœur, elle peut pas marcher longtemps, "
        ending = "alors avec elle on prend la voiture."
        report = {"score": 12, "scoreStatus": "scored", "nclc": "8", "cefr": "B2", "evidenceVersion": 1, "graderVersion": 0,
                  "reason": "Vous expliquez pourquoi vous préférez marcher, puis précisez quand vous choisissez la voiture.",
                  "next": "Après l’exemple du marché, revenez à votre idée : « En voiture, je n’aurais pas remarqué cette cour. »",
                  "criteria": [{"label": label, "score": 3, "why": why, "turnIndex": 0, "quote": quote} for label, why, quote in (
                      ("Accomplissement de la tâche", "Vous indiquez une préférence et une limite.", "je préfère marcher"),
                      ("Cohérence et fluidité", "L’exemple du marché illustre votre préférence.", "une cour derrière le marché"),
                      ("Précision lexicale", "Vos mots permettent de situer la scène.", "derrière le marché"),
                      ("Correction grammaticale", "Vous exprimez la cause avec une proposition complète.", "parce qu’on peut s’arrêter"))],
                  "annotations": [], "evidence": [{"turnIndex": 0, "quote": "avec elle on prend la voiture",
                                                    "why": "Vous nuancez votre avis en tenant compte de votre sœur."}],
                  "proposal": paragraphs}
        calls = []
        evaluation = "**" + reverse("study:eo_tache_three_live_evaluation", args=args)
        self.page.route(evaluation, lambda route: calls.append(route))
        self.page.clock.install(time="2026-03-16T10:00:00Z")
        self.page.clock.pause_at("2026-03-16T10:00:05Z")
        self.start.click()
        expect(self.pin_dialog).to_contain_text("Transcription envoyée à Workers pour le bilan.")
        self.submit_live_pin()
        expect(self.page.locator("html")).to_have_attribute("data-reader", "true")
        expect(self.page.locator("#lv-prompt")).to_have_text(prompt.text)
        self.page.clock.fast_forward(8_000)
        self.assertEqual(self.page.evaluate("[probe.calls, probe.sockets.length]"), [0, 0])
        self.finish_prompt()
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.assertFalse(self.page.evaluate("probe.track.enabled"))
        self.page.clock.fast_forward(5_000)
        expect(self.page.locator("#lv-time")).to_be_hidden()
        self.page.evaluate("""() => {
          const ws = probe.sockets[0];
          Object.defineProperty(probe.track, 'muted', {value:true, configurable:true});
          ws.receive({setupComplete:{}});
        }""")
        self.page.clock.fast_forward(4_000)
        expect(self.page.locator("#lv-status")).to_contain_text("le chronomètre attend")
        expect(self.page.locator("#lv-time")).to_be_hidden()
        self.page.evaluate("""text => {
          const ws = probe.sockets[0];
          delete probe.track.muted;
          probe.track.dispatchEvent(new Event('unmute'));
          ws.receive({serverContent:{inputTranscription:{text},
            outputTranscription:{text:'Interruption.'}, modelTurn:{parts:[{
              inlineData:{mimeType:'audio/pcm',data:btoa('\\0'.repeat(480))}
            }]},turnComplete:true}});
        }""", spoken)
        self.assertEqual(self.page.evaluate("probe.played.length"), 1)  # Only the question was audible.
        self.assertFalse(self.page.evaluate("probe.sent.some(m => m.realtimeInput?.text)"))
        expect(self.page.locator("#lv-notepad")).to_be_hidden()
        expect(self.page.locator("#lv-clock")).to_have_text("04:30")
        self.page.clock.fast_forward(269_000)
        expect(self.page.locator("#lv-clock")).to_have_text("00:01")
        self.page.clock.fast_forward(1_000)
        self.assertEqual(self.page.evaluate("[probe.track.readyState, probe.sent.at(-1).realtimeInput.audioStreamEnd]"),
                         ["ended", True])
        expect(self.page.get_by_role("heading", name="Temps écoulé")).to_be_visible()
        expect(self.page.locator("#lv-status")).to_contain_text("Le micro est coupé")
        expect(self.page.locator(".lv-track")).to_be_hidden()
        expect(self.page.locator(".lv-orb")).to_be_hidden()
        self.assert_no_horizontal_overflow()
        self.page.evaluate("""() => {
          Object.defineProperty(document, 'hidden', {configurable:true, value:true});
          document.dispatchEvent(new Event('visibilitychange'));
        }""")
        self.assertEqual(self.page.evaluate("[probe.track.readyState, probe.sockets[0].readyState]"), ["ended", 1])
        self.page.clock.fast_forward(1_500)
        self.page.evaluate("text => probe.sockets[0].receive({serverContent:{inputTranscription:{text}}})", last_words)
        self.page.clock.fast_forward(1_200)
        self.page.evaluate("text => probe.sockets[0].receive({serverContent:{inputTranscription:{text,finished:true}}})", ending)
        with self.page.expect_request(evaluation):
            self.page.evaluate("probe.sockets[0].onclose({wasClean:true})")
        self.page.evaluate("delete document.hidden")
        expect(self.page.locator("#lv-level")).to_have_text("Bilan en préparation…")
        expect(self.page.locator("#lv-assessment-status")).to_be_visible()
        subject_card = self.page.locator("#lv-subject")
        expect(subject_card.locator("#lv-subject-prompt")).to_have_text(prompt.text)
        expect(subject_card.locator("#lv-status")).to_be_visible()
        expect(self.page.locator("#lv-prompt")).to_be_hidden()
        expect(self.page.locator("#lv-turns li p")).to_have_text(spoken + last_words + ending)
        calls[0].fulfill(json=report)
        expect(self.page.locator("#lv-level")).to_have_text("12/20 · NCLC 8 · B2")
        saved = LiveSimulation.objects.get(user=self.user)
        self.assertEqual((saved.subject_key, saved.elapsed_ms, saved.rows),
                         (f"eo3:{prompt.pk}", 270_000, [{"speaker": "user", "text": spoken + last_words + ending}]))
        self.assertEqual(saved.snapshot["prompt"], prompt.text)
        self.assertEqual(calls[0].request.post_data_json, {
            "rows": saved.rows, "simulation": str(saved.pk), "consent": True, "provider": "cloudflare",
            "reviewGrant": self.token_replies["exchange"]["reviewGrant"],
        })
        self.assertEqual(len(self.token_requests), 2)
        expect(self.page.locator("#lv-fig-turns")).to_have_text(str(len((spoken + last_words + ending).split())))
        expect(self.page.locator("#lv-share")).to_be_hidden()
        proposal = self.page.locator("#lv-proposal")
        expect(proposal.locator("#lv-proposal-lines > p")).to_have_text(paragraphs)
        expect(proposal.get_by_role("list")).to_have_count(0)
        self.page.evaluate("""() => Object.defineProperty(navigator, 'clipboard', {configurable: true,
          value:{writeText: async text => { window.copiedProposal = text; }}})""")
        proposal.get_by_role("button", name="Copier").click()
        self.assertEqual(self.page.evaluate("window.copiedProposal"), "\n\n".join(paragraphs))
        self.page.locator("#lv-assessment summary").click()
        details = self.page.locator("#lv-assessment-result")
        expect(details.get_by_role("heading", name="Au prochain essai")).to_be_visible()
        for width, theme in ((320, "dark"), (1280, "light")):
            self.page.set_viewport_size({"width": width, "height": 844})
            self.page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
            expect(details).to_be_visible()
            full = details.bounding_box()
            strengths, marks = [part.bounding_box() for part in details.locator(".lv-assessment__part").all()]
            self.assertGreaterEqual(marks["y"], strengths["y"] + strengths["height"])
            for part in (strengths, marks):
                self.assertAlmostEqual(part["x"], full["x"], delta=1)
                self.assertAlmostEqual(part["width"], full["width"], delta=1)
            self.assert_no_horizontal_overflow()
        transcript = self.page.locator("#lv-transcript")
        if transcript.evaluate("el => el.open"):
            transcript.locator("summary").click()
        details.get_by_role("link", name="une cour derrière le marché").press("Enter")
        expect(self.page.locator("#lv-turn-0")).to_be_focused()
        expect(self.page.locator("#lv-turn-0")).to_be_visible()
        LiveSimulation.objects.filter(pk=saved.pk).update(report=report)
        self.page.reload()
        expect(self.page.locator("#lv-level")).to_have_text("12/20 · NCLC 8 · B2")
        expect(proposal.locator("#lv-proposal-lines > p")).to_have_text(paragraphs)
        expect(subject_card.locator("#lv-subject-prompt")).to_have_text(prompt.text)
        self.assertEqual(len(calls), 1)
        self.page.locator("#lv-retry").click()
        expect(self.page.get_by_role("heading", level=1)).to_have_text("Simulation")
        expect(subject_card).to_be_hidden()
        expect(self.page.locator("#lv-console #lv-status")).to_be_attached()
        self.assertNotIn("#lv-", self.page.url)

    def test_native_voice_suspended_mobile_audio_recovers_and_reports_silent_input(self):
        self.open_live_pilot()
        self.page.clock.install(time="2026-03-16T10:00:00Z")
        self.page.clock.pause_at("2026-03-16T10:00:05Z")
        self.start_preparation()
        self.page.evaluate("probe.silent=true")
        self.page.locator("#lv-skip").click()
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.page.evaluate("probe.audio.suspend()")
        self.page.clock.fast_forward(28_000)
        self.page.evaluate("probe.sockets[0].receive({setupComplete:{}})")
        resume = self.page.get_by_role("button", name="Réactiver le son")
        expect(resume).to_be_visible()
        expect(self.page.locator("#lv-time")).to_be_hidden()
        self.page.clock.fast_forward(5_000)
        self.assertFalse(self.page.evaluate("probe.track.enabled"))
        resume.click()
        expect(self.page.locator("#lv-clock")).to_have_text("03:30")
        self.page.clock.fast_forward(6_000)
        expect(self.page.locator("#lv-mic-signal")).to_contain_text("Aucun son détecté")
        self.page.evaluate("probe.audio.suspend()")
        resume.click()
        expect(self.page.locator("#lv-clock")).to_have_text("03:24")
        self.assertEqual(self.page.evaluate("[probe.calls,probe.sockets.length]"), [1, 1])
        self.assertEqual(len(self.token_requests), 2)
        self.assert_no_horizontal_overflow()

    def test_native_voice_waits_for_handshake_and_supports_interruption(self):
        self.open_live_pilot()
        expect(self.page.locator("#lv-setup input[type=checkbox], #lv-setup .lv-terms")).to_have_count(0)
        expect(self.start).to_be_enabled()
        self.start.click()
        self.assertEqual(self.page.evaluate("probe.calls"), 0)
        expect(self.pin_dialog).to_contain_text("Voix envoyée à Google (examen humain possible).")
        expect(self.pin_dialog).to_contain_text("Transcription envoyée à Groq pour le bilan.")
        expect(self.pin_dialog).to_contain_text("18 ans ou plus, au Canada ou aux États-Unis.")
        self.assertEqual(self.token_requests, [])
        self.submit_live_pin("incorrect")
        expect(self.pin_dialog.get_by_role("alert")).to_have_text("Code incorrect.")
        self.assertEqual(self.page.evaluate("[probe.calls,probe.readers.length,probe.sockets.length]"), [0, 0, 0])
        self.submit_live_pin()
        self.finish_prompt()
        self.assertEqual(self.token_requests[-1], {
            "consent": True, "purpose": "attempt", "pin": PILOT_PIN, "reviewProvider": "groq",
        })
        self.page.evaluate("document.getElementById('lv-skip').click(); document.getElementById('lv-skip').click()")
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.assertEqual(self.token_requests[-1], {
            "consent": True, "purpose": "exchange", "exchangeGrant": self.token_replies["attempt"]["exchangeGrant"],
        })
        self.assertEqual(len(self.token_requests), 3)  # Bad PIN, corrected PIN, one exchange.
        self.assertEqual(self.page.evaluate("[probe.calls,probe.sockets.length]"), [1, 1])
        self.assertNotIn(PILOT_PIN, self.page.evaluate("probe.readers[0].url + probe.sockets[0].url + JSON.stringify([probe.readingMessages,probe.sent])"))
        expect(self.pin_dialog.get_by_label("Code", exact=True)).to_have_value("")
        self.assertEqual(self.page.evaluate("probe.sent.map(m => Object.keys(m))"), [["setup"]])
        self.assertFalse(self.page.evaluate("probe.track.enabled"))
        self.page.evaluate("probe.sockets[0].receive({setupComplete:{}})")
        self.page.evaluate("probe.sockets[0].receive({setupComplete:{}})")
        self.assertEqual(self.page.evaluate("probe.sent.filter(m => m.realtimeInput?.text?.includes('Bonjour')).length"), 1)
        expect(self.page.locator("html")).to_have_attribute("data-has-audio", "true")
        expect(self.page.locator("#lv-mic-signal")).to_contain_text("Son détecté")
        audio = self.page.evaluate("""() => {
          const a = probe.sent.find(m => m.realtimeInput?.audio && /[^\\x00]/.test(atob(m.realtimeInput.audio.data))).realtimeInput.audio;
          const b = atob(a.data);
          return [a.mimeType,b.length,[...b].some(c => c.charCodeAt(0) !== 0)];
        }""")
        self.assertEqual(audio, ["audio/pcm;rate=16000", 2048, True])
        self.page.evaluate("""probe.sockets[0].receive({serverContent:{
          inputTranscription:{text:'Le samedi ?'},
          modelTurn:{parts:[{inlineData:{mimeType:'audio/pcm;rate=24000',data:btoa('\\0'.repeat(96000))}}]}
        }})""")
        self.assertEqual(self.page.evaluate("probe.played.at(-1).buffer.sampleRate"), 24000)
        self.page.locator("#lv-captions summary").click()
        self.page.evaluate("""() => {
          const send = serverContent => probe.sockets[0].receive({serverContent});
          send({inputTranscription:{text:"Et le "}});
          send({outputTranscription:{text:"À dix heures."}});
          send({interrupted:true});
          send({turnComplete:true});
          send({inputTranscription:{text:"dimanche ?",finished:true}});
        }""")
        expect(self.page.locator("#lv-ai-words")).to_have_text("À dix heures.")
        self.assertTrue(self.page.evaluate("probe.played.at(-1).wasStopped && probe.track.enabled"))
        mute = self.page.get_by_role("button", name="Couper le micro")
        expect(mute).to_have_text("")
        mute.click()
        expect(mute.locator('[data-icon="microphone-off"]')).to_be_visible()
        self.assertFalse(self.page.evaluate("probe.track.enabled"))
        self.assertTrue(self.page.evaluate("probe.sent.at(-1).realtimeInput.audioStreamEnd"))
        mute.click()
        expect(mute.locator('[data-icon="microphone"]')).to_be_visible()
        self.assertTrue(self.page.evaluate("probe.track.enabled"))
        self.page.locator("#lv-end").click()
        self.assertEqual(self.page.evaluate("[probe.track.readyState,probe.sockets[0].readyState,probe.audio.state]"),
                         ["ended", 3, "closed"])
        expect(self.page.locator("#lv-user-words")).to_have_text("—")
        self.page.locator("#lv-transcript summary").click()
        expect(self.page.locator("#lv-turns li p")).to_have_text(["Le samedi ?", "À dix heures.", "Et le dimanche ?"])
        expect(self.page.locator('#lv-turns [data-speaker="model"]')).to_contain_text("interrompue")
        self.page.locator("#lv-retry").click()
        expect(self.page.locator("#lv-turns li")).to_have_count(0)
        expect(self.start).to_be_enabled()
        self.assert_no_horizontal_overflow()

    def test_native_voice_deadline_closes_call_even_in_mid_reply(self):
        self.open_live_pilot()
        self.page.clock.install(time="2026-03-16T10:00:00Z")
        self.page.clock.pause_at("2026-03-16T10:00:05Z")
        self.start_preparation()
        notes = self.page.locator("#lv-notes")
        scratch = "Premier repère\nDeuxième repère"
        notes.fill(scratch)
        self.page.clock.fast_forward(119_000)
        expect(self.page.locator("#lv-clock")).to_have_text("00:01")
        self.assertEqual(self.page.evaluate("probe.calls"), 0)
        self.page.evaluate("probe.wait=true")
        self.page.clock.fast_forward(1_000)
        expect(self.page.locator("html")).to_have_attribute("data-waiting", "true")
        expect(notes).to_be_visible()
        self.page.clock.fast_forward(40_000)
        self.assertEqual(len(self.token_requests), 1)  # No exchange token ages during the mic prompt.
        self.page.evaluate("probe.release()")
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.page.clock.fast_forward(7_000)  # Device setup is outside the interaction clock.
        expect(self.page.locator("#lv-time")).to_be_hidden()
        self.page.evaluate("probe.sockets[0].receive({setupComplete:{}})")
        expect(self.page.locator("#lv-clock")).to_have_text("03:30")
        expect(notes).to_be_visible()
        expect(notes).to_have_value(scratch)
        self.assertNotIn("Premier repère", self.page.evaluate("JSON.stringify(probe.sent)"))
        self.page.clock.fast_forward(209_000)
        expect(self.page.locator("#lv-clock")).to_have_text("00:01")
        self.page.evaluate("""() => {
          const send = serverContent => probe.sockets[0].receive({serverContent});
          send({inputTranscription:{text:"Combien coûte "}});
          send({inputTranscription:{text:"l’atelier ?",finished:true}, outputTranscription:{text:"Vingt "}});
          send({outputTranscription:{text:"dollars.",finished:true},turnComplete:true});
          send({inputTranscription:{text:"Est-ce que je peux payer par carte ?"}, modelTurn:{
            parts:[{inlineData:{mimeType:'audio/pcm',data:btoa('\\0'.repeat(144000))}}]}});
        }""")
        self.page.clock.fast_forward(1_000)
        expect(self.page.locator("#lv-done")).to_be_visible()
        self.assertEqual(self.page.evaluate("[probe.played.at(-1).wasStopped,probe.track.readyState]"), [True, "ended"])
        expect(self.page.locator("#lv-title")).to_have_text("Simulation")
        expect(self.page.locator("#lv-kicker")).to_have_text("Votre bilan")
        self.page.locator("#lv-transcript summary").click()
        turns = self.page.locator("#lv-turns li")
        expect(turns.locator("p")).to_have_text([
            "Combien coûte l’atelier ?", "Vingt dollars.", "Est-ce que je peux payer par carte ?",
        ])
        expect(turns.locator("textarea, input, [contenteditable]")).to_have_count(0)
        expect(turns.locator(".lv-num")).to_have_text(["Votre prise de parole 1.", "Votre prise de parole 2."])
        expect(self.page.locator("#lv-count")).to_have_text("(2 prises de parole · 3 min 30 s)")
        expect(self.page.locator("#lv-fig-turns")).to_have_text("2")
        self.assertEqual(len(self.token_requests), 2)
        self.page.evaluate("window.dispatchEvent(new Event('pagehide'))")
        expect(turns).to_have_count(0)
        expect(self.page.locator("#lv-fig-turns")).to_have_text("—")

    def test_native_voice_late_permission_and_quota_do_not_reconnect(self):
        self.open_live_pilot()
        self.start_preparation()
        self.page.evaluate("probe.wait=true")
        self.page.locator("#lv-skip").click()
        expect(self.page.locator("html")).to_have_attribute("data-waiting", "true")
        self.page.locator("#lv-end").click()
        self.page.evaluate("probe.release()")
        self.assertEqual(self.page.evaluate("probe.track.readyState"), "ended")
        self.assertEqual(len(self.token_requests), 1)
        self.page.locator("#lv-retry").click()
        self.start_preparation()
        self.page.evaluate("probe.wait=false; probe.deny=true")
        self.page.locator("#lv-skip").click()
        expect(self.page.locator("#lv-status")).to_contain_text("Micro refusé")
        expect(self.page.locator("#lv-title")).to_have_text("L’échange n’a pas commencé")
        expect(self.page.locator("#lv-empty")).to_be_hidden()
        self.assertEqual(len(self.token_requests), 2)
        self.page.locator("#lv-retry").click()
        self.start_preparation()
        self.page.evaluate("probe.deny=false")
        self.mint_status = 429
        self.page.locator("#lv-skip").click()
        expect(self.page.locator("#lv-status")).to_contain_text("Limite")
        self.assertEqual(self.page.evaluate("[probe.calls,probe.track.readyState,probe.sockets.length]"), [3, "ended", 0])
        self.assertEqual(len(self.token_requests), 4)

    def test_native_voice_partial_disconnect_and_silent_attempt(self):
        self.open_live_pilot()
        for with_words in (True, False):
            self.start_preparation()
            self.page.locator("#lv-skip").click()
            expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
            self.page.evaluate("""withWords => {
              const socket = probe.sockets.at(-1);
              socket.receive({setupComplete:{}});
              if (withWords) socket.receive({serverContent:{inputTranscription:{text:"Quand commence"}}});
              socket.onclose(); delete document.documentElement.dataset.handshake;
            }""", with_words)
            expect(self.page.locator("#lv-status")).to_contain_text("interrompue")
            if with_words:
                self.page.locator("#lv-transcript summary").click()
                expect(self.page.locator("#lv-turns li p")).to_have_text("Quand commence")
            else:
                expect(self.page.locator("#lv-empty")).to_be_visible()
                expect(self.page.locator("#lv-report")).to_be_hidden()
            self.page.locator("#lv-retry").click()

    def test_native_voice_marks_only_changed_learner_words_in_readonly_transcript(self):
        self.open_live_pilot()
        report = {"score": 10, "scoreStatus": "scored", "nclc": "7", "cefr": "B2", "reason": "", "criteria": [],
                  "next": "", "evidence": [], "proposal": [], "annotations": [
                      {"turnIndex": 1, "start": 0, "end": 5, "before": "Je va", "after": "Je vais"},
                      {"turnIndex": 2, "start": 3, "end": 16, "before": "je m’inscrire", "after": "Je m’inscris",
                       "why": "Après « si », le présent de l’indicatif."}]}
        self.page.route("**" + reverse("study:eo_tache_two_live_evaluation"), lambda route: route.fulfill(json=report))
        self.start_preparation()
        self.page.locator("#lv-skip").click()
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.page.evaluate("""() => {
          const ws = probe.sockets[0];
          ws.receive({setupComplete:{}});
          ws.receive({serverContent:{
            inputTranscription:{text:"Pourriez-vous m’indiquer le tarif ?"},
            outputTranscription:{text:"Je va vérifier le prix."}, turnComplete:true
          }});
          ws.receive({serverContent:{inputTranscription:{text:"Si je m’inscrire ce soir, est-ce trop tard ?"}}});
        }""")
        self.page.locator("#lv-end").click()
        expect(self.page.locator("#lv-count")).to_contain_text("1 à vérifier")
        transcript = self.page.locator("#lv-transcript")
        if not transcript.evaluate("el => el.open"):
            transcript.locator("summary").click()
        turns = self.page.locator("#lv-turns")
        expect(turns.locator(".lv-turn__said del")).to_have_text(["m’inscrire"])
        expect(turns.locator(".lv-turn__said ins")).to_have_text(["m’inscris"])
        mark, reason = turns.locator("button.lv-mark"), turns.locator("[data-marked] .lv-turn__why")
        expect(reason).to_be_hidden()
        mark.click()
        expect(mark).to_have_attribute("aria-expanded", "true")
        expect(reason).to_have_text("Après « si », le présent de l’indicatif.")
        mark.click()
        expect(reason).to_be_hidden()
        expect(turns.locator('[data-speaker="model"] del')).to_have_count(0)
        expect(turns.locator("textarea, input, [contenteditable]")).to_have_count(0)
        replies = self.page.locator("#lv-replies")
        expect(replies).to_have_accessible_name("Afficher les réponses de l’interlocuteur")
        replies.click()
        expect(turns.locator('[data-speaker="model"]')).to_be_visible()
        expect(replies).to_have_accessible_name("Masquer les réponses de l’interlocuteur")
        expect(replies.locator('[data-icon="eye-off"]')).to_be_visible()
        self.assertEqual(len(self.token_requests), 2)

    def test_native_voice_failed_review_leaves_transcript_unmarked_and_can_retry(self):
        self.open_live_pilot()
        review_calls = []

        def unavailable(route):
            review_calls.append(route.request.post_data_json)
            route.fulfill(status=504, content_type="text/html", body="<h1>Gateway Timeout</h1>")

        self.page.route("**" + reverse("study:eo_tache_two_live_evaluation"), unavailable)
        self.start_preparation()
        self.page.locator("#lv-skip").click()
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.page.evaluate("""() => {
          const ws = probe.sockets[0];
          ws.receive({setupComplete:{}});
          ws.receive({serverContent:{inputTranscription:{
            text:"J’ai j’ai une question. J’ai donc voudrais réserver."},turnComplete:true}});
        }""")
        self.page.locator("#lv-end").click()
        transcript = self.page.locator("#lv-transcript")
        if not transcript.evaluate("el => el.open"):
            transcript.locator("summary").click()
        line = self.page.locator('#lv-turns [data-speaker="user"]')
        expect(line).to_be_visible()
        status = self.page.locator("#lv-assessment-status")
        spinner = self.page.locator(".lv-assessment__spinner")
        expect(status).to_contain_text("pas arrivé à temps")
        expect(status).not_to_have_class(re.compile("sr-only"))
        expect(spinner).to_be_hidden()
        expect(line.locator("del, ins")).to_have_count(0)
        expect(line.locator("p")).to_have_text("J’ai j’ai une question. J’ai donc voudrais réserver.")
        self.assertEqual(len(review_calls), 1)
        self.assertEqual(review_calls[0]["rows"], [
            {"speaker": "user", "text": "J’ai j’ai une question. J’ai donc voudrais réserver."},
        ])
        self.page.evaluate("""() => { window.fetch = () =>
          new Promise(resolve => probe.releaseReview = report => resolve(Response.json(report))); }""")
        self.choose_oral_grader("Groq")
        expect(self.page.locator('#lv-assess [data-icon="sparkles"]')).to_be_attached()
        expect(spinner).to_be_visible()
        expect(status).to_contain_text("Préparation")
        expect(status).to_have_class(re.compile("sr-only"))
        self.page.emulate_media(reduced_motion="reduce")
        expect(spinner).to_have_css("animation-name", "none")
        self.page.locator("#lv-retry").click()
        self.page.evaluate("""() => probe.releaseReview({score:20, nclc:'10+', cefr:'C2',
          criteria:[], evidence:[], annotations:[]})""")
        expect(self.page.locator("#lv-level")).to_have_text("Non évalué")
        expect(self.page.locator("#lv-assessment-result")).to_be_hidden()
        expect(line).to_have_count(0)

    def test_native_voice_disconnect_and_navigation_discard_pending_audio(self):
        self.open_live_pilot()
        for action in ("probe.sockets.at(-1).onclose()", "window.dispatchEvent(new Event('pagehide'))"):
            self.start_preparation()
            self.page.locator("#lv-skip").click()
            expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
            # The setup ACK may already be queued for delivery when the call closes.
            self.page.evaluate("""() => {
              window.oldMessage = probe.sockets.at(-1).onmessage;
              delete document.documentElement.dataset.handshake;
            }""")
            self.page.evaluate(action)
            self.page.evaluate("oldMessage({data:JSON.stringify({setupComplete:{}})})")
            self.assertEqual(self.page.evaluate("[probe.track.readyState,probe.sockets.at(-1).readyState]"),
                             ["ended", 3])
            self.assertFalse(self.page.evaluate("probe.sent.some(m => m.realtimeInput)"))
            if self.page.locator("#lv-retry").is_visible():
                self.page.locator("#lv-retry").click()
            expect(self.start).to_be_enabled()
        self.assertEqual(len(self.token_requests), 4)

    def test_native_voice_cancel_shared_pin_leaves_microphone_closed(self):
        self.open_live_pilot()
        self.start.click()
        buttons = self.pin_dialog.get_by_role("button")
        expect(buttons).to_have_count(2)
        for width in (320, 1183):
            self.page.set_viewport_size({"width": width, "height": 844})
            for button in buttons.all():
                width_px, height_px, radius = button.evaluate(
                    "el => [el.offsetWidth, el.offsetHeight, parseFloat(getComputedStyle(el).borderRadius)]"
                )
                self.assertEqual(width_px, height_px)
                self.assertGreaterEqual(width_px, 44)
                self.assertGreaterEqual(radius, width_px / 2)
            self.assert_no_horizontal_overflow()
        self.pin_dialog.get_by_label("Code", exact=True).fill("unfinished")
        self.pin_dialog.get_by_role("button", name="Annuler").click()
        expect(self.page.locator("#lv-status")).to_contain_text("annulée")
        expect(self.pin_dialog.get_by_label("Code", exact=True)).to_have_value("")
        expect(self.pin_dialog.get_by_role("heading", include_hidden=True)).to_have_text("Nouvel audio ElevenLabs")
        self.assertEqual(self.page.evaluate("[probe.calls,probe.readers.length,probe.sockets.length]"), [0, 0, 0])
        self.assertEqual(self.token_requests, [])

    def test_native_voice_pin_retry_survives_a_slow_entry_and_tab_switch(self):
        self.open_live_pilot()
        self.page.clock.install()
        self.start.click()
        self.submit_live_pin("incorrect")
        expect(self.pin_dialog.get_by_role("alert")).to_have_text("Code incorrect.")
        self.page.clock.fast_forward(31_000)
        self.page.evaluate("""() => {
          Object.defineProperty(document, 'hidden', {configurable:true, value:true});
          document.dispatchEvent(new Event('visibilitychange'));
          delete document.hidden;
        }""")
        expect(self.pin_dialog).to_be_visible()
        self.submit_live_pin()
        self.finish_prompt()
        self.assertEqual(self.page.evaluate("[probe.calls,probe.readers.length]"), [0, 1])

    def test_native_voice_prep_waits_for_last_audible_chunk_after_turn_complete(self):
        self.open_live_pilot()
        self.page.clock.install()
        self.start.click()
        self.submit_live_pin()
        expect(self.page.locator("html")).to_have_attribute("data-reader", "true")
        self.page.evaluate("""async () => {
          const ws = probe.readers[0];
          ws.receive({setupComplete:{}});
          ws.receive({setupComplete:{}});
          window.readChunk = {parts:[{inlineData:{
            mimeType:'audio/pcm;rate=24000',data:btoa('\\x01\\x00'.repeat(2400))
          }}]};
          ws.receive({serverContent:{modelTurn:readChunk}});
          await new Promise(resolve => probe.played[0].addEventListener('ended', resolve, {once:true}));
        }""")
        expect(self.page.locator("#lv-time")).to_be_hidden()  # A gap between chunks isn't the end of the reading.
        self.page.evaluate("""async () => {
          await probe.audio.suspend();
          probe.readers[0].receive({serverContent:{modelTurn:readChunk,turnComplete:true}});
        }""")
        self.page.clock.fast_forward(10_000)  # Wall time passes; Web Audio hasn't played its final buffer.
        expect(self.page.locator("#live-studio")).to_have_attribute("data-state", "reading")
        expect(self.page.locator("#lv-time")).to_be_hidden()
        self.assertEqual(self.page.evaluate("probe.readingMessages.filter(m => m.realtimeInput)"),
                         [{"realtimeInput": {"text": "Lisez la consigne."}}])
        self.page.get_by_role("button", name="Réactiver le son").click()
        expect(self.page.locator("#lv-prep")).to_be_visible()
        expect(self.page.locator("#lv-clock")).to_have_text("02:00")
        self.assertEqual(self.page.evaluate("probe.calls"), 0)

    def test_native_voice_incomplete_or_silent_reading_does_not_start_preparation(self):
        self.open_live_pilot()
        for failure in ("socket.onclose()", "socket.receive({serverContent:{modelTurn:{parts:[{inlineData:"
                        "{mimeType:'audio/pcm',data:'AAAAAA=='}}]},turnComplete:true}})"):
            self.start.click()
            self.submit_live_pin()
            expect(self.page.locator("html")).to_have_attribute("data-reader", "true")
            self.page.evaluate("""() => {
              const socket = probe.readers.at(-1);
              delete document.documentElement.dataset.reader;
              window.oldReader = socket.onmessage;
              socket.receive({setupComplete:{}});
              %s;
            }""" % failure)
            expect(self.page.locator("#lv-status")).to_contain_text("La préparation n’a pas démarré")
            self.page.locator("#lv-retry").click()
            self.page.evaluate("oldReader({data:JSON.stringify({serverContent:{turnComplete:true}})})")
            expect(self.start).to_be_enabled()
            expect(self.page.locator("#lv-time")).to_be_hidden()
        self.assertEqual(self.page.evaluate("[probe.calls,probe.sockets.length]"), [0, 0])

    def test_linked_voice_consent_enqueues_mai_for_the_saved_transcript(self):
        self.enterContext(patch("study.accounts.github_copilot.active_link_id", return_value=42))
        self.enterContext(patch("study.simulation.oral_jobs.wake"))
        self.open_live_pilot()
        endpoint = reverse("study:eo_tache_two_live_evaluation")
        self.page.unroute("**" + endpoint)
        self.start.click()
        expect(self.pin_dialog).to_contain_text("Transcription envoyée à MAI via GitHub Copilot")
        self.submit_live_pin()
        self.finish_prompt()
        self.page.locator("#lv-skip").click()
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        words = "Combien coûte la visite du quartier ?"
        self.page.evaluate("""words => {
          const ws = probe.sockets[0];
          ws.receive({setupComplete:{}});
          ws.receive({serverContent:{inputTranscription:{text:words},turnComplete:true}});
        }""", words)
        with self.page.expect_response(
            lambda response: urlsplit(response.url).path == endpoint and response.request.method == "POST",
        ) as review:
            self.page.locator("#lv-end").click()
        self.assertEqual(self.token_requests[0]["reviewProvider"], "copilot-mai")
        self.assertEqual(self.token_requests[0]["reviewLink"], "42")
        self.assertEqual(review.value.status, 202)
        sent = review.value.request.post_data_json
        self.assertEqual(sent["reviewGrant"], self.token_replies["exchange"]["reviewGrant"])
        self.assertNotIn("pin", sent)
        self.assertEqual(sent["rows"], [{"speaker": "user", "text": words}])
        job = OralEvaluationJob.objects.get(simulation_id=sent["simulation"])
        self.assertEqual((job.provider, job.copilot_link_id), ("copilot-mai", 42))
        self.assertEqual(job.simulation.rows[0]["text"], words)

    def test_native_voice_review_starts_itself_and_retries_on_the_captured_transcript(self):
        self.open_live_pilot()
        calls, polls = [], []
        original = "📷 Et si je veux prend deux appareils ?"
        report = {"score": 12, "scoreStatus": "scored", "nclc": "8", "cefr": "B2", "reason": "Vous comparez les options.",
                  "criteria": [{"label": label, "score": score, "why": why} for label, score, why in (
                      ("Accomplissement de la tâche", 4, "La demande de tarif est précise."),
                      ("Cohérence et fluidité", 3, "Vous enchaînez les questions."),
                      ("Précision lexicale", 3, "Le terme « prêt » convient."),
                      ("Correction grammaticale", 2, "Attention à l’infinitif après vouloir."))],
                  "next": "Précisez la durée du prêt.", "evidence": [
                      {"turnIndex": 0, "quote": "Combien coûte le prêt ?", "why": "Vous demandez directement le prix du prêt."},
                      {"turnIndex": 2, "quote": original, "why": "Vous relancez sur le cas de deux appareils."}],
                  "annotations": [{"turnIndex": 2, "start": 12, "end": 22, "before": "veux prend",
                                   "after": "veux prendre", "why": "Après vouloir, employez l’infinitif."}],
                  "proposal": ["Bonjour, combien coûte le prêt d’un appareil photo ?",
                               "Et si je veux prendre deux appareils, le tarif change-t-il ?"]}

        def fake_review(route):
            if route.request.method == "GET":
                polls.append(parse_qs(urlsplit(route.request.url).query))
                if len(calls) == 1:
                    route.fulfill(status=404, json={"error": "Aucun bilan."})
                elif len(calls) == 2:
                    route.fulfill(status=502, json={"status": "unavailable", "error": "Échec du bilan."})
                else:
                    route.fulfill(json=report)
                return
            body = route.request.post_data_json
            calls.append(body)
            if body.get("reviewGrant") != self.token_replies["exchange"]["reviewGrant"] or "pin" in body:
                route.fulfill(status=403, json={"error": "missing grant"})
            elif len(calls) == 1:
                route.fulfill(status=429, json={"error": "Quota atteint."})
            else:
                route.fulfill(status=202, json={"status": "processing"})

        endpoint = reverse("study:eo_tache_two_live_evaluation")
        self.page.route(re.compile(re.escape(endpoint) + r"(?:\?[^#]*)?$"), fake_review)
        self.start_preparation()
        self.page.locator("#lv-skip").click()
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.page.evaluate("""words => {
          const ws = probe.sockets[0];
          ws.receive({setupComplete:{}});
          ws.receive({serverContent:{inputTranscription:{text:'Combien coûte le prêt ?'},
            outputTranscription:{text:'Cinq dollars.'},turnComplete:true}});
          ws.receive({serverContent:{inputTranscription:{text:words},turnComplete:true}});
        }""", original)
        self.page.locator("#lv-end").click()
        button, level = (self.page.locator("#lv-" + key) for key in ("assess", "level"))
        status = self.page.locator("#lv-assessment-status")
        expect(status).to_contain_text("Quota atteint")
        expect(level).to_have_text("Non évalué")
        expect(button).to_be_enabled()
        self.page.set_viewport_size({"width": 320, "height": 700})
        controls = self.page.locator("#lv-assessment-controls")
        expect(button).to_have_accessible_name("Choisir le modèle d’évaluation")
        expect(button).to_have_text("")
        expect(button.locator('[data-icon="sparkles"]')).to_be_visible()
        expect(controls.locator("details, input")).to_have_count(0)
        self.assert_no_horizontal_overflow()
        expect(self.page.locator("#lv-turns")).to_contain_text("Combien coûte le prêt")
        self.page.locator("#lv-assessment summary").click()
        self.choose_oral_grader("Groq")  # Folded while Groq works, the bilan reopens on the answer.
        expect(status).to_contain_text("Échec du bilan.")
        expect(status).to_be_visible()
        expect(level).to_have_text("Non évalué")
        self.choose_oral_grader("Groq")
        expect(level).to_have_text("12/20 · NCLC 8 · B2")
        expect(self.page.locator("#lv-assessment-evidence")).to_contain_text("Vous relancez sur le cas de deux appareils.")
        table = self.page.locator("#lv-assessment-criteria")
        expect(table.get_by_role("rowheader")).to_have_text([item["label"] for item in report["criteria"]])
        expect(table.locator("tr > td:first-of-type")).to_have_text(["4/5", "3/5", "3/5", "2/5"])
        self.assert_no_horizontal_overflow()
        transcript = self.page.locator("#lv-transcript")
        if not transcript.evaluate("el => el.open"):
            transcript.locator("summary").click()
        target = self.page.locator('#lv-turns [data-speaker="user"]').last
        expect(target.locator(".lv-turn__said del")).to_have_text("prend")
        expect(target.locator(".lv-turn__said ins")).to_have_text("prendre")
        expect(target.locator("textarea, input, [contenteditable]")).to_have_count(0)
        proposal = self.page.locator("#lv-proposal")
        expect(proposal).to_be_visible()
        expect(proposal.locator("li")).to_have_text(report["proposal"])
        self.page.evaluate("""() => Object.defineProperty(navigator, "clipboard", {configurable: true,
          value: {writeText: text => { window.copiedProposal = text; return Promise.resolve(); }}})""")
        proposal.get_by_role("button", name="Copier").click()
        expect(proposal.locator("#lv-proposal-copy-label")).to_have_text("Copié !")
        self.assertEqual(self.page.evaluate("window.copiedProposal"), "\n".join(report["proposal"]))
        self.assert_no_horizontal_overflow()
        for section, body in ((self.page.locator("#lv-assessment"), "#lv-assessment-result"), (proposal, "#lv-proposal-lines")):
            section.locator("summary").click()
            expect(self.page.locator(body)).to_be_hidden()
        expect(level).to_have_text("12/20 · NCLC 8 · B2")
        expect(level).to_be_visible()
        self.assert_no_horizontal_overflow()
        self.assertEqual(len(calls), 3)
        self.assertEqual(polls, [{"provider": ["groq"], "simulation": [calls[0]["simulation"]]}] * 4)
        self.assertTrue(calls[0]["rows"] == calls[1]["rows"] == calls[2]["rows"])
        self.assertEqual(calls[2]["rows"][-1], {"speaker": "user", "text": original})
        self.assertEqual(self.page.evaluate("[probe.calls,probe.track.readyState]"), [1, "ended"])

    @override_settings(GROQ_API_KEY="fixture-groq", AI_PIN=PILOT_PIN)
    def test_oral_bilan_reopens_a_queued_review_without_resending_the_transcript(self):
        factories.make_task(self.part, "tache-2")
        saved = LiveSimulation.objects.create(
            user=self.user, rows=[{"speaker": "user", "text": "Combien coûte le prêt ?"}],
            snapshot={"prompt": "Demandez des renseignements sur les ateliers."},
        )
        OralEvaluationJob.objects.create(simulation=saved, provider="groq")
        report = {"score": 12, "scoreStatus": "scored", "nclc": "8", "cefr": "B2", "reason": "Bilan terminé.",
                  "criteria": [], "evidence": [], "annotations": [], "next": "", "proposal": []}
        requests = []

        def fake_status(route):
            requests.append((route.request.method, parse_qs(urlsplit(route.request.url).query)))
            if len(requests) == 1:
                route.fulfill(status=202, json={"status": "processing"})
            else:
                route.fulfill(json=report)

        endpoint = reverse("study:eo_tache_two_live_evaluation")
        self.page.route(re.compile(re.escape(endpoint) + r"(?:\?[^#]*)?$"), fake_status)
        self.page.goto(self.live_server_url + reverse("study:eo_tache_two_live", query={"simulation": saved.pk}))
        expect(self.page.locator("#lv-level")).to_have_text("12/20 · NCLC 8 · B2")
        self.assertEqual(requests, [("GET", {"provider": ["groq"], "simulation": [str(saved.pk)]})] * 2)
        expect(self.page.locator("[data-audio-pin-dialog]")).to_be_hidden()

    @override_settings(GROQ_API_KEY="fixture-groq", GEMINI_API_KEY="", CLOUDFLARE_WORKERS_API_KEY="", AI_PIN=PILOT_PIN)
    def test_oral_bilan_refresh_requires_confirmation_and_preserves_feedback_until_ready(self):
        factories.make_task(self.part, "tache-2")
        rows = [{"speaker": "user", "text": "Combien coûte le prêt ?"}]
        previous = {"score": 10, "scoreStatus": "scored", "nclc": "7", "cefr": "B2", "reason": "Bilan d’origine.",
                    "criteria": [], "evidence": [], "annotations": [], "next": "", "proposal": []}
        saved = LiveSimulation.objects.create(
            user=self.user, rows=rows, report=previous,
            snapshot={"prompt": "Demandez des renseignements sur les ateliers."},
        )
        endpoint = reverse("study:eo_tache_two_live_evaluation")
        url = reverse("study:eo_tache_two_live", query={"simulation": saved.pk})
        requests = []
        self.page.on("request", lambda request: requests.append(request.method) if urlsplit(request.url).path == endpoint else None)
        self.page.clock.install()
        self.page.clock.pause_at(self.page.evaluate("Date.now() + 10000"))
        self.page.goto(self.live_server_url + url)
        refresh = self.page.locator(".lv-title-row").get_by_role("button", name="Actualiser le bilan")
        expect(refresh.locator('[data-icon="reset"]')).to_be_visible()
        expect(self.page.locator("#lv-assess")).to_be_hidden()
        pin = self.page.locator("[data-audio-pin-dialog]")
        level = self.page.locator("#lv-level")
        status = self.page.locator("#lv-assessment-status")
        current = {**previous, "score": 12, "nclc": "8", "graderVersion": 0}

        with patch.object(oral_jobs, "wake"):
            for index, outcome in enumerate((({"error": "Bilan hors délai."}, 504), (current, 200))):
                before_consent = list(requests)
                refresh.click()
                expect(pin.get_by_role("heading")).to_have_text("Actualiser le bilan")
                expect(pin).to_contain_text("Transcription envoyée à Groq")
                self.assertEqual(requests, before_consent)
                pin.get_by_label("Code", exact=True).fill(PILOT_PIN)
                with self.page.expect_response(lambda response: urlsplit(response.url).path == endpoint) as queued:
                    pin.get_by_role("button", name="Actualiser le bilan").click()
                self.assertEqual(queued.value.status, 202)
                self.assertEqual(queued.value.request.post_data_json, {
                    "consent": True, "simulation": str(saved.pk), "rows": rows, "refresh": True, "pin": PILOT_PIN,
                })
                if index == 0:
                    with self.page.expect_response(lambda response: urlsplit(response.url).path == endpoint) as resumed:
                        self.page.reload()
                    self.assertEqual((resumed.value.request.method, resumed.value.status), ("GET", 202))
                expect(refresh).to_be_disabled()
                expect(status).to_have_text("Actualisation du bilan…")
                expect(level).to_have_text("10/20 · NCLC 7 · B2")
                job, _ = oral_jobs._claim()
                oral_jobs._finish(job, *outcome)
                with self.page.expect_response(lambda response: urlsplit(response.url).path == endpoint):
                    self.page.clock.run_for(1000)
                if index == 0:
                    expect(status).to_have_text("Bilan hors délai.")
                    expect(refresh).to_be_enabled()
                    expect(level).to_have_text("10/20 · NCLC 7 · B2")

        expect(level).to_have_text("12/20 · NCLC 8 · B2")
        expect(status).to_have_text("Bilan actualisé.")
        expect(refresh).to_be_hidden()
        expect(self.page.locator("#lv-turns")).to_contain_text(rows[0]["text"])
        self.assertEqual(requests, ["POST", "GET", "GET", "POST", "GET"])

    def test_native_voice_saved_exchange_reopens_on_its_stored_report(self):
        report = {"score": 12, "scoreStatus": "scored", "nclc": "8", "cefr": "B2", "reason": "Vous comparez les options.",
                  "criteria": [{"label": "Précision lexicale", "score": 3, "why": "Vous précisez l’objet demandé."}],
                  "next": "Précisez la durée du prêt.", "evidence": [],
                  "annotations": [{"turnIndex": 0, "start": 8, "end": 13, "before": "prend",
                                   "after": "prendre", "why": "Après vouloir, employez l’infinitif."}],
                  "proposal": ["Bonjour, je voudrais prendre un appareil photo."]}
        calls = []

        def fake_review(route):
            body = route.request.post_data_json
            calls.append(body)
            if len(calls) == 1:
                route.fulfill(status=429, json={"error": "Quota atteint."})
            elif body.get("pin") != PILOT_PIN:
                route.fulfill(status=403, json={"error": "pin_required", "message": "Code PIN requis."})
            else:
                route.fulfill(json=report)

        self.open_live_pilot()
        self.page.route("**" + reverse("study:eo_tache_two_live_evaluation"), fake_review)
        self.start_preparation()
        self.page.locator("#lv-skip").click()
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.page.evaluate("""() => {
          const ws = probe.sockets[0];
          ws.receive({setupComplete:{}});
          ws.receive({serverContent:{inputTranscription:{text:'Je veux prend un appareil.'},
            outputTranscription:{text:'Lequel ?'},turnComplete:true}});
        }""")
        self.page.locator("#lv-end").click()
        button, level, status = (self.page.locator("#lv-" + key) for key in ("assess", "level", "assessment-status"))
        expect(status).to_have_text("Quota atteint.")
        simulation = LiveSimulation.objects.get(user=self.user)
        self.assertEqual(simulation.rows, [{"speaker": "user", "text": "Je veux prend un appareil."},
                                           {"speaker": "model", "text": "Lequel ?"}])
        self.assertEqual(calls[0]["simulation"], str(simulation.pk))
        self.assertIn(f"simulation={simulation.pk}", self.page.url)

        self.page.reload()
        expect(self.page.locator("#lv-turns")).to_contain_text("Je veux prend un appareil.")
        expect(status).to_have_text("Pas encore de bilan : touchez ✨ pour le demander.")
        expect(level).to_have_text("Non évalué")
        self.choose_oral_grader("Groq")
        expect(self.pin_dialog.get_by_role("heading")).to_have_text("Demander le bilan")
        self.pin_dialog.get_by_label("Code", exact=True).fill(PILOT_PIN)
        self.pin_dialog.get_by_role("button", name="Demander le bilan").click()
        expect(level).to_have_text("12/20 · NCLC 8 · B2")
        self.assertEqual((calls[-1]["simulation"], "reviewGrant" in calls[-1]), (str(simulation.pk), False))

        LiveSimulation.objects.filter(pk=simulation.pk).update(report=report)
        reviews = len(calls)
        with override_settings(GEMINI_API_KEY="", GROQ_API_KEY="", AI_PIN=""):
            self.page.goto(self.live_server_url + reverse("study:eo_tache_two_live"))
            saved = self.page.locator(".lv-saved li")
            expect(saved).to_have_count(1)
            expect(saved).to_contain_text("12/20 · NCLC 8")
            saved.get_by_role("link").click()
            expect(self.page.get_by_role("heading", level=1)).to_have_text("Simulation")
            expect(self.page.locator("#lv-kicker")).to_have_text("Votre bilan")
            expect(self.page.locator("#lv-subject #lv-status")).to_have_text("Séance enregistrée.")
            expect(self.start).to_be_hidden()
            expect(level).to_have_text("12/20 · NCLC 8 · B2")
            expect(self.page.locator("#lv-assessment-legacy")).to_be_visible()
            expect(self.page.locator("#lv-assessment-criteria a")).to_have_count(0)
            expect(self.page.locator("#lv-proposal li")).to_have_text(report["proposal"])
            transcript = self.page.locator("#lv-transcript")
            if not transcript.evaluate("el => el.open"):
                transcript.locator("summary").click()
            expect(self.page.locator('#lv-turns [data-speaker="user"] .lv-turn__said ins')).to_have_text("prendre")
            self.assertEqual(len(calls), reviews)
            self.assert_no_horizontal_overflow()

        partial = {**report, "score": None, "scoreStatus": "incomplete", "nclc": None, "cefr": None,
                   "evidenceVersion": 1, "criteria": [{"label": "Précision lexicale", "score": None,
                                                       "why": "La citation proposée ne correspond pas à vos paroles."}]}
        LiveSimulation.objects.filter(pk=simulation.pk).update(report=partial)
        self.page.reload()
        expect(level).to_have_text("Grille partielle · pas de total")
        row = self.page.get_by_role("row").filter(has=self.page.get_by_role("rowheader", name="Précision lexicale"))
        expect(row.get_by_role("cell", name="Non évalué", exact=True)).to_be_visible()
        self.assertEqual(len(calls), reviews)  # Opening old or partial feedback never resubmits it.
        self.choose_oral_grader("Groq")
        self.pin_dialog.get_by_label("Code", exact=True).fill(PILOT_PIN)
        self.pin_dialog.get_by_role("button", name="Demander le bilan").click()
        expect(level).to_have_text("12/20 · NCLC 8 · B2")
        expect(button).to_be_visible()
        self.assertEqual(calls[-1]["rows"], simulation.rows)
        self.assertEqual(self.page.evaluate("probe.calls"), 0)

        self.page.goto(self.live_server_url + reverse("study:eo_tache_two_live"))
        delete = saved.get_by_role("button", name="Supprimer la séance du")
        expect(delete.locator('[data-icon="trash"]')).to_be_visible()
        delete.click()
        dialog = self.page.locator("[data-confirm-dialog]")
        dialog.get_by_role("button", name="Annuler", exact=True).click()
        expect(saved).to_have_count(1)
        delete.click()
        with self.page.expect_navigation():
            dialog.locator("[data-confirm-accept]").click()
        expect(saved).to_have_count(0)
        self.assertFalse(LiveSimulation.objects.filter(user=self.user).exists())
