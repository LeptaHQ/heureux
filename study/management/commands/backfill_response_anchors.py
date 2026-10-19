"""Bind existing selections before publishing changes to their surrounding text."""

from django.core.management.base import BaseCommand
from django.db import transaction

from study.models import Annotation
from study.public_response_annotations import capture_public_response_anchor


class Command(BaseCommand):
    help = "Record verified EO3 field anchors without copying response text or changing notes."

    def handle(self, *args, **options):
        candidates = Annotation.objects.filter(
            response_anchor={}, source_key__startswith="response:",
        ).exclude(quote="").exclude(
            source_key__startswith="response:tache2:",
        ).order_by("pk")
        recorded = 0
        examined = 0
        deleted = 0
        for pk in candidates.values_list("pk", flat=True).iterator(chunk_size=200):
            with transaction.atomic():
                annotation = Annotation.objects.select_for_update(
                    of=("self",),
                ).select_related("user").filter(pk=pk).first()
                if annotation is None:
                    deleted += 1
                    continue
                if annotation.response_anchor:
                    continue
                examined += 1
                anchor = capture_public_response_anchor(annotation)
                if anchor:
                    Annotation.objects.filter(pk=pk).update(response_anchor=anchor)
                    recorded += 1
        self.stdout.write(
            f"EO3 field anchors: {recorded} recorded; {examined - recorded} left unscoped. "
            f"{deleted} concurrently deleted rows skipped. "
            "Unverified selections remain stored without guessed placement."
        )
