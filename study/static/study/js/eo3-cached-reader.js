/* A read-only playlist: one native audio element, no synthesis requests. */
(function () {
  "use strict";
  var toggle = document.querySelector("[data-eo3-series-toggle]");
  var panel = document.querySelector("[data-eo3-series-panel]");
  if (!toggle || !panel) return;
  var audio = panel.querySelector("[data-eo3-series-audio]");
  var pause = panel.querySelector("[data-eo3-series-pause]");
  var next = panel.querySelector("[data-eo3-series-next]");
  var title = panel.querySelector("[data-eo3-series-title]");
  var status = document.querySelector("[data-eo3-series-status]");
  var label = panel.querySelector("[data-eo3-series-state]");
  var skips = panel.querySelector("[data-eo3-series-skips]");
  var progress = panel.querySelector("[data-eo3-series-progress]");
  var tracks = [];
  var index = -1;
  var totalSubjects = 0;
  var skipped = 0;
  var active = false;
  var phase = "idle";
  var epoch = 0;
  var playTicket = 0;
  var request = null;
  var source = "eo3-cached-series";
  var rate = 0.85;
  // A 10 ms local silent WAV preserves Safari's per-element user-gesture grant.
  var unlock = "data:audio/wav;base64,UklGRsQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YaAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";

  function message(text) {
    status.textContent = text || "";
    status.hidden = !text;
  }
  function clock(value) {
    if (!isFinite(value)) return "–:––";
    value = Math.max(0, Math.round(value));
    return Math.floor(value / 60) + ":" + String(value % 60).padStart(2, "0");
  }
  function renderTime() {
    if (index < 0) return;
    panel.querySelector("[data-eo3-series-time]").textContent =
      clock(audio.currentTime / rate) + " / " + clock(audio.duration / rate) + " · 0,85×";
    var percent = isFinite(audio.duration) && audio.duration > 0
      ? Math.min(100, audio.currentTime / audio.duration * 100) : 0;
    progress.setAttribute("aria-valuenow", String(Math.round(percent)));
    progress.querySelector("span").style.width = percent + "%";
  }
  function render() {
    toggle.setAttribute("aria-pressed", String(active));
    toggle.setAttribute("aria-label", active
      ? "Arrêter la lecture continue" : "Lire les audios enregistrés à la suite");
    toggle.title = active ? "Arrêter la lecture continue"
      : "Lecture continue · audios enregistrés uniquement";
    panel.hidden = !active;
    pause.disabled = index < 0;
    next.disabled = index < 0 || index + 1 >= tracks.length;
    var playing = phase === "playing";
    pause.setAttribute("aria-label", playing ? "Mettre en pause" : "Reprendre la lecture");
    pause.title = pause.getAttribute("aria-label");
    panel.classList.toggle("is-paused", !playing);
    label.textContent = playing ? "En lecture" : phase === "paused"
      ? "En pause" : phase === "blocked" ? "En attente" : "Chargement…";
    skips.textContent = skipped
      ? skipped + (skipped === 1 ? " sujet sans audio ignoré." : " sujets sans audio ignorés.")
      : "";
    renderTime();
  }
  function stop(text) {
    active = false;
    epoch += 1;
    playTicket += 1;
    if (request) request.abort();
    request = null;
    phase = "idle";
    index = -1;
    tracks = [];
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    render();
    message(text);
  }
  function advance(failed) {
    if (!active || index < 0) return;
    if (failed) skipped += 1;
    if (index + 1 >= tracks.length) {
      skipped += totalSubjects - tracks[index].position;
      var ending = "Fin des enregistrements disponibles dans ce thème.";
      if (skipped) ending += " " + skipped + (skipped === 1
        ? " sujet sans audio ignoré." : " sujets sans audio ignorés.");
      stop(ending);
      return;
    }
    skipped += tracks[index + 1].position - tracks[index].position - 1;
    loadTrack(index + 1);
  }
  function play() {
    if (!active || index < 0) return;
    var ticket = ++playTicket;
    phase = "playing";
    message("");
    render();
    document.dispatchEvent(new CustomEvent("heureux:speech-start", {detail: {source: source}}));
    audio.play().catch(function (error) {
      if (!active || ticket !== playTicket || (phase === "paused" && error.name === "AbortError")) return;
      if (audio.error) {
        advance(true);
      } else {
        phase = "blocked";
        render();
        message("Appuyez sur Lecture pour continuer.");
      }
    });
  }
  function loadTrack(number) {
    if (!active) return;
    index = number;
    var track = tracks[index];
    phase = "track-loading";
    title.textContent = "Sujet " + track.position + " · " + track.title;
    title.href = track.source_url;
    title.title = track.title;
    panel.querySelector("[data-eo3-series-counter]").textContent =
      (index + 1) + " / " + tracks.length + " audios";
    audio.loop = false;
    audio.src = track.audio_url;
    audio.load();
    audio.defaultPlaybackRate = rate;
    audio.playbackRate = rate;
    audio.preservesPitch = true;
    if ("webkitPreservesPitch" in audio) audio.webkitPreservesPitch = true;
    play();
  }
  function validate(data) {
    if (!data || !Array.isArray(data.tracks) || typeof data.theme !== "string" ||
        !Number.isInteger(data.start_position) || !Number.isInteger(data.total_subjects) ||
        data.start_position < 1 || data.start_position > data.total_subjects) {
      throw new Error("La liste des enregistrements est invalide.");
    }
    var previous = data.start_position - 1;
    return data.tracks.map(function (track) {
      if (!Number.isInteger(track.position) || track.position <= previous ||
          track.position > data.total_subjects || typeof track.title !== "string" ||
          typeof track.audio_url !== "string" || typeof track.source_url !== "string") {
        throw new Error("Un enregistrement de la liste est invalide.");
      }
      previous = track.position;
      var media = new URL(track.audio_url, location.href);
      var link = new URL(track.source_url, location.href);
      if (media.origin !== location.origin || media.search || media.hash ||
          !/^\/expression\/orale\/tache-3\/audio\/[a-z0-9_-]+\/[a-f0-9]{64}\/$/i.test(media.pathname) ||
          link.origin !== location.origin ||
          !/^\/expression\/orale\/tache-3\/sujets\/\d+\/$/.test(link.pathname)) {
        throw new Error("La lecture continue accepte uniquement les audios enregistrés de ce site.");
      }
      return Object.assign({}, track, {audio_url: media.href, source_url: link.href});
    });
  }
  function start() {
    active = true;
    phase = "playlist-loading";
    skipped = 0;
    index = -1;
    tracks = [];
    var token = ++epoch;
    request = new AbortController();
    title.removeAttribute("href");
    title.textContent = "Recherche des audios déjà préparés…";
    panel.querySelector("[data-eo3-series-counter]").textContent = "";
    panel.querySelector("[data-eo3-series-theme]").textContent = "Audios enregistrés uniquement";
    render();
    message("");
    document.dispatchEvent(new CustomEvent("heureux:speech-start", {detail: {source: source}}));
    audio.src = unlock;
    audio.play().catch(function () {
      if (active && token === epoch && index < 0) {
        message("Si nécessaire, appuyez sur Lecture après le chargement.");
      }
    });
    var url = new URL(toggle.dataset.eo3SeriesUrl, location.href);
    if (url.origin !== location.origin) {
      stop("Le lien de lecture continue est invalide.");
      return;
    }
    fetch(url, {credentials: "same-origin", redirect: "error", signal: request.signal})
      .then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) throw new Error(data.message || "Lecture continue indisponible.");
          return data;
        });
      })
      .then(function (data) {
        if (!active || token !== epoch) return;
        request = null;
        tracks = validate(data);
        totalSubjects = data.total_subjects;
        if (!tracks.length) {
          stop("Aucun audio enregistré disponible à partir de ce sujet dans ce thème.");
          return;
        }
        skipped = tracks[0].position - data.start_position;
        panel.querySelector("[data-eo3-series-theme]").textContent =
          data.theme + " · audios enregistrés uniquement";
        loadTrack(0);
      })
      .catch(function (error) {
        if (!active || token !== epoch || error.name === "AbortError") return;
        stop(error.message || "Lecture continue indisponible. Rechargez la page.");
      });
  }

  toggle.addEventListener("click", function () {
    if (active) stop("Lecture continue arrêtée.");
    else start();
  });
  pause.addEventListener("click", function () {
    if (!active || index < 0) return;
    if (phase === "playing") {
      phase = "paused";
      audio.pause();
      render();
    } else play();
  });
  next.addEventListener("click", function () { advance(false); });
  ["loadedmetadata", "durationchange", "timeupdate", "ratechange"].forEach(function (name) {
    audio.addEventListener(name, renderTime);
  });
  audio.addEventListener("play", function () {
    if (active && index >= 0) { phase = "playing"; message(""); render(); }
  });
  audio.addEventListener("pause", function () {
    if (active && index >= 0 && audio.paused && !audio.ended && !audio.error && phase === "playing") {
      phase = "paused";
      render();
    }
  });
  audio.addEventListener("ended", function () { if (active && index >= 0 && audio.ended) advance(false); });
  audio.addEventListener("error", function () { if (active && index >= 0 && audio.error) advance(true); });
  document.addEventListener("heureux:speech-start", function (event) {
    if (active && (!event.detail || event.detail.source !== source)) stop();
  });
  document.addEventListener("play", function (event) {
    if (active && event.target !== audio && event.target instanceof HTMLMediaElement) stop();
  }, true);
  document.addEventListener("heureux:flashcard-change", function () { if (active) stop(); });
  window.addEventListener("pagehide", function () { if (active) stop(); });
  render();
})();
