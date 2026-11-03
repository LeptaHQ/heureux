import copy
from datetime import datetime, timezone
from http.client import HTTPException
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from study.eo3_response_languages import (
    empty_manifest, fingerprint, model_theme, public_fields, scoped_models,
    translation_path, validate_manifest,
)
from study.tache_three_models import spoken_text
from study.translation import deepl_translate, deepl_usage, write_translation_manifest


class Command(BaseCommand):
    help = "Inspect or explicitly prepare public EO3 response glosses with DeepL; never runs on visits."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--check", action="store_true")
        mode.add_argument("--prepare", action="store_true")
        parser.add_argument("--confirm-characters", type=int)
        parser.add_argument("--themes", nargs="+", choices=sorted({
            model_theme(model) for model in scoped_models().values()
        }))

    def handle(self, *args, **options):
        path = translation_path()
        try:
            data = validate_manifest(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else empty_manifest()
        except (OSError, ValueError) as exc:
            raise CommandError(f"Cannot read the EO3 translation manifest: {exc}") from None
        data = copy.deepcopy(data)
        if settings.DEEPL_TARGET_LANG not in {"EN-GB", "EN-US"}:
            raise CommandError("EO3 preparation requires DEEPL_TARGET_LANG=EN-GB or EN-US.")
        if data["target_language"] != settings.DEEPL_TARGET_LANG:
            if data["groups"]:
                raise CommandError("Saved translations use a different target; do not mix English variants.")
            data["target_language"] = settings.DEEPL_TARGET_LANG
        models = {
            group: model for group, model in scoped_models().items()
            if not options["themes"] or model_theme(model) in options["themes"]
        }
        pending = []
        total = 0
        for group, model in sorted(models.items()):
            texts = public_fields(model)
            total += len(texts)
            saved = data["groups"].get(group, {})
            missing = list(dict.fromkeys(
                text for text in texts.values() if fingerprint(text) not in saved
            ))
            if missing:
                pending.append((group, model, missing))
        count = sum(len(texts) for _, _, texts in pending)
        characters = sum(len(text) for _, _, texts in pending for text in texts)
        self.stdout.write(
            f"{len(models)} models; {total} response blocks; {count} missing translations; "
            f"{characters} source characters to send to DeepL."
        )
        if options["check"]:
            if pending:
                raise CommandError("Translations are missing or French responses have changed; nothing was sent.")
            self.stdout.write("All current response blocks have matching saved DeepL translations.")
            return
        if not options["prepare"]:
            self.stdout.write(
                f"To prepare, use --prepare --confirm-characters {characters}. "
                "Only public French response blocks and their public context are sent."
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
        for group, model, texts in pending:
            try:
                english = deepl_translate(
                    texts, key,
                    context=(
                        f"Réponse publique pour cet exercice oral TCF Canada : {model.source_prompts[0][1]}\n"
                        f"Intervention complète : {spoken_text(model.response)}"
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
            try:
                write_translation_manifest(path, data)
            except OSError:
                raise CommandError(
                    f"Cannot save EO3 translations for {group}; earlier completed models remain saved. "
                    "No automatic retry was made."
                ) from None
            self.stdout.write(f"Saved {group}: {len(texts)} DeepL translations.")
