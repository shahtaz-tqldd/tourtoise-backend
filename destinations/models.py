from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify
from app.base.models import BaseImage, BaseModel
from .choices import (
    DestinationType, BudgetTier, DifficultyLevel, Status,
    TagCategory, AttractionType, ActivityType, BestTimeOfDay, 
    SpiceLevel, MealType
)


class Destination(BaseModel):
    name = models.CharField(max_length=150)
    tagline = models.CharField(max_length=200)
    description = models.TextField()
    cover_image = models.URLField()

    # Location
    country = models.CharField(max_length=100)
    country_code = models.CharField(max_length=3)
    region = models.CharField(max_length=150, blank=True)
    longitude = models.FloatField(null=True)
    latitude = models.FloatField(null=True)

    # attributes
    destination_type = models.CharField(max_length=20, choices=DestinationType.choices)
    min_stay_days = models.PositiveSmallIntegerField(default=2)
    max_stay_days = models.PositiveSmallIntegerField(default=7)
    budget_tier = models.CharField(max_length=10, choices=BudgetTier.choices)
    difficulty_level = models.CharField(max_length=15, choices=DifficultyLevel.choices, default=DifficultyLevel.EASY)

    currency = models.CharField(max_length=50)
    currency_code = models.CharField(max_length=3)
    
    local_languages = models.JSONField(default=list)
    best_travel_months = ArrayField(
        base_field=models.PositiveSmallIntegerField(
            validators=[MinValueValidator(1), MaxValueValidator(12)]
        ),
        default=list,
        blank=True,
        help_text="Best months to visit as integers from 1 (Jan) to 12 (Dec).",
    )

    tags = models.ManyToManyField("DestinationTag", related_name="destinations", blank=True)
    
    # additional info
    getting_around  = models.TextField(blank=True)
    visa_notes = models.TextField(blank=True)
    notes = models.JSONField(default=list, blank=True, help_text="List of important notes")
    picking_reasons = models.JSONField(default=list,blank=True, help_text="List for picking this attractions.")

    status = models.CharField(max_length=15, choices=Status.choices,default=Status.DRAFT, db_index=True)
    slug = models.SlugField(max_length=180, unique=True, blank=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            GinIndex(fields=["best_travel_months"]),
        ]

    def __str__(self):
        return f"{self.name}, {self.country}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f"{self.name}-{self.country_code}")
        if self.best_travel_months:
            # Keep month filters predictable and deduplicated.
            self.best_travel_months = sorted(set(self.best_travel_months))
        super().save(*args, **kwargs)


class DestinationTag(BaseModel):
    """Controlled vocabulary tags — defined once, reused across destinations."""
    name     = models.CharField(max_length=50, unique=True)
    category = models.CharField(max_length=15, choices=TagCategory.choices)
    slug     = models.SlugField(max_length=60, unique=True, blank=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class DestinationImage(BaseImage):
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name="images")


class SavedDestination(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_destinations",
    )
    destination = models.ForeignKey(
        Destination,
        on_delete=models.CASCADE,
        related_name="saved_by_users",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "destination"],
                name="unique_saved_destination_user_destination",
            )
        ]

    def __str__(self):
        return f"{self.user} saved {self.destination}"



# Attractions
class Attraction(BaseModel):
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name="attractions")
    name = models.CharField(max_length=200)
    description = models.TextField()
    cover_image = models.URLField(blank=True)

    # address
    address = models.CharField(max_length=300, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    
    # attributes
    attraction_type = models.CharField(max_length=20, choices=AttractionType.choices)
    budget_tier = models.CharField(max_length=10, choices=BudgetTier.choices, blank=True)
    avg_duration_hours = models.PositiveSmallIntegerField(null=True, blank=True)
    best_time_of_day = models.CharField(max_length=15, choices=BestTimeOfDay.choices, default=BestTimeOfDay.ANYTIME)
    approx_entrance_fee = models.CharField(max_length=100, blank=True)
    
    how_to_reach = models.TextField(null=True, blank=True)
    picking_reasons = models.JSONField(default=list,blank=True, help_text="List for picking this attractions.")
    notes = models.JSONField(default=list, blank=True, help_text="List of important notes")
    tags = models.ManyToManyField("DestinationTag", related_name="attractions", blank=True)
    
    entrance_fee_required = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False, db_index=True)
    
    slug = models.SlugField(max_length=220, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    
    class Meta:
        ordering = ["sort_order", "name"]
        unique_together = ("destination", "slug")

    def __str__(self):
        return f"{self.name} - {self.destination.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)



class AttractionImage(BaseImage):
    attraction = models.ForeignKey(Attraction, on_delete=models.CASCADE, related_name="images")



# Activities
class Activity(BaseModel):
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name="activities")
    name = models.CharField(max_length=200)
    description = models.TextField()
    cover_image = models.URLField(blank=True)
    
    # attributes
    activity_type = models.CharField(max_length=20, choices=ActivityType.choices)
    difficulty_level = models.CharField(max_length=15, choices=DifficultyLevel.choices, default=DifficultyLevel.EASY)
    duration_hours = models.PositiveSmallIntegerField(null=True, blank=True)
    budget_tier = models.CharField(max_length=10, choices=BudgetTier.choices)
    approx_cost = models.CharField(max_length=100, null=True, blank=True)
    best_season = models.CharField(max_length=100, blank=True)

    picking_reasons = models.JSONField(default=list,blank=True, help_text="List for picking this attractions.")
    notes = models.JSONField(default=list, blank=True, help_text="List of important notes")
    
    booking_required = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False, db_index=True)
    
    slug = models.SlugField(max_length=220, blank=True)
    
    class Meta:
        ordering = ["name"]
        unique_together = ("destination", "slug")

    def __str__(self):
        return f"{self.name} - {self.destination.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class ActivityImage(BaseImage):
    activity   = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="images")


# Cuisines
class Cuisine(BaseModel):
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name="cuisines")
    name = models.CharField(max_length=200)
    description = models.TextField()
    cover_image = models.URLField(blank=True)
    
    # attributes
    cuisine_type = models.CharField(max_length=100, blank=True)
    meal_type = models.CharField(max_length=15, choices=MealType.choices, default=MealType.ANY)
    spice_level = models.CharField(max_length=10, choices=SpiceLevel.choices, default=SpiceLevel.MILD)
    approx_cost = models.CharField(max_length=100, null=True, blank=True)

    picking_reasons = models.JSONField(default=list,blank=True, help_text="List for picking this attractions.")
    notes = models.JSONField(default=list, blank=True, help_text="List of important notes")
    
    is_vegetarian_friendly = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False, db_index=True)
    
    slug = models.SlugField(max_length=220, blank=True)
    
    class Meta:
        ordering = ["-is_featured", "name"]
        unique_together = ("destination", "slug")

    def __str__(self):
        return f"{self.name} - {self.destination.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class CuisineImage(BaseImage):
    cuisine = models.ForeignKey(Cuisine, on_delete=models.CASCADE, related_name="images")
