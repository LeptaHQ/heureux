# Expression orale, tâche 3: editorial standard

This standard concerns oral viewpoints only, not oral task 2 or written task 3.
Read every consigne in a semantic group before changing its shared default.
Similar subject matter is not sufficient evidence of equivalence.

## Speaking, not an essay

France Éducation international describes task 3 as a spontaneous, continuous,
convincing response to the examiner's question, **without preparation, lasting
4 minutes 30**. Its assessment considers linguistic control, fluency,
structure/coherence, thematic development and appropriateness to the situation:

- [Official task description](https://www.france-education-international.fr/test/tcf-canada?langue=fr)
- [Official assessment criteria](https://www.france-education-international.fr/article/evaluation-epreuves-tcf?langue=fr)

The six-part teaching structure is an introduction, three developed arguments,
a meaningful nuance and a conclusion. Three arguments and an example for each
are editorial choices, **not official quotas**. There is no official oral word
count. The reviewed models use a 300–430 whitespace-word rehearsal envelope:
at 100–110 words per minute this is approximately 2:45–4:18 before individual
variation. Rehearse with pauses; do not rush to reproduce a text or assume a
particular speaking rate. Adapt to the actual question and examiner's timing.
The language target is strong NCLC 7/8 preparation, not a promised score.

The introduction answers the exact issue and orients the listener without
announcing the whole answer twice. Each argument has a distinct claim, an
explanation of how or why it works, a plausible situated illustration and a
proportionate consequence. Examples must do more than repeat the claim.
The nuance addresses a real condition, limitation or trade-off; the conclusion
synthesizes without a new argument.

Prefer precise ordinary language, manageable sentences and reusable constructions.
Retain sound wording. Reuse a mechanism only where it answers the prompt:
practical support, emotional continuity, learning through repeated exchanges,
access to opportunities and participation are not interchangeable explanations.
Avoid universal generational judgments, essentialised national identities,
invented studies, unsupported majority claims and implied legal guarantees.
Illustrative situations are possibilities, not reports of the learner's life.

## Reviewed defaults and preserved sources

`study/content/tache_3/responses/<theme>.json` holds reviewed models using the
existing response fields: `position_claire` is the spoken introduction;
each argument has `idea`, `developpement`, `exemple` and `consequence`;
`nuance` and `conclusion` finish the intervention. `position` and `reformulation`
remain concise preparation metadata, not additional spoken paragraphs.

`study/tache_three_models.py` validates complete coverage of each authored theme,
three supported arguments, distinct claims/mechanisms/examples, and the rehearsal
envelope. Every source consigne is pinned by its exact text's SHA-256 signature,
including cross-theme equivalents. A changed consigne or membership requires
re-auditing the model rather than silently accepting a new interpretation.
Validation rejects malformed content; it does not substitute a generic answer.
Automated structural checks do not replace editorial judgment.

Semantic groups and original publication themes remain separate from reusable
argument families. In particular, retain distinct responses for book utility
versus reading necessity, adult versus elderly observers, travel versus language,
and adapting versus integrating versus evaluating life abroad. The audited
Culture partition retains its existing memberships: four repeated Culture pairs
and four cross-theme equivalent publications. Related prompts share suitable
language and mechanisms, not an answer to a different question.

Published Markdown in `study/content/responses/` remains the exact historical
model corpus. Its 130 exact-body records support 167 publications and 131
semantic identities. Do not rewrite or deduplicate those records as an incidental
part of changing a reviewed default. They retain the original model bodies,
source identities and verbatim vocabulary evidence. Existing subject vocabulary,
phrase IDs, theme vocabulary and their examples remain valid historical language
exercises, not purported quotations from a newly rewritten response.
The exact preceding detail/front/back templates are archived in
`tache_3/layout_history/original.json`, with their source commit. Together with
the immutable publication models, they reproduce the prior visible layouts;
regressions compare the original and current annotation-root text byte for byte
when the new reviewed presentation is not selected.

The current public default is selected through `effective_response`, consistently
for detail, practice and the personal editor. Reviewed public practice backs show
the introduction and all three supports, not just claim headings. Personal
responses remain private, take precedence and retain their existing presentation;
an import does not replace them. Reset deactivates a personal version without
deleting its content, notes or progress.

New public wording receives a content-derived annotation key. Reviewed layouts
must not advertise the original unversioned source key as a fallback: old offsets
must never be guessed onto rewritten text. Original annotation rows and bodies
remain available through Notes, while exact original source models remain stored
on each publication. Unreviewed, private, EO2 and EE content are not rewritten by
the reviewed catalogue. Imports validate it before writing; workers must restart
after file-backed catalogue changes.

Keep the bilingual plan in `tache_3/hints.json` consistent with each reviewed
default. Its examples should cue the same mechanism and situation, not revive a
discarded generalization. Plans remain outside annotation roots and do not
summarize private responses.
