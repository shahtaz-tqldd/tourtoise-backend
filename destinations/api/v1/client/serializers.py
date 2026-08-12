from django.utils import timezone
from rest_framework import serializers

from app.utils.cloudinary import cloudinary_thumbnail_url
from destinations.models import (
    Activity,
    ActivityImage,
    Attraction,
    AttractionImage,
    Cuisine,
    CuisineImage,
    Destination,
    DestinationImage,
    SavedDestination,
    DestinationTag,
)


class DestinationTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = DestinationTag
        fields = ("name", "slug", "category")
        read_only_fields = fields


class DestinationTagListSerializer(serializers.ModelSerializer):
    class Meta:
        model = DestinationTag
        fields = ("id", "name", "category")
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
    tags = DestinationTagSerializer(many=True, read_only=True)

    class Meta:
        model = Attraction
        fields = (
            "id",
            "name",
            "slug",
            "attraction_type",
            "description",
            "how_to_reach",
            "latitude",
            "longitude",
            "address",
            "cover_image",
            "budget_tier",
            "avg_duration_hours",
            "best_time_of_day",
            "picking_reasons",
            "notes",
            "tags",
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
            "duration_hours",
            "best_season",
            "cover_image",
            "picking_reasons",
            "notes",
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
            "spice_level",
            "meal_type",
            "cover_image",
            "is_vegetarian_friendly",
            "is_featured",
            "approx_cost",
            "picking_reasons",
            "notes",
            "images",
        )
        read_only_fields = fields


class ClientDestinationAttractionSerializer(serializers.ModelSerializer):
    tags = DestinationTagSerializer(many=True, read_only=True)

    class Meta:
        model = Attraction
        fields = (
            "name",
            "slug",
            "attraction_type",
            "address",
            "cover_image",
            "tags",
            "is_featured",
        )
        read_only_fields = fields


class ClientDestinationActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Activity
        fields = (
            "name",
            "slug",
            "activity_type",
            "cover_image",
            "booking_required",
            "is_featured",
        )
        read_only_fields = fields


class ClientDestinationCuisineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cuisine
        fields = (
            "name",
            "slug",
            "cuisine_type",
            "meal_type",
            "cover_image",
            "is_vegetarian_friendly",
            "is_featured",
        )
        read_only_fields = fields


class ClientDestinationListSerializer(serializers.ModelSerializer):
    cover_image = serializers.SerializerMethodField()
    is_now_best_time = serializers.SerializerMethodField()
    is_saved = serializers.SerializerMethodField()
    tags = serializers.SerializerMethodField()

    def get_cover_image(self, obj):
        return cloudinary_thumbnail_url(obj.cover_image, 800)

    def get_is_now_best_time(self, obj):
        return timezone.localdate().month in obj.best_travel_months

    def get_is_saved(self, obj):
        if hasattr(obj, "is_saved"):
            return bool(obj.is_saved)

        request = self.context.get("request")
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        return SavedDestination.objects.filter(user=user, destination=obj).exists()

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
            "is_saved",
            "tags",
        )
        read_only_fields = fields


class ClientDestinationShortDetailSerializer(serializers.ModelSerializer):
    cover_image = serializers.SerializerMethodField()
    tags = serializers.SerializerMethodField()

    def get_cover_image(self, obj):
        return cloudinary_thumbnail_url(obj.cover_image, 800)

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
            "tagline",
            "cover_image",
            "description",
            "budget_tier",
            "difficulty_level",
            "best_travel_months",
            "tags",
        )
        read_only_fields = fields


class DestinationSaveSerializer(serializers.Serializer):
    save = serializers.BooleanField()


class ClientDestinationDetailSerializer(serializers.ModelSerializer):
    tags = DestinationTagSerializer(many=True, read_only=True)
    images = DestinationImageSerializer(many=True, read_only=True)
    attractions = ClientDestinationAttractionSerializer(many=True, read_only=True)
    activities = ClientDestinationActivitySerializer(many=True, read_only=True)
    cuisines = ClientDestinationCuisineSerializer(many=True, read_only=True)
    is_saved = serializers.SerializerMethodField()

    def get_is_saved(self, obj):
        return ClientDestinationListSerializer(context=self.context).get_is_saved(obj)

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
            "description",
            "cover_image",
            "is_saved",
            "tags",
            "min_stay_days",
            "max_stay_days",
            "budget_tier",
            "difficulty_level",
            "local_languages",
            "best_travel_months",
            "currency",
            "currency_code",
            "getting_around",
            "visa_notes",
            "notes",
            "picking_reasons",
            "images",
            "attractions",
            "activities",
            "cuisines",
        )
        read_only_fields = fields
