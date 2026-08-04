from django.db import migrations


def convert_planning_steps(apps, schema_editor):
    step_map = {
        "1": "preference",
        "2": "recommendation",
        "3": "itinerary",
        "4": "preparation",
        "5": "overview",
        "6": "completed",
    }

    Trip = apps.get_model("trips", "Trip")
    TripAgentConversationSession = apps.get_model("trips", "TripAgentConversationSession")

    for old_value, new_value in step_map.items():
        Trip.objects.filter(current_step=old_value).update(current_step=new_value)
        TripAgentConversationSession.objects.filter(step=old_value).update(step=new_value)


class Migration(migrations.Migration):
    dependencies = [
        ("trips", "0016_remove_tripagentconversationsession_trips_tripa_trip_id_5c7bdc_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(convert_planning_steps, migrations.RunPython.noop),
    ]
