const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function studio() {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {hidden: false, disabled: false, textContent: "", focus() {}});
    return elements.get(id);
  };
  const first = {
    number: 1, topic: "Practical details", question: "Reviewed question one",
    hintEnglish: "First goal", hintFrench: "Premier point", followUpTo: null, cursor: "signed-first",
  };
  const second = {...first, number: 2, question: "Reviewed follow-up", followUpTo: 1, cursor: "signed-second"};
  element("r2-initial-turn").textContent = JSON.stringify(first);
  const root = {
    dataset: {replyUrl: "/selected/reply/", questionCount: "2"},
    querySelector() { return {value: "csrf-token"}; },
  };
  const requests = [], completions = [];
  let fail = false, started = 0;
  const window = {
    HeureuxEO2Practice: () => ({
      begin() { started += 1; return true; },
      finish(value) { completions.push(value); },
    }),
    addEventListener() {},
  };
  const fetch = async (url, options) => {
    requests.push({url, options});
    if (fail) throw new Error("Offline");
    const firstStep = options.body.get("cursor") === first.cursor;
    return {
      ok: true,
      json: async () => ({
        answer: options.body.get("action") === "skip" ? "" : firstStep ? "First reply" : "Second reply",
        next: firstStep ? second : null,
        closing: firstStep ? "" : "Reviewed closing",
      }),
    };
  };
  vm.runInNewContext(fs.readFileSync(path.join(
    __dirname, "../static/study/js/expression/eo/tache_2/rehearsal.js",
  ), "utf8"), {
    window, document: {getElementById: id => id === "eo2-rehearsal" ? root : element(id)},
    fetch, AbortController, URLSearchParams, setTimeout, clearTimeout,
  });
  return {
    el: id => element("r2-" + id), requests, completions,
    started: () => started, fail: value => { fail = value; },
  };
}
const settle = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  const empty = studio();
  assert.equal(empty.started(), 0);
  assert.equal(empty.requests.length, 0);
  empty.el("start").onclick();
  assert.equal(empty.requests.length, 0);
  empty.el("end").onclick();
  assert.deepEqual(empty.completions, [false]);

  const page = studio();
  page.el("start").onclick();
  assert.equal(page.started(), 1);
  assert.equal(page.el("question").textContent, "Reviewed question one");
  assert.equal(page.el("model").open, false);
  assert.equal(page.el("reply").hidden, true);
  page.fail(true);
  page.el("reveal").onclick();
  page.el("reveal").onclick();
  await settle();
  assert.equal(page.requests.length, 1, "A double click must not advance two turns.");
  assert.equal(page.el("reply").hidden, true);
  assert.match(page.el("status").textContent, /Réessayez/);
  page.fail(false);
  page.el("reveal").onclick();
  await settle();
  assert.equal(page.requests[0].options.body.toString(), page.requests[1].options.body.toString());
  assert.equal(page.el("answer").textContent, "First reply");
  assert.deepEqual(page.completions, [], "Revealing an answer is not ending a session.");
  const request = page.requests[1];
  assert.equal(request.url, "/selected/reply/");
  assert.equal(request.options.credentials, "same-origin");
  assert.equal(request.options.mode, "same-origin");
  assert.equal(request.options.headers["X-CSRFToken"], "csrf-token");
  assert.deepEqual([...request.options.body.keys()].sort(), ["action", "cursor"]);
  page.el("next").onclick();
  assert.equal(page.el("question").textContent, "Reviewed follow-up");
  assert.equal(page.el("reply").hidden, true);
  assert.equal(page.el("skip").hidden, false);
  page.el("skip").onclick();
  await settle();
  assert.deepEqual(page.completions, [true]);
  assert.match(page.el("summary").textContent, /^1 échange répété/);
  assert.equal(page.el("closing-text").textContent, "Reviewed closing");
  page.el("end").onclick();
  assert.deepEqual(page.completions, [true], "Ending twice must not record twice.");
  console.log("EO2 guided rehearsal checks passed.");
})().catch(error => { console.error(error); process.exitCode = 1; });
