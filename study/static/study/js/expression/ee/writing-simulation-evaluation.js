(() => {
  "use strict";

  const form = document.getElementById("writing-evaluation-form");
  if (!form) return;

  const root = form.closest(".lv-report");
  const by = (id) => document.getElementById(`lv-${id}`);
  const button = by("assess");
  const level = by("level");
  const result = by("assessment-result");
  const picker = window.HeureuxAssessmentPicker(button, (provider) => {
    if (provider !== form.dataset.evaluationProvider) {
      form.dataset.evaluationProvider = provider;
      picker.select(provider);
      result.hidden = true;
      find("review").hidden = true;
      by("proposal").hidden = true;
      level.classList.remove("lv-level--scored");
      level.textContent = "Non évalué";
    }
    requestEvaluation();
  });
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
    if (picker) return;
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
  const citedNotes = (name, entries) => {
    find(`${name}-section`).hidden = !entries.length;
    list(find(name), entries, (entry) => {
      const li = document.createElement("li");
      li.append(quote(entry.quote), ` — ${entry.text}`);
      return li;
    });
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

  const showReport = (report) => {
    text(find("verdict"), report.verdict).hidden = !report.verdict;
    const confidenceLabels = { High: "élevée", Medium: "moyenne", Low: "faible" };
    const confidence = confidenceLabels[report.confidence];
    text(
      find("score"),
      `Fourchette indicative : ${report.scoreRange.min}–${report.scoreRange.max}/20 (${report.nclcRange})${confidence ? ` · confiance ${confidence}` : ""}`,
    );
    level.textContent = `${report.score}/20 · ${report.nclc} · ${report.cefr}`;
    level.classList.add("lv-level--scored");
    text(find("uncertainty"), report.uncertainty).hidden = !report.uncertainty;
    text(find("grade-rationale"), report.gradeRationale).hidden = !report.gradeRationale;
    const gradeEvidence = find("grade-evidence");
    gradeEvidence.replaceChildren();
    if (report.gradeEvidence?.length) {
      gradeEvidence.append("Preuves : ", report.gradeEvidence.map(quote).reduce((parent, node, index) => {
        if (index) parent.append(", ");
        parent.append(node);
        return parent;
      }, document.createDocumentFragment()));
    }

    const statuses = { Met: "Satisfait", "Partly met": "Partiel", Missing: "Manquant" };
    list(find("compliance"), report.taskCompliance, (entry) => {
      const li = document.createElement("li");
      li.append(text(document.createElement("strong"), entry.item), ` · ${statuses[entry.status] || entry.status} — ${entry.evidence}`);
      if (entry.quote) li.append(" ", quote(entry.quote));
      return li;
    });

    const labels = {
      linguistic: "Linguistique",
      pragmatic: "Pragmatique",
      sociolinguistic: "Sociolinguistique",
    };
    const ratings = ["Limited", "Developing", "Adequate", "Strong", "Excellent"];
    list(find("criteria"), report.criteria, (entry) => {
      const row = document.createElement("tr");
      const heading = document.createElement("th");
      heading.scope = "row";
      heading.textContent = labels[entry.key] || entry.key;
      row.append(heading);
      const points = ratings.indexOf(entry.rating) + 1;
      const mark = row.insertCell();
      mark.textContent = points ? `${points}/5` : "Non évalué";
      if (points) {
        mark.className = "lv-criterion-mark";
        mark.style.setProperty("--lv-mark", `${points * 20}%`);
      }
      const evidence = row.insertCell();
      evidence.textContent = entry.evidence;
      if (entry.quotes?.length) evidence.append(" ", entry.quotes.map(quote).reduce((parent, node) => {
        parent.append(node, " ");
        return parent;
      }, document.createDocumentFragment()));
      return row;
    });

    citedNotes("verbs", report.verbFeedback || []);
    citedNotes("strengths", report.strengths);

    list(find("corrections"), report.corrections, correction);
    const correctionsNote = find("corrections-note");
    correctionsNote.hidden = Boolean(report.corrections.length);
    correctionsNote.textContent = report.omittedSections?.includes("corrections")
      ? "Certaines corrections n’ont pas pu être vérifiées."
      : "Aucune erreur objective claire relevée.";
    find("review").hidden = false;

    const relevance = find("relevance-section");
    relevance.hidden = !report.relevance.length;
    const decisions = { Keep: "Garder", Cut: "Retirer", Simplify: "Simplifier" };
    list(find("relevance"), report.relevance, (entry) => {
      const li = document.createElement("li");
      li.append(text(document.createElement("strong"), decisions[entry.decision] || entry.decision), " · ",
        entry.quote ? quote(entry.quote) : "La phrase", ` — ${entry.why}`);
      return li;
    });
    const upgrades = find("upgrades-section");
    upgrades.hidden = !report.upgrades.length;
    list(find("upgrades"), report.upgrades, item);

    const paragraphs = (value) => value.split(/\r?\n[ \t]*\r?\n/).map((part) => text(document.createElement("p"), part));
    const proposal = report.improvedParts?.length
      ? report.improvedParts.flatMap((part, index) => [
        text(document.createElement("h3"), index ? "Point de vue argumenté" : "Synthèse neutre"),
        ...paragraphs(part),
      ])
      : report.improvedResponse ? paragraphs(report.improvedResponse) : [];
    by("proposal-lines").replaceChildren(...proposal);
    by("proposal").hidden = !proposal.length;
    text(by("proposal-count"), proposal.length ? `${report.improvedWordCount} mots` : "");
    list(find("priorities"), report.priorities, item);
    find("priorities").closest(".lv-next-step").hidden = !report.priorities.length;

    root.querySelector(".writing-validation-warning")?.remove();
    if (report.omitted) {
      const warning = document.createElement("p");
      warning.className = "muted writing-validation-warning";
      warning.textContent = "Certains détails du bilan ont été abrégés ou écartés. La note s’appuie sur les passages vérifiés.";
      result.append(warning);
    }
    result.hidden = false;
  };

  const apply = (payload) => {
    if (payload.status === "ready" && payload.report) {
      showReport(payload.report);
      if (!picker) {
        button.closest(".lv-assessment__action").hidden = true;
        document.getElementById("writing-evaluation-disclosure").hidden = true;
      }
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
      const endpoint = new URL(url, location.href);
      if (picker) endpoint.searchParams.set("provider", form.dataset.evaluationProvider);
      const response = await fetch(endpoint, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error();
      apply(await response.json());
    } catch {
      setStatus("Impossible de lire l’état du bilan. Vous pouvez réessayer.");
      setButtonLabel("Réessayer");
    }
  };

  async function requestEvaluation() {
    by("assessment").open = true;
    setStatus("Bilan en préparation…", true);
    try {
      const response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrf, "Content-Type": "application/json" },
        body: JSON.stringify({ consent: true, provider: form.dataset.evaluationProvider }),
      });
      if (response.status === 409) {
        setStatus((await response.json()).error);
        return;
      }
      if (!response.ok) throw new Error();
      apply(await response.json());
    } catch {
      setStatus("Le bilan est temporairement indisponible. Votre réponse reste disponible.");
      setButtonLabel("Réessayer");
    }
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    requestEvaluation();
  });

  if (form.dataset.evaluationStatus !== "not_requested") {
    fetchStatus();
  }
})();
