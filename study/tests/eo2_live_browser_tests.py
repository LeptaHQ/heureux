import json
import re

from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect

from . import factories


PILOT_PIN = "test-audio-pin"


class LiveConversationBrowserMixin:
    def open_live_pilot(self, *, subject_args=()):
        """Real Web Audio and worklet; synthetic input and a local stand-in for Gemini."""
        factories.make_task(self.part, "tache-2")
        self.page.add_init_script("""
        window.probe = {calls:0, sockets:[], played:[], sent:[]};
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
        Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {value: async () => {
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
        }});
        window.WebSocket = class {
          static OPEN = 1;
          constructor(url) {
            this.url=url; this.readyState=1; this.bufferedAmount=0; p.sockets.push(this);
            queueMicrotask(() => this.onopen?.());
          }
          send(value) {
            const message = JSON.parse(value);
            p.sent.push(message);
            if (message.setup) document.documentElement.dataset.handshake='true';
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
            if body.get("pin") != PILOT_PIN:
                code = "pin_invalid" if body.get("pin") else "pin_required"
                route.fulfill(status=403, json={"error": code, "message": "Code PIN incorrect."})
                return
            route.fulfill(status=self.mint_status, json={
                "model": "models/gemini-3.8-live", "token": "auth_tokens/synthetic",
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

    def test_native_voice_subject_launch_uses_exact_consigne_and_retains_return_link(self):
        self._import_eo_tache_two_content()
        args = ("octobre", 5, 21)
        self.open_live_pilot(subject_args=args)
        self.start.click()
        expect(self.page.locator("#lv-prompt")).to_have_text(json.loads(self.selected_consigne))
        self.assertEqual(self.page.evaluate("probe.calls"), 0)
        self.page.locator("#lv-skip").click()
        self.submit_live_pin()
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.page.locator("#lv-end").click()
        self.page.get_by_role("link", name="Revenir à la fiche de ce sujet").click()
        expect(self.page).to_have_url(self.live_server_url + reverse("study:task_subject_detail", args=("eo", "tache-2", *args)))

    def test_native_voice_waits_for_handshake_and_supports_interruption(self):
        self.open_live_pilot()
        expect(self.page.locator("#lv-setup input[type=checkbox], #lv-setup .lv-terms")).to_have_count(0)
        expect(self.start).to_be_enabled()
        self.start.click()
        expect(self.page.locator("#lv-prep")).to_be_visible()
        self.assertEqual(self.page.evaluate("probe.calls"), 0)
        self.assertEqual(self.token_requests, [])
        self.page.locator("#lv-skip").click()
        expect(self.pin_dialog).to_contain_text("J’accepte d’envoyer ma voix à Google")
        self.assertEqual(self.token_requests, [])
        self.submit_live_pin("incorrect")
        expect(self.pin_dialog.get_by_role("alert")).to_have_text("Code PIN incorrect.")
        self.assertEqual(self.page.evaluate("[probe.calls,probe.sockets.length]"), [0, 0])
        self.submit_live_pin()
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.assertEqual(self.token_requests[-1], {"consent": True, "pin": PILOT_PIN})
        self.assertNotIn(PILOT_PIN, self.page.evaluate("probe.sockets[0].url + JSON.stringify(probe.sent)"))
        expect(self.pin_dialog.get_by_label("Code PIN ElevenLabs")).to_have_value("")
        self.assertEqual(self.page.evaluate("probe.sent.map(m => Object.keys(m))"), [["setup"]])
        self.assertFalse(self.page.evaluate("probe.track.enabled"))
        self.page.evaluate("probe.sockets[0].receive({setupComplete:{}})")
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
        self.assertEqual(self.page.evaluate("probe.played[0].buffer.sampleRate"), 24000)
        self.page.locator("#lv-captions summary").click()
        expect(self.page.locator("#lv-ai-words")).to_have_text("À dix heures.")
        self.page.evaluate("""() => {
          const send = serverContent => probe.sockets[0].receive({serverContent});
          send({interrupted:true, inputTranscription:{text:"Et le "}});
          send({turnComplete:true});
          send({inputTranscription:{text:"dimanche ?",finished:true}});
        }""")
        self.assertTrue(self.page.evaluate("probe.played[0].wasStopped && probe.track.enabled"))
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
        self.start.click()
        expect(self.page.locator("#lv-prep")).to_be_visible()
        self.page.clock.fast_forward(119_000)
        expect(self.page.locator("#lv-clock")).to_have_text("00:01")
        self.assertEqual(self.page.evaluate("probe.calls"), 0)
        self.page.clock.fast_forward(1_000)
        self.submit_live_pin()
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.page.clock.fast_forward(7_000)  # Device setup is outside the interaction clock.
        self.page.evaluate("probe.sockets[0].receive({setupComplete:{}})")
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
        self.assertEqual(self.page.evaluate("[probe.played[0].wasStopped,probe.track.readyState]"), [True, "ended"])
        expect(self.page.locator("#lv-title")).to_have_text("Votre bilan")
        expect(self.page.locator("#lv-evidence")).to_contain_text("Combien coûte l’atelier ?")
        self.page.locator("#lv-transcript summary").click()
        turns = self.page.locator("#lv-turns li")
        expect(turns.locator("p")).to_have_text([
            "Combien coûte l’atelier ?", "Vingt dollars.", "Est-ce que je peux payer par carte ?",
        ])
        expect(turns.nth(1).get_by_role("button")).to_have_count(0)
        turns.first.get_by_role("button").click()
        turns.first.get_by_role("textbox").fill("Combien coûte la sortie ?")
        turns.first.get_by_role("button", name="Appliquer").click()
        expect(self.page.locator("#lv-evidence")).to_contain_text("Combien coûte la sortie ?")
        expect(turns.first.locator("small")).to_contain_text("Combien coûte l’atelier ?")
        self.assertEqual(len(self.token_requests), 1)
        self.page.evaluate("window.dispatchEvent(new Event('pagehide'))")
        expect(turns).to_have_count(0)
        expect(self.page.locator("#lv-evidence")).to_be_empty()

    def test_native_voice_late_permission_and_quota_do_not_reconnect(self):
        self.open_live_pilot()
        self.start.click()
        self.page.evaluate("probe.wait=true")
        self.page.locator("#lv-skip").click()
        self.submit_live_pin()
        expect(self.page.locator("html")).to_have_attribute("data-waiting", "true")
        self.page.locator("#lv-end").click()
        self.page.evaluate("probe.release()")
        self.assertEqual(self.page.evaluate("probe.track.readyState"), "ended")
        self.assertEqual(len(self.token_requests), 1)
        self.page.locator("#lv-retry").click()
        self.start.click()
        self.page.evaluate("probe.wait=false; probe.deny=true")
        self.page.locator("#lv-skip").click()
        self.submit_live_pin()
        expect(self.page.locator("#lv-status")).to_contain_text("Micro refusé")
        expect(self.page.locator("#lv-title")).to_have_text("L’échange n’a pas commencé")
        expect(self.page.locator("#lv-empty")).to_be_hidden()
        self.assertEqual(len(self.token_requests), 2)
        self.page.locator("#lv-retry").click()
        self.start.click()
        self.page.evaluate("probe.deny=false")
        self.mint_status = 429
        self.page.locator("#lv-skip").click()
        self.submit_live_pin()
        expect(self.page.locator("#lv-status")).to_contain_text("Limite")
        self.assertEqual(self.page.evaluate("[probe.calls,probe.track.readyState,probe.sockets.length]"), [2, "ended", 0])
        self.assertEqual(len(self.token_requests), 3)

    def test_native_voice_partial_disconnect_and_silent_attempt(self):
        self.open_live_pilot()
        for with_words in (True, False):
            self.start.click()
            self.page.locator("#lv-skip").click()
            self.submit_live_pin()
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

    def test_native_voice_marks_only_changed_learner_words_and_rechecks_after_edit(self):
        self.open_live_pilot()
        self.start.click()
        self.page.locator("#lv-skip").click()
        self.submit_live_pin()
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
        expect(turns.locator("del")).to_have_text(["m’inscrire"])
        expect(turns.locator("ins")).to_have_text(["m’inscris"])
        expect(turns.locator('[data-speaker="model"] del')).to_have_count(0)
        learner = turns.locator('[data-speaker="user"]').last
        learner.get_by_role("button", name=re.compile("Rectifier", re.I)).click()
        learner.get_by_role("textbox").fill("Si je m’inscris ce soir, est-ce trop tard ?")
        learner.get_by_role("button", name="Appliquer").click()
        expect(turns.locator("del, ins")).to_have_count(0)
        expect(learner).to_contain_text("Si je m’inscrire ce soir, est-ce trop tard ?")
        self.assertEqual(len(self.token_requests), 1)

    def test_native_voice_disconnect_and_navigation_discard_pending_audio(self):
        self.open_live_pilot()
        for action in ("probe.sockets.at(-1).onclose()", "window.dispatchEvent(new Event('pagehide'))"):
            self.start.click()
            self.page.locator("#lv-skip").click()
            self.submit_live_pin()
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
        self.assertEqual(len(self.token_requests), 2)

    def test_native_voice_cancel_shared_pin_leaves_microphone_closed(self):
        self.open_live_pilot()
        self.start.click()
        self.page.locator("#lv-skip").click()
        self.pin_dialog.get_by_label("Code PIN ElevenLabs").fill("unfinished")
        self.pin_dialog.get_by_role("button", name="Annuler").first.click()
        expect(self.page.locator("#lv-status")).to_contain_text("annulée")
        expect(self.pin_dialog.get_by_label("Code PIN ElevenLabs")).to_have_value("")
        expect(self.pin_dialog.get_by_role("heading", include_hidden=True)).to_have_text("Nouvel audio ElevenLabs")
        self.assertEqual(self.page.evaluate("[probe.calls,probe.sockets.length]"), [0, 0])
        self.assertEqual(self.token_requests, [])

    def test_native_voice_prompt_reading_never_starts_either_clock_or_the_microphone(self):
        self.open_live_pilot()
        listen = self.page.locator("#lv-listen")
        expect(listen).to_be_enabled()
        listen.click()
        expect(self.pin_dialog).to_contain_text("Seule la consigne est envoyée à Google")
        self.assertEqual(self.token_requests, [])
        self.pin_dialog.get_by_label("Code PIN ElevenLabs").fill(PILOT_PIN)
        self.pin_dialog.get_by_role("button", name="Autoriser la lecture", exact=True).click()
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.page.evaluate("""() => {
          const ws = probe.sockets[0];
          ws.receive({setupComplete:{}});
          ws.receive({serverContent:{modelTurn:{parts:[{inlineData:{
            mimeType:'audio/pcm;rate=24000',data:btoa('\\0'.repeat(2400))
          }}]},turnComplete:true}});
        }""")
        expect(self.page.locator("#lv-listen-status")).to_contain_text("Lecture terminée")
        self.assertEqual(self.page.evaluate("[probe.calls,probe.sockets[0].readyState,probe.played.length]"), [0, 3, 1])
        self.assertEqual(self.token_requests[-1], {"consent": True, "purpose": "read_prompt", "pin": PILOT_PIN})
        self.assertTrue(self.page.evaluate("probe.sent.some(m => m.clientContent?.turnComplete)"))
        expect(self.page.locator("#live-studio")).to_have_attribute("data-state", "setup")
        expect(self.page.locator("#lv-time")).to_be_hidden()
        self.start.click()
        expect(self.page.locator("#lv-clock")).to_have_text("02:00")
        self.assertEqual(self.page.evaluate("probe.calls"), 0)

    def test_native_voice_optional_review_scores_current_text_and_discards_stale_results(self):
        self.open_live_pilot()
        calls = []
        exhausted = False
        original = "📷 Et si je veux prend deux appareils ?"
        edited = "Et si je veux prendre deux appareils ?"
        report = {"score": 12, "nclc": "8", "cefr": "B2", "reason": "Vous comparez les options.",
                  "next": "Précisez la durée du prêt.", "evidence": [
                      {"turnIndex": 0, "quote": "Combien coûte", "why": "Une demande de prix."},
                      {"turnIndex": 2, "quote": "Et si je veux", "why": "Une hypothèse."}],
                  "annotations": [{"turnIndex": 2, "start": 12, "end": 22, "before": "veux prend",
                                   "after": "veux prendre", "why": "Après vouloir, employez l’infinitif."}]}

        def fake_review(route):
            body = route.request.post_data_json
            calls.append(body)
            if exhausted:
                route.fulfill(status=429, json={"error": "Quota atteint."})
            elif body.get("pin") != PILOT_PIN:
                route.fulfill(status=403, json={"error": "pin_required"})
            else:
                route.fulfill(json=report)

        self.page.route("**" + reverse("study:eo_tache_two_live_evaluation"), fake_review)
        self.start.click()
        self.page.locator("#lv-skip").click()
        self.submit_live_pin()
        expect(self.page.locator("html")).to_have_attribute("data-handshake", "true")
        self.page.evaluate("""words => {
          const ws = probe.sockets[0];
          ws.receive({setupComplete:{}});
          ws.receive({serverContent:{inputTranscription:{text:'Combien coûte le prêt ?'},
            outputTranscription:{text:'Cinq dollars.'},turnComplete:true}});
          ws.receive({serverContent:{inputTranscription:{text:words},turnComplete:true}});
        }""", original)
        self.page.locator("#lv-end").click()
        consent, button, level = (self.page.locator("#lv-" + key) for key in ("assessment-consent", "assess", "level"))
        expect(level).to_have_text("Non évalué")
        expect(button).to_be_disabled()
        consent.check()
        self.assertEqual(calls, [])
        button.click()
        self.pin_dialog.get_by_label("Code PIN ElevenLabs").fill(PILOT_PIN)
        self.pin_dialog.get_by_role("button", name="Autoriser ce bilan").click()
        expect(level).to_have_text("12/20 · NCLC 8 · B2")
        expect(self.page.locator("#lv-assessment-evidence")).to_contain_text("Une hypothèse.")
        transcript = self.page.locator("#lv-transcript")
        if not transcript.evaluate("el => el.open"):
            transcript.locator("summary").click()
        target = self.page.locator('#lv-turns [data-speaker="user"]').last
        expect(target.locator("ins")).to_have_text("prendre")

        def change(text):
            target.get_by_role("button", name=re.compile("Rectifier")).click()
            target.get_by_role("textbox").fill(text)
            target.get_by_role("button", name="Appliquer").click()

        change(edited)
        expect(level).to_have_text("Non évalué")
        expect(self.page.locator("#lv-assessment-evidence")).to_be_empty()
        expect(consent).not_to_be_checked()
        self.assertEqual(calls[-1]["rows"][-1], {"speaker": "user", "text": original})
        self.assertEqual(len(calls), 2)
        exhausted = True
        consent.check()
        button.click()
        expect(self.page.locator("#lv-assessment-status")).to_contain_text("Limite atteinte")
        expect(self.page.locator("#lv-evidence")).to_contain_text("Combien coûte le prêt")
        expect(level).to_have_text("Non évalué")
        self.page.evaluate("""() => { window.HeureuxAudioRequest = (url, opts) => {
          probe.review = JSON.parse(opts.body);
          return new Promise(resolve => probe.releaseReview = report => resolve(Response.json(report)));
        }; }""")
        consent.check()
        button.click()
        self.assertEqual(self.page.evaluate("probe.review.rows.at(-1)"), {"speaker": "user", "text": edited})
        change(edited + " Merci.")
        self.page.evaluate("report => probe.releaseReview(report)", report)
        expect(level).to_have_text("Non évalué")
        expect(self.page.locator("#lv-assessment-result")).to_be_hidden()
        self.assertEqual(self.page.evaluate("[probe.calls,probe.track.readyState]"), [1, "ended"])
