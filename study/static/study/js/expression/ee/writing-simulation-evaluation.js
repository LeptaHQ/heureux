(() => {
  "use strict";

  const form = document.getElementById("writing-evaluation-form");
  if (!form) return;

  const root = form.closest(".lv-report");
  const by = (id) => document.getElementById(`lv-${id}`);
  const button = by("assess");
  const level = by("level");
  const result = by("assessment-result");
  const url = form.dataset.evaluationUrl;
  const csrf = form.elements.csrfmiddlewaretoken.value;
  let poll;

  const find = (name) => root.querySelector(`[data-writing-${name}]`);
  const setStatus = (message, busy = false) => {
    button.disabled = busy;
    button.setAttribute("aria-busy", String(busy));
    by("assessment-status").textContent = message;
  };
  const setButtonLabel = (label) => {
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
    level.textContent = `${report.score}/20 · ${report.nclc} · ${report.cefr}`;
    level.classList.add("lv-level--scored");
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
      const heading = document.createElement("th");
      heading.scope = "row";
      heading.textContent = labels[entry.key] || entry.key;
      row.append(heading);
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
    find("review").hidden = false;

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

    const paragraphs = report.improvedResponse ? report.improvedResponse.split(/\r?\n[ \t]*\r?\n/) : [];
    list(by("proposal-lines"), paragraphs, (value) => text(document.createElement("p"), value));
    by("proposal").hidden = !paragraphs.length;
    text(by("proposal-count"), paragraphs.length ? `${report.improvedWordCount} mots` : "");
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
    if (payload.status === "ready" && payload.report) {
      showReport(payload.report);
      by("assessment-controls").hidden = true;
      setStatus("");
      return;
    }
    if (payload.status === "processing") {
      setStatus("Bilan en préparation…", true);
      clearTimeout(poll);
      poll = setTimeout(fetchStatus, 1500);
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

  const fetchStatus = async () => {
    try {
      const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error();
      apply(await response.json());
    } catch {
      setStatus("Impossible de lire l’état du bilan. Vous pouvez réessayer.");
      setButtonLabel("Réessayer");
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setStatus("Bilan en préparation…", true);
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
      setStatus("Le bilan est temporairement indisponible. Votre réponse reste disponible.");
      setButtonLabel("Réessayer");
    }
  });

  if (form.dataset.evaluationStatus !== "not_requested") {
    fetchStatus();
  }
})();
