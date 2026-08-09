from django.contrib.auth import get_user_model
from rest_framework import serializers

from journals.models import ContentReport, ContentReportTarget

User = get_user_model()


class ReportUserSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="profile.username", read_only=True)

    class Meta:
        model = User
        fields = ("id", "email", "name", "username")
        read_only_fields = fields


class AdminContentReportSerializer(serializers.ModelSerializer):
    reporter = ReportUserSerializer(read_only=True)
    reviewed_by = ReportUserSerializer(read_only=True)
    target = serializers.SerializerMethodField()

    class Meta:
        model = ContentReport
        fields = (
            "id",
            "reporter",
            "target_type",
            "target",
            "reason",
            "status",
            "admin_comment",
            "reviewed_by",
            "reviewed_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_target(self, report):
        if report.target_type == ContentReportTarget.JOURNAL:
            journal = report.journal
            return {
                "id": str(journal.id),
                "content": journal.content,
                "visibility": journal.visibility,
                "author": ReportUserSerializer(journal.author).data,
                "deleted_at": journal.deleted_at,
            }

        comment = report.comment
        return {
            "id": str(comment.id),
            "journal_id": str(comment.journal_id),
            "parent_id": str(comment.parent_id) if comment.parent_id else None,
            "text": comment.text,
            "image_url": comment.image_url,
            "author": ReportUserSerializer(comment.author).data,
            "deleted_at": comment.deleted_at,
        }


class ReviewContentReportSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=("accept", "reject"))
    admin_comment = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        max_length=2000,
    )

    def validate(self, attrs):
        if attrs["action"] == "accept" and not attrs.get("admin_comment"):
            raise serializers.ValidationError(
                {"admin_comment": "Admin comment is required when accepting a report."}
            )
        return attrs
