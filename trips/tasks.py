import logging
import random
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from accounts.services.user_profile import record_completed_trip_stats
from trips.choices import (
    ScheduledNotificationStatusType,
    ScheduledTripEventType,
    TripStatus,
)
from trips.models import ScheduledTripNotification, Trip
from trips.services.notifications import (
    create_trip_lifecycle_event,
    execute_scheduled_trip_notification,
    get_trip_local_date,
    schedule_trip_notifications,
)
from trips.services.trip_chat import close_conversation_session


logger = logging.getLogger(__name__)

DISPATCH_BATCH_SIZE = 500
MAX_BATCHES_PER_RUN = 10
STALE_PROCESSING_AFTER = timedelta(minutes=15)
MAX_DISPATCH_JITTER_SECONDS = 60
LIFECYCLE_BATCH_SIZE = 5000


@shared_task
def reschedule_user_trip_notifications(user_id):
    """Rebuild future schedules after the user changes timezone."""
    from trips.choices import TripStatus
    from trips.models import Trip

    trip_ids = list(
        Trip.objects.filter(
            user_id=user_id,
            status__in=[TripStatus.READY, TripStatus.IN_PROGRESS],
            start_date__isnull=False,
            end_date__isnull=False,
            end_date__gte=timezone.localdate(),
        ).values_list("id", flat=True)
    )
    for trip in Trip.objects.filter(id__in=trip_ids).select_related("user", "user__profile"):
        schedule_trip_notifications(trip, trip.user)
    return len(trip_ids)


@shared_task
def update_trip_lifecycle_statuses():
    """Advance ready/in-progress trips according to each user's local date."""
    return _update_trip_lifecycle_statuses(timezone.now())


def _update_trip_lifecycle_statuses(now):
    utc_date = now.date()
    ready_trip_ids = list(
        Trip.objects.filter(
            status=TripStatus.READY,
            start_date__isnull=False,
            start_date__lte=utc_date + timedelta(days=1),
        )
        .order_by("start_date", "id")
        .values_list("id", flat=True)[:LIFECYCLE_BATCH_SIZE]
    )
    in_progress_trip_ids = list(
        Trip.objects.filter(
            status=TripStatus.IN_PROGRESS,
            end_date__isnull=False,
            end_date__lte=utc_date + timedelta(days=1),
        )
        .order_by("end_date", "id")
        .values_list("id", flat=True)[:LIFECYCLE_BATCH_SIZE]
    )

    started = _transition_trip_batch(
        ready_trip_ids,
        expected_status=TripStatus.READY,
        target_status=TripStatus.IN_PROGRESS,
        event_type=ScheduledTripEventType.TRIP_STARTED,
        now=now,
    )
    completed = _transition_trip_batch(
        in_progress_trip_ids,
        expected_status=TripStatus.IN_PROGRESS,
        target_status=TripStatus.COMPLETED,
        event_type=ScheduledTripEventType.TRIP_COMPLETED,
        now=now,
    )
    logger.info("Trip lifecycle updated. started=%s completed=%s", started, completed)
    return {"started": started, "completed": completed}


def _transition_trip_batch(trip_ids, **transition_kwargs):
    transitioned = 0
    for trip_id in trip_ids:
        try:
            transitioned += _transition_trip_if_due(
                trip_id,
                **transition_kwargs,
            )
        except Exception:
            logger.exception(
                "Trip lifecycle transition failed; it will be retried next run. "
                "trip_id=%s target_status=%s",
                trip_id,
                transition_kwargs["target_status"],
            )
    return transitioned


