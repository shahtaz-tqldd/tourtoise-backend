from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.db import transaction
from django.db.models import F
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from accounts.models import UserProfile
from accounts.tasks import send_password_reset_email


User = get_user_model()
password_reset_token_generator = PasswordResetTokenGenerator()


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


def build_password_reset_link(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = password_reset_token_generator.make_token(user)
    return (
        f"{settings.USER_FRONTEND_URL.rstrip('/')}"
        f"{settings.PASSWORD_RESET_PATH}"
        f"?uid={uid}&token={token}"
    )


def send_user_password_reset_email(user):
    reset_link = build_password_reset_link(user)
    context = {
        "recipient_name": user.name or user.email,
        "reset_link": reset_link,
    }
    subject = "Reset your Tourtoise password"
    message = render_to_string("accounts/emails/password_reset.txt", context)
    html_message = render_to_string("accounts/emails/password_reset.html", context)

    try:
        send_password_reset_email.delay(
            recipient_email=user.email,
            subject=subject,
            message=message,
            html_message=html_message,
        )
    except Exception:
        send_password_reset_email(
            recipient_email=user.email,
            subject=subject,
            message=message,
            html_message=html_message,
        )


def resolve_password_reset_user(uid, token):
    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        user = User.objects.get(pk=user_id)
    except Exception as exc:
        raise ValueError("Invalid password reset link.") from exc

    if not password_reset_token_generator.check_token(user, token):
        raise ValueError("Invalid or expired password reset link.")

    return user
