"""Presentation of the current oral response."""

import json

from django.conf import settings
from django.http import Http404
from django.urls import reverse

from ..oral_history import preferred_personal, variant_annotation_key
from ..eo3_audio import narration_presentation
from ..response_personalization import effective_response
from ..routing import TACHE_TWO_PROMPT_KEY, review_url, subject_selection_url
from ..tache_three_models import annotation_arguments, response_text, reviewed_model
from ..tache_three_prompt_notes import prompt_note_for_response


def oral_response_context(request, prompt):
    if "model" in request.GET or "personal" in request.GET:
        raise Http404
    response = prompt.response
    if not response.semantic_group:
        return {}
    from ..public_response_annotations import preserve_prompt_annotations

    preserve_prompt_annotations(request.user, prompt)
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
    model = reviewed_model(response, prompt)
    structured_eo3 = model is not None
    reviewed_eo3 = structured_eo3 and not value.is_personal
    if match or structured_eo3:
        # Changed public layouts must not replay offsets from published models.
        legacy_keys = []
    return {
        "response_content": value,
        "arguments": annotation_arguments(prompt, value),
        "reviewed_eo3": reviewed_eo3,
        "structured_eo3": structured_eo3,
        "single_response_eo3": prompt.theme.task.slug == "tache-3",
        "eo3_response_copy_text": response_text(value) if structured_eo3 else "",
        "eo3_audio": (
            narration_presentation(model, value, request.user.pk) if value.is_personal
            else narration_presentation(model)
        ) if structured_eo3 else None,
        "eo3_cached_playlist_url": (
            subject_selection_url(
                reverse("study:eo3_audio_playlist", args=[prompt.pk]), request,
            )
            if structured_eo3 and settings.EO3_AUDIO_ENABLED else ""
        ),
        "eo3_prompt_note": prompt_note_for_response(response, prompt),
        "oral_annotation_key": variant_annotation_key(prompt, value),
        "oral_legacy_annotation_keys": json.dumps(legacy_keys),
        "response_review_url": review_url({
            "part": prompt.theme.task.part.slug, "task": prompt.theme.task.slug,
            "kind": "spine", "response": response.pk, "prompt": prompt.pk,
        }),
    }
