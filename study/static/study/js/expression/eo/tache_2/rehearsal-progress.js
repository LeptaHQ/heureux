(() => {
  "use strict";
  window.HeureuxEO2Practice = root => {
    const status = root.querySelector("[data-practice-status]");
    const retry = root.querySelector("[data-practice-retry]");
    const restart = root.querySelector("[data-practice-restart]");
    const csrf = root.querySelector("[name=csrfmiddlewaretoken]")?.value;
    let attempt, finished = false, recorded = false, saving = false;

    function uuid() {
      if (window.crypto.randomUUID) return window.crypto.randomUUID();
      const bytes = window.crypto.getRandomValues(new Uint8Array(16));
      bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
      const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    }
    async function save() {
      if (!finished || recorded || saving || !attempt) return;
      saving = true; restart.disabled = true; retry.hidden = true;
      status.textContent = "Enregistrement de la séance…";
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 12000);
      try {
        const response = await fetch(root.dataset.finishUrl, {
          method: "POST", credentials: "same-origin", mode: "same-origin", redirect: "error",
          signal: controller.signal,
          headers: {"X-CSRFToken": csrf, Accept: "application/json"},
          body: new URLSearchParams({topic: root.dataset.practiceTopic, attempt}),
        });
        if (!response.ok || (await response.json()).recorded !== true) throw new Error("Not recorded");
        recorded = true; restart.disabled = false;
        status.textContent = "Séance enregistrée dans votre historique.";
      } catch {
        status.textContent = "Séance non enregistrée. Réessayez avant de lancer un nouvel essai.";
        retry.hidden = false;
      } finally {
        clearTimeout(timeout); saving = false;
      }
    }
    retry.onclick = save;
    return {
      begin() {
        if (saving || (finished && !recorded)) return false;
        attempt = uuid(); finished = recorded = false;
        status.textContent = ""; retry.hidden = true; restart.disabled = false;
        return true;
      },
      finish(hasExchange) {
        if (!hasExchange) {
          status.textContent = "Aucun échange terminé : cette tentative n’est pas comptée.";
          return;
        }
        finished = true; save();
      },
    };
  };
})();
