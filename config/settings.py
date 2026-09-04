"""
Django settings for the EO T3 flashcards app.

Multi-user French-expression study tool. Configuration is driven by environment
variables so the same code runs locally and in production.
"""

from pathlib import Path
import os

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load a local .env file if present (never committed).
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"{name} must be a non-negative integer."
        ) from exc
    if value < 0:
        raise ImproperlyConfigured(f"{name} must be a non-negative integer.")
    return value


def default_conn_max_age(*, on_vercel: bool, on_render: bool) -> int:
    """Seconds a database connection may be reused, per platform.

    Serverless functions (Vercel) can be frozen or recycled between invocations,
    so persistent connections provide little value and can hold scarce slots
    open. Long-lived gunicorn workers (Render) do reuse connections, but a short
    lifetime still lets the database go idle between bursts of traffic. Locally
    the database is free, so keep connections for the full ten minutes.
    """
    if on_vercel:
        return 0
    if on_render:
        return 60
    return 600


def default_conn_health_checks(*, on_vercel: bool) -> bool:
    """Health checks only pay off when connections are actually reused."""
    return not on_vercel


def is_pooled_db_host(host: str) -> bool:
    """True for a Neon pooled endpoint (``...-pooler...``), served by PgBouncer."""
    return "-pooler" in (host or "").lower()


SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "dev-insecure-key-change-me-in-production-0123456789abcdef",
)

DEBUG = env_bool("DEBUG", True)

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0,[::1]")

CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Only enable this when every request reaches Django through a trusted proxy
# that appends the connecting client address to X-Forwarded-For.
TRUST_X_FORWARDED_FOR = env_bool("TRUST_X_FORWARDED_FOR", False)
TRUSTED_PROXY_CIDRS = env_list("TRUSTED_PROXY_CIDRS")

# Render provides the public hostname at runtime — trust it automatically so
# the app works without manually listing the *.onrender.com domain.
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")

# Which platform is serving this process. Vercel runs the app as a short-lived
# serverless function, Render as a long-lived gunicorn worker; their database
# connection defaults differ accordingly.
ON_VERCEL = env_bool("VERCEL") or bool(os.environ.get("VERCEL_ENV"))
ON_RENDER = bool(
    env_bool("RENDER")
    or os.environ.get("RENDER_SERVICE_ID")
    or RENDER_EXTERNAL_HOSTNAME
)

if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

# Trust any *.onrender.com subdomain too, so the default Render domain keeps
# working even if RENDER_EXTERNAL_HOSTNAME is not injected for some reason.
if ".onrender.com" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".onrender.com")
if "https://*.onrender.com" not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append("https://*.onrender.com")

# Vercel provides exact deployment and project hostnames at runtime. Trust each
# generated hostname without opening the app to every *.vercel.app project.
for _vercel_host in {
    os.environ.get("VERCEL_URL"),
    os.environ.get("VERCEL_BRANCH_URL"),
    os.environ.get("VERCEL_PROJECT_PRODUCTION_URL"),
}:
    if not _vercel_host:
        continue
    _vercel_host = _vercel_host.strip()
    if _vercel_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_vercel_host)
    _vercel_origin = f"https://{_vercel_host}"
    if _vercel_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_vercel_origin)

# Custom production domain(s). Render serves the app on both the apex and the
# www subdomain (www.heureux.lepta.app is the primary URL), so trust both. Add
# more via the CUSTOM_DOMAINS env var (comma-separated apex domains).
CUSTOM_DOMAINS = ["heureux.lepta.app", *env_list("CUSTOM_DOMAINS")]
for _domain in CUSTOM_DOMAINS:
    _domain = _domain.strip().lstrip(".")
    if not _domain:
        continue
    for _host in (_domain, f"www.{_domain}"):
        if _host not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(_host)
        _origin = f"https://{_host}"
        if _origin not in CSRF_TRUSTED_ORIGINS:
            CSRF_TRUSTED_ORIGINS.append(_origin)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "study",
]

MIDDLEWARE = [
    "study.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "study.middleware.SecurityHeadersMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "study.middleware.AuthenticationRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "study.context_processors.study_globals",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database — PostgreSQL in production (via DATABASE_URL), SQLite for local dev.
# Set DATABASE_URL (e.g. postgres://user:pass@host:5432/dbname) in production and
# Django will use PostgreSQL automatically; without it, a local SQLite file is used.
_db_url = (
    os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""
).strip()
_sqlite_path = os.environ.get("DATABASE_PATH", BASE_DIR / "db.sqlite3")

# A serverless Postgres (Neon) bills compute for the time its endpoint stays
# awake, so connections are kept only as long as they are genuinely reused.
DB_CONN_MAX_AGE = env_int(
    "DB_CONN_MAX_AGE",
    default_conn_max_age(on_vercel=ON_VERCEL, on_render=ON_RENDER),
)
DB_CONN_HEALTH_CHECKS = env_bool(
    "DB_CONN_HEALTH_CHECKS",
    default_conn_health_checks(on_vercel=ON_VERCEL),
)

_db_config = dj_database_url.parse(
    _db_url or f"sqlite:///{_sqlite_path}",
    conn_max_age=DB_CONN_MAX_AGE,
    conn_health_checks=DB_CONN_HEALTH_CHECKS,
)

# Neon's pooled endpoint (``...-pooler...``) is PgBouncer in transaction mode,
# which cannot hold a server-side cursor open across statements. Detect it from
# the parsed host so the connection URL is never rewritten or exposed.
DB_IS_POOLED = is_pooled_db_host(_db_config.get("HOST", ""))
_db_config["DISABLE_SERVER_SIDE_CURSORS"] = env_bool(
    "DB_DISABLE_SERVER_SIDE_CURSORS",
    DB_IS_POOLED,
)

DATABASES = {"default": _db_config}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "fr"

TIME_ZONE = os.environ.get("TIME_ZONE", "America/Los_Angeles")

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
_staticfiles_backend = (
    "django.contrib.staticfiles.storage.StaticFilesStorage"
    if DEBUG
    else "whitenoise.storage.CompressedManifestStaticFilesStorage"
)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": _staticfiles_backend},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/compte/connexion/"

# Server-side translation fallback for browsers without the on-device
# Translator API (every mobile browser today). Disabled unless a
# LibreTranslate-compatible endpoint is configured, so no selected text
# ever leaves this server by default.
TRANSLATION_API_URL = os.environ.get("TRANSLATION_API_URL", "").strip()
TRANSLATION_API_KEY = os.environ.get("TRANSLATION_API_KEY", "").strip()
TRANSLATION_TIMEOUT = float(os.environ.get("TRANSLATION_TIMEOUT", "8"))

_csp_directives = [
    "default-src 'self'",
    "base-uri 'self'",
    "connect-src 'self'",
    "font-src 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "img-src 'self' data:",
    "manifest-src 'self'",
    "object-src 'none'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "worker-src 'self'",
]
if not DEBUG:
    _csp_directives.append("upgrade-insecure-requests")
CONTENT_SECURITY_POLICY = "; ".join(_csp_directives)

# Security hardening — enabled automatically when DEBUG is off.
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    # Render's platform health check hits the service over the private network
    # with plain HTTP (no X-Forwarded-Proto), so the HTTPS redirect must never
    # apply to /healthz — otherwise SecurityMiddleware calls get_host() on an
    # internal Host it can't validate and returns HTTP 400, failing the probe.
    SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "2592000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
