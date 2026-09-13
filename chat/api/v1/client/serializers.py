from rest_framework import serializers

from chat.models import ChatMessage, ChatSession


class ChatSessionSerializer(serializers.ModelSerializer):
    messages_count = serializers.IntegerField(read_only=True)
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = ChatSession
        fields = (
            "id",
            "title",
            "is_active",
            "messages_count",
            "last_message",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_last_message(self, obj):
        message = getattr(obj, "last_message", None)
        if message is None and getattr(obj, "pk", None):
            message = obj.messages.order_by("-created_at").first()
        if not message:
            return None
        return {
            "id": str(message.id),
            "sender": message.sender,
            "content": message.content,
            "created_at": message.created_at,
        }


class ChatSessionCreateSerializer(serializers.Serializer):
    title = serializers.CharField(
        max_length=180,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
    )


class ChatMessageSerializer(serializers.ModelSerializer):
    session_id = serializers.UUIDField(read_only=True)
    metadata = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = (
            "id",
            "session_id",
            "sender",
            "content",
            "metadata",
            "created_at",
        )
        read_only_fields = fields

    def get_metadata(self, obj):
        metadata = obj.metadata or {}
        return {
            key: value
            for key, value in metadata.items()
            if key not in {"cost", "token_usage"}
        }


class ChatQuestionSerializer(serializers.Serializer):
    session_id = serializers.UUIDField(required=False)
    message = serializers.CharField(allow_blank=False, trim_whitespace=True)
