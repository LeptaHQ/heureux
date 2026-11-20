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
  const slot = ["le samedi de 10 h à 11 h 30", "le mercredi de 18 h à 20 h"];
  const facts = {
    options: ["La première formule est une balade photo : on apprend à cadrer dans le parc.", "La deuxième est un atelier en studio : on découvre comment éclairer un portrait."],
    price: ["La balade coûte 20 dollars par personne.", "Le studio coûte 35 dollars par personne."],
    included: ["Les 20 dollars couvrent la balade et les conseils de la photographe, sans frais de matériel.", "Les 35 dollars comprennent la séance et le prêt d’un appareil sur réservation, sans supplément."],
    schedule: [`La balade a lieu ${slot[0]}.`, `Le studio a lieu ${slot[1]}.`],
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
  const labels = {options:"les formules", price:"le prix", included:"les frais compris", schedule:"les horaires", duration:"la durée", places:"les places restantes", level:"le niveau requis", gear:"le matériel", location:"le lieu", booking:"l’inscription", cancel:"l’annulation", rain:"la météo", payment:"le paiement", deposit:"l’acompte", discount:"les réductions", fit:"la formule adaptée"};
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
  // The learner's own day and equipment constraints, read with small explicit rules.
  const dayOf = ["sat", "wed"], when = ["le samedi matin", "le mercredi soir"], named = ["la balade", "l’atelier en studio"];
  const cue = /\b(?:(travaill\w*|bosse\w*|pris|prise|occupee?s?|absente?s?|empeche\w*|indisponibles?|impossible|complique|ai (?:un |des )?(?:cours|rendez vous|empechement|engagement))|(peux|pourrai\w*|pouvons|pourrons|pourrions|libres?|disponibles?|dispo|possible|convien\w*|va|ira|irait|arrange\w*|viens|viendrai\w*|venir))\b/;
  const hedge = /\b(?:sais pas|sais plus|peut etre|pas sure?|pas certaine?|verrai|verra|probablement|normalement|depend|crois|pense|aucune idee)\b/;
  const only = /\b(?:ne?\b(?: (?!pas\b|plus\b|jamais\b|parce\b|rien\b)\w+){0,3} (?:que|qu)|seulement|uniquement|juste) (?:en |le |la |les )?(?:samedi|mercredi|soir|week)/;
  const off = {sat:/\bsamedis? (?:en |dans l )?(?:apres midi|soir|soiree)\b/, wed:/\bmercredis? (?:en |dans la )?(?:matin|apres midi|midi|journee)\b/};
  const corr = /^(?:(?:ah|oh|euh|non) )*(?:pardon|je veux dire|je voulais dire|je me suis trompee?|enfin non)\b ?/;
  const qform = /^(?:et |mais |alors |donc )?(?:est ce|qu est ce|quel|quelle|quels|quelles|lequel|laquelle|combien|quand|comment|pourquoi|ou|peut on|puis je|pourrais je|peux je|pouvez vous|vous pouvez|y a t il)\b|\b(?:est ce|celui|celle|ceux|celles)\b/;
  const other = /\b(?:il(?! (?:y|faut|fait|pleut|me|m|nous|reste|(?:est|serait|sera) (?:im)?possible)\b)|ils|elles?|lui|eux|(?:mon|ma|mes|son|sa|ses|notre|nos|leur|leurs) (?:\w+ )?(?:amie?s?|mari|femme|epou\w*|conjoint\w*|copain\w*|copine\w*|fils|filles?|enfants?|freres?|soeurs?|pere|mere|parents?|collegues?|voisin\w*|partenaire\w*|cousin\w*|patron\w*|chef|colocataire\w*))\b/;
  const filler = new RegExp(`${cue.source}|${hedge.source}|\\b(?:je|j|moi|me|m|nous|on|ne|n|pas|jamais|ni|non|plus|oui|si|aussi|egalement|pareil|plutot|le|la|les|l|du|de|d|ce|cette|pour|que|qu|suis|sommes|est|c|en fait|finalement|samedis?|mercredis?|week ?ends?|fin de semaine|soirs?|soirees?|matins?|apres midi|parce|car|jour la|date|creneau)\\b`, "g");
  const fitAsk = /\b(?:(?:laquelle|lequel|quelle formule|quel atelier|quelle option|quel cours)\b.{0,40}\b(?:convien\w*|conseill\w*|recommand\w*|choisir|prendre|mieux|correspond\w*|irait|ira)|(?:balade|studio|atelier|formule|lequel|laquelle) (?:me|nous|m) (?:conviendr|correspondr|ir)ai\w*|(?:qui|quoi|lequel|laquelle) (?:me|nous) (?:convien|correspond)\w*|est ce que .{0,30}(?:me|nous) convien\w*|(?:me|nous) (?:conseill|recommand)\w*(?! (?:vous )?d(?:e|u|es)? (?!choisir|prendre)\w)|(?:peut|pourrait|pourraient|peuvent) (?:me|nous) convenir|que (?:me|nous) reste|me reste t il)\b/;
  function statements(question, ctx) {
    const fit = {...ctx.fit}, view = {...fit}, kept = [], clauses = [];
    const freed = new Set();
    const put = (k, v, hyp) => { view[k] = v; if (!hyp) fit[k] = v; if (dayOf.includes(k)) freed[v === "free" ? "add" : "delete"](k); };
    const drop = (k, hyp) => { delete view[k]; if (!hyp) delete fit[k]; };
    let prev = null, carry = false, mark = -1, day = false, gear = false, unclear = false, bare = true;
    for (const [n, [, text, end]] of [...question.matchAll(/([^.;:!?…]+)([.;:!?…]*)/gu)].entries()) {
      const pieces = text.split(/,\s*(?=(?:et|mais|je|j['’]|moi|nous|on|il|ils|elle|elles|mon|ma|mes|son|sa|ses|ça|ca|pardon|plutôt|(?:le |la )?(?:samedi|mercredi|week))\b)/iu)
        .flatMap(p => fold(p).split(/ (?=(?:mais|par contre|en revanche|sauf que|pardon|je veux dire|je voulais dire|enfin non|plutot|laquelle|lequel|quelle formule|quel atelier|est ce que|combien|et (?:je|j|moi|nous|on|il|elle|ils|elles|mon|ma|mes|son|sa|ses|pas|non|ni|le|la|samedi|mercredi))\b)|(?<!\b(?:sais|pas|encore|demande|savoir|voir)) (?=(?:si|s il)\b)/)).filter(Boolean);
      pieces.forEach((c, i) => clauses.push({c, n, q:i === pieces.length - 1 && end.includes("?")}));
    }
    for (let i = 0; i < clauses.length; i++) {
      let {c, q} = clauses[i], status, oppose = false;
      const after = clauses[i + 1];
      // « Le samedi, je travaille » arrives as two clauses.
      if (after?.n === clauses[i].n && !qform.test(after.c) && /^(?:et |mais )?(?:le |la |les |ce |du )?(?:samedis?|mercredis?|week ?ends?)(?: (?:matin|soir|apres midi))?$/.test(c) && !/\b(?:samedi|mercredi|week)/.test(after.c) && cue.test(after.c)) { c += " " + after.c; q = after.q; i++; }
      const raw = c, fixed = carry || corr.test(c), marker = carry ? mark : -1, contrast = /^(?:mais|par contre|en revanche|sauf)\b/.test(c);
      c = c.replace(corr, "").replace(/^(?:en fait|finalement) /, "");
      carry = false;
      if (!c) { carry = true; mark = kept.push(raw) - 1; continue; }
      let days = [/\b(?:samedis?|week ?ends?|fin de semaine)\b/, /\bmercredis?\b/].flatMap((r, k) => r.test(c) ? [dayOf[k]] : []);
      if (!days.length && /\b(?:soirs?|soirees?)\b/.test(c)) days = ["wed"];
      const deictic = !days.length && /\b(?:ce jour la|cette date|ce creneau|cette journee)\b/.test(c);
      const hyp = /^(?:et )?(?:si|s il|au cas|en cas|imaginons|supposons)\b/.test(c), mine = /\b(?:moi|nous|on)\b/.test(c) || !other.test(c), m = cue.exec(c);
      if (hedge.test(c)) status = "unsure";
      else if (m && only.test(c) && days.length === 1) { status = m[1] ? "busy" : "free"; oppose = true; }
      else if (m) {
        const neg = c.slice(0, m.index).split(" ").slice(-4).some(w => /^(?:ne|n|pas|jamais|ni)$/.test(w)) || c.slice(m.index + m[0].length).trim().split(" ").slice(0, 2).some(w => /^(?:pas|jamais)$/.test(w));
        status = Boolean(m[1]) !== neg ? "busy" : "free";
      } else if (days.length || deictic) {
        const same = /\b(?:aussi|egalement|pareil|non plus|ni|idem)\b/.test(c);
        if (!hyp && /\b(?:oui|si|plutot)\b/.test(c)) status = "free";
        else if (prev) status = same || fixed || !(contrast || /\b(?:non|pas)\b/.test(c)) ? prev : {busy:"free", free:"busy"}[prev] || prev;
        else if (ctx.intent === "fit" && (fixed || same) && fit.recent) status = fit[fit.recent];
        else if (ctx.intent === "fit" && /\b(?:pas|ni|jamais)\b/.test(c)) status = "busy";
      }
      const constraint = Boolean(status && (days.length || deictic) && !qform.test(c) && !(q && status === "free" && !prev));
      if (constraint && mine) {
        if (deictic && ctx.option == null) { unclear = true; continue; }
        if (deictic) days = [dayOf[ctx.option]];
        if (fixed && view.recent && !days.includes(view.recent)) drop(view.recent, hyp);
        days.forEach(d => put(d, off[d].test(c) ? "unsure" : status, hyp));
        if (oppose) put(dayOf[1 - dayOf.indexOf(days[0])], status === "busy" ? "free" : "busy", hyp);
        put("recent", days[days.length - 1], hyp);
        day = true;
      }
      let g;
      if (mine && !qform.test(c)) {
        const phone = /\b(?:telephone|portable|smartphone|cellulaire|cell|mobile|iphone)\b/.test(c), camera = /\b(?:appareils?|reflex|camera)\b/.test(c);
        if (/\bpas (?:qu|que|seulement|juste|uniquement)\b/.test(c)) g = camera ? "camera" : null;
        else if (/\b(?:pas|sans|aucun|plus) (?:d |de |d un |un |une |vrai |de vrai |mon |propre )*(?:appareil|reflex|camera)\b/.test(c)) g = phone ? "phone" : "none";
        else if (phone && /\b(?:n (?:ai|avons|a)(?: rien d autre)? qu|seulement|juste|uniquement|simplement|seule?)\b/.test(c)) g = "phone";
        else if (camera && /\b(?:j ai|nous avons|on a|j aurai|j apporte\w*|j amene\w*|je (?:viendrai|viens) avec|mon propre|ma propre|je possede)\b/.test(c) && !/\b(?:ne|n|pas)\b/.test(c)) g = "camera";
        if (g !== undefined) { if (g) put("gear", g, hyp); else drop("gear", hyp); gear = true; }
      }
      if (constraint) { prev = status; kept.push(c.replace(filler, " ")); if (marker >= 0) kept[marker] = ""; }
      else { kept.push(raw); if (g === undefined) bare = false; }
    }
    return {fit, view, day, gear, unclear, bare, free:[...freed], rest:kept.join(" ").replace(/\s+/g, " ").trim()};
  }
  function advise(fit, focus) {
    const busy = i => fit[dayOf[i]] === "busy", free = i => fit[dayOf[i]] === "free", open = [0, 1].filter(i => !busy(i));
    const tool = [{phone:"votre téléphone suffit", none:"un téléphone suffit", camera:"vous pouvez venir avec votre appareil photo"}[fit.gear] || "un téléphone ou un appareil photo suffit",
      {phone:"votre téléphone ne suffira pas, mais je peux vous faire réserver un appareil photo, sans supplément", none:"je peux vous faire réserver un appareil photo, sans supplément", camera:"vous pourrez utiliser votre appareil photo"}[fit.gear] || "il faut un appareil photo, mais je peux vous en faire réserver un sans supplément si vous n’en avez pas"];
    const kit = i => `Pour ${["la balade", "le studio"][i]}, ${tool[i]}.`, no = i => `${named[i]} ne vous convient pas : ${["elle", "il"][i]} a lieu ${when[i]}.`;
    let reply;
    if (focus !== null) reply = busy(focus) ? `Non, ${no(focus)}` : `${free(focus) ? "Oui" : "Oui, si ce créneau vous convient"} : ${named[focus]} a lieu ${slot[focus]}. ${kit(focus)}`;
    else if (!fit.sat && !fit.wed && !fit.gear) reply = `Cela dépend de vos disponibilités et de votre matériel. La balade a lieu ${slot[0]}, et le studio, ${slot[1]}. Quel créneau vous arrange, et avez-vous un appareil photo ?`;
    else if (!open.length) reply = `Malheureusement, aucune des deux formules ne correspond à vos disponibilités : la balade a lieu ${when[0]}, et le studio, ${when[1]}.`;
    else if (open.length === 1) { const j = open[0], n = no(1 - j); reply = `${n[0].toUpperCase()}${n.slice(1)} Je vous propose donc ${named[j]}, ${slot[j]}${free(j) ? "" : ", si ce créneau vous convient"}. ${kit(j)}`; }
    else reply = `Les deux formules ${free(0) && free(1) ? "sont possibles" : "restent possibles selon vos disponibilités"} : la balade, ${slot[0]}, ou l’atelier en studio, ${slot[1]}. ${fit.gear ? `Pour la balade, ${tool[0]} ; pour le studio, ${tool[1]}.` : "Avez-vous un appareil photo ?"}`;
    return {reply, option:focus ?? (open.length === 1 ? open[0] : null)};
  }
  function initial() { return {option:null, intent:null, last:opening, fit:{}}; }
  function resolve(question, ctx, inferred) {
    let s = fold(question);
    const clarify = (reply = "Je ne suis pas sûr d’avoir compris. Vous pouvez préciser ce que vous voulez savoir sur les ateliers ?") =>
      ({reply, next:{...ctx,last:reply}, intent:"", kind:"clarify"});
    if (/^(?:bonjour|bonsoir|salut|bonjour madame|bonjour monsieur|excusez moi)$/.test(s))
      return {reply:opening,next:{...ctx,last:opening},intent:"",kind:"social"};
    if (/^(?:d accord |tres bien )?(?:merci|au revoir|bonne journee|c est tout|merci beaucoup)(?: pour (?:votre aide|ces renseignements))?(?: (?:au revoir|bonne journee|merci|beaucoup))*$/.test(s))
      return {reply:"Avec plaisir. Bonne journée à vous !",next:ctx,intent:"",kind:"social"};
    if (/\b(?:repete[rz]|redire|pas (?:bien )?entendu)\b/.test(s))
      return {reply:ctx.last,next:ctx,intent:"",kind:"repeat"};
    const said = statements(question, ctx), asksFit = fitAsk.test(s);
    ctx = {...ctx, fit:said.fit};
    if (said.unclear) return clarify("Vous parlez du samedi ou du mercredi ?");
    s = said.rest;
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
    if (!intent && asksFit) intent = "fit";
    if (!intent && /\b(?:acompte|prix total)\b/.test(s)) intent = "deposit";
    if (!intent && /\b(?:payer|regler)\b/.test(s) && /\b(?:quand|moment|temps avant)\b/.test(s)) intent = "payment";
    if (!intent && /\b(?:quand|quel jour|quelle heure|a quelle heure|quel creneau)\b/.test(s) && !/\b(?:annul|reserv|inscri|payer|regler|pluie|pleut)/.test(s)) intent = "schedule";
    if (!intent && (s === "ou" || /\b(?:ou se (?:passe|trouve)|ou (?:ca|exactement)|quel endroit|quelle adresse)\b/.test(s))) intent = "location";
    if (!intent && /\b(?:combien de temps|quelle duree)\b/.test(s) && !/\b(?:avant|annul)/.test(s)) intent = "duration";
    if (!intent && /\b(?:quels ateliers|quelles (?:formules|activites)|quelle difference|que proposez vous)\b/.test(s)) intent = "options";
    if (!intent && ranked[0][1] >= 0.38 && ranked[0][1] - ranked[1][1] >= 0.065) intent = ranked[0][0];
    // A turn made only of constraints updates the advice instead of being read as a question.
    if (said.bare && (said.day || said.gear)) intent = said.day || ctx.intent === "fit" ? "fit" : "gear";
    else if ((said.day || (said.gear && ctx.intent === "fit")) && (!intent || intent === "gear")) intent = "fit";
    if (!intent && (Object.hasOwn(examples, inferred) || inferred === "fit")) intent = inferred;
    if (!intent) return clarify();
    if (intent === "options" && !a && !b && !alternate.test(s)) option = null;
    // « Je travaille le samedi, c’est combien ? » points to the only workshop left.
    const open = said.free.length === 1 ? [dayOf.indexOf(said.free[0])] : [0, 1].filter(i => said.view[dayOf[i]] !== "busy");
    if (said.day && !a && !b && !alternate.test(s) && open.length === 1) option = open[0];
    let reply;
    if (intent === "fit") ({reply, option} = advise(said.view, a || b || alternate.test(s) ? option : null));
    else { const fact = facts[intent]; reply = typeof fact === "string" ? fact : option === null ? fact.join(" ") : fact[option]; }
    return {reply, intent, kind:"fact", option, linked:Boolean(ctx.intent && (elliptical || alternate.test(s))),
      next:{option,intent,last:reply,fit:said.fit}};
  }
  function respond(question, previous = initial(), inferred) {
    const parts = question.trim().split(/(?<=\?)\s*(?=\S)|\s+et\s+(?=(?:combien|quand|comment|où|à quelle heure|est-ce que)\b)/iu).filter(Boolean).slice(0, 2);
    let next = previous;
    const ref = p => statements(p, previous).rest;
    if (parts.length === 2 && !first.test(ref(parts[0])) && !second.test(ref(parts[0]))) {
      // In « Où et quand a lieu la balade ? », both requests share one object.
      const later = ref(parts[1]);
      if (first.test(later) !== second.test(later)) next = {...previous,option:first.test(later) ? 0 : 1};
    }
    const partsRead = parts.map(p => { const out = resolve(p, next, parts.length === 1 ? inferred : undefined); next = out.next; return out; });
    // Only the last advice uses every constraint given in the turn.
    const shown = partsRead.filter((x, i) => x.intent !== "fit" || !partsRead.slice(i + 1).some(y => y.intent === "fit"));
    const reply = [...new Set(shown.map(x => x.reply))].join(" ");
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
