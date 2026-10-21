(function () {
  "use strict";

  var active = null;
  var selector = "audio[data-eo3-audio]";

  function syncToggles(audio) {
    var player = audio.closest("[data-eo3-player]");
    document.querySelectorAll("[data-eo3-toggle]").forEach(function (button) {
      if (button.dataset.eo3Toggle !== player.id) return;
      var playing = !audio.paused && !audio.ended;
      button.disabled = false;
      button.removeAttribute("data-eo3-unavailable");
      button.setAttribute("aria-controls", player.id);
      button.setAttribute("aria-label", "Écouter la réponse");
      button.setAttribute("aria-pressed", String(playing));
      button.title = playing ? "Mettre la lecture en pause" : "Écouter la réponse";
    });
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

  document.addEventListener("change", function (event) {
    if (!event.target.matches("[data-eo3-speed]")) return;
    var player = event.target.closest("[data-eo3-player]");
    var rate = Number(event.target.value);
    if ([0.75, 0.85, 1, 1.25, 1.5, 1.75, 2].indexOf(rate) === -1) return;
    var audio = player.querySelector(selector);
    audio.defaultPlaybackRate = rate;
    audio.playbackRate = rate;
    player.querySelector("[data-eo3-audio-status]").textContent =
      "Vitesse de lecture : " + event.target.selectedOptions[0].textContent + ".";
  });

  document.addEventListener("click", function (event) {
    var toggle = event.target.closest("[data-eo3-toggle]");
    if (toggle && !toggle.disabled) {
      var player = document.getElementById(toggle.dataset.eo3Toggle);
      var narration = player && player.querySelector(selector);
      if (!narration) {
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
            "Lecture impossible. Réessayez avec les commandes du lecteur.";
          syncToggles(narration);
        });
      }
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
})();
