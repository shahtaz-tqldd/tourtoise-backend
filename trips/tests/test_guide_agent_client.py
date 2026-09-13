from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from trips.agents.guide_agent.client import GUIDE_AGENT_NAME, GuideAgentClient


class GuideAgentClientEventTests(IsolatedAsyncioTestCase):
    async def test_appends_scheduled_message_as_model_event(self):
        session = SimpleNamespace(id="adk-session-1", events=[])
        session_service = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            create_session=AsyncMock(),
            append_event=AsyncMock(),
        )
        client = GuideAgentClient.__new__(GuideAgentClient)
        client.trip = SimpleNamespace(id="trip-1")
        client.app_name = "tourtoise_guide_agent"
        client.session_service = session_service
        client.app = object()

        result = await client.append_message_event(
            content="How was your first day in Dhaka?",
            user_id="user-1",
            session_id=session.id,
            event_id="scheduled-trip-event-1",
            metadata={"source": "scheduled_trip_message"},
        )

        self.assertEqual(result["session_id"], session.id)
        event = session_service.append_event.await_args.kwargs["event"]
        self.assertEqual(event.id, "scheduled-trip-event-1")
        self.assertEqual(event.author, GUIDE_AGENT_NAME)
        self.assertEqual(event.content.role, "model")
        self.assertEqual(event.content.parts[0].text, "How was your first day in Dhaka?")
        self.assertEqual(event.custom_metadata["source"], "scheduled_trip_message")

    async def test_does_not_append_duplicate_event(self):
        existing_event = SimpleNamespace(id="scheduled-trip-event-1")
        session = SimpleNamespace(id="adk-session-1", events=[existing_event])
        session_service = SimpleNamespace(
            get_session=AsyncMock(return_value=session),
            create_session=AsyncMock(),
            append_event=AsyncMock(),
        )
        client = GuideAgentClient.__new__(GuideAgentClient)
        client.trip = SimpleNamespace(id="trip-1")
        client.app_name = "tourtoise_guide_agent"
        client.session_service = session_service
        client.app = object()

        await client.append_message_event(
            content="How was your first day in Dhaka?",
            user_id="user-1",
            session_id=session.id,
            event_id=existing_event.id,
        )

        session_service.append_event.assert_not_awaited()

    async def test_recreates_missing_session_with_requested_stable_id(self):
        session = SimpleNamespace(id="stable-session-id", events=[])
        session_service = SimpleNamespace(
            get_session=AsyncMock(return_value=None),
            create_session=AsyncMock(return_value=session),
            append_event=AsyncMock(),
        )
        client = GuideAgentClient.__new__(GuideAgentClient)
        client.trip = SimpleNamespace(id="trip-1")
        client.app_name = "tourtoise_guide_agent"
        client.session_service = session_service
        client.app = None

        await client.append_message_event(
            content="How was your first day in Dhaka?",
            user_id="user-1",
            session_id=session.id,
            event_id="scheduled-trip-event-1",
        )

        session_service.create_session.assert_awaited_once_with(
            app_name=client.app_name,
            user_id="user-1",
            session_id=session.id,
        )
