from django.db import models


class TripStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PLANNING = "planning", "Planning"
    READY = "ready", "Ready"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"
    ARCHIVED = "archived", "Archived"


class TripVisibility(models.TextChoices):
    PRIVATE = "private", "Private"
    PUBLIC = "public", "Public"


class TripPace(models.TextChoices):
    RELAXED = "relaxed", "Relaxed"
    BALANCED = "balanced", "Balanced"
    FAST = "fast", "Fast"


class TravelerType(models.TextChoices):
    SOLO = "solo", "Solo"
    COUPLE = "couple", "Couple"
    FAMILY = "family", "Family"
    FRIENDS = "friends", "Friends"
    GROUP = "group", "Group"
    BUSINESS = "business", "Business"

class BudgetTier(models.TextChoices):
    BACKPACKER = "backpacker", "Backpacker"
    BUDGET = "budget", "Budget"
    COMFORT = "comfort", "Comfort"
    PREMIUM = "premium", "Premium"
    LUXURY = "luxury", "Luxury"


class AccommodationPreference(models.TextChoices):
    BUDGET = "budget", "Budget"
    MID_RANGE = "mid_range", "Mid-range"
    LUXURY = "luxury", "Luxury"
    BOUTIQUE = "boutique", "Boutique"
    APARTMENT = "apartment", "Apartment"
    HOSTEL = "hostel", "Hostel"
    ANY = "any", "Any"


class TripItemType(models.TextChoices):
    TRANSIT = "transit", "Transit"
    ATTRACTION = "attraction", "Attraction"
    ACTIVITY = "activity", "Activity"
    CUISINE = "cuisine", "Cuisine"
    HOTEL = "hotel", "Hotel / Stay"
    FOOD = "food", "Food"
    FREE_TIME = "free_time", "Free Time"
    NOTE = "note", "Note"
    CUSTOM = "custom", "Custom"


class TripItemStatus(models.TextChoices):
    SUGGESTED = "suggested", "Suggested"
    PLANNED = "planned", "Planned"
    BOOKED = "booked", "Booked"
    COMPLETED = "completed", "Completed"
    SKIPPED = "skipped", "Skipped"


class PlanningSource(models.TextChoices):
    USER = "user", "User"
    AGENT = "agent", "Agent"
    HYBRID = "hybrid", "Hybrid"


class AgentMessageSender(models.TextChoices):
    USER = "user", "User"
    AGENT = "agent", "Agent"
    SYSTEM = "system", "System"


class PlanningStep(models.TextChoices):
    PREFERENCE = "preference", "Preference"
    RECOMMENDATION = "recommendation", "Recommendation"
    ITINERARY = "itinerary", "Itinerary"
    PREPARATION = "preparation", "Preparation"
    OVERVIEW = "overview", "Overview"
    COMPLETED = "completed", "Completed"


class PackingItemsType(models.TextChoices):
    CLOTHING = "clothing", "Clothing"
    TOILETRIES = "toiletries", "Toiletries"
    ELECTRONICS = "electronics", "Electronics"
    MEDICINE = "medicine", "Medicine"
    TRAVEL_GEAR = "travel_gear", "Travel Gear"
    SAFETY = "safety", "Safety"
    WEATHER = "weather", "Weather"
    OTHER = "other", "Other"


class PriorityType(models.TextChoices):
    ESSENTIAL = "essential", "Essential"
    RECOMMENDED = "recommended", "Recommended"
    OPTIONAL = "optional", "Optional"

class RequiredType(models.TextChoices):
    REQUIRED = "required", "Required"
    RECOMMENDED = "recommended", "Recommended"
    CONDITIONAL = "conditional", "Conditional"


class HeadsUpType(models.TextChoices):
    SAFETY = "safety", "Safety"
    WEATHER = "weather", "Weather"
    CULTURE = "culture", "Culture"
    TRANSPORT = "transport", "Transport"
    MONEY = "money", "Money"
    HEALTH = "health", "Health"
    CONNECTIVITY = "connectivity", "Connectivity"
    TIMING = "timing", "Timing"
    RULES = "rules", "Rules"
    OTHER = "other", "Other"

class SeverityType(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
