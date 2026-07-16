from django.db import transaction
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from app.utils.response import APIResponse
from trips.api.v1.client.serializers import (
    TripChatCreateMessageSerializer,
    TripChatMessageSerializer,
    TripChatSessionSerializer,
)
from trips.choices import AgentMessageSender
from trips.models import TripAgentConversationSession, TripAgentMessage
from trips.services import create_agent_message

from .mixin import UserTripQuerysetMixin


DEMO_TRIP_CHAT_REPLY = (
    "Thanks for the message. The trip planning agent is not connected to this chat yet, "
    "so this is a demo reply for now."
)


class TripChatSessionMixin(UserTripQuerysetMixin):
    def get_trip(self):
        return get_object_or_404(self.get_trip_queryset(), pk=self.kwargs["trip_id"])

    def get_session_queryset(self):
        return TripAgentConversationSession.objects.filter(
            trip__user=self.request.user,
            trip_id=self.kwargs["trip_id"],
        ).annotate(messages_count=Count("messages", distinct=True))

    def get_session(self):
        return get_object_or_404(
            self.get_session_queryset(),
            pk=self.kwargs["session_id"],
        )

    def get_or_create_session(self, trip):
        session_id = self.kwargs["session_id"]
        session = (
            TripAgentConversationSession.objects.select_for_update()
            .filter(
                pk=session_id,
                trip=trip,
                user=self.request.user,
            )
            .first()
        )
        if session:
            return session

        existing_session = TripAgentConversationSession.objects.filter(pk=session_id).first()
        if existing_session:
            raise Http404

        return TripAgentConversationSession.objects.create(
            id=session_id,
            trip=trip,
            user=self.request.user,
            current_step=trip.current_step,
            metadata={"source": "trip_chat"},
            created_by=self.request.user,
            updated_by=self.request.user,
        )


class TripChatMessageListAPIView(TripChatSessionMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        session = self.get_session()
        messages = TripAgentMessage.objects.filter(session=session).order_by("sequence", "created_at")

        return APIResponse.success(
            data= TripChatMessageSerializer(messages, many=True).data,
            message="Trip chat messages fetched successfully.",
        )


class TripChatCreateMessageAPIView(TripChatSessionMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TripChatCreateMessageSerializer

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        trip = self.get_trip()
        session = self.get_or_create_session(trip)

        user_message = create_agent_message(
            session=session,
            sender=AgentMessageSender.USER,
            content=serializer.validated_data["message"],
            user=request.user,
        )
        agent_message = create_agent_message(
            session=session,
            sender=AgentMessageSender.AGENT,
            content=DEMO_TRIP_CHAT_REPLY,
            payload={"demo": True},
            user=request.user,
        )

        session.updated_by = request.user
        session.save(update_fields=["updated_by", "updated_at"])
        trip.updated_by = request.user
        trip.save(update_fields=["updated_by", "updated_at"])

        session.messages_count = session.messages.count()

        return APIResponse.success(
            data={
                "session": TripChatSessionSerializer(session).data,
                "user_message": TripChatMessageSerializer(user_message).data,
                "agent_message": TripChatMessageSerializer(agent_message).data,
            },
            message="Trip chat message created successfully.",
            status=status.HTTP_201_CREATED,
        )
