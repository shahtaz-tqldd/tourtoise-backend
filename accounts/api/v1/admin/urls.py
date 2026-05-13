from django.urls import path

from accounts.api.v1.admin.views import AccountListAPIView


urlpatterns = [
    path("list/", AccountListAPIView.as_view(), name="account-list"),
]
