import logging
import threading
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError, connections, transaction
from django.db.models import Min, Q
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from study.models import LiveSimulation, OralEvaluationJob, Task
from study.simulation import copilot_runtime, oral_evaluation
from study.simulation.evaluation import DEADLINE_SECONDS, EvaluationError, available_providers, timed_phase

EO3_KEY_PREFIX = "eo3:"
LEASE_DURATION = timedelta(seconds=DEADLINE_SECONDS + 30)
MAX_EXECUTIONS = 2
FAILED = "Le bilan a échoué. Votre transcription reste disponible."
LATE = "Le bilan n’est pas arrivé à temps. Votre transcription reste disponible."
logger = logging.getLogger(__name__)
_lock = threading.Lock()
_changed = threading.Event()
_runner = None


def wake():
    global _runner
    with _lock:
        _changed.set()
        if _runner is None:
            runner = threading.Thread(target=_drain, daemon=True, name="oral-evaluation")
            runner.start()
            _runner = runner


def pending_jobs():
    return OralEvaluationJob.objects.filter(error_status=0)


def lock_simulations(sessions):
    # Enqueue, successful completion and cascading deletion all lock the transcript first.
    return list(sessions.order_by("pk").select_for_update().values_list("pk", flat=True))


def _claim():
    while True:
        now = timezone.now()
        with transaction.atomic():
            job = pending_jobs().select_for_update().filter(
                Q(lease_until__isnull=True) | Q(lease_until__lte=now),
            ).order_by("queued_at", "pk").first()
            if job is None:
                return None, pending_jobs().aggregate(earliest=Min("lease_until"))["earliest"]
            if job.executions >= (1 if job.provider in copilot_runtime.MODELS else MAX_EXECUTIONS):
                OralEvaluationJob.objects.filter(pk=job.pk).update(error_status=504, error=LATE)
                continue
            job.lease_id = uuid.uuid4()
            job.lease_until = now + LEASE_DURATION
            job.executions += 1
            job.save(update_fields=["lease_id", "lease_until", "executions"])
            return job, None


def _source(job):
    snapshot = LiveSimulation.objects.filter(
        pk=job.simulation_id, user__is_active=True,
    ).values("snapshot", "rows", "subject_key", "user_id").first()
    if not snapshot or not 0 < len(settings.AI_PIN) <= 128:
        return None
    if job.provider not in copilot_runtime.MODELS and job.provider not in available_providers():
        return None
    monologue = snapshot["subject_key"].startswith(EO3_KEY_PREFIX)
    if not snapshot["snapshot"].get("prompt") or not Task.objects.filter(
        part__slug="eo", part__available=True, slug="tache-3" if monologue else "tache-2", available=True,
    ).exists():
        return None
    rows = [{"speaker": row["speaker"], "text": row["text"]} for row in snapshot["rows"]]
    return snapshot["snapshot"]["prompt"], rows, monologue, snapshot["user_id"]


@sensitive_variables()
def _evaluate(job, source, *, timings=None):
    if source is None:
        return {"error": "Le bilan n’est pas disponible."}, 403
    prompt, rows, monologue, user_id = source
    try:
        options = {}
        if job.provider in copilot_runtime.MODELS:
            try:
                options["request_report"] = copilot_runtime.linked_report_transport(
                    user_id, job.provider, job.copilot_link_id, timings=timings,
                )
            finally:
                connections.close_all()
        return oral_evaluation.score(
            prompt, rows, monologue=monologue, provider=job.provider, timings=timings, **options,
        ), 200
    except EvaluationError as exc:
        return {"error": str(exc)}, exc.status
    except Exception as exc:
        logger.error("Oral evaluation failed job=%s error=%s", job.pk, type(exc).__name__)
        return {"error": FAILED}, 500


@transaction.atomic
def _finish(job, body, status):
    leased = pending_jobs().filter(pk=job.pk, lease_id=job.lease_id)
    if status != 200:
        return bool(leased.update(error_status=status, error=body["error"]))
    field = "report" if job.provider == "groq" else "provider_reports"
    session = LiveSimulation.objects.select_for_update(of=("self",)).only(field).filter(
        pk=job.simulation_id, user__is_active=True,
    ).first()
    current = leased.select_for_update().first()
    if current is None:
        return False
    if session is not None:
        previous = session.report if job.provider == "groq" else session.provider_reports.get(job.provider)
        if not previous or (previous.get("scoreStatus") == "incomplete" and body.get("scoreStatus") == "scored"):
            if job.provider == "groq":
                session.report = body
            else:
                session.provider_reports[job.provider] = body
            session.save(update_fields=[field])
    current.delete()
    return session is not None


@sensitive_variables()
def _run(job):
    started = time.perf_counter()
    queue_ms = max(0, int((timezone.now() - job.queued_at).total_seconds() * 1000))
    timings = {}
    persisted_status = None
    try:
        with timed_phase(timings, "load"):
            source = _source(job)
            connections.close_all()
        with timed_phase(timings, "grading"):
            body, status = _evaluate(job, source, timings=timings)
        with timed_phase(timings, "save"):
            if _finish(job, body, status):
                persisted_status = status
    finally:
        provider = job.provider if job.provider in oral_evaluation.PROVIDER_LABELS else "unknown"
        logger.info(
            "oral evaluation provider=%s attempt=%s status=%s elapsed_ms=%d queue_ms=%d phases_ms=%s",
            provider, job.simulation_id, persisted_status or "not_saved",
            (time.perf_counter() - started) * 1000, queue_ms, timings,
        )


def _drain():
    global _runner
    owner = threading.current_thread()
    try:
        while True:
            _changed.clear()
            job, next_lease = _claim()
            if job:
                _run(job)
                continue
            connections.close_all()
            if next_lease:
                _changed.wait(max(0, (next_lease - timezone.now()).total_seconds()))
            else:
                with _lock:
                    if not _changed.is_set():
                        _runner = None
                        return
    except DatabaseError as exc:
        logger.error("Oral job queue paused error=%s", type(exc).__name__)
    finally:
        connections.close_all()
        restart = False
        with _lock:
            if _runner is owner:
                _runner = None
                restart = _changed.is_set()
        if restart:
            wake()
