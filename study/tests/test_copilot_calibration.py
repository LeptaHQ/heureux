import json
import time
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

from study.simulation import copilot_runtime, evaluation


@skipUnless(find_spec("copilot") is not None, "Install the optional Copilot pilot SDK.")
class CopilotCalibrationTests(SimpleTestCase):
    def setUp(self):
        self.client_factory = self.enterContext(patch("copilot.CopilotClient", autospec=True))
        self.client = self.client_factory.return_value
        self.session = self.client.create_session.return_value
        self.session.send_and_wait = AsyncMock()
        self.session.rpc.usage.get_metrics = AsyncMock(return_value=SimpleNamespace(total_nano_aiu=40_000))

    def _reply(self, content):
        from copilot.session_events import AssistantMessageData

        self.session.send_and_wait.return_value = SimpleNamespace(
            data=AssistantMessageData(content=content, message_id="fixture"),
        )

    def _request(self, deadline):
        transport = copilot_runtime.report_transport("fixture-token", "fixture-model")
        return transport(
            "copilot", "Grade the invented response.", {"response": "Bonjour Camille !"},
            {"type": "object"}, name="ee1_bilan", deadline=deadline,
        )

    def test_sends_only_the_grading_packet_and_removes_temporary_state(self):
        self._reply('{"score":12}')
        self.assertEqual(self._request(time.monotonic() + 10), {"score": 12})

        options = self.client_factory.call_args.kwargs
        runtime = options["runtime"]
        session_options = self.client.create_session.await_args.kwargs
        prompt = self.session.send_and_wait.await_args.args[0]
        self.assertEqual(json.loads(prompt), {"response": "Bonjour Camille !"})
        self.assertNotIn("fixture-token", str(session_options))
        self.assertEqual(options["mode"], "empty")
        self.assertFalse(options["github"]["use_logged_in_user"])
        self.assertFalse(session_options["enable_config_discovery"])
        self.assertEqual(session_options["tools"]["available_tools"], [])
        self.assertEqual(session_options["permissions"]["on_request"](None, None).kind, "reject")
        self.assertFalse(Path(runtime.working_directory).exists())
        self.client.force_stop.assert_awaited_once()

    def test_rejects_an_ambiguous_report_and_closes_the_runtime(self):
        self._reply('{"score":12,"score":16}')
        with self.assertRaisesMessage(evaluation.EvaluationError, "Le bilan Copilot est illisible."):
            self._request(time.monotonic() + 10)
        self.client.force_stop.assert_awaited_once()

    def test_slow_reports_log_separate_runtime_and_response_timings(self):
        self._reply('{"score":12}')
        with (
            patch.object(copilot_runtime.time, "perf_counter", side_effect=[0, 0.125, 40.125, 40.25, 40.375]),
            self.assertLogs(copilot_runtime.logger, "WARNING") as logs,
        ):
            self.assertEqual(self._request(time.monotonic() + 10), {"score": 12})
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Slow Copilot writing evaluation model=fixture-model session_ms=125 reply_ms=40000 cleanup_ms=125"],
        )

    def test_an_expired_request_never_starts_the_runtime(self):
        with self.assertRaisesMessage(evaluation.EvaluationError, "Le bilan Copilot n’est pas arrivé à temps."):
            self._request(time.monotonic() - 1)
        self.client_factory.assert_not_called()
