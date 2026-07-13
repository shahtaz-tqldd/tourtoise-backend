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

trip_notes = [
    path("create/", views.TripNoteCreateAPIView.as_view(), name="trip-note-create"),
    path("list/", views.TripNoteListAPIView.as_view(), name="trip-note-list"),
    path("<uuid:note_id>/", views.TripNoteDetailAPIView.as_view(), name="trip-note-detail"),
]

trip_packing_items = [
    path("", views.TripPreparationPackingItemListCreateAPIView.as_view(), name="trip-packing-item-list-create"),
    path(
        "<uuid:packing_item_id>/",
        views.TripPreparationPackingItemDetailAPIView.as_view(),
        name="trip-packing-item-detail",
    ),
]

trip_heads_up_items = [
    path("", views.TripHeadsUpInfoItemListCreateAPIView.as_view(), name="trip-heads-up-item-list-create"),
    path(
        "<uuid:heads_up_item_id>/",
        views.TripHeadsUpInfoItemDetailAPIView.as_view(),
        name="trip-heads-up-item-detail",
    ),
]

trip_required_documents = [
    path("", views.TripRequiredDocumentItemListCreateAPIView.as_view(), name="trip-required-document-list-create"),
    path(
        "<uuid:document_item_id>/",
        views.TripRequiredDocumentItemDetailAPIView.as_view(),
        name="trip-required-document-detail",
    ),
    path(
        "<uuid:document_item_id>/file/",
        views.TripRequiredDocumentFileDeleteAPIView.as_view(),
        name="trip-required-document-file-delete",
    ),
]

trip_plan = [
    path("daywise/", views.TripDayWisePlanListAPIView.as_view(), name="trip-daywise-plan-list"),
    path(
        "items/<int:item_id>/",
        views.TripItineraryItemUpdateAPIView.as_view(),
        name="trip-plan-item-update",
    ),
]



trip_urlpatterns = [
    path("create/", views.TripCreateAPIView.as_view(), name="trip-create"),
    path("list/", views.TripListAPIView.as_view(), name="trip-list"),
    path("<uuid:trip_id>/detail/", views.TripDetailAPIView.as_view(), name="trip-detail"),
    path("public/<uuid:share_token>/detail/", views.PublicTripDetailAPIView.as_view(), name="public-trip-detail"),
    path("<uuid:trip_id>/share-token/", views.TripShareTokenAPIView.as_view(), name="trip-share-token"),
    path("<uuid:trip_id>/visibility/", views.TripVisibilityUpdateAPIView.as_view(), name="trip-visibility-update"),
    path("<uuid:trip_id>/update/", views.TripUpdateAPIView.as_view(), name="trip-update"),
    path("<uuid:trip_id>/delete/", views.TripDeleteAPIView.as_view(), name="trip-delete"),
]

urlpatterns = [
    path("", include(trip_urlpatterns)),
    path("agent-active/", views.TripAgentInitAPIView.as_view(), name="trip-agent-active"),
    path("agent/create-message/", views.TripAgentCreateMessageAPIView.as_view(), name="trip-agent-create-message-legacy"),
    path("<uuid:trip_id>/routes/", views.TripRoutePlanListAPIView.as_view(), name="trip-route-list"),
    path("planning/", include(planning_urlpatterns)),
    path("<uuid:trip_id>/destinations/", include(trip_destination_urlpatterns)),
    path("<uuid:trip_id>/notes/", include(trip_notes)),
    path("<uuid:trip_id>/packing-items/", include(trip_packing_items)),
    path("<uuid:trip_id>/heads-up/", include(trip_heads_up_items)),
    path("<uuid:trip_id>/documents/", include(trip_required_documents)),
    path("<uuid:trip_id>/plan/", include(trip_plan)),
]
