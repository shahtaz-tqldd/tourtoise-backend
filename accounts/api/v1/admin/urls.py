from django.urls import path

from accounts.api.v1.admin.views import (
    AccountListAPIView,
    AdminDetailsAPIView,
    AdminLoginAPIView,
    UpdateAdminInfoAPIView,
    UpdateAdminPasswordAPIView,
)


urlpatterns = [
    path("login/", AdminLoginAPIView.as_view(), name="admin-login"),
    path("update-info/", UpdateAdminInfoAPIView.as_view(), name="update-admin-info"),
    path("update-password/", UpdateAdminPasswordAPIView.as_view(), name="update-admin-password"),
    path("self-details/", AdminDetailsAPIView.as_view(), name="admin-details"),
    path("list/", AccountListAPIView.as_view(), name="account-list"),
]
