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
  const csrf = form.elements.csrfmiddlewaretoken.value;
  let poll, pollDelay = 1500;

  const find = (name) => root.querySelector(`[data-writing-${name}]`);
  const setStatus = (message, busy = false) => {
    if (button) {
      button.disabled = busy;
      button.setAttribute("aria-busy", String(busy));
    }
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

  const showReport = (report, provider) => {
    const passages = new Map();
    const evidence = find("evidence");
    const passageId = (number) => `lv-writing-passage-${provider}-${number}`;
    const cite = (target, excerpts) => {
      for (const excerpt of new Set(excerpts)) {
        if (!excerpt) continue;
        if (!passages.has(excerpt)) passages.set(excerpt, passages.size + 1);
        if (!target) continue;
        const number = passages.get(excerpt);
        const link = text(document.createElement("a"), `[${number}]`);
        link.className = "lv-citation";
        link.href = `#${passageId(number)}`;
        link.setAttribute("aria-label", `Voir le passage cité ${number}`);
        link.onclick = () => { evidence.open = true; };
        target.append(" ", link);
      }
    };
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
    const statuses = { Met: "Satisfait", "Partly met": "Partiel", Missing: "Manquant" };
    list(find("compliance"), report.taskCompliance, (entry) => {
      const li = document.createElement("li");
      li.append(text(document.createElement("strong"), entry.item), ` · ${statuses[entry.status] || entry.status} — ${entry.evidence}`);
      cite(li, [entry.quote]);
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
      cite(text(row.insertCell(), entry.evidence), entry.quotes);
      return row;
    });

    const rationale = text(find("grade-rationale"), report.gradeRationale);
    rationale.hidden = !report.gradeRationale;
    cite(rationale.hidden ? null : rationale, report.gradeEvidence);

    const notes = [...report.strengths, ...(report.verbFeedback || [])];
    find("strengths-section").hidden = !notes.length;
    list(find("strengths"), notes, (entry) => {
      const li = item(entry.text);
      cite(li, [entry.quote]);
      return li;
    });

    list(find("passages"), [...passages], ([excerpt, number]) => {
      const li = document.createElement("li");
      li.id = passageId(number);
      li.append(quote(excerpt));
      return li;
    });
    evidence.hidden = !passages.size;
    evidence.open = false;

    list(find("corrections"), report.corrections, correction);
    const correctionsNote = find("corrections-note");
    correctionsNote.hidden = Boolean(report.corrections.length);
    correctionsNote.textContent = report.omittedSections?.includes("corrections")
      ? "Certaines corrections n’ont pas pu être vérifiées."
      : "Aucune erreur objective claire relevée.";

    const decisions = { Cut: "Retirer", Simplify: "Simplifier" };
    const suggestions = [
      ...report.relevance.filter((entry) => entry.decision !== "Keep").map((entry) => {
        const li = document.createElement("li");
        li.append(text(document.createElement("strong"), decisions[entry.decision] || entry.decision), " · ",
          entry.quote ? quote(entry.quote) : "La phrase", ` — ${entry.why}`);
        return li;
      }),
      ...report.upgrades.map(item),
    ];
    find("suggestions-section").hidden = !suggestions.length;
    find("suggestions").replaceChildren(...suggestions);

    const paragraphs = (value) => value.split(/\r?\n[ \t]*\r?\n/).map((part) => text(document.createElement("p"), part));
    const proposal = report.improvedParts?.length
      ? report.improvedParts.flatMap((part, index) => [
        text(document.createElement("h3"), index ? "Point de vue argumenté" : "Synthèse neutre"),
        ...paragraphs(part),
      ])
      : report.improvedResponse ? paragraphs(report.improvedResponse) : [];
    by("proposal-lines").replaceChildren(...proposal);
    by("proposal-rewrite").hidden = !proposal.length;
    text(by("proposal-count"), proposal.length ? `${report.improvedWordCount} mots` : "");
    by("proposal").hidden = false;
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

  const apply = (payload, provider) => {
    clearTimeout(poll);
    if (payload.status !== "processing") pollDelay = 1500;
    if (payload.status === "ready" && payload.report) {
      showReport(payload.report, provider);
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
      pollDelay = Math.min(8000, pollDelay * 2);
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

  const fetchStatus = async (provider) => {
    try {
      const endpoint = new URL(url, location.href);
      endpoint.searchParams.set("provider", provider);
      const response = await fetch(endpoint, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error();
      apply(await response.json(), provider);
    } catch {
      setStatus("Impossible de lire l’état du bilan. Vous pouvez réessayer.");
      setButtonLabel("Réessayer");
    }
  };

  async function requestEvaluation(provider = initialProvider) {
    clearTimeout(poll);
    pollDelay = 1500;
    by("assessment").open = true;
    setStatus("Bilan en préparation…", true);
    try {
      const response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRFToken": csrf, "Content-Type": "application/json" },
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

  if (form.dataset.evaluationStatus !== "not_requested") {
    if (button) button.disabled = true;
    fetchStatus(initialProvider);
  }
})();
