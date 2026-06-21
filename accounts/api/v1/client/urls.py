from django.urls import path, include
from accounts.api.v1.client import views

auth_apis = [
    path("register/", views.CreateNewUserView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("google/", views.GoogleLoginView.as_view(), name="google-login"),
    path("refresh/", views.RefreshTokenView.as_view(), name="refresh-token"),
    path("request-reset-password/", views.RequestPasswordResetView.as_view(), name="request-reset-password"),
    path("reset-password/", views.ResetPasswordView.as_view(), name="reset-password"),
]

profile_apis = [
    path("self-details/", views.UserDetailsView.as_view(), name="user-details"),
    path("public/<slug:username>/", views.PublicUserDetailsView.as_view(), name="public-user-details"),
    path("update/", views.UserDetailsUpdateView.as_view(), name="update-user"),
]

settings_apis = [
    path("change-password/", views.ChangePasswordView.as_view(), name="change-password"),
]

urlpatterns = [
    path("", include(auth_apis)),
    path("", include(profile_apis)),
    path("settings/", include(profile_apis)),
]
