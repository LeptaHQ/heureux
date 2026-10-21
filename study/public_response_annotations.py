"""Keep selections on the one current EO2/EO3 public response."""

import hashlib
import re

from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import Annotation, AnnotationKind, Prompt
from .oral_highlights import AnnotationRootText, _move_anchor, _render_questions
from .oral_history import variant_annotation_key
from .progress import subject_progress_by_response
from .public_annotation_migration import PUBLIC_DIGESTS
from .querysets import lean_prompt_rows
from .response_personalization import effective_response
from .routing import prompt_detail_url
from .tache_three_models import annotation_arguments, reviewed_model
from .tache_two_dialogues import dialogue_response, published_dialogue


PUBLIC_KEY = re.compile(
    r"^response:(?P<prompt>.+):(?:(?P<model>model)|variant-(?P<digest>[0-9a-f]{16}))"
    r"(?P<surface>:(?:front|back))?$"
)
CONTEXT_LABELS = re.compile(
    r"\b(?:Arguments développés|Exemple concret|Développement|Conséquence|"
    r"Introduction|Conclusion|Nuance)\b",
)


def _current_content(prompt, user):
    task = prompt.theme.task
    if task.part.slug != "eo":
        return None
    if task.slug == "tache-2":
        dialogue = published_dialogue(prompt)
        if dialogue is None:
            return None
        # EO2 note-only personalization previously shared the public layout key.
        # If a later publication diverges, keep its selections on the private text.
        current = effective_response(prompt.response, user, prompt=prompt)
        return current if current.is_personal else dialogue_response(dialogue)
    if task.slug == "tache-3":
        model = reviewed_model(prompt.response, prompt)
        return model.response if model is not None else None
    return None


def render_current_response(prompt, content, surface, user):
    prompts = list(lean_prompt_rows(prompt.response.prompts.filter(is_active=True)))
    is_eo2 = prompt.theme.task.slug == "tache-2"
    if is_eo2 and surface != "front":
        return _render_questions(prompt, content, surface, prompts)
    context = {
        "part": prompt.theme.task.part, "task": prompt.theme.task,
        "selected_prompt": prompt, "canonical_prompt": prompt,
        "response": prompt.response, "response_content": content,
        "arguments": annotation_arguments(prompt, content), "reviewed_eo3": not is_eo2,
        "oral_annotation_key": variant_annotation_key(prompt, content),
        "kind": "spine", "tache_two_subject": is_eo2,
        "kind_label": "Questions d'interaction" if is_eo2 else "Réponse argumentée",
        "theme": prompt.theme, "family": prompt.family,
        "family_label": (
            prompt.family.name.rsplit(" · ", 1)[-1] if is_eo2 else prompt.family.name
        ),
        "prompt": prompt.text,
        "aliases": [item for item in prompts if item.pk != prompt.pk],
        "detail_url": prompt_detail_url(prompt),
    }
    if surface == "detail":
        return AnnotationRootText(
            render_to_string("study/response_detail.html", context),
            root_class="answer-columns",
        )
    if surface == "front":
        context["subject_progress"] = subject_progress_by_response(
            user, {prompt.response_id},
        )[prompt.response_id]
    return AnnotationRootText(
        "<div data-annotation-root>"
        + render_to_string(f"study/partials/card_{surface}.html", context)
        + "</div>"
    )


def _normalized(text):
    return re.sub(r"\s+", " ", text).strip()


def _shared_length(left, right, *, suffix=False):
    if suffix:
        left, right = left[::-1], right[::-1]
    common = []
    for a, b in zip(left, right):
        if a != b:
            break
        common.append(a)
    text = "".join(common)
    if suffix:
        text = text[::-1]
    # Repeated section labels cannot identify which argument owned a quote.
    return sum(char.isalnum() for char in CONTEXT_LABELS.sub("", text))


