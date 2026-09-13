from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("trips", "0026_tripitinerarybudget_accommodation"),
    ]

    operations = [
        migrations.AddField(
            model_name="scheduledtripnotification",
            name="agent_context_synced_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="tripconversationmessage",
            name="read_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RemoveIndex(
            model_name="tripconversationmessage",
            name="trips_tripc_session_088ae4_idx",
        ),
        migrations.RemoveIndex(
            model_name="tripconversationmessage",
            name="trips_tripc_session_79c870_idx",
        ),
        migrations.AddIndex(
            model_name="tripconversationmessage",
            index=models.Index(
                fields=["session", "created_at"],
                name="trip_chat_timeline_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="tripconversationmessage",
            index=models.Index(
                condition=models.Q(("sender", "agent")),
                fields=["session", "read_at"],
                name="trip_chat_unread_idx",
            ),
        ),
    ]
