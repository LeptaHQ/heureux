"""Custom middleware for the flashcards project."""

from __future__ import annotations

from time import perf_counter

from django.db import connection
from django.http import JsonResponse
from django.contrib.auth.views import redirect_to_login
from django.conf import settings
from django.urls import Resolver404, resolve
from django.utils.cache import patch_cache_control

HEALTH_CHECK_PATH = "/healthz"


class DirectoryTimingMiddleware:
    """Expose aggregate request timings for the two oral subject directories."""

    paths = {
        "/expression/orale/tache-2/sujets/",
        "/expression/orale/tache-3/sujets/",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info not in self.paths:
            return self.get_response(request)
        query_count = 0
        query_seconds = 0.0

        def timed_execute(execute, sql, params, many, context):
            nonlocal query_count, query_seconds
            query_count += 1
            started = perf_counter()
            try:
                return execute(sql, params, many, context)
            finally:
                query_seconds += perf_counter() - started

        started = perf_counter()
        with connection.execute_wrapper(timed_execute):
            response = self.get_response(request)
        timing = (
            f"app;dur={(perf_counter() - started) * 1000:.1f}, "
            f'db;dur={query_seconds * 1000:.1f};desc="{query_count} queries"'
        )
        previous = response.get("Server-Timing")
        response["Server-Timing"] = f"{previous}, {timing}" if previous else timing
        return response


class HealthCheckMiddleware:
    """Answer the platform liveness probe before any host/SSL processing.

    Render performs its health check over the private network with plain HTTP
    and a Host header we cannot predict (often an internal IP). Django's normal
    request path validates that Host — in ``SecurityMiddleware`` (HTTPS redirect)
    and unconditionally in ``CommonMiddleware`` (the ``PREPEND_WWW`` check) — and
    rejects an unknown Host with HTTP 400, so the probe never turns healthy.

    By sitting first in ``MIDDLEWARE`` and matching on ``request.path`` (which is
    derived from ``PATH_INFO`` and never touches the Host header), we short-
    circuit ``/healthz`` to a 200 without weakening ``ALLOWED_HOSTS`` for any real
    traffic.

    This probe is deliberately **process liveness only**: it must never open or
    touch a database connection. Render polls it continuously, and a serverless
    Postgres (Neon) counts every connection as activity, so a DB-touching probe
    keeps the compute endpoint awake forever and burns the whole compute quota.
    Answering without the database lets Neon autosuspend after its idle window;
    real authenticated requests still surface database failures normally.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == HEALTH_CHECK_PATH:
            return JsonResponse({"status": "ok"})
        return self.get_response(request)


class SecurityHeadersMiddleware:
    """Apply the app's CSP and browser capability policy to every real page."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault(
            "Content-Security-Policy",
            settings.CONTENT_SECURITY_POLICY,
        )
        response.setdefault(
            "Permissions-Policy",
            "camera=(), geolocation=(), microphone=(), payment=(), "
            "usb=(), clipboard-read=(self), clipboard-write=(self)",
        )
        return response


class AuthenticationRequiredMiddleware:
    """Require an authenticated account for every private study surface."""

    public_paths = {
        "/compte/connexion/",
        "/compte/inscription/",
        "/compte/recuperation/",
        "/healthz",
        "/manifest.webmanifest",
        "/sw.js",
        "/offline/",
    }
    public_prefixes = ("/admin/", "/static/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_public = request.path in self.public_paths or request.path.startswith(
            self.public_prefixes
        )
        if request.user.is_authenticated:
            response = self.get_response(request)
            patch_cache_control(response, private=True, no_store=True)
            return response
        if is_public:
            return self.get_response(request)
        try:
            resolve(request.path_info)
        except Resolver404:
            response = self.get_response(request)
            patch_cache_control(response, private=True, no_store=True)
            return response
        login_target = (
            "/revision/"
            if request.path.startswith("/revision/")
            else request.get_full_path()
        )
        login_redirect = redirect_to_login(login_target)
        patch_cache_control(login_redirect, private=True, no_store=True)
        if request.path.startswith("/revision/") and request.headers.get(
            "X-Requested-With"
        ):
            response = JsonResponse(
                {
                    "error": "Votre session a expiré. Reconnectez-vous.",
                    "login_url": login_redirect.url,
                },
                status=401,
            )
            patch_cache_control(response, private=True, no_store=True)
            return response
        return login_redirect
