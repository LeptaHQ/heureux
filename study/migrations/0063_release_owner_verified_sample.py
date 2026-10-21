from django.db import migrations

SAMPLE_GROUP = "eo/tache-3/culture-p1"
# The single one-shot sample attempt was rejected by ElevenLabs with "Free plans
# can only use default voices through the API" before structured detection existed.
# The owner saw that exact error, upgraded the plan and explicitly authorized a retry.


def release_owner_verified_sample(apps, schema_editor):
    Budget = apps.get_model("study", "FrenchNarrationBudget")
    Narration = apps.get_model("study", "FrenchNarration")
    Recording = apps.get_model("study", "EO3Narration")
    budget = Budget.objects.filter(pk=1, sample_claimed=True).first()
    if budget is None or Recording.objects.filter(group=SAMPLE_GROUP).exists():
        return
    attempts = Narration.objects.filter(target_group=SAMPLE_GROUP).exclude(status="pending")
    statuses = list(attempts.values_list("status", flat=True))
    if len(statuses) != 1:
        return
    if statuses[0] != "failed":
        return
    # Reserved characters stay counted; only the single proven-unbilled slot is released.
    Narration.objects.filter(target_group=SAMPLE_GROUP).delete()
    budget.sample_claimed = False
    budget.save(update_fields=["sample_claimed"])


class Migration(migrations.Migration):
    dependencies = [("study", "0062_subject_status_reset")]

    operations = [
        migrations.RunPython(release_owner_verified_sample, migrations.RunPython.noop),
    ]
