from django.db.models import CharField, F, Prefetch, Q
from django.db.models.functions import Cast
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from app.base.pagination import CustomPagination
from app.utils.response import APIResponse
from trips.api.v1.client.serializers import (
    PublicTripDetailSerializer,
    TripAgentActiveSerializer,
    TripAgentCreateMessageSerializer,
    TripDaySerializer,
    TripDestinationSerializer,
    TripDetailSerializer,
    TripItineraryItemSerializer,
    TripListSerializer,
    TripPlanVersionCreateSerializer,
    TripPlanVersionSerializer,
    TripWriteSerializer,
)
from trips.models import Trip, TripDay, TripDestination, TripItineraryItem, TripPlanVersion
from trips.services import build_agent_active_response, update_user_profile_from_agent_preferences


class TripPaginationMixin:
    pagination_class = CustomPagination

    def paginate_with_meta(self, queryset, serializer_class):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        serializer = serializer_class(page, many=True, context={"request": self.request})
        return APIResponse.success(
            data=serializer.data,
            meta={
                "count": paginator.page.paginator.count,
                "page": paginator.page.number,
                "page_size": paginator.get_page_size(self.request),
                "num_pages": paginator.page.paginator.num_pages,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            },
            message="Trips fetched successfully.",
        )


class UserTripQuerysetMixin:
    def get_trip_queryset(self):
        return Trip.objects.filter(user=self.request.user).prefetch_related(
            Prefetch(
                "trip_destinations",
                queryset=TripDestination.objects.select_related("destination").order_by("sort_order"),
                to_attr="prefetched_trip_destinations",
            ),
            Prefetch(
                "days",
                queryset=TripDay.objects.prefetch_related(
                    Prefetch(
                        "items",
                        queryset=TripItineraryItem.objects.select_related(
                            "trip_destination", "attraction", "activity", "cuisine"
                        ).order_by("sort_order", "start_time"),
                    )
                ).order_by("day_number"),
            ),
        )

    def get_trip_by_id(self):
        return get_object_or_404(self.get_trip_queryset(), pk=self.kwargs["trip_id"])


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
      `travelers_count`, `trip_pace`, `origin_city`, `origin_country`,
      `total_budget`, `budget_currency`, `preferences`, `constraints`,
      `traveler_profile_snapshot`, `planning_summary`, `agent_context`

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


class TripAgentActiveAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Activate/update trip planning agent preferences for the current trip step.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripAgentActiveSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        trip = get_object_or_404(
            Trip.objects.filter(user=request.user),
            pk=serializer.validated_data["trip_id"],
        )
        normalized_payload = serializer.normalized_preferences()
        agent_response = build_agent_active_response(trip, normalized_payload)

        trip.preferences = normalized_payload
        trip.agent_active = agent_response["agent_active"]
        trip.agent_active_failed_message = agent_response["agent_active_failed_message"]
        trip.agent_message = agent_response["agent_message"]
        trip.updated_by = request.user
        trip.save(
            update_fields=[
                "preferences",
                "current_step",
                "agent_active",
                "agent_active_failed_message",
                "agent_message",
                "updated_by",
                "updated_at",
            ]
        )

        update_user_profile_from_agent_preferences(request.user, normalized_payload)

        return APIResponse.success(
            data=agent_response,
            message="Trip agent preferences updated successfully.",
        )


class TripAgentCreateMessageAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Save a trip agent message and advance the trip planning flow.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripAgentCreateMessageSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        trip = get_object_or_404(
            Trip.objects.filter(user=request.user),
            pk=serializer.validated_data["trip_id"],
        )

        if False:
            preferences = trip.preferences or {}
            agent_messages = preferences.get("agent_messages", [])
            agent_messages.append(
                {
                    "step": serializer.validated_data["current_step"],
                    "message": serializer.validated_data["message"],
                }
            )
            preferences["agent_messages"] = agent_messages

            trip.preferences = preferences
            trip.current_step = 3
            trip.updated_by = request.user
            trip.save(update_fields=["preferences", "current_step", "updated_by", "updated_at"])

            return APIResponse.success(
                data={
                    "is_step_complete": True,
                    "current_step": trip.current_step,
                },
                message="Trip agent message created successfully.",
            )
        else:
            return APIResponse.success(
                data={
                    "agent_message": "That's Really Nice, what else do you want?",
                },
                message="Trip agent message created successfully.",
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
                plan_snapshot_text=Cast("plan_versions__snapshot", CharField()),
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
            query |= Q(agent_context_text__icontains=slug) | Q(
                plan_versions__version=F("latest_plan_version"),
                plan_snapshot_text__icontains=slug,
            )
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


class TripDestinationCreateAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Add destination to trip API.

    Frontend request:
    - Method: POST
    - Headers: authenticated bearer token
    - URL param: `trip_id`
    - Content-Type: application/json
    - Body:
      `destination_id`, `sort_order`
      Optional:
      `arrival_date`, `departure_date`, `is_primary`, `transport_from_previous`, `notes`

    Frontend response:
    - 201 success with the created trip-destination row.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripDestinationSerializer

    def post(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        serializer = self.get_serializer(data=request.data, context={"request": request, "trip": trip})
        serializer.is_valid(raise_exception=True)
        trip_destination = serializer.save()
        return APIResponse.success(
            data=TripDestinationSerializer(trip_destination).data,
            message="Destination added to trip successfully.",
            status=status.HTTP_201_CREATED,
        )


class TripDestinationUpdateAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Update trip destination API.

    Frontend request:
    - Method: PATCH
    - Headers: authenticated bearer token
    - URL params: `trip_id`, `destination_row_id`
    - Content-Type: application/json
    - Send only destination-row fields that should change.

    Frontend response:
    - 200 success with the updated trip-destination row.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripDestinationSerializer

    def get_object(self):
        trip = self.get_trip_by_id()
        return get_object_or_404(TripDestination, trip=trip, pk=self.kwargs["destination_row_id"])

    def patch(self, request, *args, **kwargs):
        trip_destination = self.get_object()
        serializer = self.get_serializer(
            trip_destination,
            data=request.data,
            partial=True,
            context={"request": request, "trip": trip_destination.trip},
        )
        serializer.is_valid(raise_exception=True)
        trip_destination = serializer.save()
        return APIResponse.success(
            data=TripDestinationSerializer(trip_destination).data,
            message="Trip destination updated successfully.",
        )


class TripDestinationDeleteAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Remove destination from trip API.

    Frontend request:
    - Method: DELETE
    - Headers: authenticated bearer token
    - URL params: `trip_id`, `destination_row_id`
    - No request body is required.

    Frontend response:
    - 200 success with no data payload.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        trip_destination = get_object_or_404(TripDestination, trip=trip, pk=self.kwargs["destination_row_id"])
        trip_destination.delete()
        return APIResponse.success(message="Trip destination removed successfully.")


class TripDayCreateAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Create trip day API.

    Frontend request:
    - Method: POST
    - Headers: authenticated bearer token
    - URL param: `trip_id`
    - Content-Type: application/json
    - Body:
      `day_number`
      Optional:
      `trip_destination`, `date`, `title`, `summary`, `notes`

    Frontend response:
    - 201 success with the created trip day and its current items.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripDaySerializer

    def post(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        serializer = self.get_serializer(data=request.data, context={"request": request, "trip": trip})
        serializer.is_valid(raise_exception=True)
        day = serializer.save()
        return APIResponse.success(
            data=TripDaySerializer(day).data,
            message="Trip day created successfully.",
            status=status.HTTP_201_CREATED,
        )


class TripDayUpdateAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Update trip day API.

    Frontend request:
    - Method: PATCH
    - Headers: authenticated bearer token
    - URL params: `trip_id`, `day_id`
    - Content-Type: application/json
    - Send only day fields that should change.

    Frontend response:
    - 200 success with the updated day payload.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripDaySerializer

    def get_object(self):
        trip = self.get_trip_by_id()
        return get_object_or_404(TripDay, trip=trip, pk=self.kwargs["day_id"])

    def patch(self, request, *args, **kwargs):
        day = self.get_object()
        serializer = self.get_serializer(day, data=request.data, partial=True, context={"request": request, "trip": day.trip})
        serializer.is_valid(raise_exception=True)
        day = serializer.save()
        return APIResponse.success(
            data=TripDaySerializer(day).data,
            message="Trip day updated successfully.",
        )


class TripDayDeleteAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Delete trip day API.

    Frontend request:
    - Method: DELETE
    - Headers: authenticated bearer token
    - URL params: `trip_id`, `day_id`
    - No request body is required.

    Frontend response:
    - 200 success with no data payload.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        day = get_object_or_404(TripDay, trip=trip, pk=self.kwargs["day_id"])
        day.delete()
        return APIResponse.success(message="Trip day deleted successfully.")


class TripItineraryItemCreateAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Create itinerary item API.

    Frontend request:
    - Method: POST
    - Headers: authenticated bearer token
    - URL params: `trip_id`, `day_id`
    - Content-Type: application/json
    - Body:
      `title`, `item_type`, `sort_order`
      Optional:
      `status`, `description`, `trip_destination`, `start_time`, `end_time`,
      `duration_minutes`, `attraction`, `activity`, `cuisine`,
      `location_name`, `address`, `latitude`, `longitude`,
      `estimated_cost`, `cost_currency`, `booking_required`,
      `booking_reference`, `external_url`, `metadata`

    Frontend response:
    - 201 success with the created itinerary item.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripItineraryItemSerializer

    def post(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        day = get_object_or_404(TripDay, trip=trip, pk=self.kwargs["day_id"])
        serializer = self.get_serializer(
            data=request.data,
            context={"request": request, "trip": trip, "day": day},
        )
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        return APIResponse.success(
            data=TripItineraryItemSerializer(item).data,
            message="Itinerary item created successfully.",
            status=status.HTTP_201_CREATED,
        )


class TripItineraryItemUpdateAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Update itinerary item API.

    Frontend request:
    - Method: PATCH
    - Headers: authenticated bearer token
    - URL params: `trip_id`, `item_id`
    - Content-Type: application/json
    - Send only itinerary item fields that should change.

    Frontend response:
    - 200 success with the updated itinerary item.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripItineraryItemSerializer

    def get_object(self):
        trip = self.get_trip_by_id()
        return get_object_or_404(TripItineraryItem, trip=trip, pk=self.kwargs["item_id"])

    def patch(self, request, *args, **kwargs):
        item = self.get_object()
        serializer = self.get_serializer(
            item,
            data=request.data,
            partial=True,
            context={"request": request, "trip": item.trip, "day": item.day},
        )
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        return APIResponse.success(
            data=TripItineraryItemSerializer(item).data,
            message="Itinerary item updated successfully.",
        )


class TripItineraryItemDeleteAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Delete itinerary item API.

    Frontend request:
    - Method: DELETE
    - Headers: authenticated bearer token
    - URL params: `trip_id`, `item_id`
    - No request body is required.

    Frontend response:
    - 200 success with no data payload.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        item = get_object_or_404(TripItineraryItem, trip=trip, pk=self.kwargs["item_id"])
        item.delete()
        return APIResponse.success(message="Itinerary item deleted successfully.")


class TripPlanVersionListAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Trip plan version list API.

    Frontend request:
    - Method: GET
    - Headers: authenticated bearer token
    - URL param: `trip_id`

    Frontend response:
    - 200 success with saved plan versions for the trip.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        versions = trip.plan_versions.all().order_by("-version")
        return APIResponse.success(
            data=TripPlanVersionSerializer(versions, many=True).data,
            message="Trip plan versions fetched successfully.",
        )


class TripPlanVersionCreateAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Save trip plan version API.

    Frontend request:
    - Method: POST
    - Headers: authenticated bearer token
    - URL param: `trip_id`
    - Content-Type: application/json
    - Body:
      Optional:
      `summary`, `source`, `snapshot`
    - If `snapshot` is omitted, frontend should first fetch trip detail and send the structure it wants persisted.

    Frontend response:
    - 201 success with the saved plan version row.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripPlanVersionCreateSerializer

    def post(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        next_version = (trip.plan_versions.order_by("-version").first().version + 1) if trip.plan_versions.exists() else 1
        payload = serializer.validated_data
        plan_version = TripPlanVersion.objects.create(
            trip=trip,
            version=next_version,
            summary=payload.get("summary", ""),
            source=payload.get("source"),
            snapshot=payload.get("snapshot", {}),
            created_by=request.user,
            updated_by=request.user,
        )
        trip.latest_plan_version = next_version
        trip.updated_by = request.user
        trip.save(update_fields=["latest_plan_version", "updated_by", "updated_at"])

        return APIResponse.success(
            data=TripPlanVersionSerializer(plan_version).data,
            message="Trip plan version saved successfully.",
            status=status.HTTP_201_CREATED,
        )


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
                    "days",
                    queryset=TripDay.objects.prefetch_related(
                        Prefetch(
                            "items",
                            queryset=TripItineraryItem.objects.select_related(
                                "trip_destination", "attraction", "activity", "cuisine"
                            ).order_by("sort_order", "start_time"),
                        )
                    ).order_by("day_number"),
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
