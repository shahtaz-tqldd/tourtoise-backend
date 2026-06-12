from django.utils import timezone
from rest_framework import serializers

from destinations.models import (
    Activity,
    ActivityImage,
    Attraction,
    AttractionImage,
    Cuisine,
    CuisineImage,
    Destination,
    DestinationImage,
    DestinationTag,
)


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


class AttractionImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttractionImage
        fields = ("image_url", "caption", "sort_order")
        read_only_fields = fields


class ActivityImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivityImage
        fields = ("image_url", "caption", "sort_order")
        read_only_fields = fields


class CuisineImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = CuisineImage
        fields = ("image_url", "caption", "sort_order")
        read_only_fields = fields


class ClientAttractionSerializer(serializers.ModelSerializer):
    images = AttractionImageSerializer(many=True, read_only=True)

    class Meta:
        model = Attraction
        fields = (
            "id",
            "name",
            "slug",
            "attraction_type",
            "description",
            "latitude",
            "longitude",
            "address",
            "cover_image",
            "budget_tier",
            "avg_duration_hours",
            "best_time_of_day",
            "entrance_fee_required",
            "approx_entrance_fee",
            "sort_order",
            "is_featured",
            "images",
        )
        read_only_fields = fields


class ClientActivitySerializer(serializers.ModelSerializer):
    images = ActivityImageSerializer(many=True, read_only=True)

    class Meta:
        model = Activity
        fields = (
            "id",
            "name",
            "slug",
            "activity_type",
            "description",
            "difficulty_level",
            "budget_tier",
            "approx_cost",
            "cost_unit",
            "duration_hours",
            "best_season",
            "cover_image",
            "booking_required",
            "is_featured",
            "images",
        )
        read_only_fields = fields


class ClientCuisineSerializer(serializers.ModelSerializer):
    images = CuisineImageSerializer(many=True, read_only=True)

    class Meta:
        model = Cuisine
        fields = (
            "id",
            "name",
            "slug",
            "cuisine_type",
            "description",
            "ingredients_note",
            "spice_level",
            "meal_type",
            "cover_image",
            "is_vegetarian_friendly",
            "is_must_try",
            "approx_price_range",
            "images",
        )
        read_only_fields = fields


class ClientDestinationAttractionSerializer(ClientAttractionSerializer):
    class Meta(ClientAttractionSerializer.Meta):
        fields = tuple(field for field in ClientAttractionSerializer.Meta.fields if field != "id")
        read_only_fields = fields


class ClientDestinationActivitySerializer(ClientActivitySerializer):
    class Meta(ClientActivitySerializer.Meta):
        fields = tuple(field for field in ClientActivitySerializer.Meta.fields if field != "id")
        read_only_fields = fields


class ClientDestinationCuisineSerializer(ClientCuisineSerializer):
    class Meta(ClientCuisineSerializer.Meta):
        fields = tuple(field for field in ClientCuisineSerializer.Meta.fields if field != "id")
        read_only_fields = fields


class ClientDestinationListSerializer(serializers.ModelSerializer):
    is_now_best_time = serializers.SerializerMethodField()
    tags = serializers.SerializerMethodField()

    def get_is_now_best_time(self, obj):
        return timezone.localdate().month in obj.best_travel_months

    def get_tags(self, obj):
        return [tag.name for tag in obj.tags.all()]

    class Meta:
        model = Destination
        fields = (
            "name",
            "slug",
            "country",
            "region",
            "destination_type",
            "cover_image",
            "is_now_best_time",
            "tags",
        )
        read_only_fields = fields


class ClientDestinationDetailSerializer(serializers.ModelSerializer):
    tags = DestinationTagSerializer(many=True, read_only=True)
    images = DestinationImageSerializer(many=True, read_only=True)
    attractions = ClientDestinationAttractionSerializer(many=True, read_only=True)
    activities = ClientDestinationActivitySerializer(many=True, read_only=True)
    cuisines = ClientDestinationCuisineSerializer(many=True, read_only=True)

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
            "attractions",
            "activities",
            "cuisines",
        )
        read_only_fields = fields
