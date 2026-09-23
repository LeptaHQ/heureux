"""Carry EO2 selections across edits without reusing anchors on changed text."""

from contextlib import contextmanager
from difflib import SequenceMatcher
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urlsplit

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from . import catalogue
from . import content_loader as content_module
from .models import Annotation, AnnotationKind
from .oral_history import variant_annotation_key
from .response_personalization import effective_response
from .routing import TACHE_TWO_PROMPT_KEY, prompt_detail_url


_EE_TACHE_THREE_POSITION_PATTERN = re.compile(
    r"(?P<stance>Pour ma part,.*?)(?=\s+Tout d’abord,)"
    r"\s+(?P<argument_1>Tout d’abord,.*?)(?=\s+De plus,)"
    r"\s+(?P<argument_2>De plus,.*?)(?=\s+En conclusion,)"
    r"\s+(?P<conclusion>En conclusion,.*)"
)


def ee_tache_three_position_blocks(text):
    match = _EE_TACHE_THREE_POSITION_PATTERN.fullmatch(text)
    if not match:
        return ()
    return tuple(
        {
            "label": label,
            "text": match.group(group),
        }
        for label, group in (
            ("Position", "stance"),
            ("Argument 1", "argument_1"),
            ("Argument 2", "argument_2"),
            ("Conclusion", "conclusion"),
        )
    )


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


class AnnotationRootText(HTMLParser):
    """Read one annotation root while excluding its controls."""

    VOID_TAGS = {"br", "hr", "img", "input", "meta", "link", "wbr"}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []
        self.in_root = False
        self.feed(html)
        self.text = b"".join(self.parts)
        self.units = tuple(
            int.from_bytes(self.text[index:index + 2], "little")
            for index in range(0, len(self.text), 2)
        )

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID_TAGS:
            return
        attrs = dict(attrs)
        excluded = (
            (self.stack[-1][0] if self.stack else False)
            or "data-annotation-exclude" in attrs
        )
        is_root = "data-annotation-root" in attrs
        self.stack.append((excluded, is_root))
        if is_root:
            self.in_root = True

    def handle_endtag(self, tag):
        if tag in self.VOID_TAGS:
            return
        _excluded, is_root = self.stack.pop()
        if is_root:
            self.in_root = False

    def handle_data(self, data):
        if self.in_root and not (self.stack and self.stack[-1][0]):
            data = data.replace("\r\n", "\n").replace("\r", "\n")
            self.parts.append(data.encode("utf-16-le"))

    def slice(self, start, end):
        return self.text[start * 2:end * 2].decode("utf-16-le", errors="ignore")


def _ee_tache_three_root_context(prompt, content):
    source_row = catalogue.ee_tache_three_sources_by_key().get(prompt.content_key)
    if source_row is None:
        raise RuntimeError("EE Tâche 3 content is not synchronized")
    _month, source = source_row
    warnings = []
    if source.document1_invalid:
        warnings.append(
            "Le premier document publié est hors sujet ; la réponse "
            "s’appuie uniquement sur le document valide."
        )
    if source.document2_missing:
        warnings.append(
            "La source publique ne fournit pas de deuxième document."
        )
    if source.documents_identical:
        warnings.append(
            "La source publique a publié deux documents identiques."
        )
    if source.title_missing:
        warnings.append(
            "Le titre affiché a été déduit des documents, car la source "
            "n’en publie aucun."
        )
    copy_text = ""
    if content.position or content.position_claire:
        copy_text = content_module.ee_tache_three_answer_text(
            content.reformulation,
            content.position,
            content.position_claire,
        )
    return {
        "response_content": content,
        "selected_prompt": prompt,
        "task": prompt.theme.task,
        "part": prompt.theme.task.part,
        "can_edit_response": False,
        "ee_annotation_key": variant_annotation_key(prompt, content),
        "ee_annotation_legacy_keys": "",
        "ee_source_warnings": warnings,
        "source_documents_html": content_module._ee_tache_three_documents_html(
            (source.document1, source.document2)
        ),
        "ee_response_copy_text": copy_text,
        "ee_response_origin": (
            "author"
            if prompt.response.content_key
            in content_module.load_ee_tache_three_author_responses()
            else "original"
        ),
        "ee_position_blocks": ee_tache_three_position_blocks(
            content.position_claire
        ),
    }


