from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class DiscoveryIntent(str, Enum):
    DESTINATION_RECOMMENDATION = "destination_recommendation"
    DESTINATION_QUESTION = "destination_question"
    DESTINATION_COMPARISON = "destination_comparison"
    REFINE_RECOMMENDATION = "refine_recommendation"
    START_TRIP_PLANNING = "start_trip_planning"
    GENERAL_TRAVEL_QUESTION = "general_travel_question"
    OUT_OF_SCOPE = "out_of_scope"


class DestinationRecommendation(BaseModel):
    destination_slug: str
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
    destination_slug: str
    departure_location: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    preferred_month: Optional[str] = None
    duration_days: Optional[int] = Field(default=None, ge=1)
    traveller_type: Optional[str] = None
    traveller_count: Optional[int] = None
    budget_tier: Optional[str] = None
    interests: list[str] = Field(default_factory=list)
    dietary_preferences: list[str] = Field(default_factory=list)
    mobility_constraints: list[str] = Field(default_factory=list)
    source: str = "turtle_chat"
    source_session_id: str

    @model_validator(mode="after")
    def validate_trip_dates(self):
        if self.duration_days is None and self.end_date is None:
            raise ValueError("Either duration_days or end_date is required.")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date.")
        return self


class DiscoveryAgentResponse(BaseModel):
    message: str = Field(description="Helpful, natural-language response to the user.")
    intention: DiscoveryIntent
    destinations: list[DestinationRecommendation] = Field(
        default_factory=list,
        max_length=3,
    )
    handoff: Optional[TripPlanningHandoff] = None
