from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from django.test import TestCase, TransactionTestCase, tag

from study.models import Annotation, AnnotationKind

from . import factories


ADDED = ("study", "0058_annotation_response_anchor")
REPAIRED = ("study", "0059_response_anchor_database_default")
REPLACEMENT = ("study", "0058_squashed_response_anchor_default")


class LegacyAnnotationInsert:
    def insert_from_old_worker(self, kind):
        values = {
            "user": self.user, "kind": kind,
            "body": "A note saved by the preceding worker.",
            "source_key": f"rolling-schema:{kind}",
        }
        if kind == AnnotationKind.HIGHLIGHT:
            values.update(quote="Retained text.", start_offset=0, end_offset=14)
        template = Annotation.objects.create(**values)
        columns = [
            field.column for field in Annotation._meta.local_concrete_fields
            if field.name not in {"id", "response_anchor", "hidden_on_source"}
        ]
        table = connection.ops.quote_name(Annotation._meta.db_table)
        names = ", ".join(connection.ops.quote_name(column) for column in columns)
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT {names} FROM {table} WHERE id = %s", [template.pk])
            row = cursor.fetchone()
        template.delete()
        placeholders = ", ".join(["%s"] * len(columns))
        with connection.cursor() as cursor:
            cursor.execute(f"INSERT INTO {table} ({names}) VALUES ({placeholders})", row)
        return Annotation.objects.get(user=self.user, source_key=values["source_key"])


@tag("database-locking")
class AnnotationAnchorSchemaTests(LegacyAnnotationInsert, TestCase):
    def setUp(self):
        self.user = factories.make_user("legacy-annotation-writer")

    def test_legacy_column_inserts_keep_notes_and_highlights_unscoped(self):
        self.assertTrue(Annotation._meta.get_field("response_anchor").has_db_default())
        self.assertTrue(Annotation._meta.get_field("hidden_on_source").has_db_default())
        for kind in (AnnotationKind.NOTE, AnnotationKind.HIGHLIGHT):
            with self.subTest(kind=kind):
                saved = self.insert_from_old_worker(kind)
                self.assertEqual(saved.response_anchor, {})
                self.assertEqual(saved.body, "A note saved by the preceding worker.")
                self.assertEqual(saved.kind, kind)
                self.assertFalse(saved.hidden_on_source)

    def test_fresh_upgrades_add_the_column_with_a_persistent_default(self):
        applied = MigrationRecorder(connection).applied_migrations()
        for migration in (ADDED, REPAIRED, REPLACEMENT):
            applied.pop(migration, None)
        with patch.object(MigrationRecorder, "applied_migrations", return_value=applied):
            loader = MigrationLoader(connection)
        self.assertIn(REPLACEMENT, loader.graph.nodes)
        self.assertNotIn(ADDED, loader.graph.nodes)
        replacement = loader.get_migration(*REPLACEMENT)
        self.assertTrue(replacement.operations[0].field.has_db_default())

    def test_an_already_applied_0058_runs_the_corrective_migration(self):
        applied = MigrationRecorder(connection).applied_migrations()
        applied[ADDED] = True
        applied.pop(REPAIRED, None)
        applied.pop(REPLACEMENT, None)
        with patch.object(MigrationRecorder, "applied_migrations", return_value=applied):
            loader = MigrationLoader(connection)
        self.assertIn(REPAIRED, loader.graph.nodes)
        self.assertNotIn(REPLACEMENT, loader.graph.nodes)
        old = loader.project_state([ADDED]).apps.get_model("study", "Annotation")
        new = loader.project_state([REPAIRED]).apps.get_model("study", "Annotation")
        self.assertFalse(old._meta.get_field("response_anchor").has_db_default())
        self.assertTrue(new._meta.get_field("response_anchor").has_db_default())


@tag("database-locking")
class AnnotationAnchorUpgradeTests(LegacyAnnotationInsert, TransactionTestCase):
    def test_0059_repairs_the_published_schema_without_changing_existing_records(self):
        self.user = factories.make_user("existing-anchor-upgrade")
        existing = Annotation.objects.create(
            user=self.user, kind=AnnotationKind.NOTE, body="Keep this existing note.",
        )
        saved = Annotation.objects.filter(pk=existing.pk).values().get()
        loader = MigrationLoader(connection, replace_migrations=False)
        old_state = loader.project_state([ADDED])
        old = old_state.apps.get_model("study", "Annotation")
        old_field = old._meta.get_field("response_anchor")
        current_field = Annotation._meta.get_field("response_anchor")
        # Simulate the old anchor default without dropping later annotation columns.
        old_state = loader.project_state(loader.graph.leaf_nodes())
        old_state.alter_field(
            "study", "annotation", "response_anchor", old_field.clone(), preserve_default=True,
        )
        with connection.schema_editor() as editor:
            editor.alter_field(Annotation, current_field, old_field)
        try:
            with self.assertRaises(IntegrityError), transaction.atomic():
                self.insert_from_old_worker(AnnotationKind.NOTE)
            with connection.schema_editor() as editor:
                loader.get_migration(*REPAIRED).apply(old_state, editor)
            for kind in (AnnotationKind.NOTE, AnnotationKind.HIGHLIGHT):
                with self.subTest(kind=kind):
                    self.assertEqual(self.insert_from_old_worker(kind).response_anchor, {})
            self.assertEqual(Annotation.objects.filter(pk=existing.pk).values().get(), saved)
        finally:
            with connection.schema_editor() as editor:
                editor.alter_field(Annotation, old_field, current_field)
