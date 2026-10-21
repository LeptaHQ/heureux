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
    var toggle = player.id && document.querySelector('[data-eo3-toggle="' + player.id + '"]');
    window.HeureuxConfirm({
      message: "Préparer uniquement le premier extrait Culture, sujet 1 (" +
        button.dataset.eo3Characters + " caractères), voix configurée " + button.dataset.eo3Voice +
        ", avec ElevenLabs ? Cette action consomme des crédits. " +
        "Un seul essai est autorisé pour toute l’application avant votre écoute. Aucun autre texte ne sera généré.",
      label: "Confirmer et préparer cet extrait", tone: "safe"
    }).then(function (confirmed) {
      if (!confirmed) return;
      button.disabled = true;
      if (toggle) {
        toggle.disabled = true;
        toggle.setAttribute("aria-busy", "true");
        toggle.title = "Préparation en cours. Ne relancez pas l’action.";
      }
      status.textContent = "Préparation en cours… Cela peut prendre jusqu’à deux minutes. " +
        "Ne relancez pas l’action : un délai dépassé peut tout de même être facturé.";
      var csrf = document.querySelector("[name=csrfmiddlewaretoken]");
      return fetch(button.dataset.eo3Prepare, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf ? csrf.value : "" },
        body: JSON.stringify({confirm_cost: true, player_id: player.id || ""})
      }).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) throw new Error(data.message || "Préparation indisponible.");
          return data;
        });
      }).then(function (data) {
        if (!player.isConnected) return;
        player.outerHTML = data.html;
        document.dispatchEvent(new CustomEvent("heureux:audio-prepared"));
      }).catch(function (error) {
        if (!player.isConnected) return;
        status.textContent = error.message +
          " Rechargez la page pour vérifier le résultat. Ne répétez pas une préparation incertaine.";
        if (toggle) {
          toggle.removeAttribute("aria-busy");
          toggle.title = "Préparation non terminée. Rechargez la page pour vérifier le résultat.";
        }
        window.HeureuxConfirm({message: status.textContent, label: "Fermer", tone: "safe"});
      });
    });
  });
})();
