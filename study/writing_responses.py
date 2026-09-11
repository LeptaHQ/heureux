"""Learner-owned writing versions without changing shared models or their indices."""

import hashlib
import json
from collections import Counter
from urllib.parse import urlencode

from django.urls import reverse

from .models import WritingResponseOverride


def overrides_by_sujet(user, sujet_ids):
    result = {}
    for override in WritingResponseOverride.objects.filter(user=user, sujet_id__in=sujet_ids):
        result.setdefault(override.sujet_id, {})[override.version_key] = override
    return result


def writing_model_versions(sujet, overrides):
    versions = []
    occurrences = Counter()
    for number, source in enumerate(sujet.model_versions, 1):
        digest = hashlib.sha256(
            json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        occurrences[digest] += 1
        key = f"{digest}-{occurrences[digest]}"
        override = overrides.get(key)
        if override is not None and override.is_deleted:
            continue
        content = dict(source)
        if override is not None and override.body:
            content.update(body=override.body, origin="personal")
        versions.append({
            "key": key,
            "number": number,
            "copy_key": f"model-{number}",
            "content": content,
        })
    return versions


def writing_version_edit_url(part_slug, task_slug, sujet_id, version_key):
    return (
        reverse("study:writing_sujet_edit", args=[part_slug, task_slug, sujet_id])
        + "?"
        + urlencode({"version": version_key})
    )
