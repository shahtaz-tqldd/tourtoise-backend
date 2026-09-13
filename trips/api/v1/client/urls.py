from django.urls import path, include
from trips.api.v1.client import views


trip_apis = [
    path("create/", views.TripCreateAPIView.as_view(), name="trip-create"),
    path("list/", views.TripListAPIView.as_view(), name="trip-list"),
    path("public/<uuid:share_token>/detail/", views.PublicTripDetailAPIView.as_view(), name="public-trip-detail"),
    path("<uuid:trip_id>/detail/", views.TripDetailAPIView.as_view(), name="trip-detail"),
    path("<uuid:trip_id>/short-details/", views.TripShortDetailsAPIView.as_view(), name="trip-detail"),
    path("<uuid:trip_id>/share-token/", views.TripShareTokenAPIView.as_view(), name="trip-share-token"),
    path("<uuid:trip_id>/visibility/", views.TripVisibilityUpdateAPIView.as_view(), name="trip-visibility-update"),
    path("<uuid:trip_id>/update/", views.TripUpdateAPIView.as_view(), name="trip-update"),
    path("<uuid:trip_id>/delete/", views.TripDeleteAPIView.as_view(), name="trip-delete"),
]

planning_apis = [
    path("", views.TripPlanningAPIView.as_view(), name="trip-planning"),
    path("agent-init/", views.TripAgentInitAPIView.as_view(), name="trip-agent-initiate"),
    path("create-message/", views.TripAgentCreateMessageAPIView.as_view(), name="trip-agent-create-message"),
    path("activate/", views.ActivateTripPlanAPIView.as_view(), name="trip-planning-activate"),
]

trip_destination_apis = [
    path("create/", views.TripDestinationCreateAPIView.as_view(), name="trip-destination-create"),
    path("<uuid:destination_id>/update/", views.TripDestinationUpdateAPIView.as_view(), name="trip-destination-update"),
    path("<uuid:destination_id>/delete/", views.TripDestinationDeleteAPIView.as_view(), name="trip-destination-delete"),
]

trip_packing_items_apis = [
    path("", views.TripPreparationPackingItemListCreateAPIView.as_view(), name="trip-packing-item-list-create"),
    path("<uuid:packing_item_id>/", views.TripPreparationPackingItemDetailAPIView.as_view(), name="trip-packing-item-detail"),
]

trip_documents_apis = [
    path("", views.TripRequiredDocumentItemListCreateAPIView.as_view(), name="trip-required-document-list-create"),
    path("<uuid:document_id>/", views.TripRequiredDocumentItemDetailAPIView.as_view(), name="trip-required-document-detail"),
    path("<uuid:document_id>/file/", views.TripRequiredDocumentFileDeleteAPIView.as_view(), name="trip-required-document-file-delete"),
]

trip_headsup_apis = [
    path("", views.TripHeadsUpInfoItemListCreateAPIView.as_view(), name="trip-heads-up-item-list-create"),
    path("<uuid:heads_up_item_id>/", views.TripHeadsUpInfoItemDetailAPIView.as_view(), name="trip-heads-up-item-detail"),
]

trip_plan_apis = [
    path("daywise/", views.TripDayWisePlanListAPIView.as_view(), name="trip-daywise-plan-list"),
    path("routes/", views.TripRoutePlanListAPIView.as_view(), name="trip-route-list"),
    path("items/<int:item_id>/", views.TripItineraryItemUpdateAPIView.as_view(), name="trip-plan-item-update"),
]

trip_notes_apis = [
    path("create/", views.TripNoteCreateAPIView.as_view(), name="trip-note-create"),
    path("list/", views.TripNoteListAPIView.as_view(), name="trip-note-list"),
    path("<uuid:note_id>/", views.TripNoteDetailAPIView.as_view(), name="trip-note-detail"),
]

trip_chat_apis =[
    path("messages/", views.TripChatMessageListAPIView.as_view(), name="trip-chat-messages"),
    path("create-message/", views.TripChatCreateMessageAPIView.as_view(), name="trip-chat-create-message"),
    path("read-all/", views.TripChatReadAllAPIView.as_view(), name="trip-chat-read-all"),
]

urlpatterns = [
    path("", include(trip_apis)),
    path("planning/", include(planning_apis)),
    path("<uuid:trip_id>/destinations/", include(trip_destination_apis)),
    path("<uuid:trip_id>/packing-items/", include(trip_packing_items_apis)),
    path("<uuid:trip_id>/documents/", include(trip_documents_apis)),
    path("<uuid:trip_id>/heads-up/", include(trip_headsup_apis)),
    path("<uuid:trip_id>/plan/", include(trip_plan_apis)),
    path("<uuid:trip_id>/notes/", include(trip_notes_apis)),
    path("<uuid:trip_id>/chat/", include(trip_chat_apis)),
    # Backwards-compatible routes. The supplied id must match the trip's one
    # conversation session; new clients should use the routes above.
    path("<uuid:trip_id>/chat/<uuid:session_id>/", include(trip_chat_apis)),
]
