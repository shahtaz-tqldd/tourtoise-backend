from django.urls import path, include

from destinations.api.v1.admin import views

destinations_apis = [
    path("detail/", views.DestinationDetailAPIView.as_view(), name="destination-details"),
    path("short-details/", views.DestinationShortDetailAPIView.as_view(), name="destination-details"),
    path("update/", views.DestinationUpdateAPIView.as_view(), name="destination-update"),
    path("delete/", views.DestinationDeleteAPIView.as_view(), name="destination-delete"),
    path("re-train/", views.DestinationRetrainAPIView.as_view(), name="destination-retrain"),
]

attractions_apis = [
    path("", views.DestinationAttractionListCreateAPIView.as_view(), name="attraction-list-create"),
    path("bulk-template/", views.DestinationAttractionBulkTemplateAPIView.as_view(), name="attraction-bulk-template"),
    path("bulk-upload/", views.DestinationAttractionBulkUploadAPIView.as_view(), name="attraction-bulk-upload"),
    path("<uuid:attraction_id>/re-train/", views.DestinationAttractionRetrainAPIView.as_view(), name="attraction-retrain"),
    path("<uuid:attraction_id>/", views.DestinationAttractionDetailAPIView.as_view(), name="attraction-detail"),
]

activities_apis = [
    path("", views.DestinationActivityListCreateAPIView.as_view(), name="activity-list-create"),
    path("bulk-template/", views.DestinationActivityBulkTemplateAPIView.as_view(), name="activity-bulk-template"),
    path("bulk-upload/", views.DestinationActivityBulkUploadAPIView.as_view(), name="activity-bulk-upload"),
    path("<uuid:activity_id>/re-train/", views.DestinationActivityRetrainAPIView.as_view(), name="activity-retrain"),
    path("<uuid:activity_id>/", views.DestinationActivityDetailAPIView.as_view(), name="activity-detail"),
]

cuisines_apis = [
    path("", views.DestinationCuisineListCreateAPIView.as_view(), name="cuisine-list-create"),
    path("bulk-template/", views.DestinationCuisineBulkTemplateAPIView.as_view(), name="cuisine-bulk-template"),
    path("bulk-upload/", views.DestinationCuisineBulkUploadAPIView.as_view(), name="cuisine-bulk-upload"),
    path("<uuid:cuisine_id>/re-train/", views.DestinationCuisineRetrainAPIView.as_view(), name="cuisine-retrain"),
    path("<uuid:cuisine_id>/", views.DestinationCuisineDetailAPIView.as_view(), name="cuisine-detail"),
]


urlpatterns = [
    path("create/", views.DestinationCreateAPIView.as_view(), name="destination-create"),
    path("bulk-template/", views.DestinationBulkTemplateAPIView.as_view(), name="destination-bulk-template"),
    path("bulk-download/", views.DestinationBulkDownloadAPIView.as_view(), name="destination-bulk-download"),
    path("batch-train/", views.DestinationBatchTrainAPIView.as_view(), name="destination-batch-train"),
    path("batch-delete/", views.DestinationBatchDeleteAPIView.as_view(), name="destination-batch-delete"),
    path("bulk-upload/", views.DestinationBulkUploadAPIView.as_view(), name="bulk-destination-upload"),
    path("list/", views.DestinationListAPIView.as_view(), name="destination-list"),
    path("<uuid:destination_id>/", include(destinations_apis)),
    path("<uuid:destination_id>/attractions/", include(attractions_apis)),
    path("<uuid:destination_id>/activities/", include(activities_apis)),
    path("<uuid:destination_id>/cuisines/", include(cuisines_apis)),
]
