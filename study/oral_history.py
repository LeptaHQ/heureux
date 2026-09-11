"""Non-destructive ownership and recovery for corrected oral subject groups."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import date, datetime
from urllib.parse import urlsplit

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q

from .models import Annotation, OralStateSnapshot, PersonalResponse, Phrase, PhraseTier, Prompt, Response

PERSONAL_FIELDS = (
    "reformulation", "position", "position_claire", "arguments", "nuance", "conclusion",
)


def variant_annotation_key(prompt, content):
    digest = hashlib.sha256(
        json.dumps(asdict(content), sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"response:{prompt.content_key}:variant-{digest}"


def owner_response(response):
    return response.semantic_owner if response.semantic_owner_id else response


def personal_versions(response, user):
    response = owner_response(response)
    if not response.semantic_group:
        return PersonalResponse.objects.filter(user=user, response=response)
    return PersonalResponse.objects.filter(user=user).filter(
        Q(source_prompt__response=response)
        | Q(source_prompt__isnull=True) & (
            Q(response=response) | Q(response__semantic_owner=response)
        )
    ).select_related("response", "source_prompt")


def preferred_personal(response, user):
    versions = personal_versions(response, user)
    own = versions.filter(response=response).first()
    if own is not None:
        return own if own.is_active else None
    return versions.filter(is_active=True).first()


def snapshot(instance, kind, *, response=None):
    response = response or instance.response
    values = {
        field.attname: (
            value.isoformat() if isinstance(value, (date, datetime)) else value
        )
        for field in instance._meta.concrete_fields
        for value in [getattr(instance, field.attname)]
    }
    payload = json.loads(json.dumps(
        {
            "fields": values,
            "source_content_key": response.content_key,
            "source_prompt_text": response.prompt,
            "source_body": response.body,
        },
        cls=DjangoJSONEncoder, sort_keys=True,
    ))
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return OralStateSnapshot.objects.get_or_create(
        kind=kind, source_id=instance.pk, digest=digest,
        defaults={"response": response, "user_id": instance.user_id, "payload": payload},
    )[0]


@transaction.atomic
def save_personal(response, user, defaults, *, source_prompt=None):
    current = PersonalResponse.objects.select_for_update().filter(
        response=response, user=user,
    ).first()
    if current is not None:
        snapshot(current, "personal")
    return PersonalResponse.objects.update_or_create(
        response=response, user=user,
        defaults={**defaults, "source_prompt": source_prompt, "is_active": True},
    )[0]


def prompt_from_path(path, prompts_by_id, prompts_by_key):
    path = urlsplit(path).path
    match = re.fullmatch(r"/expression/orale/tache-([23])/sujets/(\d+)/", path)
    if match:
        prompt = prompts_by_id.get(int(match[2]))
        if prompt and prompt.theme.task.slug == f"tache-{match[1]}":
            return prompt
    match = re.fullmatch(
        r"/expression/orale/tache-2/sujets/([a-z0-9-]+)/batch-(\d+)/(\d+)/", path,
    )
    if match:
        return prompts_by_key.get(
            f"tache2:{match[1]}:batch-{int(match[2]):02d}:subject-{int(match[3]):02d}"
        )
    return None


def annotation_owners(annotations):
    """An explicit occurrence path outranks a historically shared source root."""
    prompts = list(Prompt.objects.filter(
        is_active=True, response__semantic_group__gt="",
    ).select_related("theme__task__part"))
    by_id = {prompt.pk: prompt for prompt in prompts}
    by_key = {prompt.content_key: prompt for prompt in prompts}
    response_by_key = {
        response.content_key: response.semantic_owner_id or response.pk
        for response in Response.objects.filter(
            Q(semantic_group__gt="") | Q(semantic_owner__isnull=False)
        )
    }
    phrase_keys = {
        match[1] for annotation in annotations
        if (match := re.match(r"phrase:([^:]+):", annotation.source_key))
    }
    phrase_owners = dict(Phrase.objects.filter(
        phrase_id__in=phrase_keys, tier=PhraseTier.SUBJECT, is_active=True,
        source_prompts__response__semantic_group__gt="",
    ).values_list("phrase_id", "source_prompts__response_id")) if phrase_keys else {}
    result = {}
    for annotation in annotations:
        prompt = by_id.get(annotation.source_prompt_id) or prompt_from_path(
            annotation.source_path, by_id, by_key,
        )
        if prompt is not None:
            if annotation.task_id is None or annotation.task_id == prompt.theme.task_id:
                result[annotation.pk] = prompt.response_id
            continue
        key = annotation.source_key
        if key.startswith("phrase:"):
            match = re.match(r"phrase:([^:]+):", key)
            if match and match[1] in phrase_owners:
                result[annotation.pk] = phrase_owners[match[1]]
        elif key.startswith(("response:", "subject-sidebar:")):
            key = key.split(":", 1)[1]
            key = key.removesuffix(":front").removesuffix(":back")
            variant = re.fullmatch(r"(.+):variant-[0-9a-f]{16}", key)
            if variant:
                prompt = by_key.get(variant[1])
                if prompt:
                    result[annotation.pk] = prompt.response_id
                continue
            if key in response_by_key:
                result[annotation.pk] = response_by_key[key]
        elif key.startswith("tache-two:"):
            match = re.fullmatch(r"tache-two:([^:]+):batch-(\d+):subject-(\d+)", key)
            if match:
                prompt = by_key.get(
                    f"tache2:{match[1]}:batch-{int(match[2]):02d}:subject-{int(match[3]):02d}"
                )
                if prompt:
                    result[annotation.pk] = prompt.response_id
    return result


def group_annotations(response, user):
    task = response.theme.task
    annotations = list(Annotation.objects.filter(
        user=user,
    ).filter(Q(task=task) | Q(task__isnull=True)).order_by("-updated_at", "-pk"))
    owners = annotation_owners(annotations)
    return [annotation for annotation in annotations if owners.get(annotation.pk) == response.pk]


def group_snapshots(response, user):
    prompt_ids = Prompt.objects.filter(response=response).values("pk")
    return OralStateSnapshot.objects.filter(user=user).filter(
        Q(kind="personal", payload__fields__source_prompt_id__in=prompt_ids)
        | (
            Q(response=response) | Q(response__semantic_owner=response)
        ) & (
            ~Q(kind="personal") | Q(payload__fields__source_prompt_id=None)
        )
    )
