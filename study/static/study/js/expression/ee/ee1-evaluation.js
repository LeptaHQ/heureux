(() => {
  "use strict";

  const root = document.querySelector("[data-ee1-evaluation]");
  if (!root) return;

  const form = root.querySelector("[data-ee1-evaluation-form]");
  const button = root.querySelector("[data-ee1-evaluate]");
  const status = root.querySelector("[data-ee1-evaluation-status]");
  const result = root.querySelector("[data-ee1-evaluation-result]");
  const url = root.dataset.evaluationUrl;
  const csrf = root.querySelector("[name=csrfmiddlewaretoken]")?.value;
  let poll;

  const setStatus = (text, tone = "") => {
    status.textContent = text;
    status.className = `notice${tone ? ` notice--${tone}` : ""}`;
  };

  const appendText = (parent, text) => {
    const node = document.createElement("span");
    node.textContent = text;
    parent.append(node);
    return node;
  };

  const list = (target, values, render) => {
    target.replaceChildren(...values.map(render));
  };

  const showReport = (report) => {
    root.querySelector("[data-ee1-verdict]").textContent = report.verdict;
    root.querySelector("[data-ee1-score]").textContent =
      `${report.cefr} · ${report.score}/20 · ${report.nclc} · ${report.scoreRange.min}–${report.scoreRange.max} (${report.nclcRange}) · confiance ${report.confidence}`;
    root.querySelector("[data-ee1-uncertainty]").textContent = report.uncertainty;
    root.querySelector("[data-ee1-grade-rationale]").textContent = report.gradeRationale;

    list(root.querySelector("[data-ee1-compliance]"), report.taskCompliance, (item) => {
      const li = document.createElement("li");
      li.className = `ee1-compliance ee1-compliance--${item.status.toLowerCase().replace(" ", "-")}`;
      appendText(li, `${item.status} · ${item.item} — ${item.evidence}`);
      if (item.quote) {
        const quote = document.createElement("q");
        quote.textContent = item.quote;
        li.append(" ", quote);
      }
      return li;
    });

    const labels = {
      linguistic: "Linguistique",
      pragmatic: "Pragmatique",
      sociolinguistic: "Sociolinguistique",
    };
    list(root.querySelector("[data-ee1-criteria]"), report.criteria, (item) => {
      const row = document.createElement("tr");
      appendText(row.insertCell(), labels[item.key] || item.key);
      appendText(row.insertCell(), item.rating);
      appendText(row.insertCell(), item.evidence);
      return row;
    });

    const strengthsSection = root.querySelector("[data-ee1-strengths-section]");
    strengthsSection.hidden = !report.strengths.length;
    list(root.querySelector("[data-ee1-strengths]"), report.strengths, (item) => {
      const li = document.createElement("li");
      appendText(li, `${item.quote} — ${item.text}`);
      return li;
    });

    list(root.querySelector("[data-ee1-corrections]"), report.corrections, (item) => {
      const row = document.createElement("tr");
      appendText(row.insertCell(), item.before);
      appendText(row.insertCell(), item.after);
      appendText(row.insertCell(), `${item.type} — ${item.why}`);
      return row;
    });
    if (!report.corrections.length) {
      const row = document.createElement("tr");
      const cell = row.insertCell();
      cell.colSpan = 3;
      cell.textContent = report.omittedSections?.includes("corrections")
        ? "Certaines corrections n’ont pas pu être vérifiées."
        : "Aucune erreur objective claire relevée.";
      root.querySelector("[data-ee1-corrections]").append(row);
    }
    if (report.omitted) {
      root.querySelector(".ee1-validation-warning")?.remove();
      const warning = document.createElement("p");
      warning.className = "muted ee1-validation-warning";
      warning.textContent = "Certains éléments ont été écartés car ils ne pouvaient pas être vérifiés à partir de votre réponse.";
      root.querySelector("[data-ee1-evaluation-result]").prepend(warning);
    }

    const relevanceSection = root.querySelector("[data-ee1-relevance-section]");
    relevanceSection.hidden = !report.relevance.length;
    list(root.querySelector("[data-ee1-relevance]"), report.relevance, (item) => {
      const li = document.createElement("li");
      appendText(li, `${item.decision} · ${item.quote || "La phrase"} — ${item.why}`);
      return li;
    });

    const upgradesSection = root.querySelector("[data-ee1-upgrades-section]");
    upgradesSection.hidden = !report.upgrades.length;
    list(root.querySelector("[data-ee1-upgrades]"), report.upgrades, (item) => {
      const li = document.createElement("li");
      appendText(li, item);
      return li;
    });

    const improvedSection = root.querySelector("[data-ee1-improved-section]");
    improvedSection.hidden = !report.improvedResponse;
    root.querySelector("[data-ee1-improved]").textContent = report.improvedResponse;
    root.querySelector("[data-ee1-improved-count]").textContent = report.improvedResponse
      ? `${report.improvedWordCount} mots`
      : "";
    list(root.querySelector("[data-ee1-priorities]"), report.priorities, (item) => {
      const li = document.createElement("li");
      appendText(li, item);
      return li;
    });
    result.hidden = false;
  };

  const apply = (payload) => {
    root.dataset.evaluationStatus = payload.status;
    if (payload.status === "ready" && payload.report) {
      showReport(payload.report);
      button.disabled = false;
      button.textContent = "Réévaluer";
      setStatus("Bilan disponible. Il s’agit d’une estimation d’entraînement, pas d’une note officielle.", "success");
      return;
    }
    if (payload.status === "processing") {
      button.disabled = true;
      setStatus("Bilan en préparation…");
      clearTimeout(poll);
      poll = setTimeout(fetchStatus, 1500);
      return;
    }
    button.disabled = false;
    if (payload.status === "unavailable") {
      setStatus(payload.error || "Le bilan est temporairement indisponible. Vous pouvez réessayer.", "error");
      button.textContent = "Réessayer";
    } else {
      setStatus("Bilan non demandé.");
      button.textContent = "Évaluer ma réponse";
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
