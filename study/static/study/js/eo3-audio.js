(function () {
  "use strict";

  var active = null;
  var selector = "audio[data-eo3-audio]";
  var continueKey = "heureux:eo3-continue";

  function syncToggles(audio) {
    var player = audio.closest("[data-eo3-player]");
    document.querySelectorAll("[data-eo3-toggle]").forEach(function (button) {
      if (button.closest("[data-eo3-player]") !== player &&
          (!player.id || button.dataset.eo3Toggle !== player.id)) return;
      var playing = !audio.paused && !audio.ended;
      button.disabled = false;
      button.removeAttribute("data-eo3-unavailable");
      button.removeAttribute("aria-busy");
      if (player.id) button.setAttribute("aria-controls", player.id);
      button.setAttribute("aria-label", "Écouter la réponse");
      button.setAttribute("aria-pressed", String(playing));
      button.title = playing ? "Mettre la lecture en pause" : "Écouter la réponse";
    });
  }

  function clock(seconds) {
    if (!isFinite(seconds)) return "–:––";
    seconds = Math.max(0, Math.round(seconds));
    return Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
  }

  function renderPlayer(audio) {
    var player = audio.closest("[data-eo3-player]");
    if (!player) return;
    var rate = audio.playbackRate || 1;
    var time = player.querySelector("[data-eo3-time]");
    if (time) {
      time.textContent = clock(audio.currentTime / rate) + " / " + clock(audio.duration / rate);
    }
    var seek = player.querySelector("[data-eo3-seek]");
    if (seek && isFinite(audio.duration) && audio.duration > 0 && !seek.matches(":active")) {
      seek.value = String(Math.round(audio.currentTime / audio.duration * 1000));
    }
  }

  function initialize(root) {
    var players = [];
    if (root.matches && root.matches(selector)) players.push(root);
    if (root.querySelectorAll) {
      players = players.concat(Array.from(root.querySelectorAll(selector)));
    }
    players.forEach(function (audio) {
      if (audio.dataset.eo3Initialized) {
        syncToggles(audio);
        return;
      }
      audio.dataset.eo3Initialized = "true";
      audio.defaultPlaybackRate = 0.85;
      audio.playbackRate = 0.85;
      audio.preservesPitch = true;
      if ("webkitPreservesPitch" in audio) audio.webkitPreservesPitch = true;
      ["loadedmetadata", "durationchange", "timeupdate", "ratechange", "play", "pause", "ended", "seeked"]
        .forEach(function (name) {
          audio.addEventListener(name, function () { renderPlayer(audio); });
        });
      renderPlayer(audio);
      audio.addEventListener("error", function () {
        syncToggles(audio);
        audio.closest("[data-eo3-player]")
          .querySelector("[data-eo3-audio-status]").textContent =
          "Lecture indisponible. Rechargez la page pour vérifier la version de la réponse, puis réessayez.";
      });
      audio.addEventListener("pause", function () {
        syncToggles(audio);
        if (audio.error || audio.ended) return;
        audio.closest("[data-eo3-player]")
          .querySelector("[data-eo3-audio-status]").textContent = "Lecture en pause.";
      });
      audio.addEventListener("ended", function () {
        syncToggles(audio);
        audio.closest("[data-eo3-player]")
          .querySelector("[data-eo3-audio-status]").textContent = "Lecture terminée.";
      });
      syncToggles(audio);
    });
  }

  function stop() {
    if (active) active.pause();
    active = null;
  }

  document.addEventListener("play", function (event) {
    var audio = event.target;
    if (!audio.matches || !audio.matches(selector)) return;
    if (audio.closest(".hidden, [hidden], [aria-hidden='true'], [inert]")) {
      audio.pause();
      return;
    }
    if (active && active !== audio) active.pause();
    active = audio;
    syncToggles(audio);
    document.dispatchEvent(new CustomEvent("heureux:speech-start", {
      detail: { source: "eo3-narration" }
    }));
    audio.closest("[data-eo3-player]")
      .querySelector("[data-eo3-audio-status]").textContent =
      "Lecture de la réponse française.";
  }, true);

  document.addEventListener("input", function (event) {
    if (!event.target.matches("[data-eo3-seek]")) return;
    var audio = event.target.closest("[data-eo3-player]").querySelector(selector);
    if (!isFinite(audio.duration) || audio.duration <= 0) return;
    audio.currentTime = Number(event.target.value) / 1000 * audio.duration;
  });

  function closeSpeedMenus(except) {
    document.querySelectorAll("[data-eo3-speed-menu]").forEach(function (menu) {
      if (menu === except) return;
      menu.querySelector("[role=menu]").hidden = true;
      menu.querySelector("[data-eo3-speed-toggle]").setAttribute("aria-expanded", "false");
    });
  }

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    var open = document.querySelector("[data-eo3-speed-toggle][aria-expanded='true']");
    if (!open) return;
    closeSpeedMenus();
    open.focus();
  });

  document.addEventListener("click", function (event) {
    var speedToggle = event.target.closest("[data-eo3-speed-toggle]");
    var option = event.target.closest("[data-eo3-speed]");
    if (!speedToggle && !option) {
      if (!event.target.closest("[data-eo3-speed-menu]")) closeSpeedMenus();
      return;
    }
    var wrapper = (speedToggle || option).closest("[data-eo3-speed-menu]");
    var list = wrapper.querySelector("[role=menu]");
    var trigger = wrapper.querySelector("[data-eo3-speed-toggle]");
    if (speedToggle) {
      var opening = list.hidden;
      closeSpeedMenus(wrapper);
      list.hidden = !opening;
      trigger.setAttribute("aria-expanded", String(opening));
      if (opening) (list.querySelector("[aria-checked=true]") || list.firstElementChild).focus();
      return;
    }
    var rate = Number(option.dataset.eo3Speed);
    if ([0.5, 0.6, 0.75, 0.85, 1, 1.25, 1.5, 1.75, 2].indexOf(rate) === -1) return;
    var player = option.closest("[data-eo3-player]");
    var audio = player.querySelector(selector);
    audio.defaultPlaybackRate = rate;
    audio.playbackRate = rate;
    list.querySelectorAll("[data-eo3-speed]").forEach(function (item) {
      item.setAttribute("aria-checked", String(item === option));
    });
    trigger.textContent = option.textContent;
    trigger.setAttribute("aria-label", "Vitesse de lecture : " + option.textContent);
    list.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    trigger.focus();
    player.querySelector("[data-eo3-audio-status]").textContent =
      "Vitesse de lecture : " + option.textContent + ".";
  });

  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-eo3-toggle]");
    if (toggle && !toggle.disabled) {
      var player = toggle.closest("[data-eo3-player]") ||
        (toggle.dataset.eo3Toggle && document.getElementById(toggle.dataset.eo3Toggle));
      var narration = player && player.querySelector(selector);
      if (!narration) {
        var preparation = player && player.querySelector("[data-eo3-prepare]");
        if (preparation && !preparation.disabled) {
          preparation.click();
          return;
        }
        console.error("Le lecteur de narration est introuvable.");
        toggle.disabled = true;
        toggle.title = "Lecture indisponible. Rechargez la page.";
        return;
      }
      if (!narration.paused) {
        narration.pause();
      } else {
        narration.play().catch(function (error) {
          if (error.name === "AbortError" && narration.paused) return;
          player.querySelector("[data-eo3-audio-status]").textContent =
            error.name === "NotAllowedError" ? "Touchez lecture pour écouter." : "Lecture impossible. Réessayez.";
          syncToggles(narration);
        });
      }
      return;
    }
    var loop = event.target.closest("[data-eo3-loop]");
    if (loop) {
      var looped = loop.closest("[data-eo3-player]").querySelector(selector);
      looped.loop = !looped.loop;
      loop.setAttribute("aria-pressed", String(looped.loop));
      loop.closest("[data-eo3-player]").querySelector("[data-eo3-audio-status]").textContent =
        looped.loop ? "Lecture en boucle activée." : "Lecture en boucle désactivée.";
      return;
    }
    var nav = event.target.closest("[data-eo3-nav]");
    if (nav) {
      var current = nav.closest("[data-eo3-player]").querySelector(selector);
      try {
        sessionStorage.setItem(continueKey, JSON.stringify({
          rate: current ? current.playbackRate : 0.85,
          loop: Boolean(current && current.loop)
        }));
      } catch (error) { /* Navigation still works without autoplay. */ }
      return;
    }
    var button = event.target.closest("[data-eo3-restart]");
    if (!button) return;
    var audio = button.closest("[data-eo3-player]").querySelector(selector);
    audio.currentTime = 0;
  });

  document.addEventListener("heureux:speech-start", function (event) {
    if (!event.detail || event.detail.source !== "eo3-narration") stop();
  });
  document.addEventListener("heureux:audio-prepared", function () {
    initialize(document);
  });
  document.addEventListener("heureux:flashcard-change", function (event) {
    stop();
    initialize(event.target);
  });
  window.addEventListener("pagehide", stop);
  new MutationObserver(function (mutations) {
    if (active && !active.isConnected) stop();
    mutations.forEach(function (mutation) {
      mutation.addedNodes.forEach(function (node) {
        if (node.nodeType === 1) initialize(node);
      });
    });
  }).observe(document.body, { childList: true, subtree: true });
  initialize(document);

  var pendingSettings = null;

  function applySettings(player, saved) {
    var option = player.querySelector('[data-eo3-speed="' + Number(saved.rate) + '"]');
    if (!option) return false;
    option.click();
    if (document.activeElement) document.activeElement.blur();
    var loop = player.querySelector("[data-eo3-loop]");
    if (loop && saved.loop && loop.getAttribute("aria-pressed") !== "true") loop.click();
    return true;
  }

  function resume() {
    var saved;
    try {
      saved = JSON.parse(sessionStorage.getItem(continueKey) || "null");
      sessionStorage.removeItem(continueKey);
    } catch (error) { return; }
    if (!saved) return;
    var toggle = document.querySelector("#eo3-response-player [data-eo3-toggle]");
    if (!toggle || toggle.disabled) return;
    if (!applySettings(toggle.closest("[data-eo3-player]"), saved)) pendingSettings = saved;
    toggle.click();
  }
  document.addEventListener("heureux:audio-prepared", function () {
    var player = document.getElementById("eo3-response-player");
    if (pendingSettings && player && applySettings(player, pendingSettings)) pendingSettings = null;
  });
  resume();
})();
