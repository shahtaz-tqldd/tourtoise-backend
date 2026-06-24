from django.db import models
from django.db.models import Max

from app.base.models import BaseModel
from chat.choices import ChatMessageSender


class ChatSession(BaseModel):
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="chat_sessions",
        db_index=True,
    )
    title = models.CharField(max_length=180, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["user", "updated_at"]),
        ]

    def __str__(self):
        return self.title or f"Chat session {self.id}"


class ChatMessage(BaseModel):
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.CharField(max_length=10, choices=ChatMessageSender.choices)
    sequence = models.PositiveIntegerField()
    content = models.TextField()
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["sequence", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["session", "sequence"], name="unique_chat_message_sequence"),
        ]
        indexes = [
            models.Index(fields=["session", "sender"]),
            models.Index(fields=["session", "created_at"]),
        ]

    def __str__(self):
        return f"{self.sender} message {self.sequence} for {self.session_id}"

    @classmethod
    def next_sequence_for_session(cls, session):
        current_max = cls.objects.filter(session=session).aggregate(
            max_sequence=Max("sequence")
        )["max_sequence"]
        return (current_max or 0) + 1
