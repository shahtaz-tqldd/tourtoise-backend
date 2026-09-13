import json
import logging
from copy import deepcopy
from typing import Optional
from uuid import uuid4

from django.conf import settings

from google.adk.apps.app import App
from google.adk.runners import Runner
from google.adk.sessions.database_session_service import DatabaseSessionService

from .agents import ADKAgent
from trips.choices import PlanningStep

# utils
from .helpers import call_agent_async


logger = logging.getLogger(__name__)


DEFAULT_STRUCTURED_RESPONSE = {
    "question": "Could you tell me what kind of trip experience you prefer?",
    "is_qna_complete": False,
    "context": None,
}

DEFAULT_RECOMMENDATIONS_RESPONSE = {
    "is_discovery_complete": False,
    "attraction_ids": [],
    "activity_ids": [],
    "cuisine_ids": [],
    "messages": {
        "attractions": "",
        "activities": "",
        "cuisines": "",
    },
}

DEFAULT_ITINERARY_RESPONSE = {
    "is_itinerary_complete": False,
    "title": "",
    "summary": "",
    "day_wise_plan": [],
    "route_plan": [],
    "rough_budget": {},
    "message": "",
}

DEFAULT_PREPARATION_RESPONSE = {
    "is_preparation_complete": False,
    "title": "",
    "summary": "",
    "packing_items": [],
    "required_documents": [],
    "heads_up": [],
    "message": "",
}


class PlanAgentClient:
    """Service class for the trip preference planning agent with ADK session persistence."""

    def __init__(
        self,
        trip,
        planning_step: PlanningStep = PlanningStep.PREFERENCE,
        destination_id: str | list[str] | None = None,
        trip_context: dict | None = None,
    ):
        self.trip = trip
        self.planning_step = planning_step
        self.destination_id = destination_id
        self.app_name = "tourtoise_planning_agent"
        self.session_service = None
        self.app = None
        self.root_agent = None

        try:
            self.session_service = DatabaseSessionService(db_url=settings.ADK_DB_URL)
            self.root_agent = ADKAgent().root_agent(
                planning_step=self.planning_step,
                destination_id=self.destination_id,
            )
            self.app = App(
                name=self.app_name,
                root_agent=self.root_agent,
            )
        except Exception as exc:
            logger.error(
                "PlanAgentClient initialization failed; falling back to default response. "
                "trip_id=%s planning_step=%s error_type=%s error=%s",
                getattr(self.trip, "id", None),
                self.planning_step,
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
                    "trip_id=%s user_id=%s session_id=%s planning_step=%s error=%s",
                    getattr(self.trip, "id", None),
                    user_id,
                    session_id,
                    self.planning_step,
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
                "ADK session creation failed. trip_id=%s user_id=%s planning_step=%s",
                getattr(self.trip, "id", None),
                user_id,
                self.planning_step,
            )
            raise

        return new_session.id


    async def run_agent(
        self,
        user_query: str,
        user_id: str,
        session_id: Optional[str] = None,
        preferences: Optional[dict] = None,
        trip_snapshot: Optional[dict] = None,
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

        enriched_query = self._build_enriched_query(user_query, preferences or {}, trip_snapshot or {})

        agent_response = await call_agent_async(
            runner=runner,
            user_id=user_id,
            session_id=active_session_id,
            query=enriched_query,
            planning_step=self.planning_step,
        )
        qna_response = agent_response.qna_response
        
        if not qna_response:
            logger.error(
                "PlanAgentClient received no valid structured response; using default. "
                "trip_id=%s user_id=%s session_id=%s planning_step=%s response_text_preview=%r "
                "total_tokens=%s intention=%s",
                getattr(self.trip, "id", None),
                user_id,
                active_session_id,
                self.planning_step,
                (agent_response.response_text or "")[:500],
                agent_response.total_tokens,
                agent_response.intention,
            )
            qna_response = self._default_response()
        
        return {
            "session_id": active_session_id,
            "response": qna_response,
            "cost": agent_response.cost,
            "total_tokens": agent_response.total_tokens,
            "input_tokens": agent_response.input_tokens,
            "output_tokens": agent_response.output_tokens,
            "model": settings.PLANNING_AGENT_MODEL,
            "intention": agent_response.intention,
        }

    def _build_enriched_query(self, user_query: str, preferences: dict, trip_snapshot: dict) -> str:
        if self.planning_step in {PlanningStep.ITINERARY, PlanningStep.PREPARATION}:
            context = {"trip_planning_context": trip_snapshot}
        else:
            context = {
                "preferences": preferences,
                "trip": trip_snapshot,
            }
        return f"{user_query}\n\nCONTEXT_JSON:\n{_compact_json(context)}"

    def _fallback_response(self, session_id: Optional[str], reason: str) -> dict:
        fallback_session_id = session_id or str(uuid4())
        logger.error(
            "PlanAgentClient returning DEFAULT_STRUCTURED_RESPONSE. reason=%s trip_id=%s "
            "session_id=%s planning_step=%s",
            reason,
            getattr(self.trip, "id", None),
            fallback_session_id,
            self.planning_step,
        )
        return {
            "session_id": fallback_session_id,
            "response": self._default_response(),
            "cost": None,
            "total_tokens": None,
            "input_tokens": None,
            "output_tokens": None,
            "model": settings.PLANNING_AGENT_MODEL,
            "intention": None,
        }

    def _default_response(self) -> dict:
        if self.planning_step == PlanningStep.RECOMMENDATION:
            return deepcopy(DEFAULT_RECOMMENDATIONS_RESPONSE)
        if self.planning_step == PlanningStep.ITINERARY:
            return deepcopy(DEFAULT_ITINERARY_RESPONSE)
        if self.planning_step == PlanningStep.PREPARATION:
            return deepcopy(DEFAULT_PREPARATION_RESPONSE)
        return deepcopy(DEFAULT_STRUCTURED_RESPONSE)


def _compact_json(value: dict) -> str:
    """Serialize agent context once, without whitespace-only token overhead."""
    return json.dumps(
        _without_empty_values(value),
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _without_empty_values(value):
    if isinstance(value, dict):
        return {
            key: compacted
            for key, item in value.items()
            if (compacted := _without_empty_values(item)) not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [
            compacted
            for item in value
            if (compacted := _without_empty_values(item)) not in (None, "", [], {})
        ]
    return value
