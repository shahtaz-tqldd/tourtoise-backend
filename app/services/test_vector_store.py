from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from app.services.vector_store import DestinationVectorService
from vector_store.models import VectorDocument


class DestinationVectorFeatureFlagTests(SimpleTestCase):
    def setUp(self):
        config_objects_patcher = patch(
            "app.services.vector_store.TourtoiseConfig.objects"
        )
        self.config_objects = config_objects_patcher.start()
        self.addCleanup(config_objects_patcher.stop)
        config_values = self.config_objects.order_by.return_value.values_list.return_value
        config_values.first.return_value = False
        self.embedding_service = Mock()
        self.service = DestinationVectorService(
            embedding_service=self.embedding_service,
        )

    def test_disabled_config_skips_all_indexing_entry_points(self):
        with (
            patch.object(self.service, "_get_destination") as get_destination,
            patch.object(self.service, "_get_attraction") as get_attraction,
            patch.object(self.service, "_get_activity") as get_activity,
            patch.object(self.service, "_get_cuisine") as get_cuisine,
            patch.object(self.service, "_reindex_instance") as reindex_instance,
            patch("app.services.vector_store.Destination.objects") as destinations,
        ):
            self.assertIsNone(self.service.index_destination(uuid4()))
            self.assertIsNone(self.service.index_attraction(uuid4()))
            self.assertIsNone(self.service.index_activity(uuid4()))
            self.assertIsNone(self.service.index_cuisine(uuid4()))
            self.assertIsNone(self.service.index_destination_tree(uuid4()))
            self.assertIsNone(self.service.index_all())

        get_destination.assert_not_called()
        get_attraction.assert_not_called()
        get_activity.assert_not_called()
        get_cuisine.assert_not_called()
        reindex_instance.assert_not_called()
        destinations.prefetch_related.assert_not_called()
        self.embedding_service.embed_document.assert_not_called()

    @patch("app.services.vector_store.VectorDocument.objects")
    def test_disabled_config_skips_search_and_index_status_queries(
        self,
        vector_documents,
    ):
        results = self.service.search("beach destination")
        indexed_ids = self.service.get_indexed_source_ids(
            VectorDocument.SourceType.DESTINATION,
            [uuid4()],
        )

        self.assertEqual(results, [])
        self.assertEqual(indexed_ids, set())
        self.embedding_service.embed_query.assert_not_called()
        vector_documents.using.assert_not_called()

    def test_config_value_is_checked_again_for_each_operation(self):
        self.assertFalse(self.service._is_vectorization_enabled())

        config_values = self.config_objects.order_by.return_value.values_list.return_value
        config_values.first.return_value = True

        self.assertTrue(self.service._is_vectorization_enabled())
        self.assertEqual(self.config_objects.order_by.call_count, 2)

    def test_missing_config_uses_the_model_default(self):
        config_values = self.config_objects.order_by.return_value.values_list.return_value
        config_values.first.return_value = None

        self.assertTrue(self.service._is_vectorization_enabled())


class DestinationVectorContentTests(SimpleTestCase):
    def setUp(self):
        self.service = DestinationVectorService(embedding_service=Mock())
        self.destination = SimpleNamespace(name="Pokhara")

    def test_activity_content_uses_best_months(self):
        activity = SimpleNamespace(
            destination=self.destination,
            name="Paragliding",
            description="Tandem flight.",
            notes=[],
            picking_reasons=[],
            activity_type="adventure",
            difficulty_level="easy",
            budget_tier="premium",
            approx_cost="120 USD",
            best_months=[9, 10, 11],
            is_featured=True,
        )

        content = self.service._build_content(
            activity,
            VectorDocument.SourceType.ACTIVITY,
        )

        self.assertIn("Best months: 9, 10, 11", content)
        self.assertNotIn("Best season", content)

    def test_attraction_content_uses_best_months(self):
        attraction = SimpleNamespace(
            destination=self.destination,
            name="Phewa Lake",
            description="A scenic lake.",
            notes=[],
            picking_reasons=[],
            attraction_type="natural_site",
            budget_tier="mid",
            best_time_of_day="evening",
            best_months=[10, 11],
            how_to_reach="Walk from Lakeside.",
            address="Lakeside",
            is_featured=True,
            tags=SimpleNamespace(all=lambda: []),
        )

        content = self.service._build_content(
            attraction,
            VectorDocument.SourceType.ATTRACTION,
        )

        self.assertIn("Best months: 10, 11", content)
