from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from accounts.models import UserProfile

User = get_user_model()


def ensure_user_profile(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def increment_user_journal_count(user, amount=1):
    ensure_user_profile(user)
    UserProfile.objects.filter(user=user).update(
        total_journal_count=F("total_journal_count") + amount
    )


def decrement_user_journal_count(user, amount=1):
    ensure_user_profile(user)
    profile = UserProfile.objects.select_for_update().get(user=user)
    profile.total_journal_count = max(profile.total_journal_count - amount, 0)
    profile.save(update_fields=["total_journal_count"])


def record_completed_trip_stats(trip):
    if trip.status != "completed" or trip.completed_stats_recorded:
        return False

    countries = [
        country
        for country in trip.trip_destinations.order_by("sort_order").values_list(
            "destination__country", flat=True
        )
        if country
    ]
    normalized_countries = []
    seen = set()
    for country in countries:
        key = country.strip().casefold()
        if key and key not in seen:
            normalized_countries.append(country.strip())
            seen.add(key)

    with transaction.atomic():
        locked_trip = type(trip).objects.select_for_update().get(pk=trip.pk)
        if locked_trip.completed_stats_recorded or locked_trip.status != "completed":
            return False

        ensure_user_profile(locked_trip.user)
        profile = UserProfile.objects.select_for_update().get(user=trip.user)
        existing_keys = {
            country.strip().casefold()
            for country in profile.visited_country_list
            if str(country).strip()
        }
        for country in normalized_countries:
            if country.casefold() not in existing_keys:
                profile.visited_country_list.append(country)
                existing_keys.add(country.casefold())

        profile.total_country_visited = len(profile.visited_country_list)
        profile.total_trip_count += 1
        profile.save(
            update_fields=[
                "visited_country_list",
                "total_country_visited",
                "total_trip_count",
            ]
        )
        locked_trip.completed_stats_recorded = True
        locked_trip.save(update_fields=["completed_stats_recorded", "updated_at"])
        trip.completed_stats_recorded = True
        return True
