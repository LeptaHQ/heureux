"""Directory timings are aggregate-only and do not touch unrelated requests."""

from unittest.mock import patch

from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from study.middleware import DirectoryTimingMiddleware


class DirectoryTimingTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_both_directories_report_app_and_database_time(self):
        def view(request):
            with connection.cursor() as cursor:
                cursor.execute("SELECT %s", ["private timing parameter"])
                cursor.fetchone()
            return HttpResponse("Directory")

        middleware = DirectoryTimingMiddleware(view)
        for path in sorted(middleware.paths):
            with self.subTest(path=path):
                with patch("study.middleware.perf_counter", side_effect=[1, 2, 3, 5]):
                    response = middleware(self.factory.get(path))
                self.assertEqual(
                    response["Server-Timing"],
                    'app;dur=4000.0, db;dur=1000.0;desc="1 queries"',
                )
                self.assertNotIn("private timing parameter", str(response.headers))
                self.assertEqual(response.content, b"Directory")

    def test_other_requests_do_not_install_database_wrappers(self):
        middleware = DirectoryTimingMiddleware(lambda request: HttpResponse())
        for path in ("/healthz", "/expression/", "/expression/orale/tache-3/sujets/1/"):
            with self.subTest(path=path):
                with patch.object(connection, "execute_wrapper") as wrapper:
                    response = middleware(self.factory.get(path))
                wrapper.assert_not_called()
                self.assertNotIn("Server-Timing", response)

    def test_existing_metrics_and_private_cache_headers_are_preserved(self):
        def view(request):
            response = HttpResponse()
            response["Server-Timing"] = "upstream;dur=12"
            response["Cache-Control"] = "private, no-store"
            return response

        response = DirectoryTimingMiddleware(view)(
            self.factory.get("/expression/orale/tache-2/sujets/"),
        )
        self.assertTrue(response["Server-Timing"].startswith("upstream;dur=12, app;dur="))
        self.assertIn('desc="0 queries"', response["Server-Timing"])
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_failed_requests_remove_the_wrapper_and_do_not_hide_errors(self):
        def view(request):
            raise RuntimeError("Directory failed")

        before = list(connection.execute_wrappers)
        with self.assertRaisesMessage(RuntimeError, "Directory failed"):
            DirectoryTimingMiddleware(view)(
                self.factory.get("/expression/orale/tache-3/sujets/"),
            )
        self.assertEqual(connection.execute_wrappers, before)
