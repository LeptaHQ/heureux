"""Point Tâche 2 annotations at the subject deck they now share."""

import re

from django.db import migrations


TACHE_TWO_SOURCE_RE = re.compile(
    r"^tache-two:(?P<month>[a-z0-9-]+):batch-(?P<batch>\d+):"
    r"subject-(?P<subject>\d+)$"
)
HIGHLIGHT_TEXT_FIELDS = (
    "title",
    "body",
    "quote",
    "source_title",
    "prefix",
    "suffix",
)


def _subject_content_key(month, batch, subject):
    return f"tache2:{month}:batch-{int(batch):02d}:subject-{int(subject):02d}"


def _annotation_key(subject_content_key):
    _, month, batch, subject = subject_content_key.split(":")
    return (
        f"tache-two:{month}:batch-{int(batch.removeprefix('batch-'))}:"
        f"subject-{int(subject.removeprefix('subject-'))}"
    )


def merge_highlights(Annotation, survivor, duplicate):
    newer, older = (
        (duplicate, survivor)
        if duplicate.updated_at > survivor.updated_at
        else (survivor, duplicate)
    )
    updates = {
        field: getattr(newer, field) or getattr(older, field)
        for field in HIGHLIGHT_TEXT_FIELDS
    }
    updates.update(
        {
            "task_id": newer.task_id or older.task_id,
            "study_later": survivor.study_later or duplicate.study_later,
            "created_at": min(survivor.created_at, duplicate.created_at),
            "updated_at": max(survivor.updated_at, duplicate.updated_at),
        }
    )
    Annotation.objects.filter(pk=survivor.pk).update(**updates)
    duplicate.delete()


def _key_by_subject_key(apps, canonical_only):
    """Map every Tâche 2 annotation key onto the key of its shared deck."""
    Prompt = apps.get_model("study", "Prompt")
    rows = Prompt.objects.filter(
        content_key__startswith="tache2:",
    ).values_list("content_key", "response_id", "is_canonical")
    canonical_by_response = {
        response_id: content_key
        for content_key, response_id, is_canonical in rows
        if is_canonical
    }
    mapping = {}
    for content_key, response_id, _is_canonical in rows:
        target = canonical_by_response.get(response_id)
        if target is None or (canonical_only and target == content_key):
            continue
        mapping[_annotation_key(content_key)] = _annotation_key(target)
    return mapping


def _rewrite_source_keys(apps, mapping):
    Annotation = apps.get_model("study", "Annotation")
    if not mapping:
        return
    for annotation in Annotation.objects.filter(
        source_key__startswith="tache-two:",
    ).iterator():
        source_key = mapping.get(annotation.source_key)
        if source_key is None or source_key == annotation.source_key:
            continue

        duplicate = None
        if annotation.kind == "highlight":
            duplicate = (
                Annotation.objects.filter(
                    kind="highlight",
                    user_id=annotation.user_id,
                    source_path=annotation.source_path,
                    source_key=source_key,
                    start_offset=annotation.start_offset,
                    end_offset=annotation.end_offset,
                )
                .exclude(pk=annotation.pk)
                .first()
            )
        if duplicate:
            merge_highlights(Annotation, duplicate, annotation)
        else:
            Annotation.objects.filter(pk=annotation.pk).update(
                source_key=source_key
            )


def share_tache_two_annotation_keys(apps, schema_editor):
    _rewrite_source_keys(apps, _key_by_subject_key(apps, canonical_only=True))


def restore_per_subject_annotation_keys(apps, schema_editor):
    """Re-anchor each annotation on the subject page it was taken from."""
    Annotation = apps.get_model("study", "Annotation")
    Prompt = apps.get_model("study", "Prompt")
    key_by_content_key = {
        content_key: _annotation_key(content_key)
        for content_key in Prompt.objects.filter(
            content_key__startswith="tache2:",
        ).values_list("content_key", flat=True)
    }
    path_re = re.compile(
        r"^/expression/(?:orale|ecrite)/[-a-zA-Z0-9_]+/"
        r"sujets/(?P<month>[a-z0-9-]+)/batch-(?P<batch>\d+)/"
        r"(?P<subject>\d+)/$"
    )
    for annotation in Annotation.objects.filter(
        source_key__startswith="tache-two:",
    ).iterator():
        match = path_re.fullmatch(annotation.source_path.split("?", 1)[0])
        if match is None:
            continue
        source_key = key_by_content_key.get(
            _subject_content_key(
                match.group("month"),
                match.group("batch"),
                match.group("subject"),
            )
        )
        if source_key is None or source_key == annotation.source_key:
            continue
        Annotation.objects.filter(pk=annotation.pk).update(
            source_key=source_key
        )


class Migration(migrations.Migration):
    dependencies = [
        ("study", "0039_writing_sujet_completion"),
    ]

    operations = [
        migrations.RunPython(
            share_tache_two_annotation_keys,
            restore_per_subject_annotation_keys,
        ),
    ]
