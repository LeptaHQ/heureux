import copy
from datetime import datetime, timezone
from http.client import HTTPException
import json
import os
import tempfile

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from study.eo2_question_languages import (
    THEMES, empty_manifest, fingerprint, scoped_dialogues, translation_path, validate_manifest,
)
from study.translation import deepl_translate, deepl_usage


class Command(BaseCommand):
    help = "Inspect or explicitly prepare saved EO2 question translations with DeepL; never runs on visits."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--check", action="store_true")
        mode.add_argument("--prepare", action="store_true")
        parser.add_argument("--confirm-characters", type=int)
        parser.add_argument("--themes", nargs="+", choices=sorted(THEMES))

    def handle(self, *args, **options):
        from study import catalogue

        path = translation_path()
        try:
            data = validate_manifest(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else empty_manifest()
        except (ValueError, OSError) as exc:
            raise CommandError(f"Cannot read the EO2 translation manifest: {exc}") from None
        data = copy.deepcopy(data)
        if settings.DEEPL_TARGET_LANG not in {"EN-GB", "EN-US"}:
            raise CommandError("EO2 question preparation requires DEEPL_TARGET_LANG=EN-GB or EN-US.")
        if data["target_language"] != settings.DEEPL_TARGET_LANG:
            if data["groups"]:
                raise CommandError("Saved translations use a different target; do not mix English variants.")
            data["target_language"] = settings.DEEPL_TARGET_LANG
        _, themes = catalogue.tache_two_subject_themes()
        group_themes = {
            row.group: themes[key] for key, row in catalogue.tache_two_dialogues().items()
        }
        source_prompts = {
            f"tache2:{month.slug}:batch-{batch.number:02d}:subject-{subject.number:02d}": subject.prompt
            for month in catalogue.tache_two_subject_months()
            for batch in month.batches for subject in batch.subjects
        }
        group_contexts = {}
        for key, row in catalogue.tache_two_dialogues().items():
            group_contexts.setdefault(row.group, source_prompts[key])
        selected = set(options["themes"] or THEMES)
        models = {
            group: row for group, row in scoped_dialogues().items() if group_themes[group] in selected
        }
        pending = []
        total = 0
        for group, dialogue in sorted(models.items()):
            saved = data["groups"].get(group, {})
            texts = list(dict.fromkeys(
                question.question for question in dialogue.questions
                if fingerprint(question.question) not in saved
            ))
            total += len(dialogue.questions)
            if texts:
                pending.append((group, dialogue, texts))
        count = sum(len(texts) for _, _, texts in pending)
        characters = sum(len(text) for _, _, texts in pending for text in texts)
        self.stdout.write(
            f"{len(models)} models; {total} questions; {count} missing translations; "
            f"{characters} source characters to send to DeepL."
        )
        if options["check"]:
            if pending:
                raise CommandError("Translations are missing or French questions have changed; nothing was sent.")
            self.stdout.write("All current questions have matching saved DeepL translations.")
            return
        if not options["prepare"]:
            self.stdout.write(
                f"To prepare, use --prepare --confirm-characters {characters}. "
                "Only shared French questions and their public context are sent."
            )
            return
        if not pending:
            self.stdout.write("Already prepared; no provider call.")
            return
        if options["confirm_characters"] != characters:
            raise CommandError("Run --dry-run, then confirm the exact current character count.")
        key = settings.DEEPL_API_KEY
        if not key:
            raise CommandError("DEEPL_API_KEY is not configured; no translations were generated.")
        try:
            used, limit = deepl_usage(key)
        except (OSError, HTTPException, UnicodeError, ValueError):
            raise CommandError("DeepL usage could not be verified; no translation request was sent.") from None
        if characters > limit - used:
            raise CommandError("The requested translations exceed the remaining DeepL character allowance.")
        for group, dialogue, texts in pending:
            try:
                english = deepl_translate(
                    texts, key,
                    context=(
                        f"Questions pour ce jeu de rôle oral : {group_contexts[group]}\n"
                        f"Début de la conversation : {dialogue.opening}"
                    ),
                )
                rows = data["groups"].setdefault(group, {})
                for french, translated in zip(texts, english):
                    rows[fingerprint(french)] = {"french": french, "english": translated.strip()}
                data["generated_at"] = datetime.now(timezone.utc).isoformat()
                data.pop("reviewed_at", None)
                validate_manifest(data)
            except (OSError, HTTPException, UnicodeError, ValueError):
                raise CommandError(
                    f"DeepL preparation failed for {group}; earlier completed models are saved. "
                    "No automatic retry was made. Inspect --dry-run before resuming."
                ) from None
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=path.parent, delete=False,
                ) as stream:
                    temporary = stream.name
                    json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
                    stream.write("\n")
                os.replace(temporary, path)
                temporary = None
            finally:
                if temporary is not None:
                    os.unlink(temporary)
            self.stdout.write(f"Saved {group}: {len(texts)} DeepL translations.")
