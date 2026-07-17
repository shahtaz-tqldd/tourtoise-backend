from datetime import timedelta
from uuid import uuid4

from django.db import transaction
from django.db.models import Max
from django.conf import settings
from django.urls import reverse
from rest_framework import serializers

from app.utils.cloudinary import cloudinary_thumbnail_url, upload_file
from accounts.services import record_completed_trip_stats
from destinations.choices import Status
from destinations.models import Destination, DestinationTag
from trips.choices import TripStatus, TripVisibility
from trips.models import (
    Trip,
    TripAgentMessage,
    TripItinerary,
    TripItineraryDay,
    TripDestination,
    TripItineraryDayItem,
    TripRoutePlanItem,
    TripHeadsUpInfoItem,
    TripNote,
    TripNoteImage,
    TripPreparation,
    TripPreparationPackingItem,
    TripRequiredDocumentItem,
)


class DestinationTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = DestinationTag
        fields = ("name", "category")
        read_only_fields = fields

class TripDestinationSummarySerializer(serializers.ModelSerializer):
    tags = DestinationTagSerializer(many=True, read_only=True)
    class Meta:
        model = Destination
        fields = ("name", "tagline", "slug", "country", "region", "destination_type", "cover_image", "tags")
        read_only_fields = fields


class TripListPrimaryDestinationSerializer(serializers.ModelSerializer):
    cover_image = serializers.SerializerMethodField()

    class Meta:
        model = Destination
        fields = ("name", "country", "region", "cover_image")
        read_only_fields = fields

    def get_cover_image(self, obj):
        return cloudinary_thumbnail_url(obj.cover_image, 800)


class TripDestinationSerializer(serializers.ModelSerializer):
    destination = TripDestinationSummarySerializer(read_only=True)
    destination_id = serializers.UUIDField(write_only=True, required=True)

    class Meta:
        model = TripDestination
        fields = (
            "id",
            "destination",
            "destination_id",
            "sort_order",
            "arrival_date",
            "departure_date",
            "stay_nights",
            "is_primary",
            "transport_from_previous",
            "notes",
        )
        read_only_fields = ("id", "stay_nights")

    def validate_destination_id(self, value):
        if not Destination.objects.filter(pk=value, status="published").exists():
            raise serializers.ValidationError("Destination not found or not available.")
        return value

    def validate_transport_from_previous(self, value):
        return value or {}

    def create(self, validated_data):
        destination = Destination.objects.get(pk=validated_data.pop("destination_id"))
        trip = self.context["trip"]
        request = self.context["request"]
        return TripDestination.objects.create(
            trip=trip,
            destination=destination,
            created_by=request.user,
            updated_by=request.user,
            **validated_data,
        )

    def update(self, instance, validated_data):
        destination_id = validated_data.pop("destination_id", None)
        if destination_id:
            instance.destination = Destination.objects.get(pk=destination_id)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.updated_by = self.context["request"].user
        instance.save()
        return instance


class TripItineraryItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = TripItineraryDayItem
        fields = (
            "id",
            "item_type",
            "title",
            "description",
            "time",
            "notes",
            "item_id",
            "estimated_cost",
        )
        read_only_fields = ("id",)

    def create(self, validated_data):
        day = self.context["day"]
        return TripItineraryDayItem.objects.create(
            trip_itinerary_day=day,
            **validated_data,
        )

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.updated_by = self.context["request"].user
        instance.save()
        return instance


class TripRoutePlanItemSerializer(serializers.ModelSerializer):
    estimated_cost = serializers.SerializerMethodField()
    estimated_duration = serializers.SerializerMethodField()

    class Meta:
        model = TripRoutePlanItem
        fields = (
            "id",
            "date",
            "notes",
            "to_point",
            "from_point",
            "start_time",
            "transport_mode",
            "estimated_cost",
            "estimated_duration",
        )
        read_only_fields = fields

    def get_estimated_cost(self, obj):
        return str(obj.estimated_cost) if obj.estimated_cost is not None else None

    def get_estimated_duration(self, obj):
        return str(obj.estimated_duration) if obj.estimated_duration else None


class TripNoteImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = TripNoteImage
        fields = ("id", "image_url", "caption", "sort_order", "created_at")
        read_only_fields = ("id", "created_at")


class TripNoteSerializer(serializers.ModelSerializer):
    images = TripNoteImageSerializer(source="trip_note_images", many=True, required=False)
    changed_orders = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = TripNote
        fields = (
            "id",
            "trip",
            "content",
            "images",
            "changed_orders",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "trip", "created_at", "updated_at")

    def validate(self, attrs):
        content = attrs.get("content", getattr(self.instance, "content", "")).strip()
        images = attrs.get("trip_note_images")
        has_existing_images = bool(self.instance and self.instance.trip_note_images.exists())

        if not content and images == []:
            raise serializers.ValidationError("A note must include content or at least one image.")

        if not content and images is None and not has_existing_images:
            raise serializers.ValidationError("A note must include content or at least one image.")

        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        trip = self.context["trip"]
        images = validated_data.pop("trip_note_images", [])

        with transaction.atomic():
            note = TripNote.objects.create(
                trip=trip,
                created_by=request.user,
                updated_by=request.user,
                **validated_data,
            )
            self._replace_images(note, images)
            return note

    def update(self, instance, validated_data):
        images = validated_data.pop("trip_note_images", None)
        changed_orders = validated_data.pop("changed_orders", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.updated_by = self.context["request"].user

        with transaction.atomic():
            instance.save()
            if images is not None:
                self._replace_images(instance, images)
            if changed_orders is not None:
                self._update_image_orders(instance, changed_orders)
            return instance

    def _replace_images(self, note, images):
        request = self.context["request"]
        note.trip_note_images.all().delete()
        TripNoteImage.objects.bulk_create(
            [
                TripNoteImage(
                    note=note,
                    image_url=image["image_url"],
                    caption=image.get("caption", ""),
                    sort_order=image.get("sort_order", index),
                    created_by=request.user,
                )
                for index, image in enumerate(images, start=1)
            ]
        )
        if hasattr(note, "_prefetched_objects_cache"):
            note._prefetched_objects_cache.pop("trip_note_images", None)

    def _update_image_orders(self, note, changed_orders):
        order_map = self._validate_changed_orders(changed_orders)
        images = list(note.trip_note_images.filter(pk__in=order_map.keys()))

        if len(images) != len(order_map):
            raise serializers.ValidationError({"changed_orders": "One or more image IDs are invalid for this note."})

        for image in images:
            image.sort_order = order_map[str(image.pk)]

        TripNoteImage.objects.bulk_update(images, ["sort_order"])
        if hasattr(note, "_prefetched_objects_cache"):
            note._prefetched_objects_cache.pop("trip_note_images", None)

    def _validate_changed_orders(self, changed_orders):
        if not isinstance(changed_orders, list):
            raise serializers.ValidationError({"changed_orders": "Expected a list of order changes."})

        order_map = {}
        seen_orders = set()
        for item in changed_orders:
            if not isinstance(item, dict):
                raise serializers.ValidationError({"changed_orders": "Each order change must be an object."})

            item_id = str(item.get("id", "")).strip()
            sort_order = item.get("sort_order")

            if not item_id or sort_order is None:
                raise serializers.ValidationError({"changed_orders": "Each item must include id and sort_order."})

            if item_id in order_map:
                raise serializers.ValidationError({"changed_orders": "Duplicate IDs are not allowed."})

            try:
                sort_order = int(sort_order)
            except (TypeError, ValueError):
                raise serializers.ValidationError({"changed_orders": "sort_order must be an integer."})

            if sort_order < 0:
                raise serializers.ValidationError({"changed_orders": "sort_order must be zero or greater."})

            if sort_order in seen_orders:
                raise serializers.ValidationError({"changed_orders": "Duplicate sort_order values are not allowed."})

            order_map[item_id] = sort_order
            seen_orders.add(sort_order)

        if not order_map:
            raise serializers.ValidationError({"changed_orders": "At least one order change is required."})

        return order_map


class PreparationItemSortOrderMixin:
    preparation_context_key = "preparation"
    sort_order_conflict_message = "Sort order already exists for this trip preparation."

    def validate_sort_order(self, value):
        preparation = self.context[self.preparation_context_key]
        queryset = self.Meta.model.objects.filter(preparation=preparation, sort_order=value)

        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise serializers.ValidationError(self.sort_order_conflict_message)

        return value

    def _set_next_sort_order(self, validated_data):
        if "sort_order" in self.initial_data:
            return

        preparation = self.context[self.preparation_context_key]
        next_sort_order = (
            self.Meta.model.objects.filter(preparation=preparation).aggregate(Max("sort_order"))["sort_order__max"]
            or 0
        ) + 1
        validated_data["sort_order"] = next_sort_order

    def create(self, validated_data):
        preparation = self.context[self.preparation_context_key]
        self._set_next_sort_order(validated_data)
        return self.Meta.model.objects.create(preparation=preparation, **validated_data)


class TripPreparationPackingItemSerializer(PreparationItemSortOrderMixin, serializers.ModelSerializer):
    class Meta:
        model = TripPreparationPackingItem
        fields = (
            "id",
            "item",
            "quantity",
            "category",
            "priority",
            "is_packed",
            "additional_notes",
        )
        read_only_fields = ("id",)


class TripHeadsUpInfoItemSerializer(PreparationItemSortOrderMixin, serializers.ModelSerializer):
    class Meta:
        model = TripHeadsUpInfoItem
        fields = (
            "id",
            "title",
            "category",
            "severity",
            "sort_order",
            "additional_note",
        )
        read_only_fields = ("id",)


class TripRequiredDocumentItemSerializer(PreparationItemSortOrderMixin, serializers.ModelSerializer):
    document = serializers.FileField(write_only=True, required=False)
    document_file_name = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = TripRequiredDocumentItem
        fields = (
            "id",
            "document_name",
            "document_file_name",
            "document",
            "document_url",
            "document_url_public_id",
            "required_level",
            "sort_order",
            "additional_note",
        )
        read_only_fields = ("id", "document_url", "document_url_public_id")

    def validate_document(self, value):
        allowed_types = {"application/pdf"}
        content_type = getattr(value, "content_type", "")
        if content_type.startswith("image/") or content_type in allowed_types:
            return value
        raise serializers.ValidationError("Only image and PDF files are allowed.")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["document"] = None
        if instance.document_url:
            data["document"] = {
                "file_name": instance.document_file_name,
                "url": instance.document_url,
                "public_id": instance.document_url_public_id,
            }
        return data

    def create(self, validated_data):
        document = validated_data.pop("document", None)
        if document:
            upload = upload_file(document, folder="trip-documents")
            validated_data["document_file_name"] = document.name
            validated_data["document_url"] = upload["url"]
            validated_data["document_url_public_id"] = upload["public_id"]
        return super().create(validated_data)

    def update(self, instance, validated_data):
        document = validated_data.pop("document", None)
        if document:
            upload = upload_file(document, folder="trip-documents")
            validated_data["document_file_name"] = document.name
            validated_data["document_url"] = upload["url"]
            validated_data["document_url_public_id"] = upload["public_id"]

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class TripDaySerializer(serializers.ModelSerializer):
    items = TripItineraryItemSerializer(source="day_items", many=True, read_only=True)

    class Meta:
        model = TripItineraryDay
        fields = (
            "id",
            "day",
            "date",
            "title",
            "summary",
            "items",
        )
        read_only_fields = ("id", "items")

    def create(self, validated_data):
        trip = self.context["trip"]
        itinerary, _ = TripItinerary.objects.get_or_create(trip=trip)
        return TripItineraryDay.objects.create(
            itinerary=itinerary,
            **validated_data,
        )

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.updated_by = self.context["request"].user
        instance.save()
        return instance


class TripListSerializer(serializers.ModelSerializer):
    primary_destination = serializers.SerializerMethodField()
    destinations_count = serializers.SerializerMethodField()
    share_url = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = (
            "id",
            "title",
            "status",
            "visibility",
            "start_date",
            "end_date",
            "nights",
            "destinations_count",
            "duration_days",
            "travelers_count",
            "traveler_type",
            "primary_destination",
            "share_url",
        )
        read_only_fields = fields

    def get_primary_destination(self, obj):
        primary = next((item for item in getattr(obj, "prefetched_trip_destinations", []) if item.is_primary), None)
        if not primary and hasattr(obj, "_prefetched_objects_cache"):
            primary = next((item for item in obj.trip_destinations.all() if item.is_primary), None)
        if not primary:
            return None
        return TripListPrimaryDestinationSerializer(primary.destination).data

    def get_destinations_count(self, obj):
        if hasattr(obj, "prefetched_trip_destinations"):
            return len(obj.prefetched_trip_destinations)
        return obj.trip_destinations.count()

    def get_share_url(self, obj):
        request = self.context.get("request")
        if obj.visibility != TripVisibility.PUBLIC or not request:
            return None
        return f"{settings.USER_FRONTEND_URL}/trip/public/{obj.share_token}"


class TripDetailSerializer(serializers.ModelSerializer):
    trip_destinations = TripDestinationSerializer(many=True, read_only=True)
    days = serializers.SerializerMethodField()
    share_url = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = (
            "id",
            "title",
            "share_token",
            "status",
            "visibility",
            "current_step",
            "start_date",
            "end_date",
            "nights",
            "duration_days",
            "travelers_count",
            "traveler_type",
            "origin_city",
            "origin_country",
            "start_location_address",
            "start_location_latitude",
            "start_location_longitude",
            "total_budget",
            "budget_currency",
            "accommodation_preference",
            "preferences",
            "planning_summary",
            "agent_active",
            "agent_active_failed_message",
            "agent_context",
            "share_url",
            "trip_destinations",
            "days",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_share_url(self, obj):
        request = self.context.get("request")
        if obj.visibility != TripVisibility.PUBLIC or not request:
            return None
        return f"{settings.USER_FRONTEND_URL}/trip/public/{obj.share_token}"

    def get_days(self, obj):
        try:
            days = obj.trip_itinerary.itinerary_days.all()
        except TripItinerary.DoesNotExist:
            return []
        return TripDaySerializer(days, many=True).data


class TripDetailsSerializer(serializers.ModelSerializer):
    trip_destinations = TripDestinationSerializer(many=True, read_only=True)
    share_url = serializers.SerializerMethodField()
    planning_title = serializers.SerializerMethodField()
    planning_description = serializers.SerializerMethodField()
    start_location = serializers.SerializerMethodField()
    budget = serializers.SerializerMethodField()
    preparation_stats = serializers.SerializerMethodField()
    session_id = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = (
            "id",
            "title",
            "planning_title",
            "planning_description",
            "status",
            "visibility",
            "current_step",
            "start_date",
            "end_date",
            "nights",
            "duration_days",
            "travelers_count",
            "traveler_type",
            "start_location",
            "budget",
            "share_url",
            "trip_destinations",
            "preparation_stats",
            "session_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_share_url(self, obj):
        request = self.context.get("request")
        if obj.visibility != TripVisibility.PUBLIC or not request:
            return None
        return f"{settings.USER_FRONTEND_URL}/trip/public/{obj.share_token}"

    def get_planning_title(self, obj):
        itinerary = self._get_itinerary(obj)
        return itinerary.title if itinerary else ""

    def get_planning_description(self, obj):
        itinerary = self._get_itinerary(obj)
        return itinerary.summary if itinerary else ""

    def get_start_location(self, obj):
        return {
            "address": obj.start_location_address,
            "city": obj.origin_city,
            "country": obj.origin_country,
            "longitude": obj.start_location_longitude,
            "latitude": obj.start_location_latitude,
        }

    def get_budget(self, obj):
        itinerary = self._get_itinerary(obj)
        if not itinerary:
            return None

        budget = getattr(itinerary, "rough_budget", None)
        if not budget:
            return None

        return {
            "currency": obj.budget_currency,
            "transport": str(budget.transport) if budget.transport is not None else None,
            "food": str(budget.food) if budget.food is not None else None,
            "activities": str(budget.activities) if budget.activities is not None else None,
            "tickets_or_entry": str(budget.tickets_or_entry) if budget.tickets_or_entry is not None else None,
            "miscellaneous": str(budget.miscellaneous) if budget.miscellaneous is not None else None,
            "total_estimated": (
                str(budget.total_estimated_budget)
                if budget.total_estimated_budget is not None
                else None
            ),
            "note": budget.budget_note
        }

    def get_preparation_stats(self, obj):
        preparation = self._get_preparation(obj)
        if not preparation:
            return {
                "packing_items": {
                    "total_count": 0,
                    "is_packed_count": 0,
                },
                "documents": {
                    "total_count": 0,
                    "uploaded_count": 0,
                },
            }

        packing_items = list(preparation.packing_items.all())
        required_documents = list(preparation.required_documents.all())
        return {
            "packing_items": {
                "total_count": len(packing_items),
                "is_packed_count": sum(1 for item in packing_items if item.is_packed),
            },
            "documents": {
                "total_count": len(required_documents),
                "uploaded_count": sum(1 for item in required_documents if item.document_url),
            },
        }
    def get_session_id(self, obj):
        preparation = self._get_preparation(obj)
        return preparation.session_id

    def _get_itinerary(self, obj):
        try:
            return obj.trip_itinerary
        except TripItinerary.DoesNotExist:
            return None

    def _get_preparation(self, obj):
        try:
            return obj.structured_preparation
        except TripPreparation.DoesNotExist:
            return None


class PublicTripDetailSerializer(serializers.ModelSerializer):
    trip_destinations = TripDestinationSerializer(many=True, read_only=True)
    days = serializers.SerializerMethodField()
    share_url = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = (
            "id",
            "title",
            "share_token",
            "status",
            "visibility",
            "planning_source",
            "current_step",
            "start_date",
            "end_date",
            "nights",
            "duration_days",
            "travelers_count",
            "traveler_type",
            "origin_city",
            "origin_country",
            "start_location_address",
            "start_location_latitude",
            "start_location_longitude",
            "total_budget",
            "budget_currency",
            "accommodation_preference",
            "planning_summary",
            "agent_active",
            "agent_active_failed_message",
            "trip_destinations",
            "days",
            "share_url",
        )
        read_only_fields = fields

    def get_share_url(self, obj):
        request = self.context.get("request")
        if not request:
            return None
        return f"{settings.USER_FRONTEND_URL}/trip/public/{obj.share_token}"

    def get_days(self, obj):
        try:
            days = obj.trip_itinerary.itinerary_days.all()
        except TripItinerary.DoesNotExist:
            return []
        return TripDaySerializer(days, many=True).data


class TripWriteSerializer(serializers.ModelSerializer):
    DATE_RANGE_OVERLAP_MESSAGE = "Between this date range there are another trip exists."

    days = serializers.IntegerField(write_only=True, min_value=1, max_value=365, required=False)
    destination_slugs = serializers.ListField(
        child=serializers.SlugField(),
        write_only=True,
        required=False,
        allow_empty=False,
    )

    class Meta:
        model = Trip
        fields = (
            "title",
            "status",
            "visibility",
            "planning_source",
            "current_step",
            "start_date",
            "end_date",
            "days",
            "duration_days",
            "travelers_count",
            "traveler_type",
            "origin_city",
            "origin_country",
            "start_location_address",
            "start_location_latitude",
            "start_location_longitude",
            "total_budget",
            "budget_currency",
            "accommodation_preference",
            "destination_slugs",
            "preferences",
            "planning_summary",
            "agent_context",
        )

    def validate(self, attrs):
        start_date = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end_date = attrs.get("end_date", getattr(self.instance, "end_date", None))
        days = attrs.pop("days", None)
        destination_slugs = attrs.get("destination_slugs")

        if days is not None:
            attrs["duration_days"] = days
            if start_date and not end_date:
                attrs["end_date"] = start_date + timedelta(days=days - 1)
                end_date = attrs["end_date"]

        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({"end_date": "end_date must be after or equal to start_date."})

        if start_date and end_date:
            self._validate_date_range_has_no_trip_overlap(start_date, end_date)

        if destination_slugs:
            duplicates = sorted({slug for slug in destination_slugs if destination_slugs.count(slug) > 1})
            if duplicates:
                raise serializers.ValidationError(
                    {"destination_slugs": f"Duplicate destination slug(s): {', '.join(duplicates)}."}
                )

            found_slugs = set(
                Destination.objects.filter(slug__in=destination_slugs, status=Status.PUBLISHED)
                .values_list("slug", flat=True)
            )
            missing_slugs = [slug for slug in destination_slugs if slug not in found_slugs]
            if missing_slugs:
                raise serializers.ValidationError(
                    {"destination_slugs": f"Destination not found or not available: {', '.join(missing_slugs)}."}
                )

        return attrs

    def _validate_date_range_has_no_trip_overlap(self, start_date, end_date):
        request = self.context["request"]
        overlapping_trips = Trip.objects.filter(
            user=request.user,
            start_date__lte=end_date,
            end_date__gte=start_date,
        )
        if self.instance:
            overlapping_trips = overlapping_trips.exclude(pk=self.instance.pk)

        if overlapping_trips.exists():
            raise serializers.ValidationError({"non_field_errors": [self.DATE_RANGE_OVERLAP_MESSAGE]})

    def create(self, validated_data):
        request = self.context["request"]
        destination_slugs = validated_data.pop("destination_slugs", [])
        validated_data["current_step"] = 2
        with transaction.atomic():
            trip = Trip.objects.create(
                user=request.user,
                created_by=request.user,
                updated_by=request.user,
                **validated_data,
            )
            self._create_trip_destinations(trip, destination_slugs)
            if trip.status == TripStatus.COMPLETED:
                record_completed_trip_stats(trip)
            return trip

    def update(self, instance, validated_data):
        validated_data.pop("destination_slugs", None)
        old_status = instance.status
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.updated_by = self.context["request"].user
        instance.save()
        if old_status != TripStatus.COMPLETED and instance.status == TripStatus.COMPLETED:
            record_completed_trip_stats(instance)
        return instance

    def _create_trip_destinations(self, trip, destination_slugs):
        if not destination_slugs:
            return

        request = self.context["request"]
        destinations_by_slug = Destination.objects.in_bulk(destination_slugs, field_name="slug")
        trip_destinations = [
            TripDestination(
                trip=trip,
                destination=destinations_by_slug[slug],
                sort_order=index,
                is_primary=index == 1,
                created_by=request.user,
                updated_by=request.user,
            )
            for index, slug in enumerate(destination_slugs, start=1)
        ]
        TripDestination.objects.bulk_create(trip_destinations)


class TripShareTokenSerializer(serializers.Serializer):
    regenerate = serializers.BooleanField(required=False, default=False)
    id = serializers.UUIDField(source="trip.id", read_only=True)
    visibility = serializers.CharField(source="trip.visibility", read_only=True)
    share_token = serializers.UUIDField(source="trip.share_token", read_only=True)
    share_url = serializers.SerializerMethodField()

    def save(self, **kwargs):
        trip = self.context["trip"]
        request = self.context["request"]

        if self.validated_data.get("regenerate"):
            trip.share_token = uuid4()
        trip.visibility = TripVisibility.PUBLIC
        trip.updated_by = request.user
        trip.save(update_fields=["share_token", "visibility", "updated_by", "updated_at"])
        self.instance = trip
        return trip

    def get_share_url(self, obj):
        trip = obj if isinstance(obj, Trip) else obj.get("trip")
        request = self.context.get("request")
        if not request or not trip:
            return None
        return f"{settings.USER_FRONTEND_URL}/trip/public/{obj.share_token}"

    def to_representation(self, instance):
        trip = instance if isinstance(instance, Trip) else self.instance
        return {
            "id": str(trip.id),
            "visibility": trip.visibility,
            "share_token": str(trip.share_token),
            "share_url": self.get_share_url(trip),
        }


class TripVisibilitySerializer(serializers.Serializer):
    visibility = serializers.ChoiceField(choices=TripVisibility.choices)
    id = serializers.UUIDField(source="trip.id", read_only=True)
    share_url = serializers.SerializerMethodField()

    def save(self, **kwargs):
        trip = self.context["trip"]
        request = self.context["request"]
        trip.visibility = self.validated_data["visibility"]
        trip.updated_by = request.user
        trip.save(update_fields=["visibility", "updated_by", "updated_at"])
        self.instance = trip
        return trip

    def get_share_url(self, obj):
        trip = obj if isinstance(obj, Trip) else obj.get("trip")
        request = self.context.get("request")
        if not request or not trip or trip.visibility != TripVisibility.PUBLIC:
            return None
        return f"{settings.USER_FRONTEND_URL}/trip/public/{obj.share_token}"

    def to_representation(self, instance):
        trip = instance if isinstance(instance, Trip) else self.instance
        return {
            "id": str(trip.id),
            "visibility": trip.visibility,
            "share_token": str(trip.share_token),
            "share_url": self.get_share_url(trip),
        }



class TripAgentActiveSerializer(serializers.Serializer):
    trip_id = serializers.UUIDField()
    let_agent_decide = serializers.BooleanField(required=False, default=True)
    travel_pace = serializers.CharField(max_length=40, allow_blank=True, required=False)
    interest_tags = serializers.ListField(
        child=serializers.CharField(max_length=80),
        required=False,
        allow_empty=True,
    )
    dietary_needs = serializers.ListField(
        child=serializers.CharField(max_length=80),
        required=False,
        allow_empty=True,
    )
    dietary_other = serializers.CharField(max_length=200, allow_blank=True, required=False)
    mobility_constraints = serializers.ListField(
        child=serializers.CharField(max_length=120),
        required=False,
        allow_empty=True,
    )
    mobility_other = serializers.CharField(max_length=200, allow_blank=True, required=False)

    def validate(self, attrs):
        attrs["interest_tags"] = self._clean_list(attrs.get("interest_tags", []))
        attrs["dietary_needs"] = self._append_other(
            attrs.get("dietary_needs", []),
            attrs.get("dietary_other", ""),
        )
        attrs["mobility_constraints"] = self._append_other(
            attrs.get("mobility_constraints", []),
            attrs.get("mobility_other", ""),
        )
        attrs["travel_pace"] = attrs.get("travel_pace", "").strip()
        return attrs

    def normalized_preferences(self):
        data = self.validated_data
        return {
            "travel_pace": data["travel_pace"],
            "interest_tags": data["interest_tags"],
            "dietary_needs": data["dietary_needs"],
            "mobility_constraints": data["mobility_constraints"],
        }

    def _append_other(self, values, other):
        cleaned = self._clean_list(values)
        other = (other or "").strip()
        if other and other not in cleaned:
            cleaned.append(other)
        return cleaned

    def _clean_list(self, values):
        cleaned = []
        for value in values or []:
            value = value.strip() if isinstance(value, str) else value
            if value and value not in cleaned:
                cleaned.append(value)
        return cleaned


class TripAgentCreateMessageSerializer(serializers.Serializer):
    trip_id = serializers.UUIDField()
    session_id = serializers.UUIDField(required=False)
    current_step = serializers.IntegerField(min_value=1, max_value=6)
    message = serializers.CharField(allow_blank=False, trim_whitespace=True)


class TripAgentMessageListQuerySerializer(serializers.Serializer):
    session_id = serializers.UUIDField()


class TripPlanningTripQuerySerializer(serializers.Serializer):
    trip_id = serializers.UUIDField()


class TripAgentMessageSerializer(serializers.ModelSerializer):
    session_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = TripAgentMessage
        fields = (
            "id",
            "session_id",
            "sender",
            "content",
            "metadata",
            "created_at",
        )
        read_only_fields = fields


class TripChatCreateMessageSerializer(serializers.Serializer):
    message = serializers.CharField(allow_blank=False, trim_whitespace=True)


class TripChatMessageSerializer(serializers.ModelSerializer):
    session_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = TripAgentMessage
        fields = (
            "id",
            "session_id",
            "sender",
            "content",
            "metadata",
            "created_at",
        )
        read_only_fields = fields


class TripChatSessionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    trip_id = serializers.UUIDField(source="trip.id", read_only=True)
    current_step = serializers.IntegerField(read_only=True)
    external_session_id = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    messages_count = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
