"""Provider transport and response decoding shared by simulation graders."""

import json
import logging
import random
import re
import socket
import threading
import time
from contextlib import closing, contextmanager
from http.client import HTTPException, HTTPSConnection

from django.conf import settings
from django.views.decorators.debug import sensitive_variables

MODEL = "openai/gpt-oss-120b"
QWEN_MODEL = "qwen/qwen3.8-27b"
_GEMINI_MODEL = "gemini-3.8-flash"
_WORKERS_MODEL = "@cf/google/gemma-4-26b-a4b-it"
PROVIDER_LABELS = {"groq": "Groq", "gemini": "Gemini", "cloudflare": "Workers"}
DEADLINE_SECONDS = 180
REFRESH_FAILED = "Le bilan n’a pas pu être actualisé. Votre bilan enregistré reste disponible."
_MAX_RESPONSE = 64_000
_RETRY_MIN_SECONDS = 30
_SLOW_SECONDS = 30
_UNREADABLE = "Le bilan est illisible. Vous pouvez réessayer."
_WORKERS_ERROR_CODES = {"3007", "3008", "3036", "3040"}
_LOGGABLE_PROVIDER_CODES = {
    "internal_server_error", "invalid_request_error", "json_validate_failed", "permission_denied",
    "rate_limit_exceeded", "resource_exhausted", "unauthenticated", "unavailable",
} | _WORKERS_ERROR_CODES
logger = logging.getLogger(__name__)


class EvaluationError(Exception):
    def __init__(self, status, message, *, retry=False, schema_rejected=False, retry_after=None):
        self.status, self.retry = status, retry
        self.schema_rejected = schema_rejected
        self.retry_after = retry_after
        super().__init__(message)


def is_older_report(report, grader_version):
    if not report or type(grader_version) is not int:
        return False
    version = report.get("graderVersion")
    return version is None or (type(version) is int and version < grader_version)


@contextmanager
def timed_phase(timings, phase):
    if timings is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        timings[phase] = int((time.perf_counter() - started) * 1000)


def unique_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError
    return result


def checked_text(value, limit, *, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError
    value.encode("utf-8")
    return value


def _provider_error_code(raw, *, service=""):
    try:
        reply = json.loads(raw)
        error = reply.get("error") or (reply.get("errors") or [{}])[0]
        code = error.get("code")
        if service == "Cloudflare" and type(code) in (int, str) and str(code) in _WORKERS_ERROR_CODES:
            return str(code)
        if not isinstance(code, str) or not code:
            code = error.get("status") or error.get("type")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError):
        return ""
    return code.lower() if isinstance(code, str) and re.fullmatch(r"[A-Za-z_]{1,40}", code) else ""


def _cut(sock, late):
    late.set()
    try:
        # SSLSocket.shutdown would drop TLS state under the reading thread.
        socket.socket.shutdown(sock, socket.SHUT_RDWR)
    except OSError:
        pass


@sensitive_variables()
def _post(payload, deadline, *, host, path, auth, service):
    started = time.monotonic()
    if started >= deadline:
        raise EvaluationError(504, "Le délai du bilan est écoulé. Votre travail reste disponible.")
    late, timer = threading.Event(), None
    try:
        with closing(HTTPSConnection(host, timeout=deadline - started)) as conn:
            conn.request("POST", path, body=payload, headers={"Content-Type": "application/json", **auth})
            sock = conn.sock  # getresponse() can hand the socket over to the response.
            # A trickling reply must not keep renewing the read timeout.
            timer = threading.Timer(max(0, deadline - time.monotonic()), _cut, (sock, late))
            timer.daemon = True
            timer.start()
            with conn.getresponse() as resp:
                if resp.status == 200:
                    body = resp.read(_MAX_RESPONSE + 1)
                    if late.is_set():
                        raise TimeoutError
                    if len(body) > _MAX_RESPONSE:
                        raise EvaluationError(502, _UNREADABLE)
                    return body, time.monotonic() - started
                provider = _provider_error_code(resp.read(16_000), service=service)
                wait = resp.getheader("retry-after") or ""
    except (OSError, HTTPException) as exc:
        elapsed = time.monotonic() - started
        if not (isinstance(exc, TimeoutError) or late.is_set()):
            logger.warning("%s evaluation: connection %s after %.0f s", service, type(exc).__name__, elapsed)
            raise EvaluationError(503, "Le service de bilan est inaccessible. Votre travail reste disponible.",
                                  retry=True) from None
        logger.warning("%s evaluation: no report after %.0f s", service, elapsed)
        raise EvaluationError(504, f"Le bilan n’est pas arrivé à temps (arrêt à {elapsed:.0f} s). "
                                   "Votre travail reste disponible.") from None
    finally:
        if timer is not None:
            timer.cancel()
    logger.warning("%s evaluation: provider HTTP %d %s", service, resp.status,
                   provider if provider in _LOGGABLE_PROVIDER_CODES else "-")
    code = f"HTTP {resp.status} {provider}".strip()
    wait_seconds = int(wait) if service == "Cloudflare" and re.fullmatch(r"\d{1,5}", wait) else None
    # Do not bypass Retry-After dates or other values we cannot safely interpret.
    retry_workers = (
        service == "Cloudflare"
        and (resp.status, provider) in {(408, "3007"), (408, "3008"), (429, "3040")}
        and (not wait or wait_seconds is not None)
    )
    retry_after = (wait_seconds or 0) if retry_workers else None
    if resp.status == 429:
        later = f" Réessayez dans {wait} s." if re.fullmatch(r"\d{1,5}", wait) else ""
        raise EvaluationError(429, f"Limite de demandes de bilan atteinte ({code}).{later} Votre travail reste disponible.",
                              retry=retry_workers, retry_after=retry_after)
    if resp.status >= 500 or retry_workers:
        raise EvaluationError(502, f"Le bilan est momentanément indisponible ({code}). Votre travail reste disponible.",
                              retry=True, retry_after=retry_after)
    raise EvaluationError(
        502, f"La demande de bilan a été refusée ({code}). Votre travail reste disponible.",
        schema_rejected=service == "Groq" and resp.status == 400 and provider == "json_validate_failed",
    )


