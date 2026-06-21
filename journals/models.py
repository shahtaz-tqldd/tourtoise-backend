from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from app.base.models import BaseImage, BaseModel


class JournalVisibility(models.TextChoices):
    PUBLIC = "public", "Public"
    PRIVATE = "private", "Private"


class JournalTag(BaseModel):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Journal(BaseModel):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="journals",
    )
    content = models.TextField()
    visibility = models.CharField(
        max_length=10,
        choices=JournalVisibility.choices,
        default=JournalVisibility.PUBLIC,
        db_index=True,
    )
    tags = models.ManyToManyField(JournalTag, related_name="journals", blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["visibility", "-created_at"])]

    def __str__(self):
        return f"Journal by {self.author}"


class JournalImage(BaseImage):
    journal = models.ForeignKey(Journal, on_delete=models.CASCADE, related_name="images")


class JournalComment(BaseModel):
    journal = models.ForeignKey(Journal, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="journal_comments",
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="replies",
        null=True,
        blank=True,
    )
    text = models.TextField(blank=True)
    image_url = models.URLField(blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["journal", "parent", "created_at"])]

    def clean(self):
        if not self.text.strip() and not self.image_url:
            raise ValidationError("A comment must contain text or an image.")
        if self.parent_id:
            if self.parent.parent_id:
                raise ValidationError("Replies cannot have nested replies.")
            if self.parent.journal_id != self.journal_id:
                raise ValidationError("Reply and parent must belong to the same journal.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class SavedJournal(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_journals",
    )
    journal = models.ForeignKey(Journal, on_delete=models.CASCADE, related_name="saved_by_users")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "journal"],
                name="unique_saved_journal_user_journal",
            )
        ]
