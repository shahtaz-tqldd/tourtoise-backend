from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken
from uuid import uuid4

from app.utils.cloudinary import delete_image, upload_image
from accounts.choices import AccountProvider, AccountStatus
from accounts.services.firebase import FirebaseVerificationError, verify_firebase_id_token
from accounts.models import CreditTransaction, UserProfile
from accounts.services.password import resolve_password_reset_user, send_user_password_reset_email
from accounts.services.verification import (
    InvalidVerificationOTP,
    complete_email_verification,
    issue_email_verification_otp,
    verify_email_otp,
)
from app.base.validators import validate_bio_word_count, validate_timezone_name


User = get_user_model()


class CreditTransactionSerializer(serializers.ModelSerializer):
    transaction_type_display = serializers.CharField(
        source="get_transaction_type_display",
        read_only=True,
    )

    class Meta:
        model = CreditTransaction
        fields = (
            "id",
            "transaction_type",
            "transaction_type_display",
            "amount",
            "description",
            "metadata",
            "created_at",
        )
        read_only_fields = fields


def get_or_create_profile(user):
    try:
        return user.profile
    except UserProfile.DoesNotExist:
        return UserProfile.objects.create(user=user)


def build_auth_token_payload(user):
    refresh = RefreshToken.for_user(user)
    return {
        "access_token": str(refresh.access_token),
        "refresh_token": str(refresh),
    }


def build_unique_username_from_email(email):
    local_part = email.split("@", 1)[0]
    base_username = slugify(local_part)[:50].strip("-") or "user"
    username = base_username
    suffix = 1

    while UserProfile.objects.filter(username=username).exists():
        suffix_text = f"-{suffix}"
        username = f"{base_username[:50 - len(suffix_text)]}{suffix_text}"
        suffix += 1

    return username


