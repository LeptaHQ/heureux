from django.db import migrations


def restore_personal_note_groups(apps, schema_editor):
    annotation = apps.get_model("study", "Annotation")
    annotation.objects.using(schema_editor.connection.alias).filter(
        kind="note",
        quote="",
        source_path="",
        source_key="",
        task__isnull=False,
    ).update(task=None)


class Migration(migrations.Migration):
    dependencies = [
        ("study", "0056_personal_task_response"),
    ]

    operations = [
        migrations.RunPython(restore_personal_note_groups, migrations.RunPython.noop),
    ]
