from rest_framework import serializers

from trips.models import Trip


class AdminTripListUserSerializer(serializers.Serializer):
    name = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    username = serializers.CharField(read_only=True)
    avatar_url = serializers.URLField(source="profile.avatar_url", read_only=True)


class AdminTripPlanningUsageSerializer(serializers.Serializer):
    cost = serializers.FloatField(source="planning_cost", read_only=True)
    tokens = serializers.IntegerField(source="planning_total_tokens", read_only=True)


class AdminTripChatUsageSerializer(serializers.Serializer):
    total_message = serializers.IntegerField(
        source="trip_chat_messages_count",
        read_only=True,
    )
    cost = serializers.FloatField(source="trip_chat_cost", read_only=True)
    tokens = serializers.IntegerField(source="trip_chat_total_tokens", read_only=True)


class AdminTripPrimaryDestinationSerializer(serializers.Serializer):
    name = serializers.CharField(read_only=True)
    country = serializers.CharField(read_only=True)
    region = serializers.CharField(read_only=True)


class AdminTripListSerializer(serializers.ModelSerializer):
    user = AdminTripListUserSerializer(read_only=True)
    planning = AdminTripPlanningUsageSerializer(source="*", read_only=True)
    trip_chat = AdminTripChatUsageSerializer(source="*", read_only=True)
    primary_destination = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = (
            "id",
            "title",
            "user",
            "status",
            "start_date",
            "end_date",
            "primary_destination",
            "planning",
            "trip_chat",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_primary_destination(self, obj):
        primary_destinations = getattr(obj, "prefetched_primary_destinations", [])
        if not primary_destinations:
            return None
        return AdminTripPrimaryDestinationSerializer(
            primary_destinations[0].destination,
        ).data


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
            "origin_city",
            "origin_country",
            "total_budget",
            "budget_currency",
            "preferences",
            "planning_summary",
            "agent_context",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
