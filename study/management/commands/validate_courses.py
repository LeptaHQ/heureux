import json

from django.core.management.base import BaseCommand, CommandError

from study.course_content import CONTENT_ROOT, load_course_catalog, validate_coverage_ledger


class Command(BaseCommand):
    help = "Validate complete original lessons and, optionally, all benchmark coverage ledgers."

    def add_arguments(self, parser):
        parser.add_argument("--coverage", action="store_true")

    def handle(self, *args, **options):
        try:
            catalog = load_course_catalog(CONTENT_ROOT / "courses")
            if not catalog.lessons:
                raise ValueError("No course lessons are installed")
            if options["coverage"]:
                for level in ("a1", "a2", "b1", "b2"):
                    validate_coverage_ledger(
                        json.loads((CONTENT_ROOT / "coverage" / f"{level}.json").read_text(encoding="utf-8")),
                        json.loads((CONTENT_ROOT / "benchmarks" / f"{level}.json").read_text(encoding="utf-8")),
                        catalog,
                    )
        except (ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Validated {len(catalog.lessons)} course lessons."))
