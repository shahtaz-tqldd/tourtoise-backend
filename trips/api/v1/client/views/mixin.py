from django.db.models import Prefetch
from django.shortcuts import get_object_or_404

from app.base.pagination import CustomPagination
from app.utils.response import APIResponse

from trips.models import (
    Trip, TripDestination, TripItineraryDayItem, 
    TripItineraryDay
  )


class TripPaginationMixin:
    pagination_class = CustomPagination

    def paginate_with_meta(self, queryset, serializer_class, message="Trips fetched successfully."):
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
            message=message,
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
                "trip_itinerary__itinerary_days",
                queryset=TripItineraryDay.objects.prefetch_related(
                    Prefetch(
                        "day_items",
                        queryset=TripItineraryDayItem.objects.order_by("time"),
                    )
                ).order_by("day"),
            ),
        )

    def get_trip_by_id(self):
        return get_object_or_404(self.get_trip_queryset(), pk=self.kwargs["trip_id"])
