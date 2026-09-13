from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from analytics.choices import AIUsageType
from analytics.services.ai_usage import record_ai_usage
from destinations.models import Destination
from trips.models import Trip, TripDestination


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
        record_ai_usage(
            user=self.traveler,
            trip=trip,
            usage_type=AIUsageType.TRIP_PLANNING,
            cost=0.0001,
            tokens=40,
        )
        record_ai_usage(
            user=self.traveler,
            trip=trip,
            usage_type=AIUsageType.TRIP_PLANNING,
            cost=0.0002,
            tokens=60,
        )
        record_ai_usage(
            user=self.traveler,
            trip=trip,
            usage_type=AIUsageType.TRIP_CHAT,
            cost=0.0004,
            tokens=75,
        )
        record_ai_usage(
            user=self.traveler,
            trip=trip,
            usage_type=AIUsageType.TRIP_CHAT,
            cost=0.0006,
            tokens=125,
        )
        record_ai_usage(
            user=self.traveler,
            trip=trip,
            usage_type=AIUsageType.CHAT,
            cost=1,
            tokens=10_000,
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
        self.assertEqual(row["trip_chat"]["total_message"], 2)

    def test_returns_zero_usage_for_trip_without_ai_usage(self):
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
