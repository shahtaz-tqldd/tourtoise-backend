from django.db import models
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
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["session", "sender"]),
            models.Index(fields=["session", "created_at"]),
        ]

    def __str__(self):
        return f"{self.sender} message for {self.session_id}"
