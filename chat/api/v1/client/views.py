from asgiref.sync import async_to_sync
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from app.base.pagination import CustomPagination
from app.utils.response import APIResponse
from accounts.choices import CreditTransactionType
from accounts.services.credit import CreditService, InsufficientCreditsError
from analytics.choices import AIUsageType
from analytics.services.ai_usage import record_ai_usage
from chat.choices import ChatMessageSender
from chat.models import ChatMessage, ChatSession
from chat.agents.discovery_agent import DiscoveryAgentClient
from chat.api.v1.client.serializers import (
    ChatMessageSerializer,
    ChatQuestionSerializer,
    ChatSessionCreateSerializer,
    ChatSessionSerializer,
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
            queryset.order_by("created_at"),
            ChatMessageSerializer,
            "Chat messages fetched successfully.",
        )


class ChatQuestionAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChatQuestionSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session_id = serializer.validated_data.get("session_id")
        message = serializer.validated_data["message"]

        try:
            CreditService.ensure_credits(
                user=request.user,
                amount=CreditService.AGENT_CHAT_COST,
            )
        except InsufficientCreditsError as exc:
            return APIResponse.error(
                errors={"credit": [str(exc)]},
                message="Insufficient credits.",
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        try:
            with CreditService.charge_agent_generation(
                user=request.user,
                amount=CreditService.AGENT_CHAT_COST,
                transaction_type=CreditTransactionType.AGENT_CHAT,
                description="Discovery chat agent response",
                metadata={"endpoint": "ChatQuestionAPIView"},
            ) as credit_transaction:
                with transaction.atomic():
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
                        content=message,
                        created_by=request.user,
                        updated_by=request.user,
                    )

                external_session_id = session.metadata.get("discovery_agent_session_id")
                result = async_to_sync(
                    DiscoveryAgentClient(
                        request.user,
                        source_session_id=str(session.id),
                    ).run_agent
                )(
                    user_query=message,
                    user_id=str(request.user.id),
                    session_id=external_session_id,
                )
                record_ai_usage(
                    user=request.user,
                    usage_type=AIUsageType.CHAT,
                    cost=result["meta"].get("cost") or 0,
                    tokens=result["meta"].get("token_usage") or 0,
                )
            credit_spent = abs(credit_transaction.amount) if credit_transaction else 0
        except InsufficientCreditsError as exc:
            return APIResponse.error(
                errors={"credit": [str(exc)]},
                message="Insufficient credits.",
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        response = result["response"]
        agent_metadata = {
            **result["meta"],
            "destinations": response.get("destinations", []),
            "handoff": response.get("handoff"),
        }

        with transaction.atomic():
            session = ChatSession.objects.select_for_update().get(
                pk=session.pk,
                user=request.user,
            )
            agent_message = ChatMessage.objects.create(
                session=session,
                sender=ChatMessageSender.AGENT,
                content=response["message"],
                metadata=agent_metadata,
                created_by=request.user,
                updated_by=request.user,
            )

            metadata = dict(session.metadata)
            if result.get("session_id"):
                metadata["discovery_agent_session_id"] = result["session_id"]
            if response.get("handoff"):
                metadata["trip_planning_handoff"] = response["handoff"]
            session.metadata = metadata
            if not session.title:
                session.title = message[:180]
            session.updated_by = request.user
            session.save(
                update_fields=["title", "metadata", "updated_by", "updated_at"]
            )

        return APIResponse.success(
            data={
                "session_id": str(session.id),
                "user_message": ChatMessageSerializer(user_message).data,
                "agent_message": ChatMessageSerializer(agent_message).data,
                "handoff": response.get("handoff"),
            },
            meta={"credit_spent": credit_spent},
            message="Chat message created successfully.",
            status=status.HTTP_201_CREATED,
        )
