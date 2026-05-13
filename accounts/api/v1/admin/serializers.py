from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

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


class AccountListSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="profile.username", read_only=True)
    location = serializers.CharField(source="profile.location", read_only=True)
    public_profile = serializers.BooleanField(source="profile.is_public_profile", read_only=True)
    last_active_at = serializers.DateTimeField(source="last_login", read_only=True)
    travel_style = serializers.CharField(source="profile.travel_style", read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "username",
            "name",
            "location",
            "phone",
            "status",
            "travel_style",
            "public_profile",
            "is_staff",
            "is_superuser",
            "is_email_verified",
            "last_active_at",
            "created_at",
        )
        read_only_fields = fields
