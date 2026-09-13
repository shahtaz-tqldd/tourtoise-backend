from django.db import migrations, models


def forwards(apps, schema_editor):
    Trip = apps.get_model("trips", "Trip")
    Trip.objects.filter(visibility="link_only").update(visibility="public")


def backwards(apps, schema_editor):
    Trip = apps.get_model("trips", "Trip")
    Trip.objects.filter(visibility="public").update(visibility="link_only")


class Migration(migrations.Migration):

    dependencies = [
        ("trips", "0006_remove_tripitineraryitem_day_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="trip",
            name="visibility",
            field=models.CharField(
                choices=[("private", "Private"), ("public", "Public")],
                default="private",
                max_length=15,
            ),
        ),
    ]
