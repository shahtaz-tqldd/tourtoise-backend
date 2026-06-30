from django.db import models

class DestinationType(models.TextChoices):
    CITY       = "city",       "City"
    BEACH      = "beach",      "Beach"
    MOUNTAIN   = "mountain",   "Mountain"
    CULTURAL   = "cultural",   "Cultural"
    NATURE     = "nature",     "Nature"
    ISLAND     = "island",     "Island"
    VILLAGE    = "village",    "Village"


class BudgetTier(models.TextChoices):
    BUDGET  = "budget",  "Budget"
    MID     = "mid",     "Mid-range"
    PREMIUM = "premium", "Premium"


class DifficultyLevel(models.TextChoices):
    EASY        = "easy",        "Easy"
    MODERATE    = "moderate",    "Moderate"
    CHALLENGING = "challenging", "Challenging"


class Status(models.TextChoices):
    DRAFT     = "draft",     "Draft"
    PUBLISHED = "published", "Published"
    ARCHIVED  = "archived",  "Archived"


class TagCategory(models.TextChoices):
    EXPERIENCE = "experience", "Experience"   # hiking, temples, beaches
    VIBE       = "vibe",       "Vibe"         # romantic, solo, family
    ACTIVITY   = "activity",   "Activity"     # surfing, diving, trekking


class AttractionType(models.TextChoices):
    TEMPLE        = "temple",         "Temple / Religious Site"
    MUSEUM        = "museum",         "Museum"
    NATURAL_SITE  = "natural_site",   "Natural Site"
    VIEWPOINT     = "viewpoint",      "Viewpoint"
    MONUMENT      = "monument",       "Monument / Historic"
    MARKET        = "market",         "Market / Bazaar"
    PARK          = "park",           "Park / Garden"
    BEACH         = "beach",          "Beach"
    WATERFALL     = "waterfall",      "Waterfall"
    OTHER         = "other",          "Other"


class ActivityType(models.TextChoices):
    TREKKING     = "trekking",      "Trekking / Hiking"
    WATER_SPORTS = "water_sports",  "Water Sports"
    CULTURAL     = "cultural",      "Cultural Experience"
    WILDLIFE     = "wildlife",      "Wildlife & Nature"
    ADVENTURE    = "adventure",     "Adventure Sports"
    WELLNESS     = "wellness",      "Wellness / Spa"
    FOOD_TOUR    = "food_tour",     "Food Tour"
    CITY_TOUR    = "city_tour",     "City Tour"
    DAY_TRIP     = "day_trip",      "Day Trip"


class MealType(models.TextChoices):
    BREAKFAST = "breakfast", "Breakfast"
    LUNCH     = "lunch",     "Lunch"
    DINNER    = "dinner",    "Dinner"
    SNACK     = "snack",     "Snack / Street Food"
    DESSERT   = "dessert",   "Dessert"
    DRINK     = "drink",     "Drink / Beverage"
    ANY       = "any",       "Any"


class SpiceLevel(models.TextChoices):
    NONE   = "none",   "None"
    MILD   = "mild",   "Mild"
    MEDIUM = "medium", "Medium"
    HOT    = "hot",    "Hot"
    VERY_HOT = "very_hot", "Very Hot"


class TipType(models.TextChoices):
    DO      = "do",      "Do"
    DONT    = "dont",    "Don't"
    INFO    = "info",    "General Info"
    WARNING = "warning", "Warning"


class BestTimeOfDay(models.TextChoices):
    MORNING   = "morning",   "Morning"
    AFTERNOON = "afternoon", "Afternoon"
    EVENING   = "evening",   "Evening"
    ANYTIME   = "anytime",   "Anytime"