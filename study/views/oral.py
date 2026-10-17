"""Presentation of the current oral response."""

import json

from django.http import Http404

from ..oral_history import preferred_personal, variant_annotation_key
from ..response_personalization import effective_response
from ..routing import TACHE_TWO_PROMPT_KEY, review_url
from ..tache_three_models import reviewed_model


def oral_response_context(request, prompt):
    if "model" in request.GET or "personal" in request.GET:
        raise Http404
    response = prompt.response
    if not response.semantic_group:
        return {}
    selected_personal = preferred_personal(response, request.user)
    value = effective_response(
        response, request.user, prompt=prompt,
        model_only=selected_personal is None,
        personal=selected_personal,
    )
    storage_key = (
        selected_personal.response.content_key if selected_personal is not None
        else prompt.model_content.get("storage_key", response.content_key)
    )
    legacy_keys = [f"response:{storage_key}"]
    match = TACHE_TWO_PROMPT_KEY.fullmatch(storage_key)
    reviewed_eo3 = not value.is_personal and reviewed_model(response, prompt) is not None
    if match or reviewed_eo3:
        # Changed public layouts must not replay offsets from published models.
        legacy_keys = []
    return {
        "response_content": value,
        "reviewed_eo3": reviewed_eo3,
        "oral_annotation_key": variant_annotation_key(prompt, value),
        "oral_legacy_annotation_keys": json.dumps(legacy_keys),
        "response_review_url": review_url({
            "part": prompt.theme.task.part.slug, "task": prompt.theme.task.slug,
            "kind": "spine", "response": response.pk, "prompt": prompt.pk,
        }),
    }
