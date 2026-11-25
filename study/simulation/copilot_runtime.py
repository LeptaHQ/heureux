"""Isolated GitHub Copilot inference for writing bilans."""

import asyncio
import json
import os
import time
from contextlib import contextmanager
from tempfile import TemporaryDirectory, gettempdir

from django.conf import settings
from django.views.decorators.debug import sensitive_variables

from . import evaluation

MODELS = {
    "copilot-astra": ("Astra", "gpt-6.2-astra"),
    "copilot-mai": ("MAI", "mai-code-2-flash"),
    "copilot-opus": ("Opus", "claude-opus-5.5"),
}
LABELS = {key: label for key, (label, _) in MODELS.items()}
DEFAULT = "copilot-mai"


@contextmanager
def evaluation_slot():
    if not settings.ON_RENDER:
        yield
        return

    import fcntl

    path = os.path.join(gettempdir(), "heureux-copilot-evaluation.lock")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "r+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise evaluation.EvaluationError(
                503, "Un bilan Copilot est déjà en cours. Réessayez dans un instant.",
            ) from None
        yield


@sensitive_variables()
async def _request_report(token, model, instruction, packet, schema, deadline, *, measure):
    from copilot import CopilotClient, JsonRpcError, RuntimeConnection
    from copilot.rpc import PermissionDecisionReject
    from copilot.session_events import AssistantMessageData

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    with TemporaryDirectory(prefix="heureux-copilot-") as directory:
        runtime = RuntimeConnection.for_spawned_stdio(
            base_directory=directory,
            working_directory=directory,
            env={"PATH": os.defpath, "HOME": directory, "COPILOT_TELEMETRY_DISABLED": "true"},
        )
        client = CopilotClient(
            mode="empty", runtime=runtime, github={"token": token, "use_logged_in_user": False},
        )
        try:
            async with asyncio.timeout(remaining):
                session = await client.create_session(
                    model=model,
                    system_message={"mode": "append", "content": instruction},
                    enable_config_discovery=False,
                    instructions={"skip_custom_instructions": True},
                    git={"enable_host_git_operations": False},
                    tools={"available_tools": []},
                    permissions={"on_request": lambda *_: PermissionDecisionReject()},
                    github={"telemetry_enabled": False},
                )
                reply = await session.send_and_wait(
                    json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                    response_schema=schema,
                    timeout=max(0, deadline - time.monotonic()),
                )
                if reply is None or not isinstance(reply.data, AssistantMessageData):
                    raise ValueError
                content = reply.data.content
                if len(content.encode()) > evaluation._MAX_RESPONSE:
                    raise ValueError
                report = json.loads(content, object_pairs_hook=evaluation.unique_fields)
                if not isinstance(report, dict):
                    raise ValueError
                credits = None
                if measure and deadline - time.monotonic() > 1:
                    try:
                        credits = (await session.rpc.usage.get_metrics(timeout=1)).total_nano_aiu
                    except (JsonRpcError, TimeoutError):
                        pass
                return report, credits
        finally:
            await client.force_stop()


@sensitive_variables()
def report_transport(token, model, *, measure=False):
    from copilot import JsonRpcError

    @sensitive_variables()
    def request_report(provider, instruction, packet, schema, *, name, deadline, **_):
        started = time.monotonic()
        try:
            report, nano_credits = asyncio.run(
                _request_report(token, model, instruction, packet, schema, deadline, measure=measure),
            )
        except TimeoutError:
            raise evaluation.EvaluationError(504, "Le bilan Copilot n’est pas arrivé à temps.") from None
        except (ValueError, RecursionError):
            raise evaluation.EvaluationError(502, "Le bilan Copilot est illisible.") from None
        except (JsonRpcError, OSError, RuntimeError):
            raise evaluation.EvaluationError(
                502, "Ce modèle Copilot n’a pas répondu. Vérifiez la connexion GitHub et l’accès au modèle.",
            ) from None
        if measure:
            usage = "credits not reported" if nano_credits is None else f"{nano_credits / 1e9:.4f} AI credits"
            print(f"{provider} {name}: {time.monotonic() - started:.1f} s · {usage}")
        return report

    return request_report
