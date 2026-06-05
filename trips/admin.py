from django.contrib import admin

from trips.models import (
    Trip,
    TripActivityRecommendationItem,
    TripAgentConversationSession,
    TripAgentMessage,
    TripAttractionRecommendationItem,
    TripCuisineRecommendationItem,
    TripDestination,
    TripHeadsUpInfoItem,
    TripItinerary,
    TripItineraryBudget,
    TripItineraryDay,
    TripItineraryDayItem,
    TripPreparation,
    TripPreparationPackingItem,
    TripRecommendations,
    TripRequiredDocumentItem,
    TripRoutePlanItem,
)


class TripDestinationInline(admin.TabularInline):
    model = TripDestination
    extra = 0
    fields = ("destination", "sort_order", "arrival_date", "departure_date", "stay_nights", "is_primary")
    show_change_link = True


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "user",
        "status",
        "travelers_count",
        "start_date",
        "end_date",
        "updated_at",
    )
    list_filter = ("status", "visibility")
    search_fields = ("title", "user__email", "user__name")
    readonly_fields = ("id", "share_token", "created_at", "updated_at", "created_by", "updated_by")
    autocomplete_fields = ("user",)
    inlines = (TripDestinationInline,)


@admin.register(TripDestination)
class TripDestinationAdmin(admin.ModelAdmin):
    list_display = ("trip", "destination", "sort_order", "arrival_date", "departure_date", "is_primary")
    list_filter = ("is_primary",)
    search_fields = ("trip__title", "destination__name", "trip__user__email")
    readonly_fields = ("id", "created_at", "updated_at", "created_by", "updated_by")
    autocomplete_fields = ("trip", "destination")


@admin.register(TripRecommendations)
class TripRecommendationsAdmin(admin.ModelAdmin):
    list_display = ("trip", "is_finalized", "session_id", "updated_at")
    list_filter = ("is_finalized",)
    search_fields = ("trip__title", "session_id")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("trip",)


@admin.register(TripAttractionRecommendationItem)
class TripAttractionRecommendationItemAdmin(admin.ModelAdmin):
    list_display = ("recommendation", "attraction")
    autocomplete_fields = ("recommendation", "attraction")


@admin.register(TripCuisineRecommendationItem)
class TripCuisineRecommendationItemAdmin(admin.ModelAdmin):
    list_display = ("recommendation", "cuisine")
    autocomplete_fields = ("recommendation", "cuisine")


@admin.register(TripActivityRecommendationItem)
class TripActivityRecommendationItemAdmin(admin.ModelAdmin):
    list_display = ("recommendation", "activity")
    autocomplete_fields = ("recommendation", "activity")


@admin.register(TripItinerary)
class TripItineraryAdmin(admin.ModelAdmin):
    list_display = ("trip", "title", "is_finalized", "session_id", "updated_at")
    list_filter = ("is_finalized",)
    search_fields = ("trip__title", "title", "session_id")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("trip",)


@admin.register(TripRoutePlanItem)
class TripRoutePlanItemAdmin(admin.ModelAdmin):
    list_display = ("itinerary", "date", "start_time", "from_point", "to_point", "transport_mode")
    list_filter = ("transport_mode",)
    search_fields = ("itinerary__trip__title", "from_point", "to_point")
    autocomplete_fields = ("itinerary",)


@admin.register(TripItineraryDay)
class TripItineraryDayAdmin(admin.ModelAdmin):
    list_display = ("itinerary", "day", "date", "title")
    search_fields = ("itinerary__trip__title", "title")
    autocomplete_fields = ("itinerary",)


@admin.register(TripItineraryDayItem)
class TripItineraryDayItemAdmin(admin.ModelAdmin):
    list_display = ("trip_itinerary_day", "time", "title", "item_type", "estimated_cost")
    list_filter = ("item_type",)
    search_fields = ("trip_itinerary_day__itinerary__trip__title", "title")
    autocomplete_fields = ("trip_itinerary_day",)


@admin.register(TripItineraryBudget)
class TripItineraryBudgetAdmin(admin.ModelAdmin):
    list_display = ("itinerary", "total_estimated_budget", "updated_at")
    search_fields = ("itinerary__trip__title",)
    readonly_fields = ("id", "created_at", "updated_at", "created_by", "updated_by")
    autocomplete_fields = ("itinerary",)


@admin.register(TripPreparation)
class TripPreparationAdmin(admin.ModelAdmin):
    list_display = ("trip", "title", "is_finalized", "session_id")
    list_filter = ("is_finalized",)
    search_fields = ("trip__title", "title", "session_id")
    autocomplete_fields = ("trip",)


@admin.register(TripPreparationPackingItem)
class TripPreparationPackingItemAdmin(admin.ModelAdmin):
    list_display = ("preparation", "item", "quantity", "category", "priority", "sort_order")
    list_filter = ("category", "priority")
    search_fields = ("preparation__trip__title", "item")
    autocomplete_fields = ("preparation",)


@admin.register(TripRequiredDocumentItem)
class TripRequiredDocumentItemAdmin(admin.ModelAdmin):
    list_display = ("preparation", "document_name", "required_level", "sort_order")
    list_filter = ("required_level",)
    search_fields = ("preparation__trip__title", "document_name")
    autocomplete_fields = ("preparation",)


@admin.register(TripHeadsUpInfoItem)
class TripHeadsUpInfoItemAdmin(admin.ModelAdmin):
    list_display = ("preparation", "title", "category", "severity", "sort_order")
    list_filter = ("category", "severity")
    search_fields = ("preparation__trip__title", "title")
    autocomplete_fields = ("preparation",)


@admin.register(TripAgentConversationSession)
class TripAgentConversationSessionAdmin(admin.ModelAdmin):
    list_display = ("trip", "user", "current_step", "created_at")
    list_filter = ("current_step",)
    search_fields = ("trip__title", "user__email")
    readonly_fields = ("id", "created_at", "updated_at", "created_by", "updated_by")
    autocomplete_fields = ("trip", "user")


@admin.register(TripAgentMessage)
class TripAgentMessageAdmin(admin.ModelAdmin):
    list_display = ("session", "trip", "sender", "content", "created_at")
    list_filter = ("sender",)
    search_fields = ("content", "trip__title")
    readonly_fields = ("id", "created_at", "updated_at", "created_by", "updated_by")
    autocomplete_fields = ("session", "trip")
