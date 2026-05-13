from rest_framework import serializers

from destinations.models import Destination, DestinationImage, DestinationTag


class DestinationTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = DestinationTag
        fields = ("name", "slug", "category")
        read_only_fields = fields


class DestinationImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = DestinationImage
        fields = ("image_url", "caption", "sort_order")
        read_only_fields = fields


class ClientDestinationListSerializer(serializers.ModelSerializer):
    tags = DestinationTagSerializer(many=True, read_only=True)

    class Meta:
        model = Destination
        fields = (
            "name",
            "slug",
            "country",
            "country_code",
            "region",
            "destination_type",
            "tagline",
            "cover_image",
            "budget_tier",
            "difficulty",
            "best_travel_months",
            "tags",
        )
        read_only_fields = fields


class ClientDestinationDetailSerializer(serializers.ModelSerializer):
    tags = DestinationTagSerializer(many=True, read_only=True)
    images = DestinationImageSerializer(many=True, read_only=True)

    class Meta:
        model = Destination
        fields = (
            "name",
            "slug",
            "country",
            "country_code",
            "region",
            "destination_type",
            "latitude",
            "longitude",
            "tagline",
            "overview",
            "cover_image",
            "tags",
            "min_stay_days",
            "max_stay_days",
            "budget_tier",
            "difficulty",
            "local_languages",
            "best_travel_months",
            "currency",
            "currency_code",
            "getting_around",
            "visa_notes",
            "cultural_tips",
            "images",
        )
        read_only_fields = fields
