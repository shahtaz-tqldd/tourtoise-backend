from datetime import date, datetime, timezone as datetime_timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from notification.models import Notification
from trips.choices import (
    ScheduledNotificationStatusType,
    ScheduledTripDeliveryType,
    ScheduledTripEventType,
    TripStatus,
)
from trips.models import (
    ScheduledTripNotification,
    Trip,
    TripConversationMessage,
    TripConversationSession,
)
from trips.services.notifications import (
    execute_scheduled_trip_notification,
    schedule_trip_notifications,
)
from trips.tasks import _update_trip_lifecycle_statuses, dispatch_due_trip_notifications


User = get_user_model()


class ScheduledTripNotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="scheduled-traveler@example.com",
            password="testpass123",
        )
        self.user.profile.timezone = "Asia/Dhaka"
        self.user.profile.save(update_fields=["timezone"])
        self.trip = Trip.objects.create(
            user=self.user,
            title="Bangladesh Tour",
            status=TripStatus.READY,
            start_date=date(2026, 12, 10),
            end_date=date(2026, 12, 11),
            created_by=self.user,
            updated_by=self.user,
        )
        self.now = datetime(2026, 12, 1, tzinfo=datetime_timezone.utc)

    def test_builds_local_time_schedule_and_is_idempotent(self):
        schedule_trip_notifications(self.trip, now=self.now)
        schedule_trip_notifications(self.trip, now=self.now)

        events = ScheduledTripNotification.objects.filter(trip=self.trip)
        self.assertEqual(events.count(), 5)

        packing = events.get(event_type=ScheduledTripEventType.PACKING_REMINDER)
        self.assertEqual(packing.delivery_type, ScheduledTripDeliveryType.ALERT)
        self.assertEqual(packing.local_date, date(2026, 12, 9))
        self.assertEqual(packing.scheduled_for.hour, 11)  # 17:00 Asia/Dhaka

        first_summary = events.get(
            event_type=ScheduledTripEventType.DAILY_SUMMARY,
            local_date=date(2026, 12, 10),
        )
        self.assertEqual(first_summary.scheduled_for.hour, 2)  # 08:00 Asia/Dhaka

        first_check_in = events.get(
            event_type=ScheduledTripEventType.DAILY_CHECK_IN,
            local_date=date(2026, 12, 10),
        )
        self.assertEqual(first_check_in.delivery_type, ScheduledTripDeliveryType.MESSAGE)
        self.assertEqual(first_check_in.scheduled_for.hour, 15)  # 21:00 Asia/Dhaka

    def test_alert_delivery_is_linked_and_idempotent(self):
        schedule_trip_notifications(self.trip, now=self.now)
        schedule = ScheduledTripNotification.objects.get(
            event_type=ScheduledTripEventType.PACKING_REMINDER
        )
        schedule.status = ScheduledNotificationStatusType.PROCESSING
        schedule.save(update_fields=["status"])

        execute_scheduled_trip_notification(schedule.id)
        execute_scheduled_trip_notification(schedule.id)

        schedule.refresh_from_db()
        self.assertEqual(schedule.status, ScheduledNotificationStatusType.SENT)
        self.assertIsNotNone(schedule.alert_id)
        self.assertEqual(Notification.objects.filter(trip=self.trip).count(), 1)

    @patch("trips.services.notifications.get_channel_layer")
    def test_nightly_message_delivery_is_linked_and_idempotent(self, get_channel_layer):
        channel_layer = SimpleNamespace(group_send=AsyncMock())
        get_channel_layer.return_value = channel_layer
        schedule_trip_notifications(self.trip, now=self.now)
        schedule = ScheduledTripNotification.objects.filter(
            event_type=ScheduledTripEventType.DAILY_CHECK_IN
        ).first()
        schedule.status = ScheduledNotificationStatusType.PROCESSING
        schedule.save(update_fields=["status"])

        with (
            patch(
                "trips.services.notifications._destination_name_for_date",
                return_value="Dhaka",
            ),
            patch(
                "trips.services.notifications.random.choice",
                side_effect=lambda messages: messages[0],
            ),
            patch(
                "trips.services.trip_chat.push_trip_message_to_agent_context",
                return_value={"session_id": "guide-session-1"},
            ) as push_agent_context,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                execute_scheduled_trip_notification(schedule.id)
            with self.captureOnCommitCallbacks(execute=True):
                execute_scheduled_trip_notification(schedule.id)

        schedule.refresh_from_db()
        self.assertEqual(schedule.status, ScheduledNotificationStatusType.SENT)
        self.assertIsNotNone(schedule.message_id)
        self.assertEqual(TripConversationMessage.objects.filter(session__trip=self.trip).count(), 1)
        self.assertIn("first day in Dhaka", schedule.message.content)
        self.assertIsNotNone(schedule.agent_context_synced_at)
        push_agent_context.assert_called_once_with(
            schedule.message,
            event_id=f"scheduled-trip-event-{schedule.id}",
        )
        channel_layer.group_send.assert_awaited_once()
        socket_event = channel_layer.group_send.await_args.args[1]["payload"]
        self.assertEqual(socket_event["type"], "trip.message.created")
        self.assertEqual(socket_event["conversation_id"], str(schedule.message.session_id))
        self.assertEqual(socket_event["message"]["id"], str(schedule.message_id))

    def test_disabled_alerts_are_skipped_but_messages_remain_enabled(self):
        self.user.profile.is_alert_notification_enabled = False
        self.user.profile.save(update_fields=["is_alert_notification_enabled"])
        schedule_trip_notifications(self.trip, now=self.now)
        alert_schedule = ScheduledTripNotification.objects.get(
            event_type=ScheduledTripEventType.PACKING_REMINDER
        )

        result = execute_scheduled_trip_notification(alert_schedule.id)

        self.assertEqual(result, ScheduledNotificationStatusType.SKIPPED)
        self.assertFalse(Notification.objects.filter(trip=self.trip).exists())

    def test_daily_check_in_is_skipped_after_trip_completion(self):
        schedule_trip_notifications(self.trip, now=self.now)
        schedule = ScheduledTripNotification.objects.filter(
            event_type=ScheduledTripEventType.DAILY_CHECK_IN
        ).first()
        self.trip.status = TripStatus.COMPLETED
        self.trip.save(update_fields=["status"])

        result = execute_scheduled_trip_notification(schedule.id)

        schedule.refresh_from_db()
        self.assertEqual(result, ScheduledNotificationStatusType.SKIPPED)
        self.assertIsNone(schedule.message_id)
        self.assertIn("completed", schedule.last_error)

    def test_trip_lifecycle_uses_user_timezone_and_creates_outbox_events(self):
        conversation = TripConversationSession.objects.create(
            trip=self.trip,
            user=self.user,
            is_active=True,
            created_by=self.user,
            updated_by=self.user,
        )
        # 18:01 UTC on Dec 9 is 00:01 on Dec 10 in Asia/Dhaka.
        start_result = _update_trip_lifecycle_statuses(
            datetime(2026, 12, 9, 18, 1, tzinfo=datetime_timezone.utc)
        )

        self.trip.refresh_from_db()
        self.assertEqual(start_result, {"started": 1, "completed": 0})
        self.assertEqual(self.trip.status, TripStatus.IN_PROGRESS)
        started_event = ScheduledTripNotification.objects.get(
            trip=self.trip,
            event_type=ScheduledTripEventType.TRIP_STARTED,
        )
        execute_scheduled_trip_notification(started_event.id)
        started_event.refresh_from_db()
        self.assertEqual(started_event.status, ScheduledNotificationStatusType.SENT)
        self.assertEqual(started_event.alert.title, "Your trip has started")

        # Completion happens after the full Dec 11 local trip day has ended.
        completion_result = _update_trip_lifecycle_statuses(
            datetime(2026, 12, 11, 18, 1, tzinfo=datetime_timezone.utc)
        )

        self.trip.refresh_from_db()
        conversation.refresh_from_db()
        self.assertEqual(completion_result, {"started": 0, "completed": 1})
        self.assertEqual(self.trip.status, TripStatus.COMPLETED)
        self.assertFalse(conversation.is_active)
        completed_event = ScheduledTripNotification.objects.get(
            trip=self.trip,
            event_type=ScheduledTripEventType.TRIP_COMPLETED,
        )
        execute_scheduled_trip_notification(completed_event.id)
        completed_event.refresh_from_db()
        self.assertEqual(completed_event.status, ScheduledNotificationStatusType.SENT)
        self.assertIn("overall experience", completed_event.message.content)

    def test_trip_does_not_start_before_local_start_date(self):
        result = _update_trip_lifecycle_statuses(
            datetime(2026, 12, 9, 17, 59, tzinfo=datetime_timezone.utc)
        )

        self.trip.refresh_from_db()
        self.assertEqual(result, {"started": 0, "completed": 0})
        self.assertEqual(self.trip.status, TripStatus.READY)
        self.assertFalse(
            ScheduledTripNotification.objects.filter(
                trip=self.trip,
                event_type=ScheduledTripEventType.TRIP_STARTED,
            ).exists()
        )

    @patch("trips.tasks.execute_trip_notification.apply_async")
    def test_dispatcher_claims_due_events_before_enqueuing(self, apply_async):
        schedule_trip_notifications(self.trip, now=self.now)
        schedule = ScheduledTripNotification.objects.first()
        schedule.scheduled_for = datetime(2020, 1, 1, tzinfo=datetime_timezone.utc)
        schedule.save(update_fields=["scheduled_for"])

        dispatched = dispatch_due_trip_notifications()

        schedule.refresh_from_db()
        self.assertEqual(dispatched, 1)
        self.assertEqual(schedule.status, ScheduledNotificationStatusType.PROCESSING)
        self.assertEqual(schedule.attempt_count, 1)
        apply_async.assert_called_once()
