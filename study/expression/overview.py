"""Aggregate counts and progress rendered by EO/EE overview pages."""

from collections import Counter, defaultdict
from types import SimpleNamespace
from urllib.parse import urlsplit

from django.db import connection
from django.db.models import Case, Count, Max, Min, Q, Value, When

from study.catalogue import registry as catalogue
from study.catalogue import loader as content_loader
from study.expression.ee.formulations.catalogue import get_ee_formulations
from study.expression.ee.formulations.progress import FORMULATION_ENTRY_PATHS
from study.models import (
    Annotation, AnnotationKind, Card, CardState, CardType, MemoryQuestionProgress,
    PersonalWritingResponse, PhraseTier, Prompt, Response, WritingResponseOverride,
    WritingSujetCompletion,
)
from study.expression.eo.history import AnnotationPromptOwner, _annotation_prompt_key, annotation_owners
from study.review.progress import (
    EXPRESSION_PART_BY_PATH, PHRASE_SOURCE_RE, SUBJECT_PATH_RE,
    progress_summary, subject_highlight_times, writing_sujet_id_from_source_key,
)
from study.catalogue.retirement import retired_task_filter


def _values(rows, types):
    rows = list(rows)
    if not rows:
        return "SELECT " + ", ".join(f"CAST(NULL AS {kind})" for kind in types) + " WHERE 1=0", ()
    return (
        "VALUES " + ", ".join("(" + ", ".join(["%s"] * len(row)) + ")" for row in rows),
        tuple(value for row in rows for value in row),
    )


def _response_lookup_key(key):
    tail = key.removeprefix("response:")
    variant = tail.find(":variant-")
    if variant > 0:
        return tail[:variant]
    for suffix in (":front", ":back"):
        if tail.endswith(suffix):
            return tail[:-len(suffix)]
    return tail


def _subject_mark(annotation):
    return (
        annotation.kind == AnnotationKind.HIGHLIGHT
        and not annotation.hidden_on_source
        and (
            annotation.source_key.startswith(("response:", "phrase:", "tache-two:"))
            or (not annotation.source_key and "/sujets/" in annotation.source_path)
        )
    )


def _ordinary_candidate(annotation, roots, keys, prompts, response_ids):
    key = annotation.source_key
    if PHRASE_SOURCE_RE.match(key):
        return True
    if key.startswith("response:"):
        return _response_lookup_key(key) in roots | keys
    if key:
        return _annotation_prompt_key(key) in keys
    try:
        path = SUBJECT_PATH_RE.fullmatch(urlsplit(annotation.source_path).path)
    except ValueError:
        return True
    prompt = prompts.get(int(path["prompt_id"])) if path else None
    return bool(
        prompt and prompt[1] in response_ids and prompt[4]
        and prompt[2] == EXPRESSION_PART_BY_PATH[path["part"]]
        and prompt[3] == path["task"]
    )


def _subject_source(user, task_ids, weights, highlights):
    units, unit_params = _values(
        ((task, response, weight) for task, counts in weights.items() for response, weight in counts.items()),
        ("bigint", "bigint", "bigint"),
    )
    wanted = {response for counts in weights.values() for response in counts}
    marks, mark_params = _values(
        ((response, connection.ops.adapt_datetimefield_value(at)) for response, at in highlights.items()),
        ("bigint", "timestamp"),
    )
    tasks, task_params = _values(((task,) for task in task_ids), ("bigint",))
    if wanted:
        vocabulary_responses = Response.objects.filter(pk__in=wanted).exclude(
            retired_task_filter("theme__task__"),
        ).values("pk")
        vocabulary = Card.objects.current_content().filter(
            user=user, phrase__tier=PhraseTier.SUBJECT,
            phrase__source_prompts__is_active=True,
            phrase__source_prompts__response_id__in=vocabulary_responses,
        ).filter(Q(started_at__isnull=False) | ~Q(state=CardState.NEW))
        vocabulary_sql, vocabulary_params = vocabulary.order_by().values_list(
            "phrase__source_prompts__response_id", flat=True,
        ).distinct().query.sql_with_params()
    else:
        vocabulary_sql, vocabulary_params = _values([], ("bigint",))
    return f"""
        WITH units(task_id,response_id,weight) AS ({units}),
             marks(response_id,at) AS ({marks}),
             vocabulary(response_id) AS ({vocabulary_sql}),
             tasks(task_id) AS ({tasks})
        SELECT t.task_id, 0,
               COALESCE(SUM(u.weight),0),
               COALESCE(SUM(CASE
                   WHEN c.subject_completed_at IS NOT NULL THEN u.weight
                   WHEN c.subject_status_reset_at IS NOT NULL
                       THEN CASE WHEN h.at > c.subject_status_reset_at THEN u.weight ELSE 0 END
                   WHEN h.response_id IS NOT NULL
                        OR c.response_practice_started_at IS NOT NULL
                        OR c.state <> %s OR v.response_id IS NOT NULL THEN u.weight
                   ELSE 0 END),0),
               COALESCE(SUM(CASE WHEN c.subject_completed_at IS NOT NULL THEN u.weight ELSE 0 END),0),
               0
        FROM tasks t LEFT JOIN units u ON u.task_id=t.task_id
        LEFT JOIN study_card c ON c.response_id=u.response_id AND c.user_id=%s AND c.card_type=%s
        LEFT JOIN marks h ON h.response_id=u.response_id
        LEFT JOIN vocabulary v ON v.response_id=u.response_id
        GROUP BY t.task_id
    """, (
        *unit_params, *mark_params, *vocabulary_params, *task_params,
        str(CardState.NEW), user.pk, str(CardType.SPINE),
    )


