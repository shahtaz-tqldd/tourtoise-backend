from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from destinations.models import Destination
from trips.choices import AgentMessageSender, PlanningStep
from trips.models import (
    Trip,
    TripAgentConversationSession,
    TripAgentMessage,
    TripConversationMessage,
    TripConversationSession,
    TripDestination,
    TripPlanningSession,
)


User = get_user_model()


class AdminTripListApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="testpass123",
        )
        self.traveler = User.objects.create_user(
            email="traveler@example.com",
            password="testpass123",
        )
        self.traveler.name = "Test Traveler"
        self.traveler.save(update_fields=["name"])
        self.traveler.profile.avatar_url = "https://example.com/traveler.png"
        self.traveler.profile.save(update_fields=["avatar_url"])
        self.client.force_authenticate(user=self.admin)

    def create_trip(self, title):
        return Trip.objects.create(
            user=self.traveler,
            title=title,
            created_by=self.traveler,
            updated_by=self.traveler,
        )

    def add_primary_destination(self, trip):
        destination = Destination.objects.create(
            name="Dhaka",
            tagline="Capital city",
            description="A busy river city.",
            cover_image="https://example.com/dhaka.jpg",
            country="Bangladesh",
            country_code="BGD",
            region="South Asia",
            destination_type="city",
            budget_tier="budget",
            currency="Bangladeshi Taka",
            currency_code="BDT",
            created_by=self.traveler,
            updated_by=self.traveler,
        )
        TripDestination.objects.create(
            trip=trip,
            destination=destination,
            is_primary=True,
            created_by=self.traveler,
            updated_by=self.traveler,
        )
        return destination

    def test_includes_separate_planning_and_trip_chat_usage(self):
        trip = self.create_trip("Usage Trip")
        self.add_primary_destination(trip)
        planning_session = TripPlanningSession.objects.create(
            trip=trip,
            user=self.traveler,
            created_by=self.traveler,
            updated_by=self.traveler,
        )
        step_session = TripAgentConversationSession.objects.create(
            planning_session=planning_session,
            trip=trip,
            user=self.traveler,
            step=PlanningStep.PREFERENCE,
            created_by=self.traveler,
            updated_by=self.traveler,
        )
        TripAgentMessage.objects.create(
            session=step_session,
            sender=AgentMessageSender.AGENT,
            content="First planning response",
            metadata={"cost": 0.0001, "total_tokens": 40},
        )
        TripAgentMessage.objects.create(
            session=step_session,
            sender=AgentMessageSender.SYSTEM,
            content="Second planning response",
            metadata={"cost": 0.0002, "total_tokens": 60},
        )
        TripAgentMessage.objects.create(
            session=step_session,
            sender=AgentMessageSender.USER,
            content="Planning question",
        )

        conversation = TripConversationSession.objects.create(
            trip=trip,
            user=self.traveler,
            created_by=self.traveler,
            updated_by=self.traveler,
        )
        TripConversationMessage.objects.create(
            session=conversation,
            sender=AgentMessageSender.USER,
            content="Chat question",
        )
        TripConversationMessage.objects.create(
            session=conversation,
            sender=AgentMessageSender.AGENT,
            content="First chat response",
            metadata={"cost": 0.0004, "total_tokens": 75},
        )
        TripConversationMessage.objects.create(
            session=conversation,
            sender=AgentMessageSender.AGENT,
            content="Second chat response",
            metadata={"cost": 0.0006, "total_tokens": 125},
        )

        response = self.client.get("/api/v1/admin/trips/list/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = response.data["data"][0]
        self.assertEqual(
            row["user"],
            {
                "name": "Test Traveler",
                "email": "traveler@example.com",
                "avatar_url": "https://example.com/traveler.png",
            },
        )
        self.assertEqual(
            row["primary_destination"],
            {
                "name": "Dhaka",
                "country": "Bangladesh",
                "region": "South Asia",
            },
        )
        self.assertAlmostEqual(row["planning"]["cost"], 0.0003)
        self.assertEqual(row["planning"]["tokens"], 100)
        self.assertAlmostEqual(row["trip_chat"]["cost"], 0.001)
        self.assertEqual(row["trip_chat"]["tokens"], 200)
        self.assertEqual(row["trip_chat"]["total_message"], 3)

    def test_returns_zero_usage_for_trip_without_messages(self):
        self.create_trip("Empty Trip")

        response = self.client.get("/api/v1/admin/trips/list/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = response.data["data"][0]
        self.assertEqual(row["planning"], {"cost": 0.0, "tokens": 0})
        self.assertEqual(
            row["trip_chat"],
            {"total_message": 0, "cost": 0.0, "tokens": 0},
        )
        self.assertIsNone(row["primary_destination"])

    def test_filters_trips_by_destination_name_country_and_region(self):
        trip = self.create_trip("Dhaka Trip")
        self.add_primary_destination(trip)
        self.create_trip("Destination-less Trip")

        for query_param in (
            "destination_name=dhak",
            "country=bangla",
            "region=south+asia",
        ):
            with self.subTest(query_param=query_param):
                response = self.client.get(f"/api/v1/admin/trips/list/?{query_param}")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                self.assertEqual(response.data["meta"]["count"], 1)
                self.assertEqual(response.data["data"][0]["id"], str(trip.id))
