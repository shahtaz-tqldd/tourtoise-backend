from django.urls import path

from journals.api.v1.admin.views import (
    AdminContentReportListAPIView,
    AdminContentReportReviewAPIView,
)


urlpatterns = [
    path("reports/", AdminContentReportListAPIView.as_view(), name="admin-content-report-list"),
    path(
        "reports/<uuid:pk>/review/",
        AdminContentReportReviewAPIView.as_view(),
        name="admin-content-report-review",
    ),
]
