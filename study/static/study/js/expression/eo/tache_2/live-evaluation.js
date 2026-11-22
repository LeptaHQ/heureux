(() => {
  "use strict";
  const root = document.getElementById("live-studio");
  const opinion = root.dataset.mode === "opinion";
  const by = id => document.getElementById("lv-" + id);
  const button = by("assess");
  if (!button) return;
  const late = "Le bilan n’est pas arrivé à temps. Vous pouvez réessayer dans cet onglet.";
  let rows, onResult, pending, grant, simulation, elapsed;
  const status = (text, busy = false) => {
    button.setAttribute("aria-busy", String(busy));
    const message = by("assessment-status");
    message.classList.toggle("sr-only", busy && !opinion);
    message.textContent = text;
  };
  let copied;
  const copyLabel = text => {
    clearTimeout(copied);
    by("proposal-copy-label").textContent = text;
    if (text !== "Copier") copied = setTimeout(() => copyLabel("Copier"), 2400);
  };
  by("proposal-copy").onclick = async () => {
    const text = [...by("proposal-lines").children].map(line => line.textContent).join(opinion ? "\n\n" : "\n");
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
      const line = document.createElement(opinion ? "p" : "li");
      line.textContent = text;
      return line;
    }));
    by("proposal").hidden = !lines.length;
  }

  function show(report) {
    by("level").textContent = report.scoreStatus === "incomplete" ? "Grille partielle · pas de total" :
      report.score === null ? (opinion ? "Intervention insuffisante pour une note" : "Échange insuffisant pour une note") :
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
    if (opinion && report.proposal?.length && report.score !== null && !report.omitted) by("assessment").open = false;
    return report.omitted ? "Les éléments non vérifiables ont été écartés." :
      report.score === null ? "Bilan disponible sans note globale." : "Estimation d’entraînement disponible.";
  }

  // A saved exchange (`id`) reopens with its stored report, or waits for the sparkle button.
  function bind(transcript, paint, {elapsed: spoken = 0, id = null, report = null} = {}) {
    pending?.abort();
    pending = null;
    rows = transcript;
    onResult = paint;
    simulation = id;
    elapsed = Math.round(spoken);
    const hasSpeech = rows?.some(row => row.speaker === "user" && row.text.trim());
    button.disabled = true;
    by("assessment").open = by("proposal-card").open = true;
    by("level").textContent = "Non évalué";
    by("assessment-controls").hidden = !hasSpeech;
    by("assessment-result").hidden = true;
    for (const part of ["assessment-reason", "assessment-evidence", "assessment-criteria", "assessment-next"]) by(part).replaceChildren();
    propose([]);
    status(rows && !hasSpeech ? "Aucune parole de votre part à évaluer." : "");
    if (!hasSpeech) return;
    if (report) status(show(report));
    else if (simulation) {
      button.disabled = false;
      status(opinion ? "Pas encore de bilan pour cette intervention : touchez ✨ pour le demander." :
        "Pas encore de bilan pour cet échange : touchez ✨ pour le demander.");
    } else assess();
  }
  const post = (call, body) => ({
    method: "POST", credentials: "same-origin", mode: "same-origin", cache: "no-store", redirect: "error", signal: call.signal,
    headers: {"Content-Type": "application/json", "X-CSRFToken": root.querySelector('[name="csrfmiddlewaretoken"]').value},
    body: JSON.stringify(body)
  });
  // Saving is not aborted by « Nouvel essai », so a quickly dismissed exchange still reaches the account.
  async function save() {
    try {
      const response = await fetch(root.dataset.saveUrl, post({}, {elapsed, rows: rows.map(({speaker, text, interrupted}) =>
        interrupted ? {speaker, text, interrupted: true} : {speaker, text})}));
      return response.status === 201 ? (await response.json()).id : null;
    } catch {
      return null;
    }
  }
  // Starts when the exchange ends, once it is saved; the sparkle button retries after a failure.
  async function assess() {
    if (!rows || pending) return;
    const call = pending = new AbortController();
    button.disabled = true;
    if (opinion) by("level").textContent = "Bilan en préparation…";
    status(opinion ? "Vous pouvez déjà relire votre transcription ci-dessous." : "Groq examine votre échange…", true);
    // A result or failure reopens the bilan if it was folded while Groq worked.
    const done = text => {
      if (!opinion || by("assessment-result").hidden || !simulation) by("assessment").open = true;
      if (opinion && by("assessment-result").hidden) by("level").textContent = "Bilan indisponible";
      status(simulation ? text : `${text} Cette séance n’a pas pu être enregistrée.`);
    };
    try {
      if (!simulation) {
        const id = await save();
        if (pending !== call) return;
        if (typeof id === "string") {
          simulation = id;
          // A reload or a shared tab reopens this exchange instead of a blank studio.
          const url = new URL(location.href);
          url.searchParams.set("simulation", id);
          history.replaceState(history.state, "", url);
        }
      }
      const options = post(call, {consent: true, rows: rows.map(({speaker, text}) => ({speaker, text})),
        ...(simulation && {simulation}), ...(grant && {reviewGrant: grant})});
      // Without this tab's review grant, such as for a reopened exchange, the audio PIN authorizes the report.
      const response = await (grant ? fetch(root.dataset.evaluationUrl, options) :
        window.HeureuxAudioRequest(root.dataset.evaluationUrl, options, {title: "Demander le bilan Groq", action: "Demander le bilan",
          description: "La transcription de cette séance sera envoyée à Groq pour le bilan."}));
      if (pending !== call) return;
      if (!response.ok) {
        if (response.status === 403) grant = null;
        if (response.status === 504) {
          done(late);
          return;
        }
        const detail = response.headers.get("content-type")?.includes("application/json") ? await response.json() : null;
        if (pending !== call) return;
        done(response.status === 401 ? "Reconnectez-vous pour demander un bilan Groq." :
          typeof detail?.message === "string" ? detail.message :
          typeof detail?.error === "string" ? detail.error :
          `Le service de bilan n’a pas répondu correctement (HTTP ${response.status}). Votre transcription reste disponible.`);
        return;
      }
      const report = await response.json();
      if (pending !== call) return;
      // A slow report arrives after keep-alive spaces, so its failure is in the body, not the HTTP status.
      if (typeof report.error === "string") {
        done(report.error);
        return;
      }
      done(show(report));
    } catch (error) {
      if (pending === call) done(error.name === "AbortError" ? "Bilan annulé. Aucune note attribuée." :
        "Impossible de recevoir le bilan. Gardez cet onglet ouvert : votre transcription reste disponible.");
    } finally {
      if (pending === call) {
        pending = null;
        button.disabled = false;
      }
    }
  }
  button.onclick = assess;
  window.HeureuxEO2Evaluation = {bind, setGrant: value => { grant = value; }, clear: () => { grant = null; bind(null, null); }};
})();