@sensitive_variables()
def _request_with_retry(payload, *, host, path, auth, service, retry_schema=False, deadline=None):
    if deadline is None:
        deadline = time.monotonic() + DEADLINE_SECONDS

    def send():
        return _post(
            json.dumps(payload, ensure_ascii=False).encode(), deadline,
            host=host, path=path, auth=auth, service=service,
        )

    try:
        return send()
    except EvaluationError as exc:
        retry_json = retry_schema and exc.schema_rejected
        if not (exc.retry or retry_json) or deadline - time.monotonic() < _RETRY_MIN_SECONDS:
            raise
        if retry_json:
            schema = payload["response_format"]["json_schema"]["schema"]
            payload["response_format"] = {"type": "json_object"}
            payload["messages"][0]["content"] += "\nJSON schema: " + json.dumps(schema, separators=(",", ":"))
        else:
            delay = max(1 + random.random(), exc.retry_after or 0)
            if exc.retry_after is not None and deadline - time.monotonic() - delay < _RETRY_MIN_SECONDS:
                raise
            time.sleep(delay)
            if exc.retry_after is not None and deadline - time.monotonic() < _RETRY_MIN_SECONDS:
                raise
        return send()


@sensitive_variables()
def _chat_payload(instruction, packet, schema, name):
    return {
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": json.dumps(packet, ensure_ascii=False, separators=(",", ":"))},
        ],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": name, "strict": True, "schema": schema}},
    }


@sensitive_variables()
def _chat_report(reply, elapsed, name):
    choice, usage = reply["choices"][0], reply.get("usage") or {}
    finish = choice.get("finish_reason")
    if finish != "stop" or elapsed > _SLOW_SECONDS:
        usage = usage if isinstance(usage, dict) else {}
        tokens = {key: usage[key] for key in ("prompt_tokens", "completion_tokens") if type(usage.get(key)) is int}
        details = usage.get("completion_tokens_details")
        reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
        if type(reasoning) is int:
            tokens["reasoning_tokens"] = reasoning
        if finish not in ("stop", "length", "content_filter", "tool_calls"):
            finish = "unknown"
        logger.warning("%s: finish %s after %.0f s (tokens %s)", name, finish, elapsed, tokens)
    if choice["message"].get("refusal"):
        raise EvaluationError(422, "Aucun bilan n’a pu être établi.")
    if finish != "stop":
        raise EvaluationError(422, "Le bilan est incomplet. Aucune note globale n’a été attribuée.")
    return json.loads(choice["message"]["content"], object_pairs_hook=unique_fields)


@sensitive_variables()
def request_report(
    instruction, packet, schema, *, name="bilan", max_tokens=3584, retry_schema=False, deadline=None, model=MODEL,
):
    payload = {
        "model": model,
        **_chat_payload(instruction, packet, schema, name),
        # Groq counts this cap plus the prompt against the token rate limit.
        "max_completion_tokens": max_tokens,
    }
    if model == QWEN_MODEL:
        payload["reasoning_effort"] = "none"
    else:
        payload.update(reasoning_effort="low", include_reasoning=False)
    body, elapsed = _request_with_retry(
        payload, host="api.groq.com", path="/openai/v1/chat/completions",
        auth={"Authorization": f"Bearer {settings.GROQ_API_KEY}"}, service="Groq",
        retry_schema=retry_schema, deadline=deadline,
    )
    try:
        return _chat_report(json.loads(body), elapsed, name)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError):
        logger.warning("%s: could not decode the Groq report", name)
        raise EvaluationError(502, _UNREADABLE) from None


