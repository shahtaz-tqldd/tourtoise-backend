from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework import serializers as drf_serializers
from rest_framework.generics import CreateAPIView, GenericAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView

from app.utils.response import APIResponse
from accounts.api.v1.client.serializers import (
    ChangePasswordSerializer,
    GoogleLoginSerializer,
    LoginSerializer,
    PublicUserProfileSerializer,
    RequestPasswordResetSerializer,
    RegisterSerializer,
    ResetPasswordSerializer,
    UserSerializer,
    UserUpdateSerializer,
)

User = get_user_model()


class CreateNewUserView(CreateAPIView):
    """
    Client registration API.

    Frontend request:
    - Method: POST
    - Content-Type: application/json
    - Body:
      `email`, `password`, `confirm_password`
      Optional: `name`, `phone`, `username`

    Frontend response:
    - 201 success with the created user profile payload.
    - Response includes account/profile fields, but not auth tokens.
    """

    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return APIResponse.error(
                errors=serializer.errors,
                message="Registration failed.",
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            user = serializer.save()
        except drf_serializers.ValidationError as exc:
            return APIResponse.error(
                errors=exc.detail,
                message="Registration failed.",
                status=status.HTTP_400_BAD_REQUEST,
            )
        return APIResponse.success(
            data=UserSerializer(user).data,
            message="User created successfully.",
            status=status.HTTP_201_CREATED,
        )


class LoginView(GenericAPIView):
    """
    Client login API.

    Frontend request:
    - Method: POST
    - Content-Type: application/json
    - Body: `email`, `password`

    Frontend response:
    - 200 success with:
      `access_token`
      `refresh_token`
    """

    serializer_class = LoginSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        return APIResponse.success(
            data=serializer.validated_data,
            message="User logged in.",
        )


class GoogleLoginView(GenericAPIView):
    """
    Google account login API.

    Frontend request:
    - Method: POST
    - Content-Type: application/json
    - Path: /api/v1/accounts/google/
    - Body:
      `provider`, `firebase_id_token`, `google_access_token`, `firebase_uid`,
      `email`, `email_verified`, `name`, `photo_url`, `phone_number`

    Frontend response:
    - 200 success with:
      `access_token`
      `refresh_token`
    """

    serializer_class = GoogleLoginSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        return APIResponse.success(
            data=serializer.save(),
            message="User logged in.",
        )


class RefreshTokenView(TokenRefreshView):
    """
    Refresh access token API.

    Frontend request:
    - Method: POST
    - Content-Type: application/json
    - Body: `refresh`
      Send the refresh token previously returned by the login API.

    Frontend response:
    - 200 success with a new `access` token.
    """

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        return APIResponse.success(
            data=response.data,
            message="Token refreshed successfully.",
            status=response.status_code,
        )


class UserDetailsView(APIView):
    """
    Current user details API.

    Frontend request:
    - Method: GET
    - Headers: authenticated bearer token
    - No query params or request body are required.

    Frontend response:
    - 200 success with the full current account + travel profile payload.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return APIResponse.success(data=UserSerializer(request.user).data)


class PublicUserDetailsView(GenericAPIView):
    """
    Public user profile API.

    Frontend request:
    - Method: GET
    - No authentication required.
    - URL param: `username`
      Example: `/api/v1/accounts/public/john-doe/`

    Frontend response:
    - 200 success with public-safe profile fields only.
    - Private fields such as `email`, `phone`, emergency contacts, dietary preferences,
      and internal account flags are not exposed.
    - If the profile does not exist or is not marked public, the API returns 404.
    """

    def get_object(self):
        return get_object_or_404(
            User.objects.select_related("profile").filter(profile__is_public_profile=True),
            profile__username=self.kwargs["username"],
        )

    def get(self, request, *args, **kwargs):
        user = self.get_object()
        return APIResponse.success(
            data=PublicUserProfileSerializer(user).data,
            message="Public profile fetched successfully.",
        )


class UserDetailsUpdateView(GenericAPIView):
    """
    Current user profile update API.

    Frontend request:
    - Method: PATCH
    - Headers: authenticated bearer token
    - Content-Type:
      `multipart/form-data` when sending `profile_picture`
      `application/json` when no file upload is needed
    - Send only fields you want to update.
    - Supported scalar fields:
      `email`, `name`, `phone`, `username`, `bio`, `date_of_birth`, `gender`,
      `country_of_residence`, `city`, `preferred_language`, `preferred_currency`,
      `travel_pace`, `emergency_contact_name`,
      `emergency_contact_phone`, `is_public_profile`
    - Send list fields as JSON arrays:
      `travel_interests=["beaches","food","culture"]`
      `dietary_preferences=["halal","vegetarian"]`
      `mobility_constraints=["avoid stairs"]`
    - For multipart requests, those list fields can be sent as JSON strings.
    - Send `profile_picture` to upload/replace the avatar.
    - Send `clear_profile_picture=true` to remove the current avatar.

    Frontend response:
    - 200 success with the fully updated account + profile payload.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = UserUpdateSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            request.user,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return APIResponse.success(
            data=UserSerializer(user).data,
            message="User updated successfully.",
        )


class ChangePasswordView(GenericAPIView):
    """
    Change password API for an authenticated user.

    Frontend request:
    - Method: PATCH
    - Headers: authenticated bearer token
    - Content-Type: application/json
    - Body:
      `current_password`, `new_password`, `confirm_password`

    Frontend response:
    - 200 success with no data payload.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return APIResponse.success(message="Password changed successfully.")


class RequestPasswordResetView(GenericAPIView):
    """
    Request password reset API.

    Frontend request:
    - Method: POST
    - Content-Type: application/json
    - Body: `email`

    Frontend response:
    - 200 success with a generic message regardless of whether the account exists.
    """

    serializer_class = RequestPasswordResetSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return APIResponse.success(
            message="If an account exists for that email, a password reset link has been sent."
        )


class ResetPasswordView(GenericAPIView):
    """
    Reset password API.

    Frontend request:
    - Method: POST
    - Content-Type: application/json
    - Body:
      `uid`, `token`, `new_password`, `confirm_password`
    - `uid` and `token` should come from the password reset link sent to the user.

    Frontend response:
    - 200 success with no data payload.
    """

    serializer_class = ResetPasswordSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return APIResponse.success(message="Password reset successfully.")
