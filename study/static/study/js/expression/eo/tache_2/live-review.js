(() => {
  "use strict";
  const by = id => document.getElementById("lv-" + id);
  const opinion = document.getElementById("live-studio").dataset.mode === "opinion";
  const make = (tag, text, className) => {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const count = text => (text.match(/[\p{L}\p{N}]+(?:['’-][\p{L}\p{N}]+)*/gu) || []).length;
  const duration = ms => {
    const sec = Math.round(ms / 1000);
    return sec < 60 ? `${sec} s` : `${Math.floor(sec / 60)} min ${String(sec % 60).padStart(2, "0")} s`;
  };
  let painters = [];
  let spoken = "";

  // Narrow a reviewer correction to the words it actually changes.
  const pieces = text => text.match(/[\p{L}\p{M}\p{N}]+(?:['‘’-][\p{L}\p{M}\p{N}]+)*|\s+|[^\s]/gu) || [];
  const same = (a, b) => a.replace(/[‘’]/g, "'").toLowerCase() === b.replace(/[‘’]/g, "'").toLowerCase();
  function changedWords({turnIndex, start, before = "", after = "", why = ""}) {
    const left = pieces(before), right = pieces(after);
    let first = 0, l = left.length, r = right.length;
    while (first < l && first < r && same(left[first], right[first])) start += left[first++].length;
    while (l > first && r > first && same(left[l - 1], right[r - 1])) { l--; r--; }
    const words = left.slice(first, l).join("");
    return {turnIndex, start, end: start + words.length, before: words, after: right.slice(first, r).join(""), why};
  }

  // Keep only annotations that still match the learner's current words, in reading order.
  function place(rows, annotations) {
    const marks = new Map();
    let n = 0;
    (Array.isArray(annotations) ? annotations : []).filter(mark => {
      const row = mark && rows[mark.turnIndex];
      if (!row || row.speaker !== "user" || !Number.isInteger(mark.start) || !Number.isInteger(mark.end)) return false;
      const before = mark.before ?? "", after = mark.after ?? "";
      return mark.start >= 0 && mark.start <= mark.end && mark.end <= row.text.length &&
        row.text.slice(mark.start, mark.end) === before && before !== after;
    }).sort((a, b) => a.turnIndex - b.turnIndex || a.start - b.start || a.end - b.end).forEach(mark => {
      const list = marks.get(mark.turnIndex) || [];
      if (list.length && mark.start < list.at(-1).end) return;
      list.push({start: mark.start, end: mark.end, before: mark.before ?? "", after: mark.after ?? "", why: mark.why || ""});
      marks.set(mark.turnIndex, list);
      n++;
    });
    return {marks, total: n};
  }
  // A correction with a reason is a button that shows it under the turn (see `turn`).
  function sentence(text, marks, reasonId) {
    const parts = [];
    let at = 0;
    for (const mark of marks) {
      parts.push(text.slice(at, mark.start));
      const span = make(mark.why ? "button" : "span", "", "lv-mark");
      if (mark.why) {
        span.type = "button";
        span.dataset.why = mark.why;
        span.setAttribute("aria-expanded", "false");
        span.setAttribute("aria-controls", reasonId);
      }
      if (mark.before) span.append(make("span", "à vérifier : ", "sr-only"), make("del", mark.before));
      if (mark.after) span.append(make("span", mark.before ? ", proposition : " : "ajout proposé : ", "sr-only"), make("ins", mark.after));
      parts.push(span);
      at = mark.end;
    }
    parts.push(text.slice(at));
    return parts;
  }
  function glance(rows) {
    const words = {user: 0, model: 0};
    rows.forEach(row => { words[row.speaker === "user" ? "user" : "model"] += count(row.text); });
    by("fig-turns").textContent = opinion ? words.user : rows.filter(row => row.speaker === "user").length;
    if (opinion) { by("share").hidden = true; return; }
    const total = words.user + words.model;
    by("share").hidden = !total;
    if (!total) return;
    const mine = Math.round(100 * words.user / total);
    by("share-user").textContent = `${mine}\u202f%`;
    by("share-model").textContent = `${100 - mine}\u202f%`;
    by("share-bar").style.setProperty("--share", String(mine / 100));
  }

  // Only the reviewer's corrections are painted; until it answers, the transcript stays as spoken.
  function feedback(rows, reviewedMarks = null) {
    const {marks, total} = place(rows, (reviewedMarks || []).map(changedWords));
    painters.forEach((paint, i) => paint(marks.get(i) || []));
    const mine = rows.filter(row => row.speaker === "user").length;
    const markCount = reviewedMarks === null ? "" : total ? `${total} à vérifier` : "aucune correction vérifiée";
    const turns = opinion ? "" : `${mine} prise${mine > 1 ? "s" : ""} de parole`;
    by("count").textContent = `(${[turns, spoken, mine ? markCount : ""].filter(Boolean).join(" · ")})`;
    return total;
  }

  // Learner turns are numbered like the proposal's lines; corrections sit on the words themselves.
  function turn(row, index, n) {
    const item = make("li", "");
    const user = row.speaker === "user";
    item.dataset.speaker = row.speaker;
    const line = make("p", "", "lv-turn__said");
    let who = make("strong", "Interlocuteur", "lv-who");
    if (user) {
      item.id = `lv-turn-${index}`;
      item.tabIndex = -1;
      who = make("span", `${n}.`, "lv-num");
      who.prepend(make("span", "Votre prise de parole ", "sr-only"));
    }
    const body = make("div", "", "lv-turn");
    item.append(body);
    body.append(who, line);
    if (row.interrupted) body.append(make("small", "Réponse interrompue."));
    // One reason at a time per turn, shown under it; the same correction hides it again.
    const reason = make("small", "", "lv-turn__why");
    reason.id = `lv-why-${index}`;
    reason.hidden = true;
    body.append(reason);
    line.onclick = ({target}) => {
      const mark = target.closest("button.lv-mark");
      if (!mark) return;
      const open = mark.getAttribute("aria-expanded") !== "true";
      line.querySelectorAll("button.lv-mark").forEach(other => other.setAttribute("aria-expanded", "false"));
      mark.setAttribute("aria-expanded", String(open));
      reason.textContent = open ? mark.dataset.why : "";
      reason.hidden = !open;
    };
    painters[index] = marks => {
      line.replaceChildren(...sentence(row.text, marks, reason.id));
      reason.hidden = true;
      item.toggleAttribute("data-marked", marks.length > 0);
    };
    return item;
  }

  function showReplies(on) {
    by("turns").dataset.replies = on ? "shown" : "hidden";
    const button = by("replies");
    button.title = `${on ? "Masquer" : "Afficher"} les réponses de l’interlocuteur`;
    button.setAttribute("aria-label", button.title);
    button.setAttribute("aria-expanded", String(on));
    button.querySelector('[data-icon="eye"]').toggleAttribute("hidden", on);
    button.querySelector('[data-icon="eye-off"]').toggleAttribute("hidden", !on);
  }
  by("replies").onclick = () => showReplies(by("turns").dataset.replies !== "shown");

  function clear() {
    window.HeureuxEO2Evaluation?.clear();
    painters = [];
    for (const id of ["turns", "count", "share-user", "share-model"]) by(id).replaceChildren();
    for (const id of ["fig-time", "fig-turns"]) by(id).textContent = "—";
    by("report").hidden = by("empty").hidden = by("share").hidden = true;
    by("transcript").open = false;
    showReplies(false);
  }
  // Returns whether any words were transcribed, so the caller can title an empty attempt honestly.
  // `saved` is a stored exchange, {id, report}, reopened without asking Groq again.
  function render(captured, {elapsed = 0, saved = null} = {}) {
    const rows = captured.filter(row => row.text.trim()).map(row => ({...row, text: row.text.trim()}));
    if (!rows.length) { by("empty").hidden = false; return false; }
    by("report").hidden = false;
    spoken = elapsed > 0 ? duration(elapsed) : "";
    by("fig-time").textContent = duration(elapsed);
    by("replies").hidden = !rows.some(row => row.speaker !== "user");
    let mine = 0;
    by("turns").replaceChildren(...rows.map((row, i) => turn(row, i, row.speaker === "user" ? ++mine : 0)));
    glance(rows);
    feedback(rows);
    // Wide screens show it open; phones open it once the reviewer marks corrections.
    by("transcript").open = window.matchMedia("(min-width: 62rem)").matches;
    // After the plain pass, so a stored report's corrections are painted over it, not under it.
    window.HeureuxEO2Evaluation?.bind(rows, annotations => {
      const marked = feedback(rows, annotations);
      if (annotations.length && marked) by("transcript").open = true;
    }, {elapsed, id: saved?.id, report: saved?.report, pendingProvider: saved?.pendingProvider});
    return true;
  }
  window.HeureuxEO2LiveReview = {render, clear};
})();
