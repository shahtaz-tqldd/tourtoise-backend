from typing import Optional
from pydantic import BaseModel, Field


class TripPreferenceQNAResponse(BaseModel):
    question: Optional[str] = Field(
        default=None,
        description="The single preference question to ask. Must be null after the user answers it.",
    )
    is_qna_complete: bool = Field(
        description="False for the initial question and true after the user's first answer.",
    )
    context: Optional[str] = Field(
        default=None,
        description="Short recommendation-ready preference context. Must be null until QNA is complete.",
    )


class TripRecommendationMessages(BaseModel):
    attractions: str = Field(default="")
    activities: str = Field(default="")
    cuisines: str = Field(default="")


class TripDestinationRecommendationsResponse(BaseModel):
    is_discovery_complete: bool = Field(
        description="True when destination item recommendations have been selected.",
    )
    attraction_ids: list[str] = Field(default_factory=list)
    activity_ids: list[str] = Field(default_factory=list)
    cuisine_ids: list[str] = Field(default_factory=list)
    messages: TripRecommendationMessages = Field(default_factory=TripRecommendationMessages)

class ItineraryPlanItem(BaseModel):
    time: str = Field(
        description="Approximate time for this plan item, for example '09:00 AM'."
    )
    title: str = Field(
        description="Short title for this itinerary item."
    )
    item_type: str = Field(
        description="One of: attraction, activity, cuisine, transfer, rest, free_time."
    )
    item_id: Optional[str] = Field(
        default=None,
        description="Related attraction, activity, or cuisine ID if available."
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
    accommodation: Optional[str] = Field(default=None)
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

class PackingItem(BaseModel):
    item: str = Field(description="Name of the item to pack.")
    category: str = Field(
        description="One of: clothing, toiletries, electronics, medicine, travel_gear, safety, weather, other."
    )
    reason: Optional[str] = Field(
        default=None,
        description="Short reason why this item is useful for this trip."
    )
    priority: str = Field(
        description="One of: essential, recommended, optional."
    )


class TravelDocumentItem(BaseModel):
    document: str = Field(description="Name of the required or recommended document.")
    required_level: str = Field(
        description="One of: required, recommended, conditional."
    )
    reason: Optional[str] = Field(
        default=None,
        description="Short reason or when this document may be needed."
    )


class TravelHeadsUpItem(BaseModel):
    title: str = Field(description="Short heads-up title.")
    category: str = Field(
        description="One of: safety, weather, culture, transport, money, health, connectivity, timing, rules, other."
    )
    details: str = Field(description="Short practical advice for the traveler.")
    severity: str = Field(
        description="One of: low, medium, high."
    )


class TripPreparationResponse(BaseModel):
    is_preparation_complete: bool = Field(
        description="True when packing list, documents, and heads-up information are generated."
    )
    title: str = Field(description="Short title for the preparation guide.")
    summary: str = Field(description="Short summary of preparation advice.")
    packing_items: list[PackingItem] = Field(default_factory=list)
    required_documents: list[TravelDocumentItem] = Field(default_factory=list)
    heads_up: list[TravelHeadsUpItem] = Field(default_factory=list)
    message: str = Field(description="Short user-facing message.")
