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

Make the reasoning easy to remember: name who acts, what they do and what changes.
Prefer a direct verb to an abstract label, and a clear answer to stacked negatives.
Simplify the phrasing, not the argument: keep its explanation, concrete example
and necessary limits. A shorter text is not automatically easier to learn, and a
familiar, accurate expression need not be replaced merely for variety.

## Argument substance and comparative review

Compare the current model with the preserved original before revising it. Keep
or recover a stronger sound original reason when an edit has reduced it to a
minor convenience. For example, following a sustained line of thought develops
reflection and concentration; merely being able to pause a book is not a
substitute for that intellectual benefit. Reflection and sustained attention
belong to one mechanism, not two nominally different arguments.

Check the job of each paragraph: the claim states what supports the position;
the development explains why or how in a short, clear causal sequence; the
example demonstrates that mechanism in a recognizable situation; the consequence
states what follows. Do not repeat the same assertion in four forms. An example
needs a person or group, a specific action or event, and a relevant result.
Adding "Par exemple" to a general assertion does not make it an illustration.
An example that fits all three arguments unchanged is too generic.

The three paragraphs should make distinct contributions to the exact position,
rather than list three side effects of one benefit. Preserve necessary
qualifications without turning a clear argument into empty caution. Favor clear
referents, ordinary precise vocabulary and manageable spoken sentences; literate French need not be
abstract or difficult to decode. Reuse useful language across suitable questions
while removing redundant reasoning within the same intervention. Reread the
whole intervention after assembling edits, not only its individual fields.

Benefits do not establish necessity. When a consigne says "indispensable", a
balanced answer can develop two substantial benefits and a supported reason why
they are not a universal requirement. Do not force a weak third benefit merely
to keep all three paragraphs positive. A counterexample must actually lack the
relationship or resource under discussion: having few local friends does not
demonstrate living without local relationships. A small practical example can be
clear without being strong enough to carry a broad claim about wellbeing.

## Reuse across different questions

Teach the same sound mechanism in the same words when it fits another consigne.
Reuse a whole argument where its claim, development, example and consequence all
apply; otherwise reuse only the compatible passage or concrete case. Do not invent
synonym versions just for variety. Keep each question's position, actors, scope
and limits, and retain a specific illustration when copying would weaken it.
For example, helping someone through a difficult period is not the same as
practical help, and Canada-specific access to a profession is not a universal rule.

The reviewed reuse includes personal letters, friendship, household cooperation,
asking an adult for help, conversations at a distance, public assistance,
regular visits, repairs, conservation, urban traffic, salary trade-offs and
checking a publication's origin. Some are identical arguments; others share only
an example, a development or a sentence of nuance. Adapt spoken connectors when
the same argument occupies a different position. Align both bilingual memory cues
when an illustration changes, and keep distinct source groups distinct.
`test_tache_three_reuse.py` pins these deliberate correspondences and boundaries;
literal equality is not a quality quota or a substitute for reading the prompts.

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

Reviewed public EO3 defaults use stable `response:{prompt.content_key}:model`
annotation keys. An editorial edit replaces the current authored text, not its
annotation identity. Restore selections only by an exact quote and unambiguous
saved context or a verified unchanged-field anchor; never guess old offsets onto replacement text. Removed or
ambiguous selections remain stored in Notes, including their IDs and note bodies.
The frozen, identifier-only transition bridge covers old public keys through
`11531d8`; do not extend it or author response histories or snapshots for future
public edits. Unreviewed, private, EO2 and EE content are not rewritten by the
reviewed catalogue. Imports validate it before writing; workers must restart
after file-backed catalogue changes.

### Annotation field identities and publication staging

The detail and practice-back templates mark each reviewed model field without
changing its text or whitespace. Private annotation `response_anchor` metadata
contains only the field identifier, SHA-256 checksum and relative UTF-16 start/end.
When the entire field is unchanged, its checksum and exact selected text prove
placement even if both neighbours were rewritten. If the field changed, the
conservative exact-quote/context matcher stays confined to that field. Missing,
retired or ambiguous fields leave the selection stored, not guessed elsewhere.
Cross-field selections and unscoped legacy rows retain the conservative matcher.

