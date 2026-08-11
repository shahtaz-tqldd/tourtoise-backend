from dataclasses import dataclass
from typing import Iterable

from django.db import transaction
from django.db.models import Q
from pgvector.django import CosineDistance

from destinations.models import Activity, Attraction, Cuisine, Destination
from vector_store.models import VectorDocument

from .gemini_embeddings import GeminiEmbeddingService


@dataclass(slots=True)
class VectorSearchResult:
    id: str
    source_type: str
    source_id: str
    content: str
    metadata: dict
    distance: float


class DestinationVectorService:
    db_alias = "vector"

    def __init__(self, *, embedding_service=None):
        self.embedding_service = embedding_service

    def _get_embedding_service(self):
        if self.embedding_service is None:
            self.embedding_service = GeminiEmbeddingService()
        return self.embedding_service

    @classmethod
    def get_indexed_source_ids(cls, source_type, source_ids):
        source_ids = list(source_ids)
        if not source_ids:
            return set()

        return set(
            VectorDocument.objects.using(cls.db_alias)
            .filter(source_type=source_type, source_id__in=source_ids)
            .order_by()
            .values_list("source_id", flat=True)
            .distinct()
        )

    def index_destination(self, destination):
        destination = self._get_destination(destination)
        self._reindex_instance(destination, VectorDocument.SourceType.DESTINATION)
        return destination

    def index_attraction(self, attraction):
        attraction = self._get_attraction(attraction)
        self._reindex_instance(attraction, VectorDocument.SourceType.ATTRACTION)
        return attraction

    def index_activity(self, activity):
        activity = self._get_activity(activity)
        self._reindex_instance(activity, VectorDocument.SourceType.ACTIVITY)
        return activity

    def index_cuisine(self, cuisine):
        cuisine = self._get_cuisine(cuisine)
        self._reindex_instance(cuisine, VectorDocument.SourceType.CUISINE)
        return cuisine

    def index_destination_tree(self, destination):
        destination = self._get_destination(destination)
        self._reindex_instance(destination, VectorDocument.SourceType.DESTINATION)
        for attraction in destination.attractions.all():
            self._reindex_instance(attraction, VectorDocument.SourceType.ATTRACTION)
        for activity in destination.activities.all():
            self._reindex_instance(activity, VectorDocument.SourceType.ACTIVITY)
        for cuisine in destination.cuisines.all():
            self._reindex_instance(cuisine, VectorDocument.SourceType.CUISINE)
        return destination

    def index_all(self):
        queryset = Destination.objects.prefetch_related("tags", "attractions__tags", "activities", "cuisines")
        for destination in queryset.iterator():
            self.index_destination_tree(destination)

    def remove_source(self, source_type, source_id):
        return (
            VectorDocument.objects.using(self.db_alias)
            .filter(source_type=source_type, source_id=source_id)
            .delete()
        )

    def remove_destination_tree(self, destination_id):
        """Remove a destination and every child document associated with it."""
        return (
            VectorDocument.objects.using(self.db_alias)
            .filter(
                Q(metadata__destination_id=str(destination_id))
                | Q(
                    source_type=VectorDocument.SourceType.DESTINATION,
                    source_id=destination_id,
                )
            )
            .delete()
        )

    def search(self, query, *, limit=10, source_types=None, destination_id=None):
        query_embedding = self._get_embedding_service().embed_query(query)
        queryset = VectorDocument.objects.using(self.db_alias).annotate(
            distance=CosineDistance("embedding", query_embedding)
        )
        if source_types:
            queryset = queryset.filter(source_type__in=source_types)
        if destination_id:
            queryset = queryset.filter(metadata__destination_id=str(destination_id))
        queryset = queryset.order_by("distance", "-updated_at")[:limit]
        return [
            VectorSearchResult(
                id=str(item.id),
                source_type=item.source_type,
                source_id=str(item.source_id),
                content=item.content,
                metadata=item.metadata,
                distance=float(item.distance),
            )
            for item in queryset
        ]

    def _reindex_instance(self, instance, source_type):
        documents = list(self._build_documents(instance, source_type))
        with transaction.atomic(using=self.db_alias):
            (
                VectorDocument.objects.using(self.db_alias)
                .filter(source_type=source_type, source_id=instance.id)
                .delete()
            )
            VectorDocument.objects.using(self.db_alias).bulk_create(documents)

    def _build_documents(self, instance, source_type) -> Iterable[VectorDocument]:
        metadata = self._build_metadata(instance, source_type)
        content = self._build_content(instance, source_type)
        chunks = [chunk for chunk in self._chunk_text(content) if chunk.strip()]
        total_chunks = len(chunks)

        for index, chunk in enumerate(chunks):
            chunk_metadata = {
                **metadata,
                "chunk_index": index,
                "chunk_count": total_chunks,
            }
            yield VectorDocument(
                source_type=source_type,
                source_id=instance.id,
                content=chunk,
                metadata=chunk_metadata,
                embedding=self._get_embedding_service().embed_document(chunk),
            )

    def _build_metadata(self, instance, source_type):
        metadata = {
            "name": instance.name,
            "slug": instance.slug,
            "source_type": source_type,
        }

        if source_type == VectorDocument.SourceType.DESTINATION:
            metadata.update(
                {
                    "destination_id": str(instance.id),
                    "country": instance.country,
                    "region": instance.region,
                    "destination_type": instance.destination_type,
                    "tags": [tag.name for tag in instance.tags.all()],
                }
            )
            return metadata

        destination = instance.destination
        metadata.update(
            {
                "destination_id": str(destination.id),
                "destination_name": destination.name,
            }
        )
        if hasattr(instance, "tags"):
            metadata["tags"] = [tag.name for tag in instance.tags.all()]
        return metadata

    def _build_content(self, instance, source_type):
        if source_type == VectorDocument.SourceType.DESTINATION:
            sections = [
                f"Destination: {instance.name}",
                f"Tagline: {instance.tagline}",
                f"Description: {instance.description}",
                f"Country: {instance.country}",
                f"Region: {instance.region}",
                f"Type: {instance.destination_type}",
                f"Budget tier: {instance.budget_tier}",
                f"Difficulty: {instance.difficulty_level}",
                f"Currency: {instance.currency} ({instance.currency_code})",
                f"Local languages: {', '.join(instance.local_languages or [])}",
                f"Best travel months: {', '.join(str(month) for month in instance.best_travel_months or [])}",
                f"Getting around: {instance.getting_around}",
                f"Visa notes: {instance.visa_notes}",
                f"Notes: {' | '.join(instance.notes or [])}",
                f"Picking reasons: {' | '.join(instance.picking_reasons or [])}",
                f"Tags: {', '.join(tag.name for tag in instance.tags.all())}",
            ]
            return "\n".join(section for section in sections if not section.endswith(": "))

        common_sections = [
            f"Destination: {instance.destination.name}",
            f"Name: {instance.name}",
            f"Description: {instance.description}",
            f"Notes: {' | '.join(instance.notes or [])}",
            f"Picking reasons: {' | '.join(instance.picking_reasons or [])}",
        ]

        if source_type == VectorDocument.SourceType.ATTRACTION:
            common_sections.extend(
                [
                    f"Attraction type: {instance.attraction_type}",
                    f"Budget tier: {instance.budget_tier}",
                    f"Best time of day: {instance.best_time_of_day}",
                    f"How to reach: {instance.how_to_reach}",
                    f"Address: {instance.address}",
                    f"Featured: {instance.is_featured}",
                    f"Tags: {', '.join(tag.name for tag in instance.tags.all())}",
                ]
            )
        elif source_type == VectorDocument.SourceType.ACTIVITY:
            common_sections.extend(
                [
                    f"Activity type: {instance.activity_type}",
                    f"Difficulty: {instance.difficulty_level}",
                    f"Budget tier: {instance.budget_tier}",
                    f"Approx cost: {instance.approx_cost}",
                    f"Best season: {instance.best_season}",
                    f"Featured: {instance.is_featured}",
                ]
            )
        elif source_type == VectorDocument.SourceType.CUISINE:
            common_sections.extend(
                [
                    f"Cuisine type: {instance.cuisine_type}",
                    f"Meal type: {instance.meal_type}",
                    f"Spice level: {instance.spice_level}",
                    f"Approx cost: {instance.approx_cost}",
                    f"Vegetarian friendly: {instance.is_vegetarian_friendly}",
                    f"Featured: {instance.is_featured}",
                ]
            )

        return "\n".join(section for section in common_sections if not section.endswith(": "))

    def _chunk_text(self, text, *, max_chars=2500):
        normalized = "\n".join(part.strip() for part in text.splitlines() if part.strip())
        if len(normalized) <= max_chars:
            return [normalized]

        chunks = []
        current = []
        current_length = 0
        for paragraph in normalized.split("\n"):
            addition = len(paragraph) + (1 if current else 0)
            if current and current_length + addition > max_chars:
                chunks.append("\n".join(current))
                current = [paragraph]
                current_length = len(paragraph)
                continue
            current.append(paragraph)
            current_length += addition

        if current:
            chunks.append("\n".join(current))
        return chunks

    def _get_destination(self, destination):
        if isinstance(destination, Destination):
            return destination
        return Destination.objects.prefetch_related(
            "tags",
            "attractions__tags",
            "activities",
            "cuisines",
        ).get(pk=destination)

    def _get_attraction(self, attraction):
        if isinstance(attraction, Attraction):
            return attraction
        return Attraction.objects.select_related("destination").prefetch_related("tags").get(pk=attraction)

    def _get_activity(self, activity):
        if isinstance(activity, Activity):
            return activity
        return Activity.objects.select_related("destination").get(pk=activity)

    def _get_cuisine(self, cuisine):
        if isinstance(cuisine, Cuisine):
            return cuisine
        return Cuisine.objects.select_related("destination").get(pk=cuisine)
