import logging
import time
from typing import Optional

from django.conf import settings
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App, EventsCompactionConfig
from google.adk.runners import Runner
from google.adk.sessions.database_session_service import DatabaseSessionService

from .agents import DiscoveryADKAgent
from .helpers import call_agent_async


logger = logging.getLogger(__name__)

FALLBACK_MESSAGE = (
    "I'm sorry, I couldn't reach the destination assistant just now. Please try again."
)


class DiscoveryAgentClient:
    """ADK client for conversational destination discovery."""

    app_name = "tourtoise_discovery_agent"

    def __init__(self, user, source_session_id: str):
        self.user = user
        self.source_session_id = source_session_id
        self.session_service = None
        self.app = None
        try:
            self.session_service = DatabaseSessionService(db_url=settings.ADK_DB_URL)
            root_agent = DiscoveryADKAgent(user, source_session_id).root_agent()
            self.app = App(
                name=self.app_name,
                root_agent=root_agent,
                events_compaction_config=EventsCompactionConfig(
                    compaction_interval=4, overlap_size=1
                ),
                context_cache_config=ContextCacheConfig(
                    cache_intervals=12, ttl_seconds=1800, min_tokens=4048
                ),
            )
        except Exception:
            logger.exception("DiscoveryAgentClient initialization failed")

    async def _get_or_create_session(self, user_id: str, session_id: Optional[str]):
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
                logger.exception("Could not restore discovery ADK session; creating another")
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
    ):
        started_at = time.monotonic()
        if not self.session_service or not self.app:
            return self._fallback(session_id, started_at)
        try:
            active_session_id = await self._get_or_create_session(user_id, session_id)
            response = await call_agent_async(
                Runner(app=self.app, session_service=self.session_service),
                user_id=user_id,
                session_id=active_session_id,
                query=user_query.strip(),
            )
        except Exception:
            logger.exception("Discovery agent execution failed")
            return self._fallback(session_id, started_at)

        if not response.structured:
            return self._fallback(active_session_id, started_at)
        handoff = response.structured.get("handoff")
        if handoff:
            # These provenance values belong to the application, not the model.
            handoff["source"] = "turtle_chat"
            handoff["source_session_id"] = self.source_session_id
        return {
            "session_id": active_session_id,
            "response": response.structured,
            "meta": {
                "query_intention": response.structured["intention"],
                "token_usage": response.total_tokens,
                "cost": response.cost,
                "time": round(time.monotonic() - started_at, 3),
                "fallback": False,
            },
        }

    def _fallback(self, session_id, started_at):
        return {
            "session_id": session_id,
            "response": {
                "message": FALLBACK_MESSAGE,
                "intention": None,
                "destinations": [],
                "handoff": None,
            },
            "meta": {
                "query_intention": None,
                "token_usage": 0,
                "cost": 0.0,
                "time": round(time.monotonic() - started_at, 3),
                "fallback": True,
            },
        }