Argument identities default to `[1, 2, 3]` for existing models. An optional
`argument_ids` list assigns three distinct positive integers independent of spoken
order. Keep an existing argument's ID through a targeted revision or intentional
reordering; assign a fresh, never-recycled ID to a genuinely new reason. Retiring
an argument does not authorize its quote to move into another argument. These IDs
are presentation metadata, outside response bodies, legacy digests and source
signatures. Do not infer continuity automatically from matching examples.

For the initial rollout, publish the capture runtime and compatible anchor schema
**without editorial changes**, and verify that this version is serving requests.
The column needs a persistent database default (`{}`), not just Python's `dict`
default, so preceding workers can still insert notes/highlights while migrations
run. Migration 0059 repairs already-applied 0058 databases; the replacement
0058/0059 migration adds the column with that default in one operation on fresh
upgrades. Keep both original migrations for partially upgraded databases.
Then run
`python manage.py backfill_response_anchors` against the same still-published
catalogue after the old workers have drained. A separate preservation-only build
can run that command through `deploy_database`; no model text may change in it.
This second pass closes the window where the original workers could save an
unscoped selection after the first build's backfill. The command is idempotent,
locks only each annotation row, and updates only verified anchor metadata, not
note bodies, offsets, timestamps, completion, cards or source identities.
Unverifiable older rows remain unscoped and are reported explicitly.

Only after capture and the post-cutover backfill are confirmed may an editorial
release replace the surrounding fields. The actual-transition gate must model
that sequence: create existing rows on the published text, capture/backfill there,
switch catalogues, and retain all original inline-restoration and private-data
assertions. Also exercise new selections from already-open pre-capture pages,
stale unscoped saves after the editorial cutover, reused quotes under new argument
IDs, and both detail/practice surfaces. Never replace this deployment sequence
with response snapshots or an extension of the frozen digest bridge.

## Culture learning consistency

The Culture audit covers 35 Culture consignes through 31 models, with four
additional equivalent publications in other themes. Retain the distinctions
between adapting habits, achieving a goal, integration, the overall experience
of living abroad and the motivations for leaving. Likewise, book usefulness is
not reading necessity, and cultural transmission to children is not the same
question as forgetting one's own practices.

Reuse sound claims and familiar expressions where the mechanism is genuinely the
same. The adult-observer and older-observer models share their three argument
cues and the food-collection illustration, while keeping their actors and
consignes distinct. Familiar language at home, practical preparation, shared
meals and community participation can recur in other answers when they support
the actual question; they must not become interchangeable stock paragraphs.

A development explains why the claim holds. Its example should identify a
recognizable situation, an action and a relevant outcome: a housing-support
form, a colleague explaining when to raise a problem or a visit arranged in
advance is clearer than an unnamed procedure or an unexplained difference in organization.
Keep possible outcomes conditional, distinguish a whole life from selected
television images, and answer words such as "necessary" and "always" directly.
Align both languages of the corresponding Piste after revising a support.

When assessing whether friends are necessary for happiness, do not support a
negative answer only with three benefits of friendship. Develop other affectionate
relationships and personal sources of satisfaction, while distinguishing chosen
solitude from painful isolation. Having no friends locally does not demonstrate
having no friends at all; keep that distinction in the example and both cues.
These reasons are not interchangeable with the
friendship benefits in the separate Famille question about living well. Retain the
existing support argument's identity; the replacement reasons use fresh IDs.
Likewise, relations with local residents do not mean friends born in the host
country. In the necessity question, distinguish the benefits of local support
and understanding from a universal obligation to form those ties. Someone with
few local friends is not a counterexample; someone who has not formed personal
local ties but enjoys a satisfying routine and close contact at a distance can
illustrate the limit. Retain the two revised benefits' identities and give the
new counterargument a fresh ID.

