from django.urls import path

from trips.api.v1.client.views import (
    PublicTripDetailAPIView,
    TripCreateAPIView,
    TripDayCreateAPIView,
    TripDayDeleteAPIView,
    TripDayUpdateAPIView,
    TripDeleteAPIView,
    TripDestinationCreateAPIView,
    TripDestinationDeleteAPIView,
    TripDestinationUpdateAPIView,
    TripDetailAPIView,
    TripItineraryItemCreateAPIView,
    TripItineraryItemDeleteAPIView,
    TripItineraryItemUpdateAPIView,
    TripListAPIView,
    TripPlanVersionCreateAPIView,
    TripPlanVersionListAPIView,
    TripUpdateAPIView,
)


urlpatterns = [
    path("create/", TripCreateAPIView.as_view(), name="trip-create"),
    path("list/", TripListAPIView.as_view(), name="trip-list"),
    path("public/<uuid:share_token>/detail/", PublicTripDetailAPIView.as_view(), name="public-trip-detail"),
    path("<uuid:trip_id>/detail/", TripDetailAPIView.as_view(), name="trip-detail"),
    path("<uuid:trip_id>/update/", TripUpdateAPIView.as_view(), name="trip-update"),
    path("<uuid:trip_id>/delete/", TripDeleteAPIView.as_view(), name="trip-delete"),
    
    # manage destinations
    path("<uuid:trip_id>/destinations/create/", TripDestinationCreateAPIView.as_view(), name="trip-destination-create"),
    path(
        "<uuid:trip_id>/destinations/<uuid:destination_row_id>/update/",
        TripDestinationUpdateAPIView.as_view(),
        name="trip-destination-update",
    ),
    path(
        "<uuid:trip_id>/destinations/<uuid:destination_row_id>/delete/",
        TripDestinationDeleteAPIView.as_view(),
        name="trip-destination-delete",
    ),

    # manage days
    path("<uuid:trip_id>/days/create/", TripDayCreateAPIView.as_view(), name="trip-day-create"),
    path("<uuid:trip_id>/days/<uuid:day_id>/update/", TripDayUpdateAPIView.as_view(), name="trip-day-update"),
    path("<uuid:trip_id>/days/<uuid:day_id>/delete/", TripDayDeleteAPIView.as_view(), name="trip-day-delete"),
    
    # manage itinerary items
    path(
        "<uuid:trip_id>/days/<uuid:day_id>/items/create/",
        TripItineraryItemCreateAPIView.as_view(),
        name="trip-item-create",
    ),
    path(
        "<uuid:trip_id>/items/<uuid:item_id>/update/",
        TripItineraryItemUpdateAPIView.as_view(),
        name="trip-item-update",
    ),
    path(
        "<uuid:trip_id>/items/<uuid:item_id>/delete/",
        TripItineraryItemDeleteAPIView.as_view(),
        name="trip-item-delete",
    ),

    # manage plan versions
    path("<uuid:trip_id>/plan-versions/", TripPlanVersionListAPIView.as_view(), name="trip-plan-version-list"),
    path(
        "<uuid:trip_id>/plan-versions/create/",
        TripPlanVersionCreateAPIView.as_view(),
        name="trip-plan-version-create",
    ),
]
