import json
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers

from app.utils.cloudinary import delete_image, upload_image
from destinations.models import Activity, Attraction, Cuisine, Destination, DestinationImage, DestinationTag


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


class AdminAttractionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attraction
        fields = (
            "id",
            "destination",
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
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "destination", "slug", "created_at", "updated_at")
        extra_kwargs = {
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
        validated_data["destination"] = self.context["destination"]
        validated_data["created_by"] = request.user
        validated_data["updated_by"] = request.user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data["updated_by"] = self.context["request"].user
        return super().update(instance, validated_data)

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


class AdminActivitySerializer(serializers.ModelSerializer):
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
            "cost_unit",
            "duration_hours",
            "best_season",
            "cover_image",
            "booking_required",
            "is_featured",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "destination", "slug", "created_at", "updated_at")
        extra_kwargs = {
            "cost_unit": {"required": False, "allow_blank": True},
            "best_season": {"required": False, "allow_blank": True},
            "cover_image": {"required": False, "allow_blank": True},
        }

    def validate(self, attrs):
        self._validate_unique_slug(attrs)
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["destination"] = self.context["destination"]
        validated_data["created_by"] = request.user
        validated_data["updated_by"] = request.user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data["updated_by"] = self.context["request"].user
        return super().update(instance, validated_data)

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


class AdminCuisineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cuisine
        fields = (
            "id",
            "destination",
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
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "destination", "slug", "created_at", "updated_at")
        extra_kwargs = {
            "cuisine_type": {"required": False, "allow_blank": True},
            "ingredients_note": {"required": False, "allow_blank": True},
            "cover_image": {"required": False, "allow_blank": True},
            "approx_price_range": {"required": False, "allow_blank": True},
        }

    def validate(self, attrs):
        self._validate_unique_slug(attrs)
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["destination"] = self.context["destination"]
        validated_data["created_by"] = request.user
        validated_data["updated_by"] = request.user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data["updated_by"] = self.context["request"].user
        return super().update(instance, validated_data)

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


class AdminDestinationListSerializer(serializers.ModelSerializer):
    tags = DestinationTagSerializer(many=True, read_only=True)
    images = DestinationImageSerializer(many=True, read_only=True)

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
            "cover_image",
            "budget_tier",
            "difficulty",
            "best_travel_months",
            "status",
            "data_source",
            "tags",
            "images",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class AdminDestinationDetailSerializer(serializers.ModelSerializer):
    tags = DestinationTagSerializer(many=True, read_only=True)
    images = DestinationImageSerializer(many=True, read_only=True)

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
            "status",
            "data_source",
            "images",
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
    cultural_tips = FlexibleJSONField(required=False)
    remove_image_urls = FlexibleJSONField(required=False, write_only=True)
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
            "country_code",
            "region",
            "destination_type",
            "latitude",
            "longitude",
            "tagline",
            "overview",
            "cover_image",
            "cover_image_file",
            "tags",
            "attractions",
            "activities",
            "cuisines",
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
            "status",
            "data_source",
            "gallery_images",
            "remove_image_urls",
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
        return self._validate_nested_resource(
            value,
            serializer_class=AdminAttractionSerializer,
            field_name="attractions",
        )

    def validate_activities(self, value):
        return self._validate_nested_resource(
            value,
            serializer_class=AdminActivitySerializer,
            field_name="activities",
        )

    def validate_cuisines(self, value):
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

    def validate_cultural_tips(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Send cultural_tips as a JSON array.")
        return value

    def validate_remove_image_urls(self, value):
        if value in (None, ""):
            return []
        return self._ensure_string_list(value, field_name="remove_image_urls")

    def validate(self, attrs):
        if self.instance is not None:
            nested_fields = ("attractions", "activities", "cuisines")
            nested_errors = {
                field: "Use this destination's separate admin API to manage this resource."
                for field in nested_fields
                if field in attrs
            }
            if nested_errors:
                raise serializers.ValidationError(nested_errors)

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
            self._create_nested_resources(destination, attractions_data, AdminAttractionSerializer)
            self._create_nested_resources(destination, activities_data, AdminActivitySerializer)
            self._create_nested_resources(destination, cuisines_data, AdminCuisineSerializer)
        return destination

    def update(self, instance, validated_data):
        tags_data = validated_data.pop("tags", None)
        validated_data.pop("attractions", None)
        validated_data.pop("activities", None)
        validated_data.pop("cuisines", None)
        cover_image_file = validated_data.pop("cover_image_file", serializers.empty)
        gallery_images = validated_data.pop("gallery_images", [])
        remove_image_urls = validated_data.pop("remove_image_urls", [])
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
        self._delete_gallery_images(instance, remove_image_urls)
        self._create_gallery_images(instance, gallery_images)
        return instance

    def _ensure_string_list(self, value, *, field_name):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError(f"Send {field_name} as a JSON array.")
        return [str(item).strip() for item in value if str(item).strip()]

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

        if keep_existing and destination.cover_image:
            delete_image(image_url=destination.cover_image)

        upload = upload_image(
            cover_image_file,
            folder=f"{settings.CLOUDINARY_FOLDER}/destinations/covers",
            public_id=self._build_cover_public_id(destination),
        )
        destination.cover_image = upload["url"]
        destination.save(update_fields=["cover_image", "updated_at"])

    def _create_gallery_images(self, destination, gallery_images):
        request = self.context["request"]
        existing_count = destination.images.count()
        for index, image_file in enumerate(gallery_images, start=existing_count + 1):
            upload = upload_image(
                image_file,
                folder=f"{settings.CLOUDINARY_FOLDER}/destinations/gallery",
                public_id=self._build_gallery_public_id(destination, index),
            )
            DestinationImage.objects.create(
                destination=destination,
                image_url=upload["url"],
                sort_order=index,
                created_by=request.user,
            )

    def _delete_gallery_images(self, destination, remove_image_urls):
        if not remove_image_urls:
            return
        images_to_remove = destination.images.filter(image_url__in=remove_image_urls)
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
        serializer.save()

    def _build_cover_public_id(self, destination):
        base_name = slugify(destination.name) or uuid4().hex[:8]
        return f"{base_name}-{destination.id}-cover"

    def _build_gallery_public_id(self, destination, index):
        base_name = slugify(destination.name) or uuid4().hex[:8]
        return f"{base_name}-{destination.id}-gallery-{index}"
