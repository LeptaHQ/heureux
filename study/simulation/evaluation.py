"""Provider transport and response decoding shared by simulation graders."""

import json
import logging
import random
import re
import socket
import threading
import time
from contextlib import closing
from http.client import HTTPException, HTTPSConnection

from django.conf import settings
from django.views.decorators.debug import sensitive_variables

MODEL = "openai/gpt-oss-120b"
_GEMINI_MODEL = "gemini-3.8-flash"
DEADLINE_SECONDS = 180
_MAX_RESPONSE = 64_000
_RETRY_MIN_SECONDS = 30
_SLOW_SECONDS = 30
_UNREADABLE = "Le bilan est illisible. Vous pouvez réessayer."
logger = logging.getLogger(__name__)


class EvaluationError(Exception):
    def __init__(self, status, message, *, retry=False, schema_rejected=False):
        self.status, self.retry = status, retry
        self.schema_rejected = schema_rejected
        super().__init__(message)


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


def _provider_error(raw):
    try:
        error = json.loads(raw)["error"]
        code = error.get("code")
        if not isinstance(code, str) or not code:
            code = error.get("status") or error.get("type")
        message = error.get("message")
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return "", ""
    code = code.lower() if isinstance(code, str) and re.fullmatch(r"[A-Za-z_]{1,40}", code) else ""
    return code, " ".join(message.split())[:300] if isinstance(message, str) else ""


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
                provider, detail = _provider_error(resp.read(16_000))
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
    logger.warning("%s evaluation: provider HTTP %d %s %s", service, resp.status,
                   provider or "-", (detail if service == "Groq" else "") or "-")
    code = f"HTTP {resp.status} {provider}".strip()
    if resp.status == 429:
        later = f" Réessayez dans {wait} s." if re.fullmatch(r"\d{1,5}", wait) else ""
        raise EvaluationError(429, f"Limite de demandes de bilan atteinte ({code}).{later} Votre travail reste disponible.")
    if resp.status >= 500:
        raise EvaluationError(502, f"Le bilan est momentanément indisponible ({code}). Votre travail reste disponible.",
                              retry=True)
    raise EvaluationError(
        502, f"La demande de bilan a été refusée ({code}). Votre travail reste disponible.",
        schema_rejected=service == "Groq" and resp.status == 400 and provider == "json_validate_failed",
    )


@sensitive_variables()
def request_report(instruction, packet, schema, *, name="bilan", max_tokens=3584, retry_schema=False):
    """Request and decode one report, with at most one retry within the deadline."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": json.dumps(packet, ensure_ascii=False, separators=(",", ":"))},
        ],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": name, "strict": True, "schema": schema}},
        # Groq counts this cap plus the prompt against the token rate limit.
        "reasoning_effort": "low", "include_reasoning": False, "max_completion_tokens": max_tokens,
    }
    deadline = time.monotonic() + DEADLINE_SECONDS

    def send():
        return _post(
            json.dumps(payload, ensure_ascii=False).encode(), deadline,
            host="api.groq.com", path="/openai/v1/chat/completions",
            auth={"Authorization": f"Bearer {settings.GROQ_API_KEY}"}, service="Groq",
        )

    try:
        body, elapsed = send()
    except EvaluationError as exc:
        retry_json = retry_schema and exc.schema_rejected
        if not (exc.retry or retry_json) or deadline - time.monotonic() < _RETRY_MIN_SECONDS:
            raise
        if retry_json:
            payload["response_format"] = {"type": "json_object"}
            payload["messages"][0]["content"] += "\nJSON schema: " + json.dumps(schema, separators=(",", ":"))
        else:
            time.sleep(1 + random.random())
        body, elapsed = send()
    try:
        reply = json.loads(body)
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
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, RecursionError):
        logger.warning("%s: could not decode the Groq report", name)
        raise EvaluationError(502, _UNREADABLE) from None


@sensitive_variables()
def request_gemini_report(instruction, packet, schema):
    key = settings.GEMINI_EVALUATION_API_KEY
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
    body, _ = _post(
        json.dumps(payload, ensure_ascii=False).encode(), time.monotonic() + DEADLINE_SECONDS,
        host="generativelanguage.googleapis.com", path=f"/v1beta/models/{_GEMINI_MODEL}:generateContent",
        auth={"x-goog-api-key": key}, service="Gemini",
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
