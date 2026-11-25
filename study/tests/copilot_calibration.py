"""Copilot transport for the synthetic EE1 calibration only."""

import asyncio
import json
import logging
import os
import time
from tempfile import TemporaryDirectory

from study.simulation import evaluation


async def _request_report(token, model, instruction, packet, schema, deadline):
    from copilot import CopilotClient, JsonRpcError, RuntimeConnection
    from copilot.rpc import PermissionDecisionReject
    from copilot.session_events import AssistantMessageData

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    with TemporaryDirectory(prefix="heureux-copilot-pilot-") as directory:
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
                if deadline - time.monotonic() > 1:
                    try:
                        credits = (await session.rpc.usage.get_metrics(timeout=1)).total_nano_aiu
                    except (JsonRpcError, TimeoutError):
                        pass
                return report, credits
        finally:
            await client.force_stop()


def report_transport(token, model):
    from copilot import JsonRpcError

    def request_report(provider, instruction, packet, schema, *, name, deadline, **_):
        started = time.monotonic()
        sdk_logger = logging.getLogger("copilot")
        previous_level = sdk_logger.level
        # SDK diagnostics can include raw service errors. Keep only the messages below.
        sdk_logger.setLevel(logging.CRITICAL + 1)
        try:
            report, nano_credits = asyncio.run(_request_report(token, model, instruction, packet, schema, deadline))
        except TimeoutError:
            raise evaluation.EvaluationError(504, "Copilot pilot timed out.") from None
        except (ValueError, RecursionError):
            raise evaluation.EvaluationError(502, "Copilot pilot returned an unreadable report.") from None
        except (JsonRpcError, OSError, RuntimeError) as exc:
            raise evaluation.EvaluationError(
                502, f"Copilot pilot request failed ({type(exc).__name__}). Check authentication and model access.",
            ) from None
        finally:
            sdk_logger.setLevel(previous_level)
        usage = "credits not reported" if nano_credits is None else f"{nano_credits / 1e9:.4f} AI credits"
        print(f"{provider} {name}: {time.monotonic() - started:.1f} s · {usage}")
        return report

    return request_report
