from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from destinations.choices import BudgetTier, DestinationType
from destinations.choices import Status as DestinationStatus
from destinations.models import Destination
from trips.models import Trip, TripAgentConversationSession, TripAgentMessage, TripDestination


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

    def test_trip_duration_days_are_computed_from_dates(self):
        trip = Trip.objects.create(
            user=self.user,
            title="Thailand Long Weekend",
            start_date=date(2026, 12, 10),
            end_date=date(2026, 12, 14),
            created_by=self.user,
            updated_by=self.user,
        )

        self.assertEqual(trip.duration_days, 5)
        self.assertEqual(trip.nights, 4)

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
            status=DestinationStatus.PUBLISHED,
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
            agent_context={
                "saved_plan_snapshot": {
                    "destinations": [
                        {"slug": "amalfi-coast-ita", "name": "Amalfi Coast"},
                    ],
                },
            },
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(self.url, {"destination_slug": "amalfi-coast-ita"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["meta"]["count"], 1)
        self.assertEqual(response.data["data"][0]["id"], str(plan_trip.id))

    def test_trip_list_uses_summary_payload_shape(self):
        response = self.client.get(self.url, {"destination_slug": self.bangkok.slug})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        trip = response.data["data"][0]
        self.assertEqual(
            list(trip.keys()),
            [
                "id",
                "title",
                "status",
                "visibility",
                "start_date",
                "end_date",
                "nights",
                "destinations_count",
                "duration_days",
                "travelers_count",
                "traveler_type",
                "primary_destination",
                "share_url",
            ],
        )
        self.assertEqual(
            trip["primary_destination"],
            {
                "name": "Bangkok",
                "country": "Bangkok",
                "region": "",
                "cover_image": "https://example.com/bangkok.jpg",
            },
        )

    def test_trip_list_orders_nearest_upcoming_start_date_first(self):
        today = timezone.localdate()
        later_trip = self._create_trip(
            "Later Trip",
            self.user,
            self.paris,
            start_date=today + timedelta(days=10),
            end_date=today + timedelta(days=13),
        )
        sooner_trip = self._create_trip(
            "Sooner Trip",
            self.user,
            self.bangkok,
            start_date=today + timedelta(days=3),
            end_date=today + timedelta(days=5),
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"][0]["id"], str(sooner_trip.id))
        self.assertEqual(response.data["data"][1]["id"], str(later_trip.id))

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
            status=DestinationStatus.PUBLISHED,
            created_by=self.user,
            updated_by=self.user,
        )

    def _create_trip(self, title, user, destination, start_date=None, end_date=None):
        trip = Trip.objects.create(
            user=user,
            title=title,
            start_date=start_date,
            end_date=end_date,
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


class TripCreateApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.client.force_authenticate(user=self.user)
        self.url = "/api/v1/trips/create/"
        self.amalfi = self._create_destination("Amalfi Coast", "ITA")
        self.paris = self._create_destination("Paris", "FRA")

    def test_creates_trip_with_destination_slugs_and_request_metadata(self):
        payload = {
            "title": "My new trip plan",
            "destination_slugs": [self.amalfi.slug, self.paris.slug],
            "start_date": "2026-06-05",
            "days": 5,
            "traveler_type": "solo",
            "travelers_count": 1,
            "accommodation_preference": "luxury",
            "start_location_address": "নিরিবিলি হাউজিং, West Dhanmondi, Dhaka, Bangladesh",
            "start_location_latitude": 23.750221,
            "start_location_longitude": 90.3654296,
            "total_budget": 198,
            "budget_currency": "USD",
        }

        response = self.client.post(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        trip = Trip.objects.get(id=response.data["data"]["id"])
        self.assertEqual(trip.title, payload["title"])
        self.assertEqual(trip.start_date, date(2026, 6, 5))
        self.assertEqual(trip.end_date, date(2026, 6, 9))
        self.assertEqual(trip.duration_days, 5)
        self.assertEqual(trip.nights, 4)
        self.assertEqual(trip.current_step, 2)
        self.assertEqual(response.data["data"]["current_step"], 2)
        self.assertEqual(trip.traveler_type, "solo")
        self.assertEqual(trip.accommodation_preference, "luxury")
        self.assertEqual(trip.start_location_address, payload["start_location_address"])
        self.assertEqual(trip.start_location_latitude, payload["start_location_latitude"])
        self.assertEqual(trip.start_location_longitude, payload["start_location_longitude"])

        trip_destinations = list(trip.trip_destinations.order_by("sort_order"))
        self.assertEqual([row.destination.slug for row in trip_destinations], [self.amalfi.slug, self.paris.slug])
        self.assertTrue(trip_destinations[0].is_primary)
        self.assertFalse(trip_destinations[1].is_primary)
        self.assertEqual(response.data["data"]["trip_destinations"][0]["destination"]["slug"], self.amalfi.slug)

    def test_create_rejects_unavailable_destination_slug(self):
        response = self.client.post(
            self.url,
            {
                "title": "Missing destination",
                "destination_slugs": ["unknown-destination"],
                "start_date": "2026-06-05",
                "days": 5,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("destination_slugs", response.data)

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
            cover_image=f"https://example.com/{name.lower().replace(' ', '-')}.jpg",
            budget_tier=BudgetTier.MID,
            local_languages=["English"],
            currency="Dollar",
            currency_code="USD",
            status=DestinationStatus.PUBLISHED,
            created_by=self.user,
            updated_by=self.user,
        )


class TripAgentActiveApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.other_user = User.objects.create_user(email="other@example.com", password="testpass123")
        self.client.force_authenticate(user=self.user)
        self.url = "/api/v1/trips/agent-active/"
        self.trip = Trip.objects.create(
            user=self.user,
            title="Agent Trip",
            current_step=2,
            created_by=self.user,
            updated_by=self.user,
        )

    def test_updates_trip_agent_preferences_and_user_profile(self):
        with patch("trips.api.v1.client.views.run_plan_agent_for_session") as run_agent:
            run_agent.return_value = {
                "session_id": "adk-session-1",
                "response": {
                    "question": "What would make this trip feel successful?",
                    "is_qna_complete": False,
                    "context": None,
                },
                "cost": None,
                "total_tokens": None,
                "intention": None,
            }
            response = self.client.post(
                self.url,
                {
                    "trip_id": str(self.trip.id),
                    "current_step": 2,
                    "let_agent_decide": True,
                    "travel_pace": "moderate",
                    "interest_tags": ["History", "Nature"],
                    "dietary_needs": ["Vegetarian", "Gluten-free"],
                    "dietary_other": "Halal",
                    "mobility_constraints": ["No mobility constraints", "Avoid stairs"],
                    "mobility_other": "Wheelchair access",
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["data"]["agent_active"])
        self.assertEqual(response.data["data"]["agent_message"], "What would make this trip feel successful?")
        self.assertFalse(response.data["data"]["is_qna_complete"])
        self.assertIsNotNone(response.data["data"]["session_id"])

        self.trip.refresh_from_db()
        preferences = self.trip.preferences["agent_customization"]
        self.assertEqual(self.trip.current_step, 2)
        self.assertTrue(self.trip.agent_active)
        self.assertEqual(preferences["travel_pace"], "moderate")
        self.assertEqual(preferences["dietary_needs"], ["Vegetarian", "Gluten-free", "Halal"])
        self.assertEqual(
            preferences["mobility_constraints"],
            ["No mobility constraints", "Avoid stairs", "Wheelchair access"],
        )

        profile = self.user.profile
        profile.refresh_from_db()
        self.assertEqual(profile.travel_interests, ["History", "Nature"])
        self.assertEqual(profile.dietary_preferences, ["Vegetarian", "Gluten-free", "Halal"])
        self.assertEqual(profile.travel_pace, "moderate")
        self.assertEqual(
            profile.mobility_constraints,
            ["No mobility constraints", "Avoid stairs", "Wheelchair access"],
        )
        session = TripAgentConversationSession.objects.get(trip=self.trip)
        self.assertEqual(session.qna_count, 1)
        self.assertEqual(TripAgentMessage.objects.filter(session=session).count(), 2)

    def test_can_disable_agent_decision(self):
        response = self.client.post(
            self.url,
            {
                "trip_id": str(self.trip.id),
                "let_agent_decide": False,
                "travel_pace": "moderate",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"],
            {
                "agent_active": False,
                "agent_active_failed_message": "",
                "agent_message": "Agent is not active because let_agent_decide is false.",
            },
        )
        self.assertFalse(TripAgentConversationSession.objects.filter(trip=self.trip).exists())

    def test_rejects_trip_from_another_user(self):
        other_trip = Trip.objects.create(
            user=self.other_user,
            title="Other Trip",
            created_by=self.other_user,
            updated_by=self.other_user,
        )

        response = self.client.post(
            self.url,
            {
                "trip_id": str(other_trip.id),
                "current_step": 2,
                "let_agent_decide": True,
                "travel_pace": "moderate",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TripAgentCreateMessageApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.other_user = User.objects.create_user(email="other@example.com", password="testpass123")
        self.client.force_authenticate(user=self.user)
        self.url = "/api/v1/trips/agent/create-message/"
        self.trip = Trip.objects.create(
            user=self.user,
            title="Agent Message Trip",
            current_step=2,
            created_by=self.user,
            updated_by=self.user,
        )

    def test_creates_agent_message_and_advances_step(self):
        session = TripAgentConversationSession.objects.create(
            trip=self.trip,
            user=self.user,
            current_step=2,
            external_session_id="adk-session-1",
            created_by=self.user,
            updated_by=self.user,
        )
        self.trip.preferences = {"agent_customization": {"travel_pace": "moderate"}}
        self.trip.save(update_fields=["preferences"])

        with patch("trips.api.v1.client.views.run_plan_agent_for_session") as run_agent:
            run_agent.return_value = {
                "session_id": "adk-session-1",
                "response": {
                    "question": None,
                    "is_qna_complete": True,
                    "context": "Moderate-paced traveler who prefers lots of smaller local experiences.",
                },
                "cost": None,
                "total_tokens": None,
                "intention": None,
            }
            response = self.client.post(
                self.url,
                {
                    "trip_id": str(self.trip.id),
                    "session_id": str(session.id),
                    "current_step": 2,
                    "message": "lots of smaller experience",
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["data"]["is_step_complete"])
        self.assertTrue(response.data["data"]["is_qna_complete"])
        self.assertEqual(response.data["data"]["current_step"], 3)

        self.trip.refresh_from_db()
        self.assertEqual(self.trip.current_step, 3)
        self.assertEqual(
            self.trip.agent_context["preference_qna"]["context"],
            "Moderate-paced traveler who prefers lots of smaller local experiences.",
        )
        session.refresh_from_db()
        self.assertFalse(session.is_active)
        self.assertEqual(TripAgentMessage.objects.filter(session=session).count(), 2)

    def test_rejects_trip_from_another_user(self):
        other_trip = Trip.objects.create(
            user=self.other_user,
            title="Other Message Trip",
            created_by=self.other_user,
            updated_by=self.other_user,
        )

        response = self.client.post(
            self.url,
            {
                "trip_id": str(other_trip.id),
                "current_step": 2,
                "message": "lots of smaller experience",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
