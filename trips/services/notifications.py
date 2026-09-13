import logging
import random
from datetime import datetime, time, timedelta, timezone as datetime_timezone
from functools import partial
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction
from django.utils import timezone

from notification.services import create_trip_notification, user_dashboard_group
from trips.choices import (
    AgentMessageSender,
    ScheduledNotificationStatusType,
    ScheduledTripDeliveryType,
    ScheduledTripEventType,
    TripStatus,
)
from trips.models import ScheduledTripNotification
from trips.services.trip_chat import (
    create_conversation_message,
    get_or_create_conversation_session,
)


logger = logging.getLogger(__name__)

PACKING_REMINDER_TIME = time(hour=17)
DAILY_SUMMARY_TIME = time(hour=8)
DAILY_CHECK_IN_TIME = time(hour=21)
ACTIVE_NOTIFICATION_TRIP_STATUSES = {
    TripStatus.READY,
    TripStatus.IN_PROGRESS,
    TripStatus.COMPLETED,
}
PLANNED_TRIP_EVENT_TYPES = {
    ScheduledTripEventType.PACKING_REMINDER,
    ScheduledTripEventType.DAILY_SUMMARY,
    ScheduledTripEventType.DAILY_CHECK_IN,
}
DAILY_CHECK_IN_MESSAGES = (
    "Hey, quite a day! How was your overall experience of the {ordinal} day in {destination}?",
    "You’ve wrapped up your {ordinal} day in {destination}—how was the experience overall?",
    "How did your {ordinal} day in {destination} feel overall? I’d love to hear the highlights.",
    "Your {ordinal} day in {destination} is in the books. How did everything go?",
    "Looking back on your {ordinal} day in {destination}, how was your overall experience?",
    "What a day in {destination}! How would you sum up your {ordinal} day there?",
    "Now that your {ordinal} day in {destination} is winding down, how was it overall?",
)


def get_trip_local_date(trip, at=None):
    at = at or timezone.now()
    timezone_name = _user_timezone(trip.user)
    return at.astimezone(ZoneInfo(timezone_name)).date()


def create_trip_lifecycle_event(trip, event_type, occurred_at=None):
    """Create an idempotent outbox event for a trip status transition."""
    occurred_at = occurred_at or timezone.now()
    timezone_name = _user_timezone(trip.user)
    local_datetime = occurred_at.astimezone(ZoneInfo(timezone_name))

    if event_type == ScheduledTripEventType.TRIP_STARTED:
        delivery_type = ScheduledTripDeliveryType.ALERT
    elif event_type == ScheduledTripEventType.TRIP_COMPLETED:
        delivery_type = ScheduledTripDeliveryType.MESSAGE
    else:
        raise ValueError(f"Unsupported trip lifecycle event: {event_type}")

    event, _ = ScheduledTripNotification.objects.get_or_create(
        idempotency_key=f"trip-lifecycle:{trip.id}:{event_type}",
        defaults={
            "trip": trip,
            "user": trip.user,
            "event_type": event_type,
            "delivery_type": delivery_type,
            "scheduled_for": occurred_at,
            "local_date": local_datetime.date(),
            "local_time": local_datetime.time().replace(tzinfo=None),
            "timezone": timezone_name,
            "metadata": {
                "trip_id": str(trip.id),
                "status": trip.status,
            },
            "created_by": trip.user,
            "updated_by": trip.user,
        },
    )
    return event


