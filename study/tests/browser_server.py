from threading import Lock

from django.core.servers.basehttp import ThreadedWSGIServer
from django.test.testcases import LiveServerThread, QuietWSGIRequestHandler


class SharedConnectionWSGIServer(ThreadedWSGIServer):
    def set_app(self, application):
        lock = Lock()

        def serialized_application(environ, start_response):
            with lock:
                response = application(environ, start_response)
                try:
                    yield from response
                finally:
                    close = getattr(response, "close", None)
                    if close is not None:
                        close()

        super().set_app(serialized_application)


class BrowserLiveServerThread(LiveServerThread):
    def _create_server(self, connections_override=None):
        if connections_override:
            # Django shares in-memory SQLite connections across request threads.
            # Serialize those requests so their atomic blocks cannot interleave.
            # Keep socket handlers threaded: WebKit may open idle connections.
            return SharedConnectionWSGIServer(
                (self.host, self.port),
                QuietWSGIRequestHandler,
                allow_reuse_address=False,
                connections_override=connections_override,
            )
        return super()._create_server(connections_override=connections_override)
