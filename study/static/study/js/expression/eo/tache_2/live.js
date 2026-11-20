(() => {
  "use strict";
  const root = document.getElementById("live-studio");
  const by = id => document.getElementById("lv-" + id);
  if (!root || !by("consent")) return;
  const text = (id, value) => { by(id).textContent = value; };
  const show = (id, visible) => { by(id).hidden = !visible; };
  const wsURL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained";
  const Audio = window.AudioContext || window.webkitAudioContext;
  const capable = Boolean(window.isSecureContext && navigator.mediaDevices?.getUserMedia && Audio && window.AudioWorkletNode);
  const prep = 120000, live = 210000;
  let active;
  const state = () => root.dataset.state;
  const owns = s => active === s;
  function phase(next, label) {
    root.dataset.state = next;
    for (const id of ["setup","prep","done"]) show(id,next === id);
    show("call",next === "connecting" || next === "live");
    show("notepad",["prep","connecting","live"].includes(next));
    show("mute",next === "live"); show("end",!["setup","done"].includes(next));
    text("phase",label);
  }
  function stamp() { return {wall:Date.now(),mono:performance.now()}; }
  function left(s) {
    return s.duration - Math.max(0,Date.now()-s.began.wall,performance.now()-s.began.mono);
  }
  function display(ms) {
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
  }
  function finish(s, message) {
    if (!owns(s)) return;
    active = null; clearTimeout(s.timer); clearTimeout(s.watchdog); s.abort.abort();
    cutMic(s); cutSound(s);
    s.stream?.getTracks().forEach(t => { t.onended = null; t.stop(); });
    if (s.sock) {
      s.sock.onmessage = s.sock.onopen = s.sock.onclose = s.sock.onerror = null;
      s.sock.close();
    }
    if (s.audio && s.audio.state !== "closed") s.audio.close();
    phase("done","Séance terminée"); text("label","Fin de l’échange"); text("title","L’appel est fermé.");
    text("prompt","Aucun enregistrement ni historique de cet échange n’est conservé par Heureux."); text("status",message);
    text("user-words","—"); text("ai-words","—"); by("consent").checked = false; by("notes").value = "";
  }
  function running(s) {
    if (!owns(s) || state() !== "live") return false;
    if (left(s) <= 0) { display(0); finish(s,"Les 3 min 30 sont écoulées."); return false; }
    return true;
  }
  function tick(s) {
    clearTimeout(s.timer); if (!owns(s)) return;
    const ms = left(s); display(ms);
    if (ms <= 0) {
      if (state() === "prep" && ms > -live && !document.hidden) connect(s);
      else finish(s,"Le temps est écoulé.");
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
    text("mute","Couper le micro"); by("mute").setAttribute("aria-pressed","false");
    text("status","Micro ouvert. Parlez naturellement ; vous pouvez interrompre la réponse.");
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
  function caption(s, id, piece) {
    if (!piece || typeof piece.text !== "string") return;
    const prefix = s.captions[id] || "";
    s.captions[id] = (prefix+piece.text).slice(-1600); text(id,s.captions[id]);
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
      if (turn.interrupted) { cutSound(s); s.captions = {}; }
      caption(s,"user-words",turn.inputTranscription); caption(s,"ai-words",turn.outputTranscription);
      if (!turn.interrupted) for (const part of turn.modelTurn?.parts || []) {
        if (part.inlineData?.mimeType?.startsWith("audio/pcm")) play(s,part.inlineData.data);
      }
      if (turn.turnComplete) s.captions = {};
    } catch { finish(s,"Réponse vocale illisible. La connexion et le micro ont été fermés."); }
  }
  async function connect(s) {
    if (!owns(s) || state() !== "prep") return;
    clearTimeout(s.timer); phase("connecting","Connexion"); display(live);
    text("status","Autorisez cette séance avec le PIN audio. Le micro reste coupé.");
    s.watchdog = setTimeout(() => finish(s,"Le délai d’autorisation a expiré. Le micro reste coupé."),120000);
    try {
      const response = await window.HeureuxAudioRequest(root.dataset.tokenUrl,{method:"POST",credentials:"same-origin",mode:"same-origin",cache:"no-store",
        headers:{"Content-Type":"application/json","X-CSRFToken":root.querySelector('[name="csrfmiddlewaretoken"]').value},
        body:JSON.stringify({consent:true}),signal:s.abort.signal},{
        title:"Autoriser la conversation Gemini Live",
        description:"Utilisez le PIN audio ElevenLabs. Il est vérifié par Heureux et n’est pas envoyé à Google. Cet appel ne génère pas d’enregistrement ElevenLabs.",
        action:"Autoriser cette conversation"
      });
      if (!owns(s)) return;
      if (!response.ok) {
        finish(s,response.status === 429 ? "Limite de tentatives atteinte. Utilisez le simulateur guidé ou réessayez plus tard." :
          "Gemini Live est indisponible pour cette séance. Vous pouvez revenir au simulateur guidé."); return;
      }
      const {token,model} = await response.json(); if (!owns(s)) return;
      if (typeof token !== "string" || !token.startsWith("auth_tokens/") || model !== "models/gemini-3.8-live") throw new Error("Configuration invalide");
      text("status","Autorisez le micro. Votre voix n’est pas envoyée avant l’ouverture de la séance.");
      clearTimeout(s.watchdog);
      s.watchdog = setTimeout(() => finish(s,"La connexion n’a pas abouti. Aucun nouvel essai automatique."),30000);
      const stream = await navigator.mediaDevices.getUserMedia({video:false,audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});
      if (!owns(s)) { stream.getTracks().forEach(t => t.stop()); return; }
      s.stream = stream;
      stream.getAudioTracks().forEach(t => { t.enabled = false; t.onended = () => finish(s,"Le microphone s’est déconnecté."); });
      const socket = s.sock = new WebSocket(`${wsURL}?access_token=${encodeURIComponent(token)}`);
      socket.binaryType = "arraybuffer";
      socket.onopen = () => { if (owns(s)) socket.send(JSON.stringify({setup:{model,generationConfig:{responseModalities:["AUDIO"]},inputAudioTranscription:{},outputAudioTranscription:{}}})); };
      socket.onmessage = e => receive(s,e.data);
      socket.onerror = socket.onclose = () => finish(s,"Connexion vocale interrompue ou quota indisponible. Le micro est coupé.");
    } catch (error) {
      if (owns(s)) finish(s,error.name === "AbortError" ? "Ouverture annulée. Aucun appel n’est en cours." :
        error.name === "NotAllowedError" ? "Micro refusé. Autorisez-le dans votre navigateur pour participer." : "Impossible d’ouvrir le micro ou la connexion vocale.");
    }
  }
  function setup() {
    phase("setup","Avant la simulation"); display(prep); text("status",capable ? "" : "Ce navigateur ne permet pas l’appel vocal. Essayez un navigateur récent en HTTPS.");
    text("label","L’interaction"); text("title","C’est vous qui menez l’échange.");
    text("prompt","La consigne apparaît au début de la préparation. L’interlocuteur est une IA.");
    by("consent").checked = false; by("start").disabled = true; by("captions").open = false;
  }
  by("consent").onchange = () => { by("start").disabled = !capable || !by("consent").checked; };
  by("start").onclick = async () => {
    if (!capable || active || !by("consent").checked) return;
    const s = active = {abort:new AbortController(),playing:new Set(),captions:{},cursor:0};
    phase("loading","Installation"); text("status","Vérification de la lecture audio ; le micro reste coupé.");
    try {
      s.audio = new Audio(); await s.audio.resume();
      if (!owns(s)) return;
      await s.audio.audioWorklet.addModule(root.dataset.worklet);
      if (!owns(s)) return;
      s.began = stamp(); s.duration = prep; phase("prep","Préparation"); text("label","Votre consigne");
      text("title",root.dataset.scenarioTitle);
      text("prompt",root.dataset.scenarioPrompt);
      text("status","Micro coupé. Aucun son n’est transmis."); tick(s); by("title").focus();
    } catch { if (owns(s)) finish(s,"La lecture audio n’est pas disponible dans ce navigateur."); }
  };
  by("skip").onclick = () => { if (active) connect(active); };
  by("mute").onclick = () => {
    const s = active; if (!s || !running(s)) return;
    if (!s.capture) { startMic(s); return; }
    cutMic(s); if (s.sock.readyState === WebSocket.OPEN) s.sock.send(JSON.stringify({realtimeInput:{audioStreamEnd:true}}));
    text("mute","Rouvrir le micro"); by("mute").setAttribute("aria-pressed","true"); text("status","Micro coupé. Aucun son n’est envoyé.");
  };
  by("end").onclick = () => { if (active) finish(active,"Vous avez mis fin à la séance."); };
  by("retry").onclick = setup;
  document.addEventListener("visibilitychange",() => { if (document.hidden && active) finish(active,"Séance fermée : vous avez quitté l’onglet."); });
  window.addEventListener("pagehide",() => { if (active) finish(active,"Séance fermée."); setup(); });
  setup();
})();
