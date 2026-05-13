from rest_framework import serializers

from trips.models import Trip


class AdminTripListSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_name = serializers.CharField(source="user.name", read_only=True)
    destinations_count = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = (
            "id",
            "title",
            "user_email",
            "user_name",
            "status",
            "visibility",
            "planning_source",
            "start_date",
            "end_date",
            "nights",
            "travelers_count",
            "destinations_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_destinations_count(self, obj):
        return obj.trip_destinations.count()


class AdminTripDetailSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_name = serializers.CharField(source="user.name", read_only=True)

    class Meta:
        model = Trip
        fields = (
            "id",
            "share_token",
            "title",
            "user",
            "user_email",
            "user_name",
            "status",
            "visibility",
            "planning_source",
            "start_date",
            "end_date",
            "nights",
            "travelers_count",
            "trip_pace",
            "origin_city",
            "origin_country",
            "total_budget",
            "budget_currency",
            "preferences",
            "constraints",
            "traveler_profile_snapshot",
            "planning_summary",
            "agent_context",
            "latest_plan_version",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
