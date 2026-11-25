"""GitHub App user authorization and encrypted Copilot credentials."""

import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from study.models import GitHubCopilotConnection

logger = logging.getLogger(__name__)
AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_USER_URL = "https://api.github.com/user"


class ConnectionError(Exception):
    pass


class ReconnectRequired(ConnectionError):
    pass


@dataclass(frozen=True, repr=False)
class Configuration:
    client_id: str
    client_secret: str
    callback_url: str
    cipher: Fernet


@sensitive_variables()
def configuration():
    client_id = settings.COPILOT_GITHUB_CLIENT_ID
    client_secret = settings.COPILOT_GITHUB_CLIENT_SECRET
    callback = settings.COPILOT_GITHUB_CALLBACK_URL
    key = settings.COPILOT_TOKEN_ENCRYPTION_KEY
    if not any((client_id, client_secret, callback, key)):
        return None
    try:
        url = urlsplit(callback)
        local = settings.DEBUG and url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
        if (
            not all((client_id, client_secret, url.hostname, key))
            or not (url.scheme == "https" or local)
            or url.username is not None or url.query or url.fragment
        ):
            raise ValueError
        return Configuration(client_id, client_secret, callback, Fernet(key))
    except ValueError:
        logger.error("Copilot linking disabled: invalid GitHub App settings")
        return None


def links_for(user):
    return GitHubCopilotConnection.objects.filter(user=user)


def link_status(request):
    if not hasattr(request, "_github_copilot_link"):
        request._github_copilot_link = links_for(request.user).values_list("pk", "refresh_expires_at").first()
    return request._github_copilot_link


def active_link_id(request):
    if configuration() is None:
        return None
    link = link_status(request)
    return link[0] if link and link[1] > timezone.now() else None


@sensitive_variables()
def _exchange(config, **grant):
    try:
        response = httpx.post(
            _TOKEN_URL,
            data={"client_id": config.client_id, "client_secret": config.client_secret, **grant},
            headers={"Accept": "application/json"},
            timeout=8,
            trust_env=False,
        )
        data = response.json()
    except (httpx.RequestError, ValueError):
        raise ConnectionError from None
    if not isinstance(data, dict):
        raise ConnectionError
    if data.get("error") == "bad_refresh_token":
        raise ReconnectRequired
    if not response.is_success or "error" in data:
        raise ConnectionError
    access, refresh = data.get("access_token"), data.get("refresh_token")
    expires, refresh_expires = data.get("expires_in"), data.get("refresh_token_expires_in")
    if not (
        isinstance(access, str) and access.startswith("ghu_") and 4 < len(access) <= 1024
        and isinstance(refresh, str) and refresh.startswith("ghr_") and 4 < len(refresh) <= 1024
        and type(expires) is int and 0 < expires <= 86400
        and type(refresh_expires) is int and 0 < refresh_expires <= 366 * 86400
    ):
        raise ConnectionError
    return access, refresh, expires, refresh_expires


@sensitive_variables()
def _github_id(access):
    try:
        response = httpx.get(
            _USER_URL, headers={"Authorization": f"Bearer {access}", "Accept": "application/vnd.github+json"},
            timeout=8, trust_env=False,
        )
        response.raise_for_status()
        github_id = response.json()["id"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise ConnectionError from None
    if type(github_id) is not int or not 0 < github_id < 2**63:
        raise ConnectionError
    return github_id


@sensitive_variables()
def _encrypted_fields(config, credentials):
    access, refresh, expires, refresh_expires = credentials
    now = timezone.now()
    return {
        "encrypted_tokens": config.cipher.encrypt(json.dumps([access, refresh]).encode()),
        "access_expires_at": now + timedelta(seconds=expires),
        "refresh_expires_at": now + timedelta(seconds=refresh_expires),
    }


@sensitive_variables()
def connect(user, config, code, verifier):
    credentials = _exchange(config, code=code, code_verifier=verifier, redirect_uri=config.callback_url)
    github_id = _github_id(credentials[0])
    fields = _encrypted_fields(config, credentials)
    with transaction.atomic():
        connection, created = links_for(user).select_for_update().get_or_create(
            user=user, defaults={"github_user_id": github_id, **fields},
        )
        if not created:
            if connection.github_user_id != github_id:
                return False
            links_for(user).update(**fields)
    return True


@sensitive_variables()
def access_token(user_id, link_id):
    config = configuration()
    if config is None:
        raise ReconnectRequired
    with transaction.atomic():
        link = GitHubCopilotConnection.objects.select_for_update().filter(pk=link_id, user_id=user_id).first()
        now = timezone.now()
        if not link or link.refresh_expires_at <= now:
            raise ReconnectRequired
        try:
            access, refresh = json.loads(config.cipher.decrypt(bytes(link.encrypted_tokens)))
        except (InvalidToken, ValueError):
            raise ReconnectRequired from None
        if link.access_expires_at > now + timedelta(minutes=5):
            return access
        try:
            credentials = _exchange(config, grant_type="refresh_token", refresh_token=refresh)
        except ReconnectRequired:
            link.delete()
        else:
            fields = _encrypted_fields(config, credentials)
            for name, value in fields.items():
                setattr(link, name, value)
            link.save(update_fields=fields)
            return credentials[0]
    raise ReconnectRequired
