from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from app.base.pagination import CustomPagination
from app.utils.response import APIResponse
from chat.choices import ChatMessageSender
from chat.models import ChatMessage, ChatSession
from chat.api.v1.client.serializers import (
    ChatMessageSerializer,
    ChatQuestionSerializer,
    ChatSessionCreateSerializer,
    ChatSessionSerializer,
)


FALLBACK_AGENT_ANSWER = (
    "Thanks for your question. The chat agent is not connected yet, "
    "so this is a fallback response for now."
)


class ChatPaginationMixin:
    pagination_class = CustomPagination

    def paginate_with_meta(self, queryset, serializer_class, message):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        serializer = serializer_class(page, many=True, context={"request": self.request})
        return APIResponse.success(
            data=serializer.data,
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


class ChatQuerysetMixin:
    def get_session_queryset(self):
        return ChatSession.objects.filter(user=self.request.user).annotate(
            messages_count=Count("messages", distinct=True),
        )

    def get_owned_session(self):
        return get_object_or_404(
            ChatSession.objects.filter(user=self.request.user),
            pk=self.kwargs["session_id"],
        )


class ChatSessionListAPIView(ChatPaginationMixin, ChatQuerysetMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        queryset = self.get_session_queryset()
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(messages__content__icontains=search)
            ).distinct()

        return self.paginate_with_meta(
            queryset.order_by("-updated_at"),
            ChatSessionSerializer,
            "Chat sessions fetched successfully.",
        )


class ChatSessionCreateAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatSessionCreateSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = ChatSession.objects.create(
            user=request.user,
            title=serializer.validated_data.get("title", ""),
            created_by=request.user,
            updated_by=request.user,
        )
        session.messages_count = 0
        session.last_message = None
        return APIResponse.success(
            data=ChatSessionSerializer(session, context={"request": request}).data,
            message="Chat session created successfully.",
            status=status.HTTP_201_CREATED,
        )


class ChatSessionDeleteAPIView(ChatQuerysetMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        self.get_owned_session().delete()
        return APIResponse.success(message="Chat session deleted successfully.")


class ChatSessionMessageListAPIView(ChatPaginationMixin, ChatQuerysetMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        session = self.get_owned_session()
        queryset = ChatMessage.objects.filter(session=session)
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(content__icontains=search)

        return self.paginate_with_meta(
            queryset.order_by("sequence", "created_at"),
            ChatMessageSerializer,
            "Chat messages fetched successfully.",
        )


class ChatQuestionAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatQuestionSerializer

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session_id = serializer.validated_data.get("session_id")
        message = serializer.validated_data["message"]

        if session_id:
            session = get_object_or_404(
                ChatSession.objects.select_for_update().filter(user=request.user),
                pk=session_id,
            )
        else:
            session = ChatSession.objects.create(
                user=request.user,
                title=message[:180],
                created_by=request.user,
                updated_by=request.user,
            )

        user_message = ChatMessage.objects.create(
            session=session,
            sender=ChatMessageSender.USER,
            sequence=ChatMessage.next_sequence_for_session(session),
            content=message,
            created_by=request.user,
            updated_by=request.user,
        )
        agent_message = ChatMessage.objects.create(
            session=session,
            sender=ChatMessageSender.AGENT,
            sequence=user_message.sequence + 1,
            content=FALLBACK_AGENT_ANSWER,
            payload={"fallback": True},
            created_by=request.user,
            updated_by=request.user,
        )

        if not session.title:
            session.title = message[:180]
        session.updated_by = request.user
        session.save(update_fields=["title", "updated_by", "updated_at"])

        return APIResponse.success(
            data={
                "session_id": str(session.id),
                "user_message": ChatMessageSerializer(user_message).data,
                "agent_message": ChatMessageSerializer(agent_message).data,
            },
            message="Chat message created successfully.",
            status=status.HTTP_201_CREATED,
        )
