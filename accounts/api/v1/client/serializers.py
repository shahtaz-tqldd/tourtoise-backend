from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from uuid import uuid4

from app.utils.cloudinary import delete_image, upload_image
from accounts.models import UserProfile
from accounts.services import resolve_password_reset_user, send_user_password_reset_email


User = get_user_model()


def get_or_create_profile(user):
    try:
        return user.profile
    except UserProfile.DoesNotExist:
        return UserProfile.objects.create(user=user)


class UserSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="profile.username", read_only=True)
    avatar_url = serializers.URLField(source="profile.avatar_url", read_only=True)
    bio = serializers.CharField(source="profile.bio", read_only=True)
    date_of_birth = serializers.DateField(source="profile.date_of_birth", read_only=True)
    gender = serializers.CharField(source="profile.gender", read_only=True)
    country_of_residence = serializers.CharField(source="profile.country_of_residence", read_only=True)
    city = serializers.CharField(source="profile.city", read_only=True)
    preferred_language = serializers.CharField(source="profile.preferred_language", read_only=True)
    preferred_currency = serializers.CharField(source="profile.preferred_currency", read_only=True)
    travel_style = serializers.CharField(source="profile.travel_style", read_only=True)
    travel_interests = serializers.ListField(source="profile.travel_interests", read_only=True)
    dietary_preferences = serializers.ListField(source="profile.dietary_preferences", read_only=True)
    accessibility_needs = serializers.CharField(source="profile.accessibility_needs", read_only=True)
    emergency_contact_name = serializers.CharField(source="profile.emergency_contact_name", read_only=True)
    emergency_contact_phone = serializers.CharField(source="profile.emergency_contact_phone", read_only=True)
    is_public_profile = serializers.BooleanField(source="profile.is_public_profile", read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "name",
            "phone",
            "status",
            "is_email_verified",
            "is_staff",
            "is_superuser",
            "username",
            "avatar_url",
            "bio",
            "date_of_birth",
            "gender",
            "country_of_residence",
            "city",
            "preferred_language",
            "preferred_currency",
            "travel_style",
            "travel_interests",
            "dietary_preferences",
            "accessibility_needs",
            "emergency_contact_name",
            "emergency_contact_phone",
            "is_public_profile",
            "created_at",
        )
        read_only_fields = (
            "id",
            "status",
            "is_email_verified",
            "is_staff",
            "is_superuser",
            "created_at",
            "updated_at",
        )


class PublicUserProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="profile.username", read_only=True)
    avatar_url = serializers.URLField(source="profile.avatar_url", read_only=True)
    bio = serializers.CharField(source="profile.bio", read_only=True)
    country_of_residence = serializers.CharField(source="profile.country_of_residence", read_only=True)
    city = serializers.CharField(source="profile.city", read_only=True)
    preferred_language = serializers.CharField(source="profile.preferred_language", read_only=True)
    preferred_currency = serializers.CharField(source="profile.preferred_currency", read_only=True)
    travel_style = serializers.CharField(source="profile.travel_style", read_only=True)
    travel_interests = serializers.ListField(source="profile.travel_interests", read_only=True)

    class Meta:
        model = User
        fields = (
            "name",
            "username",
            "avatar_url",
            "bio",
            "country_of_residence",
            "city",
            "preferred_language",
            "preferred_currency",
            "travel_style",
            "travel_interests",
        )
        read_only_fields = fields


