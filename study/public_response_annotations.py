"""Keep selections on each learner's current EO2/EO3 response."""

from contextlib import contextmanager
from copy import copy
import hashlib
import logging
import re
from types import SimpleNamespace

from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import Annotation, AnnotationKind, OralStateSnapshot, Prompt
from .oral_highlights import AnnotationRootText, _move_anchor, _render_questions
from .oral_history import legacy_variant_annotation_key, variant_annotation_key
from .progress import subject_progress_by_response
from .public_annotation_migration import PUBLIC_DIGESTS
from .querysets import lean_prompt_rows
from .response_personalization import effective_response
from .routing import prompt_detail_url
from .tache_three_models import annotation_arguments, reviewed_model
from .tache_two_dialogues import dialogue_response, published_dialogue


PUBLIC_KEY = re.compile(
    r"^response:(?P<prompt>.+):(?:(?P<model>model)|variant-(?P<digest>[0-9a-f]{16}))"
    r"(?P<surface>:(?:front|back|position))?$"
)
CONTEXT_LABELS = re.compile(
    r"\b(?:Arguments développés|Exemple concret|Développement|Conséquence|"
    r"Introduction|Conclusion|Nuance)\b",
)
logger = logging.getLogger(__name__)


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
        return (
            effective_response(prompt.response, user, prompt=prompt)
            if model is not None else None
        )
    return None


def render_current_response(prompt, content, surface, user, *, legacy_personal=False):
    if surface == "position":
        return AnnotationRootText(render_to_string(
            "study/partials/eo3_position.html",
            {
                "position": content.position,
                "position_annotation_key": variant_annotation_key(prompt, content),
            },
        ))
    prompts = list(lean_prompt_rows(prompt.response.prompts.filter(is_active=True)))
    is_eo2 = prompt.theme.task.slug == "tache-2"
    if is_eo2 and surface != "front":
        return _render_questions(prompt, content, surface, prompts)
    context = {
        "part": prompt.theme.task.part, "task": prompt.theme.task,
        "selected_prompt": prompt, "canonical_prompt": prompt,
        "response": prompt.response, "response_content": content,
        "arguments": annotation_arguments(prompt, content),
        "reviewed_eo3": not is_eo2 and not content.is_personal,
        "structured_eo3": not is_eo2 and not legacy_personal,
        "eo3_annotation_fields": not is_eo2,
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
    """Bind only a selection verified against the learner's current EO3 text."""
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
        prompt, content, match["surface"].removeprefix(":") if match["surface"] else "detail",
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


def _legacy_personal_contents(prompt, user, content, keys):
    """Prove old private namespaces from owned data, not from a public allowlist."""
    known = {}
    if content.is_personal:
        key = legacy_variant_annotation_key(prompt, content)
        if key in keys:
            known[key] = content
    if not keys or keys <= known.keys():
        return known
    snapshots = OralStateSnapshot.objects.filter(
        Q(response=prompt.response) | Q(response__semantic_owner=prompt.response),
        user=user, kind="personal",
    ).order_by("-pk").values_list("pk", "payload")
    for snapshot_id, payload in snapshots.iterator(chunk_size=32):
        try:
            fields = payload["fields"]
            old = effective_response(
                prompt.response, user, prompt=prompt, personal=SimpleNamespace(**fields),
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            logger.warning("Invalid legacy EO3 response snapshot %s", snapshot_id)
            continue
        key = legacy_variant_annotation_key(prompt, old)
        if key in keys:
            known.setdefault(key, old)
        if keys <= known.keys():
            break
    return known


def _legacy_selection(annotation, rendered):
    start, end = annotation.start_offset, annotation.end_offset
    if (
        start is None or end is None
        or rendered.slice(start, end) != annotation.quote
        or rendered.slice(max(0, start - 160), start) != annotation.prefix
        or rendered.slice(end, end + 160) != annotation.suffix
    ):
        return None
    bound = copy(annotation)
    bound.response_anchor = response_field_anchor(rendered, (start, end))
    return bound


def preserve_public_response_annotations(user, source_filter):
    """Retarget this user's existing records; never replace notes or private text."""
    unresolved = set()
    with transaction.atomic():
        annotations = list(_annotations_for_update(user, source_filter))
        candidates = {}
        for annotation in annotations:
            match = PUBLIC_KEY.fullmatch(annotation.source_key)
            if match is not None:
                candidates.setdefault(match["prompt"], []).append((annotation, match))
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
            prompt_candidates = [
                (annotation, match)
                for annotation, match in candidates[prompt.content_key]
                if annotation.source_path.split("?", 1)[0] in paths
                and annotation.task_id in {None, prompt.theme.task_id}
            ]
            private_keys = {
                f"response:{prompt.content_key}:variant-{match['digest']}"
                for _, match in prompt_candidates
                if not match["model"] and match["digest"] not in PUBLIC_DIGESTS
            }
            legacy_contents = (
                _legacy_personal_contents(prompt, user, content, private_keys)
                if prompt.theme.task.slug == "tache-3" else {}
            )
            legacy_surfaces = {}
            for annotation, match in prompt_candidates:
                suffix = match["surface"] or ""
                public = match["model"] or match["digest"] in PUBLIC_DIGESTS
                legacy_key = annotation.source_key.removesuffix(suffix) if suffix else annotation.source_key
                if not public and legacy_key not in legacy_contents:
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
                    bound = annotation
                    if (
                        match["model"] and content.is_personal
                        and prompt.theme.task.slug == "tache-3"
                        and not annotation.response_anchor
                    ):
                        original_surface = ("model", surface)
                        if original_surface not in legacy_surfaces:
                            model = reviewed_model(prompt.response, prompt)
                            legacy_surfaces[original_surface] = render_current_response(
                                prompt, model.response, surface, user,
                            )
                        bound = _legacy_selection(annotation, legacy_surfaces[original_surface])
                        if bound is None:
                            private_surface = ("personal", surface)
                            if private_surface not in legacy_surfaces:
                                legacy_surfaces[private_surface] = render_current_response(
                                    prompt, content, surface, user, legacy_personal=True,
                                )
                            bound = _legacy_selection(
                                annotation, legacy_surfaces[private_surface],
                            ) or annotation
                    elif not public:
                        legacy_surface = (legacy_key, surface)
                        if legacy_surface not in legacy_surfaces:
                            legacy_surfaces[legacy_surface] = render_current_response(
                                prompt, legacy_contents[legacy_key], surface, user,
                                legacy_personal=True,
                            )
                        bound = _legacy_selection(annotation, legacy_surfaces[legacy_surface])
                        if bound is None:
                            continue
                    if (
                        prompt.theme.task.slug == "tache-3"
                        and isinstance(bound.response_anchor, dict)
                        and bound.response_anchor.get("field") == "position"
                    ):
                        target = key + ":position"
                        if "position" not in rendered_surfaces:
                            rendered_surfaces["position"] = render_current_response(
                                prompt, content, "position", user,
                            )
                        rendered = rendered_surfaces["position"]
                    offsets = current_anchor(bound, rendered)
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
                        if bound.response_anchor
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


@contextmanager
def preserve_eo3_response_annotations(response, user):
    prompts = list(response.prompts.filter(is_active=True).select_related(
        "response", "theme__task__part", "family",
    ))
    for prompt in prompts:
        preserve_prompt_annotations(user, prompt)
    yield
    for prompt in prompts:
        preserve_prompt_annotations(user, prompt)
