from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("study", "0044_merge_equivalent_tache_two_annotations"),
    ]

    operations = [
        migrations.AddField(
            model_name="phrase",
            name="vocabulary_theme",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="direct_vocabulary_phrases",
                to="study.theme",
            ),
        ),
    ]
