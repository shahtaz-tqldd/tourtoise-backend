import logging
from typing import Optional
from uuid import uuid4

from django.conf import settings

from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import App, EventsCompactionConfig
from google.adk.runners import Runner
from google.adk.sessions.database_session_service import DatabaseSessionService

from .agents import ADKAgent

# utils
from .helpers import call_agent_async


logger = logging.getLogger(__name__)


RESPONSE_STRUCTURE = {
    "session_id": "1",
    "response": {
        "message": "text_message",
        "destinations": []
    },
    "meta":{
        "query_intention": "intention",
        "token_usage": 1,
        "cost": 10.5,
        "time": 2.4
    }
}

class DiscoveryAgentClient:
    """
    This agent help user to discover destination and 
    help user pick perfect destination for tour answering their answer
    """

    def __init__(self, user):
        self.app_name = "tourtoise_discovery_agent"
        self.session_service = None
        self.app = None
        self.root_agent = None

        try:
            self.session_service = DatabaseSessionService(db_url=settings.ADK_DB_URL)
            self.root_agent = ADKAgent().root_agent()
            self.app = App(
                name=self.app_name,
                root_agent=self.root_agent,
                events_compaction_config=EventsCompactionConfig(
                    compaction_interval=4,
                    overlap_size=1
                ),
                context_cache_config=ContextCacheConfig(
                    cache_intervals=12,
                    ttl_seconds=1800,
                    min_tokens=4048
                )
            )
        except Exception as exc:
            logger.error(
                "DiscoveryAgentClient initialization failed; falling back to default response. "
                "error_type=%s error=%s",
                type(exc).__name__,
                type(exc.__cause__).__name__ if exc.__cause__ else None,
                
            )
            self.session_service = None
            self.app = None
            self.root_agent = None


    async def _get_or_create_session(
        self,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> str:
        """Get existing session or create a new one (async)."""
        if session_id:
            try:
                session = await self.session_service.get_session(
                    app_name=self.app_name,
                    user_id=user_id,
                    session_id=session_id
                )
                if session:
                    return session.id
                
            except Exception as exc:
                logger.exception(
                    "ADK session retrieval failed; creating a new session. "
                    "trip_id=%s user_id=%s session_id=%s current_step=%s error=%s",
                    getattr(self.trip, "id", None),
                    user_id,
                    session_id,
                    self.current_step,
                    exc,
                )

        # Create new session
        try:
            new_session = await self.session_service.create_session(
                app_name=self.app_name,
                user_id=user_id
            )
        except Exception:
            logger.exception(
                "ADK session creation failed. trip_id=%s user_id=%s current_step=%s",
                getattr(self.trip, "id", None),
                user_id,
                self.current_step,
            )
            raise

        return new_session.id


    async def run_agent(
        self,
        user_query: str,
        user_id: str,
        session_id: Optional[str] = None
    ) -> dict:
        """Process a chat message and return the agent's response."""
        user_query = user_query.strip()

        if not self.session_service or not self.app:
            return self._fallback_response(session_id, reason="client_not_initialized")

        active_session_id = await self._get_or_create_session(user_id, session_id)

        runner = Runner(
          app=self.app, 
          session_service=self.session_service
        )

        agent_response = await call_agent_async(
            runner=runner,
            user_id=user_id,
            session_id=active_session_id,
            query=user_query
        )

        text_message = agent_response.text_message
        time_taken = 0
        
        return {
            "session_id": active_session_id,
            "response": {
                "message": text_message,
            },
            "meta":{
                "query_intention": agent_response.query_intention,
                "token_usage": agent_response.token_usage,
                "cost": agent_response.cost,
                "time": time_taken
            }
        }


    def _fallback_response(self, session_id: Optional[str], reason: str) -> dict:
        fallback_session_id = session_id or str(uuid4())
        
        FALLBACK_MESSAGE = "I am sorry, I couldn't generate any response due to technical difficulties."
        
        time_taken = 0
        
        return {
            "session_id": fallback_session_id,
            "response": {
                "message": FALLBACK_MESSAGE,
            },
            "meta":{
                "query_intention": None,
                "token_usage": 0,
                "cost": 0.0,
                "time": time_taken
            }
        }