def schedule_trip_notifications(trip, user=None, now=None):
    """Create or reconcile all local-time events for a ready trip."""
    user = user or trip.user
    if not trip.start_date or not trip.end_date:
        return []

    timezone_name = _user_timezone(user)
    now = now or timezone.now()
    desired = _build_schedule_specs(trip, timezone_name, now)
    desired_keys = {spec["idempotency_key"] for spec in desired}

    with transaction.atomic():
        type(trip).objects.select_for_update().get(pk=trip.pk)
        trip.scheduled_notifications.filter(
            event_type__in=PLANNED_TRIP_EVENT_TYPES,
            status__in=[
                ScheduledNotificationStatusType.PENDING,
                ScheduledNotificationStatusType.PROCESSING,
            ],
        ).exclude(idempotency_key__in=desired_keys).update(
            status=ScheduledNotificationStatusType.CANCELLED,
            processing_started_at=None,
            updated_by=user,
            updated_at=now,
        )

        existing = {
            event.idempotency_key: event
            for event in ScheduledTripNotification.objects.filter(
                idempotency_key__in=desired_keys
            )
        }
        new_events = []
        resurrected_events = []
        for spec in desired:
            key = spec["idempotency_key"]
            event = existing.get(key)
            if event is None:
                new_events.append(
                    ScheduledTripNotification(
                        **spec,
                        trip=trip,
                        user=user,
                        created_by=user,
                        updated_by=user,
                    )
                )
            elif event.status == ScheduledNotificationStatusType.CANCELLED:
                event.status = ScheduledNotificationStatusType.PENDING
                event.failed_at = None
                event.last_error = ""
                event.updated_by = user
                event.updated_at = now
                resurrected_events.append(event)

        ScheduledTripNotification.objects.bulk_create(new_events, ignore_conflicts=True)
        if resurrected_events:
            ScheduledTripNotification.objects.bulk_update(
                resurrected_events,
                ["status", "failed_at", "last_error", "updated_by", "updated_at"],
            )

        scheduled_events = list(
            ScheduledTripNotification.objects.filter(idempotency_key__in=desired_keys)
            .order_by("scheduled_for")
        )

    return scheduled_events


def _build_schedule_specs(trip, timezone_name, now):
    specs = []
    packing_date = trip.start_date - timedelta(days=1)
    specs.append(
        _schedule_spec(
            trip,
            ScheduledTripEventType.PACKING_REMINDER,
            ScheduledTripDeliveryType.ALERT,
            packing_date,
            PACKING_REMINDER_TIME,
            timezone_name,
            {"trip_id": str(trip.id)},
        )
    )

    trip_day = trip.start_date
    day_number = 1
    while trip_day <= trip.end_date:
        common_metadata = {
            "trip_id": str(trip.id),
            "trip_day": day_number,
            "date": trip_day.isoformat(),
        }
        specs.append(
            _schedule_spec(
                trip,
                ScheduledTripEventType.DAILY_SUMMARY,
                ScheduledTripDeliveryType.ALERT,
                trip_day,
                DAILY_SUMMARY_TIME,
                timezone_name,
                common_metadata,
            )
        )
        specs.append(
            _schedule_spec(
                trip,
                ScheduledTripEventType.DAILY_CHECK_IN,
                ScheduledTripDeliveryType.MESSAGE,
                trip_day,
                DAILY_CHECK_IN_TIME,
                timezone_name,
                common_metadata,
            )
        )
        trip_day += timedelta(days=1)
        day_number += 1

    return [spec for spec in specs if spec["scheduled_for"] > now]


def _schedule_spec(
    trip,
    event_type,
    delivery_type,
    local_date,
    local_time,
    timezone_name,
    metadata,
):
    local_datetime = datetime.combine(
        local_date,
        local_time,
        tzinfo=ZoneInfo(timezone_name),
    )
    scheduled_for = local_datetime.astimezone(datetime_timezone.utc)
    key = ":".join(
        (
            "trip-event",
            str(trip.id),
            event_type,
            local_date.isoformat(),
            local_time.isoformat(),
            timezone_name,
        )
    )
    return {
        "event_type": event_type,
        "delivery_type": delivery_type,
        "scheduled_for": scheduled_for,
        "local_date": local_date,
        "local_time": local_time,
        "timezone": timezone_name,
        "metadata": dict(metadata),
        "idempotency_key": key,
    }


