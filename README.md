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

## Project structure

| Path                                | Responsibility                                               |
| ----------------------------------- | ------------------------------------------------------------ |
| `config/`                           | Django settings, root URLs, and deployment entry points      |
| `study/models.py`                   | Persistent study, progress, and account data                 |
| `study/account_services.py`         | Account provisioning, recovery, and login throttling         |
| `study/content_loader.py`           | Pure parsing and validation of bundled study content         |
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
Keep lesson IDs, section IDs and slugs stable to preserve saved progress,
annotation anchors and links. `/apprendre/` defaults to the original course
when installed; `?scope=reference` and all old detail URLs retain the library.
An absent course directory falls back to reference reading, not an empty replacement.

See [the course contract](docs/apprendre-implementation-contract.md) for the
lesson and coverage schemas. Validate authored content before deployment:

```bash
python manage.py validate_courses
python manage.py validate_courses --coverage
python manage.py test study.tests.test_course_platform study.tests.test_learning
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
