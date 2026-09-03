"""Keep private study data attached while equivalent Tâche 2 decks are merged."""

import re

from django.db import migrations
from django.db.models import Q


PHRASE_SOURCE_RE = re.compile(
    r"^phrase:(?P<phrase_id>[^:]+)(?P<suffix>:.*)?$"
)
HIGHLIGHT_TEXT_FIELDS = (
    "title",
    "body",
    "quote",
    "source_title",
    "prefix",
    "suffix",
)
RESPONSE_KEY_MERGES = {
    "tache2:mai:batch-05:subject-25": "tache2:fevrier:batch-06:subject-26",
    "tache2:novembre:batch-01:subject-01": (
        "tache2:fevrier:batch-02:subject-08"
    ),
    "tache2:decembre:batch-10:subject-48": (
        "tache2:octobre:batch-04:subject-17"
    ),
    "tache2:decembre:batch-04:subject-16": (
        "tache2:juillet:batch-02:subject-09"
    ),
    "tache2:decembre:batch-10:subject-46": (
        "tache2:fevrier:batch-01:subject-02"
    ),
    "tache2:octobre:batch-03:subject-12": "tache2:mai:batch-02:subject-06",
    "tache2:octobre:batch-05:subject-24": (
        "tache2:juillet:batch-02:subject-08"
    ),
    "tache2:octobre:batch-06:subject-30": (
        "tache2:janvier:batch-03:subject-14"
    ),
    "tache2:decembre:batch-01:subject-04": (
        "tache2:juillet:batch-08:subject-38"
    ),
    "tache2:juillet:batch-02:subject-06": (
        "tache2:fevrier:batch-01:subject-04"
    ),
    "tache2:juillet:batch-04:subject-18": "tache2:juin:batch-06:subject-30",
}
PHRASE_PREFIX_MERGES = {
    "T2M5S25": "T2F2S26",
    "T2N11S1": "T2F2S8",
    "T2D12S48": "T2O10S17",
    "T2D12S16": "T2J7S9",
    "T2D12S46": "T2F2S2",
    "T2O10S12": "T2M5S6",
    "T2O10S24": "T2J7S8",
    "T2O10S30": "T2J1S14",
    "T2D12S4": "T2J7S38",
    "T2J7S6": "T2F2S4",
    "T2J7S18": "T2J6S30",
}
PHRASE_ID_EXCEPTIONS = {
    "T2J7S6V03": "T2F2S4V03R",
    "T2J7S6V04": "T2F2S4V04R",
    "T2J7S6V05": "T2F2S4V05R",
    "T2J7S6V08": "T2F2S4V08R",
    "T2J7S6V13": "T2F2S4V13R",
    "T2J7S6V17": "T2F2S4V17R",
    "T2J7S6V18": "T2F2S4V18R",
    "T2J7S6V23": "T2F2S4V23R",
    "T2J7S6V28": "T2F2S4V28R",
    "T2J7S6V29": "T2F2S4V29R",
}


def _annotation_key(subject_content_key):
    _, month, batch, subject = subject_content_key.split(":")
    return (
        f"tache-two:{month}:batch-{int(batch.removeprefix('batch-'))}:"
        f"subject-{int(subject.removeprefix('subject-'))}"
    )


SUBJECT_KEY_MERGES = {
    _annotation_key(source): _annotation_key(target)
    for source, target in RESPONSE_KEY_MERGES.items()
}


def _merge_highlights(Annotation, survivor, duplicate):
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


def _target_source_key(source_key):
    if source_key in SUBJECT_KEY_MERGES:
        return SUBJECT_KEY_MERGES[source_key]
    for source_response, target_response in RESPONSE_KEY_MERGES.items():
        prefix = f"response:{source_response}"
        if source_key == prefix or source_key.startswith(f"{prefix}:"):
            return f"response:{target_response}{source_key[len(prefix):]}"
    phrase_match = PHRASE_SOURCE_RE.fullmatch(source_key)
    if phrase_match is None:
        return None
    phrase_id = phrase_match.group("phrase_id")
    if phrase_id in PHRASE_ID_EXCEPTIONS:
        target_id = PHRASE_ID_EXCEPTIONS[phrase_id]
        return f"phrase:{target_id}{phrase_match.group('suffix') or ''}"
    for source_prefix, target_prefix in PHRASE_PREFIX_MERGES.items():
        if phrase_id.startswith(f"{source_prefix}V"):
            target_id = target_prefix + phrase_id.removeprefix(source_prefix)
            return f"phrase:{target_id}{phrase_match.group('suffix') or ''}"
    return None


def preserve_equivalent_group_annotations(apps, schema_editor):
    Annotation = apps.get_model("study", "Annotation")
    annotations = Annotation.objects.filter(
        Q(source_key__startswith="tache-two:")
        | Q(source_key__startswith="phrase:")
        | Q(source_key__startswith="response:tache2:")
    )
    for annotation in annotations.iterator():
        source_key = _target_source_key(annotation.source_key)
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
            _merge_highlights(Annotation, duplicate, annotation)
        else:
            Annotation.objects.filter(pk=annotation.pk).update(
                source_key=source_key
            )


def preserve_equivalent_group_personal_responses(apps, schema_editor):
    PersonalResponse = apps.get_model("study", "PersonalResponse")
    Response = apps.get_model("study", "Response")
    responses = Response.objects.in_bulk(
        {
            *RESPONSE_KEY_MERGES,
            *RESPONSE_KEY_MERGES.values(),
        },
        field_name="content_key",
    )
    content_fields = (
        "reformulation",
        "position",
        "position_claire",
        "arguments",
        "nuance",
        "conclusion",
    )
    for source_key, target_key in RESPONSE_KEY_MERGES.items():
        source = responses.get(source_key)
        target = responses.get(target_key)
        if source is None or target is None:
            continue
        source_versions = PersonalResponse.objects.filter(
            response_id=source.pk
        ).order_by("pk")
        for source_version in source_versions:
            target_version = PersonalResponse.objects.filter(
                user_id=source_version.user_id,
                response_id=target.pk,
            ).first()
            if target_version is None:
                PersonalResponse.objects.filter(pk=source_version.pk).update(
                    response_id=target.pk
                )
                continue
            if source_version.updated_at <= target_version.updated_at:
                continue
            updates = {
                field: getattr(source_version, field)
                for field in content_fields
            }
            updates.update(
                {
                    "created_at": min(
                        source_version.created_at,
                        target_version.created_at,
                    ),
                    "updated_at": source_version.updated_at,
                }
            )
            PersonalResponse.objects.filter(pk=target_version.pk).update(
                **updates
            )


class Migration(migrations.Migration):
    dependencies = [
        ("study", "0043_comprehension_question_study"),
    ]

    operations = [
        migrations.RunPython(
            preserve_equivalent_group_annotations,
            migrations.RunPython.noop,
        ),
        migrations.RunPython(
            preserve_equivalent_group_personal_responses,
            migrations.RunPython.noop,
        ),
    ]
