/* A single clock covers both sides of the interview, including repeats. */
(() => {
  "use strict";
  const root = document.getElementById("eo1-interview");
  if (!root) return;
  const by = id => document.getElementById("eo-" + id);
  const engine = window.HeureuxEO1Engine;
  const reviewer = window.HeureuxEO1Review;
  if (!engine || !reviewer) {
    by("setup-status").textContent = "Le studio n’a pas pu être chargé. Rechargez la page pour réessayer.";
    return;
  }
  const localModel = window.HeureuxEO1LocalExaminer;
  const speech = window.HeureuxFrenchSpeech;
  const Recognition = window.isSecureContext && (window.SpeechRecognition || window.webkitSpeechRecognition);
  const modes = [...root.querySelectorAll('[name="eo-mode"]')];
  const duration = 120;
  let state = "setup", mode, ready = false, started, startedWall, tick, turns = [], question = "";
  let recognition, silence, watchdog, preflightTimer, speaker, version = 0, pendingCheck = false;
  let inference, localPrompt = false, modelReady = false;
  let draft = "", interim = "", savedDraft = "", spoken = false, waiting = false, listening = false;

  function show(id, visible) { by(id).hidden = !visible; }
  function text(id, value) { by(id).textContent = value; }
  function setState(value) { root.dataset.state = state = value; }
  function timeLabel(seconds) {
    return [Math.floor(seconds / 60), seconds % 60].map(n => String(n).padStart(2, "0")).join(":");
  }
  function elapsed() {
    // performance.now is monotonic; the wall clock also advances during device sleep.
    return Math.max(performance.now() - started, Date.now() - startedWall, 0) / 1000;
  }
  function remaining() { return Math.max(0, duration - Math.floor(elapsed())); }
  function alive() {
    if (state !== "live") return false;
    if (elapsed() < duration) return true;
    finish(false);
    return false;
  }
  function paintTime() {
    clearTimeout(tick);
    if (!alive()) return;
    const spent = elapsed();
    text("clock", timeLabel(Math.max(0, duration - Math.floor(spent))));
    by("progress").value = spent;
    tick = setTimeout(paintTime, Math.max(1, Math.ceil((Math.floor(spent) + 1 - spent) * 1000)));
  }
  function endRecognition() {
    clearTimeout(silence);
    const r = recognition;
    recognition = null;
    listening = false;
    if (r) {
      r.onstart = r.onend = r.onerror = r.onresult = r.onspeechstart = null;
      try { r.abort(); } catch (error) {
        if (error.name !== "InvalidStateError") throw error;
      }
    }
  }
  function hush() {
    clearTimeout(watchdog);
    if (speaker) {
      speaker.onend = speaker.onerror = null;
      speaker = null;
      speech.synthesis.cancel();
    }
  }
  function setup() {
    setState("setup");
    show("setup", true); show("live", false); show("done", false); show("review", false);
    by("review").open = false;
    by("transcript").replaceChildren(); clearReport(); text("summary", "");
    root.querySelector(".eo-scale").open = false;
    turns = []; question = ""; draft = ""; interim = ""; savedDraft = "";
    by("answer").value = ""; text("dictation", "");
    text("clock", "02:00"); by("progress").value = 0;
    text("phase", "Avant l’entretien"); text("speaker", "Votre examinateur");
    text("question", "À vous la parole.");
    text("console-note", "La première question arrive au démarrage. Il n’y a pas de temps de préparation.");
    chooseMode();
  }
  function chooseMode() {
    clearTimeout(preflightTimer); endRecognition(); pendingCheck = false;
    mode = modes.find(r => r.checked).value;
    show("ai-option", modelReady && mode !== "oral");
    text("setup-status", "");
    text("privacy", mode === "voice"
      ? "Avec votre accord, le service de dictée du navigateur peut traiter votre voix en ligne. Heureux ne conserve ni audio ni transcription."
      : "Micro coupé. Vos échanges restent dans cet onglet, uniquement pour cette séance.");
    text("start", mode === "voice" && !ready ? "Vérifier le micro" : "Commencer l’entretien");
    by("start").disabled = false;
  }
  function micError(code) {
    if (["not-allowed", "service-not-allowed"].includes(code)) return "Accès au micro refusé.";
    if (code === "audio-capture") return "Aucun microphone accessible.";
    if (code === "network") return "Le service de dictée est indisponible.";
    if (code === "language-not-supported") return "La dictée en français n’est pas disponible.";
    return "La dictée n’a pas pu démarrer.";
  }
  function checkMic() {
    if (pendingCheck) return;
    pendingCheck = true; by("start").disabled = true;
    text("setup-status", "Autorisez le micro dans votre navigateur. Le chronomètre n’a pas démarré.");
    let r;
    function checked(ok, reason) {
      if (!pendingCheck) return;
      pendingCheck = false; ready = ok; chooseMode();
      text("setup-status", ok ? "Micro disponible et coupé. Commencez quand vous êtes prêt." :
        `${reason} Réessayez ou choisissez un mode sans micro.`);
    }
    try {
      r = recognition = new Recognition();
      r.lang = "fr-FR";
      r.onstart = () => checked(true);
      r.onerror = e => checked(false, micError(e.error));
      r.onend = () => checked(false, "Vérification interrompue.");
      preflightTimer = setTimeout(() => checked(false, "Le navigateur n’a pas répondu."), 20000);
      r.start();
    } catch { checked(false, "Impossible de vérifier le micro."); }
  }
  function start() {
    if (state !== "setup") return;
    if (mode === "voice" && !ready) { checkMic(); return; }
    started = performance.now(); startedWall = Date.now(); setState("live");
    show("setup", false); show("done", false); show("live", true); show("confirm", false);
    text("phase", "En entretien"); turns = []; waiting = false;
    paintTime();
    by("question").focus({preventScroll:true});
    present(engine.opening());
  }
  function present(line, generated = false) {
    localPrompt = generated;
    question = line; draft = ""; interim = ""; savedDraft = ""; by("answer").value = "";
    text("dictation", ""); text("question", line); text("speaker", "Examinateur");
    text("turn-number", `Échange ${String(turns.length + 1).padStart(2, "0")}`);
    text("console-note", "Le temps de l’échange inclut la question.");
    playQuestion();
  }
  function playQuestion() {
    if (!alive() || waiting) return;
    draft = [draft, interim].filter(Boolean).join(" "); interim = ""; version++;
    endRecognition(); hush(); spoken = false;
    controls(); text("live-status", "Écoutez la question ou lisez-la à l’écran.");
    if (document.hidden || !by("voiced").checked || !speech?.supported) { openTurn(); return; }
    const id = version;
    const u = speaker = new speech.Utterance(question);
    u.lang = "fr-FR"; u.rate = 1;
    speech.refreshVoices();
    // A generated follow-up may refer to a personal answer. Never send it to a remote voice.
    const voice = speech.preferredVoice(localPrompt);
    if (localPrompt && !voice) {
      speaker = null; openTurn("Pas de voix française locale : lisez la relance à l’écran. "); return;
    }
    if (voice) u.voice = voice;
    const done = failed => {
      if (id !== version || speaker !== u || !alive()) return;
      hush(); openTurn(failed ? "La voix de lecture est indisponible. Lisez la question à l’écran. " : "");
    };
    u.onend = () => done(false); u.onerror = () => done(true);
    // Some mobile engines drop utterances without ever reporting an end or error.
    watchdog = setTimeout(() => done(true), Math.min(12000, 2500 + question.length * 80));
    document.dispatchEvent(new CustomEvent("heureux:speech-start", {detail:{source:"eo1-interview"}}));
    try { speech.synthesis.speak(u); } catch { done(true); }
  }
  function openTurn(notice = "") {
    if (!alive()) return;
    spoken = true; controls();
    const help = mode === "text" ? "Écrivez votre réponse, puis envoyez-la." :
      mode === "oral" ? "Répondez à voix haute. Indiquez quand vous souhaitez une relance ; le micro reste coupé." :
      "Parlez naturellement. Une courte pause en fin de réponse laisse la parole à l’examinateur.";
    text("live-status", notice + help);
    if (mode === "voice") listen();
    if (mode === "text") by("answer").focus({preventScroll:true});
  }
  function controls() {
    const active = spoken && !waiting;
    show("text-area", mode === "text" && active);
    show("dictation", mode === "voice" && active && Boolean(draft || interim));
    show("keyboard", mode !== "text" && !waiting); show("no-mic", mode === "voice" && !waiting);
    by("repeat").disabled = waiting;
    by("submit").disabled = waiting || !spoken || (mode === "text" && !by("answer").value.trim())
      || (mode === "voice" && !draft && !interim && listening);
    text("submit", mode === "text" ? "Envoyer ma réponse" :
      mode === "voice" && !listening && !draft && !interim ? "Ouvrir le micro" : "J’ai terminé ma réponse");
  }
  function listen() {
    if (!alive() || recognition || mode !== "voice" || document.hidden) return;
    const id = version;
    let r;
    const current = () => recognition === r && id === version && alive();
    const schedule = () => {
      clearTimeout(silence);
      if (draft && !interim) silence = setTimeout(() => {
        if (id === version && mode === "voice" && alive()) send();
      }, 3000);
    };
    function failed(reason) {
      draft = [draft, interim].filter(Boolean).join(" "); interim = "";
      endRecognition(); controls();
      text("live-status", `${reason} Vous pouvez rouvrir le micro ou continuer sans dictée.`);
    }
    try {
      r = recognition = new Recognition();
      r.lang = "fr-FR"; r.continuous = true; r.interimResults = true;
      savedDraft = draft;
      r.onstart = () => { if (current()) { listening = true; controls(); } };
      r.onspeechstart = () => { if (current()) clearTimeout(silence); };
      r.onresult = event => {
        if (!current()) return;
        const finals = [], partials = [];
        for (const result of Array.from(event.results)) {
          (result.isFinal ? finals : partials).push(result[0].transcript.trim());
        }
        draft = [savedDraft, ...finals].filter(Boolean).join(" ");
        interim = partials.join(" "); text("dictation", [draft, interim].filter(Boolean).join(" "));
        controls(); schedule();
      };
      r.onerror = e => {
        if (current()) failed(e.error === "no-speech" ? "Aucune parole détectée." : micError(e.error));
      };
      r.onend = () => {
        if (!current()) return;
        recognition = null; listening = false;
        if (interim) { draft = [draft, interim].filter(Boolean).join(" "); interim = ""; }
        controls();
        if (draft) schedule();
        else text("live-status", "Micro en veille. Rouvrez-le quand vous êtes prêt à répondre.");
      };
      r.start(); listening = true; controls();
    } catch { failed("Le micro n’est pas disponible."); }
  }
  function answer() {
    return (mode === "text" ? by("answer").value : [draft, interim].filter(Boolean).join(" ")).trim();
  }
  function record(value) {
    // A turn switched to no-mic can still carry words dictated before that switch.
    turns.push({question, answer:value, mode:mode === "oral" && value ? "voice" : mode});
  }
  async function send() {
    if (!alive() || waiting || !spoken) return;
    const value = answer();
    if (!value && mode !== "oral") {
      if (mode === "voice") listen();
      return;
    }
    record(value); version++; endRecognition();
    if (remaining() <= 8) {
      waiting = true; question = ""; draft = ""; interim = ""; by("answer").value = ""; controls();
      text("question", "Merci pour cet échange."); text("live-status", "L’entretien touche à sa fin.");
      return;
    }
    if (!modelReady || !by("ai").checked || !value || mode === "oral") {
      present(engine.next(turns, remaining())); return;
    }
    const request = inference = new AbortController();
    waiting = true; question = ""; draft = ""; interim = ""; by("answer").value = "";
    controls(); text("live-status", "L’examinateur prépare sa relance sur cet appareil.");
    let timer, line;
    try {
      line = await Promise.race([
        localModel.followup(turns, request.signal),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Délai dépassé")), 1800); }),
      ]);
    } catch {
      if (inference === request) {
        by("ai").checked = false;
        text("phase", "En entretien · relances guidées");
      }
    } finally { clearTimeout(timer); request.abort(); }
    if (inference !== request || !alive()) return;
    inference = null;
    if (remaining() <= 8) {
      text("question", "Merci pour cet échange."); text("live-status", "L’entretien touche à sa fin.");
      return;
    }
    waiting = false;
    present(line || engine.next(turns, remaining()), Boolean(line));
  }
  function switchMode(nextMode) {
    if (!alive() || waiting) return;
    const value = answer();
    version++; endRecognition(); hush(); mode = nextMode;
    draft = value; interim = ""; by("answer").value = value;
    openTurn("Micro coupé. ");
  }
  function finish(early) {
    if (state !== "live") return;
    const seconds = early ? Math.min(duration, Math.floor(elapsed())) : duration;
    const value = answer();
    if (question && value) record(value);
    inference?.abort(); inference = null;
    setState("done"); version++; clearTimeout(tick); endRecognition(); hush();
    show("live", false); show("done", true); show("confirm", false);
    text("clock", timeLabel(duration - seconds)); by("progress").value = seconds;
    text("phase", early ? "Arrêt anticipé" : "Temps écoulé"); text("speaker", "Fin de la séance");
    text("question", "Merci, l’entretien est terminé.");
    text("console-note", "Le micro est coupé. Prenez un instant pour revenir sur vos réponses.");
    const hasWords = turns.some(t => t.answer);
    text("summary", `${early ? "Entretien arrêté" : "Entretien terminé"} à ${timeLabel(seconds)}. ` +
      (hasWords ? "Relisez vos réponses avant de voir les corrections et le repère de niveau."
        : "Aucune réponse transcrite pour cette séance."));
    by("transcript").replaceChildren();
    turns.forEach((t, i) => appendTranscript(t, i));
    show("review", turns.length > 0); show("read", hasWords); show("analyze", hasWords);
    show("review-help", turns.some(t => t.mode === "voice" && t.answer));
    if (!hasWords) renderReport();
    text("dictation", ""); by("answer").value = ""; by("done-title").focus();
  }
  function el(tag, value) {
    const node = document.createElement(tag); node.textContent = value; return node;
  }
  function appendTranscript(t, i) {
    const item = el("li", ""); by("transcript").append(item); item.append(el("strong", t.question));
    if (!t.answer) { item.append(el("p", "Réponse orale non transcrite.")); return; }
    const label = t.mode === "voice" ? "Dictée d’origine" : "Réponse au clavier";
    item.append(el("small", label), el("p", t.answer));
    if (t.mode !== "voice") return;
    const id = `eo-verified-${i}`, field = el("textarea", ""), caption = el("label", `Ce que j’ai dit · échange ${i + 1}`);
    caption.htmlFor = field.id = id; caption.className = "eo-field-label";
    field.value = t.answer; field.rows = 2; field.maxLength = Math.max(1600, t.answer.length);
    field.autocomplete = "off"; field.addEventListener("input", clearReport);
    item.append(caption, field);
  }
  function clearReport() {
    show("report", false);
    ["basis", "band", "band-reason", "correction-note", "feedback", "evidence", "corrections"].forEach(id => by(id).replaceChildren());
  }
  function renderReport() {
    clearReport();
    const reviewed = turns.map((t, i) => ({...t, answer:by(`verified-${i}`)?.value.trim() ?? t.answer}));
    const result = reviewer.assess(reviewed);
    const hasWords = reviewed.some(t => t.answer);
    const edited = turns.some((t, i) => t.answer !== reviewed[i].answer);
    text("basis", !hasWords ? "Aucun texte à analyser. Parlez au micro ou essayez le clavier pour obtenir un retour sur vos mots." :
      (result.typed ? "Ce retour inclut du texte saisi au clavier ; il ne situe pas votre prestation orale." :
        "Ce retour porte sur vos mots, pas sur votre voix.") +
      (edited ? " Les passages rectifiés par vous remplacent la dictée pour cette analyse." : ""));
    text("band", result.band || "Données insuffisantes");
    text("band-reason", result.reason);
    result.evidence.forEach(e => appendItem("evidence", `${e.what} · échange ${e.turn}`, `« ${e.quote} »`));
    text("correction-note", result.corrections.length ? "Quelques formulations à reprendre, à partir de vos mots :" :
      hasWords ? "Aucune correction certaine parmi les tournures vérifiées. Cela ne veut pas dire que tout est correct." : "Pas de correction sans exemple.");
    result.corrections.forEach(c => {
      const item = el("li", ""); item.append(el("small", `Échange ${c.turn}`),
        el("p", `Vos mots : « ${c.before} »`), el("strong", `À dire : « ${c.after} »`), el("p", c.why));
      by("corrections").append(item);
    });
    const notes = engine.feedback(reviewed);
    notes.forEach(item => appendItem("feedback", item.title, item.detail));
    show("coaching", notes.length > 0); show("report", true);
  }
  function appendItem(container, title, detail) {
    const li = document.createElement("li"), strong = document.createElement("strong");
    strong.textContent = title; li.append(strong, document.createTextNode(detail)); by(container).append(li);
  }
  modes[0].disabled = !Recognition;
  if (Recognition) modes[0].checked = true;
  else text("voice-hint", "Dictée indisponible dans ce navigateur.");
  if (!speech?.supported) { by("voiced").checked = false; by("voiced").disabled = true; }
  modes.forEach(r => r.addEventListener("change", chooseMode));
  by("start").addEventListener("click", start);
  by("submit").addEventListener("click", send);
  by("answer").addEventListener("input", controls);
  by("repeat").addEventListener("click", playQuestion);
  by("keyboard").addEventListener("click", () => switchMode("text"));
  by("no-mic").addEventListener("click", () => switchMode("oral"));
  by("stop").addEventListener("click", () => { if (alive()) { show("confirm", true); by("keep").focus(); } });
  by("keep").addEventListener("click", () => { show("confirm", false); by("stop").focus(); });
  by("finish").addEventListener("click", () => { if (alive()) finish(true); });
  by("read").addEventListener("click", () => {
    by("review").open = true; by("review").querySelector("summary").focus();
  });
  by("analyze").addEventListener("click", () => {
    renderReport(); by("report-title").focus();
  });
  by("retry").addEventListener("click", () => { ready = false; setup(); by("start").focus(); });
  document.addEventListener("visibilitychange", () => {
    if (state === "setup" && pendingCheck && document.hidden) chooseMode();
    if (!alive()) return;
    if (document.hidden) {
      draft = [draft, interim].filter(Boolean).join(" "); interim = "";
      version++; endRecognition(); hush(); spoken = true; controls();
      text("live-status", "Micro coupé. Le chronomètre continue.");
    } else paintTime();
  });
  window.addEventListener("pagehide", () => {
    inference?.abort(); inference = null;
    version++; clearTimeout(tick); endRecognition(); hush();
    ready = false; setup();
  });
  setup();
  localModel?.available().then(available => {
    modelReady = available;
    show("ai-option", available && state === "setup" && mode !== "oral");
  }).catch(() => { show("ai-option", false); });
})();
