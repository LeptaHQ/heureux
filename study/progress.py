"""Progress tracking for cards and subject-specific study material."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
import re
from typing import Iterable
from urllib.parse import urlsplit

from django.db.models import (
    Case,
    Count,
    F,
    Max,
    OuterRef,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import (
    Greatest,
    Length,
    Replace,
    Right,
    StrIndex,
    Substr,
)
from django.utils import timezone

from .models import (
    Annotation,
    AnnotationKind,
    Card,
    CardState,
    CardType,
    PersonalWritingResponse,
    Phrase,
    PhraseTier,
    Prompt,
    Response,
    WritingSujetCompletion,
)


SUBJECT_PATH_RE = re.compile(
    r"^/expression/(?P<part>orale|ecrite)/(?P<task>[-a-zA-Z0-9_]+)/"
    r"sujets/(?P<prompt_id>\d+)/$"
)
EXPRESSION_PART_BY_PATH = {
    "orale": "eo",
    "ecrite": "ee",
}
RESPONSE_SOURCE_PREFIX = "response:"
PHRASE_SOURCE_PREFIX = "phrase:"
PHRASE_SOURCE_RE = re.compile(r"^phrase:(?P<phrase_id>[^:]+):")
TACHE_TWO_SOURCE_RE = re.compile(
    r"^tache-two:(?P<month>[a-z0-9-]+):batch-(?P<batch>\d+):"
    r"subject-(?P<subject>\d+)$"
)
WRITING_SUJET_SOURCE_PREFIX = "writing-sujet:"
WRITING_SUJET_SOURCE_RE = re.compile(
    r"^writing-sujet:(?P<sujet_id>\d+):(?:personal|model-\d+)$"
)
ANNOTATION_SURFACE_SUFFIXES = (":front", ":back")
# A card counts as mature once its interval reaches three weeks.
MATURE_INTERVAL_DAYS = 21


@dataclass(frozen=True)
class ProgressSummary:
    status: str
    label: str
    total: int
    started: int
    completed: int
    percent: int


def progress_summary(
    *,
    total: int,
    started: int,
    completed: int,
) -> ProgressSummary:
    """Normalize collection progress into the app's three display states."""
    total = max(int(total), 0)
    started = min(max(int(started), 0), total)
    completed = min(max(int(completed), 0), total)
    started = max(started, completed)
    if total and completed == total:
        status = "done"
        label = "Terminé"
    elif started:
        status = "active"
        label = "En cours"
    else:
        status = "new"
        label = "À commencer"
    return ProgressSummary(
        status=status,
        label=label,
        total=total,
        started=started,
        completed=completed,
        percent=round(100 * completed / total) if total else 0,
    )


@dataclass(frozen=True)
class WritingSujetProgress:
    status: str
    label: str
    explicitly_completed: bool
    is_personalized: bool
    has_highlight: bool

    @property
    def started(self) -> int:
        return int(
            self.explicitly_completed
            or self.is_personalized
            or self.has_highlight
        )

    @property
    def completed(self) -> int:
        return int(self.explicitly_completed)


def writing_sujet_id_from_source_key(source_key: str) -> int | None:
    match = WRITING_SUJET_SOURCE_RE.fullmatch(source_key or "")
    return int(match.group("sujet_id")) if match else None


def writing_sujet_progress_by_id(
    user,
    sujet_ids,
    *,
    task_id=None,
) -> dict[int, WritingSujetProgress]:
    """Calculate EE Tâche 1/2 progress from direct response activity."""
    ids = {
        int(sujet_id)
        for sujet_id in sujet_ids
        if str(sujet_id).isdigit() and int(sujet_id) > 0
    }
    if not ids:
        return {}

    personalized_ids = set(
        PersonalWritingResponse.objects.filter(
            user=user,
            sujet_id__in=ids,
        ).values_list("sujet_id", flat=True)
    )
    completed_ids = set(
        WritingSujetCompletion.objects.filter(
            user=user,
            sujet_id__in=ids,
        ).values_list("sujet_id", flat=True)
    )
    highlighted_ids = set()
    highlights = Annotation.objects.filter(
        user=user,
        kind=AnnotationKind.HIGHLIGHT,
        source_key__startswith=WRITING_SUJET_SOURCE_PREFIX,
    )
    if task_id is not None:
        highlights = highlights.filter(
            Q(task_id=task_id) | Q(task_id__isnull=True)
        )
    source_keys = highlights.values_list("source_key", flat=True)
    for source_key in source_keys:
        sujet_id = writing_sujet_id_from_source_key(source_key)
        if sujet_id in ids:
            highlighted_ids.add(sujet_id)

    results = {}
    for sujet_id in ids:
        explicitly_completed = sujet_id in completed_ids
        is_personalized = sujet_id in personalized_ids
        has_highlight = sujet_id in highlighted_ids
        if explicitly_completed:
            status = "done"
            label = "Terminé"
        elif is_personalized or has_highlight:
            status = "active"
            label = "En cours"
        else:
            status = "new"
            label = "À commencer"
        results[sujet_id] = WritingSujetProgress(
            status=status,
            label=label,
            explicitly_completed=explicitly_completed,
            is_personalized=is_personalized,
            has_highlight=has_highlight,
        )
    return results


