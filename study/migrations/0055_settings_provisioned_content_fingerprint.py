from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("study", "0054_writing_response_controls"),
    ]

    operations = [
        migrations.AddField(
            model_name="settings",
            name="provisioned_content_fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
