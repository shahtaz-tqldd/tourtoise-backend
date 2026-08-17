import logging
from typing import Optional

from django.conf import settings
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App, EventsCompactionConfig
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions.database_session_service import DatabaseSessionService
from google.genai import types

from .agents import ADKGuideAgent
from .helpers import call_agent_async


logger = logging.getLogger(__name__)

DEFAULT_RESPONSE = (
    "I’m sorry, I couldn’t reach your trip guide just now. Please try your question again."
)
GUIDE_AGENT_NAME = "trip_guide_agent"


class GuideAgentClient:
    """Google ADK client for a trip's persistent post-planning conversation."""

    def __init__(
        self,
        trip,
        trip_context: dict | None = None,
        *,
        initialize_app: bool = True,
    ):
        self.trip = trip
        self.trip_context = trip_context or {}
        self.app_name = "tourtoise_guide_agent"
        self.session_service = None
        self.app = None

        try:
            self.session_service = DatabaseSessionService(db_url=settings.ADK_DB_URL)
        except Exception:
            logger.exception(
                "Guide ADK session service initialization failed. trip_id=%s",
                getattr(self.trip, "id", None),
            )
            return

        if not initialize_app:
            return

        try:
            root_agent = ADKGuideAgent().root_agent(trip_context=self.trip_context)
            self.app = App(
                name=self.app_name,
                root_agent=root_agent,
                events_compaction_config=EventsCompactionConfig(
                    compaction_interval=4,
                    overlap_size=1,
                ),
                context_cache_config=ContextCacheConfig(
                    cache_intervals=12,
                    ttl_seconds=1800,
                    min_tokens=4048,
                ),
            )
        except Exception:
            logger.exception(
                "Guide agent app initialization failed. trip_id=%s",
                getattr(self.trip, "id", None),
            )

    async def _get_or_create_session(
        self,
        user_id: str,
        session_id: Optional[str] = None,
    ):
        if session_id:
            try:
                session = await self.session_service.get_session(
                    app_name=self.app_name,
                    user_id=user_id,
                    session_id=session_id,
                )
                if session:
                    return session
            except Exception:
                logger.exception(
                    "Guide ADK session lookup failed; creating a new session. "
                    "trip_id=%s user_id=%s session_id=%s",
                    getattr(self.trip, "id", None),
                    user_id,
                    session_id,
                )

        session = await self.session_service.create_session(
            app_name=self.app_name,
            user_id=user_id,
            session_id=session_id,
        )
        return session

    async def run_agent(
        self,
        user_query: str,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> dict:
        if not self.session_service or not self.app:
            return self._fallback_response(session_id)

        try:
            active_session = await self._get_or_create_session(user_id, session_id)
            response = await call_agent_async(
                runner=Runner(app=self.app, session_service=self.session_service),
                user_id=user_id,
                session_id=active_session.id,
                query=user_query.strip(),
            )
        except Exception:
            logger.exception(
                "Guide agent execution failed. trip_id=%s user_id=%s",
                getattr(self.trip, "id", None),
                user_id,
            )
            return self._fallback_response(session_id)

        return {
            "session_id": active_session.id,
            "response": response.text_response or DEFAULT_RESPONSE,
            "cost": response.cost,
            "total_tokens": response.total_tokens,
        }

    async def append_message_event(
        self,
        *,
        content: str,
        user_id: str,
        session_id: Optional[str] = None,
        event_id: str,
        metadata: dict | None = None,
    ) -> dict:
        """Add an outbound guide message to ADK history without invoking the model."""
        if not self.session_service:
            raise RuntimeError("Guide ADK session service is unavailable.")

        try:
            active_session = await self._get_or_create_session(user_id, session_id)
            if any(event.id == event_id for event in active_session.events):
                return {"session_id": active_session.id, "event_id": event_id}

            event = Event(
                id=event_id,
                invocation_id=event_id,
                author=GUIDE_AGENT_NAME,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=content.strip())],
                ),
                custom_metadata=metadata or {},
                turn_complete=True,
            )
            await self.session_service.append_event(
                session=active_session,
                event=event,
            )
            return {"session_id": active_session.id, "event_id": event.id}
        except Exception:
            logger.exception(
                "Failed to append scheduled guide message to ADK history. "
                "trip_id=%s user_id=%s event_id=%s",
                getattr(self.trip, "id", None),
                user_id,
                event_id,
            )
            raise

    @staticmethod
    def _fallback_response(session_id: Optional[str]) -> dict:
        return {
            "session_id": session_id or "",
            "response": DEFAULT_RESPONSE,
            "cost": None,
            "total_tokens": None,
        }
