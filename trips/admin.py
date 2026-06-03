from django.contrib import admin

from trips.models import Trip, TripDay, TripDestination, TripItineraryItem, TripPlanVersion


class TripDestinationInline(admin.TabularInline):
    model = TripDestination
    extra = 0
    fields = ("destination", "sort_order", "arrival_date", "departure_date", "stay_nights", "is_primary")
    show_change_link = True


class TripDayInline(admin.TabularInline):
    model = TripDay
    extra = 0
    fields = ("day_number", "date", "title", "trip_destination")
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
    list_filter = ("status", "visibility", "trip_pace")
    search_fields = ("title", "user__email", "user__name")
    readonly_fields = ("id", "share_token", "created_at", "updated_at", "created_by", "updated_by")
    autocomplete_fields = ("user",)
    inlines = (TripDestinationInline, TripDayInline)


@admin.register(TripDestination)
class TripDestinationAdmin(admin.ModelAdmin):
    list_display = ("trip", "destination", "sort_order", "arrival_date", "departure_date", "is_primary")
    list_filter = ("is_primary",)
    search_fields = ("trip__title", "destination__name", "trip__user__email")
    readonly_fields = ("id", "created_at", "updated_at", "created_by", "updated_by")
    autocomplete_fields = ("trip", "destination")


@admin.register(TripDay)
class TripDayAdmin(admin.ModelAdmin):
    list_display = ("trip", "day_number", "date", "title", "trip_destination")
    search_fields = ("trip__title", "title")
    readonly_fields = ("id", "created_at", "updated_at", "created_by", "updated_by")
    autocomplete_fields = ("trip", "trip_destination")


@admin.register(TripItineraryItem)
class TripItineraryItemAdmin(admin.ModelAdmin):
    list_display = ("trip", "day", "title", "item_type", "status", "sort_order", "start_time")
    list_filter = ("item_type", "status", "booking_required")
    search_fields = ("trip__title", "title", "location_name", "booking_reference")
    readonly_fields = ("id", "created_at", "updated_at", "created_by", "updated_by")
    autocomplete_fields = (
        "trip",
        "day",
        "trip_destination",
        "attraction",
        "activity",
        "cuisine",
    )


@admin.register(TripPlanVersion)
class TripPlanVersionAdmin(admin.ModelAdmin):
    list_display = ("trip", "version", "source", "created_at")
    list_filter = ("source",)
    search_fields = ("trip__title", "summary")
    readonly_fields = ("id", "created_at", "updated_at", "created_by", "updated_by")
    autocomplete_fields = ("trip",)
