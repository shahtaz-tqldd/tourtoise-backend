from unittest.mock import patch

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from destinations.models import Activity, Attraction, Cuisine, Destination
from vector_store.models import VectorDocument


class AdminVectorApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            email="vector-admin@example.com",
            password="testpass123",
        )
        self.regular_user = User.objects.create_user(
            email="vector-user@example.com",
            password="testpass123",
        )
        self.client.force_authenticate(user=self.admin)

        self.destination = self._create_destination(
            name="Dhaka",
            country_code="BGD",
        )
        self.other_destination = self._create_destination(
            name="Kathmandu",
            country_code="NPL",
        )

        self.attraction = Attraction.objects.create(
            destination=self.destination,
            name="Lalbagh Fort",
            attraction_type="monument",
            description="A Mughal-era riverside fort.",
            picking_reasons=["Historic architecture"],
        )
        self.untrained_attraction = Attraction.objects.create(
            destination=self.destination,
            name="Ahsan Manzil",
            attraction_type="museum",
            description="The former palace of Dhaka's nawab family.",
            picking_reasons=["Local history"],
        )
        self.activity = Activity.objects.create(
            destination=self.destination,
            name="Old Dhaka Walk",
            activity_type="city_tour",
            description="A guided walk through historic neighbourhoods.",
            budget_tier="budget",
            picking_reasons=["Street-level exploration"],
        )
        self.untrained_activity = Activity.objects.create(
            destination=self.destination,
            name="River Cruise",
            activity_type="day_trip",
            description="A short cruise on the Buriganga River.",
            budget_tier="mid",
            picking_reasons=["River views"],
        )
        self.cuisine = Cuisine.objects.create(
            destination=self.destination,
            name="Kacchi Biryani",
            description="A fragrant rice and slow-cooked meat dish.",
            picking_reasons=["Signature local dish"],
        )
        self.untrained_cuisine = Cuisine.objects.create(
            destination=self.destination,
            name="Bakarkhani",
            description="A crisp, layered flatbread.",
            picking_reasons=["Traditional breakfast"],
        )

    def _create_destination(self, *, name, country_code):
        return Destination.objects.create(
            name=name,
            tagline=f"Discover {name}",
            description=f"A destination guide for {name}.",
            cover_image=f"https://example.com/{name.lower()}.jpg",
            country="Bangladesh" if country_code == "BGD" else "Nepal",
            country_code=country_code,
            destination_type="city",
            budget_tier="mid",
            currency="Taka" if country_code == "BGD" else "Nepalese Rupee",
            currency_code="BDT" if country_code == "BGD" else "NPR",
            picking_reasons=["Culture and food"],
            created_by=self.admin,
            updated_by=self.admin,
        )

    @patch(
        "destinations.api.v1.admin.views."
        "DestinationVectorService.get_indexed_source_ids"
    )
    def test_destination_list_returns_batched_training_status(self, indexed_ids_mock):
        indexed_ids_mock.return_value = {self.destination.id}

        response = self.client.get("/api/v1/admin/destinations/list/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = {row["id"]: row for row in response.data["data"]}
        self.assertIs(rows[str(self.destination.id)]["is_trained_completed"], True)
        self.assertIs(rows[str(self.other_destination.id)]["is_trained_completed"], False)
        indexed_ids_mock.assert_called_once()
        source_type, source_ids = indexed_ids_mock.call_args.args
        self.assertEqual(source_type, VectorDocument.SourceType.DESTINATION)
        self.assertCountEqual(
            list(source_ids),
            [self.destination.id, self.other_destination.id],
        )

    def test_child_lists_return_batched_training_status(self):
        cases = (
            (
                f"/api/v1/admin/destinations/{self.destination.id}/attractions/",
                VectorDocument.SourceType.ATTRACTION,
                self.attraction,
                self.untrained_attraction,
            ),
            (
                f"/api/v1/admin/destinations/{self.destination.id}/activities/",
                VectorDocument.SourceType.ACTIVITY,
                self.activity,
                self.untrained_activity,
            ),
            (
                f"/api/v1/admin/destinations/{self.destination.id}/cuisines/",
                VectorDocument.SourceType.CUISINE,
                self.cuisine,
                self.untrained_cuisine,
            ),
        )

        for url, source_type, trained_item, untrained_item in cases:
            with self.subTest(source_type=source_type), patch(
                "destinations.api.v1.admin.views."
                "DestinationVectorService.get_indexed_source_ids",
                return_value={trained_item.id},
            ) as indexed_ids_mock:
                response = self.client.get(url)

                self.assertEqual(response.status_code, status.HTTP_200_OK)
                rows = {row["id"]: row for row in response.data["data"]}
                self.assertIs(rows[str(trained_item.id)]["is_trained_completed"], True)
                self.assertIs(
                    rows[str(untrained_item.id)]["is_trained_completed"],
                    False,
                )
                indexed_ids_mock.assert_called_once()
                actual_source_type, source_ids = indexed_ids_mock.call_args.args
                self.assertEqual(actual_source_type, source_type)
                self.assertCountEqual(
                    list(source_ids),
                    [trained_item.id, untrained_item.id],
                )

    @patch("destinations.api.v1.admin.views.process_vector_operations.delay")
    def test_retrain_endpoints_queue_exact_vector_operations(self, delay_mock):
        cases = (
            (
                f"/api/v1/admin/destinations/{self.destination.id}/re-train/",
                VectorDocument.SourceType.DESTINATION,
                self.destination.id,
                self.destination.id,
            ),
            (
                f"/api/v1/admin/destinations/{self.destination.id}/attractions/"
                f"{self.attraction.id}/re-train/",
                VectorDocument.SourceType.ATTRACTION,
                self.attraction.id,
                self.destination.id,
            ),
            (
                f"/api/v1/admin/destinations/{self.destination.id}/activities/"
                f"{self.activity.id}/re-train/",
                VectorDocument.SourceType.ACTIVITY,
                self.activity.id,
                self.destination.id,
            ),
            (
                f"/api/v1/admin/destinations/{self.destination.id}/cuisines/"
                f"{self.cuisine.id}/re-train/",
                VectorDocument.SourceType.CUISINE,
                self.cuisine.id,
                self.destination.id,
            ),
        )

        for url, source_type, source_id, destination_id in cases:
            with self.subTest(source_type=source_type):
                delay_mock.reset_mock()

                response = self.client.post(url, format="json")

                self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
                self.assertEqual(response.data["status"], status.HTTP_202_ACCEPTED)
                self.assertTrue(response.data["success"])
                self.assertEqual(
                    response.data["data"],
                    {
                        "id": str(source_id),
                        "source_type": source_type,
                        "retraining_queued": True,
                    },
                )
                delay_mock.assert_called_once_with(
                    [
                        {
                            "action": "index",
                            "source_type": source_type,
                            "source_id": str(source_id),
                            "destination_id": str(destination_id),
                        }
                    ]
                )

    @patch("destinations.api.v1.admin.views.process_vector_operations.delay")
    def test_child_retrain_rejects_an_item_from_another_destination(self, delay_mock):
        urls = (
            f"/api/v1/admin/destinations/{self.other_destination.id}/attractions/"
            f"{self.attraction.id}/re-train/",
            f"/api/v1/admin/destinations/{self.other_destination.id}/activities/"
            f"{self.activity.id}/re-train/",
            f"/api/v1/admin/destinations/{self.other_destination.id}/cuisines/"
            f"{self.cuisine.id}/re-train/",
        )

        for url in urls:
            with self.subTest(url=url):
                response = self.client.post(url, format="json")
                self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        delay_mock.assert_not_called()

    @patch("destinations.api.v1.admin.views.process_vector_operations.delay")
    def test_retrain_endpoints_require_a_superadmin(self, delay_mock):
        self.client.force_authenticate(user=self.regular_user)
        urls = (
            f"/api/v1/admin/destinations/{self.destination.id}/re-train/",
            f"/api/v1/admin/destinations/{self.destination.id}/attractions/"
            f"{self.attraction.id}/re-train/",
            f"/api/v1/admin/destinations/{self.destination.id}/activities/"
            f"{self.activity.id}/re-train/",
            f"/api/v1/admin/destinations/{self.destination.id}/cuisines/"
            f"{self.cuisine.id}/re-train/",
        )

        for url in urls:
            with self.subTest(url=url):
                response = self.client.post(url, format="json")
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        delay_mock.assert_not_called()