def combine_progress(
    progress_items: Iterable[ProgressSummary],
) -> ProgressSummary:
    """Combine child progress while preserving their underlying unit counts."""
    items = list(progress_items)
    return progress_summary(
        total=sum(item.total for item in items),
        started=sum(item.started for item in items),
        completed=sum(item.completed for item in items),
    )


def card_unit_progress_from_rows(rows) -> ProgressSummary:
    """Summarize already-fetched card rows as phrase units.

    ``rows`` carry ``id``, ``phrase_id``, ``state``, ``started_at`` and
    ``suspended``; suspended rows are ignored, exactly as they are when the
    rows come straight from the database.
    """
    units = {}
    for row in rows:
        key = ("phrase", row["phrase_id"]) if row["phrase_id"] else ("card", row["id"])
        if not row["suspended"]:
            units.setdefault(key, []).append(row)
    return progress_summary(
        total=len(units),
        started=sum(
            any(
                row["state"] != CardState.NEW
                or row["started_at"] is not None
                for row in unit
            )
            for unit in units.values()
        ),
        completed=sum(
            all(row["state"] != CardState.NEW for row in unit)
            for unit in units.values()
        ),
    )


def card_unit_progress(cards) -> ProgressSummary:
    """Summarize active cards, treating both directions as one phrase unit."""
    return card_unit_progress_from_rows(
        cards.values(
            "id",
            "phrase_id",
            "state",
            "started_at",
            "suspended",
        )
    )


@dataclass(frozen=True)
class SubjectProgress:
    status: str
    label: str
    explicitly_completed: bool
    has_highlight: bool
    response_practice_started: bool
    vocabulary_activity_started: bool
    vocabulary_total: int
    vocabulary_started: int
    vocabulary_completed: int
    vocabulary_mastered: int
    vocabulary_due: int

    @property
    def vocabulary_progress(self) -> ProgressSummary:
        return progress_summary(
            total=self.vocabulary_total,
            started=self.vocabulary_started,
            completed=self.vocabulary_completed,
        )


def mark_card_started(user, card: Card) -> None:
    """Persist the presented card's first activity timestamp."""
    at = timezone.now()
    if card.started_at is None:
        Card.objects.filter(
            pk=card.pk,
            user=user,
            started_at__isnull=True,
        ).update(started_at=at)
        card.started_at = at
    if (
        card.card_type == CardType.SPINE
        and card.response_practice_started_at is None
    ):
        Card.objects.filter(
            pk=card.pk,
            user=user,
            response_practice_started_at__isnull=True,
        ).update(response_practice_started_at=at)
        card.response_practice_started_at = at


def _response_content_key(source_key: str) -> str:
    if not source_key.startswith(RESPONSE_SOURCE_PREFIX):
        return ""
    content_key = source_key[len(RESPONSE_SOURCE_PREFIX) :]
    for suffix in ANNOTATION_SURFACE_SUFFIXES:
        if content_key.endswith(suffix):
            return content_key[: -len(suffix)]
    return content_key


def _batches(values, size):
    if size < 1:
        raise ValueError("Batch size must be positive")
    iterator = iter(values)
    while batch := tuple(islice(iterator, size)):
        yield batch


_HIGHLIGHT_PATTERN_LIMIT = 8192
_HIGHLIGHT_PATTERNS_PER_QUERY = 8


def _pack_patterns(parts, prefix, suffix):
    batch = []
    length = len(prefix) + len(suffix)
    for part in parts:
        if len(prefix) + len(part) + len(suffix) > _HIGHLIGHT_PATTERN_LIMIT:
            raise ValueError("Highlight pattern component exceeds its size limit")
        if batch and length + 1 + len(part) > _HIGHLIGHT_PATTERN_LIMIT:
            yield prefix + "|".join(batch) + suffix
            batch = []
            length = len(prefix) + len(suffix)
        length += len(part) + bool(batch)
        batch.append(part)
    if batch:
        yield prefix + "|".join(batch) + suffix


