from django.core.management.base import BaseCommand, CommandError

from study.eo3_audio import NarrationError
from study.audio_pin import AudioPinError, command_generation_pin
from study.french_audio import SpeechError, generate_prepared, has_saved_recording
from study.models import FrenchNarration, FrenchNarrationBudget


class Command(BaseCommand):
    help = "Inspect or explicitly prepare ONE app-wide narration request. Never run on web startup."

    def add_arguments(self, parser):
        parser.add_argument("--id", required=True, help="Exact request fingerprint shown by the reader.")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--confirm-cost", action="store_true")

    def handle(self, *args, **options):
        try:
            recording = FrenchNarration.objects.get(pk=options["id"])
        except FrenchNarration.DoesNotExist:
            raise CommandError("Unknown narration request.") from None
        reserved = FrenchNarrationBudget.objects.filter(pk=1).values_list(
            "reserved_characters", flat=True,
        ).first() or 0
        self.stdout.write(
            f"{recording.pk}: {recording.status}; "
            f"{'private, owner-isolated' if recording.owner_id else 'public'}; "
            f"{len(recording.text)} input characters; {reserved} lifetime characters reserved."
        )
        if options["dry_run"]:
            return
        if not options["confirm_cost"]:
            raise CommandError("Inspect --dry-run, then use --confirm-cost to authorize ONE paid request.")
        try:
            pin = command_generation_pin() if (
                recording.status != "ready" and not has_saved_recording(recording)
            ) else None
            created = generate_prepared(recording.pk, pin=pin)
        except (NarrationError, SpeechError, AudioPinError) as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write("Generated." if created else "Already cached; no provider call.")
