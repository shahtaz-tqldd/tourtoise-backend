from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from chat.choices import ChatMessageSender
from chat.models import ChatMessage, ChatSession
from journals.models import Journal
from trips.choices import AgentMessageSender, TripStatus
from trips.models import Trip, TripConversationMessage, TripConversationSession


class AnalyticsAdminApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser("admin@example.com", "testpass123")
        self.user = User.objects.create_user("user@example.com", "testpass123")
        self.client.force_authenticate(self.admin)

    def _set_created_at(self, instance, value):
        instance.__class__.objects.filter(pk=instance.pk).update(created_at=value)

    def test_overview_returns_totals_and_combined_message_stats(self):
        now = timezone.now()
        old_user = User.objects.create_user("old@example.com", "testpass123")
        self._set_created_at(old_user, now - timedelta(days=45))

        completed_trip = Trip.objects.create(user=self.user, title="Done", status=TripStatus.COMPLETED)
        old_trip = Trip.objects.create(user=self.user, title="Old")
        self._set_created_at(old_trip, now - timedelta(days=45))
        Journal.objects.create(author=self.user, content="Current journal")

        chat_session = ChatSession.objects.create(user=self.user)
        ChatMessage.objects.create(
            session=chat_session,
            sender=ChatMessageSender.USER,
            content="Chat message",
        )
        trip_session = TripConversationSession.objects.create(trip=completed_trip, user=self.user)
        TripConversationMessage.objects.create(
            session=trip_session,
            sender=AgentMessageSender.AGENT,
            content="Trip message",
        )

        response = self.client.get("/api/v1/admin/analytics/overview/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["users"]["total"], 3)
        self.assertEqual(response.data["data"]["trips"]["total_planned"], 2)
        self.assertEqual(response.data["data"]["trips"]["completed"], 1)
        self.assertEqual(response.data["data"]["journals"]["total"], 1)
        self.assertEqual(response.data["data"]["ai_messages"]["total"], 2)
        self.assertEqual(response.data["data"]["ai_messages"]["this_month"], 2)

    def test_user_growth_returns_twelve_months_including_empty_months(self):
        response = self.client.get("/api/v1/admin/analytics/user-growth/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["granularity"], "month")
        self.assertEqual(len(response.data["data"]["points"]), 12)
        self.assertEqual(
            response.data["data"]["points"][-1]["period"],
            timezone.localdate().strftime("%Y-%m"),
        )

    def test_user_growth_month_filter_returns_every_day(self):
        response = self.client.get("/api/v1/admin/analytics/user-growth/", {"month": "2024-02"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["granularity"], "day")
        self.assertEqual(len(response.data["data"]["points"]), 29)
        self.assertEqual(response.data["data"]["points"][0]["period"], "2024-02-01")

    def test_analytics_requires_superadmin(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/api/v1/admin/analytics/overview/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
