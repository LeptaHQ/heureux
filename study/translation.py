"""Shared server-side translation transport. Never called by question toggles."""

import json
import urllib.request

from django.conf import settings


class DeepLResponseError(ValueError):
    pass


def post_json(url, payload, headers=None):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=settings.TRANSLATION_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def deepl_host(api_key):
    return "api-free.deepl.com" if api_key.endswith(":fx") else "api.deepl.com"


def deepl_translate(texts, api_key, *, context=""):
    if not api_key or not 1 <= len(texts) <= 50:
        raise ValueError("DeepL requires a key and between 1 and 50 texts.")
    payload = {"text": list(texts), "source_lang": "FR", "target_lang": settings.DEEPL_TARGET_LANG}
    if context:
        payload["context"] = context
    body = post_json(
        f"https://{deepl_host(api_key)}/v2/translate", payload,
        {"Authorization": f"DeepL-Auth-Key {api_key}"},
    )
    rows = body.get("translations") if isinstance(body, dict) else None
    if not isinstance(rows, list) or len(rows) != len(texts):
        raise DeepLResponseError("DeepL returned an unexpected number of translations.")
    if any(not isinstance(row, dict) or not isinstance(row.get("text"), str) for row in rows):
        raise DeepLResponseError("DeepL returned an invalid translation.")
    return [row["text"] for row in rows]


def deepl_usage(api_key):
    request = urllib.request.Request(
        f"https://{deepl_host(api_key)}/v2/usage",
        headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
    )
    with urllib.request.urlopen(request, timeout=settings.TRANSLATION_TIMEOUT) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict) or any(
        type(body.get(key)) is not int or body[key] < 0
        for key in ("character_count", "character_limit")
    ):
        raise DeepLResponseError("DeepL returned invalid usage limits.")
    return body["character_count"], body["character_limit"]
