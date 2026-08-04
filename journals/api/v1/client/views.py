from django.db import transaction
from django.db.models import BooleanField, Count, Exists, OuterRef, Q, Value
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated

from accounts.services.user_profile import decrement_user_journal_count
from app.base.pagination import CustomPagination
from app.utils.response import APIResponse
from journals.api.v1.client.serializers import (
    JournalCommentSerializer,
    JournalCommentWriteSerializer,
    JournalListSerializer,
    JournalWriteSerializer,
)
from journals.models import (
    Journal,
    JournalComment,
    JournalReaction,
    JournalVisibility,
    SavedJournal,
)


class JournalQuerysetMixin:
    def get_base_queryset(self):
        queryset = Journal.objects.select_related("author", "author__profile").prefetch_related(
            "tags", "images"
        ).annotate(
            comments_count=Count("comments", distinct=True),
            saves_count=Count("saved_by_users", distinct=True),
            reactions_count=Count("reactions", distinct=True),
        )
        user = self.request.user
        if user.is_authenticated:
            return queryset.annotate(
                is_saved=Exists(
                    SavedJournal.objects.filter(user=user, journal=OuterRef("pk"))
                ),
                is_reacted=Exists(
                    JournalReaction.objects.filter(user=user, journal=OuterRef("pk"))
                ),
            )
        return queryset.annotate(
            is_saved=Value(False, output_field=BooleanField()),
            is_reacted=Value(False, output_field=BooleanField()),
        )

    def get_accessible_queryset(self):
        queryset = self.get_base_queryset()
        if self.request.user.is_authenticated:
            return queryset.filter(
                Q(visibility=JournalVisibility.PUBLIC) | Q(author=self.request.user)
            )
        return queryset.filter(visibility=JournalVisibility.PUBLIC)

    def get_accessible_journal(self):
        return get_object_or_404(self.get_accessible_queryset(), pk=self.kwargs["journal_id"])

    def get_owned_journal(self):
        return get_object_or_404(
            self.get_base_queryset(),
            pk=self.kwargs["journal_id"],
            author=self.request.user,
        )


class PaginatedJournalMixin:
    pagination_class = CustomPagination

    def paginate_journals(self, queryset, message="Journals fetched successfully."):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        data = JournalListSerializer(page, many=True, context={"request": self.request}).data
        return APIResponse.success(
            data=data,
            meta={
                "count": paginator.page.paginator.count,
                "page": paginator.page.number,
                "page_size": paginator.get_page_size(self.request),
                "num_pages": paginator.page.paginator.num_pages,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            },
            message=message,
        )


class JournalListAPIView(PaginatedJournalMixin, JournalQuerysetMixin, GenericAPIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        queryset = self.get_base_queryset().filter(visibility=JournalVisibility.PUBLIC)
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(content__icontains=search)
                | Q(tags__name__icontains=search)
            )
        tags = [part.strip() for part in request.query_params.get("tags", "").split(",") if part.strip()]
        if tags:
            queryset = queryset.filter(tags__name__in=tags)
        return self.paginate_journals(queryset.distinct().order_by("-created_at"))


