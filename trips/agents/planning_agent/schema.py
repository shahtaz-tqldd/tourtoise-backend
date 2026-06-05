from typing import Optional
from pydantic import BaseModel, Field


class TripPreferenceQNAResponse(BaseModel):
    question: Optional[str] = Field(
        default=None,
        description="The next question to ask the user. Must be null when QNA is complete.",
    )
    is_qna_complete: bool = Field(
        description="True when enough preference context has been collected.",
    )
    context: Optional[str] = Field(
        default=None,
        description="Short summarized traveler preference context. Must be null until QNA is complete.",
    )


class TripRecommendationMessages(BaseModel):
    tour_spots: str = Field(default="")
    activities: str = Field(default="")
    foods: str = Field(default="")


class TripDestinationRecommendationsResponse(BaseModel):
    is_discovery_complete: bool = Field(
        description="True when destination item recommendations have been selected.",
    )
    tour_spot_ids: list[str] = Field(default_factory=list)
    activity_ids: list[str] = Field(default_factory=list)
    food_item_ids: list[str] = Field(default_factory=list)
    messages: TripRecommendationMessages = Field(default_factory=TripRecommendationMessages)
    selection_instruction: str = Field(default="")

class ItineraryPlanItem(BaseModel):
    time: str = Field(
        description="Approximate time for this plan item, for example '09:00 AM'."
    )
    title: str = Field(
        description="Short title for this itinerary item."
    )
    item_type: str = Field(
        description="One of: tour_spot, activity, food, transfer, rest, free_time."
    )
    item_id: Optional[str] = Field(
        default=None,
        description="Related tour spot, activity, or food item ID if available."
    )
    description: str = Field(
        description="Short practical description of what the traveler will do."
    )
    estimated_cost: Optional[str] = Field(
        default=None,
        description="Estimated cost for this item if available."
    )
    notes: Optional[str] = Field(
        default=None,
        description="Short useful note, such as booking, timing, or comfort advice."
    )


class ItineraryDayPlan(BaseModel):
    day: int = Field(description="Day number of the trip.")
    date: str = Field(description="Trip date for this day.")
    title: str = Field(description="Short theme/title for the day.")
    summary: str = Field(description="Short summary of the day's plan.")
    items: list[ItineraryPlanItem] = Field(default_factory=list)


class RoutePlanLeg(BaseModel):
    date: str = Field(description="Date of this route movement.")
    start_time: str = Field(description="Approximate starting time.")
    from_point: str = Field(description="Starting point.")
    to_point: str = Field(description="Ending point.")
    related_item_id: Optional[str] = Field(
        default=None,
        description="Related itinerary item ID if this route is connected to a selected item."
    )
    transport_mode: str = Field(
        description="Suggested transport mode, for example walking, car, rickshaw, bus, boat, train."
    )
    estimated_duration: str = Field(description="Estimated travel duration.")
    estimated_cost: Optional[str] = Field(default=None)
    notes: Optional[str] = Field(default=None)


class TripBudgetBreakdown(BaseModel):
    transport: Optional[str] = Field(default=None)
    food: Optional[str] = Field(default=None)
    activities: Optional[str] = Field(default=None)
    tickets_or_entry: Optional[str] = Field(default=None)
    miscellaneous: Optional[str] = Field(default=None)
    total_estimated_budget: str = Field(
        description="Rough total estimated budget for the trip."
    )
    budget_note: str = Field(
        description="Short note explaining that the budget is approximate."
    )


class TripItineraryDesignResponse(BaseModel):
    is_itinerary_complete: bool = Field(
        description="True when the day-wise itinerary, route plan, and rough budget are generated."
    )
    title: str = Field(description="Short title for the generated trip plan.")
    summary: str = Field(description="Short overall summary of the itinerary.")
    day_wise_plan: list[ItineraryDayPlan] = Field(default_factory=list)
    route_plan: list[RoutePlanLeg] = Field(default_factory=list)
    rough_budget: TripBudgetBreakdown
    message: str = Field(
        description="Short user-facing message explaining the generated plan."
    )
    revision_instruction: str = Field(
        description="Short instruction asking the user what they want to change."
    )