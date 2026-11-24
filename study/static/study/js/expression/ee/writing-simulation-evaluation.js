(() => {
  "use strict";

  const root = document.querySelector("[data-writing-evaluation]");
  if (!root) return;

  const form = root.querySelector("[data-writing-evaluation-form]");
  const button = root.querySelector("[data-writing-evaluate]");
  const buttonLabel = root.querySelector("[data-writing-evaluate-label]");
  const summaryScore = root.querySelector("[data-writing-summary-score]");
  const status = root.querySelector("[data-writing-evaluation-status]");
  const result = root.querySelector("[data-writing-evaluation-result]");
  const url = root.dataset.evaluationUrl;
  const csrf = root.querySelector("[name=csrfmiddlewaretoken]")?.value;
  let poll;

  const find = (name) => root.querySelector(`[data-writing-${name}]`);
  const setStatus = (text, tone = "") => {
    status.textContent = text;
    status.className = `lv-assessment__status${tone ? ` notice notice--${tone}` : ""}`;
  };
  const setButtonLabel = (label) => {
    if (buttonLabel) {
      buttonLabel.textContent = label;
    } else {
      button.textContent = label;
    }
  };
  const setSummaryScore = (label) => {
    if (summaryScore) summaryScore.textContent = label;
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
    const node = document.createElement("q");
    node.textContent = value;
    return node;
  };

  const showReport = (report) => {
    text(find("verdict"), report.verdict);
    text(
      find("score"),
      `${report.cefr} · ${report.score}/20 · ${report.nclc} · ${report.scoreRange.min}–${report.scoreRange.max} (${report.nclcRange}) · confiance ${report.confidence}`,
    );
    setSummaryScore(`${report.score}/20 · ${report.nclc} · ${report.cefr}`);
    text(find("uncertainty"), report.uncertainty);
    text(find("grade-rationale"), report.gradeRationale);
    const gradeEvidence = find("grade-evidence");
    gradeEvidence.replaceChildren();
    if (report.gradeEvidence?.length) {
      gradeEvidence.append("Preuves : ", report.gradeEvidence.map(quote).reduce((parent, node, index) => {
        if (index) parent.append(", ");
        parent.append(node);
        return parent;
      }, document.createDocumentFragment()));
    }

    list(find("compliance"), report.taskCompliance, (entry) => {
      const li = document.createElement("li");
      li.textContent = `${entry.status} · ${entry.item} — ${entry.evidence}`;
      if (entry.quote) li.append(" ", quote(entry.quote));
      return li;
    });

    const labels = {
      linguistic: "Linguistique",
      pragmatic: "Pragmatique",
      sociolinguistic: "Sociolinguistique",
    };
    list(find("criteria"), report.criteria, (entry) => {
      const row = document.createElement("tr");
      row.insertCell().textContent = labels[entry.key] || entry.key;
      row.insertCell().textContent = entry.rating;
      const evidence = row.insertCell();
      evidence.textContent = entry.evidence;
      if (entry.quotes?.length) evidence.append(" ", entry.quotes.map(quote).reduce((parent, node) => {
        parent.append(node, " ");
        return parent;
      }, document.createDocumentFragment()));
      return row;
    });

    const strengths = find("strengths-section");
    strengths.hidden = !report.strengths.length;
    list(find("strengths"), report.strengths, (entry) => {
      const li = document.createElement("li");
      li.append(quote(entry.quote), ` — ${entry.text}`);
      return li;
    });

    list(find("corrections"), report.corrections, (entry) => {
      const row = document.createElement("tr");
      row.insertCell().textContent = entry.before;
      row.insertCell().textContent = entry.after;
      row.insertCell().textContent = `${entry.type} — ${entry.why}`;
      return row;
    });
    if (!report.corrections.length) {
      const row = document.createElement("tr");
      const cell = row.insertCell();
      cell.colSpan = 3;
      cell.textContent = report.omittedSections?.includes("corrections")
        ? "Certaines corrections n’ont pas pu être vérifiées."
        : "Aucune erreur objective claire relevée.";
      find("corrections").append(row);
    }

    const relevance = find("relevance-section");
    relevance.hidden = !report.relevance.length;
    list(find("relevance"), report.relevance, (entry) => {
      const li = document.createElement("li");
      li.textContent = `${entry.decision} · ${entry.quote || "La phrase"} — ${entry.why}`;
      return li;
    });
    const upgrades = find("upgrades-section");
    upgrades.hidden = !report.upgrades.length;
    list(find("upgrades"), report.upgrades, item);

    const improved = find("improved-section");
    improved.hidden = !report.improvedResponse;
    text(find("improved"), report.improvedResponse);
    text(find("improved-count"), report.improvedResponse ? `${report.improvedWordCount} mots` : "");
    list(find("priorities"), report.priorities, item);

    if (report.omitted) {
      root.querySelector(".writing-validation-warning")?.remove();
      const warning = document.createElement("p");
      warning.className = "muted writing-validation-warning";
      warning.textContent = "Certains éléments ont été écartés car ils ne pouvaient pas être vérifiés à partir de votre réponse.";
      result.prepend(warning);
    }
    result.hidden = false;
  };

  const apply = (payload) => {
    root.dataset.evaluationStatus = payload.status;
    if (payload.status === "ready" && payload.report) {
      showReport(payload.report);
      button.disabled = false;
      setButtonLabel("Réévaluer");
      setStatus("Bilan disponible. Il s’agit d’une estimation d’entraînement, pas d’une note officielle.", "success");
      return;
    }
    if (payload.status === "processing") {
      button.disabled = true;
      setSummaryScore("Bilan en préparation…");
      setStatus("Bilan en préparation…");
      clearTimeout(poll);
      poll = setTimeout(fetchStatus, 1500);
      return;
    }
    button.disabled = false;
    if (payload.status === "unavailable") {
      setSummaryScore("Non évalué");
      setStatus(payload.error || "Le bilan est temporairement indisponible. Vous pouvez réessayer.", "error");
      setButtonLabel("Réessayer");
    } else {
      setSummaryScore("Non évalué");
      setStatus("Bilan non demandé.");
      setButtonLabel("Évaluer ma réponse");
    }
  };

  const fetchStatus = async () => {
    try {
      const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error();
      apply(await response.json());
    } catch {
      button.disabled = false;
      setStatus("Impossible de lire l’état du bilan. Vous pouvez réessayer.", "error");
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    button.disabled = true;
    setStatus("Bilan en préparation…");
    try {
      const response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrf, "Content-Type": "application/json" },
        body: JSON.stringify({ consent: true }),
      });
      if (!response.ok && response.status !== 202) throw new Error();
      apply(await response.json());
    } catch {
      button.disabled = false;
      setStatus("Le bilan est temporairement indisponible. Votre réponse reste disponible.", "error");
    }
  });

  if (root.dataset.evaluationStatus === "ready" || root.dataset.evaluationStatus === "processing") {
    fetchStatus();
  }
})();
