from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import CreditRequest, UserProfile
from app.utils.cloudinary import delete_image, upload_image

User = get_user_model()


class AdminLoginSerializer(serializers.Serializer):
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
            raise serializers.ValidationError({"error": "Admin account is disabled."})

        if not user.is_staff:
            raise serializers.ValidationError({"error": "This account does not have admin access."})

        user.last_login = timezone.now()
        user.save(update_fields=["last_login"])

        refresh = RefreshToken.for_user(user)

        return {
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
        }


class AdminDetailsSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="profile.username", read_only=True)
    avatar_url = serializers.URLField(source="profile.avatar_url", read_only=True)
    last_active_at = serializers.DateTimeField(source="last_login", read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "name",
            "phone",
            "status",
            "username",
            "avatar_url",
            "is_active",
            "is_staff",
            "is_superuser",
            "is_email_verified",
            "last_active_at",
            "created_at",
        )
        read_only_fields = fields


class UpdateAdminInfoSerializer(serializers.Serializer):
    fullname = serializers.CharField(max_length=50, required=False, allow_blank=False)
    avatar = serializers.ImageField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide fullname or avatar to update.")
        return attrs

    def update(self, instance, validated_data):
        fullname = validated_data.get("fullname")
        avatar = validated_data.get("avatar")
        profile, _ = UserProfile.objects.get_or_create(user=instance)

        if fullname is not None:
            instance.name = fullname
            instance.save(update_fields=["name", "updated_at"])

        if avatar is not None:
            previous_avatar_url = profile.avatar_url
            upload = upload_image(
                avatar,
                folder=f"{settings.CLOUDINARY_FOLDER}/admins",
                public_id=f"admin-{instance.pk}-{uuid4().hex}",
            )
            profile.avatar_url = upload["url"]
            profile.save(update_fields=["avatar_url"])
            instance._state.fields_cache["profile"] = profile
            if previous_avatar_url and previous_avatar_url != profile.avatar_url:
                delete_image(image_url=previous_avatar_url)

        return instance


class UpdateAdminPasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    confirm_new_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_new_password"]:
            raise serializers.ValidationError(
                {"confirm_new_password": "Passwords do not match."},
            )
        if attrs["current_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": "New password must be different from the current password."},
            )
        validate_password(attrs["new_password"], self.context["request"].user)
        return attrs

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


class AccountMessageCountSerializer(serializers.Serializer):
    chat_message = serializers.IntegerField(source="chat_message_count", read_only=True)
    trip_message = serializers.IntegerField(source="trip_message_count", read_only=True)


class AccountListSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="profile.username", read_only=True)
    location = serializers.CharField(source="profile.location", read_only=True)
    avatar_url = serializers.URLField(source="profile.avatar_url", read_only=True)
    public_profile = serializers.BooleanField(source="profile.is_public_profile", read_only=True)
    last_active_at = serializers.DateTimeField(source="last_login", read_only=True)
    trip_plan_count = serializers.IntegerField(read_only=True)
    credit = serializers.IntegerField(source="credit_balance", read_only=True)
    message_count = AccountMessageCountSerializer(source="*", read_only=True)
    journal_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "username",
            "name",
            "avatar_url",
            "location",
            "status",
            "public_profile",
            "is_email_verified",
            "trip_plan_count",
            "credit",
            "message_count",
            "journal_count",
            "last_active_at",
            "created_at",
        )
        read_only_fields = fields


class CreditRequestUserSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="profile.username", read_only=True)

    class Meta:
        model = User
        fields = ("id", "email", "name", "username")
        read_only_fields = fields


class AdminCreditRequestSerializer(serializers.ModelSerializer):
    user = CreditRequestUserSerializer(read_only=True)
    reviewed_by = CreditRequestUserSerializer(read_only=True)

    class Meta:
        model = CreditRequest
        fields = (
            "id",
            "user",
            "reason",
            "status",
            "approved_amount",
            "reviewed_by",
            "reviewed_at",
            "credit_transaction_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ReviewCreditRequestSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=("approve", "reject"))
    amount = serializers.IntegerField(required=False, min_value=1, max_value=2147483647)

    def validate(self, attrs):
        if attrs["action"] == "approve" and "amount" not in attrs:
            raise serializers.ValidationError(
                {"amount": "Amount is required when approving a credit request."}
            )
        if attrs["action"] == "reject" and "amount" in attrs:
            raise serializers.ValidationError(
                {"amount": "Amount must not be provided when rejecting a credit request."}
            )
        return attrs
