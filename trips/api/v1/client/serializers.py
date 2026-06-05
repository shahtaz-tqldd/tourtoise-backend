from datetime import timedelta

from django.db import transaction
from django.urls import reverse
from rest_framework import serializers

from destinations.api.v1.client.serializers import ClientDestinationListSerializer
from destinations.choices import Status
from destinations.models import Activity, Attraction, Cuisine, Destination
from trips.choices import PlanningSource
from trips.models import Trip, TripAgentMessage, TripDay, TripDestination, TripItineraryItem, TripPlanVersion


class TripDestinationSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Destination
        fields = ("name", "slug", "country", "country_code", "destination_type", "cover_image")
        read_only_fields = fields


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
    attraction_name = serializers.CharField(source="attraction.name", read_only=True)
    activity_name = serializers.CharField(source="activity.name", read_only=True)
    cuisine_name = serializers.CharField(source="cuisine.name", read_only=True)

    class Meta:
        model = TripItineraryItem
        fields = (
            "id",
            "trip_destination",
            "item_type",
            "status",
            "title",
            "description",
            "start_time",
            "end_time",
            "duration_minutes",
            "sort_order",
            "attraction",
            "activity",
            "cuisine",
            "attraction_name",
            "activity_name",
            "cuisine_name",
            "location_name",
            "address",
            "latitude",
            "longitude",
            "estimated_cost",
            "cost_currency",
            "booking_required",
            "booking_reference",
            "external_url",
            "metadata",
        )
        read_only_fields = ("id", "attraction_name", "activity_name", "cuisine_name")

    def validate(self, attrs):
        trip = self.context["trip"]
        trip_destination = attrs.get("trip_destination") or getattr(self.instance, "trip_destination", None)
        if trip_destination and trip_destination.trip_id != trip.id:
            raise serializers.ValidationError({"trip_destination": "Trip destination does not belong to this trip."})
        if attrs.get("attraction") and attrs.get("activity"):
            raise serializers.ValidationError("Select only one structured content reference per item.")
        if attrs.get("attraction") and attrs.get("cuisine"):
            raise serializers.ValidationError("Select only one structured content reference per item.")
        if attrs.get("activity") and attrs.get("cuisine"):
            raise serializers.ValidationError("Select only one structured content reference per item.")
        return attrs

    def create(self, validated_data):
        day = self.context["day"]
        trip = self.context["trip"]
        request = self.context["request"]
        return TripItineraryItem.objects.create(
            trip=trip,
            day=day,
            created_by=request.user,
            updated_by=request.user,
            **validated_data,
        )

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.updated_by = self.context["request"].user
        instance.save()
        return instance


