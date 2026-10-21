(function () {
  "use strict";

  var active = null;
  var selector = "audio[data-eo3-audio]";

  function initialize(root) {
    var players = [];
    if (root.matches && root.matches(selector)) players.push(root);
    if (root.querySelectorAll) {
      players = players.concat(Array.from(root.querySelectorAll(selector)));
    }
    players.forEach(function (audio) {
      if (audio.dataset.eo3Initialized) return;
      audio.dataset.eo3Initialized = "true";
      audio.defaultPlaybackRate = 0.85;
      audio.playbackRate = 0.85;
      audio.preservesPitch = true;
      if ("webkitPreservesPitch" in audio) audio.webkitPreservesPitch = true;
      audio.addEventListener("error", function () {
        audio.closest("[data-eo3-player]")
          .querySelector("[data-eo3-audio-status]").textContent =
          "Lecture indisponible. Rechargez la page pour vérifier la version de la réponse, puis réessayez.";
      });
      audio.addEventListener("pause", function () {
        if (audio.error || audio.ended) return;
        audio.closest("[data-eo3-player]")
          .querySelector("[data-eo3-audio-status]").textContent = "Lecture en pause.";
      });
      audio.addEventListener("ended", function () {
        audio.closest("[data-eo3-player]")
          .querySelector("[data-eo3-audio-status]").textContent = "Lecture terminée.";
      });
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
    var button = event.target.closest("[data-eo3-restart]");
    if (!button) return;
    var audio = button.closest("[data-eo3-player]").querySelector(selector);
    audio.currentTime = 0;
  });

  document.addEventListener("heureux:speech-start", function (event) {
    if (!event.detail || event.detail.source !== "eo3-narration") stop();
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