def _render_ee_tache_three_root(prompt, content):
    return AnnotationRootText(
        render_to_string(
            "study/partials/ee_tache_three_annotation_root.html",
            _ee_tache_three_root_context(prompt, content),
        )
    )


def _render_response_review_root(prompt, content, surface, prompts, subject_progress):
    aliases = [item for item in prompts if item.pk != prompt.pk]
    context = {
        "kind": "spine",
        "kind_label": "Réponse argumentée",
        "theme": prompt.theme,
        "family": prompt.family,
        "family_label": prompt.family.name,
        "prompt": prompt.text,
        "canonical_prompt": prompt,
        "aliases": aliases,
        "response": prompt.response,
        "response_content": content,
        "arguments": content.arguments,
        "detail_url": prompt_detail_url(prompt),
        "subject_progress": subject_progress,
        "tache_two_subject": False,
    }
    return AnnotationRootText(
        '<div data-annotation-root>'
        + render_to_string(f"study/partials/card_{surface}.html", context)
        + "</div>"
    )


def _annotation_surface(annotation, legacy_key):
    if annotation.source_key == legacy_key:
        return "detail"
    for surface in ("front", "back"):
        if annotation.source_key == f"{legacy_key}:{surface}":
            return surface
    return None


def _legacy_prompt_order(
    annotation,
    prompts,
    selected_prompt,
    detail_paths,
    *,
    surface,
):
    by_id = {prompt.pk: prompt for prompt in prompts}
    parts = urlsplit(annotation.source_path)
    query_prompt = None
    values = parse_qs(parts.query).get("prompt", ())
    if values:
        try:
            query_prompt = by_id.get(int(values[-1]))
        except ValueError:
            pass
    review_prompt = None
    if surface != "detail" and query_prompt is None:
        theme_values = parse_qs(parts.query).get("theme", ())
        family_values = parse_qs(parts.query).get("family", ())
        review_prompt = next(
            (
                prompt
                for prompt in sorted(
                    prompts,
                    key=lambda item: (
                        item.theme.order,
                        item.number,
                        item.pk,
                    ),
                )
                if (
                    not theme_values
                    or prompt.theme.slug == theme_values[-1]
                )
                and (
                    not family_values
                    or prompt.family.slug == family_values[-1]
                )
            ),
            None,
        )
    path_prompt = next(
        (
            prompt
            for prompt in prompts
            if parts.path == detail_paths[prompt.pk]
        ),
        None,
    )
    preferred = []
    if query_prompt is not None:
        preferred.append(query_prompt)
    if review_prompt is not None:
        preferred.append(review_prompt)
    if path_prompt is not None and not path_prompt.is_canonical:
        preferred.append(path_prompt)
    if surface == "detail" and selected_prompt is not None:
        preferred.append(by_id.get(selected_prompt.pk))
    if path_prompt is not None:
        preferred.append(path_prompt)
    preferred.extend(
        sorted(
            prompts,
            key=lambda prompt: (
                not prompt.is_canonical,
                prompt.number,
                prompt.pk,
            ),
        )
    )
    result = []
    seen = set()
    for prompt in preferred:
        if prompt is not None and prompt.pk not in seen:
            result.append(prompt)
            seen.add(prompt.pk)
    return result