def execute_scheduled_trip_notification(schedule_id):
    """Deliver one claimed event idempotently and return its terminal status."""
    with transaction.atomic():
        schedule = (
            ScheduledTripNotification.objects.select_for_update(of=("self",))
            # Nullable select_related joins become LEFT OUTER JOINs, which
            # PostgreSQL cannot include in FOR UPDATE. Lock the schedule row
            # while eagerly loading only required, non-null foreign keys.
            .select_related("trip", "user")
            .get(pk=schedule_id)
        )
        if schedule.status == ScheduledNotificationStatusType.SENT:
            if (
                schedule.delivery_type == ScheduledTripDeliveryType.MESSAGE
                and schedule.message_id
                and schedule.agent_context_synced_at is None
            ):
                _register_agent_context_sync(schedule)
            return schedule.status

        if schedule.status in {
            ScheduledNotificationStatusType.SKIPPED,
            ScheduledNotificationStatusType.CANCELLED,
        }:
            return schedule.status

        if schedule.trip.status not in ACTIVE_NOTIFICATION_TRIP_STATUSES:
            return _mark_skipped(schedule, "Trip is no longer active.")
        if (
            schedule.trip.status == TripStatus.COMPLETED
            and schedule.event_type != ScheduledTripEventType.TRIP_COMPLETED
        ):
            return _mark_skipped(schedule, "Trip was completed before this event ran.")

        if schedule.delivery_type == ScheduledTripDeliveryType.ALERT:
            if not schedule.user.profile.is_alert_notification_enabled:
                return _mark_skipped(schedule, "User disabled alert notifications.")
            _send_scheduled_alert(schedule)
        elif schedule.delivery_type == ScheduledTripDeliveryType.MESSAGE:
            _send_scheduled_message(schedule)
        else:
            raise ValueError(f"Unsupported scheduled delivery type: {schedule.delivery_type}")

        schedule.status = ScheduledNotificationStatusType.SENT
        schedule.sent_at = timezone.now()
        schedule.failed_at = None
        schedule.processing_started_at = None
        schedule.last_error = ""
        schedule.save(
            update_fields=[
                "status",
                "sent_at",
                "failed_at",
                "processing_started_at",
                "last_error",
                "updated_at",
            ]
        )
        return schedule.status


def _send_scheduled_alert(schedule):
    if schedule.alert_id:
        return schedule.alert

    if schedule.event_type == ScheduledTripEventType.PACKING_REMINDER:
        title, message, metadata = _packing_alert_content(schedule)
    elif schedule.event_type == ScheduledTripEventType.DAILY_SUMMARY:
        title, message, metadata = _daily_summary_alert_content(schedule)
    elif schedule.event_type == ScheduledTripEventType.TRIP_STARTED:
        title, message, metadata = _trip_started_alert_content(schedule)
    else:
        raise ValueError(f"Unsupported alert event: {schedule.event_type}")

    alert = create_trip_notification(
        recipient=schedule.user,
        trip=schedule.trip,
        title=title,
        message=message,
        metadata=metadata,
    )
    schedule.alert = alert
    schedule.save(update_fields=["alert", "updated_at"])
    return alert


def send_trip_message(
    *,
    trip,
    user,
    content,
    metadata=None,
    copy_to_agent_context=True,
    agent_event_id=None,
    scheduled_event_id=None,
):
    """Persist an outbound message, then emit and copy it to ADK after commit."""
    session = get_or_create_conversation_session(trip, user, plan_ready=True)
    message = create_conversation_message(
        session=session,
        sender=AgentMessageSender.AGENT,
        content=content,
        metadata=metadata or {},
        user=user,
    )
    transaction.on_commit(lambda message_id=message.id: emit_trip_message(message_id))
    if copy_to_agent_context:
        transaction.on_commit(
            partial(
                _sync_trip_message_agent_context,
                message.id,
                event_id=agent_event_id,
                schedule_id=scheduled_event_id,
            )
        )
    return message


