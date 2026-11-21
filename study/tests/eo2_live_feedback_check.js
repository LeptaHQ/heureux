const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const feedbackPath = path.join(__dirname, "../static/study/js/expression/eo/tache_2/live-feedback.js");
const {assess} = require(feedbackPath);
const user = text => ({speaker: "user", text});
const model = text => ({speaker: "model", text});
const linked = result => result.evidence.filter(item => item.context);

// Evidence is verbatim, topic-independent, and tied to a specific preceding reply.
for (const [first, reply, followup] of [
  ["Quelles sorties proposez-vous ?", "Nous proposons une visite guidée.",
    "Pour la visite guidée, faut-il réserver ?"],
  ["Quels documents dois-je apporter ?", "Il vous faut une attestation de domicile.",
    "Concernant l’attestation de domicile, puis-je envoyer une copie ?"],
  ["Comment fonctionne la bibliothèque ?", "Nous proposons un prêt numérique.",
    "Vous avez parlé d’un prêt numérique. Comment puis-je y accéder ?"],
  ["Pour me déplacer sans voiture, quels transports me conseillez-vous ?",
    "Le bus de quartier passe toutes les vingt minutes.",
    "Le bus de quartier passe aussi en soirée ?"],
]) {
  const rows = [user(first), model(reply), user(followup)];
  const snapshot = JSON.stringify(rows);
  const result = assess(rows);
  assert.deepEqual(linked(result), [{
    label: "Détail de la réponse repris", quote: followup, context: reply,
  }]);
  assert.match(result.next, /Vous reprenez un détail de la réponse/);
  result.evidence.forEach(item => assert(rows.some(row => row.speaker === "user" && row.text === item.quote)));
  assert.equal(JSON.stringify(rows), snapshot);
  assert.deepEqual(assess(rows), result);
  assert.doesNotMatch(JSON.stringify(result), /CEFR|CECR|NCLC|\b[ABC][12]\b|prononciation|note officielle/);
}

// A generic connector, a keyword, a statement or an old reply is not enough.
{
  const reply = model("Nous proposons une visite guidée.");
  for (const text of [
    "Et combien coûte le billet ?", "Et pour la visite ?",
    "Pour la visite guidée, je vais réfléchir.",
    "Pour la visite guidée, combien de",
  ]) {
    assert.equal(linked(assess([reply, user(text)])).length, 0, text);
  }
  const followup = user("Pour la visite guidée, faut-il réserver ?");
  assert.equal(linked(assess([reply, model("Nous sommes fermés demain."), followup])).length, 0);
  assert.equal(linked(assess([reply, user("Merci."), followup])).length, 0);
  assert.equal(linked(assess([{...reply, interrupted: true}, followup])).length, 0);
  assert.equal(linked(assess([model("Voulez-vous une visite guidée ?"), followup])).length, 0);
  assert.equal(linked(assess([user("Proposez-vous une visite guidée ?"), reply, followup])).length, 0);
  assert.equal(linked(assess([
    model("C’est un point très important."),
    user("Pour ce point très important, pouvez-vous donner un exemple ?"),
  ])).length, 0);
  assert.equal(linked(assess([
    model("Je peux vous donner des renseignements."),
    user("Pouvez-vous me donner des renseignements sur les tarifs ?"),
  ])).length, 0);
  // Repetition can be observed, but must never be praised as useful or unanswered.
  const duplicate = assess([
    model("La visite guidée dure deux heures."),
    user("Pour la visite guidée, combien de temps dure-t-elle ?"),
  ]);
  assert.equal(linked(duplicate).length, 1);
  assert.match(duplicate.next, /n’a pas déjà été donnée/);
  assert.doesNotMatch(linked(duplicate)[0].label, /pertinente|utile|réussie/);
}

// Partial speech, statements and a lone question receive appropriately limited guidance.
{
  for (const rows of [[], [model("Quel est le tarif ?")], [user("  ")]]) {
    const result = assess(rows);
    assert.deepEqual(result.evidence, []);
    assert.deepEqual(result.corrections, []);
    assert.match(result.next, /Aucune parole personnelle/);
  }
  for (const text of ["Bonjour.", "Merci beaucoup.", "Je voudrais participer.", "Je sais quand il faut venir.",
    "Je sais que vous pouvez répéter les exercices.", "Vous pouvez répéter la question.",
    "Quand il est tard, vous pouvez partir.", "Comment il est arrivé ici reste un mystère."]) {
    const result = assess([user(text)]);
    assert.deepEqual(result.evidence, [], text);
    assert.match(result.next, /Je ne repère pas de demande/, text);
  }
  for (const row of [
    user("Pour les documents, combien de"),
    user("Quand est-ce que…"),
    {...user("Quel est le prix ?"), interrupted: true},
  ]) {
    const result = assess([row]);
    assert.deepEqual(result.evidence, []);
    assert.match(result.next, /incomplètes/);
  }
  // A plain question counts as a question but earns no strength label.
  for (const text of ["Quel est le prix ?", "quels documents faut il apporter", "Vous avez un créneau demain ?",
    "Vous êtes où ?", "Pouvez-vous répéter ces exercices tous les jours ?"]) {
    const result = assess([user(text)]);
    assert.deepEqual(result.evidence, [], text);
    assert.match(result.next, /pas encore de réponse/, text);
  }
  assert.deepEqual(assess([model("Quel est le prix ?"), user("Quel est le prix ?")]).evidence, []);
  const clarification = assess([model("Il faut un justificatif."), user("Vous pouvez reformuler ?")]);
  assert.equal(clarification.evidence[0].label, "Demande de reformulation");
  assert.match(clarification.next, /Après la reformulation/);
  assert.equal(assess([user("Pardon, pourriez-vous répéter votre réponse ?")])
    .evidence[0].label, "Demande de reformulation");
  assert.deepEqual(assess([user("Bonjour, pourriez-vous m’indiquer les horaires ?")]).evidence, [
    {label:"Demande polie au conditionnel", quote:"Bonjour, pourriez-vous m’indiquer les horaires ?"},
  ]);
}

