(() => {
  "use strict";

  const form = document.getElementById("writing-evaluation-form");
  if (!form) return;

  const root = form.closest(".lv-report");
  const by = (id) => document.getElementById(`lv-${id}`);
  const button = by("assess");
  const level = by("level");
  const result = by("assessment-result");
  const picker = button && window.HeureuxAssessmentPicker(button, (provider) => requestEvaluation(provider));
  const initialProvider = form.dataset.evaluationProvider;
  const url = form.dataset.evaluationUrl;
  const find = (name) => root.querySelector(`[data-writing-${name}]`);
  const editor = find("proposal-editor");
  const editButton = find("proposal-edit");
  const editStatus = find("proposal-status");
  const editFields = [...editor.querySelectorAll("textarea")];
  const fieldset = editor.querySelector("fieldset");
  const copySource = document.getElementById("writing-proposal-copy");
  const copyButton = root.querySelector('[data-prompt-copy-source="writing-proposal-copy"]');
  const csrfToken = () => window.HeureuxCsrfToken?.() || form.elements.csrfmiddlewaretoken.value;
  let poll, pollDelay = 1500, awaitingReport = false;
  let current, proposalParts;

  const syncControls = () => {
    const editing = !editor.hidden;
    if (button) button.disabled = awaitingReport || editing;
    editButton.disabled = awaitingReport || editing;
    editButton.setAttribute("aria-expanded", String(editing));
    copyButton.hidden = editing;
  };
  const setStatus = (message, busy = false) => {
    awaitingReport = busy;
    syncControls();
    if (button) button.setAttribute("aria-busy", String(busy));
    by("assessment-status").textContent = message;
  };
  const setButtonLabel = (label) => {
    if (!button || picker) return;
    button.setAttribute("aria-label", label);
    button.title = label;
  };
  const text = (parent, value) => {
    parent.textContent = value || "";
    return parent;
  };
  const list = (target, values, render) => {
    target.replaceChildren(...values.map(render));
  };
  const item = (value) => {
    const li = document.createElement("li");
    li.textContent = value;
    return li;
  };
  const quote = (value) => {
    const node = text(document.createElement("q"), value);
    node.lang = "fr";
    return node;
  };
  const correction = (entry) => {
    const li = document.createElement("li");
    const change = document.createElement("div");
    change.className = "lv-mark";
    change.lang = "fr";
    const original = text(document.createElement("span"), "Original : ");
    const replacement = text(document.createElement("span"), "Correction : ");
    original.className = replacement.className = "sr-only";
    const arrow = text(document.createElement("span"), " → ");
    arrow.setAttribute("aria-hidden", "true");
    change.append(original, text(document.createElement("del"), entry.before), arrow, replacement,
      entry.after ? text(document.createElement("ins"), entry.after) : text(document.createElement("span"), "À retirer"));
    li.append(text(document.createElement("strong"), entry.type), change, text(document.createElement("p"), entry.why));
    return li;
  };

  const renderProposal = (report, edit) => {
    const paragraphs = (value) => value.split(/\r?\n[ \t]*\r?\n/).map((part) => text(document.createElement("p"), part));
    proposalParts = edit?.parts || (report.improvedParts?.length
      ? report.improvedParts : report.improvedResponse ? [report.improvedResponse] : []);
    const proposal = proposalParts.length === 2
      ? proposalParts.flatMap((part, index) => [
        text(document.createElement("h3"), index ? "Point de vue argumenté" : "Synthèse neutre"),
        ...paragraphs(part),
      ])
      : proposalParts.flatMap(paragraphs);
    by("proposal-lines").replaceChildren(...proposal);
    by("proposal-rewrite").hidden = !proposal.length;
    editButton.hidden = proposalParts.length !== editFields.length;
    text(copySource, proposal.length ? JSON.stringify(proposalParts.join("\n\n")) : "");
    text(by("proposal-rewrite-title"), edit ? "Version personnalisée" :
      report.proposalFromCorrections ? "Version corrigée" : "Version révisée");
    const rewriteNote = find("rewrite-note");
    text(rewriteNote, edit ? "Vous avez modifié cette version. L’estimation porte toujours sur votre réponse originale." :
      report.proposalFromSuggestions ? "Corrections et reformulations appliquées. La réponse à la consigne peut rester incomplète." :
      report.proposalFromCorrections ? "Corrections appliquées. La réponse à la consigne peut rester incomplète." :
      !proposal.length ? "Aucune version révisée n’a pu être vérifiée." :
      report.proposalTarget ? `Exemple d’entraînement · objectif ${report.proposalTarget}.` : "");
    rewriteNote.hidden = !rewriteNote.textContent;
    text(by("proposal-count"), proposal.length ? `${edit?.wordCount ?? report.improvedWordCount} mots` : "");
  };

  const toggleEditor = (open) => {
    editor.hidden = !open;
    by("proposal-lines").hidden = open;
    syncControls();
    (open ? editFields[0] : editButton).focus();
  };
  editButton.addEventListener("click", () => {
    picker?.close();
    editFields.forEach((field, index) => { field.value = proposalParts[index]; });
    text(editStatus, "");
    toggleEditor(true);
  });
  find("proposal-cancel").addEventListener("click", () => {
    text(editStatus, "");
    toggleEditor(false);
  });
  editor.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (editor.hidden || fieldset.disabled) return;
    const parts = editFields.map((field) => field.value);
    const {report, provider} = current;
    const saveError = "Impossible d’enregistrer la proposition. Vos modifications sont toujours dans l’éditeur.";
    fieldset.disabled = true;
    text(editStatus, "Enregistrement…");
    try {
      const response = await fetch(url, {
        method: "PATCH",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken(), "Content-Type": "application/json" },
        body: JSON.stringify({ provider, parts }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.proposalEdit) {
        text(editStatus, payload.error || saveError);
        return;
      }
      renderProposal(report, payload.proposalEdit);
      toggleEditor(false);
      text(editStatus, "Votre version a été enregistrée.");
    } catch {
      text(editStatus, saveError);
    } finally {
      fieldset.disabled = false;
    }
  });

  const showReport = (report, provider, edit) => {
    current = {report, provider};
    text(editStatus, "");
    text(find("verdict"), report.verdict).hidden = !report.verdict;
    const {min, max} = report.scoreRange || {min: report.score, max: report.score};
    level.textContent = min === max ? `${min}/20` : `${min}–${max}/20`;
    text(find("score"), report.nclcRange ? `Repère sur cette tâche : ${report.nclcRange}` : "").hidden = !report.nclcRange;
    level.classList.add("lv-level--scored");
    text(find("uncertainty"), report.uncertainty).hidden = !report.uncertainty;
    const statuses = { Met: "Satisfait", "Partly met": "Partiel", Missing: "Manquant" };
    list(find("compliance"), report.taskCompliance, (entry) => {
      const li = document.createElement("li");
      li.append(text(document.createElement("strong"), entry.item), ` · ${statuses[entry.status] || entry.status} — ${entry.evidence}`);
      return li;
    });

    const labels = {
      linguistic: "Linguistique",
      pragmatic: "Pragmatique",
      sociolinguistic: "Sociolinguistique",
    };
    list(find("criteria"), report.criteria, (entry) => {
      const row = document.createElement("tr");
      const heading = document.createElement("th");
      heading.scope = "row";
      heading.textContent = labels[entry.key] || entry.key;
      row.append(heading);
      const rating = text(row.insertCell(), entry.rating || "Non évalué");
      if (entry.rating) rating.lang = "en";
      text(row.insertCell(), entry.evidence);
      return row;
    });

    text(find("grade-rationale"), report.gradeRationale).hidden = !report.gradeRationale;

    const notes = [...report.strengths, ...(report.verbFeedback || [])];
    find("strengths-section").hidden = !notes.length;
    list(find("strengths"), notes, (entry) => item(entry.text));

    list(find("corrections"), report.corrections, correction);
    const correctionsNote = find("corrections-note");
    correctionsNote.hidden = Boolean(report.corrections.length);
    correctionsNote.textContent = report.omittedSections?.includes("corrections")
      ? "Certaines corrections n’ont pas pu être vérifiées."
      : "Aucune erreur objective claire relevée.";

    const decisions = { Develop: "Développer", Cut: "Retirer", Simplify: "Simplifier", Rephrase: "Reformuler" };
    const suggestions = [
      ...report.relevance.filter((entry) => entry.decision !== "Keep").map((entry) => {
        const li = document.createElement("li");
        li.append(text(document.createElement("strong"), decisions[entry.decision] || entry.decision), " · ",
          entry.quote ? quote(entry.quote) : "La phrase");
        if (entry.replacement) li.append(" → ", quote(entry.replacement));
        li.append(` — ${entry.why}`);
        return li;
      }),
      ...report.upgrades.map(item),
    ];
    find("suggestions-section").hidden = !suggestions.length;
    find("suggestions").replaceChildren(...suggestions);

    renderProposal(report, edit);
    by("proposal").hidden = false;
    list(find("priorities"), report.priorities, item);
    find("priorities").closest(".lv-next-step").hidden = !report.priorities.length;

    root.querySelector(".writing-validation-warning")?.remove();
    if (report.omitted) {
      const warning = document.createElement("p");
      warning.className = "muted writing-validation-warning";
      warning.textContent = "Certains détails du bilan ont été abrégés ou écartés.";
      result.append(warning);
    }
    result.hidden = false;
  };

  const apply = (payload, provider) => {
    clearTimeout(poll);
    if (payload.status !== "processing") pollDelay = 1500;
    if (payload.status === "ready" && payload.report) {
      showReport(payload.report, provider, payload.proposalEdit);
      picker?.select(provider);
      if (button && !picker) {
        button.closest(".lv-assessment__action").hidden = true;
        const disclosure = document.getElementById("writing-evaluation-disclosure");
        if (disclosure) disclosure.hidden = true;
      }
      setStatus("");
      return;
    }
    if (payload.status === "processing") {
      setStatus("Bilan en préparation…", true);
      poll = setTimeout(() => fetchStatus(provider), pollDelay);
      pollDelay = Math.min(4000, pollDelay * 2);
      return;
    }
    if (payload.status === "unavailable") {
      setStatus(payload.error || "Le bilan est temporairement indisponible. Vous pouvez réessayer.");
      setButtonLabel("Réessayer");
    } else {
      setStatus("Bilan non demandé.");
      setButtonLabel("Évaluer ma réponse");
    }
  };

  const statusReadError = "Impossible de lire l’état du bilan. Vous pouvez réessayer.";
  const fetchStatus = async (provider, failures = 0) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const endpoint = new URL(url, location.href);
      endpoint.searchParams.set("provider", provider);
      const response = await fetch(endpoint, { credentials: "same-origin", cache: "no-store", signal: controller.signal });
      if (response.redirected || response.status === 401) {
        setStatus("Reconnectez-vous à Heureux pour consulter le bilan.");
        setButtonLabel("Vérifier le bilan");
        return;
      }
      if (!response.ok) {
        if (response.status >= 500 || response.status === 429) throw new Error();
        const payload = await response.json().catch(() => null);
        setStatus(payload?.error || statusReadError);
        setButtonLabel("Réessayer");
        return;
      }
      apply(await response.json(), provider);
    } catch {
      if (failures < 3) {
        setStatus("Vérification de l’état du bilan…", true);
        poll = setTimeout(() => fetchStatus(provider, failures + 1), 1500 * 2 ** failures);
        return;
      }
      setStatus(statusReadError);
      setButtonLabel("Réessayer");
    } finally {
      clearTimeout(timeout);
    }
  };

  async function requestEvaluation(provider = initialProvider) {
    if (awaitingReport || !editor.hidden) return;
    clearTimeout(poll);
    pollDelay = 1500;
    by("assessment").open = true;
    setStatus("Bilan en préparation…", true);
    try {
      const response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken(), "Content-Type": "application/json" },
        body: JSON.stringify({ consent: true, provider }),
      });
      if (response.status === 409) {
        setStatus((await response.json()).error);
        return;
      }
      if (!response.ok) throw new Error();
      apply(await response.json(), provider);
    } catch {
      setStatus("Le bilan est temporairement indisponible. Votre réponse reste disponible.");
      setButtonLabel("Réessayer");
    }
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    requestEvaluation();
  });

  const saved = document.getElementById("writing-saved-evaluation");
  if (saved) {
    apply(JSON.parse(saved.textContent), initialProvider);
  } else if (form.dataset.evaluationStatus !== "not_requested") {
    setStatus(by("assessment-status").textContent, true);
    fetchStatus(initialProvider);
  }
})();