class UserJournalListAPIView(PaginatedJournalMixin, JournalQuerysetMixin, GenericAPIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        queryset = self.get_base_queryset().filter(author_id=self.kwargs["user_id"])
        if not request.user.is_authenticated or str(request.user.pk) != str(self.kwargs["user_id"]):
            queryset = queryset.filter(visibility=JournalVisibility.PUBLIC)
        return self.paginate_journals(
            queryset.order_by("-created_at"),
            "User journals fetched successfully.",
        )


class MyJournalListAPIView(PaginatedJournalMixin, JournalQuerysetMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return self.paginate_journals(
            self.get_base_queryset().filter(author=request.user).order_by("-created_at"),
            "Your journals fetched successfully.",
        )


class SavedJournalListAPIView(PaginatedJournalMixin, JournalQuerysetMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        queryset = self.get_accessible_queryset().filter(saved_by_users__user=request.user).order_by(
            "-saved_by_users__created_at"
        )
        return self.paginate_journals(queryset, "Saved journals fetched successfully.")


class JournalCreateAPIView(JournalQuerysetMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = JournalWriteSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        journal = serializer.save()
        journal = self.get_base_queryset().get(pk=journal.pk)
        return APIResponse.success(
            data=JournalListSerializer(journal, context={"request": request}).data,
            message="Journal created successfully.",
            status=status.HTTP_201_CREATED,
        )


class JournalDetailAPIView(JournalQuerysetMixin, GenericAPIView):
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        journal = self.get_accessible_journal()
        return APIResponse.success(
            data=JournalListSerializer(journal, context={"request": request}).data,
            message="Journal fetched successfully.",
        )


class JournalUpdateAPIView(JournalQuerysetMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = JournalWriteSerializer

    def patch(self, request, *args, **kwargs):
        return self._update(request, partial=True)

    def put(self, request, *args, **kwargs):
        return self._update(request, partial=False)

    def _update(self, request, partial):
        journal = self.get_owned_journal()
        serializer = self.get_serializer(
            journal,
            data=request.data,
            partial=partial,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        journal = self.get_base_queryset().get(pk=journal.pk)
        return APIResponse.success(
            data=JournalListSerializer(journal, context={"request": request}).data,
            message="Journal updated successfully.",
        )


class JournalDeleteAPIView(JournalQuerysetMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        journal = self.get_owned_journal()
        author = journal.author
        with transaction.atomic():
            journal.delete()
            decrement_user_journal_count(author)
        return APIResponse.success(message="Journal deleted successfully.")


class JournalSaveAPIView(JournalQuerysetMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        journal = self.get_accessible_journal()
        SavedJournal.objects.get_or_create(
            user=request.user,
            journal=journal,
            defaults={"created_by": request.user, "updated_by": request.user},
        )
        return APIResponse.success(
            data={"journal_id": str(journal.id), "saved": True},
            message="Journal saved successfully.",
        )

    def delete(self, request, *args, **kwargs):
        journal = self.get_accessible_journal()
        SavedJournal.objects.filter(user=request.user, journal=journal).delete()
        return APIResponse.success(
            data={"journal_id": str(journal.id), "saved": False},
            message="Journal removed from saved list successfully.",
        )


class JournalReactionAPIView(JournalQuerysetMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        journal = self.get_accessible_journal()
        JournalReaction.objects.get_or_create(
            user=request.user,
            journal=journal,
            defaults={"created_by": request.user, "updated_by": request.user},
        )
        reactions_count = JournalReaction.objects.filter(journal=journal).count()
        return APIResponse.success(
            data={
                "journal_id": str(journal.id),
                "reacted": True,
                "reactions_count": reactions_count,
            },
            message="Journal reacted successfully.",
        )

    def delete(self, request, *args, **kwargs):
        journal = self.get_accessible_journal()
        JournalReaction.objects.filter(user=request.user, journal=journal).delete()
        reactions_count = JournalReaction.objects.filter(journal=journal).count()
        return APIResponse.success(
            data={
                "journal_id": str(journal.id),
                "reacted": False,
                "reactions_count": reactions_count,
            },
            message="Journal reaction removed successfully.",
        )


class CommentPaginationMixin:
    pagination_class = CustomPagination

    def paginate_comments(self, queryset, message):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        return APIResponse.success(
            data=JournalCommentSerializer(page, many=True).data,
            meta={
                "count": paginator.page.paginator.count,
                "page": paginator.page.number,
                "page_size": paginator.get_page_size(self.request),
                "num_pages": paginator.page.paginator.num_pages,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            },
            message=message,
        )


class JournalCommentListCreateAPIView(CommentPaginationMixin, JournalQuerysetMixin, GenericAPIView):
    serializer_class = JournalCommentWriteSerializer

    def get_permissions(self):
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    def get(self, request, *args, **kwargs):
        journal = self.get_accessible_journal()
        comments = journal.comments.filter(parent__isnull=True).select_related(
            "author", "author__profile"
        ).annotate(replies_count=Count("replies")).order_by("created_at")
        return self.paginate_comments(comments, "Comments fetched successfully.")

    def post(self, request, *args, **kwargs):
        journal = self.get_accessible_journal()
        serializer = self.get_serializer(
            data=request.data,
            context={"request": request, "journal": journal},
        )
        serializer.is_valid(raise_exception=True)
        comment = serializer.save()
        comment.replies_count = 0
        return APIResponse.success(
            data=JournalCommentSerializer(comment).data,
            message="Comment created successfully.",
            status=status.HTTP_201_CREATED,
        )


class CommentReplyListCreateAPIView(CommentPaginationMixin, JournalQuerysetMixin, GenericAPIView):
    serializer_class = JournalCommentWriteSerializer

    def get_permissions(self):
        return [AllowAny()] if self.request.method == "GET" else [IsAuthenticated()]

    def get_parent(self, journal):
        return get_object_or_404(
            JournalComment.objects.select_related("journal"),
            pk=self.kwargs["comment_id"],
            journal=journal,
            parent__isnull=True,
        )

    def get(self, request, *args, **kwargs):
        parent = self.get_parent(self.get_accessible_journal())
        replies = parent.replies.select_related("author", "author__profile").annotate(
            replies_count=Value(0)
        ).order_by("created_at")
        return self.paginate_comments(replies, "Replies fetched successfully.")

    def post(self, request, *args, **kwargs):
        journal = self.get_accessible_journal()
        parent = self.get_parent(journal)
        serializer = self.get_serializer(
            data=request.data,
            context={"request": request, "journal": journal, "parent": parent},
        )
        serializer.is_valid(raise_exception=True)
        reply = serializer.save()
        reply.replies_count = 0
        return APIResponse.success(
            data=JournalCommentSerializer(reply).data,
            message="Reply created successfully.",
            status=status.HTTP_201_CREATED,
        )


class CommentDeleteAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        comment = get_object_or_404(
            JournalComment,
            pk=self.kwargs["comment_id"],
            author=request.user,
        )
        comment.delete()
        return APIResponse.success(message="Comment deleted successfully.")


class CommentUpdateAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = JournalCommentWriteSerializer

    def patch(self, request, *args, **kwargs):
        return self._update(request, partial=True)

    def put(self, request, *args, **kwargs):
        return self._update(request, partial=False)

    def _update(self, request, partial):
        comment = get_object_or_404(
            JournalComment.objects.select_related("author", "author__profile").annotate(
                replies_count=Count("replies")
            ),
            pk=self.kwargs["comment_id"],
            author=request.user,
        )
        serializer = self.get_serializer(
            comment,
            data=request.data,
            partial=partial,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        comment = serializer.save()
        return APIResponse.success(
            data=JournalCommentSerializer(comment).data,
            message="Comment updated successfully.",
        )
