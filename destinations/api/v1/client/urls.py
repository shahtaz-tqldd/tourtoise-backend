from django.urls import path

from destinations.api.v1.client.views import (
    ClientDestinationDetailAPIView,
    ClientDestinationListAPIView,
    ClientDestinationSaveAPIView,
    ClientSavedDestinationListAPIView,
)


urlpatterns = [
    path("list/", ClientDestinationListAPIView.as_view(), name="client-destination-list"),
    path("save/list/", ClientSavedDestinationListAPIView.as_view(), name="client-saved-destination-list"),
    path("<slug:destination_slug>/save/", ClientDestinationSaveAPIView.as_view(), name="client-destination-save"),
    path("<slug:slug>/detail/", ClientDestinationDetailAPIView.as_view(), name="client-destination-detail"),
]
