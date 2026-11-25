from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("study", "0074_oral_simulation_provider_reports"),
    ]

    operations = [
        migrations.AddField(
            model_name="livesimulation",
            name="snapshot",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="livesimulation",
            name="evaluation_claims",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
