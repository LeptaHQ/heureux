"""Isolated GitHub Copilot inference for simulation bilans."""

import asyncio
import json
import logging
import os
import time
from tempfile import TemporaryDirectory

from django.views.decorators.debug import sensitive_variables

from study.accounts import github_copilot

from . import evaluation

logger = logging.getLogger(__name__)

MODELS = {
    "copilot-astra": ("Astra", "gpt-6.2-astra"),
    "copilot-mai": ("MAI", "mai-code-2-flash"),
    "copilot-opus": ("Opus", "claude-opus-5.5"),
}
LABELS = {key: label for key, (label, _) in MODELS.items()}
DEFAULT = "copilot-mai"
RECONNECT = "Reconnectez votre compte GitHub pour utiliser Copilot."


@sensitive_variables()
def linked_report_transport(user_id, provider, link_id):
    try:
        token = github_copilot.access_token(user_id, link_id)
    except github_copilot.ReconnectRequired:
        raise evaluation.EvaluationError(403, RECONNECT) from None
    except github_copilot.ConnectionError:
        raise evaluation.EvaluationError(502, "La connexion à GitHub est temporairement indisponible.") from None
    return report_transport(token, MODELS[provider][1])


@sensitive_variables()
async def _request_report(token, model, instruction, packet, schema, deadline, *, measure):
    from copilot import CopilotClient, JsonRpcError, RuntimeConnection
    from copilot.rpc import PermissionDecisionReject
    from copilot.session_events import AssistantMessageData

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    started = time.perf_counter()
    session_ready = reply_received = None
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
                session_ready = time.perf_counter()
                reply = await session.send_and_wait(
                    json.dumps(packet, ensure_ascii=False, separators=(",", ":")),
                    response_schema=schema,
                    timeout=max(0, deadline - time.monotonic()),
                )
                reply_received = time.perf_counter()
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
            stopping = time.perf_counter()
            await client.force_stop()
            stopped = time.perf_counter()
            if stopped - started >= evaluation._SLOW_SECONDS:
                session_ready = session_ready if session_ready is not None else stopping
                reply_received = reply_received if reply_received is not None else stopping
                logger.warning(
                    "Slow Copilot evaluation model=%s session_ms=%d reply_ms=%d cleanup_ms=%d",
                    model, (session_ready - started) * 1000, (reply_received - session_ready) * 1000,
                    (stopped - stopping) * 1000,
                )


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
