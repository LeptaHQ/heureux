(() => {
  "use strict";
  const by = id => document.getElementById("lv-" + id);
  const make = (tag, text, className) => {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const quote = value => `« ${value} »`;
  const action = (label, run) => {
    const button = make("button", label);
    button.type = "button";
    button.onclick = run;
    return button;
  };
  const count = text => (text.match(/[\p{L}\p{N}]+(?:['’-][\p{L}\p{N}]+)*/gu) || []).length;
  const duration = ms => {
    const sec = Math.round(ms / 1000);
    return sec < 60 ? `${sec} s` : `${Math.floor(sec / 60)} min ${String(sec % 60).padStart(2, "0")}`;
  };
  let painters = [];

  // Quoted speech with its speaker, so the evidence reads like the exchange itself.
  const said = (speaker, words) => {
    const line = make("p", "", "lv-said");
    line.dataset.speaker = speaker;
    line.append(make("small", speaker === "user" ? "Vous" : "Interlocuteur"), make("span", quote(words)));
    return line;
  };

  // Keep only annotations that still match the learner's current words, numbered in reading order.
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
      list.push({start: mark.start, end: mark.end, before: mark.before ?? "", after: mark.after ?? "",
        why: mark.why || "", n: ++n});
      marks.set(mark.turnIndex, list);
    });
    return {marks, total: n};
  }
  // Strengths come only from the report's positive evidence, never from the absence of a flag.
  function strengths(rows, evidence) {
    const found = new Map();
    for (const item of evidence) {
      const index = Number.isInteger(item.turnIndex) ? item.turnIndex : rows.findIndex((row, i) =>
        row.speaker === "user" && row.text === item.quote && !(found.get(i) || []).includes(item.label));
      if (rows[index]?.speaker !== "user") continue;
      found.set(index, [...(found.get(index) || []), item.label]);
    }
    return found;
  }
  function sentence(text, marks) {
    const parts = [];
    let at = 0;
    for (const mark of marks) {
      parts.push(text.slice(at, mark.start));
      const span = make("span", "", "lv-mark");
      span.dataset.mark = mark.n;
      if (mark.before) span.append(make("span", "à vérifier : ", "sr-only"), make("del", mark.before));
      if (mark.after) span.append(make("span", mark.before ? ", proposition : " : "ajout proposé : ", "sr-only"), make("ins", mark.after));
      parts.push(span);
      at = mark.end;
    }
    parts.push(text.slice(at));
    return parts;
  }
  function reveal(n) {
    const mark = by("turns").querySelector(`[data-mark="${n}"]`);
    if (!mark) return;
    by("transcript").open = true;
    const line = mark.closest(".lv-turn__said");
    line.focus({preventScroll: true});
    line.scrollIntoView({block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
  }

  function glance(rows, tally) {
    by("fig-turns").textContent = tally.turns;
    by("fig-questions").textContent = tally.questions;
    by("fig-links").textContent = tally.followUps;
    const words = {user: 0, model: 0};
    rows.forEach(row => { words[row.speaker === "user" ? "user" : "model"] += count(row.text); });
    const total = words.user + words.model;
    by("share").hidden = !total;
    if (!total) return;
    const mine = Math.round(100 * words.user / total);
    by("share-user").textContent = `${mine}\u202f%`;
    by("share-model").textContent = `${100 - mine}\u202f%`;
    by("share-bar").style.setProperty("--share", String(mine / 100));
  }

  function feedback(rows, reviewedMarks = null) {
    const {evidence = [], corrections = [], next = "", tally, annotations} = window.HeureuxEO2Feedback.assess(rows);
    glance(rows, tally);
    const highlights = (reviewedMarks || []).map(mark => window.HeureuxEO2Feedback.changedWords(mark.turnIndex, mark));
    const {marks, total} = place(rows, [...highlights, ...annotations]);
    const good = strengths(rows, evidence);
    painters.forEach((paint, i) => paint(marks.get(i) || [], good.get(i) || []));
    by("key").hidden = !total;
    const mine = rows.filter(row => row.speaker === "user").length;
    const markCount = total ? `${total} à vérifier` : reviewedMarks === null ? "aucune suggestion locale" : "aucune correction vérifiée";
    by("count").textContent = (mine === 1 ? "votre réplique" : `vos ${mine} répliques`) + (mine ? ` · ${markCount}` : "");

    by("observations").hidden = !evidence.length;
    by("evidence").replaceChildren(...evidence.map(({label, quote:words, context}) => {
      const item = make("li", "");
      item.append(make("span", label, "lv-chip"));
      if (context) item.append(said("model", context));
      item.append(said("user", words));
      return item;
    }));

    // Marks shown in the conversation are indexed here; anything not placed keeps its explanation.
    const placed = [...marks.values()].flat();
    const pair = (line, before, after) => {
      if (before) {
        const struck = make("span", "« ", "lv-fix__before");
        struck.append(make("del", before), " »");
        line.append(struck, make("span", " → ", "lv-fix__arrow"));
      }
      line.append(make("strong", after ? quote(after) : "Supprimer ce passage", "lv-fix__after"));
      return line;
    };
    const items = placed.map(mark => {
      const item = make("li", "");
      const jump = action("", () => reveal(mark.n));
      jump.className = "lv-jump";
      jump.append(make("span", "Voir dans l’échange la formulation ", "sr-only"), make("b", String(mark.n), "lv-fix__n"),
        make("span", " : ", "sr-only"));
      item.append(pair(jump, mark.before, mark.after));
      return item;
    });
    const covered = fix => placed.some(mark => (mark.why && mark.why === fix.why) ||
      (fix.before.includes(mark.before) && fix.after.includes(mark.after)));
    corrections.filter(fix => !covered(fix)).forEach(({before, after, why}) => {
      const item = make("li", "");
      item.append(pair(make("p", "", "lv-fix"), before, after), make("small", why));
      items.push(item);
    });
    by("language").hidden = !items.length;
    by("corrections").replaceChildren(...items);
    by("next").textContent = next;
    return total;
  }

  function turn(row, index) {
    const item = make("li", "");
    const user = row.speaker === "user";
    item.dataset.speaker = row.speaker;
    const tags = make("span", "", "lv-tags");
    const line = make("p", "", "lv-turn__said");
    const notes = make("span", "", "lv-why");
    if (user) line.tabIndex = -1;
    const body = make("div", "", "lv-turn");
    item.append(make("strong", user ? "Vous" : "Interlocuteur"), body);
    body.append(tags, line, notes);
    if (row.interrupted) body.append(make("small", "Réponse interrompue."));
    painters[index] = (marks, good) => {
      tags.hidden = !good.length;
      tags.replaceChildren(...good.map(label => make("span", label, "lv-chip")));
      line.replaceChildren(...sentence(row.text, marks));
      notes.hidden = !marks.length;
      notes.replaceChildren(...marks.map(mark => {
        const note = make("span", "", "lv-why__item");
        note.append(make("b", String(mark.n)), mark.why || `${quote(mark.before)} → ${quote(mark.after)}`);
        return note;
      }));
      item.toggleAttribute("data-marked", marks.length > 0);
    };
    return item;
  }

  function showReplies(on) {
    by("replies").setAttribute("aria-pressed", String(on));
    by("turns").dataset.replies = on ? "shown" : "hidden";
  }
  by("replies").onclick = () => showReplies(by("replies").getAttribute("aria-pressed") !== "true");

  function clear() {
    window.HeureuxEO2Evaluation?.clear();
    painters = [];
    for (const id of ["turns", "count", "evidence", "corrections", "next", "share-user", "share-model"]) by(id).replaceChildren();
    for (const id of ["fig-time", "fig-turns", "fig-questions", "fig-links"]) by(id).textContent = "—";
    by("report").hidden = by("empty").hidden = by("share").hidden = by("key").hidden = true;
    by("transcript").open = false;
    showReplies(false);
  }
  // Returns whether any words were transcribed, so the caller can title an empty attempt honestly.
  function render(captured, {elapsed = 0} = {}) {
    const rows = captured.filter(row => row.text.trim()).map(row => ({...row, text: row.text.trim()}));
    if (!rows.length) { by("empty").hidden = false; return false; }
    by("report").hidden = false;
    by("fig-time").textContent = duration(elapsed);
    by("replies").hidden = !rows.some(row => row.speaker !== "user");
    by("turns").replaceChildren(...rows.map(turn));
    window.HeureuxEO2Evaluation?.bind(rows, annotations => {
      const marked = feedback(rows, annotations);
      if (annotations.length && marked) by("transcript").open = true;
    });
    const marked = feedback(rows);
    // Wide screens show it beside the findings; phones open it when it carries annotations.
    by("transcript").open = marked > 0 || window.matchMedia("(min-width: 62rem)").matches;
    return true;
  }
  window.HeureuxEO2LiveReview = {render, clear};
})();
