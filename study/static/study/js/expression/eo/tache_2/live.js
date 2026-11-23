(() => {
  "use strict";
  const root = document.getElementById("live-studio");
  const by = id => document.getElementById("lv-" + id);
  if (!root || !by("setup")) return;
  const text = (id, value) => { by(id).textContent = value; };
  const show = (id, visible) => { by(id).hidden = !visible; };
  const wsURL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained";
  const Audio = window.AudioContext || window.webkitAudioContext;
  const capable = Boolean(window.isSecureContext && navigator.mediaDevices?.getUserMedia && Audio && window.AudioWorkletNode);
  const opinion = root.dataset.mode === "opinion";
  const prep = 120000, live = opinion ? 270000 : 210000;
  const timeLabel = opinion ? "4 min 30" : "3 min 30";
  const review = window.HeureuxEO2LiveReview;
  const introduction = by("prompt").textContent;
  const initialTitle = by("title").textContent;
  const initialKicker = by("kicker").textContent;
  const debriefPrompt = root.dataset.scenarioPrompt;
  const stepOf = {reading:"reading",prep:"prep",connecting:"live",live:"live",done:"done"};
  let active;
  const state = () => root.dataset.state;
  const owns = s => active === s;
  function phase(next, label) {
    root.dataset.state = next;
    for (const id of ["setup","prep","done"]) show(id,next === id);
    show("call",next === "live");
    show("start",next === "setup"); show("skip",next === "prep"); show("retry",next === "done");
    show("time",next === "prep" || next === "live");
    show("notepad",!opinion && ["prep","connecting","live"].includes(next));
    show("mute",next === "live"); show("end",!["setup","draining","done"].includes(next));
    if (!["connecting","live"].includes(next)) show("resume-audio",false);
    text("phase",label);
    for (const step of root.querySelectorAll(".lv-step")) {
      if (step.dataset.step === stepOf[next]) step.setAttribute("aria-current","step");
      else step.removeAttribute("aria-current");
    }
  }
  function stamp() { return {wall:Date.now(),mono:performance.now()}; }
  function left(s) {
    return s.duration - Math.max(0,Date.now()-s.began.wall,performance.now()-s.began.mono);
  }
  function display(ms) {
    const total = state() === "live" ? live : prep;
    root.style.setProperty("--lv-left",String(Math.min(1,Math.max(0,ms/total))));
    const sec = Math.max(0,Math.ceil(ms/1000));
    text("clock",`${String(Math.floor(sec/60)).padStart(2,"0")}:${String(sec%60).padStart(2,"0")}`);
  }
  function cutSound(s) {
    for (const source of s.playing) { source.onended = null; source.stop(); source.disconnect(); }
    s.playing.clear(); s.cursor = 0;
  }
  function cutMic(s) {
    if (s.capture) {
      s.capture.port.onmessage = null; s.capture.port.close(); s.capture.disconnect(); s.capture = null;
    }
    s.source?.disconnect(); s.source = null;
    s.stream?.getAudioTracks().forEach(t => { t.enabled = false; });
    delete root.dataset.mic;
  }
  function bilanHeading() {
    text("title", initialTitle); text("kicker", "Votre bilan");
  }
  function finish(s, message, ending = "interrupted") {
    if (!owns(s)) return;
    const started = ["live","draining"].includes(state());
    const elapsed = started ? s.elapsed ?? Math.min(live, Math.max(0,live-left(s))) : 0;
    active = null; clearTimeout(s.timer); clearTimeout(s.watchdog); s.abort.abort();
    s.exchangeGrant = null;
    if (s.audio) s.audio.onstatechange = null;
    cutMic(s); cutSound(s);
    s.stream?.getTracks().forEach(t => { t.onended = t.onunmute = null; t.stop(); });
    closeSocket(s);
    if (s.audio && s.audio.state !== "closed") s.audio.close();
    phase("done","Séance terminée");
    const reviewed = started && review.render(s.rows,{elapsed});
    root.dataset.ending = started ? ending : "failed";
    if (reviewed && ending === "normal") bilanHeading();
    else text("title",!started ? (opinion ? "La prise de parole n’a pas commencé" : "L’échange n’a pas commencé") :
      reviewed ? "Votre bilan partiel" : "Pas de bilan pour cet essai");
    text("prompt",debriefPrompt); text("status",message); show("failed",!started);
    text("user-words","—"); if (!opinion) text("ai-words","—"); by("notes").value = "";
    s.rows.length = 0; s.partial = {}; s.lastModel = null;
    by("title").focus();
  }
  function endAttempt(s, message) {
    if (!opinion || state() !== "live") { finish(s,message,"normal"); return; }
    s.elapsed = Math.min(live,Math.max(0,live-left(s)));
    clearTimeout(s.timer); cutMic(s);
    s.stream.getTracks().forEach(t => t.stop());
    phase("draining","Fin de la transcription");
    text("title",s.elapsed >= live ? "Temps écoulé" : "Prise de parole terminée");
    text("status","Le micro est coupé. La transcription se termine…");
    by("title").focus();
    if (s.sock?.readyState === WebSocket.OPEN) s.sock.send(JSON.stringify({realtimeInput:{audioStreamEnd:true}}));
    // No provider event marks the whole transcript complete. Allow a quiet gap after the last
    // input chunk, with an absolute cap even if the socket never settles.
    s.finishCaptions = () => finish(s,message,"normal");
    s.watchdog = setTimeout(s.finishCaptions,6000);
  }
  function running(s) {
    if (!owns(s) || state() !== "live") return false;
    if (left(s) <= 0) { display(0); endAttempt(s,`Les ${timeLabel} sont écoulées.`); return false; }
    return true;
  }
  function tick(s) {
    clearTimeout(s.timer); if (!owns(s)) return;
    const ms = left(s); display(ms);
    if (ms <= 0) {
      if (state() === "prep" && ms > -live && !document.hidden) connect(s);
      else endAttempt(s,state() === "live" ? `Les ${timeLabel} sont écoulées. Le micro est coupé.` : "Le temps est écoulé.");
    } else {
      if (state() === "live") micSignal(s);
      s.timer = setTimeout(() => tick(s), Math.min(ms,ms%1000 || 1000));
    }
  }
  function micSignal(s) {
    const track = s.stream.getAudioTracks()[0];
    const input = track.label || "Microphone du navigateur";
    const signal = !s.capture ? "Micro coupé" : s.audio.state !== "running" ? "Son suspendu" :
      track.muted ? "Entrée interrompue par le téléphone" :
      performance.now()-s.lastSignal < 5000 ? "Son détecté" : performance.now()-s.micOpened < 5000 ? "En écoute" :
      "Aucun son détecté · vérifiez le micro ou essayez sans écouteurs";
    const value = `${input} · ${signal}`;
    if (by("mic-signal").textContent !== value) text("mic-signal",value);
  }
  function startMic(s) {
    s.micOpened = performance.now(); s.lastSignal = -Infinity;
    s.stream.getAudioTracks().forEach(t => { t.enabled = true; });
    const capture = s.capture = new AudioWorkletNode(s.audio,"french-live-pcm",{channelCount:1,channelCountMode:"explicit"});
    capture.onprocessorerror = () => { if (s.capture === capture) finish(s,"La capture audio s’est arrêtée."); };
    const source = s.source = s.audio.createMediaStreamSource(s.stream);
    capture.port.onmessage = ({data}) => {
      if (!running(s) || s.capture !== capture || s.sock.readyState !== WebSocket.OPEN) return;
      if (s.sock.bufferedAmount > 128000) { finish(s,"Connexion trop lente pour poursuivre sans décaler votre voix."); return; }
      const bytes = new Uint8Array(data);
      if (new Int16Array(data).some(value => Math.abs(value) > 32)) s.lastSignal = performance.now();
      const audio = {mimeType:"audio/pcm;rate=16000",data:btoa(String.fromCharCode(...bytes))};
      s.sock.send(JSON.stringify({realtimeInput:{audio}}));
    };
    source.connect(capture); capture.connect(s.audio.destination);
    root.dataset.mic = "open";
    text("mute","Couper le micro"); by("mute").setAttribute("aria-pressed","false");
    text("status",opinion ? "Micro ouvert · développez votre point de vue. L’interlocuteur vous écoute en silence." :
      "Micro ouvert · transcription automatique. Vous pouvez interrompre votre interlocuteur.");
  }
  function audioReady(s) {
    if (!owns(s) || !s.handshake || !["connecting","live"].includes(state())) return;
    const suspended = s.audio.state !== "running";
    show("resume-audio",suspended);
    if (suspended) { text("status","Le téléphone a suspendu le son. Touchez « Réactiver le son »."); return; }
    if (state() === "live") { text("status",s.capture ? "Micro ouvert · transcription automatique." : "Micro coupé."); return; }
    const track = s.stream.getAudioTracks()[0];
    if (!track || track.readyState !== "live") {
      finish(s,"Le micro est déconnecté. Vérifiez vos écouteurs ou essayez le micro du téléphone."); return;
    }
    if (track.muted) {
      track.enabled = true;  // Let the device wake, without wiring it to the socket yet.
      text("status","Le micro ne fournit pas encore de son. Vérifiez les écouteurs ; le chronomètre attend."); return;
    }
    clearTimeout(s.watchdog); startMic(s);
    s.began = stamp(); s.duration = live; phase("live",opinion ? "Point de vue" : "Échange"); tick(s);
    if (!opinion) s.sock.send(JSON.stringify({realtimeInput:{text:"Pour ouvrir cet échange, dites « Bonjour ! », avec une brève salutation si elle convient à notre relation, puis laissez-moi poser la première question sur le sujet."}}));
  }
  function play(s, encoded, onEnded) {
    const bytes = atob(encoded);
    if (!bytes.length || bytes.length % 2 || bytes.length > 1024*1024) throw new Error("Audio invalide");
    const buffer = s.audio.createBuffer(1,bytes.length/2,24000), samples = buffer.getChannelData(0);
    for (let i=0;i<samples.length;i++) {
      const v = bytes.charCodeAt(2*i) | (bytes.charCodeAt(2*i+1)<<8);
      samples[i] = (v < 32768 ? v : v-65536)/32768;
    }
    const when = Math.max(s.cursor,s.audio.currentTime);
    if (when-s.audio.currentTime > 30) throw new Error("Réponse trop longue");
    const source = s.audio.createBufferSource(); source.buffer = buffer; source.connect(s.audio.destination);
    s.playing.add(source); source.onended = () => { s.playing.delete(source); source.disconnect(); onEnded?.(); };
    source.start(when); s.cursor = when+buffer.duration;
    return onEnded && samples.some(sample => sample !== 0);
  }
  function caption(s, speaker, piece) {
    if (!piece) return;
    if (typeof piece.text === "string" && piece.text.length) {
      let row = s.partial[speaker];
      if (!row) {
        row = s.partial[speaker] = {speaker, text:""};
        s.rows.push(row);
        if (speaker === "model") s.lastModel = row;
      }
      row.text += piece.text;
      text(speaker === "user" ? "user-words" : "ai-words", row.text.slice(-1600));
    }
    if (piece.finished) delete s.partial[speaker];
  }
  function receive(s, raw) {
    if (!owns(s)) return;
    try {
      const msg = JSON.parse(typeof raw === "string" ? raw : new TextDecoder().decode(raw));
      if (msg.error || msg.goAway) { finish(s,"Le service a fermé la connexion. Aucun nouvel appel n’a été lancé."); return; }
      if (msg.setupComplete && state() === "connecting" && !s.handshake) {
        s.handshake = true;
        clearTimeout(s.watchdog);
        // A late handshake must still leave time for an explicit tap to resume mobile audio.
        s.watchdog = setTimeout(() => finish(s,"Le son ou le micro n’est pas prêt. Vérifiez les écouteurs ou essayez le micro du téléphone."),120000);
        audioReady(s);
      }
      const turn = msg.serverContent;
      if (!turn) return;
      if (opinion) {
        if (state() === "live") running(s);
        if (["live","draining"].includes(state())) caption(s,"user",turn.inputTranscription);
        if (state() === "draining" && (turn.inputTranscription?.text || turn.inputTranscription?.finished)) {
          clearTimeout(s.timer);
          s.timer = setTimeout(s.finishCaptions,1800);
        }
        return;  // The candidate keeps the floor, even if Gemini emits a reply during a pause.
      }
      if (!running(s)) return;
      if (turn.interrupted) {
        s.awaitingInterruptedEnd = true;
        cutSound(s);
        caption(s,"model",turn.outputTranscription);
        if (s.lastModel) s.lastModel.interrupted = true;
        // A new learner utterance can already be in progress when the barge-in arrives.
        if (s.lastModel && s.rows.at(-1) === s.lastModel) delete s.partial.user;
        delete s.partial.model; s.lastModel = null;
        caption(s,"user",turn.inputTranscription);
      } else {
        if (turn.modelTurn || turn.outputTranscription?.text) s.awaitingInterruptedEnd = false;
        caption(s,"user",turn.inputTranscription); caption(s,"model",turn.outputTranscription);
      }
      if (!turn.interrupted) for (const part of turn.modelTurn?.parts || []) {
        if (part.inlineData?.mimeType?.startsWith("audio/pcm")) play(s,part.inlineData.data);
      }
      if (turn.turnComplete) {
        // The interrupted model turn can end after the learner has already started talking.
        if (!s.awaitingInterruptedEnd) s.partial = {};
        s.lastModel = null; s.awaitingInterruptedEnd = false;
      }
    } catch { finish(s,"Réponse vocale illisible. La connexion et le micro ont été fermés."); }
  }
  function closeSocket(s) {
    if (!s.sock) return;
    s.sock.onmessage = s.sock.onopen = s.sock.onclose = s.sock.onerror = null;
    s.sock.close(); s.sock = null;
  }
  function requestOptions(s, body) {
    return {method:"POST",credentials:"same-origin",mode:"same-origin",cache:"no-store",redirect:"error",
      headers:{"Content-Type":"application/json","X-CSRFToken":root.querySelector('[name="csrfmiddlewaretoken"]').value},
      body:JSON.stringify({consent:true,...body}),signal:s.abort.signal};
  }
  function tokenError(s, response) {
    finish(s,response.status === 429 ? "Limite de tentatives atteinte. Réessayez plus tard." :
      response.status === 403 ? "L’autorisation de cette séance n’est plus valide." :
      "La simulation est indisponible pour le moment.");
  }
  function openSocket(s, {token, model}) {
    if (typeof token !== "string" || !token.startsWith("auth_tokens/") || model !== "models/gemini-3.8-live") throw new Error("Configuration invalide");
    const socket = s.sock = new WebSocket(`${wsURL}?access_token=${encodeURIComponent(token)}`);
    socket.binaryType = "arraybuffer";
    socket.onopen = () => { if (owns(s) && s.sock === socket) socket.send(JSON.stringify({setup:{model,generationConfig:{responseModalities:["AUDIO"]},inputAudioTranscription:{languageCodes:["fr-FR"]},outputAudioTranscription:{}}})); };
    return socket;
  }
  function readPrompt(s, config) {
    phase("reading","Lecture du sujet");
    text("title","Votre consigne"); text("prompt",root.dataset.scenarioPrompt);
    text("status","Lecture du sujet · micro coupé, chronomètre arrêté.");
    by("title").focus();
    const socket = openSocket(s,config);
    const failed = () => finish(s,"La lecture du sujet n’a pas abouti. " +
      (opinion ? "Le chronomètre n’a pas démarré." : "La préparation n’a pas démarré."));
    let requested = false, audible = false, complete = false;
    function afterPlayback() {
      if (!owns(s) || state() !== "reading" || !complete || s.playing.size) return;
      clearTimeout(s.watchdog);
      if (opinion) { connect(s); return; }
      s.began = stamp(); s.duration = prep; phase("prep","Préparation"); by("notepad").open = true;
      text("status","Micro coupé · préparez vos questions."); tick(s);
    }
    s.watchdog = setTimeout(failed,120000);
    socket.onerror = socket.onclose = () => { if (s.sock === socket) failed(); };
    socket.onmessage = e => {
      if (!owns(s) || s.sock !== socket) return;
      try {
        const msg = JSON.parse(typeof e.data === "string" ? e.data : new TextDecoder().decode(e.data));
        if (msg.error || msg.goAway || msg.serverContent?.interrupted) { failed(); return; }
        if (msg.setupComplete && !requested) {
          requested = true;
          socket.send(JSON.stringify({realtimeInput:{text:"Lisez la consigne."}}));
        }
        const turn = msg.serverContent;
        for (const part of turn?.modelTurn?.parts || []) if (part.inlineData?.mimeType?.startsWith("audio/pcm")) {
          if (play(s,part.inlineData.data,afterPlayback)) audible = true;
        }
        if (turn?.turnComplete) {
          if (!requested || !audible) { failed(); return; }
          complete = true; closeSocket(s); afterPlayback();
        }
      } catch { failed(); }
    };
  }
  async function connect(s) {
    if (!owns(s) || state() !== (opinion ? "reading" : "prep")) return;
    clearTimeout(s.timer); phase("connecting","Connexion");
    const notes = by("notes");
    by("notepad").open = !opinion && Boolean(notes.value.trim());
    if (document.activeElement === notes) by("notepad").querySelector("summary").focus({preventScroll:true});
    notes.scrollTop = 0;
    text("status",`Autorisez le micro. Les ${timeLabel} commencent une fois la connexion établie.`);
    s.watchdog = setTimeout(() => finish(s,"Le délai d’autorisation du micro a expiré."),120000);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({video:false,audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});
      if (!owns(s)) { stream.getTracks().forEach(t => t.stop()); return; }
      s.stream = stream;
      stream.getAudioTracks().forEach(t => {
        t.enabled = false;
        t.onunmute = () => audioReady(s);
        t.onended = () => finish(s,"Le microphone s’est déconnecté. Vérifiez vos écouteurs ou essayez sans Bluetooth.");
      });
      s.audio.onstatechange = () => audioReady(s);
      clearTimeout(s.watchdog);
      s.watchdog = setTimeout(() => finish(s,"La connexion n’a pas abouti. Aucun nouvel essai automatique."),30000);
      text("status","Connexion au studio · le chronomètre est arrêté.");
      const response = await fetch(root.dataset.tokenUrl,requestOptions(s,{purpose:"exchange",exchangeGrant:s.exchangeGrant}));
      s.exchangeGrant = null;
      if (!owns(s)) return;
      if (!response.ok) { tokenError(s,response); return; }
      const config = await response.json();
      if (!owns(s)) return;
      if (typeof config.reviewGrant !== "string" || !config.reviewGrant) throw new Error("Autorisation invalide");
      window.HeureuxEO2Evaluation?.setGrant(config.reviewGrant);
      const socket = openSocket(s,config);
      socket.onmessage = e => receive(s,e.data);
      socket.onerror = socket.onclose = () => finish(s,"Connexion vocale interrompue ou quota indisponible. Le micro est coupé.");
    } catch (error) {
      if (owns(s)) finish(s,error.name === "AbortError" ? "Ouverture annulée. Aucun appel n’est en cours." :
        error.name === "NotAllowedError" ? "Micro refusé. Autorisez le microphone pour ce site dans votre navigateur." :
        ["NotFoundError","NotReadableError"].includes(error.name) ? "Micro indisponible. Vérifiez le micro des écouteurs ou réessayez sans Bluetooth." :
        "Impossible d’ouvrir le micro ou la connexion vocale.");
    }
  }
  // A saved exchange opens on its debrief; its report is the stored one, not a new Groq call.
  function reopen(saved) {
    phase("done","Séance enregistrée");
    root.dataset.ending = "normal";
    bilanHeading(); text("prompt",debriefPrompt); text("status","Séance enregistrée.");
    review.render(saved.rows,{elapsed:saved.elapsed,saved});
  }
  function setup() {
    review.clear(); delete root.dataset.ending; delete root.dataset.mic;
    phase("setup","Avant la simulation"); display(prep); text("status",capable ? "" : "Ce navigateur ne permet pas l’appel vocal. Essayez un navigateur récent en HTTPS.");
    text("title",initialTitle); text("kicker",initialKicker); text("prompt",introduction);
    by("start").disabled = !capable; by("captions").open = false;
  }
  by("start").onclick = async () => {
    if (!capable || active || state() !== "setup") return;
    const s = active = {abort:new AbortController(),playing:new Set(),rows:[],partial:{},cursor:0};
    try {
      const response = await window.HeureuxAudioRequest(root.dataset.tokenUrl,requestOptions(s,{purpose:"attempt"}),{
        confirmBeforeSend:true, title:"Autoriser la simulation", action:"Autoriser cette simulation",
        description:(opinion ? "La question sera lue sans micro. J’accepte d’envoyer ma voix à Google pendant ma prise de parole, puis sa transcription à Groq pour le bilan. " :
          "La consigne sera lue sans micro. J’accepte d’envoyer ma voix à Google pendant l’échange, puis sa transcription à Groq pour le bilan. ") +
          "Heureux conserve la transcription et le bilan, pas l’audio. " +
          "Je confirme avoir au moins 18 ans et participer depuis le Canada ou les États-Unis. Des personnes peuvent examiner l’échange pour améliorer les produits de Google.",
        onConfirm:() => {
          phase("loading","Ouverture"); text("status","Ouverture de la lecture · micro coupé.");
          clearTimeout(s.watchdog);
          s.watchdog = setTimeout(() => finish(s,"La lecture n’a pas pu démarrer. Aucun chronomètre n’a été lancé."),30000);
          s.audio ??= new Audio();
          return s.audio.resume();
        }
      });
      if (!owns(s)) return;
      if (!response.ok) { tokenError(s,response); return; }
      const config = await response.json();
      if (!owns(s)) return;
      if (typeof config.exchangeGrant !== "string" || !config.exchangeGrant) throw new Error("Autorisation invalide");
      s.exchangeGrant = config.exchangeGrant;
      await s.audio.audioWorklet.addModule(root.dataset.worklet);
      if (!owns(s)) return;
      clearTimeout(s.watchdog); readPrompt(s,config);
    } catch (error) {
      if (!owns(s)) return;
      if (error.name === "AbortError") {
        finish(s,"Ouverture annulée."); setup(); text("status","Ouverture annulée."); by("start").focus();
      } else finish(s,"Impossible de lancer la lecture du sujet. Le chronomètre n’a pas démarré.");
    }
  };
  by("skip").onclick = () => { if (active) connect(active); };
  by("resume-audio").onclick = async () => {
    const s = active; if (!s) return;
    try { await s.audio.resume(); audioReady(s); }
    catch { if (owns(s)) finish(s,"Le son n’a pas repris. Vérifiez le micro ou réessayez sans écouteurs."); }
  };
  by("mute").onclick = () => {
    const s = active; if (!s || !running(s)) return;
    if (!s.capture) { startMic(s); return; }
    cutMic(s); if (s.sock.readyState === WebSocket.OPEN) s.sock.send(JSON.stringify({realtimeInput:{audioStreamEnd:true}}));
    text("mute","Rouvrir le micro"); by("mute").setAttribute("aria-pressed","true"); text("status","Micro coupé. Aucun son n’est envoyé.");
  };
  by("end").onclick = () => { if (active) endAttempt(active,"Vous avez mis fin à la séance."); };
  by("retry").onclick = () => {
    const url = new URL(location.href);
    if (url.searchParams.has("simulation") || url.hash.startsWith("#lv-")) {
      url.searchParams.delete("simulation");
      url.hash = "";
      history.replaceState(history.state,"",url);
    }
    setup(); by("title").focus();
  };
  document.addEventListener("visibilitychange",() => {
    if (document.hidden && active) finish(active,"Séance fermée : vous avez quitté l’onglet.");
  });
  window.addEventListener("pagehide",() => { if (active) finish(active,"Séance fermée."); setup(); });
  // Keep the session timeline below the site's sticky navigation.
  const nav = document.querySelector(".nav");
  const pin = () => root.style.setProperty("--lv-top",`${nav ? Math.round(nav.getBoundingClientRect().height) : 0}px`);
  window.addEventListener("resize",pin); pin();
  setup();
  const saved = by("saved-simulation");
  if (saved) reopen(JSON.parse(saved.textContent));
})();
