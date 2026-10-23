/* Only this separate, explicitly confirmed action can spend synthesis credits. */
(function () {
  "use strict";
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-eo3-prepare]");
    if (!button || button.disabled) return;
    event.preventDefault();
    event.stopPropagation();
    var player = button.closest("[data-eo3-player]");
    var status = player.querySelector("[data-eo3-prepare-status]");
    var toggle = player.querySelector("[data-eo3-toggle]") ||
      (player.id && document.querySelector('[data-eo3-toggle="' + player.id + '"]'));
    var previousToggle = toggle && {
      disabled: toggle.disabled, title: toggle.title, label: toggle.getAttribute("aria-label")
    };
    var refreshing = button.hasAttribute("data-eo3-refresh");
    var onDemand = refreshing || button.hasAttribute("data-eo3-on-demand");
    (onDemand && !refreshing ? Promise.resolve(true) : window.HeureuxConfirm(refreshing ? {
      message: "L’enregistrement conservé reste disponible. Créer un nouvel audio avec le texte " +
        "et la voix actuels ? Cette action consomme des crédits ElevenLabs et nécessite votre code PIN.",
      label: "Continuer avec le code PIN", tone: "safe", icon: "download", title: "Créer un nouvel audio"
    } : {
      message: "Préparer uniquement le premier extrait Culture, sujet 1 (" +
        button.dataset.eo3Characters + " caractères), voix configurée " + button.dataset.eo3Voice +
        ", avec ElevenLabs ? Cette action consomme des crédits. " +
        "Un seul essai est autorisé pour toute l’application avant votre écoute. Aucun autre texte ne sera généré.",
      label: "Confirmer et préparer cet extrait", tone: "safe", icon: "download", title: "Préparer l’audio"
    })).then(function (confirmed) {
      if (!confirmed) return;
      button.disabled = true;
      if (toggle) {
        toggle.disabled = true;
        toggle.setAttribute("aria-busy", "true");
        toggle.title = "Préparation de l’audio en cours…";
        toggle.setAttribute("aria-label", "Préparation de l’audio en cours");
      }
      status.textContent = onDemand ? "" :
        "Préparation en cours… Cela peut prendre jusqu’à deux minutes. " +
        "Ne relancez pas l’action : un délai dépassé peut tout de même être facturé.";
      var csrf = document.querySelector("[name=csrfmiddlewaretoken]");
      return window.HeureuxAudioRequest(button.dataset.eo3Prepare, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf ? csrf.value : "" },
        body: JSON.stringify({confirm_cost: true, player_id: player.id || "", refresh: refreshing})
      }).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) throw new Error(data.message || "Préparation indisponible.");
          return data;
        });
      }).then(function (data) {
        if (!player.isConnected) return;
        player.insertAdjacentHTML("afterend", data.html);
        var fresh = player.nextElementSibling;
        var oldAudio = player.querySelector("[data-eo3-audio]");
        var wasPlaying = oldAudio && !oldAudio.paused && !oldAudio.ended;
        var playback = oldAudio && {rate: oldAudio.playbackRate, loop: oldAudio.loop};
        var row = fresh && fresh.querySelector(".eo3-audio__row");
        if (row) player.querySelectorAll("[data-eo3-nav]").forEach(function (link) {
          var copy = link.cloneNode(true);
          if (link.previousElementSibling) {
            row.querySelector("[data-eo3-toggle]").insertAdjacentElement("afterend", copy);
          } else row.insertBefore(copy, row.firstChild);
        });
        player.remove();
        document.dispatchEvent(new CustomEvent("heureux:audio-prepared", {
          detail: {player: fresh, playback: playback}
        }));
        if (onDemand && fresh && (!refreshing || wasPlaying)) {
          var freshToggle = fresh.querySelector("[data-eo3-toggle]") || toggle;
          if (freshToggle && fresh.querySelector("[data-eo3-audio]")) freshToggle.click();
        }
      }).catch(function (error) {
        if (!player.isConnected) return;
        if (error.name === "AbortError") {
          status.textContent = "Préparation annulée.";
          button.disabled = false;
          if (toggle) {
            toggle.removeAttribute("aria-busy");
            toggle.disabled = previousToggle.disabled;
            toggle.title = previousToggle.title;
            toggle.setAttribute("aria-label", previousToggle.label);
          }
          return;
        }
        status.textContent = onDemand ? error.message :
          error.message + " Rechargez la page pour vérifier le résultat. Ne répétez pas une préparation incertaine.";
        button.disabled = !onDemand;
        if (toggle) {
          toggle.removeAttribute("aria-busy");
          toggle.disabled = !onDemand;
          toggle.setAttribute("aria-label", "Écouter la réponse");
          toggle.title = onDemand ? "Réessayer la lecture" :
            "Préparation non terminée. Rechargez la page pour vérifier le résultat.";
        }
        window.HeureuxConfirm({message: status.textContent, label: "Fermer", tone: "safe", notice: true, title: "Lecture indisponible"});
      });
    });
  });
})();