class TripDaySerializer(serializers.ModelSerializer):
    items = TripItineraryItemSerializer(many=True, read_only=True)

    class Meta:
        model = TripDay
        fields = (
            "id",
            "trip_destination",
            "day_number",
            "date",
            "title",
            "summary",
            "notes",
            "items",
        )
        read_only_fields = ("id", "items")

    def validate(self, attrs):
        trip = self.context["trip"]
        trip_destination = attrs.get("trip_destination") or getattr(self.instance, "trip_destination", None)
        if trip_destination and trip_destination.trip_id != trip.id:
            raise serializers.ValidationError({"trip_destination": "Trip destination does not belong to this trip."})
        return attrs

    def create(self, validated_data):
        trip = self.context["trip"]
        request = self.context["request"]
        return TripDay.objects.create(
            trip=trip,
            created_by=request.user,
            updated_by=request.user,
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
    days_count = serializers.SerializerMethodField()
    share_url = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = (
            "id",
            "title",
            "status",
            "planning_source",
            "visibility",
            "current_step",
            "start_date",
            "end_date",
            "nights",
            "duration_days",
            "travelers_count",
            "traveler_type",
            "trip_pace",
            "total_budget",
            "budget_currency",
            "accommodation_preference",
            "primary_destination",
            "destinations_count",
            "days_count",
            "share_url",
            "updated_at",
        )
        read_only_fields = fields

    def get_primary_destination(self, obj):
        primary = next((item for item in getattr(obj, "prefetched_trip_destinations", []) if item.is_primary), None)
        if not primary and hasattr(obj, "_prefetched_objects_cache"):
            primary = next((item for item in obj.trip_destinations.all() if item.is_primary), None)
        if not primary:
            return None
        return ClientDestinationListSerializer(primary.destination).data

    def get_destinations_count(self, obj):
        if hasattr(obj, "prefetched_trip_destinations"):
            return len(obj.prefetched_trip_destinations)
        return obj.trip_destinations.count()

    def get_days_count(self, obj):
        if hasattr(obj, "_prefetched_objects_cache") and "days" in obj._prefetched_objects_cache:
            return len(obj._prefetched_objects_cache["days"])
        return obj.days.count()

    def get_share_url(self, obj):
        request = self.context.get("request")
        if obj.visibility != "link_only" or not request:
            return None
        return request.build_absolute_uri(
            reverse("public-trip-detail", kwargs={"share_token": obj.share_token})
        )


class TripDetailSerializer(serializers.ModelSerializer):
    trip_destinations = TripDestinationSerializer(many=True, read_only=True)
    days = TripDaySerializer(many=True, read_only=True)
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
            "trip_pace",
            "origin_city",
            "origin_country",
            "start_location_address",
            "start_location_latitude",
            "start_location_longitude",
            "total_budget",
            "budget_currency",
            "accommodation_preference",
            "preferences",
            "constraints",
            "traveler_profile_snapshot",
            "planning_summary",
            "agent_active",
            "agent_active_failed_message",
            "agent_message",
            "agent_context",
            "latest_plan_version",
            "share_url",
            "trip_destinations",
            "days",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_share_url(self, obj):
        request = self.context.get("request")
        if obj.visibility != "link_only" or not request:
            return None
        return request.build_absolute_uri(
            reverse("public-trip-detail", kwargs={"share_token": obj.share_token})
        )


class PublicTripDetailSerializer(serializers.ModelSerializer):
    trip_destinations = TripDestinationSerializer(many=True, read_only=True)
    days = TripDaySerializer(many=True, read_only=True)
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
            "trip_pace",
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
            "agent_message",
            "trip_destinations",
            "days",
            "share_url",
        )
        read_only_fields = fields

    def get_share_url(self, obj):
        request = self.context.get("request")
        if not request:
            return None
        return request.build_absolute_uri(
            reverse("public-trip-detail", kwargs={"share_token": obj.share_token})
        )


class TripWriteSerializer(serializers.ModelSerializer):
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
            "trip_pace",
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
            "constraints",
            "traveler_profile_snapshot",
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

    def create(self, validated_data):
        request = self.context["request"]
        destination_slugs = validated_data.pop("destination_slugs", [])
        validated_data["current_step"] = 2
        validated_data.setdefault("traveler_profile_snapshot", self._build_traveler_snapshot(request.user))
        with transaction.atomic():
            trip = Trip.objects.create(
                user=request.user,
                created_by=request.user,
                updated_by=request.user,
                **validated_data,
            )
            self._create_trip_destinations(trip, destination_slugs)
            return trip

    def update(self, instance, validated_data):
        validated_data.pop("destination_slugs", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.updated_by = self.context["request"].user
        instance.save()
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

    def _build_traveler_snapshot(self, user):
        profile = getattr(user, "profile", None)
        if not profile:
            return {}
        return {
            "travel_interests": profile.travel_interests,
            "dietary_preferences": profile.dietary_preferences,
            "travel_pace": profile.travel_pace,
            "mobility_constraints": profile.mobility_constraints,
            "preferred_language": profile.preferred_language,
            "preferred_currency": profile.preferred_currency,
            "country_of_residence": profile.country_of_residence,
            "city": profile.city,
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
    trip_id = serializers.UUIDField()
    step = serializers.IntegerField(min_value=1, max_value=6, required=False)


class TripAgentMessageSerializer(serializers.ModelSerializer):
    session_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = TripAgentMessage
        fields = (
            "id",
            "session_id",
            "sender",
            "step",
            "sequence",
            "content",
            "created_at",
        )
        read_only_fields = fields


class TripPlanVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TripPlanVersion
        fields = ("id", "version", "summary", "source", "snapshot", "created_at")
        read_only_fields = ("id", "version", "created_at")


class TripPlanVersionCreateSerializer(serializers.Serializer):
    summary = serializers.CharField(required=False, allow_blank=True)
    source = serializers.ChoiceField(choices=PlanningSource.choices, required=False, default=PlanningSource.AGENT)
    snapshot = serializers.JSONField(required=False)
