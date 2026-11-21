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

// Held-out constraint checks: availability and equipment must lead to honest, fact-based advice.
function chain(...questions) {
  let ctx = engine.initial();
  return questions.map(q => { const r = engine.respond(q, ctx); ctx = r.context; return r; });
}
const [target, targetPrice] = chain("Je ne peux pas venir le samedi et je n’ai qu’un téléphone. Laquelle me convient ?", "Et c’est combien ?");
assert.match(target.reply, /balade ne vous convient pas.*samedi matin.*studio.*mercredi de 18 h à 20 h.*réserver un appareil photo, sans supplément/);
assert.doesNotMatch(target.reply, /votre téléphone suffit/);
assert.equal(targetPrice.reply, "Le studio coûte 35 dollars par personne.");
const across = chain("Le samedi, je travaille.", "Mon seul appareil, c’est mon téléphone. Vous me conseillez lequel ?");
assert.match(across[1].reply, /balade ne vous convient pas.*studio.*votre téléphone ne suffira pas.*réserver/);
assert.match(chain("bonjour je bosse tous les samedis j ai juste mon portable vous me conseillez quoi")[0].reply, /Je vous propose donc l’atelier en studio.*réserver/);
const voiceRepeat = chain("Je suis pris le samedi. Quelle formule me conseillez-vous ?", "Pardon, vous pouvez répéter ?", "Et l’autre ?");
assert.equal(voiceRepeat[1].reply, voiceRepeat[0].reply);
assert.match(voiceRepeat[2].reply, /^Non, la balade ne vous convient pas/);
assert.match(chain("Je ne suis pas disponible le samedi ni le mercredi soir. Lequel me conviendrait ?")[0].reply, /aucune des deux formules ne correspond.*samedi matin.*mercredi soir/);
const owner = chain("Je travaille le samedi, mais j’ai mon propre reflex. Quelle formule choisir ?")[0].reply;
assert.match(owner, /studio.*utiliser votre appareil photo/);
assert.doesNotMatch(owner, /réserver/);
assert.match(chain("Le mercredi soir, je suis occupée et je n’ai qu’un smartphone. Laquelle me va le mieux ?")[0].reply, /studio ne vous convient pas.*balade.*votre téléphone suffit/);
// Self-correction, within one turn and on the next turn.
assert.match(chain("Je ne peux pas le mercredi, pardon, je voulais dire le samedi. Laquelle me convient ?")[0].reply, /^La balade ne vous convient pas.*Je vous propose donc l’atelier en studio/);
const fixed = chain("Je ne peux pas venir le mercredi. Lequel me conseillez-vous ?", "Pardon, je me suis trompée : c’est le samedi.");
assert.match(fixed[0].reply, /^L’atelier en studio ne vous convient pas/);
assert.match(fixed[1].reply, /^La balade ne vous convient pas.*Je vous propose donc l’atelier en studio/);
const gearFix = chain("Laquelle me convient ?", "Je n’ai qu’un téléphone.", "Je n’ai pas qu’un téléphone, j’ai aussi un reflex.");
assert.match(gearFix[0].reply, /Cela dépend.*Quel créneau vous arrange/);
assert.match(gearFix[1].reply, /deux formules restent possibles.*votre téléphone suffit.*réserver un appareil photo/);
assert.match(gearFix[2].reply, /vous pourrez utiliser votre appareil photo/);
// Negative controls: someone else's constraint, negation, hypotheses and ambiguity are not guessed.
const daughter = chain("Ma fille ne peut pas venir le samedi, mais moi je n’ai qu’un téléphone. Laquelle me convient ?")[0].reply;
assert.match(daughter, /deux formules restent possibles/);
assert.doesNotMatch(daughter, /ne vous convient pas/);
assert.equal(chain("Mon mari travaille le samedi.")[0].parts[0].kind, "clarify");
assert.match(chain("Je ne travaille pas le samedi. Laquelle me convient ?")[0].reply, /deux formules restent possibles/);
const hypothetical = chain("Si je ne pouvais pas venir le samedi, laquelle me conviendrait ?", "Laquelle me convient ?");
assert.match(hypothetical[0].reply, /^La balade ne vous convient pas/);
assert.match(hypothetical[1].reply, /^Cela dépend de vos disponibilités/);
assert.match(chain("Je ne suis pas libre ce jour-là. Laquelle me convient ?")[0].reply, /samedi ou du mercredi/);
assert.match(chain("Je ne sais pas encore si je serai libre le samedi. Lequel me conseillez-vous ?")[0].reply, /selon vos disponibilités/);
const askDay = chain("Est-ce que je peux venir le samedi ?", "Laquelle me convient ?");
assert.equal(askDay[0].parts[0].intent, "schedule");
assert.match(askDay[1].reply, /^Cela dépend/);
// Existing simple questions keep their meaning when a day is mentioned.
assert.equal(chain("Je travaille le samedi, c’est combien ?")[0].reply, "Le studio coûte 35 dollars par personne.");
assert.equal(chain("Le samedi me va très bien, combien ça coûte ?")[0].reply, "La balade coûte 20 dollars par personne.");
assert.match(chain("Lequel est le moins cher ?")[0].reply, /20 dollars.*35 dollars/);
assert.equal(chain("Que me conseillez-vous de manger à Tokyo ?")[0].parts[0].kind, "clarify");
assert.deepEqual(engine.feedback([{question:"Laquelle me convient ?", ...target}]).evidence.map(e => e.label), [engine.labels.fit]);

require("./eo2_live_feedback_check");
