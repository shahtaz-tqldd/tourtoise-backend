from django.urls import path

from journals.api.v1.client import views


urlpatterns = [
    path("list/", views.JournalListAPIView.as_view(), name="journal-list"),
    path("create/", views.JournalCreateAPIView.as_view(), name="journal-create"),
    path("mine/list/", views.MyJournalListAPIView.as_view(), name="my-journal-list"),
    path("saved/list/", views.SavedJournalListAPIView.as_view(), name="saved-journal-list"),
    path("users/<uuid:user_id>/list/", views.UserJournalListAPIView.as_view(), name="user-journal-list"),
    path("<uuid:journal_id>/detail/", views.JournalDetailAPIView.as_view(), name="journal-detail"),
    path("<uuid:journal_id>/update/", views.JournalUpdateAPIView.as_view(), name="journal-update"),
    path("<uuid:journal_id>/delete/", views.JournalDeleteAPIView.as_view(), name="journal-delete"),
    path("<uuid:journal_id>/save/", views.JournalSaveAPIView.as_view(), name="journal-save"),
    path("<uuid:journal_id>/react/", views.JournalReactionAPIView.as_view(), name="journal-react"),
    path("<uuid:journal_id>/report/", views.JournalReportCreateAPIView.as_view(), name="journal-report"),
    path(
        "<uuid:journal_id>/comments/",
        views.JournalCommentListCreateAPIView.as_view(),
        name="journal-comment-list-create",
    ),
    path(
        "<uuid:journal_id>/comments/<uuid:comment_id>/replies/",
        views.CommentReplyListCreateAPIView.as_view(),
        name="journal-reply-list-create",
    ),
    path(
        "comments/<uuid:comment_id>/update/",
        views.CommentUpdateAPIView.as_view(),
        name="journal-comment-update",
    ),
    path(
        "comments/<uuid:comment_id>/delete/",
        views.CommentDeleteAPIView.as_view(),
        name="journal-comment-delete",
    ),
    path(
        "comments/<uuid:comment_id>/report/",
        views.CommentReportCreateAPIView.as_view(),
        name="journal-comment-report",
    ),
]