def _writing_source(user, task, highlighted, occurrence_weights):
    activity = PersonalWritingResponse.objects.filter(
        user=user, sujet__task=task,
    ).order_by().annotate(_started=Value(1), _done=Value(0)).values_list("sujet_id", "_started", "_done")
    edits = WritingResponseOverride.objects.filter(
        user=user, sujet__task=task,
    ).exclude(body="").order_by().annotate(
        _started=Value(1), _done=Value(0),
    ).values_list("sujet_id", "_started", "_done")
    completions = WritingSujetCompletion.objects.filter(
        user=user, sujet__task=task,
    ).order_by().annotate(_started=Value(1), _done=Value(1)).values_list("sujet_id", "_started", "_done")
    activity_sql, activity_params = activity.union(edits, completions, all=True).query.sql_with_params()
    marks, mark_params = _values(((pk, 1, 0) for pk in highlighted), ("bigint", "integer", "integer"))
    units, catalogue_params = _values(
        ((task.pk, sujet, weight) for sujet, weight in occurrence_weights.items()),
        ("bigint", "bigint", "bigint"),
    )
    catalogue_sql = f"""units(task_id,sujet_id,weight) AS ({units}),
        counts AS (SELECT task_id,SUM(weight) AS total FROM units GROUP BY task_id)"""
    return f"""
        WITH {catalogue_sql}, flags(sujet_id,started,completed) AS (
            {activity_sql} UNION ALL SELECT * FROM ({marks}) highlighted
        ), activity AS (
            SELECT sujet_id,MAX(started) AS started,MAX(completed) AS completed
            FROM flags GROUP BY sujet_id
        )
        SELECT u.task_id,MAX(n.total),SUM(u.weight),
               SUM(u.weight*COALESCE(a.started,0)),SUM(u.weight*COALESCE(a.completed,0)),0
        FROM units u LEFT JOIN activity a ON a.sujet_id=u.sujet_id
        JOIN counts n ON n.task_id=u.task_id GROUP BY u.task_id
    """, (*catalogue_params, *activity_params, *mark_params)


def writing_occurrence_progress(user, task, weights):
    """Published writing overview progress without per-sujet state objects."""
    if not weights:
        return progress_summary(total=0, started=0, completed=0)
    marks = Annotation.objects.filter(
        Q(task=task) | Q(task__isnull=True),
        user=user, kind=AnnotationKind.HIGHLIGHT,
        source_key__startswith="writing-sujet:",
    ).order_by().values_list("source_key", flat=True).distinct()
    highlighted = {
        pk for key in marks
        if (pk := writing_sujet_id_from_source_key(key)) in weights
    }
    sql, params = _writing_source(user, task, highlighted, weights)
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        _task, _prompts, total, started, completed, _due = cursor.fetchone()
    return progress_summary(total=total, started=started, completed=completed)


