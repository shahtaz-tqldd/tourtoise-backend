from django.urls import path

from destinations.api.v1.admin.views import (
    AdminDestinationActivityDetailAPIView,
    AdminDestinationActivityListCreateAPIView,
    AdminDestinationAttractionDetailAPIView,
    AdminDestinationAttractionListCreateAPIView,
    AdminDestinationCreateAPIView,
    AdminDestinationCuisineDetailAPIView,
    AdminDestinationCuisineListCreateAPIView,
    AdminDestinationDeleteAPIView,
    AdminDestinationDetailAPIView,
    AdminDestinationListAPIView,
    AdminDestinationUpdateAPIView,
)


urlpatterns = [
    path("create/", AdminDestinationCreateAPIView.as_view(), name="admin-destination-create"),
    path("list/", AdminDestinationListAPIView.as_view(), name="admin-destination-list"),
    path("<uuid:destination_id>/detail/", AdminDestinationDetailAPIView.as_view(), name="admin-destination-detail"),
    path("<uuid:destination_id>/update/", AdminDestinationUpdateAPIView.as_view(), name="admin-destination-update"),
    path("<uuid:destination_id>/delete/", AdminDestinationDeleteAPIView.as_view(), name="admin-destination-delete"),
    path(
        "<uuid:destination_id>/attractions/",
        AdminDestinationAttractionListCreateAPIView.as_view(),
        name="admin-destination-attraction-list-create",
    ),
    path(
        "<uuid:destination_id>/attractions/<uuid:attraction_id>/",
        AdminDestinationAttractionDetailAPIView.as_view(),
        name="admin-destination-attraction-detail",
    ),
    path(
        "<uuid:destination_id>/activities/",
        AdminDestinationActivityListCreateAPIView.as_view(),
        name="admin-destination-activity-list-create",
    ),
    path(
        "<uuid:destination_id>/activities/<uuid:activity_id>/",
        AdminDestinationActivityDetailAPIView.as_view(),
        name="admin-destination-activity-detail",
    ),
    path(
        "<uuid:destination_id>/cuisines/",
        AdminDestinationCuisineListCreateAPIView.as_view(),
        name="admin-destination-cuisine-list-create",
    ),
    path(
        "<uuid:destination_id>/cuisines/<uuid:cuisine_id>/",
        AdminDestinationCuisineDetailAPIView.as_view(),
        name="admin-destination-cuisine-detail",
    ),
]
