"""Private, explicit learning state for the curated EE3 formulation bank."""

from .ee_formulations import get_ee_formulations
from .models import MemoryQuestionProgress
from .progress import progress_summary


def formulation_progress(user, catalog=None):
    catalog = catalog or get_ee_formulations()
    keys = {entry.content_key for entry in catalog.entries}
    learned = set(
        MemoryQuestionProgress.objects.filter(
            user=user, memory_number=1, question_key__in=keys,
        ).values_list("question_key", flat=True)
    )
    return learned, progress_summary(
        total=len(keys), started=len(learned), completed=len(learned),
    )