def _transition_trip_if_due(
    trip_id,
    *,
    expected_status,
    target_status,
    event_type,
    now,
):
    with transaction.atomic():
        trip = (
            Trip.objects.select_for_update(of=("self",))
            .select_related("user", "user__profile")
            .get(pk=trip_id)
        )
        if trip.status != expected_status:
            return 0

        local_date = get_trip_local_date(trip, now)
        if target_status == TripStatus.IN_PROGRESS:
            is_due = trip.start_date and local_date >= trip.start_date
        else:
            # Keep the trip active through its complete final local day.
            is_due = trip.end_date and local_date > trip.end_date
        if not is_due:
            return 0

        trip.status = target_status
        trip.updated_by = trip.user
        trip.save(update_fields=["status", "updated_by", "updated_at"])
        create_trip_lifecycle_event(trip, event_type, occurred_at=now)
        if target_status == TripStatus.COMPLETED:
            close_conversation_session(trip, user=trip.user, at=now)
            # Keep status, lifecycle outbox, and profile stats atomic. A
            # failure rolls the trip back to IN_PROGRESS for the next run.
            record_completed_trip_stats(trip)
    return 1


@shared_task
def dispatch_due_trip_notifications():
    """Claim due rows in bounded batches and fan them out across workers."""
    now = timezone.now()
    _recover_stale_events(now)
    dispatched = 0

    for _ in range(MAX_BATCHES_PER_RUN):
        event_ids = _claim_due_events(now, DISPATCH_BATCH_SIZE)
        if not event_ids:
            break

        dispatched += len(event_ids)
        for event_id in event_ids:
            execute_trip_notification.apply_async(
                args=[str(event_id)],
                countdown=random.uniform(0, MAX_DISPATCH_JITTER_SECONDS),
            )

        if len(event_ids) < DISPATCH_BATCH_SIZE:
            break

    logger.info("Dispatched %s scheduled trip events.", dispatched)
    return dispatched


def _claim_due_events(now, batch_size):
    with transaction.atomic():
        events = list(
            ScheduledTripNotification.objects.select_for_update(skip_locked=True)
            .filter(
                status=ScheduledNotificationStatusType.PENDING,
                scheduled_for__lte=now,
            )
            .order_by("scheduled_for", "id")[:batch_size]
        )
        if not events:
            return []

        event_ids = [event.id for event in events]
        ScheduledTripNotification.objects.filter(id__in=event_ids).update(
            status=ScheduledNotificationStatusType.PROCESSING,
            processing_started_at=now,
            attempt_count=F("attempt_count") + 1,
            last_error="",
        )
        return event_ids


def _recover_stale_events(now):
    cutoff = now - STALE_PROCESSING_AFTER
    return ScheduledTripNotification.objects.filter(
        status=ScheduledNotificationStatusType.PROCESSING,
        processing_started_at__lt=cutoff,
    ).update(
        status=ScheduledNotificationStatusType.PENDING,
        processing_started_at=None,
        last_error="Recovered after a worker lease expired.",
    )


@shared_task(bind=True, max_retries=3)
def execute_trip_notification(self, schedule_id):
    try:
        return execute_scheduled_trip_notification(schedule_id)
    except ScheduledTripNotification.DoesNotExist:
        logger.warning("Scheduled trip event no longer exists. schedule_id=%s", schedule_id)
        return ScheduledNotificationStatusType.CANCELLED
    except Exception as exc:
        logger.exception(
            "Scheduled trip event execution failed. schedule_id=%s retry=%s",
            schedule_id,
            self.request.retries,
        )
        if self.request.retries >= self.max_retries:
            _mark_event_failed(schedule_id, exc)
            return ScheduledNotificationStatusType.FAILED

        ScheduledTripNotification.objects.filter(pk=schedule_id).update(
            attempt_count=F("attempt_count") + 1,
            last_error=str(exc)[:2000],
        )
        retry_delay = min(15 * 60, 60 * (2**self.request.retries))
        retry_delay += random.randint(0, 30)
        raise self.retry(exc=exc, countdown=retry_delay)


def _mark_event_failed(schedule_id, exc):
    ScheduledTripNotification.objects.filter(pk=schedule_id).update(
        status=ScheduledNotificationStatusType.FAILED,
        failed_at=timezone.now(),
        processing_started_at=None,
        last_error=str(exc)[:2000],
    )
