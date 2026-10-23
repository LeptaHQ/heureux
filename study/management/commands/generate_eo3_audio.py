from django.core.management.base import BaseCommand, CommandError

from study import catalogue
from study.audio_pin import AudioPinError, command_generation_pin
from study.eo3_audio import (
    NarrationError, generate_narration, narration_source, narration_spec, saved_narrations,
)


class Command(BaseCommand):
    help = "Prepare cached ElevenLabs narration of approved public EO3 models."

    def add_arguments(self, parser):
        selection = parser.add_mutually_exclusive_group(required=True)
        selection.add_argument("--group", help="One canonical group, e.g. culture-p1.")
        selection.add_argument("--all", action="store_true", help="All approved models.")
        parser.add_argument("--dry-run", action="store_true", help="Estimate only; no paid calls.")
        parser.add_argument("--confirm-cost", action="store_true", help="Allow paid generation.")
        parser.add_argument("--refresh", action="store_true", help="Use current text/voice instead of an older saved take.")

    def handle(self, *args, **options):
        models = catalogue.tache_three_models()
        if options["group"]:
            group = options["group"]
            if not group.startswith("eo/tache-3/"):
                group = f"eo/tache-3/{group}"
            if group not in models:
                raise CommandError("Unknown approved EO3 group.")
            models = {group: models[group]}
        if not options["dry_run"] and not options["confirm_cost"]:
            raise CommandError("Use --dry-run first, then --confirm-cost to permit paid generation.")
        try:
            specs = [narration_spec(model) for model in models.values()]
            sources = [narration_source(model) for model in models.values()]
            saved = saved_narrations(sources, current_only=options["refresh"])
            cached = {spec.fingerprint for spec, source in zip(specs, sources) if source in saved}
            missing = [spec for spec in specs if spec.fingerprint not in cached]
            self.stdout.write(
                f"{len(specs)} models; {len(cached)} cached; {len(missing)} to generate; "
                f"{sum(len(spec.text) for spec in missing)} new input characters."
            )
            if options["dry_run"]:
                return
            for spec in specs:
                pin = command_generation_pin() if spec.fingerprint not in cached else None
                created = generate_narration(spec, pin=pin, refresh=options["refresh"])
                self.stdout.write(f"{spec.group}: {'generated' if created else 'cached'}")
        except (NarrationError, AudioPinError) as exc:
            raise CommandError(str(exc)) from None