def response_field_anchor(rendered, offsets):
    """Store field identity and a checksum, never a previous response body."""
    start, end = offsets
    for field, (left, right) in getattr(rendered, "response_fields", {}).items():
        if left <= start < end <= right:
            return {
                "field": field,
                "sha256": hashlib.sha256(rendered.text[left * 2:right * 2]).hexdigest(),
                "start": start - left, "end": end - left,
            }
    return {}


def _response_field_offsets(annotation, rendered, anchor, bounds):
    left, right = bounds
    start, end = anchor.get("start"), anchor.get("end")
    if (
        type(start) is int and type(end) is int
        and 0 <= start < end <= right - left
        and anchor.get("sha256") == hashlib.sha256(
            rendered.text[left * 2:right * 2],
        ).hexdigest()
        and rendered.slice(left + start, left + end) == annotation.quote
    ):
        return left + start, left + end
    return None


def current_anchor(annotation, rendered):
    """Require an exact quote and unambiguous remaining context, not old offsets."""
    quote = annotation.quote.encode("utf-16-le")
    if not quote:
        return None
    bounds = None
    anchor = getattr(annotation, "response_anchor", {})
    if anchor:
        if not isinstance(anchor, dict) or not isinstance(anchor.get("field"), str):
            return None
        bounds = getattr(rendered, "response_fields", {}).get(anchor.get("field"))
        if bounds is None:
            return None
        offsets = _response_field_offsets(annotation, rendered, anchor, bounds)
        if offsets is not None:
            return offsets
    prefix, suffix = _normalized(annotation.prefix), _normalized(annotation.suffix)
    matches = []
    cursor = 0
    while (position := rendered.text.find(quote, cursor)) != -1:
        cursor = position + 2
        if position % 2:
            continue
        start, end = position // 2, (position + len(quote)) // 2
        if bounds is not None and not (bounds[0] <= start < end <= bounds[1]):
            continue
        left = _normalized(rendered.slice(max(0, start - 400), start))
        right = _normalized(rendered.slice(end, end + 400))
        score = (
            _shared_length(left, prefix, suffix=True)
            + _shared_length(right, suffix)
        )
        exact = (
            start == annotation.start_offset and end == annotation.end_offset
            and (not prefix or left.endswith(prefix))
            and (not suffix or right.startswith(suffix))
        )
        matches.append((score, exact, start, end))
    if not matches:
        return None
    exact = [item for item in matches if item[1]]
    if len(exact) == 1:
        return exact[0][2:]
    if (
        len(matches) == 1 and not prefix and not suffix
        and sum(char.isalnum() for char in annotation.quote) >= 32
    ):
        return matches[0][2:]
    matches.sort(reverse=True)
    if matches[0][0] < 16:
        return None
    if len(matches) > 1 and matches[0][0] == matches[1][0]:
        return None
    return matches[0][2:]


def _public_paths(prompt):
    return {
        prompt_detail_url(prompt), reverse("study:review"),
        reverse("study:part_review", args=["eo"]),
        reverse("study:response_detail", args=["eo", prompt.theme.task.slug, prompt.pk]),
        reverse("study:task_review", args=["eo", prompt.theme.task.slug]),
    }


def capture_public_response_anchor(annotation):
    """Bind only a selection verified against the currently published EO3 text."""
    match = PUBLIC_KEY.fullmatch(annotation.source_key)
    if not annotation.quote or match is None or not (
        match["model"] or match["digest"] in PUBLIC_DIGESTS
    ) or match["surface"] == ":front":
        return {}
    prompt = Prompt.objects.filter(
        content_key=match["prompt"], is_active=True, response__is_active=True,
        theme__task__part__slug="eo", theme__task__slug="tache-3",
    ).select_related("response", "theme__task__part", "family").first()
    if (
        prompt is None or annotation.task_id not in {None, prompt.theme.task_id}
        or annotation.source_path.split("?", 1)[0] not in _public_paths(prompt)
    ):
        return {}
    content = _current_content(prompt, annotation.user)
    if content is None:
        return {}
    rendered = render_current_response(
        prompt, content, "back" if match["surface"] == ":back" else "detail",
        annotation.user,
    )
    return capture_rendered_response_anchor(annotation, rendered)


