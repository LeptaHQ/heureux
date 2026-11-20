/* Behavioural checks for the EO Tâche 1 examiner, without a browser or network. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const enginePath = path.join(
  __dirname, "../static/study/js/expression/eo/tache_1/interview-engine.js"
);
const defaultEngine = require(enginePath);

function seeded(seed) {
  return function () {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const engineFor = (seed) => defaultEngine.create({ random: seeded(seed) });
const flat = (text) => text.replace(/\s+/g, " ").trim();
const wordCount = (text) => flat(text).split(" ").length;

function interview(engine, answers, start = 115, step = 18) {
  const turns = [];
  const lines = [engine.opening()];
  let remaining = start;
  for (const answer of answers) {
    turns.push({ question: lines[lines.length - 1], answer });
    if (remaining <= 8) break;
    lines.push(engine.next(turns, remaining));
    remaining -= step;
  }
  return { turns, lines };
}

function afterOpening(engine, answer) {
  const opening = engine.opening();
  return { opening, line: engine.next([{ question: opening, answer }], 100) };
}

// The browser build exposes the same API as a classic script global.
{
  const sandbox = { window: {} };
  vm.runInNewContext(fs.readFileSync(enginePath, "utf8"), sandbox);
  for (const name of ["opening", "next", "feedback", "create"]) {
    assert.equal(typeof sandbox.window.HeureuxEO1Engine[name], "function", name);
  }
}

// Openings greet a stranger, ask for a presentation and vary between runs.
{
  const openings = new Set();
  for (let seed = 1; seed <= 40; seed++) {
    const line = engineFor(seed).opening();
    assert.match(line, /^Bonjour/);
    assert.match(line, /présenter|de vous/);
    assert.doesNotMatch(line, /\(e\)|\btu\b|\bton\b|\bta\b/);
    openings.add(line);
  }
  assert(openings.size >= 8, `only ${openings.size} distinct openings`);
}

// Follow-ups pick up what the learner said without echoing their words.
{
  const answer = "Je m'appelle Zorblax, je viens de Quarvel et je travaille comme infirmière à l'hôpital.";
  for (let seed = 1; seed <= 10; seed++) {
    const { line } = afterOpening(engineFor(seed), answer);
    assert.match(line, /travail/, line);
    assert.doesNotMatch(line, /Zorblax|Quarvel|infirmi|hôpital/, line);
  }
  const sport = "Je ne fais pas de sport, mais je lis des romans policiers le soir.";
  for (let seed = 1; seed <= 10; seed++) {
    const { line } = afterOpening(engineFor(seed), sport);
    assert.doesNotMatch(line, /activité physique|cette activité/, line);
    assert.match(line, /livre|lire/, line);
  }
}

// Repeat, rephrase, then move on, whatever the wording of the request.
{
  const engine = engineFor(7);
  const opening = engine.opening();
  const core = opening.slice(opening.lastIndexOf(".") + 2);
  const turns = [{ question: opening, answer: "pardon vous pouvez répéter la question" }];
  const repeated = engine.next(turns, 110);
  assert(flat(repeated).endsWith(flat(core)), repeated);
  turns.push({ question: repeated, answer: "Désolé, je n’ai pas bien compris." });
  const rephrased = engine.next(turns, 104);
  assert(!flat(rephrased).includes(flat(core)), rephrased);
  turns.push({ question: rephrased, answer: "Sorry?" });
  const moved = engine.next(turns, 98);
  assert.match(moved, /passons|changeons/i, moved);
  assert.notEqual(moved, rephrased);

  for (const request of ["Je ne comprends pas.", "c'est-à-dire ?", "Qu'est-ce que ça veut dire ?"]) {
    const { opening: first, line } = afterOpening(engineFor(3), request);
    assert.match(line, /reformule|autrement/i, request);
    assert.notEqual(line, first);
  }
}

// A request to change subject leaves the current topic; long answers are never requests.
{
  const engine = engineFor(11);
  const opening = engine.opening();
  const topic = engine.next([{ question: opening, answer: "" }], 100);
  const turns = [{ question: opening, answer: "" },
    { question: topic, answer: "Je préfère ne pas en parler, c'est un peu personnel." }];
  const switched = engine.next(turns, 80);
  assert.match(switched, /autre|changeons/i, switched);
  assert.notEqual(flat(switched), flat(topic));

  const long = "Je travaille dans une école de musique où je dois souvent répéter les mêmes " +
    "exercices avec les enfants, et je ne comprends pas toujours pourquoi ils aiment ça.";
  for (let seed = 1; seed <= 10; seed++) {
    for (const answer of [long, "Je ne sais pas cuisiner."]) {
      const { line } = afterOpening(engineFor(seed), answer);
      assert.doesNotMatch(line, /répète|reformule|autrement|grave|problème|passons|changeons/i, line);
    }
  }
}

// Whole interviews never repeat a question and stay time-aware near the end.
{
  const styles = {
    oral: Array(8).fill(""),
    terse: ["Oui.", "Non.", "Lyon.", "Un peu.", "Le soir.", "Avec mes amis.", "Oui.", "Bof."],
    rich: [
      "Je suis Zorblax, je vis en colocation et je travaille dans un bureau d'architectes.",
      "J'aime mon travail parce que les projets changent souvent, mais les journées sont longues.",
      "Le week-end, je fais du vélo avec mes amis et je cuisine pour ma famille.",
      "Mon plat préféré, c'est un ragoût que ma grand-mère préparait en hiver.",
      "J'apprends le français depuis deux ans grâce aux séries et à un cours du soir.",
      "Plus tard, j'aimerais déménager dans une ville plus calme, près de la mer.",
      "Je lis surtout des romans, souvent le dimanche matin.",
      "Le matin, sans hésiter."
    ]
  };
  const sequences = new Set();
  for (let seed = 1; seed <= 30; seed++) {
    for (const [style, answers] of Object.entries(styles)) {
      const { lines } = interview(engineFor(seed), answers, 105, 12);
      sequences.add(lines.join("|"));
      const cores = lines.map((line) => flat(line).replace(/^(?:[^?]*?[.!] )+/, ""));
      assert.equal(new Set(cores).size, cores.length, `${style} ${seed}: ${lines.join(" / ")}`);
      for (const line of lines) {
        assert(line.trim().length > 0);
        assert.doesNotMatch(line, /Zorblax|ragoût|architectes|\(e\)/, line);
      }
    }
    const engine = engineFor(seed);
    const opening = engine.opening();
    const late = engine.next([{ question: opening, answer: "" }], 18);
    assert(wordCount(late) <= 12, late);
  }
  assert(sequences.size >= 80, `only ${sequences.size} distinct interviews`);
}

// Debriefs quote the learner exactly and stay neutral when nothing was transcribed.
{
  const banned = /NCLC|CECR|CEFR|\b[ABC][12]\b|score|\/\s*20|%|niveau|secondes|minutes/i;
  assert.deepEqual(defaultEngine.feedback([]), []);

  const engine = engineFor(5);
  const oral = interview(engine, Array(5).fill(""));
  const silent = engine.feedback(oral.turns);
  assert(silent.length >= 1 && silent.length <= 3);
  assert(silent.some((item) => oral.lines.some((line) => {
    const core = flat(line).replace(/^(?:[^?]*?[.!] )+/, "");
    return flat(item.detail).includes(core);
  })), "self-review should cite a question that was actually asked");
  for (const item of silent) {
    assert(item.title && item.detail);
    assert.doesNotMatch(item.title + item.detail, banned);
    assert.doesNotMatch(item.detail, /vous avez répondu|vous avez dit/);
  }

  const answers = ["Oui.", "Pardon, pouvez-vous répéter ?",
    "Je fais du yoga le matin parce que ça m'aide à me concentrer au travail."];
  const transcribed = interview(engineFor(9), answers);
  const notes = engine.feedback(transcribed.turns);
  assert(notes.length >= 2 && notes.length <= 3, JSON.stringify(notes));
  const quoted = notes.flatMap((item) => [...item.detail.matchAll(/«\s*([^»]+?)\s*»/g)])
    .map((match) => match[1].replace(/^…|…$/g, ""));
  const learnerQuotes = quoted.filter((text) => answers.some((answer) => answer.includes(text)));
  assert(learnerQuotes.some((text) => text.includes("parce que ça m'aide")), JSON.stringify(notes));
  assert(learnerQuotes.includes("Oui"), JSON.stringify(notes));
  assert(notes.some((item) => /reformul|répét/i.test(item.title + item.detail)));
  for (const item of notes) assert.doesNotMatch(item.title + item.detail, banned);
}

// Carry a concrete detail across consecutive turns, even without the local model.
{
  for (let seed = 1; seed <= 10; seed++) {
    const {lines} = interview(engineFor(seed), ["Je travaille de nuit dans une pharmacie.",
      "En général, je rentre à pied parce que le calme me fait du bien.",
      "Je prends cette rue parce que je peux passer devant la boulangerie."]);
    assert.match(lines[1], /nuit de travail/);
    assert.match(lines[2], /rentrez à pied/);
    assert.match(lines[3], /exemple/);
    assert.doesNotMatch(afterOpening(engineFor(seed), "Je ne travaille pas de nuit.").line, /nuit de travail/);
  }
}

// Quotes and corrections belong to the supplied turn, never to an examiner question.
{
  const {assess} = require("../static/study/js/expression/eo/tache_1/transcript-review");
  const review = (...answers) => assess(answers.map(answer => ({question:"Parlez-moi de vous.", answer, mode:"voice"})));
  const sample = ["j’habite à canada. Je travaille de nuit dans une pharmacie.",
    "Je rentre à pied parce que le calme me fait du bien avant de dormir.",
    "Hier, j’ai pris le chemin du parc pour écouter les oiseaux."];
  const result = review(...sample);
  assert.equal(result.band, "Indices de B1");
  assert.equal(result.typed, false);
  assert.equal(result.corrections[0].before, "j’habite à canada");
  assert.equal(result.corrections[0].after, "j’habite au Canada");
  assert.deepEqual(result.evidence.map(e => e.turn), [2, 3]);
  result.evidence.forEach(e => assert.equal(e.quote, sample[e.turn - 1]));
  assert.equal(review("Je peux de nouveau travailler.", "Je suis 22 ans plus jeune que mon frère.").corrections.length, 0);
  assert.equal(review("Je fais de le vélo.").corrections[0].after, "Je fais du vélo");
  assert.equal(review("", "Oui.", "Pardon ?").band, "");
  assert.equal(review("Je suis ici.", "Je suis ici.", "Je suis ici.").band, "");
  assert.notEqual(review("J’aime ma ville parce que ma famille ici.", "Je voudrais un café.", "Je suis étudiant.").band,
    "Indices de B1");
  assert.match(review("Je réside à Lyon depuis dix ans.", "J’exerce le métier de médecin.",
    "Je pratique la natation chaque semaine avec ma sœur.").band, /A2/);
}

console.log("EO1 interview and transcript review checks passed");
