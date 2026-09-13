from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("trips", "0017_convert_planning_steps"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="tripagentconversationsession",
            index=models.Index(fields=["trip", "step", "is_active"], name="trips_tripa_trip_id_c0cc6f_idx"),
        ),
    ]
