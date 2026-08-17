"""Domain services for a trip's post-planning conversation."""

from asgiref.sync import async_to_sync
from django.utils import timezone

from trips.choices import TripStatus
from trips.models import TripConversationMessage, TripConversationSession


TRIP_CHAT_CLOSED_STATUSES = frozenset(
    {
        TripStatus.COMPLETED,
        TripStatus.CANCELLED,
        TripStatus.ARCHIVED,
    }
)


def is_trip_chat_open(trip) -> bool:
    """Return whether the traveler may add another message to this trip chat."""
    return trip.status not in TRIP_CHAT_CLOSED_STATUSES


def get_or_create_conversation_session(trip, user, plan_ready=None):
    """Return the trip's single conversation and keep its active flag accurate."""
    if plan_ready is None:
        # Imported lazily while the planning services are being split into
        # smaller domain modules.
        from trips.services.services import is_trip_plan_ready

        plan_ready = is_trip_plan_ready(trip)

    should_be_active = bool(plan_ready and is_trip_chat_open(trip))
    conversation_session, _ = TripConversationSession.objects.get_or_create(
        trip=trip,
        defaults={
            "user": user,
            "is_active": should_be_active,
            "created_by": user,
            "updated_by": user,
        },
    )
    if conversation_session.is_active != should_be_active:
        conversation_session.is_active = should_be_active
        conversation_session.updated_by = user
        conversation_session.save(
            update_fields=["is_active", "updated_by", "updated_at"]
        )
    return conversation_session


def close_conversation_session(trip, user=None, at=None) -> int:
    """Deactivate an existing conversation without creating a new one."""
    at = at or timezone.now()
    updates = {
        "is_active": False,
        "updated_at": at,
    }
    if user is not None:
        updates["updated_by"] = user
    return TripConversationSession.objects.filter(
        trip=trip,
        is_active=True,
    ).update(**updates)


def create_conversation_message(
    session,
    sender,
    content="",
    metadata=None,
    user=None,
    read_at=None,
):
    actor = user or session.user
    return TripConversationMessage.objects.create(
        session=session,
        sender=sender,
        content=content or "",
        metadata=metadata or {},
        read_at=read_at,
        created_by=actor,
        updated_by=actor,
    )


def run_guide_agent_for_session(session, user_query):
    """Run the guide against the persistent ADK session for this trip chat."""
    from trips.agents.guide_agent import GuideAgentClient
    from trips.services.services import build_trip_guide_context

    client = GuideAgentClient(
        session.trip,
        trip_context=build_trip_guide_context(session.trip),
    )
    result = async_to_sync(client.run_agent)(
        user_query=user_query,
        user_id=str(session.user_id),
        session_id=session.external_session_id or str(session.id),
    )
    _update_external_session_id(session, result.get("session_id"))
    return result


def push_trip_message_to_agent_context(message, *, event_id=None) -> dict:
    """Copy an outbound scheduled message into the guide's ADK event history."""
    from trips.agents.guide_agent import GuideAgentClient

    session = message.session
    client = GuideAgentClient(session.trip, initialize_app=False)
    event_id = event_id or f"trip-message-{message.id}"
    result = async_to_sync(client.append_message_event)(
        content=message.content,
        user_id=str(session.user_id),
        session_id=session.external_session_id or str(session.id),
        event_id=event_id,
        metadata={
            "trip_id": str(session.trip_id),
            "conversation_id": str(session.id),
            "message_id": str(message.id),
            "source": "scheduled_trip_message",
        },
    )
    _update_external_session_id(session, result.get("session_id"))

    message_metadata = dict(message.metadata or {})
    message_metadata["agent_context"] = {
        "event_id": event_id,
        "synced": True,
    }
    message.metadata = message_metadata
    message.save(update_fields=["metadata", "updated_at"])
    return result


def _update_external_session_id(session, external_session_id):
    external_session_id = external_session_id or ""
    if external_session_id and session.external_session_id != external_session_id:
        session.external_session_id = external_session_id
        session.save(update_fields=["external_session_id", "updated_at"])
