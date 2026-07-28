from uuid import uuid4

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from app.base.models import BaseModel, BaseImage
from destinations.models import Activity, Attraction, Cuisine, Destination
from trips.choices import (
    AgentMessageSender,
    PlanningSource,
    TripStatus,
    BudgetTier,
    TripVisibility,
    TravelerType,
    PackingItemsType,
    PriorityType,
    RequiredType,
    HeadsUpType,
    SeverityType,
    PlanningStep,
)


class Trip(BaseModel):
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="trips",
        db_index=True,
    )
    title = models.CharField(max_length=180)
    share_token = models.UUIDField(default=uuid4, unique=True, editable=False, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=TripStatus.choices,
        default=TripStatus.DRAFT,
        db_index=True,
    )
    visibility = models.CharField(
        max_length=15,
        choices=TripVisibility.choices,
        default=TripVisibility.PRIVATE,
    )
    planning_source = models.CharField(
        max_length=10,
        choices=PlanningSource.choices,
        default=PlanningSource.HYBRID,
    )

    # Trip fundamentals
    start_date = models.DateField(null=True, blank=True, db_index=True)
    end_date = models.DateField(null=True, blank=True, db_index=True)
    nights = models.PositiveSmallIntegerField(null=True, blank=True)
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)
    travelers_count = models.PositiveSmallIntegerField(default=1)
    traveler_type = models.CharField(
        max_length=20,
        choices=TravelerType.choices,
        blank=True,
    )
    
    origin_city = models.CharField(max_length=120, blank=True)
    origin_country = models.CharField(max_length=120, blank=True)
    start_location_address = models.CharField(max_length=500, blank=True)
    start_location_latitude = models.FloatField(null=True, blank=True)
    start_location_longitude = models.FloatField(null=True, blank=True)

    # Budget and personalization
    budget_tier = models.CharField(
        max_length=20,
        choices=BudgetTier.choices,
        blank=True,
    )
    budget_currency = models.CharField(max_length=10, blank=True, default="USD")

    preferences = models.JSONField(
        default=dict,
        blank=True,
        help_text="Flexible trip preferences collected from the user or AI agent.",
    )

    current_step = models.CharField(
        max_length=32,
        choices=PlanningStep.choices,
        db_index=True,
        default=PlanningStep.PREFERENCE
    )

    # Agent Specific Parameter
    agent_active = models.BooleanField(default=False)
    is_qna_complete = models.BooleanField(default=False)
    is_recommendation_complete = models.BooleanField(default=False)
    is_itinerary_design_complete = models.BooleanField(default=False)
    is_trip_preparation_complete = models.BooleanField(default=False)
    
    planning_summary = models.TextField(blank=True)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Agent-specific structured state, prompts, or planning notes.",
    )

    completed_stats_recorded = models.BooleanField(default=False, db_index=True)
    
    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=models.F("start_date")) | Q(end_date__isnull=True) | Q(start_date__isnull=True),
                name="trip_end_date_after_start_date",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["user", "start_date"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.user})"

    def save(self, *args, **kwargs):
        if self.start_date and self.end_date:
            self.nights = max((self.end_date - self.start_date).days, 0)
            self.duration_days = self.nights + 1
        super().save(*args, **kwargs)


