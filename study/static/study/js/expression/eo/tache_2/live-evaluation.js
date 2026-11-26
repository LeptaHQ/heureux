(() => {
  "use strict";
  const root = document.getElementById("live-studio");
  const opinion = root.dataset.mode === "opinion";
  const canAssess = root.dataset.evaluationEnabled === "1";
  const autoProvider = root.dataset.autoEvaluation;
  const by = id => document.getElementById("lv-" + id);
  const button = by("assess");
  if (!button) return;
  const late = "Le bilan n’est pas arrivé à temps. Vous pouvez réessayer depuis cette séance.";
  const picker = window.HeureuxAssessmentPicker(button, (provider, label) => assess(provider, label));
  const refreshControls = window.HeureuxAssessmentRefresh((provider, label) => assess(provider, label, {refresh: true}));
  const reports = new Map();
  let rows, onResult, pending, grant, snapshotGrant, simulation, elapsed, attemptId, displayedProvider;
  const status = (text, busy = false, refreshing = false) => {
    button.setAttribute("aria-busy", String(busy));
    refreshControls?.setBusy(busy);
    const message = by("assessment-status");
    message.classList.toggle("sr-only", busy && !opinion && !refreshing);
    message.textContent = text;
  };
  let copied;
  const copyLabel = text => {
    clearTimeout(copied);
    by("proposal-copy-label").textContent = text === "Copier" ? "" : text;
    const icon = text === "Copié !" ? "check" : text === "Échec" ? "alert-triangle" : "copy";
    by("proposal-copy").querySelectorAll("[data-icon]").forEach(node => {
      node.toggleAttribute("hidden", node.dataset.icon !== icon);
    });
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

  function citation({turnIndex, quote}, current) {
    const words = document.createElement("q");
    words.textContent = quote;
    // Older bilans used whole turns as quotations. Display them as saved.
    if (!current || !Number.isInteger(turnIndex) || rows[turnIndex]?.speaker !== "user" ||
        !rows[turnIndex].text.includes(quote)) return words;
    const link = document.createElement("a");
    link.className = "lv-citation"; link.href = `#lv-turn-${turnIndex}`;
    link.append(words);
    link.onclick = () => { by("transcript").open = true; };
    return link;
  }
  by("assessment-result").querySelector('[href="#lv-transcript"]').onclick = () => { by("transcript").open = true; };

  function show(report, provider) {
    reports.set(provider, report);
    displayedProvider = provider;
    picker?.select(provider);
    const canRefresh = refreshControls?.select(report, provider, picker?.label(provider) || root.dataset.evaluationProviderLabel);
    const current = report.evidenceVersion === 1;
    const retry = report.scoreStatus === "incomplete";
    by("level").classList.toggle("lv-level--scored", Number.isInteger(report.score) && report.scoreStatus !== "incomplete");
    by("level").textContent = report.scoreStatus === "incomplete" ? "Grille partielle · pas de total" :
      report.score === null ? (opinion ? "Intervention insuffisante pour une note" : "Échange insuffisant pour une note") :
      `${report.score}/20 · NCLC ${report.nclc} · ${report.cefr}`;
    by("assessment-reason").textContent = report.reason;
    by("assessment-legacy").hidden = current || !report.criteria.length;
    by("assessment-criteria").replaceChildren(...report.criteria.map(criterion => {
      const {label, score, why, quote} = criterion;
      const row = document.createElement("tr"), name = document.createElement("th");
      name.scope = "row"; name.textContent = label;
      row.append(name);
      const mark = row.insertCell();
      mark.textContent = score === null ? "Non évalué" : `${score}/5`;
      if (Number.isInteger(score) && score >= 0 && score <= 5) {
        mark.className = "lv-criterion-mark";
        mark.style.setProperty("--lv-mark", `${score * 20}%`);
      }
      const observation = row.insertCell();
      observation.textContent = why;
      if (quote) observation.append(citation(criterion, current));
      return row;
    }));
    by("assessment-evidence").replaceChildren(...report.evidence.map(item => {
      const li = document.createElement("li");
      li.append(citation(item, current), ` — ${item.why}`);
      return li;
    }));
    by("assessment-next").textContent = report.next;
    by("assessment-result").hidden = false;
    by("assessment-controls").hidden = !picker && !(retry && canAssess);
    if (retry && !picker && canAssess) {
      button.disabled = false;
      button.setAttribute("aria-label", button.title = "Réévaluer le bilan");
    }
    onResult(report.annotations);
    propose(report.proposal || []);
    if (opinion && report.proposal?.length && report.score !== null && !report.omitted && !canRefresh) by("assessment").open = false;
    if (report.previousReportKept && retry) return "La nouvelle évaluation reste incomplète. Votre bilan précédent a été conservé.";
    if (retry && canAssess) return "Vous pouvez demander une nouvelle évaluation de cette transcription avec ✨.";
    return report.omitted ? "Les éléments non vérifiables ont été écartés." :
      report.score === null ? "Bilan disponible sans note globale." : "Estimation d’entraînement disponible.";
  }

  // Reopen the stored report without sending the transcript again.
  function bind(transcript, paint, {elapsed: spoken = 0, id = null, report = null, pendingProvider = null} = {}) {
    pending?.abort();
    pending = null;
    rows = transcript;
    onResult = paint;
    simulation = id;
    elapsed = Math.round(spoken);
    reports.clear();
    displayedProvider = null;
    refreshControls?.select(null);
    const provider = !id && grant ? autoProvider : root.dataset.evaluationProvider;
    picker?.close();
    picker?.select(provider);
    const hasSpeech = rows?.some(row => row.speaker === "user" && row.text.trim());
    attemptId = !opinion && hasSpeech && !id ? crypto.randomUUID() : null;
    button.disabled = true;
    if (!picker) button.setAttribute("aria-label", button.title = "Évaluer mon niveau");
    by("assessment").open = by("proposal-card").open = true;
    by("level").textContent = "Non évalué";
    by("level").classList.remove("lv-level--scored");
    by("assessment-controls").hidden = !hasSpeech;
    by("assessment-result").hidden = true;
    for (const part of ["assessment-reason", "assessment-evidence", "assessment-criteria", "assessment-next"]) by(part).replaceChildren();
    propose([]);
    status(rows && !hasSpeech ? "Aucune parole de votre part à évaluer." : "");
    if (!hasSpeech) return;
    if (report) {
      button.disabled = false;
      status(show(report, provider));
    }
    else if (simulation) {
      button.disabled = !canAssess;
      by("assessment-controls").hidden = !canAssess;
      status(canAssess ? "Pas encore de bilan : touchez ✨ pour le demander." :
        "Bilan indisponible. Votre transcription reste disponible.");
    } else assess(provider, root.dataset.autoEvaluationLabel, {automatic: true});
    if (pendingProvider) assess(pendingProvider, "", {resume: true});
  }
  const post = (call, body) => ({
    method: "POST", credentials: "same-origin", mode: "same-origin", cache: "no-store", redirect: "error", signal: call.signal,
    headers: {"Content-Type": "application/json",
      "X-CSRFToken": window.HeureuxCsrfToken?.() || root.querySelector('[name="csrfmiddlewaretoken"]').value},
    body: JSON.stringify(body)
  });
  // Saving is not aborted by « Nouvel essai », so a quickly dismissed exchange still reaches the account.
  async function save() {
    try {
      const options = post({}, {elapsed, snapshotGrant, rows: rows.map(({speaker, text, interrupted}) =>
        interrupted ? {speaker, text, interrupted: true} : {speaker, text})});
      if (attemptId) options.headers["Idempotency-Key"] = attemptId;
      const response = await fetch(root.dataset.saveUrl, options);
      return response.status === 201 ? (await response.json()).id : null;
    } catch {
      return null;
    }
  }
  async function assess(provider, label, {automatic = false, resume = false, refresh = false} = {}) {
    if (!rows || pending) return;
    const existing = reports.get(provider);
    if (!resume && !refresh && existing && existing.scoreStatus !== "incomplete") {
      status(show(existing, provider));
      return;
    }
    const refreshing = refresh || (resume && refreshControls?.isOutdated(existing));
    const call = pending = new AbortController();
    button.disabled = true;
    if (opinion && by("assessment-result").hidden) by("level").textContent = "Bilan en préparation…";
    if (refreshing) by("assessment").open = true;
    status(refreshing ? "Actualisation du bilan…" : opinion ? "Vous pouvez déjà relire votre transcription ci-dessous." :
      "Préparation de votre bilan…", true, refreshing);
    // Keep an existing report visible until the chosen model returns a result.
    const done = text => {
      if (refreshing || !opinion || by("assessment-result").hidden || !simulation) by("assessment").open = true;
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
        } else {
          done("Impossible d’enregistrer la transcription. Vous pouvez réessayer dans cet onglet.");
          return;
        }
      }
      if (automatic && !grant) {
        by("level").textContent = "Non évalué";
        by("assessment-controls").hidden = !canAssess;
        status(!canAssess ? "Bilan indisponible. Votre transcription reste disponible." :
          picker ? "Choisissez un modèle pour demander le bilan." : "Touchez ✨ pour demander le bilan.");
        return;
      }
      const url = new URL(root.dataset.evaluationUrl, location.href);
      url.searchParams.set("simulation", simulation);
      url.searchParams.set("provider", provider);
      const readStatus = () => fetch(url, {credentials: "same-origin", cache: "no-store", signal: call.signal});
      let response;
      if (resume || (!automatic && !refresh && provider !== displayedProvider)) {
        const cached = await readStatus();
        if (pending !== call) return;
        if (cached.ok || resume) response = cached;
        else if (cached.status !== 404) {
          if ((await cached.json()).status !== "unavailable") throw new Error();
          if (pending !== call) return;
        }
      }
      const useGrant = !response && !refresh && provider === autoProvider && grant;
      if (!response) {
        const options = post(call, {consent: true, simulation, rows: rows.map(({speaker, text}) => ({speaker, text})),
          ...(provider !== "groq" && {provider}), ...(useGrant && {reviewGrant: grant}), ...(refresh && {refresh: true})});
        const action = refresh ? "Actualiser le bilan" : "Demander le bilan";
        response = await (useGrant ? fetch(root.dataset.evaluationUrl, options) :
          window.HeureuxAudioRequest(root.dataset.evaluationUrl, options, {
            title: action, action,
            description: `Transcription envoyée à ${label}${provider.startsWith("copilot-") ? " via GitHub Copilot" : ""} pour le bilan.`,
            confirmBeforeSend: true,
          }));
      }
      let delay = 1000;
      const pollUntil = Date.now() + 300000;
      while (pending === call && response.status === 202 && Date.now() < pollUntil) {
        await new Promise(resolve => setTimeout(resolve, delay));
        if (pending !== call) return;
        response = await readStatus();
        delay = Math.min(8000, delay * 2);
      }
      if (pending !== call) return;
      if (response.status === 202) {
        status("Bilan toujours en préparation. Vous pouvez revenir à cette séance plus tard.");
        return;
      }
      if (!response.ok) {
        if (response.status === 403 && useGrant) grant = null;
        if (response.status === 504) {
          done(late);
          return;
        }
        const detail = response.headers.get("content-type")?.includes("application/json") ? await response.json() : null;
        if (pending !== call) return;
        done(response.status === 401 ? "Reconnectez-vous pour demander votre bilan." :
          typeof detail?.message === "string" ? detail.message :
          typeof detail?.error === "string" ? detail.error :
          `Le service de bilan n’a pas répondu correctement (HTTP ${response.status}). Votre transcription reste disponible.`);
        return;
      }
      const {refreshError, ...report} = await response.json();
      if (pending !== call) return;
      if (typeof report.error === "string") {
        done(report.error);
        return;
      }
      const updated = existing && (existing.graderVersion ?? null) !== (report.graderVersion ?? null);
      const message = show(report, provider);
      const unchanged = refreshing && refreshControls?.isOutdated(report);
      done(refreshError || (unchanged ? "Le bilan n’a pas pu être actualisé. Votre bilan enregistré reste disponible." :
        updated ? "Bilan actualisé." : message));
    } catch (error) {
      if (pending === call) done(error.name === "AbortError" ? (refresh ? "Actualisation annulée." : "Bilan annulé. Aucune note attribuée.") :
        "Impossible de recevoir le bilan. Votre transcription reste disponible.");
    } finally {
      if (pending === call) {
        pending = null;
        button.disabled = false;
      }
    }
  }
  if (!picker) button.onclick = () => assess(root.dataset.evaluationProvider, root.dataset.evaluationProviderLabel);
  window.HeureuxEO2Evaluation = {
    bind, setGrant: value => { grant = value; }, setSnapshotGrant: value => { snapshotGrant = value; },
    clear: () => { grant = snapshotGrant = null; bind(null, null); },
  };
})();
