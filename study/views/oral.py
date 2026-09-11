"""Oral model variants and preserved learner history."""

import json

from django.db.models import Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from ..models import Card, OralStateSnapshot, Prompt, Response, ReviewLog
from ..oral_history import (
    PERSONAL_FIELDS, group_annotations, group_snapshots, owner_response, personal_versions,
    preferred_personal, save_personal,
    variant_annotation_key,
)
from ..response_personalization import effective_response
from ..routing import TACHE_TWO_PROMPT_KEY, prompt_detail_url, review_url
from ..progress import subject_progress_by_response, summarize_subject_progress
from .helpers import _route_task


def oral_subject_directory(request, task, *, deduplicate=False):
    prompts = list(Prompt.objects.filter(
        is_active=True, response__is_active=True, theme__task=task,
    ).select_related("theme", "response").order_by("theme__order", "number", "pk"))
    progress = subject_progress_by_response(request.user, {prompt.response_id for prompt in prompts})
    counts = {}
    for prompt in prompts:
        counts[prompt.response_id] = counts.get(prompt.response_id, 0) + 1
    groups = {}
    seen = set()
    for prompt in prompts:
        if deduplicate and prompt.response_id in seen:
            continue
        seen.add(prompt.response_id)
        theme = prompt.theme
        group = groups.setdefault(theme.pk, {
            "slug": theme.slug, "name": theme.display_name, "icon": theme.icon,
            "subjects": [], "response_ids": set(),
        })
        group["subjects"].append({
            "prompt": prompt, "progress": progress[prompt.response_id],
            "publication_count": counts[prompt.response_id],
        })
        group["response_ids"].add(prompt.response_id)
    for group in groups.values():
        group["subject_count"] = len(group["subjects"])
        group.update(summarize_subject_progress(progress[pk] for pk in group["response_ids"]))
    return render(request, "study/oral_subjects.html", {
        "part": task.part, "task": task, "groups": list(groups.values()),
        "subject_deduplication_available": True, "deduplicate_subjects": deduplicate,
        "publication_count": len(prompts),
        "display_count": sum(group["subject_count"] for group in groups.values()),
        "summary": summarize_subject_progress(progress.values()),
        "prompt_copies": {str(prompt.pk): prompt.text for prompt in prompts},
    })


def oral_response_context(request, prompt):
    response = prompt.response
    if not response.semantic_group:
        return {}
    versions = list(personal_versions(response, request.user))
    selected_personal = None
    personal_id = request.GET.get("personal")
    if personal_id:
        selected_personal = next((item for item in versions if str(item.pk) == personal_id), None)
        if selected_personal is None:
            raise Http404
    elif request.GET.get("model") != "1":
        selected_personal = preferred_personal(response, request.user)
    value = effective_response(
        response, request.user, prompt=prompt,
        model_only=request.GET.get("model") == "1",
        personal=selected_personal,
    )
    storage_key = (
        selected_personal.response.content_key if selected_personal is not None
        else prompt.model_content.get("storage_key", response.content_key)
    )
    legacy_keys = [f"response:{storage_key}"]
    match = TACHE_TWO_PROMPT_KEY.fullmatch(storage_key)
    if match:
        legacy_keys.append(
            f"tache-two:{match['month']}:batch-{int(match['batch'])}:subject-{int(match['subject'])}"
        )
    copy_text = "\n\n".join(
        text for text in [
            value.reformulation, value.position, value.position_claire,
            *[
                "\n".join(part for part in (
                    argument.idea, argument.developpement, argument.exemple, argument.consequence,
                ) if part)
                for argument in value.arguments
            ],
            value.nuance, value.conclusion,
        ] if text
    )
    return {
        "response_content": value,
        "oral_annotation_key": variant_annotation_key(prompt, value),
        "oral_legacy_annotation_keys": json.dumps(legacy_keys),
        "oral_copy_text": copy_text,
        "response_review_url": review_url({
            "part": prompt.theme.task.part.slug, "task": prompt.theme.task.slug,
            "kind": "spine", "response": response.pk, "prompt": prompt.pk,
            "model": "1" if request.GET.get("model") == "1" else "",
            "personal": personal_id or "",
        }),
        "oral_model_variants": [
            {"prompt": item, "url": prompt_detail_url(item) + "?model=1"}
            for item in response.prompts.filter(is_active=True).select_related("theme__task__part")
        ],
        "oral_personal_versions": [
            {"version": item, "url": prompt_detail_url(prompt) + f"?personal={item.pk}"}
            for item in versions
        ],
        "oral_history_url": reverse(
            "study:oral_response_history",
            args=[prompt.theme.task.part.slug, prompt.theme.task.slug, response.pk],
        ),
    }


@require_http_methods(["GET", "POST"])
def oral_response_history(request, part_slug, task_slug, response_id):
    task = _route_task(part_slug, task_slug, request=request)
    if part_slug != "eo" or task_slug not in {"tache-2", "tache-3"}:
        raise Http404
    original = get_object_or_404(
        Response.objects.select_related("semantic_owner", "theme__task__part"),
        pk=response_id, theme__task=task,
    )
    response = owner_response(original)
    if not response.semantic_group:
        raise Http404
    sources = Response.objects.filter(Q(pk=response.pk) | Q(semantic_owner=response))
    versions = personal_versions(response, request.user)
    snapshots = group_snapshots(response, request.user)
    prompt = response.canonical_prompt
    if request.method == "POST":
        selected_id = request.POST.get("personal_id") or request.POST.get("snapshot_id", "")
        if not selected_id.isdigit():
            return HttpResponseBadRequest("Identifiant de version invalide.")
        if request.POST.get("personal_id"):
            version = get_object_or_404(versions, pk=request.POST["personal_id"])
            defaults = {name: getattr(version, name) for name in PERSONAL_FIELDS}
        elif request.POST.get("snapshot_id"):
            archived = get_object_or_404(
                snapshots, pk=request.POST["snapshot_id"], kind="personal",
            )
            defaults = {name: archived.payload["fields"][name] for name in PERSONAL_FIELDS}
        else:
            return HttpResponseBadRequest("Version requise.")
        save_personal(response, request.user, defaults, source_prompt=prompt)
        return redirect(prompt_detail_url(prompt) + "?saved=1")
    return render(request, "study/oral_response_history.html", {
        "part": task.part, "task": task, "response": response,
        "detail_url": prompt_detail_url(prompt),
        "versions": versions, "snapshots": snapshots,
        "annotations": group_annotations(response, request.user),
        "cards": Card.objects.filter(user=request.user, response__in=sources),
        "reviews": ReviewLog.objects.filter(
            user=request.user, card__response__in=sources,
        ).select_related("card").order_by("-reviewed_at", "-pk"),
    })
