"""URL configuration for the flashcards project."""

from django.contrib import admin
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import include, path
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView


def healthz(request):
    """Process-liveness probe for Render — deliberately never touches the DB.

    ``study.middleware.HealthCheckMiddleware`` normally answers this path first;
    this view is the fallback when the middleware is not installed. Like the
    middleware it performs zero database work: the probe runs continuously, and
    a serverless Postgres (Neon) treats any connection as activity, so touching
    the database here would keep the compute endpoint awake permanently instead
    of letting it autosuspend. Database problems still surface on real requests.
    """
    return JsonResponse({"status": "ok"})


@never_cache
def service_worker(request):
    response = render(
        request,
        "sw.js",
        content_type="application/javascript",
    )
    response["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response["Service-Worker-Allowed"] = "/"
    return response


@never_cache
def page_not_found(request, exception):
    base_template = (
        "base.html"
        if request.user.is_authenticated
        else "study/auth/base.html"
    )
    return render(
        request,
        "404.html",
        {"base_template": base_template},
        status=404,
    )


handler404 = page_not_found


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    path(
        "sw.js",
        service_worker,
        name="service_worker",
    ),
    path(
        "manifest.webmanifest",
        TemplateView.as_view(
            template_name="manifest.webmanifest",
            content_type="application/manifest+json",
        ),
        name="manifest",
    ),
    path(
        "offline/",
        TemplateView.as_view(template_name="offline.html"),
        name="offline",
    ),
    path("", include("study.urls")),
]