def _sync_trip_message_agent_context(message_id, *, event_id=None, schedule_id=None):
    """Idempotently finish the ADK side of scheduled-message delivery."""
    from trips.models import TripConversationMessage
    from trips.services.trip_chat import push_trip_message_to_agent_context

    message = TripConversationMessage.objects.select_related(
        "session",
        "session__trip",
    ).get(pk=message_id)
    result = push_trip_message_to_agent_context(message, event_id=event_id)
    if schedule_id:
        synced_at = timezone.now()
        ScheduledTripNotification.objects.filter(
            pk=schedule_id,
            agent_context_synced_at__isnull=True,
        ).update(
            agent_context_synced_at=synced_at,
            last_error="",
            updated_at=synced_at,
        )
    return result


def _register_agent_context_sync(schedule):
    event_id = f"scheduled-trip-event-{schedule.id}"
    transaction.on_commit(
        partial(
            _sync_trip_message_agent_context,
            schedule.message_id,
            event_id=event_id,
            schedule_id=schedule.id,
        )
    )


def emit_trip_message(message_id):
    """Send a persisted trip message over the user's existing socket channel."""
    from trips.api.v1.client.serializers import TripChatMessageSerializer
    from trips.models import TripConversationMessage

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    try:
        message = TripConversationMessage.objects.select_related("session").get(pk=message_id)
        socket_payload = {
            "type": "trip.message.created",
            "conversation_id": str(message.session_id),
            "trip_id": str(message.session.trip_id),
            "message": TripChatMessageSerializer(message).data,
        }
        async_to_sync(channel_layer.group_send)(
            user_dashboard_group(message.session.user_id),
            {
                "type": "trip.message.created",
                "payload": socket_payload,
            },
        )
    except Exception:
        logger.exception("Failed to emit trip message over socket. message_id=%s", message_id)


def _send_scheduled_message(schedule):
    if schedule.message_id:
        return schedule.message

    content = build_scheduled_trip_message(schedule)
    message = send_trip_message(
        trip=schedule.trip,
        user=schedule.user,
        content=content,
        metadata={
            "scheduled_event_id": str(schedule.id),
            "event_type": schedule.event_type,
            "generated_by_agent": False,
        },
        agent_event_id=f"scheduled-trip-event-{schedule.id}",
        scheduled_event_id=schedule.id,
    )
    schedule.message = message
    schedule.save(update_fields=["message", "updated_at"])
    return message


def build_scheduled_trip_message(schedule):
    """Build a varied, destination-aware nightly check-in."""
    if schedule.event_type == ScheduledTripEventType.TRIP_COMPLETED:
        return (
            f"Your {schedule.trip.title} trip is complete. "
            "How was your overall experience?"
        )
    day_number = schedule.metadata.get("trip_day")
    if day_number:
        destination = (
            _destination_name_for_date(schedule.trip, schedule.local_date)
            or "your destination"
        )
        return random.choice(DAILY_CHECK_IN_MESSAGES).format(
            ordinal=_ordinal_day(day_number),
            destination=destination,
        )
    return "How was your day?"


def _ordinal_day(value):
    names = {
        1: "first",
        2: "second",
        3: "third",
        4: "fourth",
        5: "fifth",
        6: "sixth",
        7: "seventh",
        8: "eighth",
        9: "ninth",
        10: "tenth",
        11: "eleventh",
        12: "twelfth",
        13: "thirteenth",
        14: "fourteenth",
        15: "fifteenth",
        16: "sixteenth",
        17: "seventeenth",
        18: "eighteenth",
        19: "nineteenth",
        20: "twentieth",
    }
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    if number in names:
        return names[number]
    suffix = (
        "th"
        if 10 <= number % 100 <= 20
        else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    )
    return f"{number}{suffix}"


