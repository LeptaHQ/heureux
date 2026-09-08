"""Subject highlight scoping preserves the legacy resolver without overfetch."""

from contextlib import contextmanager
from unittest.mock import patch

from django.db import connection
from django.db.models import Q
from django.db.models.query import ValuesIterable
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from study.models import Annotation, AnnotationKind, PhraseTier, Prompt, Response
from study.progress import _batches, subject_progress_by_response

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
            number=100, text="Equivalent subject",
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
        return rows, responses

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
                self.assertEqual(len(queries), 3 if not count else 4)
                self.assertFalse(result[self.response.pk].has_highlight)

    def test_large_response_sets_bound_parameters_and_queries_not_note_count(self):
        responses = Response.objects.bulk_create([
            Response(
                content_key=f"large-scope:{index}", theme=self.theme,
                family=self.response.family, body_hash=f"scope-{index}",
            )
            for index in range(700)
        ])
        ids = [self.response.pk, *(response.pk for response in responses)]
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
            self.assertEqual(len(queries), 12)
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
        self.assertEqual(len(queries), 12)
        self.assertLessEqual(max(parameter_counts), 999)
