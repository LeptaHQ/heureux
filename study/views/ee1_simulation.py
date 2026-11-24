"""EE Tâche 1 simulation configuration."""

import threading

from study.expression.ee.tache_1 import evaluation
from study.views.writing_simulation import (
    WritingSimulationSpec,
    _attempt_context as _shared_attempt_context,
    _setup_context as _shared_setup_context,
    attempt as _shared_attempt,
    evaluate as _shared_evaluate,
    evaluation_json,
    run_evaluation as _shared_run_evaluation,
    setup as _shared_setup,
    start as _shared_start,
    subject_picker as _shared_subject_picker,
    task_for as _shared_task,
    update_timer as _shared_update_timer,
)


SPEC = WritingSimulationSpec(
    number=1,
    word_min=60,
    word_max=120,
    minutes_setting="EE1_SIMULATION_MINUTES",
    evaluator=evaluation,
    response_label="Votre message",
    response_placeholder="Rédigez votre message ici…",
    session_prompt=(
        "Rédigez un message clair, adapté au destinataire, en "
        "{word_min} à {word_max} mots. Vous disposez de {minutes} minutes."
    ),
    picker_intro=(
        "Sélectionnez un sujet pour votre message de "
        "{word_min} à {word_max} mots."
    ),
)


def _task():
    return _shared_task(SPEC)


def subject_picker(request):
    return _shared_subject_picker(request, SPEC)


def setup(request):
    return _shared_setup(request, SPEC)


def start(request):
    return _shared_start(request, SPEC)


def update_timer(request, attempt_id):
    return _shared_update_timer(request, SPEC, attempt_id)


def _setup_context(request, task):
    return _shared_setup_context(request, SPEC, task)


def _attempt_context(attempt, *, error="", now=None):
    return _shared_attempt_context(attempt, SPEC, error=error, now=now)


def attempt(request, attempt_id):
    return _shared_attempt(request, SPEC, attempt_id)


def _run_evaluation(attempt_id, started_at):
    return _shared_run_evaluation(attempt_id, started_at, SPEC)


def evaluate(request, attempt_id):
    return _shared_evaluate(
        request,
        SPEC,
        attempt_id,
        thread_module=threading,
    )


def _evaluation_json(attempt, *, status=200):
    return evaluation_json(attempt, status=status)
