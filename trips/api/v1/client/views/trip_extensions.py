from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from app.utils.response import APIResponse
from trips.choices import PlanningStep, TripStatus
from trips.services.services import invalidate_trip_planning

from trips.api.v1.client.serializers import (
    TripDaySerializer,
    TripDestinationSerializer,
    TripItineraryItemSerializer,
    TripRoutePlanItemSerializer,
)

from trips.models import (
    TripItineraryDay,
    TripDestination,
    TripItineraryDayItem,
    TripItinerary,
)

from .mixin import UserTripQuerysetMixin


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
        invalidate_trip_planning(
            trip,
            PlanningStep.RECOMMENDATION,
            user=request.user,
        )
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
    - URL params: `trip_id`, `destination_id`
    - Content-Type: application/json
    - Send only destination-row fields that should change.

    Frontend response:
    - 200 success with the updated trip-destination row.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripDestinationSerializer

    def get_object(self):
        trip = self.get_trip_by_id()
        return get_object_or_404(TripDestination, trip=trip, pk=self.kwargs["destination_id"])

    def patch(self, request, *args, **kwargs):
        trip_destination = self.get_object()
        serializer = self.get_serializer(
            trip_destination,
            data=request.data,
            partial=True,
            context={"request": request, "trip": trip_destination.trip},
        )
        serializer.is_valid(raise_exception=True)
        planning_inputs_changed = any(
            getattr(trip_destination, field) != value
            for field, value in serializer.validated_data.items()
        )
        trip_destination = serializer.save()
        if planning_inputs_changed:
            invalidate_trip_planning(
                trip_destination.trip,
                PlanningStep.RECOMMENDATION,
                user=request.user,
            )
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
    - URL params: `trip_id`, `destination_id`
    - No request body is required.

    Frontend response:
    - 200 success with no data payload.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        trip_destination = get_object_or_404(TripDestination, trip=trip, pk=self.kwargs["destination_id"])
        trip_destination.delete()
        invalidate_trip_planning(
            trip,
            PlanningStep.RECOMMENDATION,
            user=request.user,
        )
        return APIResponse.success(message="Trip destination removed successfully.")


class TripRoutePlanListAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    List route plan items for a trip.

    Frontend request:
    - Method: GET
    - Headers: authenticated bearer token
    - URL param: `trip_id`

    Frontend response:
    - 200 success with route plan items ordered by date and start time.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripRoutePlanItemSerializer

    def get(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        try:
            route_plan_items = trip.trip_itinerary.route_plan_items.all()
        except TripItinerary.DoesNotExist:
            route_plan_items = []

        return APIResponse.success(
            data=self.get_serializer(route_plan_items, many=True).data,
            message="Trip route plan fetched successfully.",
        )


class TripDayWisePlanListAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    List day-wise plan for a trip.

    Frontend request:
    - Method: GET
    - Headers: authenticated bearer token
    - URL param: `trip_id`

    Frontend response:
    - 200 success with itinerary days and their items.
    - In-progress trips start with the current day in the user's timezone,
      followed by upcoming days and then completed days.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripDaySerializer

    def get_trip_local_date(self, trip):
        timezone_name = getattr(trip.user.profile, "timezone", "UTC")
        try:
            trip_timezone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            trip_timezone = ZoneInfo("UTC")
        return timezone.localdate(timezone=trip_timezone)

    @staticmethod
    def sort_days_from_current_date(days, current_date):
        return sorted(
            days,
            key=lambda day: (
                day.date is None,
                bool(day.date and day.date < current_date),
                day.date or current_date,
                day.day,
            ),
        )

    def get(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        try:
            days = trip.trip_itinerary.itinerary_days.prefetch_related("day_items").all()
        except TripItinerary.DoesNotExist:
            days = []

        if trip.status == TripStatus.IN_PROGRESS:
            current_date = self.get_trip_local_date(trip)
            days = self.sort_days_from_current_date(list(days), current_date)
            data = self.get_serializer(days, many=True).data
            for day, serialized_day in zip(days, data):
                serialized_day["is_complete"] = bool(
                    day.date and day.date < current_date
                )
        else:
            data = self.get_serializer(days, many=True).data

        return APIResponse.success(
            data=data,
            message="Trip day-wise plan fetched successfully.",
        )


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
        invalidate_trip_planning(
            trip,
            PlanningStep.PREPARATION,
            user=request.user,
        )
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
        return get_object_or_404(TripItineraryDay, itinerary__trip=trip, pk=self.kwargs["day_id"])

    def patch(self, request, *args, **kwargs):
        day = self.get_object()
        serializer = self.get_serializer(
            day,
            data=request.data,
            partial=True,
            context={"request": request, "trip": day.itinerary.trip},
        )
        serializer.is_valid(raise_exception=True)
        day = serializer.save()
        invalidate_trip_planning(
            day.itinerary.trip,
            PlanningStep.PREPARATION,
            user=request.user,
        )
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
        day = get_object_or_404(TripItineraryDay, itinerary__trip=trip, pk=self.kwargs["day_id"])
        day.delete()
        invalidate_trip_planning(
            trip,
            PlanningStep.PREPARATION,
            user=request.user,
        )
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
        day = get_object_or_404(TripItineraryDay, itinerary__trip=trip, pk=self.kwargs["day_id"])
        serializer = self.get_serializer(
            data=request.data,
            context={"request": request, "trip": trip, "day": day},
        )
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        invalidate_trip_planning(
            trip,
            PlanningStep.PREPARATION,
            user=request.user,
        )
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
        return get_object_or_404(
            TripItineraryDayItem,
            trip_itinerary_day__itinerary__trip=trip,
            pk=self.kwargs["item_id"],
        )

    def patch(self, request, *args, **kwargs):
        item = self.get_object()
        serializer = self.get_serializer(
            item,
            data=request.data,
            partial=True,
            context={
                "request": request,
                "trip": item.trip_itinerary_day.itinerary.trip,
                "day": item.trip_itinerary_day,
            },
        )
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        invalidate_trip_planning(
            item.trip_itinerary_day.itinerary.trip,
            PlanningStep.PREPARATION,
            user=request.user,
        )
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
        item = get_object_or_404(
            TripItineraryDayItem,
            trip_itinerary_day__itinerary__trip=trip,
            pk=self.kwargs["item_id"],
        )
        item.delete()
        invalidate_trip_planning(
            trip,
            PlanningStep.PREPARATION,
            user=request.user,
        )
        return APIResponse.success(message="Itinerary item deleted successfully.")
