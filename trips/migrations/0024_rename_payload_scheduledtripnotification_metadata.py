from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("trips", "0023_alter_scheduledtripnotification_event_type"),
    ]

    operations = [
        migrations.RenameField(
            model_name="scheduledtripnotification",
            old_name="payload",
            new_name="metadata",
        ),
    ]