class UserSerializer(serializers.ModelSerializer):
    credit = serializers.IntegerField(source="credit.balance", read_only=True, default=0)
    username = serializers.CharField(source="profile.username", read_only=True)
    avatar_url = serializers.URLField(source="profile.avatar_url", read_only=True)
    bio = serializers.CharField(source="profile.bio", read_only=True)
    date_of_birth = serializers.DateField(source="profile.date_of_birth", read_only=True)
    gender = serializers.CharField(source="profile.gender", read_only=True)
    country_of_residence = serializers.CharField(source="profile.country_of_residence", read_only=True)
    city = serializers.CharField(source="profile.city", read_only=True)
    preferred_language = serializers.CharField(source="profile.preferred_language", read_only=True)
    preferred_currency = serializers.CharField(source="profile.preferred_currency", read_only=True)
    timezone = serializers.CharField(source="profile.timezone", read_only=True)
    travel_interests = serializers.ListField(source="profile.travel_interests", read_only=True)
    dietary_preferences = serializers.ListField(source="profile.dietary_preferences", read_only=True)
    travel_pace = serializers.CharField(source="profile.travel_pace", read_only=True)
    mobility_constraints = serializers.ListField(source="profile.mobility_constraints", read_only=True)
    emergency_contact_name = serializers.CharField(source="profile.emergency_contact_name", read_only=True)
    emergency_contact_phone = serializers.CharField(source="profile.emergency_contact_phone", read_only=True)
    is_public_profile = serializers.BooleanField(source="profile.is_public_profile", read_only=True)
    total_country_visited = serializers.IntegerField(source="profile.total_country_visited", read_only=True)
    visited_country_list = serializers.ListField(source="profile.visited_country_list", read_only=True)
    total_trip_count = serializers.IntegerField(source="profile.total_trip_count", read_only=True)
    total_journal_count = serializers.IntegerField(source="profile.total_journal_count", read_only=True)
    is_location_sharing_enabled = serializers.BooleanField(
        source="profile.is_location_sharing_enabled",
        read_only=True,
    )
    is_alert_notification_enabled = serializers.BooleanField(
        source="profile.is_alert_notification_enabled",
        read_only=True,
    )

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "name",
            "phone",
            "provider",
            "firebase_uid",
            "status",
            "is_email_verified",
            "is_staff",
            "is_superuser",
            "credit",
            "username",
            "avatar_url",
            "bio",
            "date_of_birth",
            "gender",
            "country_of_residence",
            "city",
            "preferred_language",
            "preferred_currency",
            "timezone",
            "travel_interests",
            "dietary_preferences",
            "travel_pace",
            "mobility_constraints",
            "emergency_contact_name",
            "emergency_contact_phone",
            "is_public_profile",
            "total_country_visited",
            "visited_country_list",
            "total_trip_count",
            "total_journal_count",
            "is_location_sharing_enabled",
            "is_alert_notification_enabled",
            "created_at",
            "last_login",
        )
        read_only_fields = (
            "id",
            "status",
            "provider",
            "firebase_uid",
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
    date_of_birth = serializers.DateField(source="profile.date_of_birth", read_only=True)
    gender = serializers.CharField(source="profile.gender", read_only=True)
    city = serializers.CharField(source="profile.city", read_only=True)
    country = serializers.CharField(source="profile.country_of_residence", read_only=True)
    preferred_language = serializers.CharField(source="profile.preferred_language", read_only=True)
    preferred_currency = serializers.CharField(source="profile.preferred_currency", read_only=True)
    travel_interests = serializers.ListField(source="profile.travel_interests", read_only=True)
    mobility_constraints = serializers.ListField(source="profile.mobility_constraints", read_only=True)
    dietary_preferences = serializers.ListField(source="profile.dietary_preferences", read_only=True)
    travel_pace = serializers.CharField(source="profile.travel_pace", read_only=True)
    visited_country_list = serializers.ListField(source="profile.visited_country_list", read_only=True)
    visited_country_count = serializers.IntegerField(source="profile.total_country_visited", read_only=True)
    trip_count = serializers.IntegerField(source="profile.total_trip_count", read_only=True)
    journal_count = serializers.IntegerField(source="profile.total_journal_count", read_only=True)
    emergency_contact_name = serializers.CharField(source="profile.emergency_contact_name", read_only=True)
    emergency_contact_phone = serializers.CharField(source="profile.emergency_contact_phone", read_only=True)

    class Meta:
        model = User
        fields = (
            "name",
            "username",
            "avatar_url",
            "bio",
            "gender",
            "date_of_birth",
            "city",
            "country",
            "preferred_language",
            "preferred_currency",
            "travel_interests",
            "mobility_constraints",
            "dietary_preferences",
            "travel_pace",
            "visited_country_list",
            "visited_country_count",
            "trip_count",
            "journal_count",
            "emergency_contact_name",
            "emergency_contact_phone",
        )
        read_only_fields = fields


class UserUpdateSerializer(serializers.ModelSerializer):
    username = serializers.SlugField(required=False, allow_blank=True)
    bio = serializers.CharField(
        required=False,
        allow_blank=True,
        validators=[validate_bio_word_count],
    )
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.CharField(required=False, allow_blank=True)
    country_of_residence = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=False, allow_blank=True)
    preferred_language = serializers.CharField(required=False, allow_blank=True)
    preferred_currency = serializers.CharField(required=False, allow_blank=True)
    timezone = serializers.CharField(required=False)
    travel_interests = serializers.JSONField(required=False)
    dietary_preferences = serializers.JSONField(required=False)
    travel_pace = serializers.CharField(required=False, allow_blank=True)
    mobility_constraints = serializers.JSONField(required=False)
    emergency_contact_name = serializers.CharField(required=False, allow_blank=True)
    emergency_contact_phone = serializers.CharField(required=False, allow_blank=True)
    is_public_profile = serializers.BooleanField(required=False)
    is_location_sharing_enabled = serializers.BooleanField(required=False)
    is_alert_notification_enabled = serializers.BooleanField(required=False)
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
            "timezone",
            "travel_interests",
            "dietary_preferences",
            "travel_pace",
            "mobility_constraints",
            "emergency_contact_name",
            "emergency_contact_phone",
            "is_public_profile",
            "is_location_sharing_enabled",
            "is_alert_notification_enabled",
            "profile_picture",
            "clear_profile_picture",
            "avatar_url",
        )
        read_only_fields = ("avatar_url",)

    def validate_username(self, value):
        if not value:
            return None
        profile = get_or_create_profile(self.instance)
        queryset = UserProfile.objects.filter(username=value)
        queryset = queryset.exclude(pk=profile.pk)
        if queryset.exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_timezone(self, value):
        validate_timezone_name(value)
        return value

    def validate_travel_interests(self, value):
        return self._normalize_string_list(value, "travel_interests")

    def validate_dietary_preferences(self, value):
        return self._normalize_string_list(value, "dietary_preferences")

    def validate_mobility_constraints(self, value):
        return self._normalize_string_list(value, "mobility_constraints")

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
            "timezone",
            "travel_interests",
            "dietary_preferences",
            "travel_pace",
            "mobility_constraints",
            "emergency_contact_name",
            "emergency_contact_phone",
            "is_public_profile",
            "is_location_sharing_enabled",
            "is_alert_notification_enabled",
        }
        profile = get_or_create_profile(instance)
        previous_timezone = profile.timezone

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
        if profile.timezone != previous_timezone:
            from trips.tasks import reschedule_user_trip_notifications

            transaction.on_commit(
                lambda: reschedule_user_trip_notifications.delay(str(instance.id))
            )
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
            return None
        if UserProfile.objects.filter(username=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def create(self, validated_data):
        username = validated_data.pop("username", None)
        validated_data.pop("confirm_password")
        password = validated_data.pop("password")
        try:
            with transaction.atomic():
                validated_data["provider"] = AccountProvider.PASSWORD
                user = User.objects.create_user(
                    password=password,
                    _defer_onboarding=True,
                    **validated_data,
                )
                if username:
                    profile = get_or_create_profile(user)
                    profile.username = username
                    profile.save(update_fields=["username"])
        except IntegrityError as exc:
            if User.objects.filter(email__iexact=validated_data["email"]).exists():
                raise serializers.ValidationError(
                    {"email": "A user with this email already exists."}
                ) from exc
            if username and UserProfile.objects.filter(username=username).exists():
                raise serializers.ValidationError(
                    {"username": "This username is already taken. Please choose another username."}
                ) from exc
            raise serializers.ValidationError(
                {"non_field_errors": "Could not create user. Please try again."}
            ) from exc
        issue_email_verification_otp(user)
        return user


class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.RegexField(
        regex=r"^\d{4}$",
        error_messages={"invalid": "OTP must be exactly 4 digits."},
    )

    def validate(self, attrs):
        try:
            user = verify_email_otp(email=attrs["email"], otp=attrs["otp"])
        except InvalidVerificationOTP as exc:
            raise serializers.ValidationError({"otp": str(exc)}) from exc
        attrs["user"] = user
        return attrs

    def save(self, **kwargs):
        return build_auth_token_payload(self.validated_data["user"])


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

        if user.provider == AccountProvider.PASSWORD and not user.is_email_verified:
            raise serializers.ValidationError({"error": "Email is not verified."})

        if user.status == AccountStatus.DEACTIVATED or user.deleted_at:
            user.reactivate()

        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])

        return build_auth_token_payload(user)


class GoogleLoginSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=[AccountProvider.GOOGLE])
    firebase_id_token = serializers.CharField(write_only=True)
    google_access_token = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    firebase_uid = serializers.CharField(max_length=128)
    email = serializers.EmailField()
    email_verified = serializers.BooleanField()
    name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    photo_url = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    phone_number = serializers.CharField(max_length=17, required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs):
        try:
            decoded_token = verify_firebase_id_token(attrs["firebase_id_token"])
        except FirebaseVerificationError as exc:
            raise serializers.ValidationError({"firebase_id_token": str(exc)}) from exc

        if decoded_token:
            firebase_uid = decoded_token.get("uid")
            email = decoded_token.get("email")
            if firebase_uid and firebase_uid != attrs["firebase_uid"]:
                raise serializers.ValidationError({"firebase_uid": "Firebase UID does not match the ID token."})
            if email and email.lower() != attrs["email"].lower():
                raise serializers.ValidationError({"email": "Email does not match the Firebase ID token."})
            attrs["email_verified"] = bool(decoded_token.get("email_verified", attrs["email_verified"]))
            attrs["name"] = attrs.get("name") or decoded_token.get("name", "")
            attrs["photo_url"] = attrs.get("photo_url") or decoded_token.get("picture", "")
            attrs["phone_number"] = attrs.get("phone_number") or decoded_token.get("phone_number")

        return attrs

    def save(self, **kwargs):
        email = self.validated_data["email"]
        firebase_uid = self.validated_data["firebase_uid"]

        try:
            with transaction.atomic():
                user = (
                    User.objects.select_for_update()
                    .filter(firebase_uid=firebase_uid)
                    .first()
                )
                if user is None:
                    user = (
                        User.objects.select_for_update()
                        .filter(email__iexact=email)
                        .first()
                    )

                if user is None:
                    user = User.objects.create_user(
                        email=email,
                        password=None,
                        name=self.validated_data.get("name", ""),
                        provider=AccountProvider.GOOGLE,
                        firebase_uid=firebase_uid,
                        firebase_id_token=self.validated_data["firebase_id_token"],
                        google_access_token=self.validated_data.get("google_access_token") or "",
                        is_email_verified=self.validated_data["email_verified"],
                        _defer_onboarding=not self.validated_data["email_verified"],
                    )
                    profile = get_or_create_profile(user)
                    profile.username = build_unique_username_from_email(email)
                else:
                    if not user.is_active:
                        raise serializers.ValidationError({"error": "User is disabled."})

                    if user.status == AccountStatus.DEACTIVATED or user.deleted_at:
                        user.reactivate()

                    user.email = email
                    user.name = self.validated_data.get("name", user.name)
                    user.provider = AccountProvider.GOOGLE
                    user.firebase_uid = firebase_uid
                    user.firebase_id_token = self.validated_data["firebase_id_token"]
                    user.google_access_token = self.validated_data.get("google_access_token") or ""
                    user.is_email_verified = self.validated_data["email_verified"]
                    profile = get_or_create_profile(user)
                    if not profile.username:
                        profile.username = build_unique_username_from_email(email)

                phone_number = self.validated_data.get("phone_number")
                if phone_number is not None:
                    user.phone = phone_number or ""

                photo_url = self.validated_data.get("photo_url")
                if photo_url and not profile.avatar_url:
                    profile.avatar_url = photo_url

                user.last_login = timezone.now()
                user.save(
                    update_fields=[
                        "email",
                        "name",
                        "phone",
                        "provider",
                        "firebase_uid",
                        "firebase_id_token",
                        "google_access_token",
                        "is_email_verified",
                        "last_login",
                    ]
                )
                profile.save(update_fields=["username", "avatar_url"])
        except IntegrityError as exc:
            raise serializers.ValidationError(
                {"error": "Could not complete Google login. Please try again."}
            ) from exc

        if user.is_email_verified:
            user = complete_email_verification(user)
        return build_auth_token_payload(user)


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
