import json
from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from study.course_content import (
    CONTENT_ROOT,
    load_course_catalog,
    validate_coverage_ledger,
    validate_depth_report,
)


class Command(BaseCommand):
    help = "Validate original lessons and optional benchmark coverage and public-text depth reports."

    def add_arguments(self, parser):
        parser.add_argument("--coverage", action="store_true")
        parser.add_argument("--depth", action="store_true")

    def handle(self, *args, **options):
        depth_summaries = []
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
            if options["depth"]:
                for level in ("a1", "a2", "b1", "b2"):
                    entries = validate_depth_report(
                        json.loads((CONTENT_ROOT / "depth" / f"{level}.json").read_text(encoding="utf-8")),
                        json.loads((CONTENT_ROOT / "benchmarks" / f"{level}.json").read_text(encoding="utf-8")),
                        catalog,
                    )
                    access = Counter(entry.access for entry in entries)
                    compared = sum(entry.compared for entry in entries)
                    depth_summaries.append(
                        f"{level.upper()} depth: {len(entries)} recorded; "
                        f"{access['read']} read, {access['partial']} partial, "
                        f"{access['unavailable']} unavailable; {compared} compared, "
                        f"{len(entries) - compared} not assessed."
                    )
        except (ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Validated {len(catalog.lessons)} course lessons."))
        for summary in depth_summaries:
            self.stdout.write(summary)
        if options["depth"]:
            self.stdout.write(
                "Depth validation checks record structure and links, not source-reading truth, "
                "teaching equivalence or proprietary assessment."
            )
