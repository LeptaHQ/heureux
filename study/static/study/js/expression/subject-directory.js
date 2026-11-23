(() => {
  "use strict";
  const rowSelector = "[data-subject-progress-row], [data-writing-sujet-progress-row]";
  const rowsIn = node => Array.from(node.querySelectorAll(rowSelector));
  const statusOf = row => {
    const badge = row.querySelector(".progress-status");
    return badge?.classList.contains("progress-status--done") ? "done" :
      badge?.classList.contains("progress-status--active") ? "active" : "new";
  };
  const sizeLabel = n => `${n} sujet${n === 1 ? "" : "s"}`;
  let lastFocused = document.activeElement;
  document.addEventListener("focusin", event => { lastFocused = event.target; });

  function saveFocus(form) {
    const button = document.activeElement;
    const startedHere = form.contains(button);
    // Disabling a focused button leaves focus on body. An earlier save must not
    // steal it back after the learner has moved to a different control.
    const current = () => document.activeElement === document.body && startedHere &&
      lastFocused === button ? button : document.activeElement;
    return {current, restore() {
      if (startedHere && button.isConnected && document.activeElement === document.body &&
          current() === button) button.focus({preventScroll: true});
    }};
  }

  function summary(rows, unique) {
    if (unique) {
      const byId = new Map(rows.map(row => [row.dataset.subjectProgressRow || row.dataset.writingSujetProgressRow || row, row]));
      rows = Array.from(byId.values());
    }
    const states = rows.map(statusOf), total = states.length;
    const done = states.filter(state => state === "done").length;
    const active = states.filter(state => state === "active").length;
    return {done, active, total, fraction: `${done}/${total}`,
      status: total && done === total ? "done" : done || active ? "active" : "new"};
  }

  function badgeState(el, state) {
    for (const status of ["new", "active", "done"]) el.classList.toggle(`progress-status--${status}`, status === state);
  }

  function updateTotal(delta) {
    const el = document.querySelector("[data-collection-progress]");
    if (!el || !delta) return;
    const fraction = el.querySelector("[data-collection-progress-value]");
    const [before, total] = fraction.textContent.split("/").map(Number);
    const done = before + delta;
    fraction.textContent = `${done}/${total}`;
    el.title = `${done} sur ${total} ${el.dataset.progressUnit}`;
    el.querySelector(".sr-only").textContent = el.title;
    const metric = document.querySelector("[data-subject-completed-count]");
    if (metric) metric.textContent = String(done);
  }

  function updateDetailSummary() {
    const fraction = document.querySelector("[data-subject-group-fraction]");
    const bar = document.querySelector("[data-subject-group-bar]");
    if (!bar && !fraction) return;
    const s = summary(rowsIn(document), !bar || bar.dataset.unique === "true");
    if (fraction) {
      fraction.textContent = s.fraction;
      const badge = document.querySelector("[data-subject-group-status]");
      badge.textContent = {done: "Terminé", active: "En cours", new: "À commencer"}[s.status];
      badgeState(badge, s.status);
    } else {
      document.querySelector("[data-subject-group-completed]").textContent = `${s.done} terminé${s.done === 1 ? "" : "s"}`;
      bar.querySelector(".bg-mature").style.width = `${Math.round(100 * s.done / s.total)}%`;
      bar.querySelector(".bg-started").style.width = `${Math.round(100 * s.active / s.total)}%`;
    }
  }

  function updateRows(rows, {status, bookmarked, focus}) {
    const collection = rows[0]?.closest("[data-subject-collection]");
    if (!collection) return;
    const filter = collection.dataset.statusFilter;
    const remove = filter === "bookmarked" ? bookmarked === false :
      filter && status && status !== filter;
    const families = new Set(), themes = new Set(), tables = new Set();
    const selector = focus?.hasAttribute("aria-checked") ? '[role="checkbox"]' : "button[aria-pressed]";
    let nextFocus;
    if (remove && focus && rows.some(row => row.contains(focus))) {
      const all = rowsIn(collection), index = all.indexOf(focus.closest("tr"));
      const remaining = all.filter(row => !rows.includes(row));
      nextFocus = remaining[Math.min(index, remaining.length - 1)]?.querySelector(selector) ||
        document.querySelector("[data-subject-directory-search] input[type=search]");
    }
    for (const row of rows) {
      families.add(row.closest("[data-subject-family-group]"));
      themes.add(row.closest("[data-t1-table-theme]"));
      tables.add(row.closest("table"));
      if (remove) row.remove();
    }
    for (const family of families) {
      if (!family) continue;
      const members = rowsIn(family);
      if (!members.length) { family.remove(); continue; }
      family.querySelector("[data-family-size]").textContent = sizeLabel(members.length);
      family.querySelector("[data-family-fraction]").textContent = summary(members, true).fraction;
    }
    for (const theme of themes) {
      if (!theme) continue;
      const s = summary(rowsIn(theme), !rows[0].hasAttribute("data-progress-weight"));
      const badge = theme.querySelector("summary .progress-status");
      badge.textContent = s.fraction;
      badgeState(badge, s.status);
    }
    if (remove) {
      const n = rowsIn(collection).length;
      document.querySelector("[data-subject-result-count]").textContent = n ? sizeLabel(n) :
        filter === "bookmarked" ? "Aucun favori ne correspond à ces filtres." : "Aucun sujet ne correspond à ces filtres.";
      if (!n) collection.remove();
    }
    if (status && collection.dataset.directoryOrder === "reprendre") {
      const rank = {active: 0, new: 1, done: 2};
      const ordered = rowsIn(collection).sort((a, b) => rank[statusOf(a)] - rank[statusOf(b)] ||
        Number(a.dataset.catalogueOrder) - Number(b.dataset.catalogueOrder));
      ordered.forEach((row, index) => {
        const body = row.parentElement;
        if (body.rows[index] !== row) body.insertBefore(row, body.rows[index]);
      });
    }
    if (status) for (const table of tables) table?.dispatchEvent(new Event("heureux:subject-rows-changed"));
    if (nextFocus) nextFocus.focus({preventScroll: true});
    else if (document.activeElement === document.body && focus?.isConnected &&
             focus !== document.body && !focus.disabled) {
      // Moving another row during a sort can blur its active control.
      focus.focus({preventScroll: true});
    }
  }

  window.HeureuxSubjectDirectory = {
    statusOf,
    saveFocus,
    progress(rows, old, status, focus) {
      if (!rows.length || old === status) return;
      // EE can count several publications for one saved marker, including rows outside this filter.
      const weight = Number(rows[0].dataset.progressWeight || 1);
      updateTotal(weight * (Number(status === "done") - Number(old === "done")));
      updateRows(rows.filter(row => row.isConnected), {status, focus});
      updateDetailSummary();
    },
    bookmark(rows, bookmarked, focus) {
      if (!bookmarked && rows[0]?.closest('[data-status-filter="bookmarked"]')) {
        updateRows(rows, {bookmarked, focus});
      }
    }
  };
})();
