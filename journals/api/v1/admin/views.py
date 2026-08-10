from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from accounts.permissions import IsAdmin
from accounts.services.user_profile import decrement_user_journal_count
from app.base.pagination import CustomPagination
from app.utils.response import APIResponse
from journals.api.v1.admin.serializers import (
    AdminContentReportSerializer,
    ReviewContentReportSerializer,
)
from journals.models import (
    ContentReport,
    ContentReportStatus,
    ContentReportTarget,
    Journal,
    JournalComment,
)
from notification.services import create_general_notification


class AdminContentReportListAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = AdminContentReportSerializer
    pagination_class = CustomPagination

    def get(self, request, *args, **kwargs):
        queryset = ContentReport.objects.select_related(
            "reporter__profile",
            "reviewed_by__profile",
            "journal__author__profile",
            "comment__author__profile",
        )

        report_status = request.query_params.get("status")
        if report_status:
            valid_statuses = {choice.value for choice in ContentReportStatus}
            if report_status not in valid_statuses:
                return self._invalid_filter("status", "Invalid report status.")
            queryset = queryset.filter(status=report_status)

        target_type = request.query_params.get("target_type")
        if target_type:
            valid_targets = {choice.value for choice in ContentReportTarget}
            if target_type not in valid_targets:
                return self._invalid_filter("target_type", "Invalid report target type.")
            queryset = queryset.filter(target_type=target_type)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return APIResponse.success(
            data=self.get_serializer(page, many=True).data,
            meta={
                "count": paginator.page.paginator.count,
                "page": paginator.page.number,
                "page_size": paginator.get_page_size(request),
                "num_pages": paginator.page.paginator.num_pages,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            },
            message="Content reports fetched successfully.",
        )

    @staticmethod
    def _invalid_filter(field, message):
        return APIResponse.error(
            errors={field: [message]},
            message=message,
            status=status.HTTP_400_BAD_REQUEST,
        )


class AdminContentReportReviewAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = ReviewContentReportSerializer

    def patch(self, request, pk, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            report = get_object_or_404(
                ContentReport.objects.select_for_update(of=("self",)).select_related(
                    "reporter__profile",
                    "reviewed_by__profile",
                    "journal__author__profile",
                    "comment__author__profile",
                ),
                pk=pk,
            )
            if report.status != ContentReportStatus.PENDING:
                return APIResponse.error(
                    errors={"detail": ["This report has already been reviewed."]},
                    message="This report has already been reviewed.",
                    status=status.HTTP_400_BAD_REQUEST,
                )

            action = serializer.validated_data["action"]
            report.status = (
                ContentReportStatus.ACCEPTED
                if action == "accept"
                else ContentReportStatus.REJECTED
            )
            report.admin_comment = serializer.validated_data.get("admin_comment", "")
            report.reviewed_by = request.user
            report.reviewed_at = timezone.now()
            report.updated_by = request.user

            if action == "accept":
                self._remove_reported_content(report, request.user)

            report.save(
                update_fields=[
                    "status",
                    "admin_comment",
                    "reviewed_by",
                    "reviewed_at",
                    "updated_by",
                    "updated_at",
                ]
            )

        return APIResponse.success(
            data=AdminContentReportSerializer(report).data,
            message=f"Report {report.status} successfully.",
        )

    @staticmethod
    def _remove_reported_content(report, admin):
        if report.target_type == ContentReportTarget.JOURNAL:
            target = Journal.objects.select_for_update().select_related("author").get(
                pk=report.journal_id
            )
            target_label = "journal"
        else:
            target = JournalComment.objects.select_for_update().select_related("author").get(
                pk=report.comment_id
            )
            target_label = "comment"

        if target.deleted_at is not None:
            return

        target.deleted_at = timezone.now()
        target.updated_by = admin
        target.save(update_fields=["deleted_at", "updated_by", "updated_at"])
        if report.target_type == ContentReportTarget.JOURNAL:
            report.journal = target
            decrement_user_journal_count(target.author)
        else:
            report.comment = target

        notification_kwargs = {
            "recipient": target.author,
            "title": f"Your {target_label} was removed",
            "message": report.admin_comment,
            "metadata": {
                "moderation_report_id": str(report.id),
                "target_type": report.target_type,
                "target_id": str(target.id),
            },
            "created_by": admin,
        }
        transaction.on_commit(
            lambda kwargs=notification_kwargs: create_general_notification(**kwargs)
        )
