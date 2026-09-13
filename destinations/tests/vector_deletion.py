from types import SimpleNamespace
from unittest.mock import Mock, call, patch
from uuid import uuid4

from django.db.models import Q
from django.test import SimpleTestCase, TestCase

from vector_store.services.vectorize import DestinationVectorService
from destinations import signals as destination_signals
from destinations.choices import ActivityType, AttractionType, BudgetTier, DestinationType
from destinations.models import Activity, Attraction, Cuisine, Destination
from destinations.tasks import process_vector_operations
from vector_store.models import VectorDocument


def delete_operation(source_type, source_id, destination_id):
    return {
        "action": "delete",
        "source_type": source_type,
        "source_id": str(source_id),
        "destination_id": str(destination_id),
    }


def delete_tree_operation(destination_id):
    return {
        "action": "delete_tree",
        "source_type": "destination",
        "source_id": str(destination_id),
        "destination_id": str(destination_id),
    }


class DestinationVectorDeletionNormalizationTests(SimpleTestCase):
    def test_delete_tree_keeps_exact_child_deletes_and_deduplicates_operations(self):
        destination_id = uuid4()
        tree_operation = delete_tree_operation(destination_id)
        expected_operations = [
            delete_operation("attraction", uuid4(), destination_id),
            delete_operation("activity", uuid4(), destination_id),
            delete_operation("cuisine", uuid4(), destination_id),
            tree_operation,
        ]
        operations = [*expected_operations, tree_operation.copy()]

        normalized = destination_signals._normalize_vector_operations(operations)

        self.assertEqual(normalized, expected_operations)

    def test_delete_tree_does_not_suppress_deletes_for_any_destination(self):
        deleted_destination_id = uuid4()
        other_destination_id = uuid4()
        unrelated_delete = delete_operation("attraction", uuid4(), other_destination_id)
        related_delete = delete_operation("activity", uuid4(), deleted_destination_id)
        tree_operation = delete_tree_operation(deleted_destination_id)
        operations = [
            unrelated_delete,
            related_delete,
            tree_operation,
        ]

        normalized = destination_signals._normalize_vector_operations(operations)

        self.assertEqual(normalized, [unrelated_delete, related_delete, tree_operation])


class DestinationVectorDeletionCascadeSignalTests(TestCase):
    def test_destination_delete_queues_exact_child_deletes_and_one_tree_delete(self):
        with patch("destinations.signals._queue_vector_operation"):
            destination = Destination.objects.create(
                name="Vector Delete City",
                tagline="A destination used to test vector cleanup",
                description="Current destination content.",
                cover_image="https://example.com/vector-delete-city.jpg",
                country="Bangladesh",
                country_code="BGD",
                destination_type=DestinationType.CITY,
                budget_tier=BudgetTier.MID,
                currency="Bangladeshi Taka",
                currency_code="BDT",
            )
            attraction = Attraction.objects.create(
                destination=destination,
                name="Delete Test Attraction",
                description="Current attraction content.",
                attraction_type=AttractionType.MONUMENT,
            )
            activity = Activity.objects.create(
                destination=destination,
                name="Delete Test Activity",
                description="Current activity content.",
                activity_type=ActivityType.CITY_TOUR,
                budget_tier=BudgetTier.MID,
            )
            cuisine = Cuisine.objects.create(
                destination=destination,
                name="Delete Test Cuisine",
                description="Current cuisine content.",
            )

        destination_id = destination.id
        attraction_id = attraction.id
        activity_id = activity.id
        cuisine_id = cuisine.id
        expected_raw_operations = {
            (
                "delete",
                "attraction",
                str(attraction_id),
                str(destination_id),
            ),
            (
                "delete",
                "activity",
                str(activity_id),
                str(destination_id),
            ),
            (
                "delete",
                "cuisine",
                str(cuisine_id),
                str(destination_id),
            ),
            (
                "delete_tree",
                "destination",
                str(destination_id),
                str(destination_id),
            ),
        }

        with (
            patch(
                "destinations.signals._normalize_vector_operations",
                wraps=destination_signals._normalize_vector_operations,
            ) as normalize_mock,
            patch("destinations.signals.process_vector_operations.delay") as delay_mock,
            self.captureOnCommitCallbacks(execute=True),
        ):
            destination.delete()

        normalize_mock.assert_called_once()
        raw_operations = normalize_mock.call_args.args[0]
        self.assertEqual(len(raw_operations), 4)
        self.assertEqual(
            {
                (
                    operation["action"],
                    operation["source_type"],
                    operation["source_id"],
                    operation["destination_id"],
                )
                for operation in raw_operations
            },
            expected_raw_operations,
        )
        delay_mock.assert_called_once()
        queued_operations = delay_mock.call_args.args[0]
        self.assertEqual(len(queued_operations), 4)
        self.assertEqual(
            {
                (
                    operation["action"],
                    operation["source_type"],
                    operation["source_id"],
                    operation["destination_id"],
                )
                for operation in queued_operations
            },
            expected_raw_operations,
        )
        self.assertFalse(Destination.objects.filter(pk=destination_id).exists())
        self.assertFalse(Attraction.objects.filter(pk=attraction_id).exists())
        self.assertFalse(Activity.objects.filter(pk=activity_id).exists())
        self.assertFalse(Cuisine.objects.filter(pk=cuisine_id).exists())


