import csv
import io
import json
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import models, transaction
from django.utils.text import slugify
from rest_framework import serializers

from app.utils.cloudinary import delete_image
from destinations.tasks import (
    upload_destination_gallery_image,
    upload_model_gallery_image,
    upload_model_image,
)
from destinations.choices import (
    ActivityType,
    AttractionType,
    BestTimeOfDay,
    BudgetTier,
    DestinationType,
    DifficultyLevel,
    MealType,
    SpiceLevel,
    Status,
    TagCategory,
)
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


class FlexibleJSONField(serializers.JSONField):
    def to_internal_value(self, data):
        if data in (None, "", []):
            return [] if self.required is False else data
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError("Send a valid JSON value.") from exc
        return super().to_internal_value(data)


class DestinationTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = DestinationTag
        fields = ("id", "name", "slug", "category")
        read_only_fields = fields


class DestinationImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = DestinationImage
        fields = ("id", "image_url", "caption", "sort_order", "created_at")
        read_only_fields = fields


class AttractionImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttractionImage
        fields = ("id", "image_url", "caption", "sort_order", "created_at")
        read_only_fields = fields


class ActivityImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivityImage
        fields = ("id", "image_url", "caption", "sort_order", "created_at")
        read_only_fields = fields


class CuisineImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = CuisineImage
        fields = ("id", "image_url", "caption", "sort_order", "created_at")
        read_only_fields = fields


class ChildImageUploadMixin:
    image_serializer_class = None
    image_model = None
    image_relation_name = ""
    image_folder_name = ""

    def validate_removed_images(self, value):
        image_urls = self._ensure_string_list(value, field_name="removed_images")
        if not image_urls or self.instance is None:
            return image_urls

        existing_urls = set(self.instance.images.filter(image_url__in=image_urls).values_list("image_url", flat=True))
        missing_urls = [image_url for image_url in image_urls if image_url not in existing_urls]
        if missing_urls:
            raise serializers.ValidationError(
                "These image URLs are not valid for this resource: "
                + ", ".join(missing_urls)
            )
        return image_urls

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["images"] = self.image_serializer_class(instance.images.all(), many=True).data
        return data

    def _save_pending_upload(self, image_file):
        extension = image_file.name.rsplit(".", 1)[-1] if "." in image_file.name else "upload"
        storage_name = f"pending_uploads/cloudinary/{uuid4().hex}.{extension}"
        image_file.seek(0)
        return default_storage.save(storage_name, image_file)

    def _create_child_images(self, instance, image_files):
        request = self.context["request"]
        existing_count = instance.images.count()
        for index, image_file in enumerate(image_files, start=existing_count + 1):
            self._enqueue_child_image_upload(
                image_file,
                instance=instance,
                sort_order=index,
                created_by_id=request.user.id,
            )

    def _delete_child_images(self, instance, image_urls):
        if not image_urls:
            return
        for image in instance.images.filter(image_url__in=image_urls):
            delete_image(image_url=image.image_url)
            image.delete()

    def _enqueue_child_image_upload(self, image_file, *, instance, sort_order, created_by_id):
        def enqueue():
            storage_path = self._save_pending_upload(image_file)
            upload_model_gallery_image.delay(
                storage_path=storage_path,
                app_label=instance._meta.app_label,
                parent_model_name=instance._meta.object_name,
                parent_object_id=str(instance.pk),
                image_model_name=self.image_model._meta.object_name,
                relation_name=self.image_relation_name,
                folder=f"{settings.CLOUDINARY_FOLDER}/destinations/{self.image_folder_name}/gallery",
                public_id=self._build_child_gallery_public_id(instance, sort_order),
                sort_order=sort_order,
                created_by_id=str(created_by_id) if created_by_id else None,
            )

        transaction.on_commit(enqueue)

    def _build_child_gallery_public_id(self, instance, index):
        base_name = slugify(instance.name) or uuid4().hex[:8]
        return f"{base_name}-{instance.id}-gallery-{index}"

    def _ensure_string_list(self, value, *, field_name):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError(f"Send {field_name} as a JSON array.")
        return [str(item).strip() for item in value if str(item).strip()]


class TrainingStatusSerializerMixin:
    def get_is_trained_completed(self, instance):
        trained_source_ids = self.context.get("trained_source_ids", set())
        return (
            instance.pk in trained_source_ids
            or str(instance.pk) in trained_source_ids
        )


class AdminAttractionSerializer(ChildImageUploadMixin, serializers.ModelSerializer):
    image_serializer_class = AttractionImageSerializer
    image_model = AttractionImage
    image_relation_name = "attraction"
    image_folder_name = "attractions"

    images = serializers.ListField(
        child=serializers.ImageField(),
        required=False,
        write_only=True,
    )
    removed_images = FlexibleJSONField(required=False, write_only=True)
    tags = DestinationTagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(
        queryset=DestinationTag.objects.all(),
        many=True,
        required=False,
        write_only=True,
    )
    picking_reasons = FlexibleJSONField(required=False)
    notes = FlexibleJSONField(required=False)

    class Meta:
        model = Attraction
        fields = (
            "id",
            "destination",
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
            "tag_ids",
            "entrance_fee_required",
            "approx_entrance_fee",
            "sort_order",
            "is_featured",
            "images",
            "removed_images",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "destination", "slug", "created_at", "updated_at")
        extra_kwargs = {
            "how_to_reach": {"required": False, "allow_blank": True, "allow_null": True},
            "address": {"required": False, "allow_blank": True},
            "cover_image": {"required": False, "allow_blank": True},
            "budget_tier": {"required": False, "allow_blank": True},
            "approx_entrance_fee": {"required": False, "allow_blank": True},
        }

    def validate(self, attrs):
        self._validate_unique_slug(attrs)
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        tag_ids = validated_data.pop("tag_ids", [])
        image_files = validated_data.pop("images", [])
        validated_data.pop("removed_images", [])
        validated_data["destination"] = self.context["destination"]
        validated_data["created_by"] = request.user
        validated_data["updated_by"] = request.user
        attraction = super().create(validated_data)
        if tag_ids:
            attraction.tags.set(tag_ids)
        self._create_child_images(attraction, image_files)
        return attraction

    def update(self, instance, validated_data):
        tag_ids = validated_data.pop("tag_ids", None)
        image_files = validated_data.pop("images", [])
        removed_images = validated_data.pop("removed_images", [])
        validated_data["updated_by"] = self.context["request"].user
        attraction = super().update(instance, validated_data)
        if tag_ids is not None:
            attraction.tags.set(tag_ids)
        self._delete_child_images(attraction, removed_images)
        self._create_child_images(attraction, image_files)
        return attraction

    def _validate_unique_slug(self, attrs):
        destination = self.context.get("destination")
        if not destination or destination._state.adding:
            return
        name = attrs.get("name", getattr(self.instance, "name", ""))
        slug = slugify(name)
        queryset = Attraction.objects.filter(destination=destination, slug=slug)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                {"name": "An attraction with this name already exists for this destination."}
            )


class AdminActivitySerializer(ChildImageUploadMixin, serializers.ModelSerializer):
    image_serializer_class = ActivityImageSerializer
    image_model = ActivityImage
    image_relation_name = "activity"
    image_folder_name = "activities"

    images = serializers.ListField(
        child=serializers.ImageField(),
        required=False,
        write_only=True,
    )
    removed_images = FlexibleJSONField(required=False, write_only=True)
    picking_reasons = FlexibleJSONField(required=False)
    notes = FlexibleJSONField(required=False)

    class Meta:
        model = Activity
        fields = (
            "id",
            "destination",
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
            "removed_images",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "destination", "slug", "created_at", "updated_at")
        extra_kwargs = {
            "best_season": {"required": False, "allow_blank": True},
            "cover_image": {"required": False, "allow_blank": True},
            "approx_cost": {"required": False, "allow_blank": True, "allow_null": True},
        }

    def validate(self, attrs):
        self._validate_unique_slug(attrs)
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        image_files = validated_data.pop("images", [])
        validated_data.pop("removed_images", [])
        validated_data["destination"] = self.context["destination"]
        validated_data["created_by"] = request.user
        validated_data["updated_by"] = request.user
        activity = super().create(validated_data)
        self._create_child_images(activity, image_files)
        return activity

    def update(self, instance, validated_data):
        image_files = validated_data.pop("images", [])
        removed_images = validated_data.pop("removed_images", [])
        validated_data["updated_by"] = self.context["request"].user
        activity = super().update(instance, validated_data)
        self._delete_child_images(activity, removed_images)
        self._create_child_images(activity, image_files)
        return activity

    def _validate_unique_slug(self, attrs):
        destination = self.context.get("destination")
        if not destination or destination._state.adding:
            return
        name = attrs.get("name", getattr(self.instance, "name", ""))
        slug = slugify(name)
        queryset = Activity.objects.filter(destination=destination, slug=slug)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                {"name": "An activity with this name already exists for this destination."}
            )