def _project_unchanged_annotation(
    annotation,
    old,
    new,
    *,
    validate_context=False,
):
    start, end = annotation.start_offset, annotation.end_offset
    if (
        start is None
        or end is None
        or old.slice(start, end) != annotation.quote
    ):
        return None
    if validate_context and (
        annotation.prefix
        and not old.slice(0, start).endswith(annotation.prefix)
        or annotation.suffix
        and not old.slice(end, len(old.units)).startswith(annotation.suffix)
    ):
        return None
    for block in SequenceMatcher(
        None,
        old.units,
        new.units,
        autojunk=False,
    ).get_matching_blocks():
        if block.a <= start and end <= block.a + block.size:
            new_start = block.b + start - block.a
            new_end = new_start + end - start
            if new.slice(new_start, new_end) == annotation.quote:
                return new_start, new_end
    return None


def _find_contextual_anchor(annotation, rendered):
    quote = annotation.quote.encode("utf-16-le")
    if not quote:
        return []

    def normalized(value):
        return re.sub(
            r"(?:À commencer|En cours|Terminé)",
            "<progress>",
            value,
        )

    matches = []
    offset = 0
    while True:
        byte_offset = rendered.text.find(quote, offset)
        if byte_offset < 0:
            break
        start = byte_offset // 2
        end = start + len(quote) // 2
        prefix_matches = bool(
            annotation.prefix
            and normalized(rendered.slice(0, start)).endswith(
                normalized(annotation.prefix)
            )
        )
        suffix_matches = bool(
            annotation.suffix
            and normalized(rendered.slice(end, len(rendered.units))).startswith(
                normalized(annotation.suffix)
            )
        )
        score = int(prefix_matches) + int(suffix_matches)
        if (
            not annotation.prefix
            and not annotation.suffix
            or score
        ):
            matches.append((start, end, score))
        offset = byte_offset + 2
    return matches