class TripDestination(BaseModel):
    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name="trip_destinations",
    )
    destination = models.ForeignKey(
        Destination,
        on_delete=models.PROTECT,
        related_name="trip_destinations",
    )
    sort_order = models.PositiveSmallIntegerField(default=1)
    arrival_date = models.DateField(null=True, blank=True)
    departure_date = models.DateField(null=True, blank=True)
    stay_nights = models.PositiveSmallIntegerField(null=True, blank=True)
    is_primary = models.BooleanField(default=False, db_index=True)
    transport_from_previous = models.JSONField(
        default=dict,
        blank=True,
        help_text="Structured transport details from the previous destination.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["sort_order", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "sort_order"], name="unique_trip_destination_order"),
            models.UniqueConstraint(fields=["trip", "destination", "sort_order"], name="unique_trip_destination_row"),
            models.UniqueConstraint(
                fields=["trip"],
                condition=Q(is_primary=True),
                name="unique_primary_destination_per_trip",
            ),
            models.CheckConstraint(
                condition=Q(departure_date__gte=models.F("arrival_date"))
                | Q(departure_date__isnull=True)
                | Q(arrival_date__isnull=True),
                name="trip_destination_departure_after_arrival",
            ),
        ]
        indexes = [
            models.Index(fields=["trip", "sort_order"]),
            models.Index(fields=["destination"]),
        ]

    def __str__(self):
        return f"{self.trip.title} - {self.destination.name}"

    def save(self, *args, **kwargs):
        if self.arrival_date and self.departure_date:
            self.stay_nights = max((self.departure_date - self.arrival_date).days, 0)
        super().save(*args, **kwargs)


# recommendation
class TripRecommendations(BaseModel):
    trip = models.OneToOneField(
        Trip,
        on_delete=models.CASCADE,
        related_name="trip_recommendations",
    )
    
    attraction_recommendation_message = models.TextField(blank=True)
    cusine_recommendation_message = models.TextField(blank=True)
    activity_recommendation_message = models.TextField(blank=True)

    external_session_id = models.CharField(max_length=120, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

class TripAttractionRecommendationItem(BaseModel):
    recommendation = models.ForeignKey(
        TripRecommendations,
        on_delete=models.CASCADE,
        related_name="attraction_items",
    )
    attraction = models.ForeignKey(
        Attraction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trip_recommendation_items",
    )

class TripCuisineRecommendationItem(BaseModel):
    recommendation = models.ForeignKey(
        TripRecommendations,
        on_delete=models.CASCADE,
        related_name="cuisine_items",
    )
    cuisine = models.ForeignKey(
        Cuisine,
        on_delete=models.CASCADE,
        related_name="trip_recommendation_items",
    )

class TripActivityRecommendationItem(BaseModel):
    recommendation = models.ForeignKey(
        TripRecommendations,
        on_delete=models.CASCADE,
        related_name="activity_items",
    )
    activity = models.ForeignKey(
        Activity,
        on_delete=models.CASCADE,
        related_name="trip_recommendation_items",
    )


# itenary
class TripItinerary(BaseModel):
    trip = models.OneToOneField(
        Trip,
        on_delete=models.CASCADE,
        related_name="trip_itinerary",
    )
    
    title = models.CharField(max_length=180, blank=True)
    summary = models.TextField(blank=True)
    message = models.TextField(blank=True)
    
    external_session_id = models.CharField(max_length=120, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

class TripRoutePlanItem(models.Model):
    itinerary = models.ForeignKey(
        TripItinerary,
        on_delete=models.CASCADE,
        related_name="route_plan_items",
    )

    date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    to_point = models.CharField(max_length=255)
    from_point = models.CharField(max_length=255)
    start_time = models.TimeField(null=True, blank=True)
    transport_mode = models.CharField(max_length=50)
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimated_duration = models.DurationField(null=True, blank=True)

    class Meta:
        ordering = ["date", "start_time"]
        indexes = [
            models.Index(fields=["itinerary", "date", "start_time"]),
        ]

class TripItineraryDay(models.Model):
    itinerary = models.ForeignKey(
        TripItinerary,
        on_delete=models.CASCADE,
        related_name="itinerary_days",
    )

    day = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(365)]
    )
    date = models.DateField(null=True, blank=True)
    title = models.CharField(max_length=180)
    summary = models.TextField(blank=True)

    class Meta:
        ordering = ["day"]
        constraints = [
            models.UniqueConstraint(fields=["itinerary", "day"], name="unique_itinerary_day_order"),
        ]
        indexes = [
            models.Index(fields=["itinerary", "day"]),
            models.Index(fields=["itinerary", "date"]),
        ]

