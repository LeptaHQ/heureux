import json
import re

from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect

from study.models import LiveSimulation

from . import factories


PILOT_PIN = "test-audio-pin"


class LiveConversationBrowserMixin:
    def open_live_pilot(self, *, subject_args=()):
        """Real Web Audio and worklet; synthetic input and a local stand-in for Gemini."""
        factories.make_task(self.part, "tache-2")
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
          tone.connect(out); tone.start();
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
        self.mint_status = 200

        def fake_token(route):
            body = route.request.post_data_json
            self.token_requests.append(body)
            if body.get("purpose") == "exchange" and body == {
                "consent": True, "purpose": "exchange", "exchangeGrant": "fixture-exchange",
            }:
                token, grant = "exchange", {"reviewGrant": "fixture-review"}
            elif body.get("purpose") == "attempt" and body.get("pin") == PILOT_PIN:
                token, grant = "reader", {"exchangeGrant": "fixture-exchange"}
            else:
                code = "pin_invalid" if body.get("pin") else "pin_required"
                route.fulfill(status=403, json={"error": code, "message": "Code PIN incorrect."})
                return
            route.fulfill(status=self.mint_status, json={
                "model": "models/gemini-3.8-live", "token": "auth_tokens/" + token, **grant,
            })

        self.page.route("**" + reverse("study:eo_tache_two_live_token", args=subject_args), fake_token)
        with override_settings(
            GEMINI_LIVE_API_KEY="fixture-not-a-key", GEMINI_LIVE_FREE_TIER_CONFIRMED=True,
            ELEVENLABS_PIN=PILOT_PIN,
        ):
            if subject_args:
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
                self.page.goto(self.live_server_url + reverse("study:eo_tache_two_live"))
        self.start = self.page.locator("#lv-start")
        self.pin_dialog = self.page.locator("[data-audio-pin-dialog]")

    def submit_live_pin(self, pin=PILOT_PIN):
        expect(self.pin_dialog.get_by_role("heading")).to_have_text("Autoriser la conversation Gemini Live")
        self.pin_dialog.get_by_label("Code PIN ElevenLabs").fill(pin)
        self.pin_dialog.get_by_role("button", name="Autoriser cette conversation").click()

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
        expect(self.page.locator("#lv-prep")).to_be_visible()

    def start_preparation(self):
        self.start.click()
        self.submit_live_pin()
        self.finish_prompt()

    def test_native_voice_subject_launch_uses_exact_consigne_and_retains_return_link(self):
        self._import_eo_tache_two_content()
        args = ("octobre", 5, 21)
        self.open_live_pilot(subject_args=args)
        expect(self.pin_dialog).to_be_hidden()  # The PIN waits for « Commencer la séance ».
        self.assertEqual(self.token_requests, [])
        self.start.click()
        self.submit_live_pin()
        self.finish_prompt()
        expect(self.page.locator("#lv-prompt")).to_have_text(json.loads(self.selected_consigne))
        self.assertEqual(self.page.evaluate("probe.calls"), 0)
        self.page.locator("#lv-skip").click()
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.page.locator("#lv-end").click()
        self.page.get_by_role("link", name="Revenir à la fiche de ce sujet").click()
        expect(self.page).to_have_url(self.live_server_url + reverse("study:task_subject_detail", args=("eo", "tache-2", *args)))

    def test_native_voice_waits_for_handshake_and_supports_interruption(self):
        self.open_live_pilot()
        expect(self.page.locator("#lv-setup input[type=checkbox], #lv-setup .lv-terms")).to_have_count(0)
        expect(self.start).to_be_enabled()
        self.start.click()
        self.assertEqual(self.page.evaluate("probe.calls"), 0)
        expect(self.pin_dialog).to_contain_text("J’accepte d’envoyer ma voix à Google pendant l’échange, puis sa transcription pour le bilan.")
        self.assertEqual(self.token_requests, [])
        self.submit_live_pin("incorrect")
        expect(self.pin_dialog.get_by_role("alert")).to_have_text("Code PIN incorrect.")
        self.assertEqual(self.page.evaluate("[probe.calls,probe.readers.length,probe.sockets.length]"), [0, 0, 0])
        self.submit_live_pin()
        self.finish_prompt()
        self.assertEqual(self.token_requests[-1], {"consent": True, "purpose": "attempt", "pin": PILOT_PIN})
        self.page.evaluate("document.getElementById('lv-skip').click(); document.getElementById('lv-skip').click()")
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.assertEqual(self.token_requests[-1], {"consent": True, "purpose": "exchange", "exchangeGrant": "fixture-exchange"})
        self.assertEqual(len(self.token_requests), 3)  # Bad PIN, corrected PIN, one exchange.
        self.assertEqual(self.page.evaluate("[probe.calls,probe.sockets.length]"), [1, 1])
        self.assertNotIn(PILOT_PIN, self.page.evaluate("probe.readers[0].url + probe.sockets[0].url + JSON.stringify([probe.readingMessages,probe.sent])"))
        expect(self.pin_dialog.get_by_label("Code PIN ElevenLabs")).to_have_value("")
        self.assertEqual(self.page.evaluate("probe.sent.map(m => Object.keys(m))"), [["setup"]])
        self.assertFalse(self.page.evaluate("probe.track.enabled"))
        self.page.evaluate("probe.sockets[0].receive({setupComplete:{}})")
        self.page.evaluate("probe.sockets[0].receive({setupComplete:{}})")
        self.assertEqual(self.page.evaluate("probe.sent.filter(m => m.realtimeInput?.text?.includes('Bonjour')).length"), 1)
        expect(self.page.locator("html")).to_have_attribute("data-has-audio", "true")
        audio = self.page.evaluate("""() => {
          const a = probe.sent.find(m => m.realtimeInput?.audio && /[^\\x00]/.test(atob(m.realtimeInput.audio.data))).realtimeInput.audio;
          const b = atob(a.data);
          return [a.mimeType,b.length,[...b].some(c => c.charCodeAt(0) !== 0)];
        }""")
        self.assertEqual(audio, ["audio/pcm;rate=16000", 2048, True])
        self.page.evaluate("""probe.sockets[0].receive({serverContent:{
          inputTranscription:{text:'Le samedi ?'}, outputTranscription:{text:'À dix heures.'},
          modelTurn:{parts:[{inlineData:{mimeType:'audio/pcm;rate=24000',data:btoa('\\0'.repeat(96000))}}]}
        }})""")
        self.assertEqual(self.page.evaluate("probe.played.at(-1).buffer.sampleRate"), 24000)
        self.page.locator("#lv-captions summary").click()
        expect(self.page.locator("#lv-ai-words")).to_have_text("À dix heures.")
        self.page.evaluate("""() => {
          const send = serverContent => probe.sockets[0].receive({serverContent});
          send({interrupted:true, inputTranscription:{text:"Et le "}});
          send({turnComplete:true});
          send({inputTranscription:{text:"dimanche ?",finished:true}});
        }""")
        self.assertTrue(self.page.evaluate("probe.played.at(-1).wasStopped && probe.track.enabled"))
        self.page.locator("#lv-mute").click()
        self.assertFalse(self.page.evaluate("probe.track.enabled"))
        self.assertTrue(self.page.evaluate("probe.sent.at(-1).realtimeInput.audioStreamEnd"))
        self.page.locator("#lv-mute").click()
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
        self.page.clock.fast_forward(119_000)
        expect(self.page.locator("#lv-clock")).to_have_text("00:01")
        self.assertEqual(self.page.evaluate("probe.calls"), 0)
        self.page.evaluate("probe.wait=true")
        self.page.clock.fast_forward(1_000)
        expect(self.page.locator("html")).to_have_attribute("data-waiting", "true")
        self.page.clock.fast_forward(40_000)
        self.assertEqual(len(self.token_requests), 1)  # No exchange token ages during the mic prompt.
        self.page.evaluate("probe.release()")
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.page.clock.fast_forward(7_000)  # Device setup is outside the interaction clock.
        expect(self.page.locator("#lv-time")).to_be_hidden()
        self.page.evaluate("probe.sockets[0].receive({setupComplete:{}})")
        expect(self.page.locator("#lv-clock")).to_have_text("03:30")
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
        expect(self.page.locator("#lv-title")).to_have_text("Votre bilan")
        expect(self.page.locator("#lv-observations")).to_be_hidden()  # Plain questions earn no strength label.
        self.page.locator("#lv-transcript summary").click()
        turns = self.page.locator("#lv-turns li")
        expect(turns.locator("p")).to_have_text([
            "Combien coûte l’atelier ?", "Vingt dollars.", "Est-ce que je peux payer par carte ?",
        ])
        expect(turns.locator("textarea, input, [contenteditable]")).to_have_count(0)
        expect(turns.locator(".lv-num")).to_have_text(["Votre prise de parole 1.", "Votre prise de parole 2."])
        expect(turns.locator(".lv-why:visible")).to_have_count(0)
        expect(self.page.locator("#lv-count")).to_have_text("(2 prises de parole · 3 min 30 s · aucune suggestion locale)")
        self.assertEqual(len(self.token_requests), 2)
        self.page.evaluate("window.dispatchEvent(new Event('pagehide'))")
        expect(turns).to_have_count(0)
        expect(self.page.locator("#lv-evidence")).to_be_empty()

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
        expect(self.page.locator("#lv-evidence")).to_contain_text("Demande polie au conditionnel")
        transcript = self.page.locator("#lv-transcript")
        if not transcript.evaluate("el => el.open"):
            transcript.locator("summary").click()
        turns = self.page.locator("#lv-turns")
        expect(turns.locator(".lv-turn__said del")).to_have_text(["m’inscrire"])
        expect(turns.locator(".lv-turn__said ins")).to_have_text(["m’inscris"])
        expect(turns.locator('[data-speaker="model"] del')).to_have_count(0)
        expect(turns.locator("textarea, input, [contenteditable]")).to_have_count(0)
        why = turns.locator(".lv-why").last
        expect(why).to_be_visible()
        expect(why).to_contain_text("m’inscris")
        replies = self.page.locator("#lv-replies")
        expect(replies).to_have_text("Afficher les réponses de l’interlocuteur")
        replies.click()
        expect(turns.locator('[data-speaker="model"]')).to_be_visible()
        expect(replies).to_have_text("Masquer les réponses de l’interlocuteur")
        self.page.locator("#lv-corrections button").first.click()
        expect(turns.locator(".lv-turn__said").last).to_be_focused()
        self.assertEqual(len(self.token_requests), 2)

    def test_native_voice_shows_inline_local_suggestions_when_gemini_review_fails(self):
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
        line = self.page.locator('#lv-turns [data-speaker="user"]')
        expect(line).to_be_visible()
        expect(line.locator(".lv-turn__said del")).to_have_count(2)
        expect(line.locator("ins")).to_have_text("Je voudrais donc")
        expect(line).to_contain_text("doublon de transcription possible")
        status = self.page.locator("#lv-assessment-status")
        spinner = self.page.locator(".lv-assessment__spinner")
        expect(status).to_contain_text("pas arrivé à temps")
        expect(status).not_to_have_class(re.compile("sr-only"))
        expect(spinner).to_be_hidden()
        expect(line.locator("ins")).to_be_visible()
        self.assertEqual(len(review_calls), 1)
        self.assertEqual(review_calls[0]["rows"], [
            {"speaker": "user", "text": "J’ai j’ai une question. J’ai donc voudrais réserver."},
        ])
        self.page.evaluate("""() => { window.fetch = () =>
          new Promise(resolve => probe.releaseReview = report => resolve(Response.json(report))); }""")
        self.page.locator("#lv-assess").click()
        expect(self.page.locator('#lv-assess [data-icon="sparkles"]')).to_be_visible()
        expect(spinner).to_be_visible()
        expect(status).to_contain_text("examine")
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
        self.pin_dialog.get_by_label("Code PIN ElevenLabs").fill("unfinished")
        self.pin_dialog.get_by_role("button", name="Annuler").click()
        expect(self.page.locator("#lv-status")).to_contain_text("annulée")
        expect(self.pin_dialog.get_by_label("Code PIN ElevenLabs")).to_have_value("")
        expect(self.pin_dialog.get_by_role("heading", include_hidden=True)).to_have_text("Nouvel audio ElevenLabs")
        self.assertEqual(self.page.evaluate("[probe.calls,probe.readers.length,probe.sockets.length]"), [0, 0, 0])
        self.assertEqual(self.token_requests, [])

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
        self.page.evaluate("probe.audio.resume()")
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

    def test_native_voice_review_starts_itself_and_retries_on_the_captured_transcript(self):
        self.open_live_pilot()
        calls = []
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
            body = route.request.post_data_json
            calls.append(body)
            if body.get("reviewGrant") != "fixture-review" or "pin" in body:
                route.fulfill(status=403, json={"error": "missing grant"})
            elif len(calls) == 1:
                route.fulfill(status=429, json={"error": "Quota atteint."})
            elif len(calls) == 2:  # A slow report streams keep-alive spaces, then its error.
                route.fulfill(content_type="application/json", body="  " + json.dumps({"error": "Délai.", "status": 504}))
            else:
                route.fulfill(json=report)

        self.page.route("**" + reverse("study:eo_tache_two_live_evaluation"), fake_review)
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
        expect(button).to_have_accessible_name("Évaluer mon niveau avec Gemini")
        expect(button).to_have_text("")
        expect(button.locator('[data-icon="sparkles"]')).to_be_visible()
        expect(controls.locator("details, input")).to_have_count(0)
        self.assert_no_horizontal_overflow()
        expect(self.page.locator("#lv-turns")).to_contain_text("Combien coûte le prêt")
        button.click()
        expect(status).to_contain_text("Délai.")  # A streamed timeout shows how far Gemini got.
        expect(level).to_have_text("Non évalué")
        button.click()
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
        expect(target.locator(".lv-why")).to_contain_text("Après vouloir, employez l’infinitif.")
        proposal = self.page.locator("#lv-proposal")
        expect(proposal).to_be_visible()
        expect(proposal.locator("li")).to_have_text(report["proposal"])
        self.page.evaluate("""() => Object.defineProperty(navigator, "clipboard", {configurable: true,
          value: {writeText: text => { window.copiedProposal = text; return Promise.resolve(); }}})""")
        proposal.get_by_role("button", name="Copier").click()
        expect(proposal.locator("#lv-proposal-copy-label")).to_have_text("Copié !")
        self.assertEqual(self.page.evaluate("window.copiedProposal"), "\n".join(report["proposal"]))
        self.assert_no_horizontal_overflow()
        self.assertEqual(len(calls), 3)
        self.assertTrue(calls[0]["rows"] == calls[1]["rows"] == calls[2]["rows"])
        self.assertEqual(calls[2]["rows"][-1], {"speaker": "user", "text": original})
        self.assertEqual(self.page.evaluate("[probe.calls,probe.track.readyState]"), [1, "ended"])

    def test_native_voice_saved_exchange_reopens_on_its_stored_report(self):
        report = {"score": 12, "scoreStatus": "scored", "nclc": "8", "cefr": "B2", "reason": "Vous comparez les options.",
                  "criteria": [], "next": "Précisez la durée du prêt.", "evidence": [],
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

        # The settings stay on after the page loads so the exchange really reaches the save endpoint.
        with override_settings(GEMINI_LIVE_API_KEY="fixture-not-a-key", GEMINI_LIVE_FREE_TIER_CONFIRMED=True,
                               ELEVENLABS_PIN=PILOT_PIN):
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
            expect(status).to_have_text("Pas encore de bilan pour cet échange : touchez ✨ pour le demander.")
            expect(level).to_have_text("Non évalué")
            button.click()
            expect(self.pin_dialog.get_by_role("heading")).to_have_text("Demander le bilan Gemini")
            self.pin_dialog.get_by_label("Code PIN ElevenLabs").fill(PILOT_PIN)
            self.pin_dialog.get_by_role("button", name="Demander le bilan").click()
            expect(level).to_have_text("12/20 · NCLC 8 · B2")
            self.assertEqual((calls[-1]["simulation"], "reviewGrant" in calls[-1]), (str(simulation.pk), False))

            LiveSimulation.objects.filter(pk=simulation.pk).update(report=report)
            reviews = len(calls)
            self.page.goto(self.live_server_url + reverse("study:eo_tache_two_live"))
            saved = self.page.locator(".lv-saved li")
            expect(saved).to_have_count(1)
            expect(saved).to_contain_text("12/20 · NCLC 8")
            saved.get_by_role("link").click()
            expect(level).to_have_text("12/20 · NCLC 8 · B2")
            expect(self.page.locator("#lv-proposal li")).to_have_text(report["proposal"])
            transcript = self.page.locator("#lv-transcript")
            if not transcript.evaluate("el => el.open"):
                transcript.locator("summary").click()
            expect(self.page.locator('#lv-turns [data-speaker="user"] .lv-turn__said ins')).to_have_text("prendre")
            self.assertEqual(len(calls), reviews)
            self.assert_no_horizontal_overflow()