class UserUpdateSerializer(serializers.ModelSerializer):
    username = serializers.SlugField(required=False, allow_blank=True)
    bio = serializers.CharField(required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.CharField(required=False, allow_blank=True)
    country_of_residence = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=False, allow_blank=True)
    preferred_language = serializers.CharField(required=False, allow_blank=True)
    preferred_currency = serializers.CharField(required=False, allow_blank=True)
    travel_style = serializers.ChoiceField(
        choices=UserProfile._meta.get_field("travel_style").choices,
        required=False,
        allow_blank=True,
    )
    travel_interests = serializers.JSONField(required=False)
    dietary_preferences = serializers.JSONField(required=False)
    accessibility_needs = serializers.CharField(required=False, allow_blank=True)
    emergency_contact_name = serializers.CharField(required=False, allow_blank=True)
    emergency_contact_phone = serializers.CharField(required=False, allow_blank=True)
    is_public_profile = serializers.BooleanField(required=False)
    profile_picture = serializers.FileField(write_only=True, required=False, allow_null=True)
    clear_profile_picture = serializers.BooleanField(write_only=True, required=False, default=False)
    avatar_url = serializers.URLField(source="profile.avatar_url", read_only=True)

    class Meta:
        model = User
        fields = (
            "email",
            "name",
            "phone",
            "username",
            "bio",
            "date_of_birth",
            "gender",
            "country_of_residence",
            "city",
            "preferred_language",
            "preferred_currency",
            "travel_style",
            "travel_interests",
            "dietary_preferences",
            "accessibility_needs",
            "emergency_contact_name",
            "emergency_contact_phone",
            "is_public_profile",
            "profile_picture",
            "clear_profile_picture",
            "avatar_url",
        )
        read_only_fields = ("avatar_url",)

    def validate_username(self, value):
        profile = get_or_create_profile(self.instance)
        queryset = UserProfile.objects.filter(username=value)
        queryset = queryset.exclude(pk=profile.pk)
        if queryset.exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_travel_interests(self, value):
        return self._normalize_string_list(value, "travel_interests")

    def validate_dietary_preferences(self, value):
        return self._normalize_string_list(value, "dietary_preferences")

    def validate(self, attrs):
        clear_profile_picture = attrs.get("clear_profile_picture", False)
        profile_picture = attrs.get("profile_picture", serializers.empty)
        if clear_profile_picture and profile_picture not in (serializers.empty, None):
            raise serializers.ValidationError(
                {"clear_profile_picture": "Do not send clear_profile_picture with profile_picture."}
            )
        return attrs

    def update(self, instance, validated_data):
        profile_picture = validated_data.pop("profile_picture", serializers.empty)
        clear_profile_picture = validated_data.pop("clear_profile_picture", False)
        profile_fields = {
            "username",
            "bio",
            "date_of_birth",
            "gender",
            "country_of_residence",
            "city",
            "preferred_language",
            "preferred_currency",
            "travel_style",
            "travel_interests",
            "dietary_preferences",
            "accessibility_needs",
            "emergency_contact_name",
            "emergency_contact_phone",
            "is_public_profile",
        }
        profile = get_or_create_profile(instance)

        for attr, value in validated_data.items():
            if attr in profile_fields:
                setattr(profile, attr, value)
            else:
                setattr(instance, attr, value)

        if clear_profile_picture:
            if profile.avatar_url:
                delete_image(image_url=profile.avatar_url)
            profile.avatar_url = ""
        elif profile_picture is not serializers.empty:
            if profile_picture is None:
                if profile.avatar_url:
                    delete_image(image_url=profile.avatar_url)
                profile.avatar_url = ""
            else:
                if profile.avatar_url:
                    delete_image(image_url=profile.avatar_url)
                upload = upload_image(
                    profile_picture,
                    folder=f"{settings.CLOUDINARY_FOLDER}/users",
                    public_id=self._build_profile_picture_public_id(instance),
                )
                profile.avatar_url = upload["url"]

        instance.save()
        profile.save()
        return instance

    def _build_profile_picture_public_id(self, user):
        base_name = slugify(user.name or user.email or "user-profile")
        return base_name or f"user-profile-{uuid4().hex[:8]}"

    def _normalize_string_list(self, value, field_name):
        if value in (None, "", []):
            return []
        if isinstance(value, str):
            try:
                import json

                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError(
                    f"Send {field_name} as a valid JSON array."
                ) from exc
        if not isinstance(value, list):
            raise serializers.ValidationError(f"Send {field_name} as a JSON array.")
        return [str(item).strip() for item in value if str(item).strip()]


class RegisterSerializer(serializers.ModelSerializer):
    username = serializers.SlugField(required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = (
            "email",
            "name",
            "phone",
            "username",
            "password",
            "confirm_password",
        )

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs

    def validate_username(self, value):
        if not value:
            return value
        if UserProfile.objects.filter(username=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def create(self, validated_data):
        username = validated_data.pop("username", "")
        validated_data.pop("confirm_password")
        password = validated_data.pop("password")
        user = User.objects.create_user(password=password, **validated_data)
        if username:
            profile = get_or_create_profile(user)
            profile.username = username
            profile.save(update_fields=["username"])
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        email = data.get("email")
        password = data.get("password")
        request = self.context.get("request")

        user = authenticate(request=request, email=email, password=password)

        if not user:
            raise serializers.ValidationError({"error": "Invalid credentials."})

        if not user.is_active:
            raise serializers.ValidationError({"error": "User is disabled."})

        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])

        refresh = RefreshToken.for_user(user)

        return {
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
        }


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        if attrs["current_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": "New password must be different from the current password."}
            )
        validate_password(attrs["new_password"], self.context["request"].user)
        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


class RequestPasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def save(self, **kwargs):
        email = self.validated_data["email"]
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user:
            send_user_password_reset_email(user)
        return None


class ResetPasswordSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})

        try:
            user = resolve_password_reset_user(attrs["uid"], attrs["token"])
        except ValueError as exc:
            raise serializers.ValidationError({"token": str(exc)}) from exc

        validate_password(attrs["new_password"], user)
        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data["user"]
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user
