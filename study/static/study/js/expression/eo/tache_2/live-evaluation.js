(() => {
  "use strict";
  const root = document.getElementById("live-studio");
  const by = id => document.getElementById("lv-" + id);
  const consent = by("assessment-consent"), button = by("assess");
  if (!consent || !button) return;
  let rows, onResult, pending;
  const status = text => { by("assessment-status").textContent = text; };

  function bind(reviewed, paint, edited = false) {
    pending?.abort();
    pending = null;
    rows = reviewed;
    onResult = paint;
    const hasSpeech = rows?.some(row => row.speaker === "user" && row.text.trim());
    consent.checked = false;
    consent.disabled = !hasSpeech;
    button.disabled = true;
    by("level").textContent = "Non évalué";
    by("assessment-controls").hidden = !hasSpeech;
    by("assessment-result").hidden = true;
    for (const id of ["assessment-reason", "assessment-evidence", "assessment-next"]) by(id).replaceChildren();
    status(!rows ? "" : !hasSpeech ? "Aucune parole de votre part à évaluer." :
      edited ? "Transcription modifiée. Aucune nouvelle demande n’a été envoyée." : "");
  }
  consent.onchange = () => {
    if (!consent.checked && pending) {
      pending.abort();
      pending = null;
      status("Demande arrêtée. Les corrections locales restent disponibles.");
    }
    button.disabled = !consent.checked || !!pending;
  };
  button.onclick = async () => {
    if (!rows || !consent.checked || pending) return;
    if (by("turns").querySelector("[data-editing]")) {
      status("Appliquez ou annulez la rectification en cours avant de demander le bilan.");
      return;
    }
    const call = pending = new AbortController();
    button.disabled = true;
    status("Gemini examine votre échange…");
    try {
      const response = await window.HeureuxAudioRequest(root.dataset.evaluationUrl, {
        method: "POST", credentials: "same-origin", mode: "same-origin", cache: "no-store", signal: call.signal,
        headers: {"Content-Type": "application/json", "X-CSRFToken": root.querySelector('[name="csrfmiddlewaretoken"]').value},
        body: JSON.stringify({consent: true, rows: rows.map(({speaker, text}) => ({speaker, text}))})
      }, {title: "Autoriser le bilan Gemini", description: "Le PIN est vérifié par Heureux. Seules la consigne et les répliques relues sont transmises à Google.", action: "Autoriser ce bilan"});
      if (pending !== call) return;
      if (!response.ok) {
        status(response.status === 429 ? "Limite atteinte. Réessayez plus tard ; les corrections locales restent disponibles." :
          response.status === 401 ? "Reconnectez-vous pour demander un bilan Gemini." :
          "Bilan Gemini indisponible. Les corrections locales restent disponibles.");
        return;
      }
      const report = await response.json();
      if (pending !== call) return;
      by("level").textContent = report.score === null ? "Échange insuffisant pour une note" :
        `${report.score}/20 · NCLC ${report.nclc} · ${report.cefr}`;
      by("assessment-reason").textContent = report.reason;
      by("assessment-evidence").replaceChildren(...report.evidence.map(({quote, why}) => {
        const li = document.createElement("li"), words = document.createElement("q");
        words.textContent = quote;
        li.append(words, ` — ${why}`);
        return li;
      }));
      by("assessment-next").textContent = report.next;
      by("assessment-result").hidden = false;
      by("assessment-controls").hidden = true;
      onResult(report.annotations);
      status(report.score === null ? "Bilan disponible sans estimation chiffrée." : "Estimation d’entraînement disponible.");
    } catch (error) {
      if (pending === call) status(error.name === "AbortError" ? "Bilan annulé. Aucune note attribuée." :
        "Bilan Gemini indisponible. Les corrections locales restent disponibles.");
    } finally {
      if (pending === call) {
        pending = null;
        consent.checked = false;
        button.disabled = true;
      }
    }
  };
  window.HeureuxEO2Evaluation = {bind, clear: () => bind(null, null)};
})();
