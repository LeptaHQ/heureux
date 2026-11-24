(() => {
  "use strict";

  const form = document.getElementById("writing-evaluation-form");
  if (!form) return;

  const root = form.closest(".lv-report");
  const by = (id) => document.getElementById(`lv-${id}`);
  const button = by("assess");
  const level = by("level");
  const result = by("assessment-result");
  const menu = document.getElementById("writing-models");
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
    if (menu) return;
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
    text(find("verdict"), report.verdict).hidden = !report.verdict;
    const confidence = report.confidence ? ` · confiance ${report.confidence}` : "";
    text(
      find("score"),
      `${report.cefr} · ${report.score}/20 · ${report.nclc} · ${report.scoreRange.min}–${report.scoreRange.max} (${report.nclcRange})${confidence}`,
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
    find("priorities").closest(".lv-next-step").hidden = !report.priorities.length;

    root.querySelector(".writing-validation-warning")?.remove();
    if (report.omitted) {
      const warning = document.createElement("p");
      warning.className = "muted writing-validation-warning";
      warning.textContent = "Certains détails du bilan ont été abrégés ou écartés. La note s’appuie sur les passages vérifiés.";
      result.prepend(warning);
    }
    result.hidden = false;
  };

  const apply = (payload) => {
    if (payload.status === "ready" && payload.report) {
      showReport(payload.report);
      if (!menu) {
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
      if (menu) endpoint.searchParams.set("provider", form.dataset.evaluationProvider);
      const response = await fetch(endpoint, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error();
      apply(await response.json());
    } catch {
      setStatus("Impossible de lire l’état du bilan. Vous pouvez réessayer.");
      setButtonLabel("Réessayer");
    }
  };

  const setMenu = (open) => {
    menu.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
  };
  if (menu) {
    button.addEventListener("click", () => setMenu(menu.hidden));
    document.addEventListener("click", (event) => {
      if (!menu.hidden && !menu.contains(event.target) && !button.contains(event.target)) setMenu(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !menu.hidden) {
        event.preventDefault();
        setMenu(false);
        button.focus();
      }
    });
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const selected = event.submitter;
    if (menu) {
      if (selected?.name !== "provider") return;
      setMenu(false);
      if (selected.value !== form.dataset.evaluationProvider) {
        form.dataset.evaluationProvider = selected.value;
        menu.querySelectorAll("button").forEach((choice) =>
          choice.setAttribute("aria-pressed", String(choice === selected)));
        result.hidden = true;
        find("review").hidden = true;
        by("proposal").hidden = true;
        level.classList.remove("lv-level--scored");
        level.textContent = "Non évalué";
      }
    }
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
  });

  if (form.dataset.evaluationStatus !== "not_requested") {
    fetchStatus();
  }
})();
