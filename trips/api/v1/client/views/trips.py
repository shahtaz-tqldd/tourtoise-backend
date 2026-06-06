from django.db.models import CharField, Prefetch, Q
from django.db.models.functions import Cast
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from app.utils.response import APIResponse

from trips.api.v1.client.serializers import (
    PublicTripDetailSerializer,
    TripDetailSerializer,
    TripListSerializer,
    TripWriteSerializer,
)

from trips.models import (
    Trip,
    TripItineraryDay,
    TripDestination,
    TripItineraryDayItem,
)

from .mixin import UserTripQuerysetMixin, TripPaginationMixin


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
      `total_budget`, `budget_currency`, `preferences`, 
      `planning_summary`, `agent_context`

    Frontend response:
    - 201 success with the full created trip payload.
    - `id` is the identifier used for future user update/delete/detail operations.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripWriteSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        trip = serializer.save()
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
        queryset = self.get_trip_queryset().order_by("-updated_at")
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
                agent_context_text=Cast("agent_context", CharField()),
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
            query |= Q(agent_context_text__icontains=slug)
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
        trip = self.get_trip_by_id()
        return APIResponse.success(
            data=TripDetailSerializer(trip, context={"request": request}).data,
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
        trip = serializer.save()
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


class PublicTripDetailAPIView(GenericAPIView):
    """
    Public shared trip detail API.

    Frontend request:
    - Method: GET
    - No authentication required.
    - URL param: `share_token`
    - Only trips with `visibility=link_only` are accessible through this endpoint.

    Frontend response:
    - 200 success with share-safe trip details for public viewing.
    - If the token does not exist or the trip is not shareable, the API returns 404.
    """

    def get_object(self):
        return get_object_or_404(
            Trip.objects.filter(visibility="link_only").prefetch_related(
                Prefetch(
                    "trip_destinations",
                    queryset=TripDestination.objects.select_related("destination").order_by("sort_order"),
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
            ),
            share_token=self.kwargs["share_token"],
        )

    def get(self, request, *args, **kwargs):
        trip = self.get_object()
        return APIResponse.success(
            data=PublicTripDetailSerializer(trip, context={"request": request}).data,
            message="Shared trip fetched successfully.",
        )
