from django.urls import path

from chat.api.v1.client import views


urlpatterns = [
    path("sessions/list/", views.ChatSessionListAPIView.as_view(), name="chat-session-list"),
    path("sessions/create/", views.ChatSessionCreateAPIView.as_view(), name="chat-session-create"),
    path(
        "sessions/<uuid:session_id>/messages/",
        views.ChatSessionMessageListAPIView.as_view(),
        name="chat-session-messages",
    ),
    path(
        "sessions/<uuid:session_id>/delete/",
        views.ChatSessionDeleteAPIView.as_view(),
        name="chat-session-delete",
    ),
    path("ask/", views.ChatQuestionAPIView.as_view(), name="chat-ask"),
]
