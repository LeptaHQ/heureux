const assert = require("node:assert/strict");
const engine = require("../static/study/js/expression/eo/tache_2/roleplay-engine");
let context = engine.initial();
const turns = [];
function ask(question) {
  const result = engine.respond(question, context);
  context = result.context;
  turns.push({question, ...result});
  return result.reply;
}

assert.match(ask("Bonjour, je voudrais me renseigner sur vos ateliers de photographie."), /balade.*studio/);
assert.match(ask("Quel budget prévoir pour la balade ?"), /20 dollars/);
assert.match(ask("Et l’autre ?"), /35 dollars/);
assert.match(ask("Je n’ai qu’un téléphone, ça marche aussi ?"), /En studio/);
const gear = ask("Et pour la première formule ?");
assert.match(gear, /balade.*téléphone/);
assert.equal(ask("Vous pouvez répéter ?"), gear);
assert.match(ask("Pas celui du mercredi : celui du samedi coûte combien ?"), /20 dollars/);
assert.match(ask("Celui du samedi… pardon, du mercredi."), /35 dollars/);
assert.match(ask("C’est le total ou juste un acompte ?"), /prix total/);
assert.match(ask("Il faut payer combien de temps avant ?"), /réglez à l’accueil/);
assert.match(ask("Que me conseillez-vous de manger à Tokyo ?"), /préciser/);
assert.match(engine.respond("Et l’autre ?").reply, /balade au parc ou.*studio/);
const two = engine.respond("Combien coûte le studio et quand a-t-il lieu ?");
assert.match(two.reply, /35 dollars.*mercredi/);
assert.deepEqual(two.parts.map(x => x.intent), ["price","schedule"]);
assert.doesNotMatch(engine.respond("Où et quand se déroule la balade ?").reply,/studio/);
assert.match(engine.respond("Avez-vous des tarifs réduits ?").reply,/pas de tarif réduit/);
const notes = engine.feedback(turns);
assert.equal(notes.linked, "Et l’autre ?");
assert(notes.evidence.every(e => turns[e.turn - 1].question === e.question));
assert(!notes.evidence.some(e => e.turn === 6));
assert.equal(engine.respond("Hmmm", engine.initial(), "invent_a_price").parts[0].kind, "clarify");
assert.equal(engine.feedback([]).evidence.length,0);
