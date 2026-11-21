/* Practice indicators for this sample, not the scoring algorithm for the TCF. */
(function (root, factory) {
  const review = factory();
  if (root) root.HeureuxEO1Review = review;
  if (typeof module === "object" && module.exports) module.exports = review;
})(typeof window === "object" ? window : null, function () {
  "use strict";
  const rules = [
    [/\bje suis ([2-9]|[1-9]\d) ans(?=\s*[,!.?…]|$)/iu, "j’ai $1 ans",
      "Pour donner son âge en français, on emploie avoir, et non être."],
    [/\bje suis besoin de\b/iu, "j’ai besoin de", "L’expression est « avoir besoin de quelque chose »."],
    [/\bje suis d['’]accord à vous\b/iu, "je suis d’accord avec vous", "On est d’accord avec une personne."],
    [/\bje va\b/iu, "je vais", "Au présent, aller se conjugue « je vais » ; « va » s’emploie avec il ou elle."],
    [/\bje peux de (faire|parler|partir|venir|travailler)\b/iu, "je peux $1", "Après pouvoir, l’infinitif se construit sans « de »."],
    [/\bje fais de le (sport|ski|vélo|yoga)(?!\p{L})/iu, "je fais du $1", "Devant ce nom masculin, de et le se contractent en « du »."],
    [/(?<!\p{L})à le (travail|cinéma|restaurant|parc|marché|bureau)(?!\p{L})/iu, "au $1", "Devant ce nom masculin, à et le se contractent en « au »."],
    [/\bje suis allé(e?) à Canada\b/iu, "je suis allé$1 au Canada", "Pour la destination, on dit « au Canada »."],
    [/\b(?:j['’]habite|je vis) à Canada\b/iu, m => m.replace(/à Canada$/iu, "au Canada"),
      "Pour situer son lieu de vie, on dit « au Canada »."],
    [/\bje veux (?:de |d['’])(apprendre|travailler|parler|faire|partir)\b/iu, "je veux $1", "Vouloir est directement suivi de l’infinitif."],
    [/\bje suis en train (apprendre|travailler|parler|faire)\b/iu,
      (m, verb) => `je suis en train ${verb === "apprendre" ? "d’" : "de "}${verb}`,
      "Pour décrire une action en cours, on dit « être en train de » suivi de l’infinitif."],
    [/\ble (guitare|flûte|clarinette|séance|leçon)(?![\p{L}-])/iu, "la $1",
      "Ce nom est féminin : on emploie « la »."],
    [/(?:^|[.!?…]\s+|\b(?:si|quand|lorsque|que) )je m['’]inscrire(?!\p{L})/iu, m => m.replace(/inscrire$/iu, "inscris"),
      "Avec « je », on dit « je m’inscris ». L’infinitif convient après un autre verbe : « je voudrais m’inscrire »."],
    [/(?:^|[.!?…]\s+)(?:(?:oui|non|moi),\s*)?(?:les|ces) (?:guitares|activités|séances|sorties|ateliers|horaires|cours) m['’]intéresse(?!\p{L})/iu,
      m => m + "nt", "À l’écrit, le verbe s’accorde avec le sujet pluriel : « m’intéressent ». Les deux formes se prononcent pareil."],
  ];
  const fold = s => s.normalize("NFD").replace(/\p{M}/gu, "").replace(/[’‘]/g, "'").toLowerCase();
  const words = s => fold(s).match(/[a-zœ]+/g) || [];
  const key = s => words(s).join(" ");
  function* phraseEdits(answer) {
    for (const [pattern, replacement, why] of rules) {
      for (const found of answer.matchAll(new RegExp(pattern.source, pattern.flags + "g"))) {
        const before = found[0];
        let after = before.replace(pattern, replacement);
        if (/^\p{Lu}/u.test(before)) after = after[0].toLocaleUpperCase("fr") + after.slice(1);
        if (after !== before) yield {start: found.index, before, after, why};
      }
    }
  }
  function corrections(rows) {
    const notes = [], seen = new Set();
    for (const {answer, index} of rows) {
      for (const {before, after, why} of phraseEdits(answer)) {
        if (seen.has(why)) continue;
        notes.push({turn: index + 1, before, after, why});
        seen.add(why);
        if (notes.length === 4) return notes;
      }
    }
    return notes;
  }
  const personalClause = /\b(?:(?:je |j')(?:(?:ne |me |m'|l'|la |le |les |leur |lui |y |en |n'))*(?:ai|vais|vois|vis|lis|fais|sais|suis|peux|veux|dois|[a-zœ]{2,}(?:e|is|ds|ns|ais|rai))|(?:nous |on )(?:(?:nous |se |s'|y |en |ne |n'))*(?:sommes|est|a|va|vit|fait|[a-zœ]{2,}(?:ons|e|ait|it)))\b/;
  const detail = /\b(?:chaque|tous les|toutes les|le week.end|le samedi|le dimanche|avec (?:ma|mon|mes|des|un)|depuis|pendant|souvent|le soir|le matin|pres de|a cote|en famille|par semaine|dans (?:mon|ma|une?|le|la)|a la|au|en train)\b/;
  const reason = /\b(?:parce qu[e']|car |puisqu[e']|c'est pourquoi |c'est pour (?:ca|cela) que |par exemple[, ]+)/;
  const otherClause = /\b(?:c'est|(?:il|elle|ils|elles|cela|ca) (?:[a-zœ]+ |m'|l')?(?:[a-zœ]{2,}(?:e|ent|it|ait)|est|a|ont|sont|font|fait|permet|peut)|(?:le|la|les|mon|ma|mes) [a-zœ]+ (?:[mts]'|(?:me |se |nous ))?(?:est|sont|a|ont|fait|permet|vit|habite|travaille|plait|aide))\b/;
  const narrative = /\b(?:(?:j'ai|nous avons|on a) (?:commence|termine|travaille|rencontre|demande|change|visite|essaye|decide|fait|pris|choisi|appris|decouvert|vu|lu)|je suis (?:arrivee?|allee?|partie?|devenue?|sortie?)|quand j'etais|avant je|je faisais|j'allais|(?:j'aimerais|je voudrais|j'envisage de|je compte|je vais) (?:[a-zœ]{2,}(?:er|ir|re)))\b/;
  function developed(s) {
    const m = reason.exec(s);
    if (!m) return false;
    const lead = s.slice(0, m.index), tail = s.slice(m.index + m[0].length).split(/[.!?;]/)[0];
    return personalClause.test(lead) && words(lead).length >= 3 && words(tail).length >= 4 &&
      (personalClause.test(tail) || otherClause.test(tail));
  }
  function assess(turns) {
    const rows = turns.map((t, index) => ({...t, index, answer:t.answer.trim()})).filter(t => t.answer);
    const result = {band:"", evidence:[], typed:rows.some(t => t.mode !== "voice"), corrections:corrections(rows),
      reason:"Il faut plusieurs réponses personnelles différentes pour situer cet échange. Un manque de données n’est pas un niveau débutant."};
    const seen = new Set();
    const usable = rows.filter(t => {
      const k = key(t.answer), tokens = words(t.answer);
      if (seen.has(k) || !k || key(t.question).includes(k) || tokens.length < 3 ||
          new Set(tokens).size < 3 ||
          /\b(?:repeter|repetez|reformuler|pas compris|pas en parler|autre question)\b/.test(k)) return false;
      seen.add(k);
      return true;
    }).map(t => ({...t, sample:fold(t.answer)}));
    const statements = usable.filter(t => personalClause.test(t.sample));
    if (statements.length < 2 || new Set(usable.flatMap(t => words(t.sample))).size < 12) {
      if (usable.length >= 3) result.reason = "L’analyse automatique ne reconnaît pas assez d’indices distincts pour situer cet extrait. Cela ne préjuge pas de votre niveau.";
      return result;
    }
    const concrete = statements.filter(t => detail.test(t.sample));
    const explained = statements.filter(t => developed(t.sample));
    const story = statements.filter(t => narrative.test(t.sample) && words(t.sample).length >= 8 &&
      (detail.test(t.sample) || /\b(?:hier|quand|pour|ensuite|dernier|derniere|prochain|prochaine)\b/.test(t.sample)));
    function cite(t, what) {
      result.evidence.push({turn:t.index + 1, quote:t.answer, what});
    }
    if (explained.length && story.some(t => t !== explained[0]) && usable.length >= 3) {
      result.band = "Indices de B1"; result.reason = "Vous reliez des idées sur un sujet familier et développez une expérience ou un projet. Ce sont des indices compatibles avec B1, pas un plafond : cet exercice ne départage pas les niveaux supérieurs.";
      cite(explained[0], "Explication ou exemple"); cite(story.find(t => t !== explained[0]), "Expérience ou projet");
    } else if (concrete.length && usable.length >= 2) {
      result.band = "Indices d’A2"; result.reason = "Vous échangez des informations personnelles et donnez au moins un détail de contexte. Cela illustre un descripteur A2 sans exclure un niveau plus avancé.";
      cite(concrete[0], "Détail sur le quotidien");
      if (explained.length && explained[0] !== concrete[0]) cite(explained[0], "Idée développée");
    } else {
      result.band = "Indices d’A1–A2"; result.reason = "On distingue des phrases personnelles simples. Ce repère décrit ce qui apparaît ici, pas la limite de votre niveau.";
      cite(statements[0], "Information personnelle"); cite(statements[1], "Autre information");
    }
    return result;
  }
  return {assess, phraseEdits};
});