// Only reviewed learner text supplies corrections; spoken French is not formalized.
{
  const result = assess([
    model("Je va au parc."),
    {...user("Je suis besoin de réserver."), original: "Je va au parc."},
    user("Je suis besoin de venir."), user("Je veux de parler."),
    user("Je fais de le sport."), user("Je suis en train travailler."),
  ]);
  assert.deepEqual(result.corrections.map(({before, after}) => [before, after]), [
    ["Je suis besoin de", "J’ai besoin de"],
    ["Je veux de parler", "Je veux parler"],
    ["Je fais de le sport", "Je fais du sport"],
  ]);
  const spoken = ["Je peux de nouveau venir.", "J’ai pas de voiture.",
    "Ça coûte combien ?", "Je suis 22 ans plus jeune que mon frère.",
    "Je va, pardon, je vais venir.", "Pourquoi ne dit-on pas « je suis besoin de » ?"];
  assert.deepEqual(assess(spoken.map(user)).corrections, []);
  assert.deepEqual(assess([{...user("Je suis besoin de venir."), interrupted: true}]).corrections, []);
  assert.deepEqual(assess([{...user("Je vais venir."), original: "Je va venir."}]).corrections, []);
}

// Inline edits anchor to the right speaker, occurrence and UTF-16 offsets; no global string replacement.
{
  const rows = [model("Le guitare ?"), user(""), user("🎸 Je prends le guitare et je range le guitare."),
    model("Et vous ?"), user("Si je m’inscrire, quand commence la séance ?"),
    user("Je peux de venir. Je suis en train travailler.")];
  const {annotations} = assess(rows);
  assert.deepEqual(annotations.map(({turnIndex, before, after}) => [turnIndex, before, after]), [
    [2, "le", "la"], [2, "le", "la"], [4, "m’inscrire", "m’inscris"], [5, "de ", ""], [5, "", "de "],
  ]);
  for (const {turnIndex, start, end, before, why} of annotations) {
    assert.equal(rows[turnIndex].text.slice(start, end), before);
    assert(why);
  }
  const rebuild = index => annotations.filter(a => a.turnIndex === index).reduceRight(
    (text, a) => text.slice(0, a.start) + a.after + text.slice(a.end), rows[index].text);
  assert.equal(rebuild(2), "🎸 Je prends la guitare et je range la guitare.");
  assert.equal(rebuild(5), "Je peux venir. Je suis en train de travailler.");
  assert.deepEqual(assess([model("Il faut le guitare."), user("J’aimerais m’inscrire. Ça coûte combien ?")]).annotations, []);
  const spelling = assess([user("Ces activités m’intéresse beaucoup.")]).annotations[0];
  assert.equal(spelling.before, "m’intéresse");
  assert.equal(spelling.after, "m’intéressent");
  assert.match(spelling.why, /À l’écrit/);
  assert.deepEqual(assess([user("Le tarif pour ces activités m’intéresse beaucoup.")]).annotations, []);
  assert.deepEqual(assess([user("Puis-je m’inscrire ? Quand puis je m’inscrire ? Dois-je m’inscrire ?")]).annotations, []);
  assert.equal(assess([user("Oui, les guitares m’intéresse.")]).annotations[0].after, "m’intéressent");
  assert.deepEqual(assess([user("Je prends le guitare, pardon, la guitare.")]).annotations, []);
}

// Spoken restarts are proofreading suggestions, not grammar or delivery judgments.
{
  const text = "🎫 J’ai j'ai une question. J’ai donc voudrais réserver. Merci pour merci pour les horaires.";
  const {annotations} = assess([model(text), user(text + " À demain.")]);
  assert.equal(annotations.length, 3);
  assert(annotations.every(a => a.turnIndex === 1 && (text + " À demain.").slice(a.start, a.end) === a.before));
  assert.match(annotations[0].why, /doublon de transcription possible/);
  assert.match(annotations[2].why, /doublon de transcription possible/);
  const corrected = annotations.reduceRight((s, a) => s.slice(0, a.start) + a.after + s.slice(a.end), text);
  assert.equal(corrected, "🎫 J’ai une question. Je voudrais donc réserver. Merci pour les horaires.");
  for (const row of [user("Oui oui, c’est très très pratique."), user("Je dis « j’ai j’ai une question »."),
    user("J’ai, pardon, je voudrais réserver."), {...user("C’est c’est ouvert ?"), interrupted: true}]) {
    assert.deepEqual(assess([row]).annotations, []);
  }
}

// The classic browser script shares grammar only, never the Tâche 1 assessment.
{
  const sandbox = {window: {HeureuxEO1Review: {
    assess() { throw new Error("The Tâche 1 assessment must not run"); },
    phraseEdits: require("../static/study/js/expression/eo/tache_1/transcript-review").phraseEdits,
  }}};
  vm.runInNewContext(fs.readFileSync(feedbackPath, "utf8"), sandbox);
  const result = sandbox.window.HeureuxEO2Feedback.assess([user("Je suis besoin de venir.")]);
  assert.equal(result.corrections[0].after, "J’ai besoin de");
  const withoutGrammar = {window: {}};
  vm.runInNewContext(fs.readFileSync(feedbackPath, "utf8"), withoutGrammar);
  assert.match(withoutGrammar.window.HeureuxEO2Feedback.assess([user("Quel est le prix ?")]).next, /pas encore de réponse/);
}
console.log("EO2 local transcript feedback checks passed");