def _numeric_patterns(prefix, numbers, outer_prefix, outer_suffix):
    """Factor shared digit prefixes before bounding each literal SQL pattern."""
    trie = {}
    numbers = sorted(numbers)
    if not numbers:
        raise ValueError("Highlight numeric patterns need at least one number")
    for number in numbers:
        node = trie
        for digit in str(number):
            node = node.setdefault(digit, {})
        node[""] = {}

    def render(node):
        by_suffix = {}
        for digit, child in sorted(node.items()):
            if digit:
                by_suffix.setdefault(render(child), []).append(digit)
        parts = [
            (digits[0] if len(digits) == 1 else "[" + "".join(digits) + "]")
            + suffix
            for suffix, digits in by_suffix.items()
        ]
        if not parts:
            return ""
        pattern = parts[0] if len(parts) == 1 else "(?:" + "|".join(parts) + ")"
        return "(?:" + pattern + ")?" if "" in node else pattern

    pattern = prefix + "0*" + render(trie)
    if len(outer_prefix) + len(pattern) + len(outer_suffix) <= _HIGHLIGHT_PATTERN_LIMIT:
        yield pattern
    elif len(numbers) > 1:
        middle = len(numbers) // 2
        for half in (numbers[:middle], numbers[middle:]):
            yield from _numeric_patterns(prefix, half, outer_prefix, outer_suffix)
    else:
        raise ValueError("Highlight pattern component exceeds its size limit")


def _prompt_highlight_scopes(prompts, shapes):
    aliases = {}
    routes = {}
    for prompt in prompts:
        content_key = prompt.get("content_key", "")
        if shapes["alias"] and content_key.startswith("tache2:"):
            match = TACHE_TWO_SOURCE_RE.fullmatch(
                content_key.replace("tache2:", "tache-two:", 1)
            )
            if match:
                month = match["month"]
                batch = int(match["batch"])
                subject = int(match["subject"])
                canonical = (
                    f"tache2:{month}:batch-{batch:02d}:subject-{subject:02d}"
                )
                if content_key == canonical:
                    aliases.setdefault((month, batch), set()).add(subject)
        if shapes["legacy"]:
            part = {"eo": "orale", "ee": "ecrite"}.get(
                prompt["theme__task__part__slug"]
            )
            task = prompt["theme__task__slug"]
            if part and re.fullmatch(r"[-a-zA-Z0-9_]+", task):
                routes.setdefault((part, task), set()).add(prompt["pk"])

    if aliases:
        prefix, suffix = "^tache-two:(?:", ")$"
        parts = (
            pattern
            for (month, batch), subjects in sorted(aliases.items())
            for pattern in _numeric_patterns(
                f"{month}:batch-0*{batch}:subject-", subjects, prefix, suffix
            )
        )
        for pattern in _pack_patterns(parts, prefix, suffix):
            yield Q(_highlight_key__regex=pattern)
        # Unusual Unicode numeric spellings stay with the original Python int
        # parser rather than expanding every decimal alphabet into SQL patterns.
        yield Q(source_key__startswith="tache-two:", _highlight_key__regex=r"[^ -~]")
    if routes:
        prefix, suffix = r"^[^?#]*/expression/(?:", r")/(?:[?#].*)?$"
        parts = (
            pattern
            for (part, task), prompt_ids in sorted(routes.items())
            for pattern in _numeric_patterns(
                f"{part}/{re.escape(task)}/sujets/", prompt_ids, prefix, suffix
            )
        )
        for pattern in _pack_patterns(parts, prefix, suffix):
            yield Q(source_key="", _highlight_path__regex=pattern)
        yield Q(
            source_key="",
            _highlight_path__regex=r"/sujets/[^/?#]*[^ -~][^/?#]*/",
        )


