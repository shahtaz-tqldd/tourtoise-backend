from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from app.utils.response import APIResponse
from accounts.choices import CreditTransactionType
from accounts.services.credit import CreditService, InsufficientCreditsError
from analytics.choices import AIUsageType
from analytics.services.ai_usage import record_ai_usage
from trips.api.v1.client.serializers import (
    TripChatCreateMessageSerializer,
    TripChatMessageSerializer,
    TripChatSessionSerializer,
)
from trips.choices import AgentMessageSender, TripStatus
from trips.models import TripConversationMessage
from trips.services.services import is_trip_plan_ready
from trips.services.trip_chat import (
    create_conversation_message,
    get_or_create_conversation_session,
    is_trip_chat_open,
    run_guide_agent_for_session,
)

from .mixin import UserTripQuerysetMixin


class TripChatSessionMixin(UserTripQuerysetMixin):
    def get_trip(self):
        return get_object_or_404(self.get_trip_queryset(), pk=self.kwargs["trip_id"])

    def get_session(self, trip):
        session = get_or_create_conversation_session(
            trip,
            self.request.user,
            plan_ready=True,
        )
        requested_session_id = self.kwargs.get("session_id")
        if requested_session_id and requested_session_id != session.id:
            # Keep the legacy session-id URL safe while the client migrates to
            # /trips/{trip_id}/chat/*. A trip can never select another session.
            return None
        return session

    def plan_not_ready_response(self):
        return APIResponse.error(
            message="Trip chat is available after the trip plan is ready.",
            errors={"trip_plan": ["Complete preference Q&A, recommendations, itinerary, and preparation first."]},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def chat_closed_response(self, trip):
        if trip.status == TripStatus.COMPLETED:
            message = "Trip chat is closed because this trip has been completed."
        else:
            message = "Trip chat is closed for this trip."
        return APIResponse.error(
            message=message,
            errors={
                "trip_status": [
                    "Messages cannot be sent after a trip is completed or closed."
                ]
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


class TripChatMessageListAPIView(TripChatSessionMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        trip = self.get_trip()
        if not is_trip_plan_ready(trip):
            return self.plan_not_ready_response()

        session = self.get_session(trip)
        if session is None:
            raise Http404
        messages = TripConversationMessage.objects.filter(session=session).order_by("created_at")
        unread_count = messages.filter(
            sender=AgentMessageSender.AGENT,
            read_at__isnull=True,
        ).count()

        return APIResponse.success(
            data=TripChatMessageSerializer(messages, many=True).data,
            meta={"unread_count": unread_count},
            message="Trip chat messages fetched successfully.",
        )


class TripChatReadAllAPIView(TripChatSessionMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, *args, **kwargs):
        trip = self.get_trip()
        if not is_trip_plan_ready(trip):
            return self.plan_not_ready_response()
        session = self.get_session(trip)
        if session is None:
            raise Http404

        read_at = timezone.now()
        marked_read_count = TripConversationMessage.objects.filter(
            session=session,
            sender=AgentMessageSender.AGENT,
            read_at__isnull=True,
        ).update(read_at=read_at, updated_by=request.user, updated_at=read_at)
        return APIResponse.success(
            data={
                "conversation_id": str(session.id),
                "marked_read_count": marked_read_count,
                "unread_count": 0,
                "read_at": read_at,
            },
            message="Trip chat messages marked as read.",
        )


class TripChatCreateMessageAPIView(TripChatSessionMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TripChatCreateMessageSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        trip = self.get_trip()
        if not is_trip_chat_open(trip):
            return self.chat_closed_response(trip)
        if not is_trip_plan_ready(trip):
            return self.plan_not_ready_response()
        session = self.get_session(trip)
        if session is None:
            raise Http404

        try:
            with CreditService.charge_agent_generation(
                user=request.user,
                amount=CreditService.TRIP_CHAT_COST,
                transaction_type=CreditTransactionType.TRIP_CHAT,
                description="Trip chat agent response",
                metadata={
                    "endpoint": "TripChatCreateMessageAPIView",
                    "trip_id": str(trip.id),
                },
            ) as credit_transaction:
                user_message = create_conversation_message(
                    session=session,
                    sender=AgentMessageSender.USER,
                    content=serializer.validated_data["message"],
                    user=request.user,
                    read_at=timezone.now(),
                )

                agent_result = run_guide_agent_for_session(
                    session=session,
                    user_query=serializer.validated_data["message"],
                )
                record_ai_usage(
                    user=request.user,
                    trip=trip,
                    usage_type=AIUsageType.TRIP_CHAT,
                    cost=agent_result.get("cost") or 0,
                    tokens=agent_result.get("total_tokens") or 0,
                )
            credit_spent = abs(credit_transaction.amount) if credit_transaction else 0
        except InsufficientCreditsError as exc:
            return APIResponse.error(
                errors={"credit": [str(exc)]},
                message="Insufficient credits.",
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        agent_message = create_conversation_message(
            session=session,
            sender=AgentMessageSender.AGENT,
            content=agent_result["response"],
            metadata={
                "cost": agent_result.get("cost"),
                "total_tokens": agent_result.get("total_tokens"),
            },
            user=request.user,
            read_at=timezone.now(),
        )

        session.updated_by = request.user
        session.save(update_fields=["updated_by", "updated_at"])

        session.messages_count = session.messages.count()

        return APIResponse.success(
            data={
                "session": TripChatSessionSerializer(session).data,
                "user_message": TripChatMessageSerializer(user_message).data,
                "agent_message": TripChatMessageSerializer(agent_message).data,
            },
            meta={"credit_spent": credit_spent},
            message="Trip chat message created successfully.",
            status=status.HTTP_201_CREATED,
        )
