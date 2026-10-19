"""Keep EE1 selections on the same, current writing response."""

import re

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import Annotation, AnnotationKind, PersonalWritingResponse, WritingSujet
from .oral_highlights import AnnotationRootText, _move_anchor, _project_unchanged_annotation
from .public_response_annotations import current_anchor
from .templatetags.study_markdown import render_markdown_prose
from .writing_responses import overrides_by_sujet, replaced_model_key, writing_model_versions


WRITING_KEY = re.compile(r"writing-sujet:(?P<sujet>\d+):(?P<version>personal|model-[1-9]\d*)")


def rendered_writing_body(body):
    return AnnotationRootText(
        f"<div data-annotation-root>{render_markdown_prose(body)}</div>"
    )


def _save_anchor(annotation, values):
    if all(getattr(annotation, name) == value for name, value in values.items()):
        return
    if annotation.kind == AnnotationKind.HIGHLIGHT:
        _move_anchor(annotation, values)
    else:
        Annotation.objects.filter(pk=annotation.pk).update(**values, updated_at=timezone.now())


def _anchor_values(key, rendered, offsets):
    start, end = offsets
    return {
        "source_key": key, "start_offset": start, "end_offset": end,
        "prefix": rendered.slice(max(0, start - 160), start),
        "suffix": rendered.slice(end, end + 160),
    }


@transaction.atomic
def preserve_edited_writing_annotations(user, sujet, key, before_body, after_body):
    """Project selections through a known edit, without storing response history."""
    if before_body == after_body:
        return
    before, after = rendered_writing_body(before_body), rendered_writing_body(after_body)
    annotations = Annotation.objects.select_for_update(of=("self",)).filter(
        Q(task_id=sujet.task_id) | Q(task_id__isnull=True),
        user=user, source_key=key,
    ).order_by("pk")
    for annotation in annotations:
        if not annotation.quote:
            continue
        offsets = _project_unchanged_annotation(
            annotation, before, after, validate_context=True,
        )
        if (
            offsets is not None
            and before.text.count(annotation.quote.encode("utf-16-le")) > 1
            and current_anchor(annotation, after) != offsets
        ):
            continue
        if offsets is not None:
            _save_anchor(annotation, _anchor_values(key, after, offsets))


@transaction.atomic
def preserve_ee1_response_annotations(user, source_filter):
    """Recover unchanged selections from a former copy; retain all other Notes."""
    annotations = list(
        Annotation.objects.select_for_update(of=("self",)).filter(
            source_filter, user=user, source_key__startswith="writing-sujet:",
        ).order_by("pk")
    )
    grouped = {}
    for annotation in annotations:
        match = WRITING_KEY.fullmatch(annotation.source_key)
        if match is not None:
            grouped.setdefault(int(match["sujet"]), []).append((annotation, match["version"]))
    if not grouped:
        return set()
    sujets = list(WritingSujet.objects.filter(
        pk__in=grouped, is_active=True, task__part__slug="ee", task__slug="tache-1",
    ))
    personal = {
        item.sujet_id: item
        for item in PersonalWritingResponse.objects.filter(user=user, sujet__in=sujets)
    }
    overrides = overrides_by_sujet(user, [sujet.pk for sujet in sujets])
    unresolved = set()
    for sujet in sujets:
        versions = writing_model_versions(sujet, overrides.get(sujet.pk, {}))
        bodies = {f"model-{item['number']}": item["content"]["body"] for item in versions}
        own = personal.get(sujet.pk)
        replaced = replaced_model_key(
            sujet.model_versions, overrides.get(sujet.pk, {}), has_personal=own is not None,
        )
        if own is not None:
            bodies["personal"] = own.body
        rendered = {}
        for annotation, version in grouped[sujet.pk]:
            if annotation.task_id not in {None, sujet.task_id}:
                continue
            target_version = "personal" if version == "model-1" and replaced else version
            body = bodies.get(target_version)
            if body is None:
                continue
            target = f"writing-sujet:{sujet.pk}:{target_version}"
            if not annotation.quote and annotation.kind == AnnotationKind.NOTE:
                _save_anchor(annotation, {"source_key": target})
                continue
            if target_version not in rendered:
                rendered[target_version] = rendered_writing_body(body)
            text = rendered[target_version]
            offsets = current_anchor(annotation, text)
            if offsets is None:
                unresolved.add(annotation.pk)
                continue
            _save_anchor(annotation, _anchor_values(target, text, offsets))
    return unresolved