def _subject_highlight_rows(user, response_ids):
    """Fetch target-related candidates and their resolved response-key IDs."""
    highlights = Annotation.objects.filter(
        Q(source_key__startswith=RESPONSE_SOURCE_PREFIX)
        | Q(source_key__startswith=PHRASE_SOURCE_PREFIX)
        | Q(source_key__startswith="tache-two:")
        | Q(source_key="", source_path__contains="/sujets/"),
        user=user,
        kind=AnnotationKind.HIGHLIGHT,
    )
    shapes = highlights.aggregate(
        response=Count("pk", filter=Q(source_key__startswith=RESPONSE_SOURCE_PREFIX)),
        phrase=Count("pk", filter=Q(source_key__startswith=PHRASE_SOURCE_PREFIX)),
        alias=Count("pk", filter=Q(source_key__startswith="tache-two:")),
        legacy=Count("pk", filter=Q(source_key="")),
    )
    if not any(shapes.values()):
        return [], {}, []

    # Response/phrase predicates repeat their IDs in up to three subqueries.
    # Batches bound SQL parameters, not note count.
    rows = []
    response_by_content_key = {}
    id_batches = (
        _batches(sorted(response_ids), 150)
        if shapes["response"] or shapes["phrase"]
        else ()
    )
    for ids in id_batches:
        candidates = highlights
        scope = Q()
        if shapes["response"]:
            responses = Response.objects.filter(pk__in=ids, is_active=True)
            candidates = candidates.alias(
                _front_surface=Right("source_key", 6),
                _back_surface=Right("source_key", 5),
            ).alias(
                _response_key=Case(
                    When(
                        _front_surface=":front",
                        then=Substr(
                            "source_key", len(RESPONSE_SOURCE_PREFIX) + 1,
                            Greatest(
                                Length("source_key")
                                - len(RESPONSE_SOURCE_PREFIX) - len(":front"),
                                Value(0),
                            ),
                        ),
                    ),
                    When(
                        _back_surface=":back",
                        then=Substr(
                            "source_key", len(RESPONSE_SOURCE_PREFIX) + 1,
                            Greatest(
                                Length("source_key")
                                - len(RESPONSE_SOURCE_PREFIX) - len(":back"),
                                Value(0),
                            ),
                        ),
                    ),
                    default=Substr("source_key", len(RESPONSE_SOURCE_PREFIX) + 1),
                ),
            )
            scope |= Q(
                source_key__startswith=RESPONSE_SOURCE_PREFIX,
                _response_key__in=responses.values("content_key"),
            )
            candidates = candidates.annotate(
                _matched_response_id=Subquery(
                    responses.filter(content_key=OuterRef("_response_key"))
                    .order_by().values("pk")[:1]
                ),
            )
        if shapes["phrase"]:
            phrases = Phrase.objects.filter(
                tier=PhraseTier.SUBJECT,
                is_active=True,
                source_prompts__is_active=True,
                source_prompts__response_id__in=ids,
            )
            candidates = candidates.alias(
                _phrase_tail=Substr("source_key", len(PHRASE_SOURCE_PREFIX) + 1),
            ).alias(
                _phrase_separator=StrIndex("_phrase_tail", Value(":")),
            ).alias(
                _phrase_key=Substr(
                    "_phrase_tail", 1,
                    Greatest(F("_phrase_separator") - 1, Value(0)),
                ),
            )
            scope |= Q(
                source_key__startswith=PHRASE_SOURCE_PREFIX,
                _phrase_separator__gt=1,
                _phrase_key__in=phrases.values("phrase_id"),
            )
        fields = ["source_path", "source_key"]
        if shapes["response"]:
            fields.append("_matched_response_id")
        batch_rows = list(candidates.filter(scope).order_by().values(*fields))
        if shapes["response"]:
            for row in batch_rows:
                if (
                    row["_matched_response_id"] is not None
                    and row["source_key"].startswith(RESPONSE_SOURCE_PREFIX)
                ):
                    content_key = _response_content_key(row["source_key"])
                    response_by_content_key[content_key] = (
                        row["_matched_response_id"]
                    )
        rows.extend(batch_rows)

    prompts = []
    if shapes["alias"] or shapes["legacy"]:
        fields = ["pk", "response_id"]
        if shapes["alias"]:
            fields.append("content_key")
        if shapes["legacy"]:
            fields.extend(("theme__task__part__slug", "theme__task__slug"))
        prompts = list(
            Prompt.objects.filter(
                response_id__in=response_ids,
                is_active=True,
                response__is_active=True,
            ).order_by().values(*fields)
        )
        normalized_path = Max("source_path")
        for character in ("\t", "\r", "\n"):
            normalized_path = Replace(normalized_path, Value(character), Value(""))
        # Progress needs presence per source, not every selected offset. HAVING
        # evaluates the patterns once per source even when it has many marks.
        candidates = highlights.order_by().values("source_path", "source_key").alias(
            _highlight_key=Max("source_key"),
            _highlight_path=normalized_path,
        )
        # Construct each route/month/batch pattern once, not once per
        # (highlight, prompt) pair in a correlated database subquery.
        for scopes in _batches(
            _prompt_highlight_scopes(prompts, shapes), _HIGHLIGHT_PATTERNS_PER_QUERY
        ):
            scope = Q()
            for item in scopes:
                scope |= item
            rows.extend(
                candidates.filter(scope).order_by().values("source_path", "source_key")
            )
    return rows, response_by_content_key, prompts