def _learning_source(user, catalogs, activity):
    aggregates = {}
    rows = []
    all_keys = set()
    for task_id, catalog in catalogs.items():
        keys = {entry.content_key for entry in catalog.entries}
        started = keys & activity
        name, additional = f"learned_{task_id}", f"additional_{task_id}"
        aggregates[name] = Count(
            "question_key", distinct=True, filter=Q(memory_number=1, question_key__in=keys),
        )
        aggregates[additional] = Count(
            "question_key", distinct=True,
            filter=Q(memory_number=1, question_key__in=keys - started),
        )
        all_keys.update(keys)
        rows.append((task_id, 0, len(keys), f'{len(started)}+"{additional}"', f'"{name}"'))
    if not all_keys:
        return _values(
            ((task, prompts, total, 0, 0, 0) for task, prompts, total, _started, _completed in rows),
            ("bigint", "bigint", "bigint", "bigint", "bigint", "bigint"),
        )
    learned_sql, learned_params = MemoryQuestionProgress.objects.filter(
        user=user, question_key__in=all_keys,
    ).order_by().values(_group=Value(1)).annotate(**aggregates).query.sql_with_params()
    return (
        f"WITH learned AS ({learned_sql}) " + " UNION ALL ".join(
            f"SELECT {int(task)}, {int(prompts)}, {int(total)}, {started}, {completed}, 0 FROM learned"
            for task, prompts, total, started, completed in rows
        ),
        learned_params,
    )


