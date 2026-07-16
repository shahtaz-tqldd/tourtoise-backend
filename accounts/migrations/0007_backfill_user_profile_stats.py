from django.db import migrations


def backfill_user_profile_stats(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    UserProfile = apps.get_model("accounts", "UserProfile")
    Journal = apps.get_model("journals", "Journal")
    Trip = apps.get_model("trips", "Trip")
    TripDestination = apps.get_model("trips", "TripDestination")

    for user in User.objects.all().only("id"):
        profile, _ = UserProfile.objects.get_or_create(user_id=user.id)
        completed_trips = Trip.objects.filter(user_id=user.id, status="completed")
        countries = TripDestination.objects.filter(
            trip__user_id=user.id,
            trip__status="completed",
        ).values_list("destination__country", flat=True)

        visited_countries = []
        seen = set()
        for country in countries:
            country = str(country or "").strip()
            key = country.casefold()
            if key and key not in seen:
                visited_countries.append(country)
                seen.add(key)

        profile.visited_country_list = visited_countries
        profile.total_country_visited = len(visited_countries)
        profile.total_trip_count = completed_trips.count()
        profile.total_journal_count = Journal.objects.filter(author_id=user.id).count()
        profile.save(
            update_fields=[
                "visited_country_list",
                "total_country_visited",
                "total_trip_count",
                "total_journal_count",
            ]
        )

    Trip.objects.filter(status="completed").update(completed_stats_recorded=True)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_user_deleted_at_and_more"),
        ("journals", "0001_initial"),
        ("trips", "0014_trip_completed_stats_recorded"),
    ]

    operations = [
        migrations.RunPython(backfill_user_profile_stats, migrations.RunPython.noop),
    ]
