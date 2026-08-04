import logging
from typing import Optional

from django.conf import settings
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App, EventsCompactionConfig
from google.adk.runners import Runner
from google.adk.sessions.database_session_service import DatabaseSessionService

from .agents import ADKGuideAgent
from .helpers import call_agent_async


logger = logging.getLogger(__name__)

DEFAULT_RESPONSE = (
    "I’m sorry, I couldn’t reach your trip guide just now. Please try your question again."
)


class GuideAgentClient:
    """Google ADK client for a trip's persistent post-planning conversation."""

    def __init__(self, trip, trip_context: dict | None = None):
        self.trip = trip
        self.trip_context = trip_context or {}
        self.app_name = "tourtoise_guide_agent"
        self.session_service = None
        self.app = None

        try:
            self.session_service = DatabaseSessionService(db_url=settings.ADK_DB_URL)
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
                "GuideAgentClient initialization failed. trip_id=%s",
                getattr(self.trip, "id", None),
            )

    async def _get_or_create_session(
        self,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> str:
        if session_id:
            try:
                session = await self.session_service.get_session(
                    app_name=self.app_name,
                    user_id=user_id,
                    session_id=session_id,
                )
                if session:
                    return session.id
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
        )
        return session.id

    async def run_agent(
        self,
        user_query: str,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> dict:
        if not self.session_service or not self.app:
            return self._fallback_response(session_id)

        try:
            active_session_id = await self._get_or_create_session(user_id, session_id)
            response = await call_agent_async(
                runner=Runner(app=self.app, session_service=self.session_service),
                user_id=user_id,
                session_id=active_session_id,
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
            "session_id": active_session_id,
            "response": response.text_response or DEFAULT_RESPONSE,
            "cost": response.cost,
            "total_tokens": response.total_tokens,
        }

    @staticmethod
    def _fallback_response(session_id: Optional[str]) -> dict:
        return {
            "session_id": session_id or "",
            "response": DEFAULT_RESPONSE,
            "cost": None,
            "total_tokens": None,
        }