class AdminCuisineSerializer(ChildImageUploadMixin, serializers.ModelSerializer):
    image_serializer_class = CuisineImageSerializer
    image_model = CuisineImage
    image_relation_name = "cuisine"
    image_folder_name = "cuisines"

    images = serializers.ListField(
        child=serializers.ImageField(),
        required=False,
        write_only=True,
    )
    removed_images = FlexibleJSONField(required=False, write_only=True)
    picking_reasons = FlexibleJSONField(required=False)
    notes = FlexibleJSONField(required=False)

    class Meta:
        model = Cuisine
        fields = (
            "id",
            "destination",
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
            "removed_images",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "destination", "slug", "created_at", "updated_at")
        extra_kwargs = {
            "cuisine_type": {"required": False, "allow_blank": True},
            "cover_image": {"required": False, "allow_blank": True},
            "approx_cost": {"required": False, "allow_blank": True, "allow_null": True},
        }

    def validate(self, attrs):
        self._validate_unique_slug(attrs)
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        image_files = validated_data.pop("images", [])
        validated_data.pop("removed_images", [])
        validated_data["destination"] = self.context["destination"]
        validated_data["created_by"] = request.user
        validated_data["updated_by"] = request.user
        cuisine = super().create(validated_data)
        self._create_child_images(cuisine, image_files)
        return cuisine

    def update(self, instance, validated_data):
        image_files = validated_data.pop("images", [])
        removed_images = validated_data.pop("removed_images", [])
        validated_data["updated_by"] = self.context["request"].user
        cuisine = super().update(instance, validated_data)
        self._delete_child_images(cuisine, removed_images)
        self._create_child_images(cuisine, image_files)
        return cuisine

    def _validate_unique_slug(self, attrs):
        destination = self.context.get("destination")
        if not destination or destination._state.adding:
            return
        name = attrs.get("name", getattr(self.instance, "name", ""))
        slug = slugify(name)
        queryset = Cuisine.objects.filter(destination=destination, slug=slug)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                {"name": "A cuisine with this name already exists for this destination."}
            )


class AdminAttractionListSerializer(TrainingStatusSerializerMixin, AdminAttractionSerializer):
    is_trained_completed = serializers.SerializerMethodField()

    class Meta(AdminAttractionSerializer.Meta):
        fields = (*AdminAttractionSerializer.Meta.fields, "is_trained_completed")
        read_only_fields = (
            *AdminAttractionSerializer.Meta.read_only_fields,
            "is_trained_completed",
        )


class AdminActivityListSerializer(TrainingStatusSerializerMixin, AdminActivitySerializer):
    is_trained_completed = serializers.SerializerMethodField()

    class Meta(AdminActivitySerializer.Meta):
        fields = (*AdminActivitySerializer.Meta.fields, "is_trained_completed")
        read_only_fields = (
            *AdminActivitySerializer.Meta.read_only_fields,
            "is_trained_completed",
        )


class AdminCuisineListSerializer(TrainingStatusSerializerMixin, AdminCuisineSerializer):
    is_trained_completed = serializers.SerializerMethodField()

    class Meta(AdminCuisineSerializer.Meta):
        fields = (*AdminCuisineSerializer.Meta.fields, "is_trained_completed")
        read_only_fields = (
            *AdminCuisineSerializer.Meta.read_only_fields,
            "is_trained_completed",
        )


