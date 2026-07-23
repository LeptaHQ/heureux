# Heureux

Heureux is a Django study application. It combines
model responses, reusable vocabulary, comprehension practice, spaced
repetition, notes, highlights, and explicit subject-completion tracking.

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
| `study/card_presentation.py`        | Review scope parsing and card response payloads              |
| `study/response_personalization.py` | Canonical and personalized response resolution               |
| `study/views/`                      | HTTP request handlers and shared view helpers                |
| `study/templates/study/partials/`   | Reusable app template fragments                              |
| `study/static/study/`               | Versioned CSS, JavaScript, icons, and images                 |
| `study/content/`                    | Source-controlled content imported into the database         |
| `templates/`                        | Project-wide shell, error, PWA, and service-worker templates |

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
