from django.urls import path

from accounts.api.v1.admin.views import (
    AccountListAPIView,
    AdminDetailsAPIView,
    AdminLoginAPIView,
)


urlpatterns = [
    path("login/", AdminLoginAPIView.as_view(), name="admin-login"),
    path("self-details/", AdminDetailsAPIView.as_view(), name="admin-details"),
    path("list/", AccountListAPIView.as_view(), name="account-list"),
]
