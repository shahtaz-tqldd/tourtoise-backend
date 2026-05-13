from django.urls import path

from destinations.api.v1.admin.views import (
    AdminDestinationCreateAPIView,
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
]
