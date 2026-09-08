"""Exact exposure projection, rolling-deployment compatibility and read bounds."""

from copy import deepcopy
from dataclasses import asdict, replace
from threading import Event, Thread, current_thread
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import JSONField
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature, tag
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from study import course_practice
from study.course_content import build_course_catalog
from study.course_practice import _exposures, start_attempt
from study.models import CourseAttempt, CourseExposureIndex, CourseItemExposure, ReviewSession

from . import factories
from .course_fixtures import course_lesson


def legacy_fields(user, lesson, *, status="abandoned", mode="check"):
    items = [
        {**asdict(item), "item_version": item.item_version, "exposure_key": item.exposure_key}
        for item in lesson.practice if item.pool == mode
    ]
    return {
        "user_id": user.pk, "lesson_id": lesson.id, "content_version": lesson.content_version,
        "mode": mode, "status": status,
        "snapshot": {
            "title": lesson.title, "slug": lesson.slug, "cefr_level": lesson.cefr_level,
            "version": lesson.version, "items": items,
        },
        "events": [
            {"action": "answer", "item_id": item["id"], "response": item["answers"][0],
             "correct": True, "hinted": False, "at": timezone.now().isoformat()}
            for item in items
        ] if status == "completed" else [],
        "submitted_at": timezone.now() if status == "completed" else None,
    }


def legacy_exposures(user, lesson):
    keys = {item.exposure_key for item in lesson.practice}
    ids = {item.id for item in lesson.practice}
    prompts, seen_ids = set(), set()
    for lesson_id, snapshot in CourseAttempt.objects.filter(user=user).values_list("lesson_id", "snapshot"):
        for item in snapshot["items"]:
            if item["exposure_key"] in keys:
                prompts.add(item["exposure_key"])
            if lesson_id == lesson.id and item["id"] in ids:
                seen_ids.add((lesson_id, item["id"]))
    return prompts, seen_ids


def measured_exposures(user, lesson):
    decoded = []
    original_decode = JSONField.from_db_value

    def decode(field, value, expression, db):
        if field.name in {"snapshot", "events"}:
            decoded.append((field.name, len(value.encode())))
        return original_decode(field, value, expression, db)

    with patch.object(JSONField, "from_db_value", decode), CaptureQueriesContext(connection) as queries:
        result = _exposures(user, lesson)
    return result, list(queries), decoded


class CourseExposureTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("exposure-owner", pin="482731")
        self.lesson = course_lesson()

    def legacy(self, lesson=None, **kwargs):
        return CourseAttempt.objects.create(**legacy_fields(self.user, lesson or self.lesson, **kwargs))

    def test_every_status_and_unpublished_content_is_indexed_without_rewriting_history(self):
        for status in ("active", "abandoned", "completed"):
            self.legacy(replace(self.lesson, id=f"a1-removed-{status}"), status=status)
        self.legacy(status="completed", mode="practice")
        self.legacy(mode="review")
        original = list(CourseAttempt.objects.order_by("pk").values())
        expected = legacy_exposures(self.user, self.lesson)
        self.assertEqual(_exposures(self.user, self.lesson), expected)
        self.assertEqual(CourseExposureIndex.objects.count(), 5)
        self.assertEqual(CourseItemExposure.objects.count(), 32)
        self.assertEqual(list(CourseAttempt.objects.order_by("pk").values()), original)
        self.assertFalse(any(row["assessed"] for row in course_practice.practice_guidance(self.user, self.lesson)))

    def test_prompt_and_same_lesson_identity_rules_survive_edits(self):
        self.legacy()
        for lesson in (
            replace(self.lesson, practice=tuple(
                replace(item, id="renamed-" + item.id) for item in self.lesson.practice
            )),
            replace(self.lesson, practice=tuple(
                replace(item, prompt="Changed: " + item.prompt) for item in self.lesson.practice
            )),
            replace(self.lesson, id="a1-another-lesson"),
            replace(self.lesson, practice=tuple(
                replace(item, answers=("different",), explanation="New explanation")
                for item in self.lesson.practice
            )),
        ):
            with self.subTest(lesson=lesson.id, item=lesson.practice[4]):
                self.assertEqual(_exposures(self.user, lesson), legacy_exposures(self.user, lesson))
        self.assertEqual(CourseExposureIndex.objects.count(), 1)

    def test_same_ids_in_unrelated_lesson_and_other_users_are_not_exposure(self):
        self.legacy(course_lesson("A2"))
        other = factories.make_user("exposure-other")
        CourseAttempt.objects.create(**legacy_fields(other, self.lesson))
        self.assertEqual(_exposures(self.user, self.lesson), (set(), set()))
        self.assertEqual(CourseExposureIndex.objects.count(), 1)
        self.assertFalse(CourseItemExposure.objects.filter(user=other).exists())

    def test_late_legacy_insert_fetches_only_its_snapshot_then_none(self):
        self.legacy(mode="practice")
        _exposures(self.user, self.lesson)
        late = self.legacy(status="active")
        result, _, decoded = measured_exposures(self.user, self.lesson)
        self.assertEqual(result, legacy_exposures(self.user, self.lesson))
        self.assertEqual([field for field, size in decoded], ["snapshot"])
        self.assertTrue(CourseExposureIndex.objects.filter(attempt=late).exists())
        self.assertEqual(measured_exposures(self.user, self.lesson)[2], [])

    def test_warm_reads_have_fixed_queries_and_no_historical_json(self):
        fields = legacy_fields(self.user, course_lesson("A2"), status="completed")
        previous = 0
        for count in (0, 100, 1000):
            CourseAttempt.objects.bulk_create([
                CourseAttempt(**deepcopy(fields)) for _ in range(count - previous)
            ], batch_size=100)
            _, _, cold_decoded = measured_exposures(self.user, self.lesson)
            self.assertEqual(len(cold_decoded), count - previous)
            result, queries, decoded = measured_exposures(self.user, self.lesson)
            self.assertEqual(result, (set(), set()))
            self.assertEqual(len(queries), 6)  # Atomic boundary plus four SELECTs.
            self.assertEqual(decoded, [])
            self.assertFalse(any('"snapshot"' in row["sql"] or '"events"' in row["sql"] for row in queries))
            self.assertEqual(CourseExposureIndex.objects.count(), count)
            previous = count

    def test_repeated_relevant_exposures_return_only_candidate_identities(self):
        fields = legacy_fields(self.user, self.lesson)
        CourseAttempt.objects.bulk_create([CourseAttempt(**deepcopy(fields)) for _ in range(105)])
        result = _exposures(self.user, self.lesson)
        self.assertEqual(result, legacy_exposures(self.user, self.lesson))
        self.assertEqual(tuple(map(len, result)), (8, 8))
        self.assertLessEqual(sum(map(len, result)), 2 * len(self.lesson.practice))
        self.assertEqual(CourseExposureIndex.objects.count(), 105)
        self.assertEqual(CourseItemExposure.objects.count(), 840)

    def test_practice_get_warm_footprint_does_not_grow_with_unrelated_history(self):
        self.client.force_login(self.user)
        url = reverse("study:course_practice", args=[self.lesson.slug])
        fields = legacy_fields(self.user, course_lesson("A2"), status="completed")
        with patch("study.views.course.load_course_catalog", return_value=build_course_catalog([self.lesson])):
            previous = 0
            for count in (0, 100, 1000):
                CourseAttempt.objects.bulk_create([
                    CourseAttempt(**deepcopy(fields)) for _ in range(count - previous)
                ], batch_size=100)
                self.client.get(url)
                with (
                    patch.object(CourseAttempt._meta.get_field("snapshot"), "from_db_value") as decode,
                    CaptureQueriesContext(connection) as queries,
                ):
                    response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(queries), 12)
                decode.assert_not_called()
                self.assertEqual(response.context["evidence"]["fresh_review_available"], True)
                previous = count

    def test_start_and_resume_index_allocation_atomically(self):
        attempt = start_attempt(self.user, self.lesson, "check")
        self.assertTrue(attempt.independent)
        self.assertEqual(attempt.item_exposures.count(), 8)
        self.assertEqual(attempt.exposure_index.pk, attempt.pk)
        with self.assertNumQueries(5):
            self.assertEqual(start_attempt(self.user, self.lesson, "check").pk, attempt.pk)
        self.assertEqual(CourseExposureIndex.objects.count(), 1)
        course_practice.abandon_attempt(self.user, attempt.pk)
        legacy = self.legacy(status="active")
        self.assertEqual(start_attempt(self.user, self.lesson, "check").pk, legacy.pk)
        self.assertTrue(CourseExposureIndex.objects.filter(attempt=legacy).exists())
        course_practice.abandon_attempt(self.user, legacy.pk)
        self.assertFalse(start_attempt(self.user, self.lesson, "check").independent)

    def test_failed_readiness_rolls_back_catch_up_and_retries_cleanly(self):
        attempt = self.legacy()
        with patch.object(CourseExposureIndex.objects, "bulk_create", side_effect=RuntimeError("index failed")):
            with self.assertRaisesRegex(RuntimeError, "index failed"):
                _exposures(self.user, self.lesson)
        self.assertFalse(CourseExposureIndex.objects.exists())
        self.assertFalse(CourseItemExposure.objects.exists())
        self.assertTrue(CourseAttempt.objects.filter(pk=attempt.pk).exists())
        _exposures(self.user, self.lesson)
        self.assertEqual(CourseItemExposure.objects.count(), 8)

    def test_failed_new_allocation_leaves_no_attempt_or_partial_projection(self):
        with patch.object(CourseExposureIndex.objects, "bulk_create", side_effect=RuntimeError("index failed")):
            with self.assertRaisesRegex(RuntimeError, "index failed"):
                start_attempt(self.user, self.lesson, "check")
        self.assertFalse(CourseAttempt.objects.exists())
        self.assertFalse(CourseExposureIndex.objects.exists())
        self.assertFalse(CourseItemExposure.objects.exists())
        self.assertTrue(start_attempt(self.user, self.lesson, "check").independent)

    def test_invalid_legacy_snapshot_is_not_silently_marked_ready(self):
        fields = legacy_fields(self.user, self.lesson)
        del fields["snapshot"]["items"][0]["exposure_key"]
        self.legacy()
        CourseAttempt.objects.create(**fields)
        with self.assertRaises(KeyError):
            _exposures(self.user, self.lesson)
        self.assertFalse(CourseExposureIndex.objects.exists())
        self.assertFalse(CourseItemExposure.objects.exists())

    def test_reset_and_user_deletion_cascade_without_affecting_other_users(self):
        own = start_attempt(self.user, self.lesson, "check")
        other = factories.make_user("exposure-other", pin="482731")
        other_attempt = start_attempt(other, self.lesson, "check")
        self.client.force_login(self.user)
        response = self.client.post(reverse("study:reset_progress"), {
            "current_pin": "482731", "confirmation": "REINITIALISER",
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CourseExposureIndex.objects.filter(attempt_id=own.pk).exists())
        self.assertFalse(CourseItemExposure.objects.filter(user=self.user).exists())
        self.assertTrue(CourseExposureIndex.objects.filter(attempt=other_attempt).exists())
        self.assertTrue(start_attempt(self.user, self.lesson, "check").independent)
        self.client.force_login(other)
        response = self.client.post(reverse("study:delete_account"), {
            "current_pin": "482731", "username_confirmation": other.username,
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(CourseExposureIndex.objects.filter(attempt_id=other_attempt.pk).exists())
        self.assertFalse(CourseItemExposure.objects.filter(user_id=other.pk).exists())
        self.assertTrue(CourseItemExposure.objects.filter(user=self.user).exists())


class ExposureMigrationCases:
    migrate_from = ("study", "0049_annotation_listing_indexes")
    migrate_to = ("study", "0050_course_exposure_projection")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        self.old_apps = executor.loader.project_state([self.migrate_from]).apps
        self.addCleanup(self.migrate_forward)
        self.user = factories.make_user("migration-exposure-owner")
        self.lesson = course_lesson()
        self.old_attempt = self.old_apps.get_model("study", "CourseAttempt")

    def migrate_forward(self):
        MigrationExecutor(connection).migrate([self.migrate_to])

    def native_actions(self, table):
        with connection.cursor() as cursor:
            if connection.vendor == "sqlite":
                cursor.execute(f"PRAGMA foreign_key_list({connection.ops.quote_name(table)})")
                return [row[6] for row in cursor.fetchall()]
            cursor.execute(
                "SELECT confdeltype FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'f'",
                [table],
            )
            return ["CASCADE" if row[0] == "c" else row[0] for row in cursor.fetchall()]

    def raw_delete(self, attempt):
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM study_courseattempt WHERE id = %s",
                [CourseAttempt._meta.pk.get_db_prep_value(attempt.pk, connection)],
            )

    def test_old_state_all_status_backfill_and_late_insert(self):
        original = []
        for status in ("active", "abandoned", "completed"):
            original.append(self.old_attempt.objects.create(
                **legacy_fields(self.user, replace(self.lesson, id=f"a1-{status}"), status=status),
            ))
        frozen = list(self.old_attempt.objects.order_by("pk").values())
        self.migrate_forward()
        _exposures(self.user, self.lesson)
        self.assertEqual(CourseExposureIndex.objects.count(), 3)
        self.assertEqual(list(self.old_attempt.objects.order_by("pk").values()), frozen)
        late = self.old_attempt.objects.create(**legacy_fields(self.user, self.lesson, mode="review"))
        _, _, decoded = measured_exposures(self.user, self.lesson)
        self.assertEqual(len(decoded), 1)
        self.assertTrue(CourseExposureIndex.objects.filter(attempt_id=late.pk).exists())
        self.assertEqual(measured_exposures(self.user, self.lesson)[2], [])

    def test_native_cascades_apply_only_to_new_tables_and_survive_reapplication(self):
        original_actions = self.native_actions("study_courseattempt")
        for _ in range(2):
            self.migrate_forward()
            self.assertEqual(self.native_actions("study_courseexposureindex"), ["CASCADE"])
            self.assertEqual(self.native_actions("study_courseitemexposure"), ["CASCADE", "CASCADE"])
            self.assertEqual(self.native_actions("study_courseattempt"), original_actions)
            MigrationExecutor(connection).migrate([self.migrate_from])
            self.assertNotIn("study_courseexposureindex", connection.introspection.table_names())
            self.assertNotIn("study_courseitemexposure", connection.introspection.table_names())

    def test_raw_attempt_delete_cascades_and_rollback_restores_everything(self):
        attempt = self.old_attempt.objects.create(**legacy_fields(self.user, self.lesson))
        self.migrate_forward()
        _exposures(self.user, self.lesson)
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with transaction.atomic():
                self.raw_delete(attempt)
                self.assertFalse(CourseExposureIndex.objects.exists())
                self.assertFalse(CourseItemExposure.objects.exists())
                raise RuntimeError("rollback")
        self.assertTrue(CourseAttempt.objects.filter(pk=attempt.pk).exists())
        self.assertEqual(CourseExposureIndex.objects.count(), 1)
        self.assertEqual(CourseItemExposure.objects.count(), 8)
        self.raw_delete(attempt)
        connection.check_constraints()
        self.assertFalse(CourseExposureIndex.objects.exists())
        self.assertFalse(CourseItemExposure.objects.exists())

    def test_legacy_collectors_can_reset_and_delete_user_after_indexing(self):
        self.old_attempt.objects.create(**legacy_fields(self.user, self.lesson))
        self.migrate_forward()
        _exposures(self.user, self.lesson)
        self.old_attempt.objects.filter(user_id=self.user.pk).delete()
        connection.check_constraints()
        self.assertFalse(CourseExposureIndex.objects.exists())
        self.assertFalse(CourseItemExposure.objects.exists())
        self.old_attempt.objects.create(**legacy_fields(self.user, self.lesson))
        _exposures(self.user, self.lesson)
        old_user = self.old_apps.get_model(get_user_model()._meta.label).objects.get(pk=self.user.pk)
        old_user.delete()
        connection.check_constraints()
        self.assertFalse(CourseAttempt.objects.exists())
        self.assertFalse(CourseExposureIndex.objects.exists())
        self.assertFalse(CourseItemExposure.objects.exists())


class CourseExposureMigrationTests(ExposureMigrationCases, TransactionTestCase):
    pass


@skipUnlessDBFeature("has_select_for_update")
@tag("database-locking")
class PostgresCourseExposureMigrationTests(ExposureMigrationCases, TransactionTestCase):
    pass


@skipUnlessDBFeature("has_select_for_update")
@tag("database-locking")
class CourseExposureConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = factories.make_user("exposure-concurrency", pin="482731")
        self.lesson = course_lesson()
        self.client.force_login(self.user)

    def while_indexing(self, first_operation, other_operation):
        indexing, attempted_lock, acquired_lock, release = Event(), Event(), Event(), Event()
        original_index = course_practice._index_attempts
        original_lock = course_practice.lock_course_user
        failures, results = [], {}

        def delayed_index(attempts):
            if current_thread().name == "course-indexer":
                indexing.set()
                if not release.wait(15):
                    raise TimeoutError("Indexing was not released")
            return original_index(attempts)

        def observed_lock(user):
            if current_thread().name == "course-contender":
                attempted_lock.set()
            result = original_lock(user)
            if current_thread().name == "course-contender":
                acquired_lock.set()
            return result

        def run(name, operation):
            try:
                results[name] = operation()
            except BaseException as exc:  # Thread failures must reach the test runner.
                failures.append(exc)
            finally:
                connections.close_all()

        first = Thread(target=run, args=("first", first_operation), name="course-indexer")
        other = Thread(target=run, args=("other", other_operation), name="course-contender")
        with (
            patch.object(course_practice, "_index_attempts", delayed_index),
            patch.object(course_practice, "lock_course_user", observed_lock),
            patch("study.views.account.lock_course_user", observed_lock),
        ):
            first.start()
            try:
                self.assertTrue(indexing.wait(15), failures)
                other.start()
                self.assertTrue(attempted_lock.wait(15), failures)
                self.assertFalse(acquired_lock.wait(0.2))
            finally:
                release.set()
                first.join(20)
                if other.ident is not None:
                    other.join(20)
        self.assertFalse(first.is_alive())
        self.assertFalse(other.is_alive())
        self.assertEqual(failures, [])
        return results

    def test_cross_lesson_starts_serialize_shared_prompt_freshness(self):
        second_lesson = replace(self.lesson, id="a1-shared-prompts")
        results = self.while_indexing(
            lambda: start_attempt(self.user, self.lesson, "check"),
            lambda: start_attempt(self.user, second_lesson, "check"),
        )
        self.assertTrue(results["first"].independent)
        self.assertFalse(results["other"].independent)
        self.assertEqual(CourseExposureIndex.objects.count(), 2)

    def test_same_mode_concurrent_starts_resume_one_allocation(self):
        results = self.while_indexing(
            lambda: start_attempt(self.user, self.lesson, "check"),
            lambda: start_attempt(self.user, self.lesson, "check"),
        )
        self.assertEqual(results["first"].pk, results["other"].pk)
        self.assertEqual(CourseAttempt.objects.count(), 1)
        self.assertEqual(CourseItemExposure.objects.count(), 8)

    def test_concurrent_catch_up_has_one_complete_projection(self):
        CourseAttempt.objects.create(**legacy_fields(self.user, self.lesson))
        results = self.while_indexing(
            lambda: _exposures(self.user, self.lesson),
            lambda: _exposures(self.user, self.lesson),
        )
        self.assertEqual(results["first"], results["other"])
        self.assertEqual(CourseExposureIndex.objects.count(), 1)
        self.assertEqual(CourseItemExposure.objects.count(), 8)

    def test_reset_waits_for_reconciliation_then_cascades(self):
        CourseAttempt.objects.create(**legacy_fields(self.user, self.lesson))
        results = self.while_indexing(
            lambda: _exposures(self.user, self.lesson),
            lambda: self.client.post(reverse("study:reset_progress"), {
                "current_pin": "482731", "confirmation": "REINITIALISER",
            }),
        )
        self.assertEqual(results["other"].status_code, 302)
        self.assertFalse(CourseAttempt.objects.exists())
        self.assertFalse(CourseItemExposure.objects.exists())
        self.assertFalse(CourseExposureIndex.objects.exists())

    def test_account_deletion_waits_for_reconciliation_then_cascades(self):
        CourseAttempt.objects.create(**legacy_fields(self.user, self.lesson))
        results = self.while_indexing(
            lambda: _exposures(self.user, self.lesson),
            lambda: self.client.post(reverse("study:delete_account"), {
                "current_pin": "482731", "username_confirmation": self.user.username,
            }),
        )
        self.assertEqual(results["other"].status_code, 302)
        self.assertFalse(get_user_model().objects.filter(pk=self.user.pk).exists())
        self.assertFalse(CourseAttempt.objects.exists())
        self.assertFalse(CourseItemExposure.objects.exists())
        self.assertFalse(CourseExposureIndex.objects.exists())

    def test_reset_user_lock_does_not_deadlock_review_user_foreign_key_checks(self):
        session = ReviewSession.load(self.user)
        waiting_for_review_session = Event()
        failures, results = [], []
        from study.views import account
        original_lock = account._locked_review_session

        def observed_review_lock(user):
            waiting_for_review_session.set()
            return original_lock(user)

        def reset():
            try:
                results.append(self.client.post(reverse("study:reset_progress"), {
                    "current_pin": "482731", "confirmation": "REINITIALISER",
                }).status_code)
            except BaseException as exc:  # Thread failures must reach the test runner.
                failures.append(exc)
            finally:
                connections.close_all()

        worker = Thread(target=reset)
        with patch.object(account, "_locked_review_session", observed_review_lock):
            try:
                with transaction.atomic():
                    ReviewSession.objects.select_for_update().get(pk=session.pk)
                    worker.start()
                    self.assertTrue(waiting_for_review_session.wait(15), failures)
                    # A review inserts user-owned rows while holding this session.
                    # PostgreSQL's deferred FK check takes this KEY SHARE lock.
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '3s'")
                        cursor.execute(
                            "SELECT id FROM auth_user WHERE id = %s FOR KEY SHARE",
                            [self.user.pk],
                        )
            finally:
                worker.join(20)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(results, [302])
