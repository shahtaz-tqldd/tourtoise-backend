from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from analytics.choices import AIUsageType
from analytics.models import AIUsage
from destinations.choices import BudgetTier, DestinationType
from destinations.choices import Status as DestinationStatus
from destinations.models import Destination
from notification.models import Notification, NotificationRead, NotificationType
from trips.models import (
    Trip,
    TripAgentConversationSession,
    TripAgentMessage,
    TripConversationMessage,
    TripConversationSession,
    TripDestination,
    TripItinerary,
    TripItineraryBudget,
    TripItineraryDay,
    TripItineraryDayItem,
    TripPreparation,
    TripPreparationPackingItem,
    TripPlanningSession,
    TripRoutePlanItem,
    TripRequiredDocumentItem,
)


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
                "unread_notification",
                "unread_message",
            ],
        )
        self.assertEqual(trip["unread_notification"], 0)
        self.assertEqual(trip["unread_message"], 0)
        self.assertEqual(
            trip["primary_destination"],
            {
                "name": "Bangkok",
                "country": "Bangkok",
                "region": "",
                "cover_image": "https://example.com/bangkok.jpg",
            },
        )

    def test_trip_list_includes_unread_notification_and_message_counts(self):
        unread_notification = Notification.objects.create(
            recipient=self.user,
            trip=self.bangkok_trip,
            notification_type=NotificationType.TRIP,
            title="Pack your documents",
        )
        read_notification = Notification.objects.create(
            recipient=self.user,
            trip=self.bangkok_trip,
            notification_type=NotificationType.TRIP,
            title="Already read",
        )
        NotificationRead.objects.create(
            notification=read_notification,
            user=self.user,
            created_by=self.user,
        )
        session = TripConversationSession.objects.create(
            trip=self.bangkok_trip,
            user=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        TripConversationMessage.objects.create(
            session=session,
            sender="agent",
            content="How was your day?",
            created_by=self.user,
            updated_by=self.user,
        )
        TripConversationMessage.objects.create(
            session=session,
            sender="agent",
            content="A read message",
            read_at=timezone.now(),
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(self.url, {"destination_slug": self.bangkok.slug})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        trip = response.data["data"][0]
        self.assertEqual(trip["unread_notification"], 1)
        self.assertEqual(trip["unread_message"], 1)
        self.assertEqual(unread_notification.trip_id, self.bangkok_trip.id)

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

    def test_create_rejects_overlapping_trip_date_range_for_same_user(self):
        Trip.objects.create(
            user=self.user,
            title="Existing Trip",
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 15),
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.post(
            self.url,
            {
                "title": "Overlapping Trip",
                "start_date": "2026-06-14",
                "end_date": "2026-06-18",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            str(response.data["non_field_errors"][0]),
            "Between this date range there are another trip exists.",
        )

    def test_create_allows_overlapping_trip_date_range_for_different_user(self):
        other_user = User.objects.create_user(email="other@example.com", password="testpass123")
        Trip.objects.create(
            user=other_user,
            title="Other User Trip",
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 15),
            created_by=other_user,
            updated_by=other_user,
        )

        response = self.client.post(
            self.url,
            {
                "title": "Same Dates",
                "start_date": "2026-06-14",
                "end_date": "2026-06-18",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

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


class TripUpdateApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.client.force_authenticate(user=self.user)
        self.trip = Trip.objects.create(
            user=self.user,
            title="Original Trip",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            created_by=self.user,
            updated_by=self.user,
        )
        self.url = f"/api/v1/trips/{self.trip.id}/update/"

    def test_update_rejects_overlapping_trip_date_range_for_same_user(self):
        Trip.objects.create(
            user=self.user,
            title="Existing Trip",
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 15),
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.patch(
            self.url,
            {
                "start_date": "2026-06-15",
                "end_date": "2026-06-18",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            str(response.data["non_field_errors"][0]),
            "Between this date range there are another trip exists.",
        )

    def test_update_allows_current_trip_existing_date_range(self):
        response = self.client.patch(
            self.url,
            {
                "title": "Renamed Trip",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.title, "Renamed Trip")


class TripSharingApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.other_user = User.objects.create_user(email="other@example.com", password="testpass123")
        self.client.force_authenticate(user=self.user)
        self.trip = Trip.objects.create(
            user=self.user,
            title="Shareable Trip",
            created_by=self.user,
            updated_by=self.user,
        )

    def test_creates_share_link_and_makes_trip_public(self):
        response = self.client.post(f"/api/v1/trips/{self.trip.id}/share-token/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.visibility, "public")
        self.assertEqual(response.data["data"]["share_token"], str(self.trip.share_token))
        self.assertIn(f"/api/v1/trips/public/{self.trip.share_token}/detail/", response.data["data"]["share_url"])

    def test_share_token_endpoint_keeps_existing_token_by_default(self):
        original_token = self.trip.share_token

        response = self.client.post(f"/api/v1/trips/{self.trip.id}/share-token/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.share_token, original_token)

    def test_share_token_endpoint_can_regenerate_token(self):
        original_token = self.trip.share_token

        response = self.client.post(
            f"/api/v1/trips/{self.trip.id}/share-token/",
            {"regenerate": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.trip.refresh_from_db()
        self.assertNotEqual(self.trip.share_token, original_token)
        self.assertEqual(response.data["data"]["share_token"], str(self.trip.share_token))

    def test_public_detail_is_available_only_for_public_trips(self):
        private_response = self.client.get(f"/api/v1/trips/public/{self.trip.share_token}/detail/")
        self.assertEqual(private_response.status_code, status.HTTP_404_NOT_FOUND)

        self.trip.visibility = "public"
        self.trip.save(update_fields=["visibility"])
        public_response = self.client.get(f"/api/v1/trips/public/{self.trip.share_token}/detail/")

        self.assertEqual(public_response.status_code, status.HTTP_200_OK)
        self.assertEqual(public_response.data["data"]["id"], str(self.trip.id))

    def test_visibility_endpoint_can_make_trip_private(self):
        self.trip.visibility = "public"
        self.trip.save(update_fields=["visibility"])

        response = self.client.patch(
            f"/api/v1/trips/{self.trip.id}/visibility/",
            {"visibility": "private"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.visibility, "private")
        self.assertIsNone(response.data["data"]["share_url"])

    def test_visibility_endpoint_rejects_other_user_trip(self):
        other_trip = Trip.objects.create(
            user=self.other_user,
            title="Other Trip",
            created_by=self.other_user,
            updated_by=self.other_user,
        )

        response = self.client.patch(
            f"/api/v1/trips/{other_trip.id}/visibility/",
            {"visibility": "public"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


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

    def test_let_agent_decide_uses_profile_preferences(self):
        profile = self.user.profile
        profile.travel_interests = ["History", "Nature"]
        profile.dietary_preferences = ["Vegetarian", "Halal"]
        profile.travel_pace = "moderate"
        profile.mobility_constraints = ["Avoid stairs"]
        profile.save(
            update_fields=[
                "travel_interests",
                "dietary_preferences",
                "travel_pace",
                "mobility_constraints",
            ]
        )
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
                    "travel_pace": "fast",
                    "interest_tags": ["Nightlife"],
                    "dietary_needs": ["Gluten-free"],
                    "mobility_constraints": ["No mobility constraints"],
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
        self.assertEqual(preferences["interest_tags"], ["History", "Nature"])
        self.assertEqual(preferences["dietary_needs"], ["Vegetarian", "Halal"])
        self.assertEqual(preferences["mobility_constraints"], ["Avoid stairs"])
        run_agent.assert_called_once()
        self.assertEqual(run_agent.call_args.kwargs["preferences"], preferences)

        profile = self.user.profile
        profile.refresh_from_db()
        self.assertEqual(profile.travel_interests, ["History", "Nature"])
        self.assertEqual(profile.dietary_preferences, ["Vegetarian", "Halal"])
        self.assertEqual(profile.travel_pace, "moderate")
        self.assertEqual(profile.mobility_constraints, ["Avoid stairs"])
        session = TripAgentConversationSession.objects.get(trip=self.trip)
        self.assertEqual(session.qna_count, 1)
        self.assertEqual(TripAgentMessage.objects.filter(session=session).count(), 2)
        self.user.credit.refresh_from_db()
        self.assertEqual(self.user.credit.balance, 99)

    def test_manual_preferences_keep_agent_active_and_update_user_profile(self):
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
                    "let_agent_decide": False,
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
        self.assertTrue(self.trip.agent_active)
        preferences = self.trip.preferences["agent_customization"]
        self.assertEqual(
            preferences,
            {
                "travel_pace": "moderate",
                "interest_tags": ["History", "Nature"],
                "dietary_needs": ["Vegetarian", "Gluten-free", "Halal"],
                "mobility_constraints": [
                    "No mobility constraints",
                    "Avoid stairs",
                    "Wheelchair access",
                ],
            },
        )
        self.assertEqual(
            response.data["data"]["preferences"]["dietary_needs"],
            ["Vegetarian", "Gluten-free", "Halal"],
        )
        run_agent.assert_called_once()
        self.assertEqual(run_agent.call_args.kwargs["preferences"], preferences)
        session = TripAgentConversationSession.objects.get(trip=self.trip)
        self.assertEqual(session.qna_count, 1)
        self.assertEqual(TripAgentMessage.objects.filter(session=session).count(), 2)
        self.user.credit.refresh_from_db()
        self.assertEqual(self.user.credit.balance, 99)

        profile = self.user.profile
        profile.refresh_from_db()
        self.assertEqual(profile.travel_interests, ["History", "Nature"])
        self.assertEqual(profile.dietary_preferences, ["Vegetarian", "Gluten-free", "Halal"])
        self.assertEqual(profile.travel_pace, "moderate")
        self.assertEqual(
            profile.mobility_constraints,
            ["No mobility constraints", "Avoid stairs", "Wheelchair access"],
        )

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


class TripChatApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.other_user = User.objects.create_user(email="other@example.com", password="testpass123")
        self.client.force_authenticate(user=self.user)
        self.trip = Trip.objects.create(
            user=self.user,
            title="Chat Trip",
            is_qna_complete=True,
            is_recommendation_complete=True,
            is_itinerary_design_complete=True,
            is_trip_preparation_complete=True,
            created_by=self.user,
            updated_by=self.user,
        )
        self.url = f"/api/v1/trips/{self.trip.id}/chat/"

    @patch("trips.api.v1.client.views.trip_chat.run_guide_agent_for_session")
    def test_creates_trip_chat_message_with_guide_agent_reply(self, run_guide_agent):
        run_guide_agent.return_value = {
            "session_id": "guide-session-1",
            "response": "Your first planned stop is the old town.",
            "cost": 0.0001,
            "total_tokens": 42,
        }

        response = self.client.post(
            f"{self.url}create-message/",
            {"message": "What is my first stop?"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["meta"]["credit_spent"], 1)
        self.assertEqual(response.data["data"]["user_message"]["sender"], "user")
        self.assertEqual(response.data["data"]["agent_message"]["sender"], "agent")
        self.assertEqual(
            response.data["data"]["agent_message"]["content"],
            "Your first planned stop is the old town.",
        )
        self.assertEqual(response.data["data"]["agent_message"]["metadata"]["total_tokens"], 42)
        self.assertTrue(response.data["data"]["agent_message"]["is_read"])

        session = TripConversationSession.objects.get(trip=self.trip)
        self.assertEqual(str(response.data["data"]["session"]["id"]), str(session.id))
        self.assertEqual(session.trip, self.trip)
        self.assertEqual(session.user, self.user)
        self.assertEqual(TripConversationMessage.objects.filter(session=session).count(), 2)
        self.assertFalse(TripAgentConversationSession.objects.filter(trip=self.trip).exists())
        self.user.credit.refresh_from_db()
        self.assertEqual(self.user.credit.balance, 99)
        usage = AIUsage.objects.get(user=self.user, trip=self.trip)
        self.assertEqual(usage.usage_type, AIUsageType.TRIP_CHAT)
        self.assertEqual(usage.cost, Decimal("0.00010000"))
        self.assertEqual(usage.tokens, 42)
        self.assertEqual(usage.metadata, {})
        run_guide_agent.assert_called_once_with(
            session=session,
            user_query="What is my first stop?",
        )

    @patch("trips.api.v1.client.views.trip_chat.run_guide_agent_for_session")
    def test_trip_chat_rejects_message_without_credit(self, run_guide_agent):
        self.user.credit.balance = 0
        self.user.credit.save(update_fields=["balance"])

        response = self.client.post(
            f"{self.url}create-message/",
            {"message": "What is my first stop?"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(response.data["message"], "Insufficient credits.")
        self.assertFalse(TripConversationMessage.objects.filter(session__trip=self.trip).exists())
        self.assertFalse(AIUsage.objects.filter(user=self.user, trip=self.trip).exists())
        run_guide_agent.assert_not_called()

    def test_lists_trip_chat_messages_for_session(self):
        session = TripConversationSession.objects.create(
            trip=self.trip,
            user=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        TripConversationMessage.objects.create(
            session=session,
            sender="user",
            content="Hello",
            created_by=self.user,
            updated_by=self.user,
        )
        TripConversationMessage.objects.create(
            session=session,
            sender="agent",
            content="How was your day?",
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(f"{self.url}messages/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 2)
        self.assertEqual(response.data["data"][0]["content"], "Hello")
        self.assertEqual(response.data["meta"]["unread_count"], 1)
        self.assertFalse(response.data["data"][1]["is_read"])

    def test_marks_all_trip_chat_agent_messages_as_read(self):
        session = TripConversationSession.objects.create(
            trip=self.trip,
            user=self.user,
            created_by=self.user,
            updated_by=self.user,
        )
        message = TripConversationMessage.objects.create(
            session=session,
            sender="agent",
            content="How was your day?",
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.patch(f"{self.url}read-all/", {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["conversation_id"], str(session.id))
        self.assertEqual(response.data["data"]["marked_read_count"], 1)
        self.assertEqual(response.data["data"]["unread_count"], 0)
        message.refresh_from_db()
        self.assertIsNotNone(message.read_at)

    def test_rejects_other_user_trip_chat_session(self):
        other_trip = Trip.objects.create(
            user=self.other_user,
            title="Other Trip",
            created_by=self.other_user,
            updated_by=self.other_user,
        )
        session = TripConversationSession.objects.create(
            trip=other_trip,
            user=self.other_user,
            created_by=self.other_user,
            updated_by=self.other_user,
        )

        response = self.client.get(f"/api/v1/trips/{other_trip.id}/chat/messages/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_rejects_chat_until_all_planning_steps_are_complete(self):
        self.trip.is_trip_preparation_complete = False
        self.trip.save(update_fields=["is_trip_preparation_complete"])

        response = self.client.post(
            f"{self.url}create-message/",
            {"message": "Can we chat yet?"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(TripConversationMessage.objects.filter(session__trip=self.trip).exists())

    def test_trip_has_one_planning_and_one_conversation_session(self):
        planning_session = TripPlanningSession.objects.create(trip=self.trip, user=self.user)
        conversation_session = TripConversationSession.objects.create(trip=self.trip, user=self.user)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TripPlanningSession.objects.create(trip=self.trip, user=self.user)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TripConversationSession.objects.create(trip=self.trip, user=self.user)

        self.assertEqual(planning_session.trip, conversation_session.trip)

    def test_planning_steps_keep_separate_agent_sessions_under_one_parent(self):
        from trips.choices import PlanningStep
        from trips.services.services import get_or_create_agent_conversation_session

        preference_session = get_or_create_agent_conversation_session(
            self.trip, self.user, step=PlanningStep.PREFERENCE
        )
        recommendation_session = get_or_create_agent_conversation_session(
            self.trip, self.user, step=PlanningStep.RECOMMENDATION
        )
        repeated_preference_session = get_or_create_agent_conversation_session(
            self.trip, self.user, step=PlanningStep.PREFERENCE
        )

        self.assertEqual(preference_session.id, repeated_preference_session.id)
        self.assertNotEqual(preference_session.id, recommendation_session.id)
        self.assertEqual(
            preference_session.planning_session_id,
            recommendation_session.planning_session_id,
        )
        self.assertEqual(
            TripPlanningSession.objects.filter(trip=self.trip).count(),
            1,
        )


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
        self.user.credit.refresh_from_db()
        self.assertEqual(self.user.credit.balance, 99)

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


class TripRequiredDocumentApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.client.force_authenticate(user=self.user)
        self.trip = Trip.objects.create(
            user=self.user,
            title="Document Trip",
            created_by=self.user,
            updated_by=self.user,
        )
        self.url = f"/api/v1/trips/{self.trip.id}/documents/"

    @patch("trips.api.v1.client.serializers.upload_file")
    def test_creates_required_document_with_image_upload(self, upload_file_mock):
        upload_file_mock.return_value = {
            "url": "https://res.cloudinary.com/demo/image/upload/trip-documents/passport.jpg",
            "public_id": "trip-documents/passport",
        }
        upload = SimpleUploadedFile("passport.jpg", b"image-bytes", content_type="image/jpeg")

        response = self.client.post(
            self.url,
            {
                "document_name": "Passport",
                "required_level": "required",
                "document": upload,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["document_name"], "Passport")
        self.assertEqual(response.data["data"]["document_file_name"], "passport.jpg")
        self.assertEqual(
            response.data["data"]["document"],
            {
                "file_name": "passport.jpg",
                "url": "https://res.cloudinary.com/demo/image/upload/trip-documents/passport.jpg",
                "public_id": "trip-documents/passport",
            },
        )
        self.assertEqual(
            response.data["data"]["document_url"],
            "https://res.cloudinary.com/demo/image/upload/trip-documents/passport.jpg",
        )
        self.assertEqual(response.data["data"]["document_url_public_id"], "trip-documents/passport")
        upload_file_mock.assert_called_once()

    @patch("trips.api.v1.client.serializers.upload_file")
    def test_updates_required_document_with_pdf_upload(self, upload_file_mock):
        preparation = TripPreparation.objects.create(trip=self.trip, created_by=self.user, updated_by=self.user)
        document = TripRequiredDocumentItem.objects.create(
            preparation=preparation,
            document_name="Visa",
            sort_order=1,
            created_by=self.user,
            updated_by=self.user,
        )
        upload_file_mock.return_value = {
            "url": "https://res.cloudinary.com/demo/raw/upload/trip-documents/visa.pdf",
            "public_id": "trip-documents/visa",
        }
        upload = SimpleUploadedFile("visa.pdf", b"%PDF-1.4", content_type="application/pdf")

        response = self.client.patch(
            f"{self.url}{document.id}/",
            {
                "document": upload,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"]["document_url"],
            "https://res.cloudinary.com/demo/raw/upload/trip-documents/visa.pdf",
        )
        self.assertEqual(response.data["data"]["document_file_name"], "visa.pdf")
        self.assertEqual(
            response.data["data"]["document"],
            {
                "file_name": "visa.pdf",
                "url": "https://res.cloudinary.com/demo/raw/upload/trip-documents/visa.pdf",
                "public_id": "trip-documents/visa",
            },
        )
        document.refresh_from_db()
        self.assertEqual(document.document_file_name, "visa.pdf")
        self.assertEqual(document.document_url_public_id, "trip-documents/visa")

    def test_lists_required_document_file_name(self):
        preparation = TripPreparation.objects.create(trip=self.trip, created_by=self.user, updated_by=self.user)
        TripRequiredDocumentItem.objects.create(
            preparation=preparation,
            document_name="Ticket",
            document_file_name="ticket.pdf",
            document_url="https://res.cloudinary.com/demo/raw/upload/trip-documents/ticket.pdf",
            document_url_public_id="trip-documents/ticket",
            sort_order=1,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"][0]["document_file_name"], "ticket.pdf")
        self.assertEqual(
            response.data["data"][0]["document"],
            {
                "file_name": "ticket.pdf",
                "url": "https://res.cloudinary.com/demo/raw/upload/trip-documents/ticket.pdf",
                "public_id": "trip-documents/ticket",
            },
        )

    def test_updates_required_document_file_name(self):
        preparation = TripPreparation.objects.create(trip=self.trip, created_by=self.user, updated_by=self.user)
        document = TripRequiredDocumentItem.objects.create(
            preparation=preparation,
            document_name="Ticket",
            document_file_name="old-ticket.pdf",
            document_url="https://res.cloudinary.com/demo/raw/upload/trip-documents/ticket.pdf",
            document_url_public_id="trip-documents/ticket",
            sort_order=1,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.patch(
            f"{self.url}{document.id}/",
            {"document_file_name": "updated-ticket.pdf"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["document_file_name"], "updated-ticket.pdf")
        self.assertEqual(response.data["data"]["document"]["file_name"], "updated-ticket.pdf")
        document.refresh_from_db()
        self.assertEqual(document.document_file_name, "updated-ticket.pdf")

    @patch("trips.api.v1.client.views.preparation_items.delete_file")
    def test_deletes_required_document_file_from_item_and_storage(self, delete_file_mock):
        preparation = TripPreparation.objects.create(trip=self.trip, created_by=self.user, updated_by=self.user)
        document = TripRequiredDocumentItem.objects.create(
            preparation=preparation,
            document_name="Visa",
            document_file_name="visa.pdf",
            document_url="https://res.cloudinary.com/demo/raw/upload/trip-documents/visa.pdf",
            document_url_public_id="trip-documents/visa",
            sort_order=1,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.delete(f"{self.url}{document.id}/file/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["data"]["document"])
        self.assertEqual(response.data["data"]["document_file_name"], "")
        self.assertIsNone(response.data["data"]["document_url"])
        self.assertEqual(response.data["data"]["document_url_public_id"], "")
        delete_file_mock.assert_called_once_with(
            public_id="trip-documents/visa",
            file_url="https://res.cloudinary.com/demo/raw/upload/trip-documents/visa.pdf",
        )
        document.refresh_from_db()
        self.assertEqual(document.document_file_name, "")
        self.assertIsNone(document.document_url)
        self.assertEqual(document.document_url_public_id, "")

    def test_rejects_unsupported_document_upload_type(self):
        upload = SimpleUploadedFile("itinerary.txt", b"text", content_type="text/plain")

        response = self.client.post(
            self.url,
            {
                "document_name": "Itinerary",
                "document": upload,
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TripDetailApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.client.force_authenticate(user=self.user)
        self.trip = Trip.objects.create(
            user=self.user,
            title="Trip Detail",
            origin_city="Dhaka",
            origin_country="Bangladesh",
            start_location_address="Gulshan Avenue",
            start_location_latitude=23.7925,
            start_location_longitude=90.4078,
            budget_currency="BDT",
            created_by=self.user,
            updated_by=self.user,
        )
        self.url = f"/api/v1/trips/{self.trip.id}/detail/"

    def test_includes_itinerary_budget_and_preparation_stats(self):
        itinerary = TripItinerary.objects.create(
            trip=self.trip,
            title="Dhaka Weekend",
            summary="A compact city itinerary.",
        )
        TripItineraryBudget.objects.create(
            itinerary=itinerary,
            transport="100.00",
            food="75.50",
            total_estimated_budget="225.50",
            budget_note="Includes daily meals and transport.",
            metadata={"currency": "USD"},
        )
        preparation = TripPreparation.objects.create(
            trip=self.trip,
            title="Prep",
        )
        TripPreparationPackingItem.objects.create(
            preparation=preparation,
            item="Passport",
            is_packed=True,
            sort_order=1,
        )
        TripPreparationPackingItem.objects.create(
            preparation=preparation,
            item="Rain jacket",
            is_packed=False,
            sort_order=2,
        )
        TripRequiredDocumentItem.objects.create(
            preparation=preparation,
            document_name="Passport scan",
            document_url="https://example.com/passport.pdf",
            sort_order=1,
        )
        TripRequiredDocumentItem.objects.create(
            preparation=preparation,
            document_name="Visa",
            sort_order=2,
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data["data"]
        self.assertEqual(data["planning_title"], "Dhaka Weekend")
        self.assertEqual(data["planning_description"], "A compact city itinerary.")
        self.assertEqual(
            data["start_location"],
            {
                "address": "Gulshan Avenue",
                "city": "Dhaka",
                "country": "Bangladesh",
                "longitude": 90.4078,
                "latitude": 23.7925,
            },
        )
        self.assertNotIn("origin_city", data)
        self.assertNotIn("origin_country", data)
        self.assertNotIn("start_location_address", data)
        self.assertNotIn("start_location_latitude", data)
        self.assertNotIn("start_location_longitude", data)
        self.assertNotIn("budget_currency", data)
        self.assertEqual(data["budget"]["budget_currency"], "BDT")
        self.assertEqual(data["budget"]["transport"], "100.00")
        self.assertEqual(data["budget"]["food"], "75.50")
        self.assertEqual(data["budget"]["total_estimated_budget"], "225.50")
        self.assertEqual(data["budget"]["budget_note"], "Includes daily meals and transport.")
        self.assertEqual(
            data["preparation_stats"]["packing_items"],
            {
                "total_count": 2,
                "is_packed_count": 1,
            },
        )
        self.assertEqual(
            data["preparation_stats"]["documents"],
            {
                "total_count": 2,
                "uploaded_count": 1,
            },
        )


class TripRoutePlanListApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.other_user = User.objects.create_user(email="other@example.com", password="testpass123")
        self.client.force_authenticate(user=self.user)
        self.trip = Trip.objects.create(
            user=self.user,
            title="Route Plan Trip",
            created_by=self.user,
            updated_by=self.user,
        )
        self.url = f"/api/v1/trips/{self.trip.id}/route-plans/"

    def test_lists_route_plan_items_for_trip(self):
        itinerary = TripItinerary.objects.create(
            trip=self.trip,
            title="Dhaka Weekend",
            summary="Short city plan",
        )
        TripRoutePlanItem.objects.create(
            itinerary=itinerary,
            date=date(2026, 7, 20),
            from_point="Hotel",
            to_point="Museum",
            start_time="09:30",
            transport_mode="car",
            estimated_cost="12.50",
            estimated_duration=timedelta(minutes=35),
            notes="Morning transfer",
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Trip route plan fetched successfully.")
        self.assertEqual(len(response.data["data"]), 1)
        route_plan = response.data["data"][0]
        self.assertEqual(route_plan["date"], "2026-07-20")
        self.assertEqual(route_plan["from_point"], "Hotel")
        self.assertEqual(route_plan["to_point"], "Museum")
        self.assertEqual(route_plan["start_time"], "09:30:00")
        self.assertEqual(route_plan["transport_mode"], "car")
        self.assertEqual(route_plan["estimated_cost"], "12.50")
        self.assertEqual(route_plan["estimated_duration"], "0:35:00")
        self.assertEqual(route_plan["notes"], "Morning transfer")

    def test_returns_empty_list_when_trip_has_no_itinerary(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"], [])

    def test_rejects_route_plan_for_another_users_trip(self):
        other_trip = Trip.objects.create(
            user=self.other_user,
            title="Other Route Trip",
            created_by=self.other_user,
            updated_by=self.other_user,
        )

        response = self.client.get(f"/api/v1/trips/{other_trip.id}/route-plans/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TripPlanApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(email="traveler@example.com", password="testpass123")
        self.other_user = User.objects.create_user(email="other@example.com", password="testpass123")
        self.client.force_authenticate(user=self.user)
        self.trip = Trip.objects.create(
            user=self.user,
            title="Plan Trip",
            created_by=self.user,
            updated_by=self.user,
        )
        self.itinerary = TripItinerary.objects.create(
            trip=self.trip,
            title="Dhaka Weekend",
            summary="Short city plan",
        )
        self.day = TripItineraryDay.objects.create(
            itinerary=self.itinerary,
            day=1,
            date=date(2026, 7, 20),
            title="Arrival",
            summary="Start the trip",
        )
        self.item = TripItineraryDayItem.objects.create(
            trip_itinerary_day=self.day,
            time="09:00",
            title="Breakfast",
            item_type="food",
            description="Local breakfast",
            notes="Try nearby cafe",
            estimated_cost="8.50",
        )

    def test_lists_daywise_plan_for_trip(self):
        response = self.client.get(f"/api/v1/trips/{self.trip.id}/plan/daywise/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Trip day-wise plan fetched successfully.")
        self.assertEqual(len(response.data["data"]), 1)
        day = response.data["data"][0]
        self.assertEqual(day["day"], 1)
        self.assertEqual(day["date"], "2026-07-20")
        self.assertEqual(day["title"], "Arrival")
        self.assertEqual(len(day["items"]), 1)
        self.assertEqual(day["items"][0]["title"], "Breakfast")

    def test_returns_empty_daywise_plan_when_trip_has_no_itinerary(self):
        trip = Trip.objects.create(
            user=self.user,
            title="Empty Plan Trip",
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(f"/api/v1/trips/{trip.id}/plan/daywise/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"], [])

    def test_updates_trip_plan_item(self):
        response = self.client.patch(
            f"/api/v1/trips/{self.trip.id}/plan/items/{self.item.id}/",
            {
                "title": "Updated breakfast",
                "time": "10:15:00",
                "notes": "Reserved a table",
                "estimated_cost": "12.75",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Itinerary item updated successfully.")
        self.assertEqual(response.data["data"]["title"], "Updated breakfast")
        self.assertEqual(response.data["data"]["time"], "10:15:00")
        self.assertEqual(response.data["data"]["notes"], "Reserved a table")
        self.assertEqual(response.data["data"]["estimated_cost"], "12.75")
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, "Updated breakfast")

    def test_rejects_plan_item_update_for_another_users_trip(self):
        other_trip = Trip.objects.create(
            user=self.other_user,
            title="Other Plan Trip",
            created_by=self.other_user,
            updated_by=self.other_user,
        )
        other_itinerary = TripItinerary.objects.create(trip=other_trip)
        other_day = TripItineraryDay.objects.create(
            itinerary=other_itinerary,
            day=1,
            title="Other day",
        )
        other_item = TripItineraryDayItem.objects.create(
            trip_itinerary_day=other_day,
            title="Other item",
            item_type="activity",
        )

        response = self.client.patch(
            f"/api/v1/trips/{other_trip.id}/plan/items/{other_item.id}/",
            {"title": "Should not update"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
