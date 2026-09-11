"""Subject highlight scoping preserves the legacy resolver without overfetch."""

from contextlib import contextmanager
import hashlib
import re
from unittest.mock import patch

from django.db import connection
from django.db.models import Q
from django.db.models.query import ValuesIterable
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from study.models import Annotation, AnnotationKind, PhraseTier, Prompt, Response
from study.progress import (
    _HIGHLIGHT_PATTERN_LIMIT,
    _batches,
    _numeric_patterns,
    _pack_patterns,
    subject_progress_by_response,
)

from . import factories


class BatchingTests(SimpleTestCase):
    def test_batches_support_iterators_and_partial_final_batches(self):
        values = iter(range(7))
        self.assertEqual(
            list(_batches(values, 3)), [(0, 1, 2), (3, 4, 5), (6,)]
        )
        self.assertEqual(list(_batches(values, 3)), [])

    def test_batches_reject_nonpositive_sizes(self):
        for size in (0, -1):
            with self.subTest(size=size):
                with self.assertRaisesMessage(ValueError, "must be positive"):
                    list(_batches([], size))

    def test_numeric_pattern_packing_is_bounded(self):
        prefix, suffix = "^route:(?:", ")$"
        numbers = {
            int.from_bytes(hashlib.sha256(str(index).encode()).digest()[:16], "big")
            for index in range(1000)
        }
        patterns = list(_pack_patterns(
            _numeric_patterns("subject-", numbers, prefix, suffix),
            prefix, suffix,
        ))
        self.assertGreater(len(patterns), 1)
        self.assertTrue(all(
            len(pattern) <= _HIGHLIGHT_PATTERN_LIMIT for pattern in patterns
        ))
        self.assertTrue(all(pattern.isascii() for pattern in patterns))
        for number in (min(numbers), max(numbers)):
            self.assertTrue(any(
                re.fullmatch(pattern, f"route:subject-000{number}")
                for pattern in patterns
            ))
        self.assertFalse(any(
            re.fullmatch(pattern, "route:subject-999")
            for pattern in patterns
        ))


class SubjectHighlightScopeTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("highlight-scope")
        self.other_user = factories.make_user("highlight-other")
        self.task = factories.make_task(factories.make_part("eo"), "tache-2")
        self.theme = factories.make_theme("scoped-highlights", task=self.task)
        self.response = factories.make_response(theme=self.theme)
        self.other_response = factories.make_response(theme=self.theme)
        self.prompt = self.response.prompts.get()
        self.prompt.content_key = "tache2:janvier:batch-01:subject-01"
        self.prompt.save(update_fields=["content_key"])
        self.other_prompt = self.other_response.prompts.get()
        self.other_prompt.content_key = "tache2:janvier:batch-02:subject-02"
        self.other_prompt.save(update_fields=["content_key"])
        self.alias = Prompt.objects.create(
            response=self.response, theme=self.theme, family=self.response.family,
            content_key="tache2:mars:batch-01:subject-12",
            number=max(self.prompt.number, self.other_prompt.number) + 1,
            text="Equivalent subject",
        )
        self.phrase = factories.make_phrase(tier=PhraseTier.SUBJECT)
        self.phrase.source_prompts.add(self.prompt)
        self.other_phrase = factories.make_phrase(tier=PhraseTier.SUBJECT)
        self.other_phrase.source_prompts.add(self.other_prompt)
        self.path = f"/expression/orale/tache-2/sujets/{self.prompt.pk}/"
        self.other_path = f"/expression/orale/tache-2/sujets/{self.other_prompt.pk}/"

    def _annotation(self, source_key="", source_path=None, **overrides):
        return Annotation.objects.create(
            source_key=source_key,
            source_path=self.path if source_path is None else source_path,
            **{
                "user": self.user, "task": self.task,
                "kind": AnnotationKind.HIGHLIGHT, "quote": "selected text",
                "start_offset": 0, "end_offset": 5,
                **overrides,
            },
        )

    def _legacy_rows(self, user, response_ids):
        rows = list(
            Annotation.objects.filter(user=user, kind=AnnotationKind.HIGHLIGHT)
            .filter(
                Q(source_key__startswith="response:")
                | Q(source_key__startswith="phrase:")
                | Q(source_key__startswith="tache-two:")
                | Q(source_path__contains="/sujets/")
            ).values("source_path", "source_key")
        )
        responses = dict(
            Response.objects.filter(pk__in=response_ids, is_active=True)
            .values_list("content_key", "pk")
        )
        prompts = list(
            Prompt.objects.filter(
                response_id__in=response_ids, is_active=True,
                response__is_active=True,
            ).values(
                "pk", "content_key", "response_id",
                "theme__task__part__slug", "theme__task__slug",
            )
        )
        return rows, responses, prompts

    def _assert_legacy_equal(self, expected_highlight):
        ids = {self.response.pk}
        with patch("study.progress._subject_highlight_rows", self._legacy_rows):
            legacy = subject_progress_by_response(self.user, ids)
        actual = subject_progress_by_response(self.user, ids)
        self.assertEqual(actual, legacy)
        self.assertEqual(actual[self.response.pk].has_highlight, expected_highlight)

    def test_every_source_shape_preserves_legacy_semantics(self):
        arabic = str.maketrans("0123456789", "\u0660\u0661\u0662\u0663\u0664"
                              "\u0665\u0666\u0667\u0668\u0669")
        key = self.response.content_key
        cases = [
            (f"response:{key}", self.path, True),
            (f"response:{key}:front", "/review/", True),
            (f"response:{key}:back", "/review/", True),
            (f"response:{key}:catalog", self.path, False),
            (f"response:{key}:front:back", self.path, False),
            (f"response:{key}-other:front", self.path, False),
            (f"response:{self.other_response.content_key}", self.path, False),
            (f"subject-sidebar:{key}", self.path, False),
            ("response:", self.path, False),
            (f"phrase:{self.phrase.phrase_id}:catalog", self.path, True),
            (f"phrase:{self.phrase.phrase_id}:", self.path, True),
            (f"phrase:{self.phrase.phrase_id}", self.path, False),
            (f"phrase:{self.phrase.phrase_id}x:front", self.path, False),
            (f"phrase:{self.other_phrase.phrase_id}:catalog", self.path, False),
            ("tache-two:janvier:batch-1:subject-1", "/review/", True),
            ("tache-two:janvier:batch-0001:subject-0001", "/review/", True),
            ("tache-two:janvier:batch-01:subject-01".translate(arabic),
             "/review/", True),
            ("tache-two:mars:batch-1:subject-12", "/review/", True),
            ("tache-two:janvier:batch-1:subject-1:front", self.path, False),
            ("tache-two:janvier:batch-2:subject-2", self.path, False),
            ("", self.path, True),
            ("", self.path + "?from=review#passage", True),
            ("", "https://example.test" + self.path + "?x=1", True),
            ("", self.path.replace("/sujets/", "/sujets/000"), True),
            ("", self.path.translate(arabic).replace("tache-\u0662", "tache-2"),
             True),
            ("", self.path.replace("expression", "expre\nssion"), True),
            ("", self.path.replace("/orale/", "/ecrite/"), False),
            ("", self.path.replace("tache-2", "tache-3"), False),
            ("", self.path.rstrip("/"), False),
            ("", "/unrelated/?next=" + self.path, False),
            ("", self.other_path + "?from=review", False),
        ]
        for source_key, source_path, expected in cases:
            with self.subTest(key=source_key, path=source_path):
                annotation = self._annotation(source_key, source_path)
                self._assert_legacy_equal(expected)
                annotation.delete()

    def test_user_kind_and_inactive_content_filters_are_preserved(self):
        key = f"response:{self.response.content_key}"
        annotation = self._annotation(key, user=self.other_user)
        self._assert_legacy_equal(False)
        annotation.delete()
        annotation = self._annotation(key, kind=AnnotationKind.NOTE)
        self._assert_legacy_equal(False)
        annotation.delete()
        for source_key in (
            key, "", "tache-two:mars:batch-1:subject-12",
            f"phrase:{self.phrase.phrase_id}:front",
        ):
            with self.subTest(key=source_key):
                annotation = self._annotation(source_key)
                self._assert_legacy_equal(True)
                Response.objects.filter(pk=self.response.pk).update(is_active=False)
                # Subject phrase activity historically follows active prompts,
                # whereas response/alias/path keys also require active responses.
                self._assert_legacy_equal(source_key.startswith("phrase:"))
                Response.objects.filter(pk=self.response.pk).update(is_active=True)
                self.response.prompts.update(is_active=False)
                self._assert_legacy_equal(source_key.startswith("response:"))
                self.response.prompts.update(is_active=True)
                annotation.delete()
        annotation = self._annotation(f"phrase:{self.phrase.phrase_id}:front")
        for field, value in (("is_active", False), ("tier", PhraseTier.RESPONSE)):
            with self.subTest(field=field):
                original = getattr(self.phrase, field)
                setattr(self.phrase, field, value)
                self.phrase.save(update_fields=[field])
                self._assert_legacy_equal(False)
                setattr(self.phrase, field, original)
                self.phrase.save(update_fields=[field])

    def test_related_highlight_changes_remain_fresh(self):
        self._assert_legacy_equal(False)
        annotation = self._annotation(f"response:{self.response.content_key}:back")
        self._assert_legacy_equal(True)
        annotation.delete()
        self._assert_legacy_equal(False)

    @contextmanager
    def _capture_materialized_highlights(self):
        rows = []
        original = ValuesIterable.__iter__

        def record(iterator):
            for row in original(iterator):
                if iterator.queryset.model is Annotation:
                    rows.append(row)
                yield row

        with patch.object(ValuesIterable, "__iter__", record):
            yield rows

    def _add_unrelated_highlights(self, start, stop):
        sources = (
            (f"response:{self.other_response.content_key}:front", self.path),
            (f"phrase:{self.other_phrase.phrase_id}:catalog", self.path),
            ("tache-two:janvier:batch-2:subject-2", self.path),
            ("", self.other_path + "?from=review"),
            ("", "/unrelated/?next=" + self.path),
        )
        Annotation.objects.bulk_create([
            Annotation(
                user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
                quote="unrelated same-task selection",
                source_key=sources[index % len(sources)][0],
                source_path=sources[index % len(sources)][1],
                start_offset=index, end_offset=index + 1,
            )
            for index in range(start, stop)
        ], batch_size=100)

    def _populated_scope(self, count):
        responses = Response.objects.bulk_create([
            Response(
                content_key=f"populated-scope:{index}", theme=self.theme,
                family=self.response.family, body_hash=f"populated-{index}",
            )
            for index in range(1, count)
        ])
        Prompt.objects.bulk_create([
            Prompt(
                response=response, theme=self.theme, family=self.response.family,
                content_key=f"tache2:{month}:batch-01:subject-{1000 + index:02d}",
                number=10000 + index * 2 + month_index,
                text="Active target subject",
            )
            for index, response in enumerate(responses, start=1)
            for month_index, month in enumerate(("janvier", "mars"))
        ])
        return [self.response, *responses]

    def test_ten_thousand_same_task_highlights_transfer_no_unrelated_rows(self):
        previous = 0
        for count in (0, 100, 10001):
            self._add_unrelated_highlights(previous, count)
            previous = count
            with self.subTest(highlights=count):
                with (
                    self._capture_materialized_highlights() as rows,
                    CaptureQueriesContext(connection) as queries,
                ):
                    result = subject_progress_by_response(self.user, [self.response.pk])
                self.assertEqual(rows, [])
                self.assertEqual(len(queries), 3 if not count else 6)
                self.assertFalse(result[self.response.pk].has_highlight)

    def test_large_response_sets_bound_parameters_and_queries_not_note_count(self):
        responses = self._populated_scope(701)
        ids = [response.pk for response in responses]
        self.assertEqual(
            Prompt.objects.filter(response_id__in=ids, is_active=True).count(),
            1402,
        )
        previous = 0
        for count in (100, 10001):
            self._add_unrelated_highlights(previous, count)
            previous = count
            parameter_counts = []

            def record_params(execute, sql, params, many, context):
                parameter_counts.append(len(params or ()))
                return execute(sql, params, many, context)

            with (
                self._capture_materialized_highlights() as rows,
                CaptureQueriesContext(connection) as queries,
                connection.execute_wrapper(record_params),
            ):
                result = subject_progress_by_response(self.user, ids)
            self.assertEqual(rows, [])
            self.assertEqual(len(result), len(ids))
            self.assertFalse(any(state.has_highlight for state in result.values()))
            self.assertEqual(len(queries), 10)
            self.assertLessEqual(max(parameter_counts), 999)

        self._annotation(f"response:{self.response.content_key}:front", "")
        self._annotation(f"response:{responses[-1].content_key}:back", "")
        with (
            self._capture_materialized_highlights() as rows,
            CaptureQueriesContext(connection) as queries,
            connection.execute_wrapper(record_params),
        ):
            result = subject_progress_by_response(self.user, ids)
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {pk for pk, state in result.items() if state.has_highlight},
            {self.response.pk, responses[-1].pk},
        )
        self.assertEqual(len(queries), 10)
        self.assertLessEqual(max(parameter_counts), 999)

    def test_populated_alias_and_legacy_scopes_use_static_candidate_patterns(self):
        responses = self._populated_scope(175)
        ids = [response.pk for response in responses]
        self.assertEqual(
            Prompt.objects.filter(response_id__in=ids, is_active=True).count(), 350
        )
        self.other_prompt.content_key = "tache2:janvier:batch-01:subject-999999"
        self.other_prompt.save(update_fields=["content_key"])
        last_prompt = responses[-1].prompts.order_by("pk").last()
        for shape in ("alias", "legacy"):
            with self.subTest(shape=shape):
                for prompt in (self.prompt, last_prompt):
                    key = (
                        prompt.content_key.replace("tache2:", "tache-two:", 1)
                        if shape == "alias" else ""
                    )
                    path = f"/expression/orale/tache-2/sujets/{prompt.pk}/"
                    self._annotation(key, path)
                    self._annotation(key, path, start_offset=8, end_offset=13)
                with patch("study.progress._subject_highlight_rows", self._legacy_rows):
                    legacy = subject_progress_by_response(self.user, ids)
                actual = subject_progress_by_response(self.user, ids)
                self.assertEqual(actual, legacy)
                self.assertEqual(
                    {pk for pk, state in actual.items() if state.has_highlight},
                    {self.response.pk, responses[-1].pk},
                )
                Annotation.objects.filter(user=self.user).delete()

                Annotation.objects.bulk_create([
                    Annotation(
                        user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
                        quote="Same-task, same-month, unrelated subject",
                        source_key="tache-two:janvier:batch-1:subject-999999"
                        if shape == "alias" else "",
                        source_path=self.other_path,
                        start_offset=index, end_offset=index + 1,
                    )
                    for index in range(1000)
                ], batch_size=100)
                statements = []

                def record(execute, sql, params, many, context):
                    statements.append((sql, params))
                    return execute(sql, params, many, context)

                with (
                    self._capture_materialized_highlights() as rows,
                    connection.execute_wrapper(record),
                ):
                    actual = subject_progress_by_response(self.user, ids)
                self.assertEqual(rows, [])
                self.assertFalse(any(state.has_highlight for state in actual.values()))
                self.assertEqual(len(statements), 5)
                self.assertLessEqual(
                    max(len(params or ()) for _, params in statements), 999
                )
                patterns = []
                for sql, params in statements:
                    if 'FROM "study_annotation"' in sql:
                        self.assertNotIn("study_prompt", sql)
                        patterns.extend(
                            value for value in params or ()
                            if isinstance(value, str) and value.startswith("^")
                        )
                self.assertTrue(patterns)
                self.assertTrue(all(
                    len(pattern) <= _HIGHLIGHT_PATTERN_LIMIT for pattern in patterns
                ))
                with patch("study.progress._subject_highlight_rows", self._legacy_rows):
                    legacy = subject_progress_by_response(self.user, ids)
                self.assertEqual(actual, legacy)
                Annotation.objects.filter(user=self.user).delete()
