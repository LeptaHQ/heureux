/* Text observations only: no topic model, answer key or assessment of spoken delivery.
   Load tache_1/transcript-review.js first to share its limited grammar corrections. */
(function (root, factory) {
  const grammar = typeof module === "object" && module.exports
    ? require("../tache_1/transcript-review") : root?.HeureuxEO1Review;
  const feedback = factory(grammar?.phraseEdits);
  if (root) root.HeureuxEO2Feedback = feedback;
  if (typeof module === "object" && module.exports) module.exports = feedback;
})(typeof window === "object" ? window : null, function (phraseEdits) {
  "use strict";
  const fold = text => text.normalize("NFD").replace(/\p{M}/gu, "")
    .replace(/[’‘]/g, "'").toLowerCase();
  const key = text => fold(text).replace(/[^a-zœ0-9]+/g, " ").trim();
  const hasPhrase = (text, phrase) => (` ${key(text)} `).includes(` ${phrase} `);
  const dangling = /\b(?:a|au|aux|avec|dans|de|du|des|en|et|par|pour|sans|que|qu|si|le|la|les|un|une|ce|cette|ces|votre|vos|mon|ma|mes|ton|ta|tes)$/;
  const stop = new Set(("a au aux avec ce cet cette ces d de des du en et la le les l pour un une " +
    "votre vos ton ta tes detail details information informations chose choses point points " +
    "sujet question questions est sont bien merci oui tres vraiment quelque quelques " +
    "important importante importants importantes interessant interessante interessants interessantes " +
    "utile utiles cela ca ceci autre autres fait faire peu avoir etre savoir " +
    "je tu il elle ils elles on nous vous me te se").split(" "));
  const direct = /^(?:est ce que|qu est ce que|quel(?:le)?s?|ou|quand|combien|comment|pourquoi|que|(?:a|de|pour|avec) quel(?:le)?s?|pouvez vous|pourriez vous|peux tu|pourrais tu|puis je|faut il|y a t il)\b/;
  const verb = /\b(?:est|sont|a|ont|as|avez|faut|peut|peuvent|dois|doit|doivent|puis|peux|pouvez|pourrais|pourriez|reste|restent|coute|coutent|dure|durent|commence|commencent|finit|finissent|[a-z]+ez)\b/;
  const repetition = /^(?:(?:pouvez|pourriez)[ -]vous|(?:peux|pourrais)[ -]tu|vous (?:pouvez|pourriez)|tu (?:peux|pourrais)) (?:me |nous )?(?:le |la )?(?:repeter|reformuler)(?: (?:la question|la reponse|votre reponse|ta reponse|cela|ca))?(?: (?:plus lentement|s'il vous plait|s'il te plait))?\s*[.!?]?$/;
  const sentences = text => (text.match(/[^.!?]+[.!?]?/g) || []).map(sentence =>
    fold(sentence.trim()).replace(/^(?:(?:bonjour|bonsoir|merci|pardon|d'accord|alors|et|donc)[,\s]+)+/, ""));

  function complete(row) {
    return !row.interrupted && !/(?:[,…:;—-]|\.\.)\s*$/.test(row.text.trim()) &&
      !dangling.test(key(row.text));
  }
  function question(text) {
    return sentences(text).some(sentence => {
      const sample = sentence.replace(/^(?:pour|concernant|a propos de) [^,]+,\s*/, "");
      const normalized = key(sample), tokens = normalized.split(" ");
      if (tokens.length < 3 || new Set(tokens).size < 3 || dangling.test(normalized) ||
          /["«»“”]/.test(sample)) return false;
      return /\?$/.test(sample) || (direct.test(normalized) && verb.test(normalized) &&
        !sample.includes(",") && !/^(?:quand|comment|ou|pourquoi) (?:je|j|il|elle|ils|elles|on|nous|tu|vous)\b/.test(normalized));
    });
  }
  function reference(text) {
    const sample = fold(text.trim());
    const found = /^(?:et )?(?:pour|concernant|a propos de) ([^,;.!?]+)[,;:]\s*(.+)$/.exec(sample) ||
      /^(?:vous (?:avez (?:mentionne|propose)|parlez de)|tu (?:as (?:mentionne|propose)|parles de)) ([^.!?]+)[.!:]\s*(.+)$/.exec(sample) ||
      /^(?:vous avez|tu as) parle (?:de |d')([^.!?]+)[.!:]\s*(.+)$/.exec(sample);
    if (!found || !question(found[2])) return "";
    const tokens = key(found[1]).split(" ");
    while (stop.has(tokens[0])) tokens.shift();
    const content = tokens.filter(token => !stop.has(token));
    return tokens.length <= 8 && new Set(content).size >= 2 ? tokens.join(" ") : "";
  }
  function reusedDetail(text, source) {
    // Compound noun phrases can identify a detail without an explicit “pour…” lead-in.
    const phrases = key(text).matchAll(/\b(?:le|la|les|l|un|une|des|ce|cet|cette|ces) ([a-zœ]+ (?:de|du|des|d|a|au|aux|en) (?:(?:le|la|les|l) )?[a-zœ]+)\b/g);
    for (const [, phrase] of phrases) {
      const content = phrase.split(" ").filter(token => !stop.has(token));
      if (new Set(content).size >= 2 && hasPhrase(source, phrase)) return phrase;
    }
    return "";
  }
  const pieces = text => text.match(/[\p{L}\p{M}\p{N}]+(?:['’-][\p{L}\p{M}\p{N}]+)*|\s+|[^\s]/gu) || [];
  function* turnEdits(text) {
    if (phraseEdits) yield* phraseEdits(text);
    // Normalize only same-width apostrophes for matching; offsets and examples use the original.
    const sample = text.replace(/’/g, "'");
    for (const match of sample.matchAll(/(?<![\p{L}\p{M}'-])(j'ai|c'est|je voudrais|est-ce que|merci pour)(?:[ \t]+\1)+(?![\p{L}\p{M}'-])/giu)) {
      const start = match.index, before = text.slice(start, start + match[0].length);
      yield {start, before, after: before.slice(0, match[1].length),
        why: "Reprise ou doublon de transcription possible. À la relecture, une seule occurrence suffit ; ce n’est pas une faute de grammaire."};
    }
    for (const match of sample.matchAll(/(?<![\p{L}\p{M}'-])j'ai( donc)? voudrais(?![\p{L}\p{M}'-])/giu)) {
      const start = match.index, before = text.slice(start, start + match[0].length);
      yield {start, before, after: (before.startsWith("J") ? "Je" : "je") + " voudrais" + (match[1] ? " donc" : ""),
        why: "Si ces mots ont bien été transcrits, « voudrais » est déjà conjugué : dites « je voudrais », sans « j’ai »."};
    }
  }
  function changedWords(turnIndex, match) {
    const left = pieces(match.before), right = pieces(match.after);
    let first = 0, l = left.length, r = right.length, start = match.start;
    while (first < l && first < r && left[first] === right[first]) start += left[first++].length;
    while (l > first && r > first && left[l - 1] === right[r - 1]) { l--; r--; }
    const before = left.slice(first, l).join("");
    return {turnIndex, start, end: start + before.length, before, after: right.slice(first, r).join(""), why: match.why};
  }
  function assess(rows) {
    const evidence = [], labels = new Set(), learner = [], earlier = [];
    const annotations = [], corrections = [], seenRules = new Set();
    let questions = 0, responses = 0, followUps = 0, linked = false, reformulation = false;
    const cite = (label, row, context) => {
      if (labels.has(label)) return;
      labels.add(label);
      evidence.push({label, quote: row.text, ...(context ? {context} : {})});
    };
    const valid = row => row && typeof row.text === "string" && row.text.trim();
    rows = Array.isArray(rows) ? rows : [];
    rows.forEach((row, index) => {
      if (!valid(row) || row.speaker !== "user") return;
      learner.push(row);
      const previous = rows[index - 1];
      const source = valid(previous) && previous.speaker === "model" && complete(previous)
        ? previous : null;
      if (complete(row) && !(source && key(source.text) === key(row.text))) {
        // A self-repair or a quoted example is not an error to attribute to the speaker.
        if (!/["«»“”]/.test(row.text) &&
            !/\b(?:pardon|je (?:voulais|veux) dire|je me corrige|plutot)\b/.test(fold(row.text))) {
          const edits = Array.from(turnEdits(row.text), match => ({match, change: changedWords(index, match)}))
            .sort((a, b) => a.change.start - b.change.start);
          let previousEnd = -1;
          for (const {match, change} of edits) {
            if (change.start < previousEnd) continue;
            annotations.push(change);
            previousEnd = change.end;
            if (corrections.length < 3 && !seenRules.has(match.why)) {
              const {before, after, why} = match;
              corrections.push({before, after, why});
              seenRules.add(why);
            }
          }
        }
        const asks = question(row.text);
        const repeats = sentences(row.text).some(sentence => repetition.test(sentence) &&
          !/^(?:vous|tu) .*\.$/.test(sentence));
        if (repeats) {
          reformulation = true;
          cite("Demande de reformulation", row);
        } else if (asks) {
          questions++;
          if (valid(rows[index + 1]) && rows[index + 1].speaker === "model" &&
              complete(rows[index + 1])) responses++;
          const anchor = reference(row.text) || (source ? reusedDetail(row.text, source.text) : "");
          // A connector or shared keyword alone does not establish a relance.
          if (source && !source.text.includes("?") && anchor && hasPhrase(source.text, anchor) &&
              !earlier.some(text => hasPhrase(text, anchor))) {
            linked = true;
            followUps++;
            cite("Détail de la réponse repris", row, source.text);
          } else if (sentences(row.text).some(sentence =>
            /^(?:pourriez[- ]vous|pourrais[- ]tu)\s+(?:me |m'|nous )?(?:dire|indiquer|preciser|expliquer|conseiller|renseigner)\b/.test(sentence))) {
            cite("Demande polie au conditionnel", row);
          }
        }
      }
      earlier.push(row.text);
    });
    let next;
    if (!learner.length) {
      next = "Aucune parole personnelle à examiner. Commencez par poser une question.";
    } else if (!learner.some(complete)) {
      next = "Les paroles transcrites semblent incomplètes. Allez au bout de votre question.";
    } else if (!questions && !reformulation) {
      next = "Je ne repère pas de demande d’information assez nette dans cet extrait. Précisez ce que vous souhaitez savoir.";
    } else if (!questions) {
      next = "Après la reformulation, posez une question sur le détail que vous souhaitez éclaircir.";
    } else if (linked) {
      next = "Vous reprenez un détail de la réponse. Vérifiez que la précision demandée n’a pas déjà été donnée.";
    } else if (!responses) {
      next = "Cet extrait ne montre pas encore de réponse à votre question. Poursuivez l’échange avant d’en tirer davantage d’observations.";
    } else {
      next = "Pour poursuivre, vérifiez s’il reste un point à éclaircir dans la dernière réponse.";
    }
    return {evidence, corrections, annotations, next, tally: {turns: learner.length, questions, followUps}};
  }
  return {assess, changedWords};
});