@contextmanager
def preserve_ee_tache_three_highlights(response, user, *, selected_prompt=None):
    """Carry EE3 anchors that remain inside unchanged rendered text."""
    with transaction.atomic():
        prompts = list(
            response.prompts.filter(
                is_active=True,
                theme__is_active=True,
            ).select_related(
                "theme__task__part",
                "family",
                "response",
            )
        )
        before = {
            prompt.pk: effective_response(response, user, prompt=prompt)
            for prompt in prompts
        }
        old_keys = {
            prompt.pk: variant_annotation_key(prompt, before[prompt.pk])
            for prompt in prompts
        }
        detail_paths = {
            prompt.pk: prompt_detail_url(prompt)
            for prompt in prompts
        }
        detail_filter = Q(pk__in=[])
        for path in detail_paths.values():
            detail_filter |= Q(source_path=path) | Q(
                source_path__startswith=f"{path}?"
            )
        review_paths = {
            reverse("study:review"),
            reverse("study:part_review", args=["ee"]),
            reverse("study:task_review", args=["ee", "tache-3"]),
        }
        review_filter = Q(pk__in=[])
        for path in review_paths:
            review_filter |= Q(source_path=path) | Q(
                source_path__startswith=f"{path}?"
            )
        detail_keys = set(old_keys.values())
        review_keys = {
            f"{key}:{surface}"
            for key in old_keys.values()
            for surface in ("front", "back")
        }
        include_legacy = (
            bool(before)
            and not next(iter(before.values())).is_personal
        )
        legacy_key = f"response:{response.content_key}"
        if include_legacy:
            detail_keys.add(legacy_key)
            review_keys.update(
                f"{legacy_key}:{surface}"
                for surface in ("front", "back")
            )
        annotations = list(
            Annotation.objects.select_for_update()
            .filter(
                (
                    detail_filter & Q(source_key__in=detail_keys)
                    | review_filter & Q(source_key__in=review_keys)
                ),
                user=user,
                kind=AnnotationKind.HIGHLIGHT,
                start_offset__isnull=False,
                end_offset__isnull=False,
            )
            .order_by("pk")
        )
        yield
        if not annotations:
            return
        after = {
            prompt.pk: effective_response(response, user, prompt=prompt)
            for prompt in prompts
        }
        from .progress import subject_progress_by_response

        progress = subject_progress_by_response(user, {response.pk})[response.pk]
        rendered = {
            prompt.pk: {
                "detail": (
                    _render_ee_tache_three_root(prompt, before[prompt.pk]),
                    _render_ee_tache_three_root(prompt, after[prompt.pk]),
                ),
                **{
                    surface: (
                        _render_response_review_root(
                            prompt,
                            before[prompt.pk],
                            surface,
                            prompts,
                            progress,
                        ),
                        _render_response_review_root(
                            prompt,
                            after[prompt.pk],
                            surface,
                            prompts,
                            progress,
                        ),
                    )
                    for surface in ("front", "back")
                },
            }
            for prompt in prompts
        }
        for prompt in prompts:
            new_key = variant_annotation_key(prompt, after[prompt.pk])
            for surface in ("detail", "front", "back"):
                suffix = "" if surface == "detail" else f":{surface}"
                old, new = rendered[prompt.pk][surface]
                candidates = [
                    annotation
                    for annotation in annotations
                    if annotation.source_key == old_keys[prompt.pk] + suffix
                ]
                for annotation in candidates:
                    if surface == "front":
                        _move_anchor(
                            annotation,
                            {"source_key": new_key + suffix},
                        )
                        continue
                    offsets = _project_unchanged_annotation(
                        annotation,
                        old,
                        new,
                    )
                    if offsets is None:
                        continue
                    start, end = offsets
                    _move_anchor(
                        annotation,
                        {
                            "source_key": new_key + suffix,
                            "start_offset": start,
                            "end_offset": end,
                            "prefix": new.slice(max(0, start - 160), start),
                            "suffix": new.slice(end, end + 160),
                        },
                    )
        if include_legacy:
            for annotation in annotations:
                surface = _annotation_surface(annotation, legacy_key)
                if surface is None:
                    continue
                suffix = "" if surface == "detail" else f":{surface}"
                prompt_order = _legacy_prompt_order(
                    annotation,
                    prompts,
                    selected_prompt,
                    detail_paths,
                    surface=surface,
                )
                if surface == "front":
                    matches = [
                        (score, prompt, start, end)
                        for prompt in prompt_order
                        for start, end, score in _find_contextual_anchor(
                            annotation,
                            rendered[prompt.pk][surface][0],
                        )
                    ]
                    if not matches:
                        continue
                    best_score = max(item[0] for item in matches)
                    best = [item for item in matches if item[0] == best_score]
                    query_values = parse_qs(
                        urlsplit(annotation.source_path).query
                    ).get("prompt", ())
                    explicit_prompt_id = None
                    if query_values:
                        try:
                            explicit_prompt_id = int(query_values[-1])
                        except ValueError:
                            pass
                    chosen = next(
                        (
                            item
                            for item in best
                            if item[1].pk == explicit_prompt_id
                        ),
                        best[0] if len(best) == 1 else None,
                    )
                    if chosen is None:
                        continue
                    _score, prompt, start, end = chosen
                    new = rendered[prompt.pk][surface][1]
                    _move_anchor(
                        annotation,
                        {
                            "source_key": variant_annotation_key(
                                prompt,
                                after[prompt.pk],
                            ) + suffix,
                            "start_offset": start,
                            "end_offset": end,
                            "prefix": new.slice(max(0, start - 160), start),
                            "suffix": new.slice(end, end + 160),
                        },
                    )
                    continue
                for prompt in prompt_order:
                    old, new = rendered[prompt.pk][surface]
                    offsets = _project_unchanged_annotation(
                        annotation,
                        old,
                        new,
                        validate_context=True,
                    )
                    if offsets is None:
                        continue
                    start, end = offsets
                    _move_anchor(
                        annotation,
                        {
                            "source_key": variant_annotation_key(
                                prompt,
                                after[prompt.pk],
                            ) + suffix,
                            "start_offset": start,
                            "end_offset": end,
                            "prefix": new.slice(max(0, start - 160), start),
                            "suffix": new.slice(end, end + 160),
                        },
                    )
                    break


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