class AdminDestinationListSerializer(TrainingStatusSerializerMixin, serializers.ModelSerializer):
    tags = DestinationTagSerializer(many=True, read_only=True)
    images = DestinationImageSerializer(many=True, read_only=True)
    is_trained_completed = serializers.SerializerMethodField()

    class Meta:
        model = Destination
        fields = (
            "id",
            "name",
            "slug",
            "country",
            "country_code",
            "region",
            "destination_type",
            "tagline",
            "description",
            "cover_image",
            "budget_tier",
            "difficulty_level",
            "best_travel_months",
            "status",
            "tags",
            "images",
            "is_trained_completed",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdminDestinationShortDetailSerializer(serializers.ModelSerializer):
    tags = DestinationTagSerializer(many=True, read_only=True)

    class Meta:
        model = Destination
        fields = (
            "id",
            "name",
            "slug",
            "country",
            "region",
            "destination_type",
            "tagline",
            "description",
            "cover_image",
            "budget_tier",
            "difficulty_level",
            "best_travel_months",
            "tags",
            "status",
        )
        read_only_fields = fields


class AdminDestinationDetailSerializer(serializers.ModelSerializer):
    tags = DestinationTagSerializer(many=True, read_only=True)
    images = DestinationImageSerializer(many=True, read_only=True)
    attractions = AdminAttractionSerializer(many=True, read_only=True)
    activities = AdminActivitySerializer(many=True, read_only=True)
    cuisines = AdminCuisineSerializer(many=True, read_only=True)

    class Meta:
        model = Destination
        fields = (
            "id",
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
            "status",
            "images",
            "attractions",
            "activities",
            "cuisines",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdminDestinationWriteSerializer(serializers.ModelSerializer):
    tags = FlexibleJSONField(required=False)
    attractions = FlexibleJSONField(required=False, write_only=True)
    activities = FlexibleJSONField(required=False, write_only=True)
    cuisines = FlexibleJSONField(required=False, write_only=True)
    local_languages = FlexibleJSONField(required=False)
    best_travel_months = FlexibleJSONField(required=False)
    notes = FlexibleJSONField(required=False)
    picking_reasons = FlexibleJSONField(required=False)
    remove_image_urls = FlexibleJSONField(required=False, write_only=True)
    removed_gallery_image_ids = FlexibleJSONField(required=False, write_only=True)
    clear_cover_image = serializers.BooleanField(required=False, write_only=True, default=False)
    cover_image_file = serializers.ImageField(required=False, allow_null=True, write_only=True)
    gallery_images = serializers.ListField(
        child=serializers.ImageField(),
        required=False,
        write_only=True,
    )

    class Meta:
        model = Destination
        fields = (
            "name",
            "country",
            "region",
            "destination_type",
            "latitude",
            "longitude",
            "tagline",
            "description",
            "cover_image",
            "cover_image_file",
            "tags",
            "attractions",
            "activities",
            "cuisines",
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
            "status",
            "gallery_images",
            "remove_image_urls",
            "removed_gallery_image_ids",
            "clear_cover_image",
        )
        extra_kwargs = {
            "cover_image": {"required": False, "allow_blank": True},
            "region": {"required": False, "allow_blank": True},
            "getting_around": {"required": False, "allow_blank": True},
            "visa_notes": {"required": False, "allow_blank": True},
        }

    def validate_tags(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Send tags as a JSON array.")

        normalized_tags = []
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError(
                    "Each tag must be an object with 'name' and 'category'."
                )
            name = str(item.get("name", "")).strip()
            category = str(item.get("category", "")).strip()
            if not name or not category:
                raise serializers.ValidationError(
                    "Each tag object must include non-empty 'name' and 'category'."
                )
            normalized_tags.append({"name": name, "category": category})
        return normalized_tags

    def validate_attractions(self, value):
        if self.instance is not None:
            return self._validate_nested_cover_image_updates(
                value,
                model=Attraction,
                field_name="attractions",
            )
        return self._validate_nested_resource(
            value,
            serializer_class=AdminAttractionSerializer,
            field_name="attractions",
        )

    def validate_activities(self, value):
        if self.instance is not None:
            return self._validate_nested_cover_image_updates(
                value,
                model=Activity,
                field_name="activities",
            )
        return self._validate_nested_resource(
            value,
            serializer_class=AdminActivitySerializer,
            field_name="activities",
        )

    def validate_cuisines(self, value):
        if self.instance is not None:
            return self._validate_nested_cover_image_updates(
                value,
                model=Cuisine,
                field_name="cuisines",
            )
        return self._validate_nested_resource(
            value,
            serializer_class=AdminCuisineSerializer,
            field_name="cuisines",
        )

    def validate_local_languages(self, value):
        return self._ensure_string_list(value, field_name="local_languages")

    def validate_best_travel_months(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Send best_travel_months as a JSON array.")

        months = []
        for item in value:
            try:
                month = int(item)
            except (TypeError, ValueError) as exc:
                raise serializers.ValidationError("Months must be integers from 1 to 12.") from exc
            if month < 1 or month > 12:
                raise serializers.ValidationError("Months must be integers from 1 to 12.")
            months.append(month)
        return months

    def validate_notes(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Send notes as a JSON array.")
        return value

    def validate_picking_reasons(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Send pickign reasons as a JSON array.")
        return value

    def validate_remove_image_urls(self, value):
        if value in (None, ""):
            return []
        return self._ensure_string_list(value, field_name="remove_image_urls")

    def validate_removed_gallery_image_ids(self, value):
        image_ids = self._ensure_uuid_list(value, field_name="removed_gallery_image_ids")
        if not image_ids or self.instance is None:
            return image_ids

        existing_ids = set(
            self.instance.images.filter(id__in=image_ids).values_list("id", flat=True)
        )
        missing_ids = [str(image_id) for image_id in image_ids if image_id not in existing_ids]
        if missing_ids:
            raise serializers.ValidationError(
                f"Gallery image id(s) are not valid for this destination: {', '.join(missing_ids)}."
            )
        return image_ids

    def validate(self, attrs):
        cover_image = attrs.get("cover_image", "")
        cover_image_file = attrs.get("cover_image_file", serializers.empty)
        clear_cover_image = attrs.get("clear_cover_image", False)

        if self.instance is None and not cover_image and cover_image_file is serializers.empty:
            raise serializers.ValidationError(
                {"cover_image_file": "Send either cover_image_file or cover_image."}
            )
        if self.instance is None and clear_cover_image:
            raise serializers.ValidationError(
                {"clear_cover_image": "clear_cover_image can only be used while updating."}
            )
        if clear_cover_image and cover_image_file not in (serializers.empty, None):
            raise serializers.ValidationError(
                {"clear_cover_image": "Do not send clear_cover_image with cover_image_file."}
            )

        min_stay_days = attrs.get("min_stay_days", getattr(self.instance, "min_stay_days", 0))
        max_stay_days = attrs.get("max_stay_days", getattr(self.instance, "max_stay_days", 0))
        if min_stay_days and max_stay_days and min_stay_days > max_stay_days:
            raise serializers.ValidationError(
                {"max_stay_days": "max_stay_days must be greater than or equal to min_stay_days."}
            )
        return attrs

    def create(self, validated_data):
        tags_data = validated_data.pop("tags", [])
        attractions_data = validated_data.pop("attractions", [])
        activities_data = validated_data.pop("activities", [])
        cuisines_data = validated_data.pop("cuisines", [])
        cover_image_file = validated_data.pop("cover_image_file", serializers.empty)
        gallery_images = validated_data.pop("gallery_images", [])
        validated_data.pop("remove_image_urls", [])
        validated_data.pop("removed_gallery_image_ids", [])
        validated_data.pop("clear_cover_image", False)

        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["updated_by"] = request.user
        validated_data["cover_image"] = validated_data.get("cover_image", "")

        with transaction.atomic():
            destination = Destination.objects.create(**validated_data)
            self._sync_tags(destination, tags_data)
            self._sync_cover_image(destination, cover_image_file, keep_existing=False)
            self._create_gallery_images(destination, gallery_images)
            attractions = self._create_nested_resources(destination, attractions_data, AdminAttractionSerializer)
            activities = self._create_nested_resources(destination, activities_data, AdminActivitySerializer)
            cuisines = self._create_nested_resources(destination, cuisines_data, AdminCuisineSerializer)
            self._sync_nested_cover_images("attractions", attractions)
            self._sync_nested_cover_images("activities", activities)
            self._sync_nested_cover_images("cuisines", cuisines)
        return destination

    def update(self, instance, validated_data):
        tags_data = validated_data.pop("tags", None)
        attractions_data = validated_data.pop("attractions", [])
        activities_data = validated_data.pop("activities", [])
        cuisines_data = validated_data.pop("cuisines", [])
        cover_image_file = validated_data.pop("cover_image_file", serializers.empty)
        gallery_images = validated_data.pop("gallery_images", [])
        remove_image_urls = validated_data.pop("remove_image_urls", [])
        removed_gallery_image_ids = validated_data.pop("removed_gallery_image_ids", [])
        clear_cover_image = validated_data.pop("clear_cover_image", False)
        previous_cover_image = instance.cover_image

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.updated_by = self.context["request"].user
        instance.save()

        if tags_data is not None:
            self._sync_tags(instance, tags_data)
        if "cover_image" in validated_data and previous_cover_image and previous_cover_image != instance.cover_image:
            delete_image(image_url=previous_cover_image)
        if clear_cover_image:
            self._sync_cover_image(instance, None, keep_existing=True)
        else:
            self._sync_cover_image(instance, cover_image_file, keep_existing=True)
        self._delete_gallery_images(instance, image_urls=remove_image_urls, image_ids=removed_gallery_image_ids)
        self._create_gallery_images(instance, gallery_images)
        self._sync_nested_cover_images("attractions", attractions_data)
        self._sync_nested_cover_images("activities", activities_data)
        self._sync_nested_cover_images("cuisines", cuisines_data)
        return instance

    def _ensure_string_list(self, value, *, field_name):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError(f"Send {field_name} as a JSON array.")
        return [str(item).strip() for item in value if str(item).strip()]

    def _ensure_uuid_list(self, value, *, field_name):
        values = self._ensure_string_list(value, field_name=field_name)
        image_ids = []
        for item in values:
            try:
                image_ids.append(UUID(item))
            except (TypeError, ValueError) as exc:
                raise serializers.ValidationError(f"Send valid UUID values for {field_name}.") from exc
        return image_ids

    def _validate_nested_resource(self, value, *, serializer_class, field_name):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError(f"Send {field_name} as a JSON array.")
        destination = self.instance or Destination()
        serializer = serializer_class(
            data=value,
            many=True,
            context={
                "request": self.context["request"],
                "destination": destination,
            },
        )
        serializer.is_valid(raise_exception=True)
        self._validate_unique_nested_names(serializer.validated_data, field_name=field_name)
        return serializer.validated_data

    def _validate_nested_cover_image_updates(self, value, *, model, field_name):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError(f"Send {field_name} as a JSON array.")

        items = []
        for index, item in enumerate(value):
            if not isinstance(item, dict) or not item.get("id"):
                raise serializers.ValidationError(
                    f"Each {field_name} item must include an id for cover image updates."
                )
            try:
                instance = model.objects.get(destination=self.instance, pk=item["id"])
            except (model.DoesNotExist, ValueError, TypeError) as exc:
                raise serializers.ValidationError(
                    f"{field_name}[{index}].id is not valid for this destination."
                ) from exc
            items.append(instance)
        return items

    def _validate_unique_nested_names(self, items, *, field_name):
        seen = set()
        duplicates = set()
        for item in items:
            slug = slugify(item.get("name", ""))
            if slug in seen:
                duplicates.add(item.get("name", ""))
            seen.add(slug)
        if duplicates:
            duplicate_names = ", ".join(sorted(name for name in duplicates if name))
            raise serializers.ValidationError(
                f"Duplicate {field_name} names are not allowed in the same destination payload: {duplicate_names}."
            )

    def _sync_tags(self, destination, tags_data):
        tag_ids = []
        for item in tags_data:
            tag, _ = DestinationTag.objects.get_or_create(
                slug=slugify(item["name"]),
                defaults={
                    "name": item["name"],
                    "category": item["category"],
                    "created_by": self.context["request"].user,
                    "updated_by": self.context["request"].user,
                },
            )
            if tag.name != item["name"] or tag.category != item["category"]:
                tag.name = item["name"]
                tag.category = item["category"]
                tag.updated_by = self.context["request"].user
                tag.save(update_fields=["name", "category", "updated_by", "updated_at"])
            tag_ids.append(tag.pk)
        destination.tags.set(tag_ids)

    def _sync_cover_image(self, destination, cover_image_file, *, keep_existing):
        if cover_image_file is serializers.empty:
            return
        if cover_image_file is None:
            if keep_existing and destination.cover_image:
                delete_image(image_url=destination.cover_image)
            destination.cover_image = ""
            destination.save(update_fields=["cover_image", "updated_at"])
            return

        self._enqueue_model_image_upload(
            cover_image_file,
            instance=destination,
            field_name="cover_image",
            folder=f"{settings.CLOUDINARY_FOLDER}/destinations/covers",
            public_id=self._build_cover_public_id(destination),
            previous_image_url=destination.cover_image if keep_existing else None,
        )

    def _create_gallery_images(self, destination, gallery_images):
        request = self.context["request"]
        existing_count = destination.images.count()
        for index, image_file in enumerate(gallery_images, start=existing_count + 1):
            self._enqueue_gallery_image_upload(
                image_file,
                destination=destination,
                folder=f"{settings.CLOUDINARY_FOLDER}/destinations/gallery",
                public_id=self._build_gallery_public_id(destination, index),
                sort_order=index,
                created_by_id=request.user.id,
            )

    def _delete_gallery_images(self, destination, *, image_urls=None, image_ids=None):
        image_urls = image_urls or []
        image_ids = image_ids or []
        if not image_urls and not image_ids:
            return
        images_to_remove = destination.images.filter(
            models.Q(image_url__in=image_urls) | models.Q(id__in=image_ids)
        )
        for image in images_to_remove:
            delete_image(image_url=image.image_url)
            image.delete()

    def _create_nested_resources(self, destination, items, serializer_class):
        serializer = serializer_class(
            data=items,
            many=True,
            context={
                "request": self.context["request"],
                "destination": destination,
            },
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def _sync_nested_cover_images(self, field_name, instances):
        request = self.context["request"]
        for index, instance in enumerate(instances):
            image_file = request.FILES.get(f"{field_name}[{index}].cover_image_file")
            if not image_file:
                continue
            self._sync_child_cover_image(instance, image_file, field_name=field_name)

    def _sync_child_cover_image(self, instance, image_file, *, field_name):
        self._enqueue_model_image_upload(
            image_file,
            instance=instance,
            field_name="cover_image",
            folder=f"{settings.CLOUDINARY_FOLDER}/destinations/{field_name}/covers",
            public_id=self._build_child_cover_public_id(instance),
            previous_image_url=instance.cover_image,
        )

    def _enqueue_model_image_upload(
        self,
        image_file,
        *,
        instance,
        field_name,
        folder,
        public_id,
        previous_image_url=None,
    ):
        def enqueue():
            storage_path = self._save_pending_upload(image_file)
            upload_model_image.delay(
                storage_path=storage_path,
                app_label=instance._meta.app_label,
                model_name=instance._meta.object_name,
                object_id=str(instance.pk),
                field_name=field_name,
                folder=folder,
                public_id=public_id,
                previous_image_url=previous_image_url,
            )

        transaction.on_commit(enqueue)

    def _enqueue_gallery_image_upload(
        self,
        image_file,
        *,
        destination,
        folder,
        public_id,
        sort_order,
        created_by_id,
    ):
        def enqueue():
            storage_path = self._save_pending_upload(image_file)
            upload_destination_gallery_image.delay(
                storage_path=storage_path,
                destination_id=str(destination.pk),
                folder=folder,
                public_id=public_id,
                sort_order=sort_order,
                created_by_id=str(created_by_id) if created_by_id else None,
            )

        transaction.on_commit(enqueue)

    def _save_pending_upload(self, image_file):
        extension = image_file.name.rsplit(".", 1)[-1] if "." in image_file.name else "upload"
        storage_name = f"pending_uploads/cloudinary/{uuid4().hex}.{extension}"
        image_file.seek(0)
        return default_storage.save(storage_name, image_file)

    def _build_cover_public_id(self, destination):
        base_name = slugify(destination.name) or uuid4().hex[:8]
        return f"{base_name}-{destination.id}-cover"

    def _build_gallery_public_id(self, destination, index):
        base_name = slugify(destination.name) or uuid4().hex[:8]
        return f"{base_name}-{destination.id}-gallery-{index}"

    def _build_child_cover_public_id(self, instance):
        base_name = slugify(instance.name) or uuid4().hex[:8]
        return f"{base_name}-{instance.id}-cover"


BULK_DESTINATION_TEMPLATE = {
    "xlsx_sheets": {
        "destinations": [
            "destination_key",
            "name",
            "country",
            "country_code",
            "region",
            "destination_type",
            "latitude",
            "longitude",
            "tagline",
            "description",
            "cover_image",
            "image_urls",
            "image_captions",
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
            "status",
        ],
        "attractions": [
            "destination_key",
            "name",
            "attraction_type",
            "description",
            "how_to_reach",
            "latitude",
            "longitude",
            "address",
            "cover_image",
            "image_urls",
            "image_captions",
            "tags",
            "budget_tier",
            "avg_duration_hours",
            "best_time_of_day",
            "picking_reasons",
            "notes",
            "entrance_fee_required",
            "approx_entrance_fee",
            "sort_order",
            "is_featured",
        ],
        "activities": [
            "destination_key",
            "name",
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
            "image_urls",
            "image_captions",
            "booking_required",
            "is_featured",
        ],
        "cuisines": [
            "destination_key",
            "name",
            "cuisine_type",
            "description",
            "spice_level",
            "meal_type",
            "cover_image",
            "image_urls",
            "image_captions",
            "is_vegetarian_friendly",
            "is_featured",
            "approx_cost",
            "picking_reasons",
            "notes",
        ],
    },
    "csv_columns": [
        "record_type",
        "destination_key",
        "name",
        "country",
        "country_code",
        "region",
        "destination_type",
        "latitude",
        "longitude",
        "tagline",
        "description",
        "cover_image",
        "image_urls",
        "image_captions",
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
        "status",
        "attraction_type",
        "how_to_reach",
        "address",
        "avg_duration_hours",
        "best_time_of_day",
        "picking_reasons",
        "notes",
        "entrance_fee_required",
        "approx_entrance_fee",
        "sort_order",
        "activity_type",
        "approx_cost",
        "duration_hours",
        "best_season",
        "booking_required",
        "cuisine_type",
        "spice_level",
        "meal_type",
        "is_vegetarian_friendly",
        "is_featured",
    ],
    "examples": {
        "destinations": {
            "destination_key": "pokhara-npl",
            "name": "Pokhara",
            "country": "Nepal",
            "country_code": "NPL",
            "region": "Gandaki",
            "destination_type": "city",
            "latitude": "28.2096",
            "longitude": "83.9856",
            "tagline": "Lakeside city",
            "description": "Gateway to the Annapurna region.",
            "cover_image": "https://example.com/pokhara-cover.jpg",
            "image_urls": "https://example.com/pokhara-1.jpg;https://example.com/pokhara-2.jpg",
            "image_captions": "Lake view;Mountain view",
            "tags": "Lake:experience;Adventure:activity",
            "min_stay_days": "2",
            "max_stay_days": "5",
            "budget_tier": "mid",
            "difficulty_level": "easy",
            "local_languages": "Nepali;English",
            "best_travel_months": "10;11;12",
            "currency": "Nepalese Rupee",
            "currency_code": "NPR",
            "getting_around": "Taxi and local buses are common.",
            "visa_notes": "Check current visa policy before travel.",
            "notes": "Dress modestly at temples;Carry cash",
            "picking_reasons": "Great for island hopping;Beach escaping",
            "status": "draft",
        },
        "attractions": {
            "destination_key": "pokhara-npl",
            "name": "Phewa Lake",
            "attraction_type": "natural_site",
            "description": "A scenic freshwater lake.",
            "how_to_reach": "Walk from Lakeside or take a short taxi ride.",
            "cover_image": "https://example.com/phewa-cover.jpg",
            "image_urls": "https://example.com/phewa-1.jpg",
            "tags": "Lake:experience;Family:vibe",
            "picking_reasons": "Boat rides;Mountain views",
            "notes": "Go near sunset;Carry cash",
        },
        "activities": {
            "destination_key": "pokhara-npl",
            "name": "Paragliding",
            "activity_type": "adventure",
            "description": "Tandem paragliding over the valley.",
            "budget_tier": "premium",
            "cover_image": "https://example.com/paragliding-cover.jpg",
        },
        "cuisines": {
            "destination_key": "pokhara-npl",
            "name": "Thakali Set",
            "description": "Traditional rice meal.",
            "meal_type": "lunch",
            "cover_image": "https://example.com/thakali-cover.jpg",
        },
    },
        "allowed_values": {
        "destination_type": [choice.value for choice in DestinationType],
        "budget_tier": [choice.value for choice in BudgetTier],
        "difficulty_level": [choice.value for choice in DifficultyLevel],
        "status": [choice.value for choice in Status],
        "tag_category": [choice.value for choice in TagCategory],
        "attraction_type": [choice.value for choice in AttractionType],
        "activity_type": [choice.value for choice in ActivityType],
        "best_time_of_day": [choice.value for choice in BestTimeOfDay],
        "spice_level": [choice.value for choice in SpiceLevel],
        "meal_type": [choice.value for choice in MealType],
    },
    "notes": [
        "XLSX uploads should use four sheet names: destinations, attractions, activities, cuisines.",
        "CSV uploads should use one combined sheet with record_type values: destination, attraction, activity, cuisine.",
        "destination_key is required and links attraction/activity/cuisine rows to a destination row.",
        "Use semicolon-separated values for list fields: image_urls, image_captions, tags, local_languages, best_travel_months, notes, picking_reasons.",
        "tags format is Name:category;Name:category, for example Lake:experience;Adventure:activity.",
    ],
    "picking_reasons": [
        "XLSX uploads should use four sheet names: destinations, attractions, activities, cuisines.",
        "CSV uploads should use one combined sheet with record_type values: destination, attraction, activity, cuisine.",
        "destination_key is required and links attraction/activity/cuisine rows to a destination row.",
        "Use semicolon-separated values for list fields: image_urls, image_captions, tags, local_languages, best_travel_months, notes, picking_reasons.",
        "tags format is Name:category;Name:category, for example Lake:experience;Adventure:activity.",
    ],
}

CHILD_BULK_TEMPLATE_NOTES = [
    "Uploads are destination-scoped, so do not include destination_key or record_type columns.",
    "CSV uploads should contain one header row and one child record per row.",
    "XLSX uploads should use a single sheet matching the resource name.",
    "Use semicolon-separated values for list fields such as image_urls, image_captions, tags, notes, and picking_reasons.",
    "tags format is Name:category;Name:category, for example Lake:experience;Adventure:activity.",
]

BULK_ATTRACTION_TEMPLATE = {
    "xlsx_sheets": {
        "attractions": [
            "name",
            "attraction_type",
            "description",
            "how_to_reach",
            "latitude",
            "longitude",
            "address",
            "cover_image",
            "image_urls",
            "image_captions",
            "tags",
            "budget_tier",
            "avg_duration_hours",
            "best_time_of_day",
            "picking_reasons",
            "notes",
            "entrance_fee_required",
            "approx_entrance_fee",
            "sort_order",
            "is_featured",
        ],
    },
    "csv_columns": [
        "name",
        "attraction_type",
        "description",
        "how_to_reach",
        "latitude",
        "longitude",
        "address",
        "cover_image",
        "image_urls",
        "image_captions",
        "tags",
        "budget_tier",
        "avg_duration_hours",
        "best_time_of_day",
        "picking_reasons",
        "notes",
        "entrance_fee_required",
        "approx_entrance_fee",
        "sort_order",
        "is_featured",
    ],
    "example": {
        "name": "Phewa Lake",
        "attraction_type": "natural_site",
        "description": "A scenic freshwater lake.",
        "how_to_reach": "Walk from Lakeside or take a short taxi ride.",
        "cover_image": "https://example.com/phewa-cover.jpg",
        "image_urls": "https://example.com/phewa-1.jpg;https://example.com/phewa-2.jpg",
        "image_captions": "Lake view;Boat ride",
        "tags": "Lake:experience;Family:vibe",
        "budget_tier": "mid",
        "avg_duration_hours": "2",
        "best_time_of_day": "evening",
        "picking_reasons": "Boat rides;Mountain views",
        "notes": "Go near sunset;Carry cash",
        "entrance_fee_required": "false",
        "approx_entrance_fee": "",
        "sort_order": "1",
        "is_featured": "true",
    },
    "allowed_values": {
        "attraction_type": [choice.value for choice in AttractionType],
        "budget_tier": [choice.value for choice in BudgetTier],
        "best_time_of_day": [choice.value for choice in BestTimeOfDay],
        "tag_category": [choice.value for choice in TagCategory],
    },
    "notes": CHILD_BULK_TEMPLATE_NOTES,
}

BULK_ACTIVITY_TEMPLATE = {
    "xlsx_sheets": {
        "activities": [
            "name",
            "activity_type",
            "description",
            "difficulty_level",
            "budget_tier",
            "approx_cost",
            "duration_hours",
            "best_season",
            "cover_image",
            "image_urls",
            "image_captions",
            "picking_reasons",
            "notes",
            "booking_required",
            "is_featured",
        ],
    },
    "csv_columns": [
        "name",
        "activity_type",
        "description",
        "difficulty_level",
        "budget_tier",
        "approx_cost",
        "duration_hours",
        "best_season",
        "cover_image",
        "image_urls",
        "image_captions",
        "picking_reasons",
        "notes",
        "booking_required",
        "is_featured",
    ],
    "example": {
        "name": "Paragliding",
        "activity_type": "adventure",
        "description": "Tandem paragliding over the valley.",
        "difficulty_level": "easy",
        "budget_tier": "premium",
        "approx_cost": "120 USD",
        "duration_hours": "3",
        "best_season": "Autumn",
        "cover_image": "https://example.com/paragliding-cover.jpg",
        "image_urls": "https://example.com/paragliding-1.jpg",
        "image_captions": "Takeoff view",
        "picking_reasons": "Aerial views;Adventure",
        "notes": "Weather dependent",
        "booking_required": "true",
        "is_featured": "true",
    },
    "allowed_values": {
        "activity_type": [choice.value for choice in ActivityType],
        "difficulty_level": [choice.value for choice in DifficultyLevel],
        "budget_tier": [choice.value for choice in BudgetTier],
    },
    "notes": CHILD_BULK_TEMPLATE_NOTES,
}

BULK_CUISINE_TEMPLATE = {
    "xlsx_sheets": {
        "cuisines": [
            "name",
            "cuisine_type",
            "description",
            "spice_level",
            "meal_type",
            "cover_image",
            "image_urls",
            "image_captions",
            "is_vegetarian_friendly",
            "is_featured",
            "approx_cost",
            "picking_reasons",
            "notes",
        ],
    },
    "csv_columns": [
        "name",
        "cuisine_type",
        "description",
        "spice_level",
        "meal_type",
        "cover_image",
        "image_urls",
        "image_captions",
        "is_vegetarian_friendly",
        "is_featured",
        "approx_cost",
        "picking_reasons",
        "notes",
    ],
    "example": {
        "name": "Thakali Set",
        "cuisine_type": "Traditional set meal",
        "description": "Traditional rice meal.",
        "spice_level": "mild",
        "meal_type": "lunch",
        "cover_image": "https://example.com/thakali-cover.jpg",
        "image_urls": "https://example.com/thakali-1.jpg",
        "image_captions": "Served plate",
        "is_vegetarian_friendly": "true",
        "is_featured": "true",
        "approx_cost": "8 USD",
        "picking_reasons": "Local favorite;Balanced meal",
        "notes": "Often served unlimited in local eateries",
    },
    "allowed_values": {
        "spice_level": [choice.value for choice in SpiceLevel],
        "meal_type": [choice.value for choice in MealType],
    },
    "notes": CHILD_BULK_TEMPLATE_NOTES,
}


class AdminDestinationBulkUploadSerializer(serializers.Serializer):
    file = serializers.FileField(write_only=True)

    destination_required_fields = (
        "destination_key",
        "name",
        "country",
        "country_code",
        "destination_type",
        "latitude",
        "longitude",
        "tagline",
        "description",
        "cover_image",
        "budget_tier",
        "currency",
        "currency_code",
    )

    child_required_fields = {
        "attractions": ("destination_key", "name", "attraction_type", "description"),
        "activities": ("destination_key", "name", "activity_type", "description", "budget_tier"),
        "cuisines": ("destination_key", "name", "description"),
    }

    def validate_file(self, upload):
        name = upload.name.lower()
        if not name.endswith((".csv", ".xlsx")):
            raise serializers.ValidationError("Upload a .csv or .xlsx file.")
        return upload

    def validate(self, attrs):
        rows_by_sheet = self._parse_upload(attrs["file"])
        destinations = self._normalize_destinations(rows_by_sheet["destinations"])
        destination_keys = {item["destination_key"] for item in destinations}
        children = {
            "attractions": self._normalize_children(rows_by_sheet.get("attractions", []), "attractions", destination_keys),
            "activities": self._normalize_children(rows_by_sheet.get("activities", []), "activities", destination_keys),
            "cuisines": self._normalize_children(rows_by_sheet.get("cuisines", []), "cuisines", destination_keys),
        }
        self._validate_existing_destinations(destinations)
        attrs["payload"] = {
            "destinations": destinations,
            **children,
        }
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        payload = validated_data["payload"]
        created = {
            "destinations": 0,
            "attractions": 0,
            "activities": 0,
            "cuisines": 0,
            "destination_images": 0,
            "attraction_images": 0,
            "activity_images": 0,
            "cuisine_images": 0,
        }
        destinations_by_key = {}

        with transaction.atomic():
            for item in payload["destinations"]:
                image_urls = item.pop("image_urls", [])
                image_captions = item.pop("image_captions", [])
                tags = item.pop("tags", [])
                destination_key = item.pop("destination_key")
                destination = Destination.objects.create(
                    **item,
                    created_by=request.user,
                    updated_by=request.user,
                )
                self._sync_tags(destination, tags, request.user)
                created["destination_images"] += self._create_images(
                    DestinationImage,
                    "destination",
                    destination,
                    image_urls,
                    image_captions,
                    request.user,
                )
                destinations_by_key[destination_key] = destination
                created["destinations"] += 1

            created["attractions"], created["attraction_images"] = self._create_children(
                Attraction,
                AttractionImage,
                "attraction",
                payload["attractions"],
                destinations_by_key,
                request.user,
            )
            created["activities"], created["activity_images"] = self._create_children(
                Activity,
                ActivityImage,
                "activity",
                payload["activities"],
                destinations_by_key,
                request.user,
            )
            created["cuisines"], created["cuisine_images"] = self._create_children(
                Cuisine,
                CuisineImage,
                "cuisine",
                payload["cuisines"],
                destinations_by_key,
                request.user,
            )

        return {
            "created": created,
            "destination_ids": [str(destination.id) for destination in destinations_by_key.values()],
        }

    def _parse_upload(self, upload):
        upload.seek(0)
        if upload.name.lower().endswith(".csv"):
            return self._parse_csv(upload)
        return self._parse_xlsx(upload)

    def _parse_csv(self, upload):
        text = upload.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise serializers.ValidationError({"file": "CSV file must include a header row."})
        rows_by_sheet = {"destinations": [], "attractions": [], "activities": [], "cuisines": []}
        type_map = {
            "destination": "destinations",
            "attraction": "attractions",
            "activity": "activities",
            "cuisine": "cuisines",
        }
        for row_number, row in enumerate(reader, start=2):
            normalized = self._normalize_row(row)
            record_type = normalized.get("record_type", "").lower()
            if not any(normalized.values()):
                continue
            sheet_name = type_map.get(record_type)
            if not sheet_name:
                raise serializers.ValidationError(
                    {"file": f"CSV row {row_number} has invalid record_type '{record_type}'."}
                )
            normalized["_row"] = row_number
            rows_by_sheet[sheet_name].append(normalized)
        return rows_by_sheet

    def _parse_xlsx(self, upload):
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise serializers.ValidationError(
                {"file": "Excel upload requires openpyxl. Install dependencies from requirements.txt."}
            ) from exc

        workbook = load_workbook(upload, read_only=True, data_only=True)
        rows_by_sheet = {}
        for sheet_name in ("destinations", "attractions", "activities", "cuisines"):
            if sheet_name not in workbook.sheetnames:
                rows_by_sheet[sheet_name] = []
                continue
            worksheet = workbook[sheet_name]
            rows = list(worksheet.iter_rows(values_only=True))
            if not rows:
                rows_by_sheet[sheet_name] = []
                continue
            headers = [self._normalize_header(value) for value in rows[0]]
            sheet_rows = []
            for row_number, values in enumerate(rows[1:], start=2):
                row = {
                    header: self._clean_cell(value)
                    for header, value in zip(headers, values)
                    if header
                }
                if not any(row.values()):
                    continue
                row["_row"] = row_number
                sheet_rows.append(row)
            rows_by_sheet[sheet_name] = sheet_rows
        return rows_by_sheet

    def _normalize_destinations(self, rows):
        if not rows:
            raise serializers.ValidationError({"destinations": "At least one destination row is required."})

        normalized = []
        seen_keys = set()
        seen_slugs = set()
        for index, row in enumerate(rows, start=1):
            self._require_fields(row, self.destination_required_fields, "destinations", index)
            destination_key = row["destination_key"]
            if destination_key in seen_keys:
                raise serializers.ValidationError({"destinations": f"Duplicate destination_key '{destination_key}'."})
            seen_keys.add(destination_key)

            country_code = row["country_code"].upper()
            slug = slugify(f"{row['name']}-{country_code}")
            if slug in seen_slugs:
                raise serializers.ValidationError(
                    {"destinations": f"Duplicate destination slug generated for '{row['name']}'."}
                )
            seen_slugs.add(slug)

            normalized.append(
                {
                    "destination_key": destination_key,
                    "name": row["name"],
                    "country": row["country"],
                    "country_code": country_code,
                    "region": row.get("region", ""),
                    "destination_type": self._choice(row["destination_type"], DestinationType, "destination_type", index),
                    "latitude": self._float(row["latitude"], "latitude", index),
                    "longitude": self._float(row["longitude"], "longitude", index),
                    "tagline": row["tagline"],
                    "description": row["description"],
                    "cover_image": row["cover_image"],
                    "image_urls": self._string_list(row.get("image_urls")),
                    "image_captions": self._string_list(row.get("image_captions")),
                    "tags": self._tags(row.get("tags"), index),
                    "min_stay_days": self._integer(row.get("min_stay_days"), "min_stay_days", index, default=2),
                    "max_stay_days": self._integer(row.get("max_stay_days"), "max_stay_days", index, default=7),
                    "budget_tier": self._choice(row["budget_tier"], BudgetTier, "budget_tier", index),
                    "difficulty_level": self._choice(row.get("difficulty_level"), DifficultyLevel, "difficulty_level", index, default=DifficultyLevel.EASY),
                    "local_languages": self._string_list(row.get("local_languages")),
                    "best_travel_months": self._month_list(row.get("best_travel_months"), index),
                    "currency": row["currency"],
                    "currency_code": row["currency_code"].upper(),
                    "getting_around": row.get("getting_around", ""),
                    "visa_notes": row.get("visa_notes", ""),
                    "notes": self._string_list(row.get("notes")),
                    "picking_reasons": self._string_list(row.get("picking_reasons")),
                    "status": self._choice(row.get("status"), Status, "status", index, default=Status.DRAFT),
                }
            )
        return normalized

    def _normalize_children(self, rows, sheet_name, destination_keys):
        normalized = []
        seen = set()
        for index, row in enumerate(rows, start=1):
            self._require_fields(row, self.child_required_fields[sheet_name], sheet_name, index)
            destination_key = row["destination_key"]
            if destination_key not in destination_keys:
                raise serializers.ValidationError(
                    {sheet_name: f"Row {index} references unknown destination_key '{destination_key}'."}
                )
            name_slug = slugify(row["name"])
            unique_key = (destination_key, name_slug)
            if unique_key in seen:
                raise serializers.ValidationError(
                    {sheet_name: f"Duplicate {sheet_name[:-1]} '{row['name']}' for destination_key '{destination_key}'."}
                )
            seen.add(unique_key)

            item = {
                "destination_key": destination_key,
                "name": row["name"],
                "description": row["description"],
                "cover_image": row.get("cover_image", ""),
                "image_urls": self._string_list(row.get("image_urls")),
                "image_captions": self._string_list(row.get("image_captions")),
            }
            if sheet_name == "attractions":
                item.update(
                    {
                        "attraction_type": self._choice(row["attraction_type"], AttractionType, "attraction_type", index),
                        "how_to_reach": row.get("how_to_reach", ""),
                        "latitude": self._optional_float(row.get("latitude"), "latitude", index),
                        "longitude": self._optional_float(row.get("longitude"), "longitude", index),
                        "address": row.get("address", ""),
                        "tags": self._tags(row.get("tags"), index),
                        "budget_tier": self._choice(row.get("budget_tier"), BudgetTier, "budget_tier", index, default=""),
                        "avg_duration_hours": self._optional_integer(row.get("avg_duration_hours"), "avg_duration_hours", index),
                        "best_time_of_day": self._choice(row.get("best_time_of_day"), BestTimeOfDay, "best_time_of_day", index, default=BestTimeOfDay.ANYTIME),
                        "picking_reasons": self._string_list(row.get("picking_reasons")),
                        "notes": self._string_list(row.get("notes")),
                        "entrance_fee_required": self._boolean(row.get("entrance_fee_required"), default=False),
                        "approx_entrance_fee": row.get("approx_entrance_fee", ""),
                        "sort_order": self._integer(row.get("sort_order"), "sort_order", index, default=0),
                        "is_featured": self._boolean(row.get("is_featured"), default=False),
                    }
                )
            elif sheet_name == "activities":
                item.update(
                    {
                        "activity_type": self._choice(row["activity_type"], ActivityType, "activity_type", index),
                        "difficulty_level": self._choice(row.get("difficulty_level"), DifficultyLevel, "difficulty_level", index, default=DifficultyLevel.EASY),
                        "budget_tier": self._choice(row["budget_tier"], BudgetTier, "budget_tier", index),
                        "approx_cost": row.get("approx_cost", ""),
                        "duration_hours": self._optional_integer(row.get("duration_hours"), "duration_hours", index),
                        "best_season": row.get("best_season", ""),
                        "picking_reasons": self._string_list(row.get("picking_reasons")),
                        "notes": self._string_list(row.get("notes")),
                        "booking_required": self._boolean(row.get("booking_required"), default=False),
                        "is_featured": self._boolean(row.get("is_featured"), default=False),
                    }
                )
            else:
                item.update(
                    {
                        "cuisine_type": row.get("cuisine_type", ""),
                        "spice_level": self._choice(row.get("spice_level"), SpiceLevel, "spice_level", index, default=SpiceLevel.MILD),
                        "meal_type": self._choice(row.get("meal_type"), MealType, "meal_type", index, default=MealType.ANY),
                        "is_vegetarian_friendly": self._boolean(row.get("is_vegetarian_friendly"), default=False),
                        "is_featured": self._boolean(row.get("is_featured"), default=False),
                        "approx_cost": row.get("approx_cost", ""),
                        "picking_reasons": self._string_list(row.get("picking_reasons")),
                        "notes": self._string_list(row.get("notes")),
                    }
                )
            normalized.append(item)
        return normalized

    def _validate_existing_destinations(self, destinations):
        slugs = [slugify(f"{item['name']}-{item['country_code']}") for item in destinations]
        existing_slugs = set(Destination.objects.filter(slug__in=slugs).values_list("slug", flat=True))
        if existing_slugs:
            raise serializers.ValidationError(
                {"destinations": f"Destination already exists for slug(s): {', '.join(sorted(existing_slugs))}."}
            )

    def _create_children(self, model, image_model, image_relation, items, destinations_by_key, user):
        child_count = 0
        image_count = 0
        for item in items:
            image_urls = item.pop("image_urls", [])
            image_captions = item.pop("image_captions", [])
            tags = item.pop("tags", [])
            destination = destinations_by_key[item.pop("destination_key")]
            child = model.objects.create(
                **item,
                destination=destination,
                created_by=user,
                updated_by=user,
            )
            if tags:
                self._sync_tags(child, tags, user)
            child_count += 1
            image_count += self._create_images(image_model, image_relation, child, image_urls, image_captions, user)
        return child_count, image_count

    def _create_images(self, model, relation_name, instance, image_urls, image_captions, user):
        for index, image_url in enumerate(image_urls):
            model.objects.create(
                **{
                    relation_name: instance,
                    "image_url": image_url,
                    "caption": image_captions[index] if index < len(image_captions) else "",
                    "sort_order": index + 1,
                    "created_by": user,
                }
            )
        return len(image_urls)

    def _sync_tags(self, destination, tags, user):
        tag_ids = []
        for item in tags:
            tag, _ = DestinationTag.objects.get_or_create(
                slug=slugify(item["name"]),
                defaults={
                    "name": item["name"],
                    "category": item["category"],
                    "created_by": user,
                    "updated_by": user,
                },
            )
            tag_ids.append(tag.pk)
        destination.tags.set(tag_ids)

    def _require_fields(self, row, fields, sheet_name, index):
        missing = [field for field in fields if not row.get(field)]
        if missing:
            raise serializers.ValidationError(
                {sheet_name: f"Row {index} is missing required field(s): {', '.join(missing)}."}
            )

    def _normalize_row(self, row):
        return {self._normalize_header(key): self._clean_cell(value) for key, value in row.items() if key}

    def _normalize_header(self, value):
        return str(value or "").strip().lower()

    def _clean_cell(self, value):
        if value is None:
            return ""
        return str(value).strip()

    def _string_list(self, value):
        if not value:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [item.strip() for item in str(value).replace(",", ";").split(";") if item.strip()]

    def _tags(self, value, index):
        tags = []
        for raw_tag in self._string_list(value):
            if ":" not in raw_tag:
                raise serializers.ValidationError(
                    {"destinations": f"Row {index} has invalid tags format. Use Name:category;Name:category."}
                )
            name, category = [part.strip() for part in raw_tag.split(":", 1)]
            tags.append(
                {
                    "name": name,
                    "category": self._choice(category, TagCategory, "tag_category", index),
                }
            )
        return tags

    def _month_list(self, value, index):
        months = []
        for item in self._string_list(value):
            month = self._integer(item, "best_travel_months", index)
            if month < 1 or month > 12:
                raise serializers.ValidationError({"best_travel_months": f"Row {index} months must be from 1 to 12."})
            months.append(month)
        return sorted(set(months))

    def _choice(self, value, choices, field_name, index, default=None):
        if value in (None, ""):
            return default.value if hasattr(default, "value") else default
        cleaned = str(value).strip().lower()
        allowed = {choice.value for choice in choices}
        if cleaned not in allowed:
            raise serializers.ValidationError(
                {field_name: f"Row {index} has invalid value '{value}'. Allowed values: {', '.join(sorted(allowed))}."}
            )
        return cleaned

    def _integer(self, value, field_name, index, default=None):
        if value in (None, ""):
            if default is not None:
                return default
            raise serializers.ValidationError({field_name: f"Row {index} requires an integer value."})
        try:
            return int(float(value))
        except (TypeError, ValueError) as exc:
            raise serializers.ValidationError({field_name: f"Row {index} requires an integer value."}) from exc

    def _optional_integer(self, value, field_name, index):
        if value in (None, ""):
            return None
        return self._integer(value, field_name, index)

    def _float(self, value, field_name, index):
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise serializers.ValidationError({field_name: f"Row {index} requires a number."}) from exc

    def _optional_float(self, value, field_name, index):
        if value in (None, ""):
            return None
        return self._float(value, field_name, index)

    def _optional_decimal(self, value, field_name, index):
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise serializers.ValidationError({field_name: f"Row {index} requires a decimal value."}) from exc

    def _boolean(self, value, *, default=False):
        if value in (None, ""):
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "y"}


class AdminDestinationChildBulkUploadSerializer(AdminDestinationBulkUploadSerializer):
    sheet_name = ""
    singular_name = ""
    model = None
    image_model = None
    image_relation = ""
    required_fields = ()

    def validate(self, attrs):
        rows = self._parse_child_upload(attrs["file"])
        attrs["payload"] = self._normalize_child_rows(rows)
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        destination = self.context["destination"]
        items = validated_data["payload"]
        created_count = 0
        image_count = 0
        created_ids = []

        with transaction.atomic():
            for item in items:
                image_urls = item.pop("image_urls", [])
                image_captions = item.pop("image_captions", [])
                tags = item.pop("tags", [])
                child = self.model.objects.create(
                    **item,
                    destination=destination,
                    created_by=request.user,
                    updated_by=request.user,
                )
                if tags:
                    self._sync_tags(child, tags, request.user)
                image_count += self._create_images(
                    self.image_model,
                    self.image_relation,
                    child,
                    image_urls,
                    image_captions,
                    request.user,
                )
                created_count += 1
                created_ids.append(str(child.id))

        return {
            "created": {
                self.sheet_name: created_count,
                f"{self.singular_name}_images": image_count,
            },
            f"{self.singular_name}_ids": created_ids,
            "destination_id": str(destination.id),
        }

    def _parse_child_upload(self, upload):
        upload.seek(0)
        if upload.name.lower().endswith(".csv"):
            return self._parse_child_csv(upload)
        return self._parse_child_xlsx(upload)

    def _parse_child_csv(self, upload):
        text = upload.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise serializers.ValidationError({"file": "CSV file must include a header row."})
        rows = []
        for row_number, row in enumerate(reader, start=2):
            normalized = self._normalize_row(row)
            if not any(normalized.values()):
                continue
            normalized["_row"] = row_number
            rows.append(normalized)
        return rows

    def _parse_child_xlsx(self, upload):
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise serializers.ValidationError(
                {"file": "Excel upload requires openpyxl. Install dependencies from requirements.txt."}
            ) from exc

        workbook = load_workbook(upload, read_only=True, data_only=True)
        worksheet = None
        for candidate in (self.sheet_name, self.sheet_name[:-1], self.sheet_name.title(), self.sheet_name[:-1].title()):
            if candidate in workbook.sheetnames:
                worksheet = workbook[candidate]
                break
        if worksheet is None:
            if workbook.sheetnames:
                worksheet = workbook[workbook.sheetnames[0]]
            else:
                return []

        rows = list(worksheet.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [self._normalize_header(value) for value in rows[0]]
        normalized_rows = []
        for row_number, values in enumerate(rows[1:], start=2):
            row = {
                header: self._clean_cell(value)
                for header, value in zip(headers, values)
                if header
            }
            if not any(row.values()):
                continue
            row["_row"] = row_number
            normalized_rows.append(row)
        return normalized_rows

    def _normalize_child_rows(self, rows):
        if not rows:
            raise serializers.ValidationError({self.sheet_name: f"At least one {self.sheet_name[:-1]} row is required."})

        destination = self.context["destination"]
        normalized = []
        seen = set()
        existing_slugs = set(
            self.model.objects.filter(destination=destination).values_list("slug", flat=True)
        )

        for index, row in enumerate(rows, start=1):
            self._require_fields(row, self.required_fields, self.sheet_name, index)
            name = row["name"]
            name_slug = slugify(name)
            if name_slug in seen:
                raise serializers.ValidationError(
                    {self.sheet_name: f"Duplicate {self.sheet_name[:-1]} '{name}' in upload payload."}
                )
            if name_slug in existing_slugs:
                raise serializers.ValidationError(
                    {self.sheet_name: f"{self.sheet_name[:-1].title()} '{name}' already exists for this destination."}
                )
            seen.add(name_slug)
            normalized.append(self._build_child_item(row, index))
        return normalized

    def _build_child_item(self, row, index):
        raise NotImplementedError


class AdminAttractionBulkUploadSerializer(AdminDestinationChildBulkUploadSerializer):
    sheet_name = "attractions"
    singular_name = "attraction"
    model = Attraction
    image_model = AttractionImage
    image_relation = "attraction"
    required_fields = ("name", "attraction_type", "description")

    def _build_child_item(self, row, index):
        return {
            "name": row["name"],
            "description": row["description"],
            "cover_image": row.get("cover_image", ""),
            "image_urls": self._string_list(row.get("image_urls")),
            "image_captions": self._string_list(row.get("image_captions")),
            "attraction_type": self._choice(row["attraction_type"], AttractionType, "attraction_type", index),
            "how_to_reach": row.get("how_to_reach", ""),
            "latitude": self._optional_float(row.get("latitude"), "latitude", index),
            "longitude": self._optional_float(row.get("longitude"), "longitude", index),
            "address": row.get("address", ""),
            "tags": self._tags(row.get("tags"), index),
            "budget_tier": self._choice(row.get("budget_tier"), BudgetTier, "budget_tier", index, default=""),
            "avg_duration_hours": self._optional_integer(row.get("avg_duration_hours"), "avg_duration_hours", index),
            "best_time_of_day": self._choice(row.get("best_time_of_day"), BestTimeOfDay, "best_time_of_day", index, default=BestTimeOfDay.ANYTIME),
            "picking_reasons": self._string_list(row.get("picking_reasons")),
            "notes": self._string_list(row.get("notes")),
            "entrance_fee_required": self._boolean(row.get("entrance_fee_required"), default=False),
            "approx_entrance_fee": row.get("approx_entrance_fee", ""),
            "sort_order": self._integer(row.get("sort_order"), "sort_order", index, default=0),
            "is_featured": self._boolean(row.get("is_featured"), default=False),
        }


class AdminActivityBulkUploadSerializer(AdminDestinationChildBulkUploadSerializer):
    sheet_name = "activities"
    singular_name = "activity"
    model = Activity
    image_model = ActivityImage
    image_relation = "activity"
    required_fields = ("name", "activity_type", "description", "budget_tier")

    def _build_child_item(self, row, index):
        return {
            "name": row["name"],
            "description": row["description"],
            "cover_image": row.get("cover_image", ""),
            "image_urls": self._string_list(row.get("image_urls")),
            "image_captions": self._string_list(row.get("image_captions")),
            "activity_type": self._choice(row["activity_type"], ActivityType, "activity_type", index),
            "difficulty_level": self._choice(row.get("difficulty_level"), DifficultyLevel, "difficulty_level", index, default=DifficultyLevel.EASY),
            "budget_tier": self._choice(row["budget_tier"], BudgetTier, "budget_tier", index),
            "approx_cost": row.get("approx_cost", ""),
            "duration_hours": self._optional_integer(row.get("duration_hours"), "duration_hours", index),
            "best_season": row.get("best_season", ""),
            "picking_reasons": self._string_list(row.get("picking_reasons")),
            "notes": self._string_list(row.get("notes")),
            "booking_required": self._boolean(row.get("booking_required"), default=False),
            "is_featured": self._boolean(row.get("is_featured"), default=False),
        }


class AdminCuisineBulkUploadSerializer(AdminDestinationChildBulkUploadSerializer):
    sheet_name = "cuisines"
    singular_name = "cuisine"
    model = Cuisine
    image_model = CuisineImage
    image_relation = "cuisine"
    required_fields = ("name", "description")

    def _build_child_item(self, row, index):
        return {
            "name": row["name"],
            "description": row["description"],
            "cover_image": row.get("cover_image", ""),
            "image_urls": self._string_list(row.get("image_urls")),
            "image_captions": self._string_list(row.get("image_captions")),
            "cuisine_type": row.get("cuisine_type", ""),
            "spice_level": self._choice(row.get("spice_level"), SpiceLevel, "spice_level", index, default=SpiceLevel.MILD),
            "meal_type": self._choice(row.get("meal_type"), MealType, "meal_type", index, default=MealType.ANY),
            "is_vegetarian_friendly": self._boolean(row.get("is_vegetarian_friendly"), default=False),
            "is_featured": self._boolean(row.get("is_featured"), default=False),
            "approx_cost": row.get("approx_cost", ""),
            "picking_reasons": self._string_list(row.get("picking_reasons")),
            "notes": self._string_list(row.get("notes")),
        }
