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

## Oral subject equivalence

EO task 2 and task 3 use editorial `semantic_groups.json` partitions, including
singletons. A shared answer or question-body hash is **not** proof of equivalence.
The importer rejects missing, incomplete, duplicate or cross-task memberships.
The manifest canonical retains identity; directories display the first publication
in their own order and search all publications before grouping and limiting.

Each original prompt keeps its model text, questions and vocabulary. Equivalent
subjects may have different models. Detail pages offer the original models and
every preserved personal alternative, with matching copy and practice controls.
The history link exposes older learner versions, schedules, review logs and
annotations; account exports include recovery snapshots. Saving/restoring a version
keeps the previous one; resetting selects the original model without deleting work.
Annotations on changed text remain in history rather than being replayed on a
different model.

An old response's ambiguous shared state belongs only to the corrected group
containing its original canonical key. Occurrence-provenanced annotations and
personal work follow their source prompt. Split vocabulary decks retain original
source IDs where available, otherwise use stable derived IDs with fresh progress.
Imports retain original response/card/log IDs and never fan out old completion to
all previously grouped prompts. Schedule projection snapshots the target and donor
states first and runs once per membership revision, excluding rationale changes.
Historical previous reviews remain inspectable but cannot undo a schedule already
projected into another group, including a surviving canonical card's old reviews.
Each changed schedule advances a card generation under lock; new review logs carry
that generation, and Undo only accepts a matching generation. Timestamp ties and
unchanged imports do not invalidate genuinely post-projection reviews.

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
  Oral and written completion controls share one JavaScript controller.
- Subject progress filters highlight candidates before transferring rows to Python.
  Existing source-key and URL parsers remain the final matching authority; batching
  keeps larger requests within database parameter limits.
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
Export format 9 includes reading, session history and course productions;
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
