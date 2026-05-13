from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from destinations.choices import BudgetTier, DestinationType
from destinations.models import Destination
from trips.models import Trip, TripDestination


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
