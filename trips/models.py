from uuid import uuid4

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from app.base.models import BaseModel
from destinations.models import Activity, Attraction, Cuisine, Destination
from trips.choices import (
    PlanningSource,
    TripItemStatus,
    TripItemType,
    TripPace,
    TripStatus,
    TripVisibility,
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
    travelers_count = models.PositiveSmallIntegerField(default=1)
    trip_pace = models.CharField(
        max_length=10,
        choices=TripPace.choices,
        default=TripPace.BALANCED,
    )
    origin_city = models.CharField(max_length=120, blank=True)
    origin_country = models.CharField(max_length=120, blank=True)

    # Budget and personalization
    total_budget = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    budget_currency = models.CharField(max_length=10, blank=True, default="USD")
    preferences = models.JSONField(
        default=dict,
        blank=True,
        help_text="Flexible trip preferences collected from the user or AI agent.",
    )
    constraints = models.JSONField(
        default=dict,
        blank=True,
        help_text="Hard constraints such as dates, visa issues, accessibility needs, or dietary rules.",
    )
    traveler_profile_snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Snapshot of relevant user profile data at planning time.",
    )

    # AI planning state
    planning_summary = models.TextField(blank=True)
    agent_context = models.JSONField(
        default=dict,
        blank=True,
        help_text="Agent-specific structured state, prompts, or planning notes.",
    )
    latest_plan_version = models.PositiveSmallIntegerField(default=1)

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


class TripDay(BaseModel):
    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name="days",
    )
    trip_destination = models.ForeignKey(
        TripDestination,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="days",
    )
    day_number = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(365)]
    )
    date = models.DateField(null=True, blank=True)
    title = models.CharField(max_length=180, blank=True)
    summary = models.TextField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["day_number"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "day_number"], name="unique_trip_day_number"),
            models.UniqueConstraint(
                fields=["trip", "date"],
                condition=Q(date__isnull=False),
                name="unique_trip_date",
            ),
        ]
        indexes = [
            models.Index(fields=["trip", "day_number"]),
            models.Index(fields=["trip", "date"]),
        ]

    def __str__(self):
        return f"{self.trip.title} - Day {self.day_number}"


class TripItineraryItem(BaseModel):
    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name="itinerary_items",
    )
    day = models.ForeignKey(
        TripDay,
        on_delete=models.CASCADE,
        related_name="items",
    )
    trip_destination = models.ForeignKey(
        TripDestination,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="itinerary_items",
    )
    item_type = models.CharField(
        max_length=20,
        choices=TripItemType.choices,
        default=TripItemType.CUSTOM,
        db_index=True,
    )
    status = models.CharField(
        max_length=15,
        choices=TripItemStatus.choices,
        default=TripItemStatus.PLANNED,
        db_index=True,
    )
    title = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=1)

    # Optional links to structured destination content
    attraction = models.ForeignKey(
        Attraction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trip_items",
    )
    activity = models.ForeignKey(
        Activity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trip_items",
    )
    cuisine = models.ForeignKey(
        Cuisine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trip_items",
    )

    # Planning and execution details
    location_name = models.CharField(max_length=180, blank=True)
    address = models.CharField(max_length=300, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    estimated_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    cost_currency = models.CharField(max_length=10, blank=True)
    booking_required = models.BooleanField(default=False)
    booking_reference = models.CharField(max_length=120, blank=True)
    external_url = models.URLField(blank=True)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Flexible structured details such as transport info, restaurant notes, or AI reasoning.",
    )

    class Meta:
        ordering = ["day__day_number", "sort_order", "start_time"]
        constraints = [
            models.UniqueConstraint(fields=["day", "sort_order"], name="unique_trip_item_order_per_day"),
            models.CheckConstraint(
                condition=Q(end_time__gte=models.F("start_time"))
                | Q(end_time__isnull=True)
                | Q(start_time__isnull=True),
                name="trip_item_end_time_after_start_time",
            ),
        ]
        indexes = [
            models.Index(fields=["trip", "status"]),
            models.Index(fields=["trip", "item_type"]),
            models.Index(fields=["day", "sort_order"]),
        ]

    def __str__(self):
        return f"{self.day} - {self.title}"


class TripPlanVersion(BaseModel):
    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name="plan_versions",
    )
    version = models.PositiveSmallIntegerField()
    summary = models.TextField(blank=True)
    source = models.CharField(
        max_length=10,
        choices=PlanningSource.choices,
        default=PlanningSource.AGENT,
    )
    snapshot = models.JSONField(
        default=dict,
        blank=True,
        help_text="Full structured snapshot of the trip plan at a given version.",
    )

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "version"], name="unique_trip_plan_version"),
        ]
        indexes = [
            models.Index(fields=["trip", "version"]),
        ]

    def __str__(self):
        return f"{self.trip.title} v{self.version}"
