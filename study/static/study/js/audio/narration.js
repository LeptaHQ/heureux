/* Browser speech for shared read-aloud, selected-text and comprehension controls. */
(function () {
  "use strict";
  var speech = window.HeureuxFrenchSpeech;
  var panel = document.querySelector("[data-narrator]");
  if (!panel || !speech) return;
  var status = panel.querySelector("[data-narrator-status]");
  var toggle = panel.querySelector("[data-narrator-toggle]");
  var speed = panel.querySelector("[data-narrator-speed]");
  var privacy = panel.querySelector("[data-narrator-privacy]");
  var current = null;
  var rate = 0.85;
  var rates = [0.75, 0.85, 1, 1.25, 1.5, 1.75, 2];

  function normalize(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function nodeText(node) {
    if (node.dataset.readAloudValue) return normalize(node.dataset.readAloudValue);
    var copy = node.cloneNode(true);
    copy.querySelectorAll("br").forEach(function (br) { br.replaceWith(" "); });
    return normalize(copy.textContent);
  }

  function visible(node) {
    if (!node || !node.isConnected ||
        node.closest(".hidden, [hidden], [aria-hidden='true'], [inert]")) return false;
    var ancestor = node.parentElement;
    while (ancestor) {
      if (ancestor.tagName === "DETAILS" && !ancestor.open) return false;
      ancestor = ancestor.parentElement;
    }
    return true;
  }

  function message(text) {
    status.textContent = text;
    if (current && current.options.onstatus) current.options.onstatus(text);
  }

  function state(value) {
    if (!current) return;
    current.state = value;
    toggle.textContent = value === "playing" ? "Pause" :
      (value === "error" ? "Réessayer" : "Lecture");
    toggle.disabled = value === "loading";
    if (current.options.onstate) current.options.onstate(value);
  }

  function clearVoiceWait(item) {
    if (!item) return;
    clearTimeout(item.voiceTimer);
    item.waitingForVoice = false;
  }

  function stop(hide) {
    var previous = current;
    current = null;
    clearVoiceWait(previous);
    if (speech.supported && previous) {
      previous.utteranceId += 1;
      speech.synthesis.cancel();
      speech.synthesis.resume();
    }
    if (previous && previous.options.onstop) previous.options.onstop();
    if (hide) panel.hidden = true;
  }

  function failed(text) {
    if (!current) return;
    clearVoiceWait(current);
    state("error");
    message(text);
    if (current.options.onerror) current.options.onerror();
  }

  function ended() {
    if (!current) return;
    state("ended");
    message("Lecture terminée.");
    if (current.options.onend) current.options.onend();
  }

  function speakNext() {
    if (!current || current.state !== "playing") return;
    if (current.index >= current.parts.length) { ended(); return; }
    var item = current;
    var id = ++item.utteranceId;
    var utterance = new speech.Utterance(item.parts[item.index]);
    utterance.lang = "fr-FR";
    utterance.rate = rate;
    utterance.pitch = 1;
    if (item.voice) utterance.voice = item.voice;
    utterance.onend = function () {
      if (current !== item || item.utteranceId !== id || item.state !== "playing") return;
      item.index += 1;
      speakNext();
    };
    utterance.onerror = function () {
      if (current !== item || item.utteranceId !== id || item.state !== "playing") return;
      failed("Lecture indisponible. Vérifiez la voix de l’appareil.");
    };
    item.utterance = utterance;
    try { speech.synthesis.speak(utterance); }
    catch (error) { failed("Lecture indisponible. Vérifiez la voix de l’appareil."); }
  }

  function beginDevice(item) {
    if (current !== item) return;
    clearVoiceWait(item);
    speech.refreshVoices();
    item.voice = speech.preferredVoice(item.private);
    if (item.private && !item.voice) {
      failed("Aucune voix française locale disponible. Activez ou installez une voix française de l’appareil pour lire ce texte privé.");
      return;
    }
    state("playing");
    message("Voix du navigateur ou de l’appareil" + (item.voice ? " · " + item.voice.name : "") +
      (item.private ? " · texte privé non transmis pour la lecture." : ""));
    speakNext();
  }

  function device() {
    if (!current) return;
    var item = current;
    clearVoiceWait(item);
    if (!speech.supported) {
      failed("La voix de l’appareil est indisponible dans ce navigateur.");
      return;
    }
    item.utteranceId += 1;
    speech.synthesis.cancel();
    speech.synthesis.resume();
    item.index = 0;
    speech.refreshVoices();
    if (item.private && !speech.preferredVoice(true) && !speech.synthesis.getVoices().length) {
      item.waitingForVoice = true;
      state("loading");
      message("Chargement de la voix française de l’appareil…");
      item.voiceTimer = setTimeout(function () { beginDevice(item); }, 1500);
      return;
    }
    beginDevice(item);
  }

  if (speech.supported && speech.synthesis.addEventListener) {
    speech.synthesis.addEventListener("voiceschanged", function () {
      if (!current || !current.waitingForVoice) return;
      speech.refreshVoices();
      if (speech.preferredVoice(true)) beginDevice(current);
    });
  }

  function setRate(value) {
    value = Number(value);
    if (rates.indexOf(value) === -1) return;
    rate = value;
    speed.value = String(value);
    document.dispatchEvent(new CustomEvent("heureux:narration-rate", { detail: { rate: value } }));
    if (current && current.state === "playing") {
      current.utteranceId += 1;
      speech.synthesis.cancel();
      speech.synthesis.resume();
      speakNext();
    }
  }

  function pause() {
    if (!current || current.state !== "playing") return;
    current.utteranceId += 1;
    speech.synthesis.cancel();
    speech.synthesis.resume();
    state("paused");
    message("Lecture en pause.");
  }

  function resume() {
    if (!current) return;
    if (current.state === "error") { device(); return; }
    if (current.state === "ended") current.index = 0;
    state("playing");
    speech.synthesis.resume();
    speakNext();
  }

  function start(options) {
    stop();
    document.dispatchEvent(new CustomEvent("heureux:speech-start", {
      detail: { source: options.source }
    }));
    current = {
      options: options, nodes: options.nodes || [],
      private: !(options.nodes || []).length || options.nodes.some(function (node) {
        return node.dataset.speechPrivate !== "false";
      }),
      parts: speech.chunks(options.text), state: "ready",
      index: 0, utteranceId: 0, voice: null, waitingForVoice: false, voiceTimer: null
    };
    var item = current;
    panel.hidden = false;
    privacy.hidden = !item.private;
    setRate(options.rate || rate);
    if (!item.parts.length) failed("Aucun texte français à lire.");
    else device();
    return {
      stop: function () { if (current === item) stop(true); },
      pause: function () { if (current === item) pause(); },
      resume: function () { if (current === item) resume(); },
      state: function () { return current === item ? item.state : "stopped"; }
    };
  }

  toggle.addEventListener("click", function () {
    if (!current) return;
    if (current.state === "playing") pause();
    else resume();
  });
  panel.querySelector("[data-narrator-restart]").addEventListener("click", device);
  panel.querySelector("[data-narrator-close]").addEventListener("click", function () { stop(true); });
  speed.addEventListener("change", function () { setRate(speed.value); });
  panel.addEventListener("click", function () {
    if (!current || !current.options.range) return;
    var selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(current.options.range);
  });
  document.addEventListener("heureux:speech-start", function (event) {
    if (current && (!event.detail || event.detail.source !== current.options.source)) stop(true);
  });
  document.addEventListener("heureux:flashcard-change", function () { stop(true); });
  window.addEventListener("pagehide", function () { stop(true); });
  new MutationObserver(function () {
    if (!current) return;
    if (current.nodes.some(function (node) {
      // Comprehension passages are hidden; the enclosing reader must remain visible.
      return node.matches("[data-co-audio-text]") ?
        !visible(node.closest("[data-co-audio-reader]")) : !visible(node);
    })) stop(true);
  }).observe(document.getElementById("main"), {
    childList: true, subtree: true, attributes: true,
    attributeFilter: ["hidden", "class", "aria-hidden", "inert", "open"]
  });

  window.HeureuxNarrator = {
    start: start, stop: stop, setRate: setRate, nodeText: nodeText,
    rate: function () { return rate; },
    supported: speech.supported,
    visible: visible
  };
  if (window.HeureuxReadAloud) window.HeureuxReadAloud.refresh(document);
})();
