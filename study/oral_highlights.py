"""Carry EO2 selections across edits without reusing anchors on changed text."""

from contextlib import contextmanager
from difflib import SequenceMatcher
from html.parser import HTMLParser

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import Annotation, AnnotationKind
from .oral_history import variant_annotation_key
from .response_personalization import effective_response
from .routing import TACHE_TWO_PROMPT_KEY, prompt_detail_url


class QuestionText(HTMLParser):
    """Read the actual template's text offsets in browser UTF-16 units."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.length = 0
        self.stack = []
        self.fields = {}
        self.container = None
        self.feed(html)
        self.text = b"".join(self.parts)
        if self.container is not None:
            start, end = self.container
            self.text = self.text[start * 2:end * 2]
            self.fields = {
                key: (left - start, right - start)
                for key, (left, right) in self.fields.items()
            }

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "hr", "img", "input", "meta", "link", "wbr"}:
            return
        attrs = dict(attrs)
        field = next(
            (
                (int(attrs[name]), kind)
                for name, kind in (
                    ("data-question-highlight-text", "question"),
                    ("data-question-highlight-response", "response"),
                )
                if name in attrs
            ),
            None,
        )
        self.stack.append((field, "data-annotation-root" in attrs, self.length))

    def handle_endtag(self, tag):
        if tag in {"br", "hr", "img", "input", "meta", "link", "wbr"}:
            return
        field, container, start = self.stack.pop()
        if field is not None:
            self.fields[field] = (start, self.length)
        if container:
            self.container = (start, self.length)

    def handle_data(self, data):
        encoded = data.encode("utf-16-le")
        self.parts.append(encoded)
        self.length += len(encoded) // 2

    def slice(self, start, end):
        return self.text[start * 2:end * 2].decode("utf-16-le", errors="ignore")


def _render_questions(prompt, content, surface, prompts):
    if surface == "back":
        return QuestionText(render_to_string("study/partials/card_back.html", {
            "kind": "spine",
            "tache_two_subject": True,
            "arguments": content.arguments,
            "aliases": [item for item in prompts if item.pk != prompt.pk],
            "canonical_prompt": prompt,
            "detail_url": prompt_detail_url(prompt),
        }))
    return QuestionText(render_to_string("study/partials/tache_two_questions.html", {
        "subject_questions": [
            {"number": index, "text": arg.idea, "response": arg.developpement}
            for index, arg in enumerate(content.arguments, 1)
        ],
    }))


def _matching_fields(before, after, old, new, question_mapping=None):
    before_rows = [(arg.idea, arg.developpement) for arg in before.arguments]
    after_rows = [(arg.idea, arg.developpement) for arg in after.arguments]
    if question_mapping is not None:
        pairs = question_mapping
    elif len(before_rows) == len(after_rows):
        pairs = {index: index for index in range(1, len(before_rows) + 1)}
    else:
        pairs = {
            block.a + offset + 1: block.b + offset + 1
            for block in SequenceMatcher(None, before_rows, after_rows, autojunk=False).get_matching_blocks()
            for offset in range(block.size)
        }
    # A row can keep its question while only its prepared answer changes (or vice versa).
    used = set(pairs.values())
    if question_mapping is None:
        for index in range(1, min(len(before_rows), len(after_rows)) + 1):
            if index not in pairs and index not in used:
                pairs[index] = index
    result = {}
    for (number, field), old_span in old.fields.items():
        new_span = new.fields.get((pairs.get(number), field))
        if new_span is not None and old.slice(*old_span) == new.slice(*new_span):
            result[(number, field)] = (old_span, new_span)
    return result


def _project(annotation, old, new, fields):
    start, end = annotation.start_offset, annotation.end_offset
    if start is None or end is None or old.slice(start, end) != annotation.quote:
        return None
    intersected = {
        key for key, (left, right) in old.fields.items()
        if left < end and right > start
    }
    if not intersected or not intersected <= fields.keys():
        return None
    starts = [
        new_span[0] + start - old_span[0]
        for old_span, new_span in fields.values() if old_span[0] <= start < old_span[1]
    ]
    ends = [
        new_span[0] + end - old_span[0]
        for old_span, new_span in fields.values() if old_span[0] < end <= old_span[1]
    ]
    if not starts or not ends or new.slice(starts[0], ends[0]) != annotation.quote:
        return None
    return starts[0], ends[0]


@contextmanager
def preserve_tache_two_highlights(response, user, *, question_mapping=None):
    with transaction.atomic():
        if not response.semantic_group:
            yield
            return
        prompts = list(response.prompts.filter(is_active=True).select_related(
            "theme__task__part", "family", "response",
        ))
        paths = {}
        source_filter = Q(pk__in=[])
        review_paths = {
            reverse("study:review"),
            reverse("study:task_review", args=["eo", "tache-2"]),
        }
        review_filter = Q(pk__in=[])
        for path in review_paths:
            review_filter |= Q(source_path=path) | Q(source_path__startswith=f"{path}?")
        for prompt in prompts:
            prompt_paths = [prompt_detail_url(prompt)]
            match = TACHE_TWO_PROMPT_KEY.fullmatch(prompt.content_key)
            if match:
                prompt_paths.append(reverse("study:task_subject_detail", args=[
                    "eo", "tache-2", match["month"], int(match["batch"]), int(match["subject"]),
                ]))
            paths[prompt.pk] = set(prompt_paths) | review_paths
            for path in prompt_paths:
                source_filter |= Q(source_path=path) | Q(source_path__startswith=f"{path}?")
            source_filter |= review_filter & Q(
                source_key__startswith=f"response:{prompt.content_key}:variant-",
            )
        annotations = list(Annotation.objects.select_for_update().filter(
            source_filter, user=user, kind=AnnotationKind.HIGHLIGHT,
            start_offset__isnull=False, end_offset__isnull=False,
        ).order_by("pk"))
        if not annotations:
            yield
            return
        before = {
            prompt.pk: effective_response(response, user, prompt=prompt)
            for prompt in prompts
        }
        yield
        for prompt in prompts:
            after = effective_response(response, user, prompt=prompt)
            # Also recover unchanged model selections hidden by an earlier personalization.
            model = effective_response(response, user, prompt=prompt, model_only=True)
            versions = [(before[prompt.pk], question_mapping)]
            if model != before[prompt.pk] and len(model.arguments) == len(after.arguments):
                versions.append((model, None))
            for previous, mapping in versions:
                _carry_prompt_highlights(
                    prompt, previous, after, prompts, paths[prompt.pk], annotations, mapping,
                )


def _carry_prompt_highlights(prompt, before, after, prompts, paths, annotations, question_mapping):
    old_key = variant_annotation_key(prompt, before)
    new_key = variant_annotation_key(prompt, after)
    storage_key = prompt.model_content.get("storage_key", prompt.response.content_key)
    legacy_key = TACHE_TWO_PROMPT_KEY.fullmatch(storage_key)
    detail_keys = {old_key, f"response:{storage_key}"}
    if legacy_key:
        detail_keys.add(
            f"tache-two:{legacy_key['month']}:batch-{int(legacy_key['batch'])}"
            f":subject-{int(legacy_key['subject'])}"
        )
    # The review's prompt is independent of edits to its prepared questions.
    front_keys = {f"{old_key}:front", f"response:{storage_key}:front"}
    for annotation in annotations:
        if (
            annotation.source_path.split("?", 1)[0] in paths
            and annotation.source_key in front_keys
            and annotation.source_key != f"{new_key}:front"
        ):
            _move_anchor(annotation, {"source_key": f"{new_key}:front"})
    for surface, keys, target_key in (
        ("detail", detail_keys, new_key),
        ("back", {f"{old_key}:back", f"response:{storage_key}:back"}, f"{new_key}:back"),
    ):
        candidates = [
            item for item in annotations
            if item.source_path.split("?", 1)[0] in paths and item.source_key in keys
            and item.source_key != target_key
        ]
        if not candidates:
            continue
        old = _render_questions(prompt, before, surface, prompts)
        new = _render_questions(prompt, after, surface, prompts)
        fields = _matching_fields(before, after, old, new, question_mapping)
        for annotation in candidates:
            if annotation.source_key != old_key + (":back" if surface == "back" else ""):
                if (
                    annotation.prefix
                    and not old.slice(0, annotation.start_offset).endswith(annotation.prefix)
                    or annotation.suffix
                    and not old.slice(annotation.end_offset, len(old.text) // 2).startswith(annotation.suffix)
                ):
                    continue
            offsets = _project(annotation, old, new, fields)
            if offsets is None:
                continue
            start, end = offsets
            _move_anchor(annotation, {
                "source_key": target_key, "start_offset": start, "end_offset": end,
                "prefix": new.slice(max(0, start - 160), start),
                "suffix": new.slice(end, end + 160),
            })


def _move_anchor(annotation, values):
    target = Annotation.objects.filter(
        user_id=annotation.user_id, kind=AnnotationKind.HIGHLIGHT,
        source_path=annotation.source_path, source_key=values["source_key"],
        start_offset=values.get("start_offset", annotation.start_offset),
        end_offset=values.get("end_offset", annotation.end_offset),
    ).exclude(pk=annotation.pk)
    # An existing current anchor already displays the selection; retain both records.
    if target.exists():
        return
    values["updated_at"] = timezone.now()
    try:
        with transaction.atomic():
            Annotation.objects.filter(pk=annotation.pk).update(**values)
    except IntegrityError:
        if not target.exists():
            raise
        return
    for name, value in values.items():
        setattr(annotation, name, value)