In the country-knowledge question, arrival logistics and budgeting both belong
to material preparation; different examples alone do not make them independent
reasons. Distinguish financial feasibility, legal agency and understanding other
people's expectations. The tenant example checks the applicable local rules
instead of asserting a universal entry rule or promising that a dispute will be
resolved. Keep the retained budget and interpersonal reasons' identities through
reordering, and give the new rights argument a fresh ID.

## Famille learning consistency

The 17 Famille consignes use 14 Famille models plus the shared Culture model
about friendship and happiness. Keep the truth-with-children and money-for-grades
pairs together, but distinguish living well, happiness and relatives as best
friends. Likewise, feeling comfortable at one's parents' home is a legitimate
reason in its own right, not only when it finances a plan to move out. The
after-25 prompt asks about practicality, not a mandatory age of independence.

Reuse the shared household-help argument across those two cohabitation questions,
while keeping their positions and other mechanisms distinct. Reuse suitable
friendship claims and the trial-choir example without replacing practical help
with emotional support in every response. Concrete examples should explain the
actual comparison or action: two Internet subscriptions instead of one, a
housing-cost comparison, an identified calculation error, or seeking help with
a damaged library book. Trust between relatives must be demonstrated by keeping
a confidence and respecting a differing choice, not assumed from kinship.

## Prompt explanations

EO3 subject pages and practice fronts use a collapsed English **Comprendre la
consigne** note, styled like the EO2 explanation. The source-pinned
`tache_3/prompt_notes.json` covers all 131 groups and 167 publications. Explain
the exact issue, significant qualifiers, useful distinctions and plausible
discussion angles. Do not translate a ready-made answer or force its position.
Check every equivalent source, including opposite question polarities and
cross-theme publications. Country and personal prompts need explicit adaptation
guidance rather than an invented nationality, biography or rule.

Notes are immutable shared editorial content, independent of private responses.
They do not reuse EO3's spoken nuance for storage. Missing groups or changed
consignes fail validation; unrelated tasks and ad-hoc groups do not receive a
generic substitute. Import validates before writes, and workers must restart
after changes. Notes sit outside detail annotation roots and carry annotation
exclusion on practice fronts. Only the French prompt is a read-aloud target.
Native disclosure works with keyboard controls and without JavaScript.

The bilingual plans in `tache_3/hints.json` provide subject-specific **Pistes**
alongside the separate prompt explanation. Each model plan cues its introduction
and position, three arguments and examples, nuance and conclusion. Keep it aligned
with the reviewed model and every equivalent consigne; never generate it from a
private answer. Both languages use EO2's shared hint-text presentation.

Audit both languages against the complete model, not just its headings. Preserve
who acts, the condition that makes an example work, and distinctions such as
possible versus necessary. Do not narrow *proches* to relatives, confuse a
departure by itself with travelling alone, or turn a possible result into a
guarantee. In prompt explanations, mark illustrative actions as optional when
the consigne asks only for a position and reasons; do not add examination tasks.

For the user's subjunctive-learning pass, retain a natural existing clause before
adding anything. Check the complete spoken response, including negative opinions,
feelings, fears and purposes, not only common `il faut que` patterns. When needed,
rephrase one existing requirement or purpose without changing its meaning,
certainty or actors. A learning target is not an official examination quota;
avoid stock filler or replacing a possibility with an obligation for grammar.

Pistes replace the visible generic **Expressions liées** block on bundled EO3
detail pages, outside both existing annotation roots. The old expression block
remains hidden, with its exact text unchanged, so historical sidebar highlights
keep their offsets. Underlying expressions, cards and lot progress are not deleted
or rewritten. Ad-hoc responses without an editorial plan receive no invented plan.
Practice backs show the same Pistes after the response, excluded from annotation
offsets and read-aloud text; practice fronts keep the prompt explanation without
revealing the plan. Do not rewrite response models, source identities, vocabulary
or saved learner data when changing guidance presentation.
