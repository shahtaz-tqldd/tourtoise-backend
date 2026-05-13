from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


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
