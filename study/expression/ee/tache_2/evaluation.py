"""Grounded EE Tâche 2 evaluation using the shared writing report validator."""

from functools import lru_cache
from pathlib import Path

from study.expression.ee.tache_1 import evaluation as shared_evaluation

oral_evaluation = shared_evaluation.oral_evaluation



@lru_cache(maxsize=1)
def master_prompt():
    return (
        Path(__file__).resolve().parents[3]
        / "content"
        / "expression"
        / "ee"
        / "tache_2"
        / "ai_examiner_prompt.md"
    ).read_text(encoding="utf-8")


def score(*, subject, response, word_count):
    return shared_evaluation.score(
        subject=subject,
        response=response,
        word_count=word_count,
        master_prompt=master_prompt(),
        word_min=120,
        word_max=150,
        schema_name="ee2_bilan",
    )
