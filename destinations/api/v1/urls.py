from django.urls import include, path


client_urlpatterns = [
    path("", include("destinations.api.v1.client.urls")),
]

admin_urlpatterns = [
    path("", include("destinations.api.v1.admin.urls")),
]
