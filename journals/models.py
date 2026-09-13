from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from app.base.models import BaseImage, BaseModel


class JournalVisibility(models.TextChoices):
    PUBLIC = "public", "Public"
    PRIVATE = "private", "Private"


class ContentReportTarget(models.TextChoices):
    JOURNAL = "journal", "Journal"
    COMMENT = "comment", "Comment"


class ContentReportStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"


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
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["visibility", "-created_at"])]

    def __str__(self):
        return f"Journal by {self.author}"

    def soft_delete(self):
        if self.deleted_at is None:
            self.deleted_at = timezone.now()
            self.save(update_fields=["deleted_at", "updated_at"])


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
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

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

    def soft_delete(self):
        if self.deleted_at is None:
            self.deleted_at = timezone.now()
            self.save(update_fields=["deleted_at", "updated_at"])


class ContentReport(BaseModel):
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="journal_content_reports",
    )
    target_type = models.CharField(max_length=10, choices=ContentReportTarget.choices)
    journal = models.ForeignKey(
        Journal,
        on_delete=models.CASCADE,
        related_name="reports",
        null=True,
        blank=True,
    )
    comment = models.ForeignKey(
        JournalComment,
        on_delete=models.CASCADE,
        related_name="reports",
        null=True,
        blank=True,
    )
    reason = models.TextField()
    status = models.CharField(
        max_length=10,
        choices=ContentReportStatus.choices,
        default=ContentReportStatus.PENDING,
    )
    admin_comment = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_journal_content_reports",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "target_type", "-created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        target_type=ContentReportTarget.JOURNAL,
                        journal__isnull=False,
                        comment__isnull=True,
                    )
                    | models.Q(
                        target_type=ContentReportTarget.COMMENT,
                        journal__isnull=True,
                        comment__isnull=False,
                    )
                ),
                name="content_report_has_matching_target",
            ),
            models.UniqueConstraint(
                fields=["reporter", "journal"],
                condition=models.Q(
                    status=ContentReportStatus.PENDING,
                    target_type=ContentReportTarget.JOURNAL,
                ),
                name="unique_pending_journal_report_per_user",
            ),
            models.UniqueConstraint(
                fields=["reporter", "comment"],
                condition=models.Q(
                    status=ContentReportStatus.PENDING,
                    target_type=ContentReportTarget.COMMENT,
                ),
                name="unique_pending_comment_report_per_user",
            ),
        ]

    @property
    def target_author(self):
        target = self.journal if self.target_type == ContentReportTarget.JOURNAL else self.comment
        return target.author

    def __str__(self):
        return f"{self.target_type} report by {self.reporter}"


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


class JournalReaction(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="journal_reactions",
    )
    journal = models.ForeignKey(Journal, on_delete=models.CASCADE, related_name="reactions")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "journal"],
                name="unique_journal_reaction_user_journal",
            )
        ]