def subject_progress_by_response(user, response_ids) -> dict[int, SubjectProgress]:
    """Calculate sujet progress from direct, material-specific activity."""
    response_ids = {
        int(response_id)
        for response_id in response_ids
        if str(response_id).isdigit() and int(response_id) > 0
    }
    if not response_ids:
        return {}
    # Bound the card and resolver IN lists as well as the highlight predicates.
    if len(response_ids) > 800:
        return {
            response_id: state
            for batch in _batches(sorted(response_ids), 800)
            for response_id, state in subject_progress_by_response(user, batch).items()
        }

    progress = {
        response_id: {
            "explicitly_completed": False,
            "has_highlight": False,
            "response_practice_started": False,
            "vocabulary_activity_started": False,
            "vocabulary_total": 0,
            "vocabulary_started": 0,
            "vocabulary_completed": 0,
            "vocabulary_mastered": 0,
            "vocabulary_due": 0,
        }
        for response_id in response_ids
    }
    response_cards = Card.objects.current_content().filter(
        Q(response_practice_started_at__isnull=False)
        | Q(subject_completed_at__isnull=False)
        | ~Q(state=CardState.NEW),
        user=user,
        card_type=CardType.SPINE,
        response_id__in=response_ids,
    ).values(
        "response_id",
        "response_practice_started_at",
        "subject_completed_at",
        "state",
    )
    for card in response_cards:
        values = progress[card["response_id"]]
        values["explicitly_completed"] = (
            card["subject_completed_at"] is not None
        )
        values["response_practice_started"] = (
            card["response_practice_started_at"] is not None
            or card["state"] != CardState.NEW
        )

    now = timezone.now()
    # One grouped aggregate rather than a row per (card, sujet) pair: a learner
    # owns thousands of subject-vocabulary cards, and every page summarizing
    # several sujets at once had to pull and count each of them in Python.
    started_activity = Q(started_at__isnull=False) | ~Q(state=CardState.NEW)
    vocabulary_rows = (
        Card.objects.current_content()
        .filter(
            user=user,
            phrase__tier=PhraseTier.SUBJECT,
            phrase__source_prompts__is_active=True,
            phrase__source_prompts__response_id__in=response_ids,
        )
        .order_by()
        .values("phrase__source_prompts__response_id")
        .annotate(
            activity_started=Count(
                "id",
                distinct=True,
                filter=started_activity,
            ),
            total=Count("id", distinct=True, filter=Q(suspended=False)),
            started=Count(
                "id",
                distinct=True,
                filter=Q(suspended=False) & started_activity,
            ),
            completed=Count(
                "id",
                distinct=True,
                filter=Q(suspended=False) & ~Q(state=CardState.NEW),
            ),
            mastered=Count(
                "id",
                distinct=True,
                filter=Q(
                    suspended=False,
                    state=CardState.REVIEW,
                    interval_days__gte=MATURE_INTERVAL_DAYS,
                ),
            ),
            due=Count(
                "id",
                distinct=True,
                filter=Q(
                    suspended=False,
                    state__in=[
                        CardState.LEARNING,
                        CardState.RELEARNING,
                        CardState.REVIEW,
                    ],
                    due__lte=now,
                ),
            ),
        )
    )
    for row in vocabulary_rows:
        values = progress[row["phrase__source_prompts__response_id"]]
        values["vocabulary_activity_started"] = bool(row["activity_started"])
        values["vocabulary_total"] = row["total"]
        values["vocabulary_started"] = row["started"]
        values["vocabulary_completed"] = row["completed"]
        values["vocabulary_mastered"] = row["mastered"]
        values["vocabulary_due"] = row["due"]

    highlight_rows, response_by_content_key, prompt_rows = _subject_highlight_rows(
        user, response_ids
    )
    if not highlight_rows:
        # Nothing can match, so the three lookups that resolve highlights onto
        # responses have nothing to resolve.
        return _finish_subject_progress(progress)

    path_matches = [
        (
            row,
            SUBJECT_PATH_RE.fullmatch(urlsplit(row["source_path"]).path),
        )
        for row in highlight_rows
    ]
    phrase_matches = [
        (row, PHRASE_SOURCE_RE.match(row["source_key"]))
        for row in highlight_rows
    ]
    response_by_prompt_content_key = {
        row["content_key"]: row["response_id"]
        for row in prompt_rows
        if row.get("content_key", "").startswith("tache2:")
    }
    prompt_references = {
        row["pk"]: row
        for row in prompt_rows
    }
    phrase_ids = {
        match.group("phrase_id")
        for _row, match in phrase_matches
        if match
    }
    response_ids_by_subject_phrase = {}
    for ids in _batches(sorted(phrase_ids), 150):
        for phrase_id, response_id in Phrase.objects.filter(
            phrase_id__in=ids,
            tier=PhraseTier.SUBJECT,
            is_active=True,
            source_prompts__is_active=True,
            source_prompts__response_id__in=response_ids,
        ).values_list("phrase_id", "source_prompts__response_id"):
            response_ids_by_subject_phrase.setdefault(phrase_id, set()).add(
                response_id
            )
    for row, path_match in path_matches:
        matched_response_ids = set()
        if path_match and not row["source_key"]:
            prompt = prompt_references.get(int(path_match.group("prompt_id")))
            if (
                prompt
                and prompt["theme__task__part__slug"]
                == EXPRESSION_PART_BY_PATH[path_match.group("part")]
                and prompt["theme__task__slug"] == path_match.group("task")
            ):
                matched_response_ids.add(prompt["response_id"])
        content_key = _response_content_key(row["source_key"])
        if content_key in response_by_content_key:
            matched_response_ids.add(response_by_content_key[content_key])
        tache_two_match = TACHE_TWO_SOURCE_RE.fullmatch(row["source_key"])
        if tache_two_match:
            tache_two_content_key = (
                f"tache2:{tache_two_match['month']}:"
                f"batch-{int(tache_two_match['batch']):02d}:"
                f"subject-{int(tache_two_match['subject']):02d}"
            )
            if tache_two_content_key in response_by_prompt_content_key:
                matched_response_ids.add(
                    response_by_prompt_content_key[tache_two_content_key]
                )
        phrase_match = PHRASE_SOURCE_RE.match(row["source_key"])
        if phrase_match:
            matched_response_ids.update(
                response_ids_by_subject_phrase.get(
                    phrase_match.group("phrase_id"),
                    set(),
                )
            )
        for response_id in matched_response_ids:
            progress[response_id]["has_highlight"] = True

    return _finish_subject_progress(progress)


