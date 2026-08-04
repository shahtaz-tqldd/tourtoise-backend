import uuid

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from pgvector.django import HnswIndex, VectorField


class VectorDocument(models.Model):
    class SourceType(models.TextChoices):
        DESTINATION = "destination", "Destination"
        ATTRACTION = "attraction", "Attraction"
        ACTIVITY = "activity", "Activity"
        CUISINE = "cuisine", "Cuisine"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    source_id = models.UUIDField()
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    embedding = VectorField(dimensions=1536)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vector_documents"
        ordering = ["source_type", "source_id", "created_at"]
        indexes = [
            models.Index(fields=["source_type", "source_id"]),
            GinIndex(fields=["metadata"]),
            HnswIndex(
                name="vector_docs_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self):
        return f"{self.source_type}:{self.source_id}"