def capture_rendered_response_anchor(annotation, rendered):
    """Do not infer an old field from a unique quote or generic section labels."""
    start, end = annotation.start_offset, annotation.end_offset
    if (
        start is None or end is None or rendered.slice(start, end) != annotation.quote
        or not annotation.quote
        or rendered.slice(max(0, start - 160), start) != annotation.prefix
        or rendered.slice(end, end + 160) != annotation.suffix
    ):
        return {}
    return response_field_anchor(rendered, (start, end))


def _annotations_for_update(user, source_filter):
    return Annotation.objects.select_for_update(of=("self",)).filter(
        source_filter,
        Q(task__isnull=True) | Q(task__part__slug="eo", task__slug__in=("tache-2", "tache-3")),
        user=user, source_key__startswith="response:", hidden_on_source=False,
    ).order_by("pk")


def preserve_public_response_annotations(user, source_filter):
    """Retarget this user's existing records; never replace notes or private text."""
    unresolved = set()
    with transaction.atomic():
        annotations = list(_annotations_for_update(user, source_filter))
        candidates = {}
        for annotation in annotations:
            match = PUBLIC_KEY.fullmatch(annotation.source_key)
            if match is not None and (
                match["model"] or match["digest"] in PUBLIC_DIGESTS
            ):
                candidates.setdefault(match["prompt"], []).append((annotation, match["surface"] or ""))
        if not candidates:
            return unresolved
        prompts = Prompt.objects.filter(
            content_key__in=candidates, is_active=True, response__is_active=True,
            theme__task__part__slug="eo", theme__task__slug__in=("tache-2", "tache-3"),
        ).select_related("response", "theme__task__part", "family")
        for prompt in prompts:
            content = _current_content(prompt, user)
            if content is None:
                continue
            key = variant_annotation_key(prompt, content)
            paths = _public_paths(prompt)
            rendered_surfaces = {}
            for annotation, suffix in candidates[prompt.content_key]:
                if annotation.source_path.split("?", 1)[0] not in paths:
                    continue
                target = key + suffix
                if not annotation.quote and annotation.kind == AnnotationKind.NOTE:
                    values = {"source_key": target}
                else:
                    surface = suffix.removeprefix(":") or "detail"
                    if surface not in rendered_surfaces:
                        rendered_surfaces[surface] = render_current_response(
                            prompt, content, surface, user,
                        )
                    rendered = rendered_surfaces[surface]
                    offsets = current_anchor(annotation, rendered)
                    if offsets is None:
                        if annotation.source_key == target:
                            unresolved.add(annotation.pk)
                        continue
                    start, end = offsets
                    values = {
                        "source_key": target,
                        "start_offset": start, "end_offset": end,
                        "prefix": rendered.slice(max(0, start - 160), start),
                        "suffix": rendered.slice(end, end + 160),
                    }
                    # Unscoped legacy rows require complete current-context proof
                    # before acquiring a field identity.
                    anchor = (
                        response_field_anchor(rendered, offsets)
                        if annotation.response_anchor
                        else capture_rendered_response_anchor(annotation, rendered)
                    )
                    if anchor:
                        values["response_anchor"] = anchor
                changed = {
                    name: value for name, value in values.items()
                    if getattr(annotation, name) != value
                }
                if not changed:
                    continue
                if set(changed) == {"response_anchor"}:
                    Annotation.objects.filter(pk=annotation.pk).update(**changed)
                    continue
                if annotation.kind == AnnotationKind.HIGHLIGHT:
                    _move_anchor(annotation, values)
                else:
                    values["updated_at"] = timezone.now()
                    Annotation.objects.filter(pk=annotation.pk).update(**values)
    return unresolved


def preserve_prompt_annotations(user, prompt):
    if (
        prompt.theme.task.part.slug == "eo"
        and prompt.theme.task.slug in ("tache-2", "tache-3")
    ):
        preserve_public_response_annotations(
            user, Q(source_key__startswith=f"response:{prompt.content_key}:"),
        )
