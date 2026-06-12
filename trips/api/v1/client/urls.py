from django.urls import path, include
from trips.api.v1.client import views

planning_urlpatterns = [
    path("agent-init/", views.TripAgentInitAPIView.as_view(), name="trip-agent-initiate"),
    path("create-message/", views.TripAgentCreateMessageAPIView.as_view(), name="trip-agent-create-message"),
    path("messages/", views.TripAgentMessageListAPIView.as_view(), name="trip-agent-messages"),
    path("recommendations/", views.TripPlanningRecommendationsAPIView.as_view(), name="trip-planning-recommendations"),
    path("itineraries/", views.TripPlanningItinerariesAPIView.as_view(), name="trip-planning-itineraries"),
    path("preparation/", views.TripPlanningPrepartionAPIView.as_view(), name="trip-planning-preparation"),
    path("overview/", views.TripPlanningOverviewAPIView.as_view(), name="trip-planning-overview"),
    path("activate/", views.ActivateTripPlanAPIView.as_view(), name="trip-planning-activate"),
]

trip_destination_urlpatterns = [
    path("create/", views.TripDestinationCreateAPIView.as_view(), name="trip-destination-create"),
    path(
        "<uuid:destination_row_id>/update/",
        views.TripDestinationUpdateAPIView.as_view(),
        name="trip-destination-update",
    ),
    path(
        "<uuid:destination_row_id>/delete/",
        views.TripDestinationDeleteAPIView.as_view(),
        name="trip-destination-delete",
    ),
]

trip_urlpatterns = [
    path("create/", views.TripCreateAPIView.as_view(), name="trip-create"),
    path("list/", views.TripListAPIView.as_view(), name="trip-list"),
    path("<uuid:trip_id>/detail/", views.TripDetailAPIView.as_view(), name="trip-detail"),
    path("public/<uuid:share_token>/detail/", views.PublicTripDetailAPIView.as_view(), name="public-trip-detail"),
    path("<uuid:trip_id>/update/", views.TripUpdateAPIView.as_view(), name="trip-update"),
    path("<uuid:trip_id>/delete/", views.TripDeleteAPIView.as_view(), name="trip-delete"),
]

urlpatterns = [
    path("", include(trip_urlpatterns)),
    path("agent-active/", views.TripAgentInitAPIView.as_view(), name="trip-agent-active"),
    path("agent/create-message/", views.TripAgentCreateMessageAPIView.as_view(), name="trip-agent-create-message-legacy"),
    path("planning/", include(planning_urlpatterns)),
    path("<uuid:trip_id>/destinations/", include(trip_destination_urlpatterns)),
]
