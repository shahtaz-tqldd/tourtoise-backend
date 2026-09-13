from django.http import QueryDict
from django.test import SimpleTestCase

from destinations.api.v1.admin.serializers import (
    AdminActivitySerializer,
    AdminAttractionSerializer,
)
from destinations.api.v1.client.serializers import (
    ClientActivitySerializer,
    ClientAttractionSerializer,
    ClientDestinationActivitySerializer,
    ClientDestinationAttractionSerializer,
)
from destinations.models import Activity, Attraction, Destination


class BestMonthsSerializerTests(SimpleTestCase):
    def setUp(self):
        self.destination = Destination()

    def test_attraction_accepts_best_months_for_create(self):
        serializer = AdminAttractionSerializer(
            data={
                "name": "Phewa Lake",
                "attraction_type": "natural_site",
                "description": "A scenic freshwater lake.",
                "best_months": [3, 4, 10],
            },
            context={"destination": self.destination},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["best_months"], [3, 4, 10])

        update_serializer = AdminAttractionSerializer(
            Attraction(),
            data={"best_months": [5, 6]},
            partial=True,
            context={"destination": self.destination},
        )
        self.assertTrue(update_serializer.is_valid(), update_serializer.errors)
        self.assertEqual(update_serializer.validated_data["best_months"], [5, 6])

    def test_activity_accepts_best_months_for_create_and_update(self):
        create_serializer = AdminActivitySerializer(
            data={
                "name": "Paragliding",
                "activity_type": "adventure",
                "description": "Tandem paragliding over the valley.",
                "budget_tier": "premium",
                "best_months": [9, 10, 11],
            },
            context={"destination": self.destination},
        )
        self.assertTrue(create_serializer.is_valid(), create_serializer.errors)
        self.assertEqual(create_serializer.validated_data["best_months"], [9, 10, 11])

        update_serializer = AdminActivitySerializer(
            Activity(),
            data={"best_months": [1, 2]},
            partial=True,
            context={"destination": self.destination},
        )
        self.assertTrue(update_serializer.is_valid(), update_serializer.errors)
        self.assertEqual(update_serializer.validated_data["best_months"], [1, 2])

    def test_best_months_accepts_json_array_string_from_form_data(self):
        attraction_data = QueryDict(mutable=True)
        attraction_data.update(
            {
                "name": "Phewa Lake",
                "attraction_type": "natural_site",
                "description": "A scenic freshwater lake.",
                "best_months": "[3, 4, 10]",
            }
        )
        attraction_serializer = AdminAttractionSerializer(
            data=attraction_data,
            context={"destination": self.destination},
        )
        self.assertTrue(attraction_serializer.is_valid(), attraction_serializer.errors)
        self.assertEqual(attraction_serializer.validated_data["best_months"], [3, 4, 10])

        activity_data = QueryDict(mutable=True)
        activity_data["best_months"] = '["9", "10", "11"]'
        activity_serializer = AdminActivitySerializer(
            Activity(),
            data=activity_data,
            partial=True,
            context={"destination": self.destination},
        )
        self.assertTrue(activity_serializer.is_valid(), activity_serializer.errors)
        self.assertEqual(activity_serializer.validated_data["best_months"], [9, 10, 11])

    def test_best_months_rejects_values_outside_calendar_range(self):
        serializer = AdminAttractionSerializer(
            data={
                "name": "Phewa Lake",
                "attraction_type": "natural_site",
                "description": "A scenic freshwater lake.",
                "best_months": [0, 13],
            },
            context={"destination": self.destination},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("best_months", serializer.errors)

    def test_admin_and_client_responses_expose_best_months(self):
        serializer_classes = (
            AdminAttractionSerializer,
            AdminActivitySerializer,
            ClientAttractionSerializer,
            ClientActivitySerializer,
            ClientDestinationAttractionSerializer,
            ClientDestinationActivitySerializer,
        )

        for serializer_class in serializer_classes:
            with self.subTest(serializer=serializer_class.__name__):
                self.assertIn("best_months", serializer_class().fields)

        self.assertNotIn("best_season", AdminActivitySerializer().fields)
