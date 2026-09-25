# Heureux

Heureux is a Django study application. It combines guided French lessons,
model responses, reusable vocabulary, comprehension practice, spaced
repetition, notes, highlights, and explicit completion tracking.

## Local development

Heureux uses Python 3.12.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py import_content --if-changed
python manage.py runserver
```

Run the regular test suite with `python manage.py test`. Browser tests are kept
out of Django's default discovery because they require Playwright:

```bash
python -m playwright install chromium
python manage.py test study.tests.browser_tests
```

## Notes and highlights

Notes folders show 50 records per page and load only the active tab. Search and
tab totals cover all matching records; the study total is calculated before the
status filter. Flashcards use the full filtered selection, while the study queue
keeps all marked records in the folder. Page navigation works without JavaScript.
The shared `study/partials/pagination.html` pager accepts a Django `page_obj`,
`page_links` (`number` and `url`), previous/next URLs, and an optional accessible label.

Vocabulary theme, category and comprehension-test pages share a compact,
collapsible guided-lots component with completed/active counts. The vocabulary
stays full-width, and the lot links work with keyboard controls or without JavaScript.

## EE task 3 formulations

`/expression/ecrite/tache-3/formulations/` is the EE3 writing toolkit. One catalogue
organizes formulations by writing function (titles, neutral synthesis, affirmation,
opposition, concession, conditions, arguments, examples, consequences and
conclusions) and by the eleven subject themes. Start with the essentials, then
learn thematic arguments rather than isolated words.

The catalogue root uses two simple progress tables: one for the essential writing
functions and one for thematic arguments. Every subdivision opens a learning page
with a sticky topic index, its own learned count, search and status filter; global
search has a separate page. The synthesis subdivision includes a compact reference
for reporting verbs such as `mettre en avant`, `indiquer` and `mettre en garde
contre`. Every thematic subdivision begins with an eight-item useful-vocabulary
reference, including its English meaning and a productive French collocation. Each
entry then pairs a reusable French frame with its English meaning, usage and grammar
guidance, an example from a reference response, and an exercise for adapting it to
a different situation. Copy and opt-in recall practice are separate actions.
Learned status is the learner's own assessment of being able to reproduce and adapt
the formulation, not an exam score.

The file-backed curriculum lives in `study/content/ee/tache_3/formulations.json`;
`study/ee_formulations.py` validates its structure, complete effective-source
coverage and verbatim example provenance. Frames and teaching guidance are
editorial adaptations, not quotations. Examples refer to the bundled reference
corpus, not live summaries of edited or personal answers. Source revisions must
keep the evidence current, and workers must restart after catalogue changes.

New completion keys use `formulation:ee3:v1:<slug>`. Materially changing a
learning target requires a new slug. Old EE3 memory URLs redirect to Formulations;
there is no legacy memory interface or special note/highlight compatibility layer.

EE3 vocabulary is removed from active navigation and learning queues. This is a
read-time exclusion with no data-deletion migration. Phrases still owned by another
active task remain available there. Old EE3 vocabulary collection links lead to
Formulations; other tasks retain their existing vocabulary features.

## Subject pistes and oral equivalence

EO task 2 subject pages show bilingual **Pistes** (hints): short French information targets
with English meanings, not ready-made questions. The editorial lists in
`study/content/tache_2/subjects/hints.json` cover every semantic group, including
singletons; every equivalent publication shares the same immutable list, whether
the current response is a model or personal. Each group needs 5–10 unique cues,
with both languages and at most 100 characters per language. The loader rejects
missing/unknown groups and malformed entries instead of substituting generic hints.
Pistes are file-backed, require no migration, and never rewrite responses or progress.
The EO2 sidebar retains completion, personalisation and individual practice controls;
practice statistics and vocabulary are no longer displayed there. Vocabulary and
its saved practice data remain available in their existing dedicated views.

EO task 3 adds a structured speaking plan in `study/content/tache_3/hints.json`:
introduction and stance, three arguments with illustrative examples, a nuance,
and a conclusion. French cues appear above their English meanings. Every semantic
group shares one coherent possible plan anchored in its canonical model, not a
live summary of a learner's personal answer. Plans are limited to 140 French words;
missing groups, incomplete translations and duplicate argument cues are rejected.
The new card sits outside the existing annotation roots so it cannot shift saved
response or sidebar highlights. Existing study controls and vocabulary remain.

EE task 1 also provides **Pistes** for Invitations & fêtes, Sorties & visites,
Accueillir un invité, Voyages & vacances, Ville & quartier, Logement &
déménagement, and Transports & orientation. The 44 canonical lists in
`study/content/ee/tache_1/hints.json` cover all 96 equivalent publications.
They summarize reviewed current responses, including authorized customizations,
without publishing account identifiers or private contact details. Each list has
5–8 bilingual cues, at most 110 characters per language per cue and 75 French
words in total. These are shared editorial snapshots, not live summaries of an
account's latest answer. The cache contains no learner state, the card stays
outside response annotation roots, and other writing themes/tasks remain unchanged.

EO task 2 and task 3 use editorial `semantic_groups.json` partitions, including
singletons. A shared answer or question-body hash is **not** proof of equivalence.
The importer rejects missing, incomplete, duplicate or cross-task memberships.
The manifest canonical retains identity; directories display the first publication
in their own order and search all publications before grouping and limiting.

Each prompt keeps its matching model text, questions and vocabulary. Detail pages
and practice show one current response: the learner's active personal response,
or the published model when there is no personal override. There is no version
chooser or oral history page; former history URLs and version-selection parameters
return 404. Saved personal data, schedules, review logs and recovery snapshots remain
stored and available in account exports. Resetting selects the published model
without deleting work. Annotations remain available in Notes rather than being
replayed on a different response text.

An old response's ambiguous shared state belongs only to the corrected group
containing its original canonical key. Occurrence-provenanced annotations and
personal work follow their source prompt. Split vocabulary decks retain original
source IDs where available, otherwise use stable derived IDs with fresh progress.
Imports retain original response/card/log IDs and never fan out old completion to
all previously grouped prompts. Schedule projection snapshots the target and donor
states first and runs once per membership revision, excluding rationale changes.
Historical previous reviews remain inspectable but cannot undo a schedule already
projected into another group, including a surviving canonical card's old reviews.
The importer locks affected review sessions before cards, archives and clears
stale Undo pointers without deleting their logs, and records each projected
card's existing review-log high-water ID. Undo cannot cross that boundary.
Timestamp ties and unchanged imports do not invalidate genuinely later reviews,
including reviews written by an old worker during application replacement.

**Deployment gate:** apply migrations and import both complete manifests before
serving the new application. Render and Vercel builds call `deploy_database`
(migrations first, then fingerprinted import); Procfile releases do the same.
Do not use `[skip db]` for this rollout. For a manual deployment run
`python manage.py deploy_database --force`, then restart workers. Do not regenerate
manifests from body hashes or replace the immutable original source files.
The additive oral columns keep database defaults as well as Python defaults,
so workers using the pre-upgrade ORM can finish inserts during replacement.

## Runtime efficiency

- `study/catalogue.py` shares immutable bundled expression content across requests.
  Restart workers after content changes; learner progress and database querysets
  are never cached there. Custom-path parsers and content imports still validate
  their inputs directly.
- Subject directories reuse one collection/group/row component and render each
  publication once, with card and table presentations of the same elements.
  EO Tâche 3 nests subject families within themes; each level counts unique
  responses for progress without duplicating subject rows.
  Theme-specific labels in `study/content/tache_3/subject_family_labels.json`
  clarify the existing families without changing memberships or saved progress.
  EO/EE subject directories and subject-only searches default to **Dédupliquer**,
  keeping the first displayed occurrence of each equivalent group. The toggle or
  `?deduplicate=0` shows every publication. Search and subject links preserve the
  chosen mode, including previous/next navigation and its within-theme counter.
  Opening an equivalent publication keeps its own text and selected response,
  while its navigation position refers to the shared group when deduplicated.
  The removed EO Tâche 3 theme/family and
  practice-overview URLs have no routes and return 404, without redirects.
  Individual practice sessions, study content, and saved progress remain.
  Oral and written completion controls share one JavaScript controller.
  EE1/EE2 response cards have per-account Edit controls and Delete controls on
  alternatives only, with confirmation. The main response cannot be deleted
  through these controls. Migration `0054` stores private model-version edits and
  deletions without changing shared content; equivalent prompts share them.
  Removing a version preserves the remaining copy and annotation identifiers.
- Vocabulary listings start in table view and remember their card/table choice
  separately from subject and note listings. Study/review sessions retain their
  flashcard behavior. Selecting a guided lot opens its entries in table view;
  a separate practice action starts that lot's available review cards.
- Subject progress filters highlight candidates before transferring rows to Python.
  Existing source-key and URL parsers remain the final matching authority; batching
  keeps larger requests within database parameter limits.
- Notes and highlights have independent ascending/descending date controls within
  each relative-date period. Sorting uses capture time, preserves the period order
  and filters, and runs before pagination; it never changes saved annotations.
- Course exposure checks use an indexed, derived projection of allocated item
  identities, not scored progress or answers. The first access indexes all missing
  attempts in batches; subsequent access processes only newly unindexed attempts.
  Original snapshots and events remain authoritative. Native deletion cascades on
  the projection tables must be preserved by future migrations.

Course attempt/production histories and same-lesson scored-guidance reconstruction
remain history-dependent; the exposure optimization does not truncate or cap them.

## Project structure

| Path                                | Responsibility                                               |
| ----------------------------------- | ------------------------------------------------------------ |
| `config/`                           | Django settings, root URLs, and deployment entry points      |
| `study/models.py`                   | Persistent study, progress, and account data                 |
| `study/account_services.py`         | Account provisioning, recovery, and login throttling         |
| `study/content_loader.py`           | Pure parsing and validation of bundled study content         |
| `study/catalogue.py`                | Shared immutable expression catalogues and lookup indexes    |
| `study/ee_formulations.py`          | Validated EE3 writing frames, source evidence and categories |
| `study/learning_content.py`         | Validation and cached loading for the Learn curriculum        |
| `study/course_content.py`           | Typed original course and benchmark coverage contracts       |
| `study/course_practice.py`          | Server-side selection, grading, exposure and delayed review  |
| `study/card_presentation.py`        | Review scope parsing and card response payloads              |
| `study/response_personalization.py` | Canonical and personalized response resolution               |
| `study/views/`                      | HTTP request handlers and shared view helpers                |
| `study/templates/study/partials/`   | Reusable app template fragments                              |
| `study/static/study/`               | Versioned CSS, JavaScript, icons, and images                 |
| `study/content/`                    | Source-controlled content imported into the database         |
| `study/content/learning/`           | Source-controlled lessons rendered by the Learn experience   |
| `templates/`                        | Project-wide shell, error, PWA, and service-worker templates |

The preserved reference library is loaded from
`study/content/learning/curriculum.json`. Original course lessons are complete
JSON objects under `study/content/learning/courses/<level>/`. Both catalogs are
validated and cached per process; restart the app after changing content.
Lesson-only edits do not invalidate the database-content import fingerprint;
the importer still checks all imported content, its code, and schema inputs.
Keep lesson IDs, section IDs and slugs stable to preserve saved progress,
annotation anchors and links. `/apprendre/` defaults to the original course
when installed; `?scope=reference` and all old detail URLs retain the library.
An absent course directory falls back to reference reading, not an empty replacement.

Course summaries, objectives and the practice link sit in a right-hand sidebar on
wide screens and above the teaching on smaller screens. Use explicit backticks
for French snippets inside English explanations; the existing inline renderer
marks them as French and gives them a distinct style. Do not automatically style
ambiguous words such as English "on". Plain-text searches ignore those backticks.
Apply this convention throughout A1–B2 and C1-preparation teaching, including
mixed-language section headings, example notes, correction explanations and
production instructions/rubrics. Leave already-French examples and translations
alone unless an English explanation contains a genuine French mention. The
all-course formatting pass preserves wording, identities and every exercise object.
Assessment versions ignore these teaching-only delimiters, so completed checks
and delayed reviews remain current. Previously stored attempts are not rewritten.

The course contains 33 A1, 36 A2, 26 B1 and 25 B2 lessons, with exact
coverage mappings for all 479 public benchmark topics, plus nine C1-oriented
preparation lessons. The teaching-depth follow-up enriched 75 existing lessons
after reading all 479 public teaching bodies: 478 comparisons are complete and
one compound-order variant remains explicitly unassessed. Its 2,513 controlled items and contextual self-review tasks
do not replace independent four-skill assessment. See the
[implementation record](docs/apprendre-rebuild-plan.md) for scope and limitations.

See [the course contract](docs/apprendre-implementation-contract.md) for the
lesson, coverage and depth-report schemas. The immutable `course_manifest.json`
records published identities, sources and preparation links. Validate authored content before deployment:

```bash
python manage.py validate_courses
python manage.py validate_courses --coverage
python manage.py validate_courses --coverage --depth
python manage.py test study.tests.test_course_bundle study.tests.test_course_depth study.tests.test_course_platform study.tests.test_learning
```

Reading completion is self-declared and separate from controlled grammar results.
Practice reveals feedback on request; checks and reviews grade first submitted
answers on the server using frozen item snapshots. The bounded criterion is
80% overall and 75% text accuracy. Review opens seven days after the first
successful check for that content version, including a clearly labelled
rehearsed success after a failure. Previously presented items, even from abandoned
sessions, cannot become fresh evidence through a retry or feedback edit.
Bank exhaustion permits rehearsal, not a false independent-mastery claim.
Open production is saved for model/rubric self-review, never automatically scored.

The separate practice page offers section/item guidance, not a mastery score.
Learning prioritizes recent incorrect or blank first answers, then hint-supported
answers, then untested items, using completed sessions only. It spreads equally
prioritized sections and prefers unseen practice items within the chosen focus;
revisiting a known weakness may deliberately rehearse an old question.
Checks/reviews spread eligible sections while preserving their bounded size,
text-answer quota and fresh-bank preference. Frozen session scope lists omitted
sections and those without eligible items; a short sample is not full coverage.
Section feedback uses only completed checks/reviews, counts the latest first
answer per unchanged item, and labels rehearsed evidence. Unchanged item versions
can inform guidance after teaching edits, explicitly labelled as older evidence;
new or changed items remain untested, and earlier results are never rewritten.

Answer normalization preserves accents and internal punctuation, while allowing
case, typographic apostrophes, whitespace and optional terminal `. ! ? …`.
Items testing capitalization or terminal punctuation can explicitly set
`case_sensitive` or `terminal_punctuation_sensitive` to `true`.
Account export format 11 includes reading, session history, course productions,
private writing-response overrides, and annotation completion/source metadata;
unfinished and abandoned session answer keys remain hidden. Confirmed progress
reset removes course history and productions, preserving notes and highlights.
Account deletion cascades all owned course data. No practice percentage converts
to an official CEFR, TCF or NCLC score.

For reference-library provenance only,
`source_type` accepts `pdf`, `notion`, `mixed`, or `editorial-gap-fill`;
source-backed lessons must retain their source labels. Labels record provenance,
not proof that every item in a source is covered.

## Naming conventions

- Python modules use `snake_case` and describe one responsibility. Service,
  loader, presentation, and helper modules carry those roles in their names.
- Browser assets use `kebab-case`; names describe behavior rather than an
  implementation detail or one third-party provider.
- Reusable templates live under `study/partials/` without underscore prefixes.
- Numbered task directories use `tache_<number>`. Numbered content packs use
  explicit suffixes such as `_1` or `_01`, according to the source series.
- Database content keys, source IDs, and URL names are stable identifiers. File
  organization may change, but those identifiers must not be renamed.