def _finish_subject_progress(progress) -> dict[int, SubjectProgress]:
    """Turn the collected per-response flags into display-ready summaries."""
    results = {}
    for response_id, values in progress.items():
        if values["explicitly_completed"]:
            status = "done"
            label = "Terminé"
        elif (
            values["has_highlight"]
            or values["response_practice_started"]
            or values["vocabulary_activity_started"]
        ):
            status = "active"
            label = "En cours"
        else:
            status = "new"
            label = "À commencer"
        results[response_id] = SubjectProgress(
            status=status,
            label=label,
            **values,
        )
    return results


def summarize_subject_progress(
    progress_items: Iterable[SubjectProgress],
) -> dict[str, int | str | ProgressSummary]:
    """Return deck-compatible totals for a group of sujets."""
    items = list(progress_items)
    summary = progress_summary(
        total=len(items),
        started=sum(item.status != "new" for item in items),
        completed=sum(item.status == "done" for item in items),
    )
    active = sum(item.status == "active" for item in items)
    mature = sum(
        item.status == "done"
        and bool(item.vocabulary_total)
        and item.vocabulary_mastered == item.vocabulary_total
        for item in items
    )
    return {
        "progress": summary,
        "status": summary.status,
        "status_label": summary.label,
        "total": summary.total,
        "new": summary.total - summary.started,
        "started_new": active,
        "learning": 0,
        "review": summary.completed,
        "completed": summary.completed,
        "mature": mature,
        "review_young": summary.completed - mature,
        "due": sum(item.vocabulary_due for item in items),
        "seen": summary.started,
        "reviewed": summary.completed,
        "pct": (
            round(100 * summary.started / summary.total)
            if summary.total
            else 0
        ),
        "completed_pct": summary.percent,
        "mature_pct": (
            round(100 * mature / summary.total) if summary.total else 0
        ),
    }
