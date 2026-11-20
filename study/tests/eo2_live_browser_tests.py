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
                self.page.get_by_role("link", name="Lancer la conversation sur ce sujet").click()
            else:
                self.page.goto(self.live_server_url + reverse("study:eo_tache_two_live"))
        self.consent = self.page.locator("#lv-consent")
        self.start = self.page.locator("#lv-start")
        self.pin_dialog = self.page.locator("[data-audio-pin-dialog]")

    def submit_live_pin(self, pin=PILOT_PIN):
        expect(self.pin_dialog.get_by_role("heading")).to_have_text("Autoriser la conversation Gemini Live")
        self.pin_dialog.get_by_label("Code PIN ElevenLabs").fill(pin)
        self.pin_dialog.get_by_role("button", name="Autoriser cette conversation").click()

    def test_native_voice_subject_launch_uses_exact_consigne_and_retains_return_link(self):
        import json
        self._import_eo_tache_two_content()
        args = ("octobre", 5, 21)
        self.open_live_pilot(subject_args=args)
        self.consent.check()
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
        expect(self.start).to_be_disabled()
        self.consent.check()
        self.start.click()
        expect(self.page.locator("#lv-prep")).to_be_visible()
        self.assertEqual(self.page.evaluate("probe.calls"), 0)
        self.assertEqual(self.token_requests, [])
        self.page.locator("#lv-skip").click()
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
        self.page.evaluate("probe.sockets[0].receive({serverContent:{interrupted:true}})")
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
        self.page.locator("#lv-retry").click()
        expect(self.start).to_be_disabled()
        self.assert_no_horizontal_overflow()

    def test_native_voice_deadline_closes_call_even_in_mid_reply(self):
        self.open_live_pilot()
        self.page.clock.install(time="2026-03-16T10:00:00Z")
        self.page.clock.pause_at("2026-03-16T10:00:05Z")
        self.consent.check()
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
        self.page.evaluate("""probe.sockets[0].receive({serverContent:{modelTurn:{
          parts:[{inlineData:{mimeType:'audio/pcm',data:btoa('\\0'.repeat(144000))}}]
        }}})""")
        self.page.clock.fast_forward(1_000)
        expect(self.page.locator("#lv-done")).to_be_visible()
        self.assertEqual(self.page.evaluate("[probe.played[0].wasStopped,probe.track.readyState]"), [True, "ended"])

    def test_native_voice_late_permission_and_quota_do_not_reconnect(self):
        self.open_live_pilot()
        self.consent.check()
        self.start.click()
        self.page.evaluate("probe.wait=true")
        self.page.locator("#lv-skip").click()
        self.submit_live_pin()
        expect(self.page.locator("html")).to_have_attribute("data-waiting", "true")
        self.page.locator("#lv-end").click()
        self.page.evaluate("probe.release()")
        self.assertEqual(self.page.evaluate("probe.track.readyState"), "ended")
        self.assertEqual(len(self.token_requests), 2)
        self.page.locator("#lv-retry").click()
        self.consent.check()
        self.start.click()
        self.page.evaluate("probe.wait=false; probe.deny=true")
        self.page.locator("#lv-skip").click()
        self.submit_live_pin()
        expect(self.page.locator("#lv-status")).to_contain_text("Micro refusé")
        self.assertEqual(len(self.token_requests), 4)
        self.page.locator("#lv-retry").click()
        self.consent.check()
        self.start.click()
        self.page.evaluate("probe.deny=false")
        self.mint_status = 429
        self.page.locator("#lv-skip").click()
        self.submit_live_pin()
        expect(self.page.locator("#lv-status")).to_contain_text("Limite")
        self.assertEqual(self.page.evaluate("[probe.calls,probe.track.readyState,probe.sockets.length]"), [2, "ended", 0])
        self.assertEqual(len(self.token_requests), 6)

    def test_native_voice_disconnect_and_navigation_discard_pending_audio(self):
        self.open_live_pilot()
        for action in ("probe.sockets.at(-1).onclose()", "window.dispatchEvent(new Event('pagehide'))"):
            self.consent.check()
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
            expect(self.start).to_be_disabled()
        self.assertEqual(len(self.token_requests), 4)

    def test_native_voice_cancel_shared_pin_leaves_microphone_closed(self):
        self.open_live_pilot()
        self.consent.check()
        self.start.click()
        self.page.locator("#lv-skip").click()
        self.pin_dialog.get_by_label("Code PIN ElevenLabs").fill("unfinished")
        self.pin_dialog.get_by_role("button", name="Annuler").first.click()
        expect(self.page.locator("#lv-status")).to_contain_text("annulée")
        expect(self.pin_dialog.get_by_label("Code PIN ElevenLabs")).to_have_value("")
        expect(self.pin_dialog.get_by_role("heading", include_hidden=True)).to_have_text("Nouvel audio ElevenLabs")
        self.assertEqual(self.page.evaluate("[probe.calls,probe.sockets.length]"), [0, 0])
        self.assertEqual(self.token_requests, [{"consent": True}])
