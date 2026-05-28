from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from destinations.choices import BudgetTier, DestinationType
from destinations.models import Destination
from trips.choices import PlanningSource
from trips.models import Trip, TripDestination, TripPlanVersion


User = get_user_model()


class TripModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.destination = Destination.objects.create(
            name="Bangkok",
            country="Thailand",
            country_code="THA",
            destination_type=DestinationType.CITY,
            latitude=13.7563,
            longitude=100.5018,
            tagline="Urban energy",
            overview="A vibrant city destination.",
            cover_image="https://example.com/bangkok.jpg",
            budget_tier=BudgetTier.MID,
            local_languages=["Thai", "English"],
            currency="Thai Baht",
            currency_code="THB",
            created_by=self.user,
            updated_by=self.user,
        )

    def test_trip_share_token_and_nights_are_computed(self):
        trip = Trip.objects.create(
            user=self.user,
            title="Thailand Winter Escape",
            start_date=date(2026, 12, 10),
            end_date=date(2026, 12, 15),
            created_by=self.user,
            updated_by=self.user,
        )

        self.assertIsNotNone(trip.share_token)
        self.assertEqual(trip.nights, 5)

    def test_trip_destination_stay_nights_are_computed(self):
        trip = Trip.objects.create(
            user=self.user,
            title="Bangkok Stop",
            created_by=self.user,
            updated_by=self.user,
        )

        stop = TripDestination.objects.create(
            trip=trip,
            destination=self.destination,
            sort_order=1,
            arrival_date=date(2026, 12, 10),
            departure_date=date(2026, 12, 13),
            is_primary=True,
            created_by=self.user,
            updated_by=self.user,
        )

        self.assertEqual(stop.stay_nights, 3)

    def test_trip_can_only_have_one_primary_destination(self):
        trip = Trip.objects.create(
            user=self.user,
            title="Thai Journey",
            created_by=self.user,
            updated_by=self.user,
        )

        TripDestination.objects.create(
            trip=trip,
            destination=self.destination,
            sort_order=1,
            is_primary=True,
            created_by=self.user,
            updated_by=self.user,
        )

        second_destination = Destination.objects.create(
            name="Chiang Mai",
            country="Thailand",
            country_code="THA",
            destination_type=DestinationType.CITY,
            latitude=18.7883,
            longitude=98.9853,
            tagline="Mountain culture",
            overview="Northern Thailand destination.",
            cover_image="https://example.com/chiang-mai.jpg",
            budget_tier=BudgetTier.MID,
            local_languages=["Thai", "English"],
            currency="Thai Baht",
            currency_code="THB",
            created_by=self.user,
            updated_by=self.user,
        )

        with self.assertRaises(IntegrityError):
            TripDestination.objects.create(
                trip=trip,
                destination=second_destination,
                sort_order=2,
                is_primary=True,
                created_by=self.user,
                updated_by=self.user,
            )


class TripListApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.other_user = User.objects.create_user(email="other@example.com", password="testpass123")
        self.client.force_authenticate(user=self.user)
        self.url = "/api/v1/trips/list/"

        self.bangkok = self._create_destination("Bangkok", "THA")
        self.paris = self._create_destination("Paris", "FRA")

        self.bangkok_trip = self._create_trip("Bangkok Stop", self.user, self.bangkok)
        self.paris_trip = self._create_trip("Paris Weekend", self.user, self.paris)
        self._create_trip("Other User Bangkok", self.other_user, self.bangkok)

    def test_filters_authenticated_user_trips_by_destination_slug(self):
        response = self.client.get(self.url, {"destination_slug": self.bangkok.slug})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["meta"]["count"], 1)
        self.assertEqual(response.data["data"][0]["id"], str(self.bangkok_trip.id))

    def test_filters_trips_by_destination_slug_in_saved_plan_snapshot(self):
        plan_trip = Trip.objects.create(
            user=self.user,
            title="Amalfi Plan",
            created_by=self.user,
            updated_by=self.user,
        )
        TripPlanVersion.objects.create(
            trip=plan_trip,
            version=1,
            source=PlanningSource.AGENT,
            snapshot={"destinations": [{"slug": "amalfi-coast-ita"}]},
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(self.url, {"destination_slug": "amalfi-coast-ita"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["meta"]["count"], 1)
        self.assertEqual(response.data["data"][0]["id"], str(plan_trip.id))

    def _create_destination(self, name, country_code):
        return Destination.objects.create(
            name=name,
            country=name,
            country_code=country_code,
            destination_type=DestinationType.CITY,
            latitude=13.7563,
            longitude=100.5018,
            tagline=f"{name} trip",
            overview=f"{name} destination.",
            cover_image=f"https://example.com/{name.lower()}.jpg",
            budget_tier=BudgetTier.MID,
            local_languages=["English"],
            currency="Dollar",
            currency_code="USD",
            created_by=self.user,
            updated_by=self.user,
        )

    def _create_trip(self, title, user, destination):
        trip = Trip.objects.create(
            user=user,
            title=title,
            created_by=user,
            updated_by=user,
        )
        TripDestination.objects.create(
            trip=trip,
            destination=destination,
            sort_order=1,
            is_primary=True,
            created_by=user,
            updated_by=user,
        )
        return trip
