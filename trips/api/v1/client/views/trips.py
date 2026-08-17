from django.db import transaction
from django.db.models import (
    Case,
    CharField,
    Count,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Cast, Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated

from app.utils.response import APIResponse
from accounts.services.user_profile import ensure_user_profile
from notification.models import Notification, NotificationType

from trips.api.v1.client.serializers import (
    PublicTripDetailSerializer,
    TripDetailSerializer,
    TripShortDetailsSerializer,
    TripDetailsSerializer,
    TripListSerializer,
    TripShareTokenSerializer,
    TripVisibilitySerializer,
    TripWriteSerializer,
)
from trips.choices import AgentMessageSender, TripStatus, TripVisibility

from trips.models import (
    Trip,
    TripItineraryDay,
    TripDestination,
    TripItineraryDayItem,
    TripConversationMessage,
    TripHeadsUpInfoItem,
    TripPreparationPackingItem,
    TripRequiredDocumentItem,
    TripRoutePlanItem,
)
from trips.services.notifications import schedule_trip_notifications

from .mixin import UserTripQuerysetMixin, TripPaginationMixin


def update_user_profile_from_trip_data(user, validated_data):
    profile_updates = {}
    if "start_location_address" in validated_data:
        profile_updates["last_tracked_address"] = validated_data["start_location_address"]
    if "accommodation_preference" in validated_data:
        profile_updates["preferred_accommodation"] = validated_data["accommodation_preference"]

    if not profile_updates:
        return

    profile = ensure_user_profile(user)
    for field, value in profile_updates.items():
        setattr(profile, field, value)
    profile.save(update_fields=list(profile_updates))


def annotate_unread_counts(queryset, user):
    unread_notifications = (
        Notification.objects.filter(
            trip_id=OuterRef("pk"),
            recipient=user,
            notification_type=NotificationType.TRIP,
        )
        .exclude(read_receipts__user=user)
        .values("trip_id")
        .annotate(total=Count("pk"))
        .values("total")[:1]
    )
    unread_messages = (
        TripConversationMessage.objects.filter(
            session__trip_id=OuterRef("pk"),
            session__user=user,
            sender=AgentMessageSender.AGENT,
            read_at__isnull=True,
        )
        .values("session__trip_id")
        .annotate(total=Count("pk"))
        .values("total")[:1]
    )
    return queryset.annotate(
        unread_notification=Coalesce(
            Subquery(unread_notifications, output_field=IntegerField()),
            Value(0),
        ),
        unread_message=Coalesce(
            Subquery(unread_messages, output_field=IntegerField()),
            Value(0),
        ),
    )


class TripCreateAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Create trip API.

    Frontend request:
    - Method: POST
    - Headers: authenticated bearer token
    - Content-Type: application/json
    - Body:
      `title`
      Optional:
      `status`, `visibility`, `planning_source`, `start_date`, `end_date`,
      `travelers_count`, `origin_city`, `origin_country`,
      `budget_tier`, `budget_currency`, `preferences`,
      `planning_summary`, `metadata`

    Frontend response:
    - 201 success with the full created trip payload.
    - `id` is the identifier used for future user update/delete/detail operations.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripWriteSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        profile_data = {
            field: serializer.validated_data[field]
            for field in ("start_location_address", "accommodation_preference")
            if field in serializer.validated_data
        }
        with transaction.atomic():
            trip = serializer.save()
            update_user_profile_from_trip_data(request.user, profile_data)
        if trip.status in {TripStatus.READY, TripStatus.IN_PROGRESS}:
            schedule_trip_notifications(trip, request.user)
        trip = self.get_trip_queryset().get(pk=trip.pk)
        return APIResponse.success(
            data=TripDetailSerializer(trip, context={"request": request}).data,
            message="Trip created successfully.",
            status=status.HTTP_201_CREATED,
        )


class TripListAPIView(TripPaginationMixin, UserTripQuerysetMixin, GenericAPIView):
    """
    User trip list API.

    Frontend request:
    - Method: GET
    - Headers: authenticated bearer token
    - Query params:
      `page`, `page_size`
      `search=winter`
      `status=draft,ready`
      `planning_source=agent,hybrid`
      `destination=tokyo`
      `destination_slug=tokyo`
      `start_date_from=2026-12-01`
      `start_date_to=2026-12-31`
    - Multiple filters can be combined.

    Frontend response:
    - 200 success with paginated trip rows.
    - Each row includes `id` for future authenticated trip operations.
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        today = timezone.localdate()
        queryset = annotate_unread_counts(
            self.get_trip_queryset(),
            self.request.user,
        ).annotate(
            start_date_sort_group=Case(
                When(start_date__gte=today, then=Value(0)),
                When(start_date__isnull=True, then=Value(2)),
                default=Value(1),
                output_field=IntegerField(),
            ),
        ).order_by("start_date_sort_group", "start_date", "-updated_at")
        params = self.request.query_params

        search = params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(trip_destinations__destination__name__icontains=search)
            )

        statuses = self._get_multi_values("status")
        if statuses:
            queryset = queryset.filter(status__in=statuses)

        planning_sources = self._get_multi_values("planning_source")
        if planning_sources:
            queryset = queryset.filter(planning_source__in=planning_sources)

        destination_slugs = self._get_multi_values("destination") + self._get_multi_values(
            "destination_slug"
        )
        if destination_slugs:
            queryset = queryset.annotate(
                metadata_text=Cast("metadata", CharField()),
            ).filter(self._build_destination_slug_query(destination_slugs))

        start_date_from = params.get("start_date_from")
        if start_date_from:
            queryset = queryset.filter(start_date__gte=start_date_from)

        start_date_to = params.get("start_date_to")
        if start_date_to:
            queryset = queryset.filter(start_date__lte=start_date_to)

        return queryset.distinct()

    def get(self, request, *args, **kwargs):
        return self.paginate_with_meta(self.get_queryset(), TripListSerializer)

    def _get_multi_values(self, key):
        values = []
        for item in self.request.query_params.getlist(key):
            values.extend([part.strip() for part in str(item).split(",") if part.strip()])
        return values

    def _build_destination_slug_query(self, destination_slugs):
        query = Q(trip_destinations__destination__slug__in=destination_slugs)
        for slug in destination_slugs:
            query |= Q(metadata_text__icontains=slug)
        return query


class TripDetailAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    User trip detail API.

    Frontend request:
    - Method: GET
    - Headers: authenticated bearer token
    - URL param: `trip_id`

    Frontend response:
    - 200 success with the full trip payload including destinations, days, and itinerary items.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        trip = get_object_or_404(
            annotate_unread_counts(self.get_trip_queryset(), request.user),
            pk=self.kwargs["trip_id"],
        )
        return APIResponse.success(
            data=TripDetailsSerializer(trip, context={"request": request}).data,
            message="Trip fetched successfully.",
        )

class TripShortDetailsAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    User trip detail API.

    Frontend request:
    - Method: GET
    - Headers: authenticated bearer token
    - URL param: `trip_id`

    Frontend response:
    - 200 success with the full trip payload including destinations, days, and itinerary items.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        return APIResponse.success(
            data=TripShortDetailsSerializer(trip, context={"request": request}).data,
            message="Trip fetched successfully.",
        )


class TripUpdateAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Update trip API.

    Frontend request:
    - Method: PATCH
    - Headers: authenticated bearer token
    - URL param: `trip_id`
    - Content-Type: application/json
    - Send only the trip fields that should change.

    Frontend response:
    - 200 success with the updated full trip payload.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripWriteSerializer

    def patch(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        serializer = self.get_serializer(trip, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        profile_data = {
            field: serializer.validated_data[field]
            for field in ("start_location_address", "accommodation_preference")
            if field in serializer.validated_data
        }
        with transaction.atomic():
            trip = serializer.save()
            update_user_profile_from_trip_data(request.user, profile_data)
        if trip.status in {TripStatus.READY, TripStatus.IN_PROGRESS}:
            schedule_trip_notifications(trip, request.user)
        trip = self.get_trip_queryset().get(pk=trip.pk)
        return APIResponse.success(
            data=TripDetailSerializer(trip, context={"request": request}).data,
            message="Trip updated successfully.",
        )


class TripDeleteAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Delete trip API.

    Frontend request:
    - Method: DELETE
    - Headers: authenticated bearer token
    - URL param: `trip_id`
    - No request body is required.

    Frontend response:
    - 200 success with no data payload.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        trip.delete()
        return APIResponse.success(message="Trip deleted successfully.")


class TripShareTokenAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Create or fetch a shareable trip token and link.

    Frontend request:
    - Method: POST
    - Headers: authenticated bearer token
    - URL param: `trip_id`
    - Optional body: `{ "regenerate": true }` to rotate the token.

    Frontend response:
    - 200 success with `share_token`, `share_url`, and `visibility=public`.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripShareTokenSerializer

    def post(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        serializer = self.get_serializer(
            data=request.data,
            context={"request": request, "trip": trip},
        )
        serializer.is_valid(raise_exception=True)
        trip = serializer.save()
        return APIResponse.success(
            data=TripShareTokenSerializer(trip, context={"request": request}).data,
            message="Trip share link created successfully.",
        )


class TripVisibilityUpdateAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Change trip visibility.

    Frontend request:
    - Method: PATCH
    - Headers: authenticated bearer token
    - URL param: `trip_id`
    - Body: `{ "visibility": "public" }` or `{ "visibility": "private" }`

    Frontend response:
    - 200 success with current visibility and share link when public.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripVisibilitySerializer

    def patch(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        serializer = self.get_serializer(
            data=request.data,
            context={"request": request, "trip": trip},
        )
        serializer.is_valid(raise_exception=True)
        trip = serializer.save()
        return APIResponse.success(
            data=TripVisibilitySerializer(trip, context={"request": request}).data,
            message="Trip visibility updated successfully.",
        )


class PublicTripDetailAPIView(GenericAPIView):
    """
    Public shared trip detail API.

    Frontend request:
    - Method: GET
    - No authentication required.
    - URL param: `share_token`
    - Only trips with `visibility=public` are accessible through this endpoint.

    Frontend response:
    - 200 success with share-safe trip details for public viewing.
    - If the token does not exist or the trip is not shareable, the API returns 404.
    """

    permission_classes = [AllowAny]
    serializer_class = PublicTripDetailSerializer

    def get_object(self):
        return get_object_or_404(
            Trip.objects.filter(visibility=TripVisibility.PUBLIC).select_related(
                "trip_itinerary__rough_budget"
            ).prefetch_related(
                Prefetch(
                    "trip_destinations",
                    queryset=TripDestination.objects.select_related(
                        "destination"
                    ).prefetch_related("destination__tags").order_by("sort_order"),
                ),
                Prefetch(
                    "trip_itinerary__itinerary_days",
                    queryset=TripItineraryDay.objects.prefetch_related(
                        Prefetch(
                            "day_items",
                            queryset=TripItineraryDayItem.objects.order_by("time"),
                        )
                    ).order_by("day"),
                ),
                Prefetch(
                    "trip_itinerary__route_plan_items",
                    queryset=TripRoutePlanItem.objects.order_by("date", "start_time"),
                ),
                Prefetch(
                    "structured_preparation__packing_items",
                    queryset=TripPreparationPackingItem.objects.order_by("sort_order"),
                ),
                Prefetch(
                    "structured_preparation__required_documents",
                    queryset=TripRequiredDocumentItem.objects.order_by("sort_order"),
                ),
                Prefetch(
                    "structured_preparation__heads_up",
                    queryset=TripHeadsUpInfoItem.objects.order_by("sort_order"),
                ),
            ),
            share_token=self.kwargs["share_token"],
        )

    def get(self, request, *args, **kwargs):
        trip = self.get_object()
        return APIResponse.success(
            data=self.get_serializer(trip).data,
            message="Shared trip fetched successfully.",
        )
