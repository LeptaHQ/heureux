(() => {
  "use strict";
  const root = document.getElementById("live-studio");
  const by = id => document.getElementById("lv-" + id);
  const consent = by("assessment-consent"), button = by("assess");
  if (!consent || !button) return;
  let rows, onResult, pending, grant;
  const status = (text, busy = false) => {
    button.setAttribute("aria-busy", String(busy));
    const message = by("assessment-status");
    message.classList.toggle("sr-only", busy);
    message.textContent = text;
  };
  let copied;
  const copyLabel = text => {
    clearTimeout(copied);
    by("proposal-copy-label").textContent = text;
    if (text !== "Copier") copied = setTimeout(() => copyLabel("Copier"), 2400);
  };
  by("proposal-copy").onclick = async () => {
    const text = [...by("proposal-lines").children].map(line => line.textContent).join("\n");
    try {
      await window.HeureuxClipboard.writeText(text);
      copyLabel("Copié !");
    } catch {
      copyLabel("Échec");
    }
  };
  function propose(lines) {
    copyLabel("Copier");
    by("proposal-lines").replaceChildren(...lines.map(text => {
      const line = document.createElement("li");
      line.textContent = text;
      return line;
    }));
    by("proposal").hidden = !lines.length;
  }

  function bind(transcript, paint) {
    pending?.abort();
    pending = null;
    rows = transcript;
    onResult = paint;
    const hasSpeech = rows?.some(row => row.speaker === "user" && row.text.trim());
    consent.checked = false;
    consent.disabled = !hasSpeech;
    button.disabled = true;
    by("level").textContent = "Non évalué";
    by("assessment-controls").hidden = !hasSpeech;
    by("assessment-result").hidden = true;
    for (const id of ["assessment-reason", "assessment-evidence", "assessment-criteria", "assessment-next"]) by(id).replaceChildren();
    propose([]);
    status(rows && !hasSpeech ? "Aucune parole de votre part à évaluer." : "");
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
    const call = pending = new AbortController();
    button.disabled = true;
    status("Gemini examine votre échange…", true);
    try {
      const response = await fetch(root.dataset.evaluationUrl, {
        method: "POST", credentials: "same-origin", mode: "same-origin", cache: "no-store", redirect: "error", signal: call.signal,
        headers: {"Content-Type": "application/json", "X-CSRFToken": root.querySelector('[name="csrfmiddlewaretoken"]').value},
        body: JSON.stringify({consent: true, reviewGrant: grant, rows: rows.map(({speaker, text}) => ({speaker, text}))})
      });
      if (pending !== call) return;
      if (!response.ok) {
        if (response.status === 504) {
          status("Le bilan n’est pas arrivé à temps. Vous pouvez réessayer dans cet onglet.");
          return;
        }
        const detail = response.headers.get("content-type")?.includes("application/json") ? await response.json() : null;
        if (pending !== call) return;
        status(response.status === 401 ? "Reconnectez-vous pour demander un bilan Gemini." :
          typeof detail?.error === "string" ? detail.error :
          `Le service de bilan n’a pas répondu correctement (HTTP ${response.status}). Votre transcription reste disponible.`);
        return;
      }
      const report = await response.json();
      if (pending !== call) return;
      by("level").textContent = report.scoreStatus === "incomplete" ? "Grille partielle · pas de total" :
        report.score === null ? "Échange insuffisant pour une note" :
        `${report.score}/20 · NCLC ${report.nclc} · ${report.cefr}`;
      by("assessment-reason").textContent = report.reason;
      by("assessment-criteria").replaceChildren(...report.criteria.map(({label, score, why}) => {
        const row = document.createElement("tr"), name = document.createElement("th");
        name.scope = "row"; name.textContent = label;
        row.append(name);
        row.insertCell().textContent = score === null ? "—" : `${score}/5`;
        row.insertCell().textContent = why;
        return row;
      }));
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
      propose(report.proposal || []);
      status(report.omitted ? "Les éléments non vérifiables ont été écartés." :
        report.score === null ? "Bilan disponible sans note globale." : "Estimation d’entraînement disponible.");
    } catch (error) {
      if (pending === call) status(error.name === "AbortError" ? "Bilan annulé. Aucune note attribuée." :
        "Impossible de recevoir le bilan. Gardez cet onglet ouvert : votre transcription et vos corrections restent disponibles.");
    } finally {
      if (pending === call) {
        pending = null;
        consent.checked = false;
        button.disabled = true;
      }
    }
  };
  window.HeureuxEO2Evaluation = {bind, setGrant: value => { grant = value; }, clear: () => { grant = null; bind(null, null); }};
})();
