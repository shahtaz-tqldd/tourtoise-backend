from django.urls import path

from accounts.api.v1.client.views import (
    ChangePasswordView,
    CreateNewUserView,
    GoogleLoginView,
    LoginView,
    PublicUserDetailsView,
    RefreshTokenView,
    RequestPasswordResetView,
    ResetPasswordView,
    UserDetailsUpdateView,
    UserDetailsView,
)

urlpatterns = [
    path("register/", CreateNewUserView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("google/", GoogleLoginView.as_view(), name="google-login"),
    path("refresh/", RefreshTokenView.as_view(), name="refresh-token"),
    path("public/<slug:username>/", PublicUserDetailsView.as_view(), name="public-user-details"),
    path("self-details/", UserDetailsView.as_view(), name="user-details"),
    path("update/", UserDetailsUpdateView.as_view(), name="update-user"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    path("request-reset-password/", RequestPasswordResetView.as_view(), name="request-reset-password"),
    path("reset-password/", ResetPasswordView.as_view(), name="reset-password"),
]
