/* A small, example-trained French intent classifier. The model picks an information
   goal, never a price, promise or schedule: those come from the scenario. */
(function (root, factory) {
  const engine = factory();
  if (root) root.HeureuxEO2 = engine;
  if (typeof module === "object" && module.exports) module.exports = engine;
})(typeof window === "object" ? window : null, function () {
  "use strict";
  const examples = {
    options: ["quels ateliers proposez-vous", "j’aimerais des renseignements sur vos cours de photographie", "je voudrais me renseigner", "quels cours avez-vous", "quelles sont les formules", "quelle différence entre les deux activités", "en quoi consiste le cours", "que va-t-on apprendre", "qu’est-ce qu’on fait concrètement", "qu’est-ce que vous proposez comme activités"],
    price: ["combien ça coûte", "ça revient à combien", "quel est le prix", "quels sont vos tarifs", "quel budget faut-il prévoir", "c’est payant", "à combien s’élève le tarif par personne", "c’est combien", "lequel est le moins cher"],
    included: ["qu’est-ce qui est compris dans le prix", "y a-t-il des frais supplémentaires", "faut-il payer un supplément", "qu’est-ce que le tarif inclut", "tout est inclus", "le prix comprend le matériel", "le prêt est-il gratuit", "dois-je payer le matériel en plus"],
    schedule: ["quels jours ont lieu les séances", "quand est-ce que ça se passe", "quels sont les horaires", "vous commencez à quelle heure", "quel créneau est disponible le week-end", "est-ce que vous ouvrez le samedi", "le soir est-ce possible", "à quelle heure ça finit"],
    duration: ["combien de temps ça dure", "quelle est la durée de la séance", "ça dure combien de temps", "combien d’heures faut-il prévoir", "pendant combien de temps"],
    places: ["reste-t-il des places", "combien de places restent disponibles", "est-ce complet", "peut-on encore venir à deux", "vous avez encore des disponibilités", "y a-t-il de la place pour deux personnes"],
    level: ["est-ce accessible aux débutants", "je n’ai jamais fait de photo", "je débute est-ce adapté", "je n’y connais rien est-ce que je peux participer", "faut-il déjà savoir se servir d’un appareil", "il faut de l’expérience", "quel niveau faut-il avoir"],
    gear: ["que faut-il apporter comme matériel", "est-ce que je dois avoir mon propre appareil", "vous prêtez le matériel", "je n’ai pas d’appareil photo", "puis-je venir avec mon téléphone", "je n’ai qu’un téléphone ça marche aussi", "un portable suffit-il", "fournissez-vous les appareils"],
    location: ["où est le rendez-vous", "où faut-il se retrouver", "c’est à quel endroit", "où se déroule l’atelier", "à quelle adresse se rendre", "comment venir en bus", "quel arrêt de bus"],
    booking: ["comment puis-je m’inscrire", "que dois-je faire pour réserver", "comment se passe l’inscription", "peut-on réserver par téléphone", "comment retenir une place", "est-ce que je peux m’inscrire sur place"],
    cancel: ["si je ne peux plus venir", "quelles sont les conditions d’annulation", "est-ce remboursable", "je dois annuler la veille", "puis-je me désister", "si j’ai un empêchement", "remboursé combien de temps avant", "comment changer de date"],
    rain: ["si jamais il pleut", "en cas de pluie", "s’il fait mauvais temps", "la météo annonce un orage", "que devient la sortie quand il pleut"],
    payment: ["comment peut-on payer", "acceptez-vous la carte bancaire", "je peux régler en espèces", "à quel moment faut-il régler", "quels moyens de paiement acceptez-vous"],
    deposit: ["est-ce le total ou un acompte", "faut-il verser un acompte", "c’est le prix total", "une avance à l’inscription"],
    discount: ["avez-vous des tarifs réduits", "y a-t-il une réduction pour les étudiants", "un rabais si on vient à deux", "vous faites un prix de groupe"],
  };
  const facts = {
    options: ["La première formule est une balade photo : on apprend à cadrer dans le parc.", "La deuxième est un atelier en studio : on découvre comment éclairer un portrait."],
    price: ["La balade coûte 20 dollars par personne.", "Le studio coûte 35 dollars par personne."],
    included: ["Les 20 dollars couvrent la balade et les conseils de la photographe, sans frais de matériel.", "Les 35 dollars comprennent la séance et le prêt d’un appareil sur réservation, sans supplément."],
    schedule: ["La balade a lieu le samedi de 10 h à 11 h 30.", "Le studio a lieu le mercredi de 18 h à 20 h."],
    duration: ["La balade dure une heure et demie.", "La séance en studio dure deux heures."],
    places: ["Il reste trois places pour la balade de samedi.", "Il reste deux places pour le studio de mercredi."],
    gear: ["Pour la balade, apportez un téléphone ou un appareil photo. On ne prête pas d’appareil au parc.", "En studio, il faut un appareil photo. Si vous n’en avez pas, je peux vous en faire réserver un sans supplément."],
    location: ["Pour la balade, rendez-vous à l’entrée du parc des Saules, devant le kiosque. L’arrêt de bus s’appelle « Parc des Saules ».", "Le studio est dans le centre culturel, salle deux, près de l’arrêt de bus « Centre culturel »."],
    level: ["La balade est ouverte aux débutants : on commence par le cadrage.", "Aucune expérience n’est nécessaire en studio. La photographe vous montre d’abord comment régler la lumière."],
    rain: ["En cas de forte pluie, la balade est reportée au samedi suivant. Si la nouvelle date ne convient pas, vous êtes remboursé.", "Le studio est en intérieur : la pluie ne change pas la séance."],
    booking: "Vous pouvez réserver à l’accueil ou par téléphone. Dites-nous la formule choisie ; le règlement se fait à l’accueil avant la séance.",
    cancel: "Vous pouvez déplacer ou annuler votre réservation sans frais jusqu’à la veille à 17 h. Après, prévenez-nous pour que nous libérions la place.",
    payment: "Vous réglez à l’accueil avant la séance, par carte ou en espèces.",
    deposit: "C’est le prix total par personne. Nous ne demandons pas d’acompte à l’inscription.",
    discount: "Nous n’avons pas de tarif réduit pour ces ateliers : le prix est le même pour chaque participant.",
  };
  const labels = {options:"les formules", price:"le prix", included:"les frais compris", schedule:"les horaires", duration:"la durée", places:"les places restantes", level:"le niveau requis", gear:"le matériel", location:"le lieu", booking:"l’inscription", cancel:"l’annulation", rain:"la météo", payment:"le paiement", deposit:"l’acompte", discount:"les réductions"};
  const opening = "Bonjour, bienvenue au centre culturel. Je vous écoute.";
  const fold = s => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().replace(/œ/g,"oe").replace(/[^a-z0-9]+/g," ").trim();
  const stop = new Set("a ai au aux bonjour c ca ce ces cet cette d dans de des dois doit du elle en est et etre faut il ils j je la le les l ma me mon n ne nos notre nous on ou par pas peut peux pour puis qu quand que quel quelle quelles quels qui s se si son sont suis t un une vos votre vous y".split(" "));
  function features(line) {
    const result = new Map();
    for (const w of fold(line).split(" ").filter(w => !stop.has(w) && w.length > 1)) {
      result.set("=" + w, 2);
      const padded = "^" + w + "$";
      for (let i = 0; i + 2 < padded.length; i++) result.set(padded.slice(i, i + 3), 1);
    }
    return result;
  }
  const docs = Object.entries(examples).flatMap(([intent, lines]) => lines.map(line => ({intent, f:features(line)})));
  const df = new Map();
  docs.forEach(d => d.f.forEach((v, k) => df.set(k, (df.get(k) || 0) + 1)));
  function vector(f) {
    let norm = 0;
    f.forEach((v, k) => {
      const weight = v * (1 + Math.log((docs.length + 1) / ((df.get(k) || 0) + 1)));
      f.set(k, weight); norm += weight * weight;
    });
    f.forEach((v, k) => f.set(k, v / Math.sqrt(norm)));
    return f;
  }
  docs.forEach(d => vector(d.f));
  function rank(line) {
    const query = vector(features(line)), scores = {};
    for (const {intent, f} of docs) {
      let sim = 0;
      f.forEach((v, k) => { sim += v * (query.get(k) || 0); });
      scores[intent] = Math.max(scores[intent] || 0, sim);
    }
    return Object.entries(scores).sort((a,b) => b[1] - a[1]);
  }
  const first = /\b(?:balade|sortie|promenade|parc|exterieur|premier|premiere|samedi)\b/;
  const second = /\b(?:studio|portrait|interieur|deuxieme|second|seconde|mercredi)\b/;
  const alternate = /\b(?:l autre|autre formule|autre atelier)\b/;
  function initial() { return {option:null, intent:null, last:opening}; }
  function resolve(question, ctx, inferred) {
    const s = fold(question);
    const clarify = (reply = "Je ne suis pas sûr d’avoir compris. Vous pouvez préciser ce que vous voulez savoir sur les ateliers ?") =>
      ({reply, next:{...ctx,last:reply}, intent:"", kind:"clarify"});
    if (/^(?:bonjour|bonsoir|salut|bonjour madame|bonjour monsieur|excusez moi)$/.test(s))
      return {reply:opening,next:{...ctx,last:opening},intent:"",kind:"social"};
    if (/^(?:d accord |tres bien )?(?:merci|au revoir|bonne journee|c est tout|merci beaucoup)(?: pour (?:votre aide|ces renseignements))?(?: (?:au revoir|bonne journee|merci|beaucoup))*$/.test(s))
      return {reply:"Avec plaisir. Bonne journée à vous !",next:ctx,intent:"",kind:"social"};
    if (/\b(?:repete[rz]|redire|pas (?:bien )?entendu)\b/.test(s))
      return {reply:ctx.last,next:ctx,intent:"",kind:"repeat"};
    const referenced = s.replace(/^.*?\b(?:pardon|je voulais dire|je veux dire)\b\s+(?=\S)/, "")
      .replace(/\bpas (?:celui |celle )?(?:(?:du |de |la |le |en |au |d ))*(?:samedi|mercredi|balade|studio|parc|portrait)\b/g, "");
    let a = first.test(referenced), b = second.test(referenced);
    // Weekdays can be constraints rather than a reference to a different workshop.
    if (/\b(?:studio|portrait)\b/.test(s) && /\bsamedi\b/.test(s) && !/\b(?:balade|parc)\b/.test(s)) a = false;
    if (/\b(?:balade|parc)\b/.test(s) && /\bmercredi\b/.test(s) && !/\bstudio\b/.test(s)) b = false;
    let option = a === b ? ctx.option : a ? 0 : 1;
    if ((a && b) || /\b(?:les deux|chaque formule|chacun|laquelle|lequel)\b/.test(s)) option = null;
    if (alternate.test(s) && !a && !b) {
      if (ctx.option === null) return clarify("Vous voulez parler de la balade au parc ou de l’atelier en studio ?");
      option = 1 - ctx.option;
    }
    const elliptical = /^(?:oui |d accord |alors )?(?:et )?(?:pour )?(?:(?:le|la|celui|celle|en|au|du|l) )*(?:premier|premiere|deuxieme|second|seconde|balade|studio|autre|samedi|mercredi)(?: (?:atelier|formule|cours|aussi))?$/.test(referenced);
    const content = s.replace(/\b(?:premier|premiere|deuxieme|second|seconde|balade|studio|atelier|ateliers|photo|photographie|formule|formules)\b/g," ");
    const ranked = rank(content);
    let intent = elliptical ? ctx.intent || "options" : "";
    if (!intent && /\b(?:acompte|prix total)\b/.test(s)) intent = "deposit";
    if (!intent && /\b(?:payer|regler)\b/.test(s) && /\b(?:quand|moment|temps avant)\b/.test(s)) intent = "payment";
    if (!intent && /\b(?:quand|quel jour|quelle heure|a quelle heure|quel creneau)\b/.test(s) && !/\b(?:annul|reserv|inscri|payer|regler|pluie|pleut)/.test(s)) intent = "schedule";
    if (!intent && (s === "ou" || /\b(?:ou se (?:passe|trouve)|ou (?:ca|exactement)|quel endroit|quelle adresse)\b/.test(s))) intent = "location";
    if (!intent && /\b(?:combien de temps|quelle duree)\b/.test(s) && !/\b(?:avant|annul)/.test(s)) intent = "duration";
    if (!intent && /\b(?:quels ateliers|quelles (?:formules|activites)|quelle difference|que proposez vous)\b/.test(s)) intent = "options";
    if (!intent && ranked[0][1] >= 0.38 && ranked[0][1] - ranked[1][1] >= 0.065) intent = ranked[0][0];
    if (!intent && Object.hasOwn(examples, inferred)) intent = inferred;
    if (!intent) return clarify();
    if (intent === "options" && !a && !b && !alternate.test(s)) option = null;
    const fact = facts[intent];
    const reply = typeof fact === "string" ? fact : option === null ? fact.join(" ") : fact[option];
    return {reply, intent, kind:"fact", option, linked:Boolean(ctx.intent && (elliptical || alternate.test(s))),
      next:{option,intent,last:reply}};
  }
  function respond(question, previous = initial(), inferred) {
    const parts = question.trim().split(/\?\s*(?=\S)|\s+et\s+(?=(?:combien|quand|comment|où|à quelle heure|est-ce que)\b)/iu).filter(Boolean).slice(0, 2);
    let next = previous;
    if (parts.length === 2 && !first.test(fold(parts[0])) && !second.test(fold(parts[0]))) {
      // In « Où et quand a lieu la balade ? », both requests share one object.
      const later = fold(parts[1]);
      if (first.test(later) !== second.test(later)) next = {...previous,option:first.test(later) ? 0 : 1};
    }
    const partsRead = parts.map(p => { const out = resolve(p, next, parts.length === 1 ? inferred : undefined); next = out.next; return out; });
    const reply = [...new Set(partsRead.map(x => x.reply))].join(" ");
    return {reply, context:{...next,last:reply}, parts:partsRead.map(({intent,kind,linked}) => ({intent,kind,linked}))};
  }
  function feedback(turns) {
    const evidence = [], seen = new Set();
    for (const [i,t] of turns.entries()) {
      for (const p of t.parts || []) {
        if (p.kind !== "fact" || seen.has(p.intent)) continue;
        evidence.push({turn:i+1, label:labels[p.intent], question:t.question}); seen.add(p.intent);
      }
    }
    const linked = turns.find(t => t.parts?.some(p => p.linked));
    const next = !seen.has("price") ? "Pour décider, comparez le prix des deux formules." :
      !seen.has("gear") ? "Vérifiez si vous pouvez participer avec le matériel que vous avez." :
      !seen.has("booking") ? "Avant de conclure, renseignez-vous sur la façon de réserver." :
      "Pour conclure, résumez la formule qui vous convient et remerciez votre interlocuteur.";
    return {evidence,linked:linked?.question || "",next};
  }
  return {opening,initial,respond,feedback,labels};
});
