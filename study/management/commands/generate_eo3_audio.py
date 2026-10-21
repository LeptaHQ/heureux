from django.core.management.base import BaseCommand, CommandError

from study import catalogue
from study.eo3_audio import NarrationError, generate_narration, narration_spec
from study.models import EO3Narration


class Command(BaseCommand):
    help = "Prepare cached ElevenLabs narration of approved public EO3 models."

    def add_arguments(self, parser):
        selection = parser.add_mutually_exclusive_group(required=True)
        selection.add_argument("--group", help="One canonical group, e.g. culture-p1.")
        selection.add_argument("--all", action="store_true", help="All approved models.")
        parser.add_argument("--dry-run", action="store_true", help="Estimate only; no paid calls.")
        parser.add_argument("--confirm-cost", action="store_true", help="Allow paid generation.")

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
            cached = set(EO3Narration.objects.filter(
                fingerprint__in=[spec.fingerprint for spec in specs],
            ).values_list("fingerprint", flat=True))
            missing = [spec for spec in specs if spec.fingerprint not in cached]
            self.stdout.write(
                f"{len(specs)} models; {len(cached)} cached; {len(missing)} to generate; "
                f"{sum(len(spec.text) for spec in missing)} new input characters."
            )
            if options["dry_run"]:
                return
            for spec in specs:
                created = generate_narration(spec)
                self.stdout.write(f"{spec.group}: {'generated' if created else 'cached'}")
        except NarrationError as exc:
            raise CommandError(str(exc)) from None
