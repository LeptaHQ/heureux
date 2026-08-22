/* Shared French speech synthesis and declarative read-aloud controls. */
(function () {
  "use strict";

  var synthesis = window.speechSynthesis;
  var Utterance = window.SpeechSynthesisUtterance;
  var frenchVoices = [];
  var feminineVoiceNames = [
    "amelie",
    "audrey",
    "aurelie",
    "caroline",
    "celine",
    "charlotte",
    "chloe",
    "claire",
    "denise",
    "elise",
    "eloise",
    "francoise",
    "hortense",
    "julie",
    "lea",
    "manon",
    "marie",
    "sandrine",
    "sylvie",
    "valerie",
    "virginie",
    "vivienne"
  ];
  var qualityVoiceNames = [
    "premium",
    "enhanced",
    "neural",
    "natural",
    "wavenet"
  ];

  function normalizedVoiceName(voice) {
    return ((voice && voice.name) || "")
      .concat(" ", (voice && voice.voiceURI) || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();
  }

  function isFeminineVoice(voice) {
    var name = normalizedVoiceName(voice);
    return feminineVoiceNames.some(function (candidate) {
      return name.indexOf(candidate) !== -1;
    });
  }

  function refreshVoices() {
    if (!synthesis) {
      frenchVoices = [];
      return;
    }
    frenchVoices = synthesis.getVoices().filter(function (voice) {
      return /^fr(?:[-_]|$)/i.test(voice.lang || "");
    });
  }

  function voiceScore(voice) {
    var language = (voice.lang || "").replace("_", "-").toLowerCase();
    var name = normalizedVoiceName(voice);
    var value = language === "fr-fr" ? 100 : 50;
    if (isFeminineVoice(voice)) value += 1000;
    else if (name.indexOf("google") !== -1) value += 500;
    qualityVoiceNames.forEach(function (quality, index) {
      if (name.indexOf(quality) !== -1) {
        value += 450 - (index * 40);
      }
    });
    if (voice.localService) value += 10;
    if (voice.default) value += 1;
    return value;
  }

  function preferredVoice() {
    return frenchVoices.slice().sort(function (first, second) {
      return voiceScore(second) - voiceScore(first);
    })[0] || null;
  }

  function splitLongSegment(segment) {
    var parts = [];
    var remainder = segment.trim();
    while (remainder.length > 220) {
      var splitAt = remainder.lastIndexOf(", ", 220);
      if (splitAt < 120) splitAt = remainder.lastIndexOf("; ", 220);
      if (splitAt < 120) splitAt = remainder.lastIndexOf(" ", 220);
      if (splitAt < 1) splitAt = 220;
      parts.push(remainder.slice(0, splitAt + 1).trim());
      remainder = remainder.slice(splitAt + 1).trim();
    }
    if (remainder) parts.push(remainder);
    return parts;
  }

  function chunks(text) {
    var normalized = String(text || "")
      .replace(/\u00a0/g, " ")
      .replace(/^\s*--\s*/, "")
      .replace(/\s+--\s+/g, ". ")
      .replace(/\s+/g, " ")
      .trim();
    if (!normalized) return [];

    var sentences;
    if (typeof Intl !== "undefined" && Intl.Segmenter) {
      var segmenter = new Intl.Segmenter("fr", { granularity: "sentence" });
      sentences = Array.from(segmenter.segment(normalized)).map(
        function (part) { return part.segment.trim(); }
      );
    } else {
      sentences = normalized.match(/[^.!?…]+(?:[.!?…]+|$)/g) || [normalized];
    }

    return sentences.reduce(function (parts, sentence) {
      return parts.concat(splitLongSegment(sentence));
    }, []).filter(Boolean);
  }

  var supported = Boolean(synthesis && Utterance);
  if (supported) {
    refreshVoices();
    if (synthesis.addEventListener) {
      synthesis.addEventListener("voiceschanged", refreshVoices);
    } else {
      synthesis.onvoiceschanged = refreshVoices;
    }
  }

  var frenchSpeech = {
    synthesis: synthesis,
    Utterance: Utterance,
    supported: supported,
    refreshVoices: refreshVoices,
    preferredVoice: preferredVoice,
    isFeminineVoice: isFeminineVoice,
    chunks: chunks
  };
  window.HeureuxFrenchSpeech = frenchSpeech;

  var active = null;
  var playbackNumber = 0;

  function readKey(button) {
    return button.dataset.readAloudKey || "";
  }

  function readLabel(button) {
    return button.dataset.readAloudLabel || "Lire à voix haute";
  }

  function sourceIsVisible(source) {
    return !source.closest(".hidden, [hidden], [aria-hidden='true'], [inert]");
  }

  function textFor(button) {
    var targetId = button.dataset.readAloudTarget;
    var sources = [];
    if (targetId) {
      var target = document.getElementById(targetId);
      if (target && sourceIsVisible(target)) sources.push(target);
    } else {
      var scope = button.closest("[data-read-aloud-scope]") || document;
      sources = Array.from(
        scope.querySelectorAll("[data-read-aloud-text]")
      ).filter(sourceIsVisible);
    }
    var seen = {};
    return sources.map(function (source) {
      return (source.textContent || "").replace(/\s+/g, " ").trim();
    }).filter(function (text) {
      if (!text || seen[text]) return false;
      seen[text] = true;
      return true;
    }).join(" — ");
  }

  function relatedButtons(button) {
    var key = readKey(button);
    if (!key) return [button];
    return Array.from(document.querySelectorAll("[data-read-aloud]")).filter(
      function (candidate) { return readKey(candidate) === key; }
    );
  }

  function setButtonState(button, reading) {
    var label = reading ? "Arrêter la lecture" : readLabel(button);
    button.classList.toggle("is-reading", reading);
    button.setAttribute("aria-pressed", reading ? "true" : "false");
    button.setAttribute("aria-label", label);
    button.setAttribute("title", label);
    var labelNode = button.querySelector("[data-read-aloud-button-label]");
    if (labelNode && labelNode.textContent !== label) {
      labelNode.textContent = label;
    }
  }

  function finish() {
    if (!active) return;
    var button = active.button;
    active = null;
    relatedButtons(button).forEach(function (candidate) {
      setButtonState(candidate, false);
    });
  }

  function stop(cancelSpeech) {
    var previous = active;
    active = null;
    playbackNumber += 1;
    if (
      cancelSpeech !== false &&
      supported &&
      (previous || synthesis.speaking || synthesis.pending || synthesis.paused)
    ) {
      synthesis.cancel();
      synthesis.resume();
    }
    if (previous) {
      relatedButtons(previous.button).forEach(function (candidate) {
        setButtonState(candidate, false);
      });
    }
  }

  function speakNext(number) {
    if (!active || active.number !== number) return;
    if (active.index >= active.chunks.length) {
      finish();
      return;
    }
    var utterance = new Utterance(active.chunks[active.index]);
    var voice = preferredVoice();
    utterance.lang = "fr-FR";
    utterance.rate = 0.92;
    utterance.pitch = 1;
    if (voice) utterance.voice = voice;
    utterance.onend = function () {
      if (!active || active.number !== number) return;
      active.index += 1;
      speakNext(number);
    };
    utterance.onerror = function () {
      if (active && active.number === number) finish();
    };
    synthesis.speak(utterance);
  }

  function start(button) {
    if (!supported || button.disabled) return;
    if (active && relatedButtons(active.button).indexOf(button) !== -1) {
      stop();
      return;
    }
    var parts = chunks(textFor(button));
    if (!parts.length) {
      refresh(button.closest("[data-read-aloud-scope]") || document);
      return;
    }
    document.dispatchEvent(new CustomEvent("heureux:speech-start", {
      detail: { source: "read-aloud" }
    }));
    stop();
    refreshVoices();
    playbackNumber += 1;
    active = {
      button: button,
      chunks: parts,
      index: 0,
      number: playbackNumber
    };
    relatedButtons(button).forEach(function (candidate) {
      setButtonState(candidate, true);
    });
    synthesis.resume();
    speakNext(playbackNumber);
  }

  function refresh(root) {
    var scope = root && root.querySelectorAll ? root : document;
    var buttons = [];
    if (scope.matches && scope.matches("[data-read-aloud]")) buttons.push(scope);
    buttons = buttons.concat(
      Array.from(scope.querySelectorAll("[data-read-aloud]"))
    );
    buttons.forEach(function (button) {
      if (!supported) {
        button.hidden = true;
        return;
      }
      button.hidden = false;
      var isActive = Boolean(
        active && relatedButtons(active.button).indexOf(button) !== -1
      );
      button.disabled = !isActive && !chunks(textFor(button)).length;
      if (!isActive) setButtonState(button, false);
    });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-read-aloud]");
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    start(button);
  });
  document.addEventListener("heureux:speech-start", function (event) {
    if (
      active &&
      (!event.detail || event.detail.source !== "read-aloud")
    ) {
      stop();
    }
  });
  document.addEventListener("heureux:flashcard-change", function (event) {
    if (active) stop();
    refresh(event.target);
  });
  window.addEventListener("pagehide", function () {
    stop();
  });

  window.HeureuxReadAloud = {
    refresh: refresh,
    stop: stop,
    textFor: textFor
  };
  refresh(document);
})();
