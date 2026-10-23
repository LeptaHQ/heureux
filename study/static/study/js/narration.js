/* One transport for declarative, selected-text and comprehension readers. */
(function () {
  "use strict";
  var speech = window.HeureuxFrenchSpeech;
  var panel = document.querySelector("[data-narrator]");
  if (!panel || !speech) return;
  var audio = panel.querySelector("[data-narrator-audio]");
  var status = panel.querySelector("[data-narrator-status]");
  var toggle = panel.querySelector("[data-narrator-toggle]");
  var speed = panel.querySelector("[data-narrator-speed]");
  var consent = panel.querySelector("[data-narrator-consent]");
  var natural = panel.querySelector("[data-narrator-natural]");
  var preparation = panel.querySelector("[data-narrator-preparation]");
  var current = null;
  var sequence = 0;
  var rate = 0.85;
  var rates = [0.75, 0.85, 1, 1.25, 1.5, 1.75, 2];
  var enabled = document.body.dataset.frenchAudioEnabled === "true";
  var configured = document.body.dataset.frenchAudioConfigured === "true";

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
    if (!node || !node.isConnected || node.closest(".hidden, [hidden], [aria-hidden='true'], [inert]")) return false;
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
    toggle.textContent = value === "playing" ? "Pause" : "Lecture";
    toggle.disabled = value === "loading";
    if (current.options.onstate) current.options.onstate(value);
  }

  function stop(hide) {
    var previous = current;
    current = null;
    sequence += 1;
    if (previous && previous.request) previous.request.abort();
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    if (speech.supported && previous && previous.engine === "device") {
      speech.synthesis.cancel();
      speech.synthesis.resume();
    }
    if (previous && previous.options.onstop) previous.options.onstop();
    if (hide) panel.hidden = true;
  }

  function failed(text) {
    if (!current) return;
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

  function setRate(value) {
    value = Number(value);
    if (rates.indexOf(value) === -1) return;
    rate = value;
    speed.value = String(value);
    audio.defaultPlaybackRate = value;
    audio.playbackRate = value;
    audio.preservesPitch = true;
    if ("webkitPreservesPitch" in audio) audio.webkitPreservesPitch = true;
    document.dispatchEvent(new CustomEvent("heureux:narration-rate", { detail: { rate: value } }));
    if (current && current.engine === "device" && current.state === "playing") {
      current.utteranceId += 1;
      speech.synthesis.cancel();
      speech.synthesis.resume();
      speakNext();
    }
  }

  function speakNext() {
    if (!current || current.engine !== "device" || current.state !== "playing") return;
    if (current.index >= current.parts.length) { ended(); return; }
    var item = current;
    var id = ++item.utteranceId;
    var utterance = new speech.Utterance(item.parts[item.index]);
    utterance.lang = "fr-FR";
    utterance.rate = rate;
    utterance.pitch = 1;
    var voice = item.voice;
    if (voice) utterance.voice = voice;
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

  function device() {
    if (!current) return;
    if (current.request) current.request.abort();
    current.request = null;
    audio.pause();
    audio.hidden = true;
    if (!speech.supported) {
      failed("La voix de l’appareil est indisponible dans ce navigateur.");
      return;
    }
    current.engine = "device";
    current.index = 0;
    current.utteranceId += 1;
    speech.synthesis.cancel();
    speech.synthesis.resume();
    speech.refreshVoices();
    var voice = speech.preferredVoice(current.private);
    if (current.private && !voice) {
      failed("Aucune voix française locale disponible. Installez une voix locale ou autorisez explicitement la voix naturelle.");
      return;
    }
    current.voice = voice;
    state("playing");
    message("Voix de l’appareil" + (voice ? " · " + voice.name : "") +
      (current.private ? " · texte privé non transmis pour la lecture." :
        " · enregistrement naturel non utilisé."));
    speakNext();
  }

  function pause() {
    if (!current || current.state !== "playing") return;
    if (current.engine === "natural") audio.pause();
    else {
      current.utteranceId += 1;
      speech.synthesis.cancel();
      speech.synthesis.resume();
    }
    state("paused");
    message("Lecture en pause.");
  }

  function resume() {
    if (!current) return;
    if (current.engine === "natural") {
      var item = current;
      var play = audio.play();
      if (play) play.catch(function (error) {
        if (current !== item) return;
        if (error.name === "NotAllowedError") {
          state("ready");
          message("Enregistrement prêt. Appuyez sur Lecture pour démarrer.");
        } else if (error.name !== "AbortError") {
          failed("Lecture naturelle indisponible. Aucun remplacement automatique par une autre voix.");
        }
      });
    } else {
      state("playing");
      speech.synthesis.resume();
      speakNext();
    }
  }

  function resolve(prepare) {
    if (!current) return;
    if (current.private && !consent.checked) {
      message("Le texte privé reste sur votre appareil. Cochez l’accord pour utiliser la voix naturelle.");
      return;
    }
    if (!current.sources.length) {
      message("Cette sélection n’a pas de source française autorisée. Utilisez la voix de l’appareil.");
      return;
    }
    var item = current;
    if (item.request) item.request.abort();
    item.utteranceId += 1;
    if (speech.supported && item.engine === "device") {
      speech.synthesis.cancel();
      speech.synthesis.resume();
    }
    audio.pause();
    var controller = new AbortController();
    item.request = controller;
    item.engine = "natural";
    state("loading");
    preparation.hidden = true;
    message(prepare ? "Préparation ElevenLabs en cours, jusqu’à deux minutes. Fermer le lecteur n’annule pas une préparation facturable…" :
      "Recherche de l’enregistrement, sans génération…");
    var csrf = document.querySelector("[name=csrfmiddlewaretoken]");
    window.HeureuxAudioRequest(document.body.dataset.frenchAudioResolveUrl, {
      method: "POST", credentials: "same-origin", signal: controller.signal,
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf ? csrf.value : "" },
      body: JSON.stringify({
        sources: item.sources, consent: item.private && consent.checked,
        prepare: prepare === true, confirm_cost: prepare === true
      })
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.message || "Lecture naturelle indisponible.");
        return data;
      });
    }).then(function (data) {
      if (current !== item || item.request !== controller) return;
      item.request = null;
      if (data.state === "ready") {
        audio.src = data.url;
        audio.hidden = false;
        setRate(rate);
        state("ready");
        message("Voix française de synthèse · ElevenLabs. Enregistrement en cache.");
        resume();
      } else {
        state("unavailable");
        message(data.message + (data.request_id ? " Référence : " + data.request_id : ""));
        panel.querySelector("[data-narrator-options]").open = true;
        item.characters = data.characters;
        preparation.hidden = !data.can_request;
      }
    }).catch(function (error) {
      if (current !== item || item.request !== controller) return;
      item.request = null;
      if (error.name === "AbortError") {
        state("unavailable");
        message("Préparation annulée.");
        panel.querySelector("[data-narrator-options]").open = true;
        preparation.hidden = !prepare;
        return;
      }
      failed(error.message || "Lecture naturelle indisponible. Vérifiez votre connexion.");
    });
  }

  function sourceData(nodes, selected) {
    return (nodes || []).map(function (node) {
      if (!node.dataset.speechGrant || nodeText(node) !== normalize(node.dataset.speechText)) return null;
      if (selected && normalize(node.dataset.speechText).indexOf(normalize(selected)) === -1) return null;
      var result = { grant: node.dataset.speechGrant };
      if (selected) result.text = normalize(selected);
      return result;
    }).filter(Boolean);
  }

  function start(options) {
    stop();
    document.dispatchEvent(new CustomEvent("heureux:speech-start", {
      detail: { source: options.source }
    }));
    var nodes = options.nodes || [];
    var sources = sourceData(nodes, options.selection);
    if (sources.length !== nodes.length) sources = [];
    current = {
      options: options, sources: sources, nodes: nodes,
      private: !nodes.length || nodes.some(function (node) {
        return node.dataset.speechPrivate !== "false";
      }),
      parts: speech.chunks(options.text), state: "ready", engine: "device",
      index: 0, utteranceId: 0, request: null
    };
    var item = current;
    panel.hidden = false;
    audio.hidden = true;
    preparation.hidden = true;
    panel.querySelector("[data-narrator-options]").open = false;
    consent.checked = false;
    panel.querySelector("[data-narrator-privacy]").hidden = !item.private;
    natural.hidden = !enabled;
    natural.disabled = !configured || !sources.length || item.private;
    panel.querySelector("[data-narrator-device]").disabled = !speech.supported;
    setRate(options.rate || rate);
    if (enabled && configured && !item.private && sources.length) resolve(false);
    else device();
    return {
      stop: function () { if (current === item) stop(true); },
      pause: function () { if (current === item) pause(); },
      resume: function () { if (current === item) resume(); },
      state: function () { return current === item ? item.state : "stopped"; }
    };
  }

  audio.addEventListener("play", function () {
    if (!current || current.engine !== "natural") return;
    state("playing");
    message("Voix française de synthèse · ElevenLabs · enregistrement en cache.");
  });
  audio.addEventListener("pause", function () {
    if (current && current.engine === "natural" && current.state === "playing" && !audio.ended) {
      state("paused");
      message("Lecture en pause.");
    }
  });
  audio.addEventListener("ended", ended);
  audio.addEventListener("error", function () {
    if (current && current.engine === "natural" && audio.getAttribute("src")) {
      failed("Lecture naturelle indisponible. Rechargez la page pour vérifier la version du texte.");
    }
  });
  toggle.addEventListener("click", function () {
    if (!current) return;
    if (current.state === "playing") pause();
    else if (current.state === "unavailable" || current.state === "error") {
      message("Choisissez explicitement la voix de l’appareil ou relancez la voix naturelle.");
    } else {
      if (current.state === "ended") {
        current.index = 0;
        if (current.engine === "natural") audio.currentTime = 0;
      }
      resume();
    }
  });
  panel.querySelector("[data-narrator-restart]").addEventListener("click", function () {
    if (!current) return;
    if (current.engine === "natural" && audio.getAttribute("src")) audio.currentTime = 0;
    else if (current.engine === "device") device();
  });
  panel.querySelector("[data-narrator-close]").addEventListener("click", function () { stop(true); });
  panel.querySelector("[data-narrator-device]").addEventListener("click", device);
  natural.addEventListener("click", function () { resolve(false); });
  panel.querySelector("[data-narrator-request]").addEventListener("click", function () {
    var item = current;
    if (!item) return;
    window.HeureuxConfirm({
      message: "Préparer cet enregistrement avec ElevenLabs" +
        (item.characters ? " (" + item.characters + " caractères)" : "") +
        " ? Cette action consomme des crédits, dans la limite du plafond global. " +
        "Un échec ou un délai dépassé peut être facturé. Aucun nouvel essai automatique.",
      label: "Confirmer et préparer", tone: "safe"
    }).then(function (confirmed) {
      if (confirmed && current === item) resolve(true);
    });
  });
  consent.addEventListener("change", function () {
    if (!current) return;
    natural.disabled = !configured || !current.sources.length || (current.private && !consent.checked);
    if (!consent.checked && current.private) {
      device();
      if (current && current.state === "playing") {
        message("Accord retiré. Voix de l’appareil uniquement pour cette lecture.");
      }
    }
  });
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
      // CO sources are intentionally hidden; their reader, not their source span, must be visible.
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
    supported: Boolean(speech.supported || (enabled && configured)),
    visible: visible
  };
  if (window.HeureuxReadAloud) window.HeureuxReadAloud.refresh(document);
})();
