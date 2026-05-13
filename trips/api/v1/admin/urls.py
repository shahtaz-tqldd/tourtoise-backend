from django.urls import path

from trips.api.v1.admin.views import AdminTripDetailAPIView, AdminTripListAPIView


urlpatterns = [
    path("list/", AdminTripListAPIView.as_view(), name="admin-trip-list"),
    path("<uuid:trip_id>/detail/", AdminTripDetailAPIView.as_view(), name="admin-trip-detail"),
]