class DestinationVectorDeletionTaskTests(SimpleTestCase):
    @patch("destinations.tasks.DestinationVectorService")
    def test_cascade_batch_dispatches_exact_child_and_destination_tree_removals(
        self,
        service_class,
    ):
        destination_id = uuid4()
        attraction_id = uuid4()
        activity_id = uuid4()
        cuisine_id = uuid4()
        operations = [
            delete_operation("attraction", attraction_id, destination_id),
            delete_operation("activity", activity_id, destination_id),
            delete_operation("cuisine", cuisine_id, destination_id),
            delete_tree_operation(destination_id),
        ]
        service = service_class.return_value

        result = process_vector_operations.run(operations)

        service_class.assert_called_once_with()
        service.remove_destination_tree.assert_called_once_with(str(destination_id))
        self.assertEqual(
            service.remove_source.call_args_list,
            [
                call("attraction", str(attraction_id)),
                call("activity", str(activity_id)),
                call("cuisine", str(cuisine_id)),
            ],
        )
        service.index_destination_tree.assert_not_called()
        service.index_destination.assert_not_called()
        service.index_attraction.assert_not_called()
        service.index_activity.assert_not_called()
        service.index_cuisine.assert_not_called()
        self.assertEqual(result, {"result": "processed", "count": 4})

    @patch("vector_store.services.vectorize.GeminiEmbeddingService")
    @patch("vector_store.services.vectorize.VectorDocument.objects")
    def test_real_delete_tree_task_does_not_initialize_embeddings(
        self,
        vector_document_objects,
        embedding_service_class,
    ):
        destination_id = uuid4()
        operation = delete_tree_operation(destination_id)
        queryset = vector_document_objects.using.return_value
        filtered_queryset = queryset.filter.return_value
        filtered_queryset.delete.return_value = (
            4,
            {"vector_store.VectorDocument": 4},
        )

        result = process_vector_operations.run([operation])

        embedding_service_class.assert_not_called()
        vector_document_objects.using.assert_called_once_with("vector")
        queryset.filter.assert_called_once_with(
            Q(metadata__destination_id=str(destination_id))
            | Q(
                source_type=VectorDocument.SourceType.DESTINATION,
                source_id=str(destination_id),
            ),
        )
        filtered_queryset.delete.assert_called_once_with()
        self.assertEqual(result, {"result": "processed", "count": 1})


class DestinationVectorDeletionServiceTests(SimpleTestCase):
    @patch("vector_store.services.vectorize.VectorDocument.objects")
    def test_remove_destination_tree_uses_metadata_and_exact_parent_fallback(
        self,
        vector_document_objects,
    ):
        destination_id = uuid4()
        delete_result = (4, {"vector_store.VectorDocument": 4})
        queryset = vector_document_objects.using.return_value
        filtered_queryset = queryset.filter.return_value
        filtered_queryset.delete.return_value = delete_result
        service = DestinationVectorService(embedding_service=Mock())

        result = service.remove_destination_tree(destination_id)

        vector_document_objects.using.assert_called_once_with("vector")
        queryset.filter.assert_called_once_with(
            Q(metadata__destination_id=str(destination_id))
            | Q(
                source_type=VectorDocument.SourceType.DESTINATION,
                source_id=destination_id,
            ),
        )
        filtered_queryset.delete.assert_called_once_with()
        self.assertEqual(result, delete_result)

    def test_all_source_metadata_uses_the_same_destination_id(self):
        destination_id = uuid4()
        destination_tags = Mock()
        destination_tags.all.return_value = [SimpleNamespace(name="City")]
        destination = SimpleNamespace(
            id=destination_id,
            name="Metadata City",
            slug="metadata-city-bgd",
            country="Bangladesh",
            region="Dhaka",
            destination_type=DestinationType.CITY,
            tags=destination_tags,
        )
        attraction_tags = Mock()
        attraction_tags.all.return_value = [SimpleNamespace(name="Historic")]
        sources = (
            (destination, VectorDocument.SourceType.DESTINATION),
            (
                SimpleNamespace(
                    id=uuid4(),
                    destination=destination,
                    name="Metadata Attraction",
                    slug="metadata-attraction",
                    tags=attraction_tags,
                ),
                VectorDocument.SourceType.ATTRACTION,
            ),
            (
                SimpleNamespace(
                    id=uuid4(),
                    destination=destination,
                    name="Metadata Activity",
                    slug="metadata-activity",
                ),
                VectorDocument.SourceType.ACTIVITY,
            ),
            (
                SimpleNamespace(
                    id=uuid4(),
                    destination=destination,
                    name="Metadata Cuisine",
                    slug="metadata-cuisine",
                ),
                VectorDocument.SourceType.CUISINE,
            ),
        )
        service = DestinationVectorService(embedding_service=Mock())

        for instance, source_type in sources:
            with self.subTest(source_type=source_type):
                metadata = service._build_metadata(instance, source_type)

                self.assertEqual(metadata["destination_id"], str(destination_id))
                self.assertEqual(metadata["source_type"], source_type)
