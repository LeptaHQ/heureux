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


def model_version_keys(models):
    keys = []
    occurrences = Counter()
    for source in models:
        digest = hashlib.sha256(
            json.dumps(source, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        occurrences[digest] += 1
        keys.append(f"{digest}-{occurrences[digest]}")
    return keys


def active_model_version_count(models, overrides):
    """Count visible shared versions without loading their database JSON."""
    return sum(
        not (
            (override := overrides.get(key)) is not None
            and override.is_deleted
        )
        for key in model_version_keys(models)
    )


def writing_model_versions(sujet, overrides):
    versions = []
    models = sujet.model_versions
    for number, (source, key) in enumerate(zip(models, model_version_keys(models)), 1):
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


def model_update_targets(sujets_by_slug, migrations):
    aliases = {
        (slug, key): (target["subject"], target["key"])
        for slug, updates in migrations.items() for key, target in updates.items()
    }
    keys_by_slug = {
        slug: model_version_keys(sujet.model_versions)
        for slug, sujet in sujets_by_slug.items()
    }
    targets = {}
    for source in aliases:
        if source[0] not in sujets_by_slug:
            continue
        target = source
        visited = set()
        while target[1] not in keys_by_slug.get(target[0], ()):
            if target in visited or target not in aliases:
                raise ValueError(f"Unresolved writing model key update: {source}")
            visited.add(target)
            target = aliases[target]
        destination = sujets_by_slug[target[0]]
        targets[(sujets_by_slug[source[0]].pk, source[1])] = (
            destination, target[1], keys_by_slug[target[0]].index(target[1]) + 1
        )
    return targets


def remap_model_overrides(targets):
    """Carry private edits/deletions only across explicitly declared model edits."""
    if not targets:
        return 0
    sujet_ids = {sujet_id for sujet_id, _ in targets}
    sujet_ids.update(destination.pk for destination, _, _ in targets.values())
    rows = list(WritingResponseOverride.objects.select_for_update().filter(
        sujet_id__in=sujet_ids,
    ).order_by("-updated_at", "-pk"))
    occupied = {(row.user_id, row.sujet_id, row.version_key) for row in rows}
    changed = []
    conflicts = 0
    for row in rows:
        target = targets.get((row.sujet_id, row.version_key))
        if target is None:
            continue
        destination, version_key, number = target
        if (row.sujet_id, row.version_key) == (destination.pk, version_key):
            continue
        # Hiding a former alternative must not hide a new subject's sole main model.
        if row.is_deleted and row.sujet_id != destination.pk and number == 1:
            conflicts += 1
            continue
        key = (row.user_id, destination.pk, version_key)
        if key in occupied:
            conflicts += 1
            continue
        occupied.add(key)
        row.sujet_id = destination.pk
        row.version_key = version_key
        changed.append(row)
    WritingResponseOverride.objects.bulk_update(changed, ["sujet", "version_key"])
    return conflicts


def writing_version_edit_url(part_slug, task_slug, sujet_id, version_key):
    return (
        reverse("study:writing_sujet_edit", args=[part_slug, task_slug, sujet_id])
        + "?"
        + urlencode({"version": version_key})
    )
