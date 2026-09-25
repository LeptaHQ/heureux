"""Reusable projections for content-heavy catalogue models."""

_RESPONSE_PRESENTATION_FIELDS = (
    "prompt",
    "reformulation",
    "position",
    "position_claire",
    "nuance",
    "conclusion",
    "body",
    "body_html",
    "semantic_rationale",
)


def lean_prompt_rows(queryset, *, with_response=False):
    """Exclude answer payloads that prompt listings and links never render."""
    deferred = ["model_content"]
    if with_response:
        deferred.extend(
            f"response__{field}"
            for field in _RESPONSE_PRESENTATION_FIELDS
        )
    return queryset.defer(*deferred)


def lean_phrase_rows(queryset):
    """Exclude import provenance from learner-facing phrase rows."""
    return queryset.defer("sources_raw")