def _packing_alert_content(schedule):
    preparation = getattr(schedule.trip, "structured_preparation", None)
    packing_items = []
    required_documents = []
    if preparation:
        packing_items = [
            {
                "item": item.item,
                "quantity": item.quantity,
                "is_packed": item.is_packed,
                "priority": item.priority,
            }
            for item in preparation.packing_items.all()
        ]
        required_documents = [
            {
                "name": document.document_name,
                "required_level": document.required_level,
                "is_packed": document.is_packed,
                "notes": document.additional_note,
            }
            for document in preparation.required_documents.all()
        ]

    message = (
        f"Review {len(packing_items)} packing items and "
        f"{len(required_documents)} travel documents before tomorrow."
    )
    return (
        f"Pack for {schedule.trip.title}",
        message,
        {
            **schedule.metadata,
            "event_type": schedule.event_type,
            "packing_items": packing_items,
            "required_documents": required_documents,
        },
    )


def _trip_started_alert_content(schedule):
    destination_names = list(
        schedule.trip.trip_destinations.order_by("sort_order").values_list(
            "destination__name",
            flat=True,
        )
    )
    destinations_text = ", ".join(destination_names) or "your destination"
    duration = schedule.trip.duration_days or 1
    message = (
        f"{schedule.trip.title} starts today in {destinations_text}. "
        f"Your plan covers {duration} day{'s' if duration != 1 else ''}."
    )
    return (
        "Your trip has started",
        message,
        {
            **schedule.metadata,
            "event_type": schedule.event_type,
            "title": schedule.trip.title,
            "start_date": schedule.trip.start_date.isoformat(),
            "end_date": schedule.trip.end_date.isoformat(),
            "duration_days": duration,
            "destinations": destination_names,
            "travelers_count": schedule.trip.travelers_count,
        },
    )


def _daily_summary_alert_content(schedule):
    itinerary = getattr(schedule.trip, "trip_itinerary", None)
    day_number = schedule.metadata.get("trip_day")
    destination_name = _destination_name_for_date(schedule.trip, schedule.local_date)
    itinerary_day = None
    if itinerary and day_number:
        itinerary_day = itinerary.itinerary_days.filter(day=day_number).first()

    items = []
    if itinerary_day:
        items = [
            {
                "time": item.time.isoformat() if item.time else None,
                "title": item.title,
                "description": item.description,
                "notes": item.notes,
            }
            for item in itinerary_day.day_items.all()
        ]
        message = (
            itinerary_day.summary
            or ", ".join(item["title"] for item in items[:3])
            or "Open your trip plan to review today’s itinerary."
        )
        title = (
            f"Today in {destination_name}"
            if destination_name
            else itinerary_day.title or f"Day {day_number} of {schedule.trip.title}"
        )
    else:
        title = (
            f"Today in {destination_name}"
            if destination_name
            else f"Day {day_number} of {schedule.trip.title}"
        )
        message = "Open your trip plan to review today’s itinerary."

    return (
        title,
        message,
        {
            **schedule.metadata,
            "event_type": schedule.event_type,
            "destination": destination_name,
            "summary": message,
            "items": items,
        },
    )


def _destination_name_for_date(trip, local_date):
    destinations = trip.trip_destinations.select_related("destination")
    dated_destination = destinations.filter(
        arrival_date__lte=local_date,
        departure_date__gte=local_date,
    ).first()
    if dated_destination:
        return dated_destination.destination.name

    primary_destination = destinations.filter(is_primary=True).first()
    if primary_destination:
        return primary_destination.destination.name

    first_destination = destinations.first()
    return first_destination.destination.name if first_destination else None


def _mark_skipped(schedule, reason):
    schedule.status = ScheduledNotificationStatusType.SKIPPED
    schedule.last_error = reason
    schedule.processing_started_at = None
    schedule.save(
        update_fields=["status", "last_error", "processing_started_at", "updated_at"]
    )
    return schedule.status


def _user_timezone(user):
    timezone_name = getattr(getattr(user, "profile", None), "timezone", "UTC") or "UTC"
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        logger.warning("Invalid user timezone; using UTC. user_id=%s", user.id)
        return "UTC"
    return timezone_name
