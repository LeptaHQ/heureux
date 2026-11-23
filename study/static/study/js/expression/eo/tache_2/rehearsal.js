(() => {
  "use strict";
  const root = document.getElementById("eo2-rehearsal");
  if (!root) return;
  const by = id => document.getElementById("r2-" + id);
  const show = (id, visible) => { by(id).hidden = !visible; };
  const initial = JSON.parse(by("initial-turn").textContent);
  const csrf = root.querySelector("[name=csrfmiddlewaretoken]").value;
  const practice = window.HeureuxEO2Practice(root);
  let current, next, closing = "", turns = 0, state = "setup", pending;

  function renderTurn(turn) {
    current = turn; state = "asking";
    by("step").textContent = `Question ${turn.number} / ${root.dataset.questionCount}`;
    by("topic").textContent = turn.topic;
    by("hint-en").textContent = turn.hintEnglish;
    by("hint-fr").textContent = turn.hintFrench;
    by("question").textContent = turn.question;
    by("model").open = false; by("opening").open = false;
    show("opening", turn.number === 1);
    show("followup", Boolean(turn.followUpTo));
    by("followup").textContent = turn.followUpTo
      ? `Relance après la réponse ${turn.followUpTo} : appuyez-vous sur l’information reçue. Passez-la si ce point est déjà résolu.` : "";
    show("ask", true); show("skip", Boolean(turn.followUpTo));
    show("reply", false); show("next", false);
    by("answer").textContent = ""; by("status").textContent = "";
    by("hint-en").focus({preventScroll: true});
  }
  function finish() {
    if (pending || !["asking", "answered"].includes(state)) return;
    state = "done"; show("workspace", false); show("done", true);
    by("summary").textContent = turns
      ? `${turns} échange${turns > 1 ? "s" : ""} répété${turns > 1 ? "s" : ""} sur ce sujet.`
      : "Vous avez parcouru le sujet sans terminer d’échange.";
    show("closing", Boolean(closing));
    by("closing-text").textContent = closing;
    by("closing").open = false;
    practice.finish(turns > 0);
    by("done-title").focus();
  }
  function controls(busy) {
    by("reveal").disabled = by("skip").disabled = by("end").disabled = busy;
  }
  async function respond(action) {
    if (state !== "asking" || pending) return;
    const request = pending = new AbortController();
    const timeout = setTimeout(() => request.abort(), 12000);
    controls(true); by("status").textContent = "Chargement de cette étape…";
    try {
      const response = await fetch(root.dataset.replyUrl, {
        method: "POST", credentials: "same-origin", mode: "same-origin", redirect: "error",
        signal: request.signal,
        headers: {"X-CSRFToken": csrf, Accept: "application/json"},
        body: new URLSearchParams({cursor: current.cursor, action}),
      });
      if (!response.ok) throw new Error("Reply unavailable");
      const data = await response.json();
      if (pending !== request) return;
      if (typeof data.answer !== "string" || (action === "reply" && !data.answer.trim())) {
        throw new Error("Empty reply");
      }
      next = data.next; closing = data.closing;
      if (action === "skip") {
        if (next) renderTurn(next);
        else { pending = null; finish(); }
      } else {
        turns += 1; state = "answered";
        by("answer").textContent = data.answer;
        show("reply", true); show("ask", false); show("next", true);
        by("next").textContent = next ? "Question suivante" : "Conclure et terminer";
        by("status").textContent = "";
        by("answer").focus({preventScroll: true});
      }
    } catch {
      if (pending === request) by("status").textContent =
        "Cette étape n’a pas pu être chargée. Réessayez avec le même bouton. Si la séance a expiré, rechargez la page.";
    } finally {
      clearTimeout(timeout);
      if (pending === request) pending = null;
      controls(false);
    }
  }
  by("start").disabled = false;
  by("start").onclick = () => {
    if (state !== "setup" || !practice.begin()) return;
    turns = 0; next = null; closing = "";
    show("setup", false); show("done", false); show("workspace", true);
    renderTurn(initial);
  };
  by("reveal").onclick = () => respond("reply");
  by("skip").onclick = () => respond("skip");
  by("next").onclick = () => {
    if (state !== "answered" || pending) return;
    if (next) renderTurn(next); else finish();
  };
  by("end").onclick = finish;
  by("restart").onclick = () => {
    if (state !== "done" || by("restart").disabled) return;
    state = "setup"; show("done", false); show("setup", true); by("start").focus();
  };
  window.addEventListener("pagehide", () => { pending?.abort(); pending = null; });
})();
