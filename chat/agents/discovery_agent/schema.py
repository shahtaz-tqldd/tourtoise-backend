from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DiscoveryIntent(str, Enum):
    DESTINATION_RECOMMENDATION = "destination_recommendation"
    DESTINATION_QUESTION = "destination_question"
    DESTINATION_COMPARISON = "destination_comparison"
    REFINE_RECOMMENDATION = "refine_recommendation"
    START_TRIP_PLANNING = "start_trip_planning"
    GENERAL_TRAVEL_QUESTION = "general_travel_question"
    OUT_OF_SCOPE = "out_of_scope"


class DestinationRecommendation(BaseModel):
    destination_id: str
    name: str
    country: str
    why_it_matches: str
    matched_preferences: list[str] = Field(default_factory=list)
    ideal_duration: Optional[str] = None
    budget_tier: Optional[str] = None
    seasonal_suitability: Optional[str] = None
    concern_or_tradeoff: Optional[str] = None
    previously_visited: bool = False


class TripPlanningHandoff(BaseModel):
    destination_id: str
    departure_location: Optional[str] = None
    start_date: Optional[str] = None
    preferred_month: Optional[str] = None
    duration_days: Optional[int] = None
    traveller_type: Optional[str] = None
    traveller_count: Optional[int] = None
    budget_tier: Optional[str] = None
    interests: list[str] = Field(default_factory=list)
    dietary_preferences: list[str] = Field(default_factory=list)
    mobility_constraints: list[str] = Field(default_factory=list)
    source: str = "turtle_chat"
    source_session_id: str


class DiscoveryAgentResponse(BaseModel):
    message: str = Field(description="Helpful, natural-language response to the user.")
    intention: DiscoveryIntent
    destinations: list[DestinationRecommendation] = Field(
        default_factory=list,
        max_length=3,
    )
    handoff: Optional[TripPlanningHandoff] = None
