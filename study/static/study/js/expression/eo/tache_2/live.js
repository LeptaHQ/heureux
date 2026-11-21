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
  const prep = 120000, live = 210000;
  const review = window.HeureuxEO2LiveReview;
  const introduction = by("prompt").textContent;
  const initialTitle = by("title").textContent;
  const initialKicker = by("kicker").textContent;
  const stepOf = {loading:"prep",prep:"prep",connecting:"live",live:"live",done:"done"};
  let active, reader;
  const state = () => root.dataset.state;
  const owns = s => active === s;
  function phase(next, label) {
    root.dataset.state = next;
    for (const id of ["setup","prep","done"]) show(id,next === id);
    show("call",next === "live");
    show("start",next === "setup"); show("skip",next === "prep"); show("retry",next === "done");
    show("time",["prep","connecting","live"].includes(next));
    show("notepad",["prep","connecting","live"].includes(next));
    show("mute",next === "live"); show("end",!["setup","done"].includes(next));
    text("phase",label);
    if (next !== "done") text("kicker",["prep","connecting","live"].includes(next) ? "Consigne" : initialKicker);
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
    const total = ["connecting","live"].includes(state()) ? live : prep;
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
  function finish(s, message, ending = "interrupted") {
    if (!owns(s)) return;
    const started = state() === "live";
    const elapsed = started ? Math.min(live,Math.max(0,Date.now()-s.began.wall,performance.now()-s.began.mono)) : 0;
    active = null; clearTimeout(s.timer); clearTimeout(s.watchdog); s.abort.abort();
    cutMic(s); cutSound(s);
    s.stream?.getTracks().forEach(t => { t.onended = null; t.stop(); });
    closeSocket(s);
    if (s.audio && s.audio.state !== "closed") s.audio.close();
    phase("done","Séance terminée");
    const reviewed = started && review.render(s.rows,{elapsed});
    root.dataset.ending = started ? ending : "failed";
    const cut = ending !== "normal";
    text("kicker",!started ? "Séance interrompue" : !reviewed ? (cut ? "Échange interrompu" : "Échange terminé") :
      cut ? "Bilan partiel · échange interrompu" : "Bilan de l’échange");
    text("title",!started ? "L’échange n’a pas commencé" : reviewed ? "Votre bilan" : "Pas de bilan pour cet essai");
    text("prompt",root.dataset.scenarioTitle); text("status",message); show("failed",!started);
    text("user-words","—"); text("ai-words","—"); by("notes").value = "";
    s.rows.length = 0; s.partial = {}; s.lastModel = null;
    by("title").focus();
  }
  function running(s) {
    if (!owns(s) || state() !== "live") return false;
    if (left(s) <= 0) { display(0); finish(s,"Les 3 min 30 sont écoulées.","normal"); return false; }
    return true;
  }
  function tick(s) {
    clearTimeout(s.timer); if (!owns(s)) return;
    const ms = left(s); display(ms);
    if (ms <= 0) {
      if (state() === "prep" && ms > -live && !document.hidden) connect(s);
      else finish(s,state() === "live" ? "Les 3 min 30 sont écoulées. Le micro est coupé." : "Le temps est écoulé.","normal");
    } else s.timer = setTimeout(() => tick(s), Math.min(ms,ms%1000 || 1000));
  }
  function startMic(s) {
    s.stream.getAudioTracks().forEach(t => { t.enabled = true; });
    const capture = s.capture = new AudioWorkletNode(s.audio,"french-live-pcm",{channelCount:1,channelCountMode:"explicit"});
    capture.onprocessorerror = () => { if (s.capture === capture) finish(s,"La capture audio s’est arrêtée."); };
    const source = s.source = s.audio.createMediaStreamSource(s.stream);
    capture.port.onmessage = ({data}) => {
      if (!running(s) || s.capture !== capture || s.sock.readyState !== WebSocket.OPEN) return;
      if (s.sock.bufferedAmount > 128000) { finish(s,"Connexion trop lente pour poursuivre sans décaler votre voix."); return; }
      const bytes = new Uint8Array(data);
      const audio = {mimeType:"audio/pcm;rate=16000",data:btoa(String.fromCharCode(...bytes))};
      s.sock.send(JSON.stringify({realtimeInput:{audio}}));
    };
    source.connect(capture); capture.connect(s.audio.destination);
    root.dataset.mic = "open";
    text("mute","Couper le micro"); by("mute").setAttribute("aria-pressed","false");
    text("status","Micro ouvert · transcription automatique. Vous pouvez interrompre votre interlocuteur.");
  }
  function play(s, encoded) {
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
    s.playing.add(source); source.onended = () => { s.playing.delete(source); source.disconnect(); };
    source.start(when); s.cursor = when+buffer.duration;
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
      if (msg.setupComplete && state() === "connecting") {
        clearTimeout(s.watchdog); s.began = stamp(); s.duration = live; phase("live","Interaction");
        startMic(s); tick(s);
      }
      const turn = msg.serverContent;
      if (!turn || !running(s)) return;
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
    s.sock.close();
  }
  function tokenRequest(s, reading = false) {
    return window.HeureuxAudioRequest(root.dataset.tokenUrl,{method:"POST",credentials:"same-origin",mode:"same-origin",cache:"no-store",
      headers:{"Content-Type":"application/json","X-CSRFToken":root.querySelector('[name="csrfmiddlewaretoken"]').value},
      body:JSON.stringify(reading ? {consent:true,purpose:"read_prompt"} : {consent:true}),signal:s.abort.signal},{
      confirmBeforeSend:true,
      title:reading ? "Autoriser la lecture de la consigne" : "Autoriser la conversation Gemini Live",
      description:"En autorisant, je confirme avoir au moins 18 ans et participer depuis le Canada ou les États-Unis. " +
        (reading ? "Seule la consigne est envoyée à Google, sans micro." :
          "J’accepte d’envoyer ma voix à Google. Sur l’offre gratuite, des personnes peuvent examiner l’échange pour améliorer les produits de Google."),
      action:reading ? "Autoriser la lecture" : "Autoriser cette conversation"
    });
  }
  async function socketConfig(response) {
    const {token,model} = await response.json();
    if (typeof token !== "string" || !token.startsWith("auth_tokens/") || model !== "models/gemini-3.8-live") throw new Error("Configuration invalide");
    return {token,model};
  }
  function openSocket(s, {token, model}) {
    const socket = s.sock = new WebSocket(`${wsURL}?access_token=${encodeURIComponent(token)}`);
    socket.binaryType = "arraybuffer";
    socket.onopen = () => socket.send(JSON.stringify({setup:{model,generationConfig:{responseModalities:["AUDIO"]},inputAudioTranscription:{},outputAudioTranscription:{}}}));
    return socket;
  }
  function stopReading(message = "") {
    const s = reader;
    if (s) {
      reader = null;
      clearTimeout(s.watchdog); clearTimeout(s.timer); s.abort.abort();
      closeSocket(s); cutSound(s);
      if (s.audio && s.audio.state !== "closed") s.audio.close();
    }
    text("listen","Écouter la consigne");
    text("listen-status",message);
  }
  by("listen").onclick = async () => {
    if (reader) { stopReading("Lecture arrêtée."); return; }
    if (!capable || active || state() !== "setup") return;
    const s = reader = {abort:new AbortController(),playing:new Set(),cursor:0};
    text("listen","Arrêter la lecture"); text("listen-status","Ouverture de la lecture…");
    const failed = () => { if (reader === s) stopReading("Lecture indisponible. Vous pouvez commencer la préparation sans l’écouter."); };
    s.watchdog = setTimeout(failed,120000);
    try {
      s.audio = new Audio(); await s.audio.resume();
      if (reader !== s) return;
      const response = await tokenRequest(s,true);
      if (reader !== s) return;
      if (!response.ok) { failed(); return; }
      const config = await socketConfig(response);
      if (reader !== s) return;
      const socket = openSocket(s,config);
      socket.onerror = socket.onclose = failed;
      socket.onmessage = e => {
        if (reader !== s) return;
        try {
          const msg = JSON.parse(typeof e.data === "string" ? e.data : new TextDecoder().decode(e.data));
          if (msg.error || msg.goAway) { failed(); return; }
          if (msg.setupComplete) {
            text("listen-status","Lecture en français · micro coupé, chronomètre arrêté.");
            socket.send(JSON.stringify({clientContent:{turns:[{role:"user",parts:[{text:"Lisez la consigne."}]}],turnComplete:true}}));
          }
          const turn = msg.serverContent;
          for (const part of turn?.modelTurn?.parts || []) if (part.inlineData?.mimeType?.startsWith("audio/pcm")) play(s,part.inlineData.data);
          if (turn?.turnComplete) {
            if (!s.cursor) { failed(); return; }
            closeSocket(s);
            s.timer = setTimeout(() => { if (reader === s) stopReading("Lecture terminée. Commencez la préparation quand vous êtes prêt."); },
              Math.max(0,(s.cursor-s.audio.currentTime)*1000));
          }
        } catch { failed(); }
      };
    } catch (error) {
      if (reader === s && error.name === "AbortError") stopReading("Lecture annulée.");
      else failed();
    }
  };
  async function connect(s) {
    if (!owns(s) || state() !== "prep") return;
    clearTimeout(s.timer); phase("connecting","Connexion"); display(live);
    by("notepad").open = false; text("status","Connexion en cours. Le micro reste coupé.");
    s.watchdog = setTimeout(() => finish(s,"Le délai d’autorisation a expiré. Le micro reste coupé."),120000);
    try {
      const response = await tokenRequest(s);
      if (!owns(s)) return;
      if (!response.ok) {
        finish(s,response.status === 429 ? "Limite de tentatives atteinte. Utilisez le simulateur guidé ou réessayez plus tard." :
          "Gemini Live est indisponible pour cette séance. Vous pouvez revenir au simulateur guidé."); return;
      }
      const config = await socketConfig(response); if (!owns(s)) return;
      text("status","Autorisez le micro. Votre voix n’est pas envoyée avant l’ouverture de la séance.");
      clearTimeout(s.watchdog);
      s.watchdog = setTimeout(() => finish(s,"La connexion n’a pas abouti. Aucun nouvel essai automatique."),30000);
      const stream = await navigator.mediaDevices.getUserMedia({video:false,audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});
      if (!owns(s)) { stream.getTracks().forEach(t => t.stop()); return; }
      s.stream = stream;
      stream.getAudioTracks().forEach(t => { t.enabled = false; t.onended = () => finish(s,"Le microphone s’est déconnecté."); });
      const socket = openSocket(s,config);
      socket.onmessage = e => receive(s,e.data);
      socket.onerror = socket.onclose = () => finish(s,"Connexion vocale interrompue ou quota indisponible. Le micro est coupé.");
    } catch (error) {
      if (owns(s)) finish(s,error.name === "AbortError" ? "Ouverture annulée. Aucun appel n’est en cours." :
        error.name === "NotAllowedError" ? "Micro refusé. Autorisez-le dans votre navigateur pour participer." : "Impossible d’ouvrir le micro ou la connexion vocale.");
    }
  }
  function setup() {
    review.clear(); delete root.dataset.ending; delete root.dataset.mic;
    phase("setup","Avant la simulation"); display(prep); text("status",capable ? "" : "Ce navigateur ne permet pas l’appel vocal. Essayez un navigateur récent en HTTPS.");
    text("title",initialTitle); text("prompt",introduction);
    stopReading();
    by("start").disabled = by("listen").disabled = !capable; by("captions").open = false;
  }
  by("start").onclick = async () => {
    if (!capable || active || state() !== "setup") return;
    stopReading();
    const s = active = {abort:new AbortController(),playing:new Set(),rows:[],partial:{},cursor:0};
    phase("loading","Installation"); text("status","Vérification de la lecture audio ; le micro reste coupé.");
    try {
      s.audio = new Audio(); await s.audio.resume();
      if (!owns(s)) return;
      await s.audio.audioWorklet.addModule(root.dataset.worklet);
      if (!owns(s)) return;
      s.began = stamp(); s.duration = prep; phase("prep","Préparation"); by("notepad").open = true;
      text("title",root.dataset.scenarioTitle);
      text("prompt",root.dataset.scenarioPrompt);
      text("status","Micro coupé · votre PIN audio sera demandé avant l’échange."); tick(s); by("title").focus();
    } catch { if (owns(s)) finish(s,"La lecture audio n’est pas disponible dans ce navigateur."); }
  };
  by("skip").onclick = () => { if (active) connect(active); };
  by("mute").onclick = () => {
    const s = active; if (!s || !running(s)) return;
    if (!s.capture) { startMic(s); return; }
    cutMic(s); if (s.sock.readyState === WebSocket.OPEN) s.sock.send(JSON.stringify({realtimeInput:{audioStreamEnd:true}}));
    text("mute","Rouvrir le micro"); by("mute").setAttribute("aria-pressed","true"); text("status","Micro coupé. Aucun son n’est envoyé.");
  };
  by("end").onclick = () => { if (active) finish(active,"Vous avez mis fin à la séance.","normal"); };
  by("retry").onclick = () => { setup(); by("title").focus(); };
  document.addEventListener("visibilitychange",() => {
    if (document.hidden && reader) stopReading("Lecture arrêtée.");
    if (document.hidden && active) finish(active,"Séance fermée : vous avez quitté l’onglet.");
  });
  window.addEventListener("pagehide",() => { if (active) finish(active,"Séance fermée."); setup(); });
  // Keep the session timeline below the site's sticky navigation.
  const nav = document.querySelector(".nav");
  const pin = () => root.style.setProperty("--lv-top",`${nav ? Math.round(nav.getBoundingClientRect().height) : 0}px`);
  window.addEventListener("resize",pin); pin();
  setup();
})();
