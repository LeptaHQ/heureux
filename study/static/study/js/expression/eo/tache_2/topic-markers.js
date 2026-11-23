(() => {
  "use strict";
  const results = document.getElementById("eo2-topic-results");
  const toast = document.querySelector("[data-subject-progress-toast]");
  if (!results || !toast || !window.fetch) return;
  let pending = 0, revision = 0, refreshNeeded = false;

  function message(text) {
    toast.textContent = text;
    toast.classList.toggle("hidden", !text);
  }

  function mark(form, checked) {
    const button = form.querySelector("button");
    const done = form.elements.field.value === "done";
    form.elements.value.value = checked ? "0" : "1";
    form.classList.toggle(done ? "is-complete" : "is-bookmarked", checked);
    button.setAttribute(done ? "aria-checked" : "aria-pressed", String(checked));
    if (done) {
      button.setAttribute("aria-label", (checked ? "Marquer ce sujet comme non terminé : " :
        "Marquer ce sujet comme terminé : ") + button.dataset.subjectLabel);
      button.title = checked ? "Sujet terminé" : "Marquer comme terminé";
    } else {
      button.title = checked ? "Retirer des sujets à refaire" : "Garder dans les sujets à refaire";
    }
  }

  function count(field, delta) {
    const total = results.querySelector(`[data-total="${field}"]`);
    if (!total) return;
    const n = Number(total.textContent) + delta;
    total.textContent = String(n);
    if (field === "done") results.querySelector("[data-done-label]").textContent = n > 1 ? "terminés" : "terminé";
  }

  async function refreshFilteredList(version) {
    try {
      const response = await fetch(location.href, {
        headers: {"X-Requested-With": "fetch"}, cache: "no-store", redirect: "error"
      });
      if (!response.ok) throw new Error();
      const doc = new DOMParser().parseFromString(await response.text(), "text/html");
      const fresh = doc.getElementById(results.id);
      if (!fresh) throw new Error();
      // A newer save may have started while this filtered page was being rendered.
      if (version !== revision) return;
      const focused = document.activeElement;
      const row = focused.closest("tbody tr");
      const selector = focused.matches("button[aria-pressed]") ? "button[aria-pressed]" :
        focused.matches("button[aria-checked]") ? "button[aria-checked]" : null;
      const index = row?.sectionRowIndex;
      results.replaceChildren(...fresh.childNodes);
      if (row && selector) {
        const rows = results.querySelectorAll("tbody tr");
        const target = document.getElementById(row.id) || rows[Math.min(index, rows.length - 1)];
        (target?.querySelector(selector) || document.getElementById("subject-directory-search")).focus({preventScroll:true});
      }
      refreshNeeded = false;
    } catch {
      if (version === revision) message("Modification enregistrée. Réappliquez le filtre pour actualiser la liste.");
    }
  }

  results.addEventListener("submit", async event => {
    const form = event.target;
    const field = form.elements.field?.value;
    if (field !== "done" && field !== "retry") return;
    event.preventDefault();
    const button = form.querySelector("button");
    if (button.hasAttribute("aria-busy")) return;
    const body = new FormData(form);
    const checked = body.get("value") === "1";
    pending++; revision++;
    button.setAttribute("aria-busy", "true");
    button.setAttribute("aria-disabled", "true");
    mark(form, checked);
    message("");
    try {
      const response = await fetch(form.action, {
        method: "POST", body, keepalive: true, redirect: "error",
        headers: {Accept: "application/json", "X-Requested-With": "fetch"}
      });
      if (!response.ok) throw new Error();
      const saved = await response.json();
      if (saved.field !== field || saved.value !== checked) throw new Error();
      count(field, checked ? 1 : -1);
      const status = results.dataset.status;
      if (status === field || (status === "not-done" && field === "done")) refreshNeeded = true;
    } catch {
      mark(form, !checked);
      message(`Modification non confirmée pour « ${form.closest("tr").querySelector(".t1-table__subject a").textContent} ». Réessayez.`);
    } finally {
      button.removeAttribute("aria-busy");
      button.removeAttribute("aria-disabled");
      if (--pending === 0 && refreshNeeded) refreshFilteredList(revision);
    }
  });
})();
