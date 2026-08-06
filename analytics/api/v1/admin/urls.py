from django.urls import path

from analytics.api.v1.admin.views import OverviewStatsAPIView, UserGrowthAPIView


urlpatterns = [
    path("overview/", OverviewStatsAPIView.as_view(), name="analytics-overview"),
    path("user-growth/", UserGrowthAPIView.as_view(), name="analytics-user-growth"),
]

