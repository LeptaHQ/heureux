from unittest.mock import Mock, patch, sentinel

from django.core.servers.basehttp import ThreadedWSGIServer
from django.test import SimpleTestCase
from django.test.testcases import QuietWSGIRequestHandler

from .browser_server import BrowserLiveServerThread, SharedConnectionWSGIServer


class BrowserLiveServerTests(SimpleTestCase):
    def make_thread(self, connections_override):
        return BrowserLiveServerThread(
            "localhost",
            sentinel.static_handler,
            connections_override=connections_override,
        )

    def test_shared_sqlite_connection_serializes_application_work(self):
        connections_override = {"default": sentinel.shared_sqlite_connection}
        thread = self.make_thread(connections_override)
        with (
            patch("study.tests.browser_server.SharedConnectionWSGIServer") as serialized_server,
            patch.object(BrowserLiveServerThread, "server_class") as threaded_server,
        ):
            server = thread._create_server(connections_override)

        self.assertIs(server, serialized_server.return_value)
        serialized_server.assert_called_once_with(
            ("localhost", 0),
            QuietWSGIRequestHandler,
            allow_reuse_address=False,
            connections_override=connections_override,
        )
        threaded_server.assert_not_called()

    def test_independent_connections_keep_the_threaded_server(self):
        thread = self.make_thread({})
        with (
            patch("study.tests.browser_server.SharedConnectionWSGIServer") as serialized_server,
            patch.object(BrowserLiveServerThread, "server_class") as threaded_server,
        ):
            server = thread._create_server({})

        self.assertIs(server, threaded_server.return_value)
        threaded_server.assert_called_once_with(
            ("localhost", 0),
            QuietWSGIRequestHandler,
            allow_reuse_address=False,
            connections_override={},
        )
        serialized_server.assert_not_called()

    def test_shared_server_keeps_socket_handlers_threaded(self):
        self.assertTrue(issubclass(SharedConnectionWSGIServer, ThreadedWSGIServer))

    def test_application_iteration_and_close_hold_the_same_lock(self):
        for disconnect in (False, True):
            with self.subTest(disconnect=disconnect):
                calls = []

                class Response:
                    def __iter__(self):
                        calls.append("iterate")
                        yield b"first"
                        yield b"second"

                    def close(self):
                        calls.append("close")

                def application(environ, start_response):
                    calls.append("application")
                    return Response()

                server = object.__new__(SharedConnectionWSGIServer)
                with patch("study.tests.browser_server.Lock") as lock:
                    lock.return_value.__enter__.side_effect = lambda: calls.append("enter")
                    lock.return_value.__exit__.side_effect = lambda *args: calls.append("exit")
                    server.set_app(application)
                response = server.get_app()({}, Mock())
                self.assertEqual(calls, [])
                if disconnect:
                    self.assertEqual(next(response), b"first")
                    response.close()
                else:
                    self.assertEqual(list(response), [b"first", b"second"])
                self.assertEqual(
                    calls, ["enter", "application", "iterate", "close", "exit"],
                )
