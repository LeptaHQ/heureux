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

The Famille audit likewise retains only its two existing equivalent pairs
(truth with children; money for grades). Staying with parents for wellbeing
and the practicality of living with them after 25 remain distinct questions,
as do friendship for living well, friendship for happiness and relatives as
best friends. A suitable choir example and recognizable support mechanisms can
be reused without merging those answers. Adult autonomy is not measured solely
by moving out; family closeness, language outcomes and advice quality are not
guaranteed by age, origin or kinship.

The Education audit distinguishes learning from formal study, studies supporting
a career from grades contributing to life success, and school phone rules from
information reliability. Keep the existing learning-age, solidarity, salary,
child-development/television and university-access equivalents, including their
cross-theme publications. Adaptation capability is not a guaranteed outcome;
school priority is not exclusivity; university access is not unconditional
admission. Internet communication with a teacher is not learning entirely alone.
The Quebec-preparation response states three actual questions; its bilingual
plan uses declarative memory cues rather than changing those questions.

For Santé, retain separate answers for encouraging competition and obliging
sport, general screen time and video-game-specific risks, meat exclusion and
vegetarian choice, means to live and salary as a condition of happiness.
Stopping state-operated sales is not the same question as banning all sales:
the model explicitly distinguishes the two readings without inventing a
national retail system. A country-specific food opinion is an illustrative
viewpoint to personalize, not evidence of the learner's nationality or habits.
Health examples must not promise outcomes, diagnose people or suggest replacing
prescribed treatment with lifestyle changes. Relevant factual references include
[WHO healthy diets](https://www.who.int/news-room/fact-sheets/detail/healthy-diet),
[WHO tobacco](https://www.who.int/news-room/fact-sheets/detail/tobacco),
[WHO alcohol](https://www.who.int/news-room/fact-sheets/detail/alcohol) and
[NHS type 1 diabetes](https://www.nhs.uk/conditions/type-1-diabetes/).

For Technologie, preserve the difference between an inevitable effect and a
possible risk, no television and no TV news, and ease without a mobile versus
possibility without any telephone. Do not answer the last question by proposing
another telephone. Online friendships can be genuine; platforms and access
conditions matter, not only individual willpower. Online purchasing feasibility
is not the same as preferring an in-store trial; collection after online payment
is still an online purchase. Carpooling is not complete absence of car use.
The space-travel response distinguishes scientific missions, public priorities
and proportionate means: benefits from satellites do not justify every crewed
flight or tourism. Its microgravity example is supported by
[NASA's research explanation](https://www.nasa.gov/missions/station/iss-research/why-do-research-on-the-international-space-station/),
not a promised return on investment. Media preferences retain recognizable
source-checking language without treating Internet, radio and newspapers as
mutually exclusive categories or guaranteeing the quality of a platform.

For Environnement, distinguish zoo utility from closure, city-wide traffic
limitation from defined centre bans, and retail availability from agricultural
practices. Retain the reviewed car group's three Environment publications.
Reduction is not the same as sorting; medical needs and access constraints must
not become personal blame. The
[IUCN European-bison history](https://iucn.org/news/species/202012/european-bison-recovering-31-species-declared-extinct-iucn-red-list)
illustrates a conservation possibility, not a success guaranteed to every zoo.
Country-policy answers must not invent the learner's country: the model provides
an explicitly identified French example using verified
[Info-tri](https://www.ecologie.gouv.fr/info-tri) and
[biowaste-sorting information](https://www.service-public.gouv.fr/particuliers/actualites/A16963).
Adapt it to the actual country and current local facts; the existence of a rule
does not establish rollout or measured success. Organic-production examples use
the [EU framework](https://agriculture.ec.europa.eu/farming/organic-farming/organic-production-and-products_en)
explicitly, without extending it to every label, promising health outcomes or
equating organic with local. Economic activity is not impact-free; assess total
resource use as well as improvements per product.
Keep country-adaptation instructions in preparation metadata and Pistes, not
inside the spoken intervention.

For Économie, retain only the identical wellbeing and salary-priority pairs.
The personal Canadian-employment projection remains distinct from general
international mobility; enjoyment of life is not the same question as salary
priority or happiness. Do not invent a learner biography, Canadian-experience
requirement, current shortage, hiring timetable or universal bilingualism rule.
[Canadian credential guidance](https://www.canada.ca/en/employment-social-development/programs/foreign-credential-recognition.html)
distinguishes profession-specific regulation by province/territory from job
search and immigration status. Management readiness, willingness and capability
are different; judging a manager's work does not require sex stereotypes.
Retain the distinction between a constrained choice and no safe alternative,
without inventing a majority of forced migrations. Do not imply a universal
income threshold for enjoyment, rank manual and office work by effort, or
equate a sports club's budget with public-service funding.
[NIOSH planned-nap guidance](https://www.cdc.gov/niosh/work-hour-training-for-nurses/longhours/mod7/07.html)
supports an alertness strategy with wake-up time, not guaranteed safety,
compulsory naps or replacement of sufficient sleep. Free fares still require
funding and do not establish car substitution. Tourism benefits depend on
local participation and resource allocation; direct help and employment do
not replace social rights or make associations unnecessary. The broad car-free
opinion retains its own benefits/trade-offs, separate from the possibility group.

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
