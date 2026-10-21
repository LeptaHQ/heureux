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

  function preferredVoice(localOnly) {
    return frenchVoices.filter(function (voice) {
      return !localOnly || voice.localService === true;
    }).sort(function (first, second) {
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
    if (window.HeureuxNarrator) return window.HeureuxNarrator.visible(source);
    var hiddenSelector = ".hidden, [hidden], [aria-hidden='true'], [inert]";
    var hiddenAncestor = source.parentElement
      ? source.parentElement.closest(hiddenSelector)
      : null;
    if (hiddenAncestor || source.matches(".hidden, [hidden]")) return false;
    if (source.matches("[aria-hidden='true'], [inert]")) return false;
    var details = source.closest("details");
    if (details && !details.open) return false;
    return true;
  }

  function sourcesFor(button) {
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
    return sources;
  }

  function textFor(button) {
    var seen = Object.create(null);
    return sourcesFor(button).map(function (source) {
      return window.HeureuxNarrator ? window.HeureuxNarrator.nodeText(source) :
        (source.dataset.readAloudValue || source.textContent || "").replace(/\s+/g, " ").trim();
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

  function finish(failed) {
    if (!active) return;
    var button = active.button;
    active = null;
    relatedButtons(button).forEach(function (candidate) {
      setButtonState(candidate, false);
      if (failed) {
        var message = "Lecture indisponible. Réessayez.";
        candidate.setAttribute("aria-label", message);
        candidate.setAttribute("title", message);
        var label = candidate.querySelector("[data-read-aloud-button-label]");
        if (label) label.textContent = message;
      }
    });
    if (failed) {
      var status = document.querySelector("[data-speech-status]");
      if (!status) {
        status = document.createElement("span");
        status.className = "sr-only";
        status.dataset.speechStatus = "";
        status.setAttribute("role", "status");
        document.body.appendChild(status);
      }
      status.textContent = "Lecture indisponible. Réessayez.";
    }
  }

  function stop() {
    var previous = active;
    active = null;
    playbackNumber += 1;
    if (previous && previous.handle) previous.handle.stop();
    if (previous) {
      relatedButtons(previous.button).forEach(function (candidate) {
        setButtonState(candidate, false);
      });
    }
  }

  function start(button) {
    var narrator = window.HeureuxNarrator;
    if (!narrator || !narrator.supported || button.disabled) return;
    if (active && relatedButtons(active.button).indexOf(button) !== -1) {
      stop();
      return;
    }
    var parts = chunks(textFor(button));
    if (!parts.length) {
      refresh(button.closest("[data-read-aloud-scope]") || document);
      return;
    }
    stop();
    playbackNumber += 1;
    var item = { button: button, number: playbackNumber };
    active = item;
    relatedButtons(button).forEach(function (candidate) {
      setButtonState(candidate, true);
    });
    item.handle = narrator.start({
      source: "read-aloud", text: textFor(button), nodes: sourcesFor(button),
      onstate: function (value) {
        active = item;
        relatedButtons(button).forEach(function (candidate) {
          setButtonState(candidate, ["playing", "paused", "ready", "loading"].indexOf(value) !== -1);
        });
      },
      onend: function () { if (active === item) finish(); },
      onerror: function () { if (active === item) finish(true); },
      onstop: function () { if (active === item) stop(); }
    });
  }

  function refresh(root) {
    var scope = root && root.querySelectorAll ? root : document;
    var buttons = [];
    if (scope.matches && scope.matches("[data-read-aloud]")) buttons.push(scope);
    buttons = buttons.concat(
      Array.from(scope.querySelectorAll("[data-read-aloud]"))
    );
    buttons.forEach(function (button) {
      if (!supported && !(window.HeureuxNarrator && window.HeureuxNarrator.supported)) {
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
