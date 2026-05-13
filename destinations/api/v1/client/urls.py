from django.urls import path

from destinations.api.v1.client.views import (
    ClientDestinationDetailAPIView,
    ClientDestinationListAPIView,
)


urlpatterns = [
    path("list/", ClientDestinationListAPIView.as_view(), name="client-destination-list"),
    path("<slug:slug>/detail/", ClientDestinationDetailAPIView.as_view(), name="client-destination-detail"),
]
