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
from trips.models import TripConversationMessage, TripConversationSession
from trips.services import (
    create_conversation_message,
    get_or_create_conversation_session,
    is_trip_plan_ready,
    run_guide_agent_for_session,
)

from .mixin import UserTripQuerysetMixin


class TripChatSessionMixin(UserTripQuerysetMixin):
    def get_trip(self):
        return get_object_or_404(self.get_trip_queryset(), pk=self.kwargs["trip_id"])

    def get_session_queryset(self):
        return TripConversationSession.objects.filter(
            trip__user=self.request.user,
            trip_id=self.kwargs["trip_id"],
        )

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

        return APIResponse.success(
            data= TripChatMessageSerializer(messages, many=True).data,
            message="Trip chat messages fetched successfully.",
        )


class TripChatCreateMessageAPIView(TripChatSessionMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TripChatCreateMessageSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        trip = self.get_trip()
        if not is_trip_plan_ready(trip):
            return self.plan_not_ready_response()
        session = self.get_session(trip)
        if session is None:
            raise Http404

        user_message = create_conversation_message(
            session=session,
            sender=AgentMessageSender.USER,
            content=serializer.validated_data["message"],
            user=request.user,
        )

        agent_result = run_guide_agent_for_session(
            session=session,
            user_query=serializer.validated_data["message"],
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