@sensitive_variables()
def request_gemini_report(instruction, packet, schema, *, deadline=None):
    key = settings.GEMINI_API_KEY
    if not key:
        logger.warning("Gemini evaluation: no evaluation API key configured")
        raise EvaluationError(503, "Le service de bilan est indisponible. Votre travail reste disponible.")
    payload = {
        "systemInstruction": {"parts": [{"text": instruction}]},
        "contents": [{"role": "user", "parts": [
            {"text": json.dumps(packet, ensure_ascii=False, separators=(",", ":"))},
        ]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
            "maxOutputTokens": 8192,
            "thinkingConfig": {"thinkingLevel": "LOW"},
        },
    }
    body, _ = _request_with_retry(
        payload, host="generativelanguage.googleapis.com", path=f"/v1beta/models/{_GEMINI_MODEL}:generateContent",
        auth={"x-goog-api-key": key}, service="Gemini", deadline=deadline,
    )
    try:
        reply = json.loads(body)
        if (reply.get("promptFeedback") or {}).get("blockReason"):
            raise EvaluationError(422, "Aucun bilan n’a pu être établi.")
        candidate = reply["candidates"][0]
        if candidate.get("finishReason") == "MAX_TOKENS":
            raise EvaluationError(422, "Le bilan est incomplet. Aucune note globale n’a été attribuée.")
        if candidate.get("finishReason") != "STOP":
            raise EvaluationError(422, "Aucun bilan n’a pu être établi.")
        content = "".join(part["text"] for part in candidate["content"]["parts"] if not part.get("thought"))
        return json.loads(content, object_pairs_hook=unique_fields)
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError):
        logger.warning("Gemini evaluation: could not decode the report")
        raise EvaluationError(502, _UNREADABLE) from None


def workers_available():
    return bool(settings.CLOUDFLARE_WORKERS_API_KEY and re.fullmatch(r"[0-9a-fA-F]{32}", settings.CLOUDFLARE_ACCOUNT_ID))


@sensitive_variables()
def request_workers_report(instruction, packet, schema, *, name="ee1_bilan", deadline=None):
    if not workers_available():
        logger.warning("Cloudflare evaluation: missing token or invalid account ID")
        raise EvaluationError(503, "Le service de bilan est indisponible. Votre travail reste disponible.")
    body, elapsed = _request_with_retry(
        {
            **_chat_payload(instruction, packet, schema, name),
            "max_completion_tokens": 6144,
            "store": False,
        },
        host="api.cloudflare.com",
        path=f"/client/v4/accounts/{settings.CLOUDFLARE_ACCOUNT_ID}/ai/run/{_WORKERS_MODEL}",
        auth={"Authorization": f"Bearer {settings.CLOUDFLARE_WORKERS_API_KEY}"},
        service="Cloudflare", deadline=deadline,
    )
    try:
        reply = json.loads(body, object_pairs_hook=unique_fields)
        if reply.get("success") is not True:
            logger.warning("Cloudflare evaluation: provider declined the report")
            raise EvaluationError(502, "Le service de bilan a refusé la demande. Votre travail reste disponible.")
        report = _chat_report(reply["result"], elapsed, "Cloudflare Gemma evaluation")
        if not isinstance(report, dict):
            raise ValueError
        return report
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError):
        logger.warning("Cloudflare evaluation: could not decode the report")
        raise EvaluationError(502, _UNREADABLE) from None


def available_providers():
    return {
        provider for provider, configured in (
            ("groq", settings.GROQ_API_KEY),
            ("gemini", settings.GEMINI_API_KEY),
            ("cloudflare", workers_available()),
        ) if configured
    }


@sensitive_variables()
def request_provider_report(provider, instruction, packet, schema, *, name="bilan", deadline=None, **groq_options):
    if provider == "groq":
        return request_report(instruction, packet, schema, name=name, deadline=deadline, **groq_options)
    if provider == "gemini":
        return request_gemini_report(instruction, packet, schema, deadline=deadline)
    if provider == "cloudflare":
        return request_workers_report(instruction, packet, schema, name=name, deadline=deadline)
    raise EvaluationError(400, "Le modèle d’évaluation n’est pas disponible.")
