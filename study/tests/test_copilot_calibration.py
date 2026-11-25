import json
import time
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import AsyncMock, Mock, patch

from django.test import SimpleTestCase

from study.simulation import copilot_runtime, evaluation


@skipUnless(find_spec("copilot") is not None, "Install the optional Copilot pilot SDK.")
class CopilotCalibrationTests(SimpleTestCase):
    def setUp(self):
        self.client_factory = self.enterContext(patch("copilot.CopilotClient", autospec=True))
        self.client = self.client_factory.return_value
        self.session = self.client.create_session.return_value
        self.session.on = Mock()
        self.session.send_and_wait = AsyncMock()
        self.session.rpc.usage.get_metrics = AsyncMock(return_value=SimpleNamespace(total_nano_aiu=40_000))

    def _reply(self, content):
        from copilot.session_events import AssistantMessageData

        self.session.send_and_wait.return_value = SimpleNamespace(
            data=AssistantMessageData(content=content, message_id="fixture"),
        )

    def _request(self, deadline, *, timings=None):
        transport = copilot_runtime.report_transport("fixture-token", "fixture-model", timings=timings)
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
        timings = {}
        with self.assertRaisesMessage(evaluation.EvaluationError, "Le bilan Copilot est illisible."):
            self._request(time.monotonic() + 10, timings=timings)
        self.client.force_stop.assert_awaited_once()
        self.assertIn("cleanup", timings)

    def test_slow_reports_log_separate_runtime_and_response_timings(self):
        self._reply('{"score":12}')
        timings = {}
        with (
            patch.object(
                copilot_runtime.time, "perf_counter",
                side_effect=[0, 0.25, 0.5, 0.5, 0.5625, 0.5625, 0.625, 0.625, 40.625, 40.75, 40.875],
            ),
            self.assertLogs(copilot_runtime.logger, "WARNING") as logs,
        ):
            self.assertEqual(self._request(time.monotonic() + 10, timings=timings), {"score": 12})
        self.assertEqual(timings, {
            "sdk_import": 250, "runtime_start": 62, "session_create": 62,
            "session": 125, "reply": 40000, "decode": 125, "cleanup": 125,
        })
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Slow Copilot evaluation model=fixture-model session_ms=125 reply_ms=40000 cleanup_ms=125"],
        )

    def test_trace_distinguishes_output_from_completion_on_timeout(self):
        from copilot.session_events import SessionEventType

        timings = {}

        async def send(*args, **kwargs):
            observe = self.session.on.call_args.args[0]
            for seconds, kind, agent_id in (
                (1, SessionEventType.USER_MESSAGE, None),
                (2, SessionEventType.MODEL_CALL_START, None),
                (3, SessionEventType.ASSISTANT_MESSAGE_DELTA, "other-agent"),
                (4, SessionEventType.ASSISTANT_MESSAGE_DELTA, None),
                (5, SessionEventType.ASSISTANT_MESSAGE_DELTA, None),
                (6, SessionEventType.MODEL_CALL_FINISHED, None),
                (7, SessionEventType.ASSISTANT_MESSAGE, None),
                (8, SessionEventType.ASSISTANT_TURN_END, None),
            ):
                clock.return_value = seconds
                observe(SimpleNamespace(type=kind, agent_id=agent_id, data="private event data"))
            clock.return_value = 10
            raise TimeoutError

        self.session.send_and_wait.side_effect = send
        with patch.object(copilot_runtime.time, "perf_counter", return_value=0) as clock:
            with self.assertRaisesMessage(evaluation.EvaluationError, "Le bilan Copilot n’est pas arrivé à temps."):
                self._request(time.monotonic() + 10, timings=timings)

        self.assertEqual(
            {key: value for key, value in timings.items() if key.endswith("_at")},
            {"sdk_message_at": 1000, "model_start_at": 2000, "first_output_at": 4000,
             "model_finish_at": 6000, "message_at": 7000, "turn_end_at": 8000},
        )
        self.assertEqual(timings["reply"], 10_000)
        self.assertTrue(all(isinstance(value, int) for value in timings.values()))
        self.session.on.return_value.assert_called_once_with()
        self.client.force_stop.assert_awaited_once()

    def test_runtime_start_timeout_never_creates_a_session(self):
        self.client.start.side_effect = TimeoutError
        timings = {}
        with self.assertRaisesMessage(evaluation.EvaluationError, "Le bilan Copilot n’est pas arrivé à temps."):
            self._request(time.monotonic() + 10, timings=timings)
        self.assertIn("runtime_start", timings)
        self.assertNotIn("session_create", timings)
        self.client.create_session.assert_not_awaited()
        self.client.force_stop.assert_awaited_once()

    def test_an_expired_request_never_starts_the_runtime(self):
        with self.assertRaisesMessage(evaluation.EvaluationError, "Le bilan Copilot n’est pas arrivé à temps."):
            self._request(time.monotonic() - 1)
        self.client_factory.assert_not_called()
