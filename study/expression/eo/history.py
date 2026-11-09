"""Non-destructive ownership and recovery for corrected oral subject groups."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from urllib.parse import urlsplit

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Case, Q, Value, When

from study.learning.practice import lock_course_user as lock_study_user
from study.models import OralStateSnapshot, PersonalResponse, Phrase, PhraseTier, Prompt, Response


@dataclass(frozen=True)
class AnnotationPromptOwner:
    pk: int
    content_key: str
    response_id: int
    task_id: int
    task_slug: str


def variant_annotation_key(prompt, content, *, tache_two_dialogue=None):
    if prompt.content_key.startswith("tache2:"):
        from study.expression.eo.tache_2.dialogues import matching_dialogue

        current = matching_dialogue(prompt, content)
        if current is not None and (
            tache_two_dialogue is None or tache_two_dialogue == current
        ):
            return f"response:{prompt.content_key}:model"
    elif getattr(
        getattr(prompt, "response", None), "semantic_group", "",
    ).startswith("eo/tache-3/"):
        from study.expression.eo.tache_3.responses import reviewed_model

        model = reviewed_model(prompt.response, prompt)
        if model is not None and (content.is_personal or content == model.response):
            return f"response:{prompt.content_key}:model"
    return legacy_variant_annotation_key(
        prompt, content, tache_two_dialogue=tache_two_dialogue,
    )


def legacy_variant_annotation_key(prompt, content, *, tache_two_dialogue=None):
    payload = asdict(content)
    if prompt.content_key.startswith("tache2:"):
        from study.expression.eo.tache_2.dialogues import matching_dialogue
        dialogue = tache_two_dialogue or matching_dialogue(prompt, content)
        payload["nuance"] = ""
        payload["arguments"] = [
            {
                **argument,
                "developpement": "",
                "exemple": "",
                "consequence": "",
            }
            for argument in payload["arguments"]
        ]
        if dialogue is not None:
            payload["is_personal"] = False
        payload["eo2_questions_only_layout"] = {
            "version": 2,
            "questions": [
                (question.topic, question.follow_up_to, question.condition)
                for question in dialogue.questions
            ] if dialogue is not None else [],
        }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
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
    # An own inactive version is an explicit reset, ahead of any active alias.
    selected = personal_versions(response, user).filter(
        Q(response=response) | Q(is_active=True),
    ).alias(
        _own_priority=Case(When(response=response, then=Value(0)), default=Value(1)),
    ).order_by("_own_priority", "-updated_at", "-id").first()
    return selected if selected is not None and selected.is_active else None


def preferred_personals(responses, user):
    """Batch equivalent of preferred_personal, including explicit model resets."""
    responses = list(responses)
    owners = {response.pk: owner_response(response) for response in responses}
    owner_ids = {owner.pk for owner in owners.values()}
    versions = list(
        PersonalResponse.objects.filter(user=user).filter(
            Q(response_id__in=owner_ids)
            | Q(response__semantic_owner_id__in=owner_ids)
            | Q(source_prompt__response_id__in=owner_ids)
        ).select_related("response", "source_prompt").only(
            "id", "response_id", "source_prompt_id", "is_active", "updated_at",
            "reformulation", "position", "position_claire", "arguments", "nuance", "conclusion",
            "response__id", "response__semantic_owner_id",
            "source_prompt__id", "source_prompt__response_id",
        ).order_by("-updated_at", "-id")
    ) if owner_ids else []
    result = {}
    for response in responses:
        owner = owners[response.pk]
        if owner.semantic_group:
            candidates = [
                version for version in versions
                if (
                    version.source_prompt.response_id == owner.pk
                    if version.source_prompt_id else
                    version.response_id == owner.pk
                    or version.response.semantic_owner_id == owner.pk
                )
            ]
        else:
            candidates = [version for version in versions if version.response_id == owner.pk]
        own = next((version for version in candidates if version.response_id == response.pk), None)
        result[response.pk] = (
            own if own.is_active else None
        ) if own is not None else next(
            (version for version in candidates if version.is_active), None,
        )
    return result


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
def save_personal(response, user, defaults, *, source_prompt=None, snapshot_previous=True):
    # A first save has no personal row to lock; keep the account lifecycle order.
    lock_study_user(user)
    current = PersonalResponse.objects.select_for_update().filter(
        response=response, user=user,
    ).first()
    if current is not None and snapshot_previous:
        snapshot(current, "personal")
    return PersonalResponse.objects.update_or_create(
        response=response, user=user,
        defaults={**defaults, "source_prompt": source_prompt, "is_active": True},
    )[0]


def _prompt_path_reference(path):
    path = urlsplit(path).path
    match = re.fullmatch(r"/expression/orale/tache-([23])/sujets/(\d+)/", path)
    if match:
        return int(match[2]), None, f"tache-{match[1]}"
    match = re.fullmatch(
        r"/expression/orale/tache-2/sujets/([a-z0-9-]+)/batch-(\d+)/(\d+)/", path,
    )
    if match:
        return (
            None,
            f"tache2:{match[1]}:batch-{int(match[2]):02d}:subject-{int(match[3]):02d}",
            None,
        )
    return None, None, None


def prompt_from_path(path, prompts_by_id, prompts_by_key):
    prompt_id, content_key, task_slug = _prompt_path_reference(path)
    if prompt_id is not None:
        prompt = prompts_by_id.get(prompt_id)
        return prompt if prompt and prompt.task_slug == task_slug else None
    return prompts_by_key.get(content_key) if content_key is not None else None


def _annotation_prompt_key(key):
    if key.startswith(("response:", "subject-sidebar:")):
        key = key.split(":", 1)[1].removesuffix(":front").removesuffix(":back")
        match = re.fullmatch(r"(.+):(?:model|variant-[0-9a-f]{16})", key)
        return match[1] if match else None
    match = re.fullmatch(r"tache-two:([^:]+):batch-(\d+):subject-(\d+)", key)
    if match:
        return f"tache2:{match[1]}:batch-{int(match[2]):02d}:subject-{int(match[3]):02d}"
    return None


def annotation_owners(annotations, *, known_prompts=(), known_responses=None):
    """Occurrence priority, optionally reusing eligible request-local metadata.

    Known prompts must be active semantic prompts; known response keys must map
    to their semantic owner. Missing references still use the normal lookups.
    """
    annotations = tuple(annotations)
    prompt_ids = set()
    prompt_keys = set()
    for annotation in annotations:
        if annotation.source_prompt_id is not None:
            prompt_ids.add(annotation.source_prompt_id)
        try:
            prompt_id, path_key, _task_slug = _prompt_path_reference(annotation.source_path)
        except ValueError:
            # A valid explicit prompt historically bypasses even a malformed URL.
            prompt_id, path_key = None, None
        if prompt_id is not None:
            prompt_ids.add(prompt_id)
        prompt_keys.update(
            key for key in (path_key, _annotation_prompt_key(annotation.source_key))
            if key is not None
        )
    by_id = {prompt.pk: prompt for prompt in known_prompts}
    by_key = {prompt.content_key: prompt for prompt in by_id.values()}
    prompts = [
        AnnotationPromptOwner(*row)
        for row in Prompt.objects.filter(
            is_active=True,
            response__semantic_group__gt="",
        ).filter(
            Q(pk__in=prompt_ids - by_id.keys())
            | Q(content_key__in=prompt_keys - by_key.keys()),
        ).order_by().values_list(
            "pk",
            "content_key",
            "response_id",
            "theme__task_id",
            "theme__task__slug",
        )
    ]
    by_id.update((prompt.pk, prompt) for prompt in prompts)
    by_key.update((prompt.content_key, prompt) for prompt in prompts)
    unresolved = [
        annotation for annotation in annotations
        if not (
            by_id.get(annotation.source_prompt_id)
            or prompt_from_path(annotation.source_path, by_id, by_key)
        )
    ]
    response_keys = {
        annotation.source_key.split(":", 1)[1].removesuffix(":front").removesuffix(":back")
        for annotation in unresolved
        if annotation.source_key.startswith(("response:", "subject-sidebar:"))
        and _annotation_prompt_key(annotation.source_key) is None
    }
    response_by_key = dict(known_responses or {})
    response_by_key.update({
        content_key: semantic_owner_id or response_id
        for content_key, semantic_owner_id, response_id
        in Response.objects.filter(
            Q(semantic_group__gt="") | Q(semantic_owner__isnull=False),
            content_key__in=response_keys - response_by_key.keys(),
        ).values_list("content_key", "semantic_owner_id", "pk")
    })
    phrase_keys = {
        match[1] for annotation in unresolved
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
            if annotation.task_id is None or annotation.task_id == prompt.task_id:
                result[annotation.pk] = prompt.response_id
            continue
        key = annotation.source_key
        if key.startswith("phrase:"):
            match = re.match(r"phrase:([^:]+):", key)
            if match and match[1] in phrase_owners:
                result[annotation.pk] = phrase_owners[match[1]]
        elif (prompt_key := _annotation_prompt_key(key)) is not None:
            prompt = by_key.get(prompt_key)
            if prompt:
                result[annotation.pk] = prompt.response_id
        elif key.startswith(("response:", "subject-sidebar:")):
            key = key.split(":", 1)[1]
            key = key.removesuffix(":front").removesuffix(":back")
            if key in response_by_key:
                result[annotation.pk] = response_by_key[key]
    return result