class TripItineraryDayItem(models.Model):
    trip_itinerary_day = models.ForeignKey(
        TripItineraryDay,
        on_delete=models.CASCADE,
        related_name="day_items",
    )

    time = models.TimeField(null=True, blank=True)
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    item_type = models.CharField(max_length=20)
    item_id = models.UUIDField(null=True, blank=True) # cusine/activity/spot
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["time"]
        indexes = [
            models.Index(fields=["trip_itinerary_day", "time"]),
            models.Index(fields=["item_type"]),
        ]

class TripItineraryBudget(BaseModel):
    itinerary = models.OneToOneField(
        TripItinerary,
        on_delete=models.CASCADE,
        related_name="rough_budget",
    )
    transport = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    food = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    activities = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    tickets_or_entry = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    miscellaneous = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    total_estimated_budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    budget_note = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.itinerary.trip.title} budget"



# trip preparation
class TripPreparation(BaseModel):
    trip = models.OneToOneField(
        Trip,
        on_delete=models.CASCADE,
        related_name="structured_preparation",
    )
    
    title = models.CharField(max_length=180, blank=True)
    summary = models.TextField(blank=True)
    message = models.TextField(blank=True)
    
    external_session_id = models.CharField(max_length=120, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.title or f"{self.trip.title} preparation"


class TripPreparationPackingItem(BaseModel):
    preparation = models.ForeignKey(
        TripPreparation,
        on_delete=models.CASCADE,
        related_name="packing_items",
    )
    item = models.CharField(max_length=180)
    quantity = models.PositiveIntegerField(default=1)
    
    category = models.CharField(
        max_length=20,
        choices=PackingItemsType.choices,
        default=PackingItemsType.OTHER,
        db_index=True,
    )
    
    priority = models.CharField(
        max_length=20,
        choices=PriorityType.choices,
        default=PriorityType.RECOMMENDED,
        db_index=True,
    )
    
    is_packed = models.BooleanField(default=False, db_index=True)
    sort_order = models.PositiveSmallIntegerField(default=1)
    additional_notes = models.TextField(blank=True, null=True)
    class Meta:
        ordering = ["sort_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["preparation", "sort_order"],
                name="unique_packing_item_order",
            ),
        ]
        indexes = [
            models.Index(fields=["preparation", "sort_order"]),
            models.Index(fields=["category"]),
            models.Index(fields=["priority"]),
        ]

    def __str__(self):
        return self.item


class TripRequiredDocumentItem(BaseModel):
    preparation = models.ForeignKey(
        TripPreparation,
        on_delete=models.CASCADE,
        related_name="required_documents",
    )
    document_name = models.CharField(max_length=180)
    document_file_name = models.CharField(max_length=180, blank=True)
    document_url = models.URLField(blank=True, null=True)
    document_url_public_id = models.CharField(max_length=255, blank=True)
    
    required_level = models.CharField(
        max_length=20,
        choices=RequiredType.choices,
        default=RequiredType.RECOMMENDED,
        db_index=True,
    )
    
    sort_order = models.PositiveSmallIntegerField(default=1)
    additional_note = models.TextField(blank=True)
    class Meta:
        ordering = ["sort_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["preparation", "sort_order"],
                name="unique_required_document_order",
            ),
        ]
        indexes = [
            models.Index(fields=["preparation", "sort_order"]),
            models.Index(fields=["required_level"]),
        ]

    def __str__(self):
        return self.document_name


class TripHeadsUpInfoItem(BaseModel):
    preparation = models.ForeignKey(
        TripPreparation,
        on_delete=models.CASCADE,
        related_name="heads_up",
    )
    title = models.CharField(max_length=180)
    category = models.CharField(
        max_length=20,
        choices=HeadsUpType.choices,
        default=HeadsUpType.OTHER,
        db_index=True,
    )
    severity = models.CharField(
        max_length=10,
        choices=SeverityType.choices,
        default=SeverityType.LOW,
        db_index=True,
    )

    sort_order = models.PositiveSmallIntegerField(default=1)
    additional_note = models.TextField(blank=True)

    class Meta:
        ordering = ["sort_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["preparation", "sort_order"],
                name="unique_heads_up_info_order",
            ),
        ]
        indexes = [
            models.Index(fields=["preparation", "sort_order"]),
            models.Index(fields=["category"]),
            models.Index(fields=["severity"]),
        ]

    def __str__(self):
        return self.title