def expression_overview_summaries(
    user, tasks, *, with_components=False, require_published=False,
):
    """Catalogue identifiers plus aggregate rows, never per-subject progress."""
    summaries = {task.pk: {"prompt_count": 0, "stats": None} for task in tasks}
    available = [task for task in tasks if task.available]
    if not available:
        return summaries
    catalogs = {
        t.pk: get_ee_formulations(int(t.slug[-1])) for t in available
        if with_components and (t.part.slug, t.slug) == content_loader.EE_TACHE_THREE_TASK
    }
    subject_tasks = available
    subject_ids = {t.pk for t in subject_tasks}
    formulation_keys = {entry.content_key for catalog in catalogs.values() for entry in catalog.entries}
    formulation_paths = {
        FORMULATION_ENTRY_PATHS[catalog.tache].format(slug=entry.slug): entry.content_key
        for catalog in catalogs.values() for entry in catalog.entries
    }
    source_filter = (
        Q(source_key__startswith="response:") | Q(source_key__startswith="phrase:")
        | Q(source_key__startswith="tache-two:") | Q(source_key="", source_path__contains="/sujets/")
    ) if subject_ids else Q(pk__in=[])
    annotation_rows = Annotation.objects.filter(user=user).filter(
        (Q(kind=AnnotationKind.HIGHLIGHT, hidden_on_source=False) & source_filter)
        | Q(source_key__in=formulation_keys) | Q(source_path__in=formulation_paths),
    ).annotate(_oral_scope=Case(
        When(Q(task__isnull=True) | Q(task__part__slug="eo", task__slug__in=("tache-2", "tache-3")), then=Value(True)),
        default=Value(False),
    )).order_by().values(
        "task_id", "source_prompt_id", "source_key", "source_path",
        "kind", "hidden_on_source", "_oral_scope",
    ).annotate(_pk=Min("pk"), _latest=Max("created_at"))
    annotations = [
        SimpleNamespace(pk=row.pop("_pk"), created_at=row.pop("_latest"), **row)
        for row in annotation_rows
    ]
    marks = [annotation for annotation in annotations if _subject_mark(annotation)]
    prompt_ids, prompt_keys = set(), set()
    for annotation in marks:
        if annotation.source_prompt_id is not None:
            prompt_ids.add(annotation.source_prompt_id)
        if annotation.source_key.startswith("response:"):
            prompt_keys.add(_response_lookup_key(annotation.source_key))
        key = _annotation_prompt_key(annotation.source_key)
        if key:
            prompt_keys.add(key)
        try:
            path = SUBJECT_PATH_RE.fullmatch(urlsplit(annotation.source_path).path)
        except ValueError:
            path = None
        if path:
            prompt_ids.add(int(path["prompt_id"]))
    fields = ["theme__task_id", "content_key", "response_id", "theme__is_active", "response__is_active"]
    if marks:
        fields += ["pk", "response__content_key", "response__semantic_group", "response__semantic_owner_id",
                   "theme__task__part__slug", "theme__task__slug"]
    prompt_rows = list(Prompt.objects.filter(is_active=True).filter(
        Q(theme__task_id__in=subject_ids) | Q(pk__in=prompt_ids) | Q(content_key__in=prompt_keys),
    ).order_by().values_list(*fields))
    by_content_key, by_task = {}, defaultdict(set)
    prompt_counts = Counter()
    known_prompts, known_responses, roots, prompt_metadata = [], {}, {}, {}
    for row in prompt_rows:
        task, key, response, active_theme, active_response = row[:5]
        if task in subject_ids:
            prompt_counts[task] += 1
            if active_response:
                by_content_key[key] = response
                if active_theme:
                    by_task[task].add(response)
        if marks:
            pk, root, group, owner, part, slug = row[5:]
            prompt_metadata[pk] = (key, response, part, slug, active_response)
            roots[response] = (root, group)
            if group:
                known_prompts.append(AnnotationPromptOwner(pk, key, response, task, slug))
            if group or owner is not None:
                known_responses[root] = owner or response
    weights = {}
    for task in subject_tasks:
        keys = None
        if (task.part.slug, task.slug) == content_loader.EE_TACHE_THREE_TASK:
            published = catalogue.ee_subject_keys(3)
            if require_published and any(key not in by_content_key for key in published):
                raise RuntimeError("EE Tâche 3 content is not synchronized")
            keys = tuple(key for key in published if key in by_content_key) or None
        weights[task.pk] = Counter(by_content_key[key] for key in keys) if keys is not None else Counter(
            {response: 1 for response in by_task[task.pk]},
        )
    wanted = {response for counts in weights.values() for response in counts}
    highlights = {}
    if marks and wanted:
        oral = {pk for pk in wanted if roots[pk][1]}
        owners = annotation_owners(
            [a for a in marks if a._oral_scope],
            known_prompts=known_prompts, known_responses=known_responses,
        ) if oral else {}
        for annotation in marks:
            owner = owners.get(annotation.pk)
            if owner in oral:
                highlights[owner] = max(highlights.get(owner, annotation.created_at), annotation.created_at)
        ordinary = wanted - oral
        ordinary_roots = {roots[pk][0] for pk in ordinary}
        ordinary_keys = {key for key, response, _part, _slug, active in prompt_metadata.values()
                         if response in ordinary and active}
        # Reuse the established legacy resolver, not another source-key grammar.
        candidates = any(_ordinary_candidate(
            a, ordinary_roots, ordinary_keys, prompt_metadata, ordinary,
        ) for a in marks)
        if ordinary and candidates:
            highlights.update({pk: latest for pk, (latest, _first) in subject_highlight_times(
                user, ordinary, grouped=True,
            ).items()})
    activity = {
        a.source_key if a.source_key in formulation_keys else formulation_paths[a.source_path]
        for a in annotations if a.source_key in formulation_keys or a.source_path in formulation_paths
    }
    sources = []
    if subject_ids:
        sources.append(_subject_source(user, subject_ids, weights, highlights))
    if catalogs:
        sources.append(_learning_source(user, catalogs, activity))
    totals = defaultdict(lambda: [0, 0, 0, 0, 0])
    components = {}
    if sources:
        sql = " UNION ALL ".join(
            f"SELECT {f'{i}, ' if with_components else ''}* FROM ({source}) overview_{i}"
            for i, (source, _params) in enumerate(sources)
        )
        params = tuple(value for _source, values in sources for value in values)
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            for row in cursor.fetchall():
                if with_components:
                    source_number, task, *counts = row
                    components[task, source_number] = progress_summary(
                        total=counts[1], started=counts[2], completed=counts[3],
                    )
                else:
                    task, *counts = row
                totals[task] = [left + right for left, right in zip(totals[task], counts)]
    for task in available:
        prompts, total, started, completed, due = totals[task.pk]
        progress = progress_summary(total=total, started=started, completed=completed)
        summaries[task.pk] = {
            "prompt_count": prompt_counts[task.pk] if task.pk in subject_ids else prompts,
            "stats": {
                "progress": progress, "seen": progress.started,
                "total": progress.total, "completed": progress.completed, "due": due,
                "started_new": max(progress.started - progress.completed, 0),
            },
        }
        if with_components:
            summaries[task.pk]["distinct_subject_count"] = len(weights.get(task.pk, {}))
            subject_source = 0 if task.pk in subject_ids else int(bool(subject_ids))
            summaries[task.pk]["subject_progress"] = components.get(
                (task.pk, subject_source), progress_summary(total=0, started=0, completed=0),
            )
            if task.pk in catalogs:
                summaries[task.pk]["formulation_progress"] = components.get(
                    (task.pk, len(sources) - 1), progress_summary(total=0, started=0, completed=0),
                )
    return summaries
