from django.db import models


class ChatMessageSender(models.TextChoices):
    USER = "user", "User"
    AGENT = "agent", "Agent"