# Planning sessions
class TripPlanningSession(BaseModel):
    """
    The single planning workspace for a trip.

    Agent sessions are kept per planning step below so that external agent context
    cannot leak from preference Q&A into recommendation, itinerary, or preparation.
    """

    trip = models.OneToOneField(
        Trip,
        on_delete=models.CASCADE,
        related_name="planning_session",
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="trip_planning_sessions",
        db_index=True,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["user", "is_active"])]

    def __str__(self):
        return f"{self.trip.title} planning session"

    def save(self, *args, **kwargs):
        if self.trip.user_id != self.user_id:
            raise ValueError("Planning session must belong to the trip owner.")
        super().save(*args, **kwargs)


class TripAgentConversationSession(BaseModel):
    """A step-specific agent session within a trip's planning session."""

    planning_session = models.ForeignKey(
        TripPlanningSession,
        on_delete=models.CASCADE,
        related_name="step_sessions",
    )
    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name="agent_conversation_sessions",
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="trip_agent_conversation_sessions",
        db_index=True,
    )
    step = models.CharField(
        max_length=32,
        choices=PlanningStep.choices,
        db_index=True,
    )
    external_session_id = models.CharField(max_length=120, blank=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["planning_session", "step"],
                name="unique_trip_planning_step_session",
            ),
        ]
        indexes = [
            models.Index(fields=["trip", "step", "is_active"]),
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self):
        return f"{self.trip.title} planning step {self.step}"

    def save(self, *args, **kwargs):
        if not self.planning_session_id:
            self.planning_session, _ = TripPlanningSession.objects.get_or_create(
                trip=self.trip,
                defaults={
                    "user": self.user,
                    "created_by": self.created_by or self.user,
                    "updated_by": self.updated_by or self.user,
                },
            )
        if self.planning_session.trip_id != self.trip_id:
            raise ValueError("Planning step session must belong to the same trip as its planning session.")
        if self.planning_session.user_id != self.user_id:
            raise ValueError("Planning step session must belong to the same user as its planning session.")
        super().save(*args, **kwargs)


# Clear domain name for new code while retaining the original model name and
# database table for backwards compatibility.
TripPlanningStepSession = TripAgentConversationSession


class TripAgentMessage(BaseModel):
    session = models.ForeignKey(
        TripAgentConversationSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.CharField(max_length=10, choices=AgentMessageSender.choices)
    content = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["session", "sender"]),
        ]

    def __str__(self):
        return f"{self.sender} message for {self.session_id}"


# Post-planning trip chat
class TripConversationSession(BaseModel):
    """The single post-planning conversation for a trip."""

    trip = models.OneToOneField(
        Trip,
        on_delete=models.CASCADE,
        related_name="conversation_session",
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="trip_conversation_sessions",
        db_index=True,
    )
    external_session_id = models.CharField(max_length=120, blank=True, db_index=True)
    is_active = models.BooleanField(default=False, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["user", "is_active"])]

    def __str__(self):
        return f"{self.trip.title} conversation"

    def save(self, *args, **kwargs):
        if self.trip.user_id != self.user_id:
            raise ValueError("Conversation session must belong to the trip owner.")
        super().save(*args, **kwargs)


class TripConversationMessage(BaseModel):
    session = models.ForeignKey(
        TripConversationSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.CharField(max_length=10, choices=AgentMessageSender.choices)
    content = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["session", "sender"])]

    def __str__(self):
        return f"{self.sender} chat message for {self.session_id}"


# trip notes
class TripNote(BaseModel):
    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name="trip_notes",
    )
    content = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["trip", "created_at"]),
        ]

    def __str__(self):
        return f"Note for {self.trip.title}"


class TripNoteImage(BaseImage):
    note = models.ForeignKey(TripNote, on_delete=models.CASCADE, related_name="trip_note_images")
