import django.db.models.deletion
import django.utils.timezone
from itertools import batched
from django.conf import settings
from django.db import migrations, models


def import_saved_practice(apps, schema_editor):
    db = schema_editor.connection.alias
    live = apps.get_model("study", "LiveSimulation").objects.using(db)
    attempts = apps.get_model("study", "EO2PracticeAttempt").objects.using(db)
    statuses = apps.get_model("study", "EO2TopicStatus").objects.using(db)
    # Read metadata only; previously expired/deleted recordings cannot be reconstructed.
    existing = live.exclude(subject_key__startswith="eo3:").order_by()
    metadata = existing.values_list("pk", "user_id", "subject_key", "created_at").iterator()
    for batch in batched(metadata, 500):
        attempts.bulk_create([
            attempts.model(user_id=user, subject_key=key, attempt=pk, live_simulation_id=pk, vocal=True, created_at=created)
            for pk, user, key, created in batch
        ])
    for batch in batched(existing.values_list("user_id", "subject_key").distinct().iterator(), 500):
        statuses.bulk_create([statuses.model(user_id=user, subject_key=key, done=True) for user, key in batch])


class Migration(migrations.Migration):

    dependencies = [
        ('study', '0069_live_simulation'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EO2PracticeAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('subject_key', models.CharField(blank=True, max_length=120)),
                ('attempt', models.UUIDField()),
                ('vocal', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('live_simulation', models.OneToOneField(null=True, on_delete=django.db.models.deletion.SET_NULL, to='study.livesimulation')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'indexes': [models.Index(fields=['user', 'subject_key', '-created_at'], name='eo2_practice_by_topic')],
                'constraints': [models.UniqueConstraint(fields=('user', 'attempt'), name='eo2_one_practice_attempt')],
            },
        ),
        migrations.CreateModel(
            name='EO2TopicStatus',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('subject_key', models.CharField(blank=True, max_length=120)),
                ('done', models.BooleanField(default=False)),
                ('retry', models.BooleanField(default=False)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('user', 'subject_key'), name='eo2_one_topic_status')],
            },
        ),
        migrations.RunPython(import_saved_practice, migrations.RunPython.noop),
    ]
