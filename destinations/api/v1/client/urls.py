from django.urls import path

from destinations.api.v1.client import views


urlpatterns = [
    path("list/", views.ClientDestinationListAPIView.as_view(), name="client-destination-list"),
    path("save/list/", views.ClientSavedDestinationListAPIView.as_view(), name="client-saved-destination-list"),
    path("<slug:destination_slug>/save/", views.ClientDestinationSaveAPIView.as_view(), name="client-destination-save"),
    path("<slug:slug>/attractions/", views.ClientDestinationAttractionListAPIView.as_view(), name="client-destination-attraction-list"),
    path("<slug:slug>/activities/", views.ClientDestinationActivityListAPIView.as_view(), name="client-destination-activity-list"),
    path("<slug:slug>/cuisines/", views.ClientDestinationCuisineListAPIView.as_view(), name="client-destination-cuisine-list"),
    path("<slug:slug>/short-detail/", views.ClientDestinationShortDetailAPIView.as_view(), name="client-destination-short-detail"),
    path("<slug:slug>/detail/", views.ClientDestinationDetailAPIView.as_view(), name="client-destination-detail"),
]
