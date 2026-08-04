from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("trips", "0009_rename_origin_city_trip_origin_cty_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="trip",
            old_name="origin_cty",
            new_name="origin_city",
        ),
    ]
