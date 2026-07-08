from django.contrib import admin

from destinations.models import (
    Activity,
    ActivityImage,
    Attraction,
    AttractionImage,
    Cuisine,
    CuisineImage,
    Destination,
    DestinationImage,
    DestinationTag,
)


class DestinationImageInline(admin.TabularInline):
    model = DestinationImage
    extra = 0
    fields = ("image_url", "caption", "sort_order", "created_at")
    readonly_fields = ("created_at",)


class AttractionInline(admin.TabularInline):
    model = Attraction
    extra = 0
    fields = ("name", "attraction_type", "is_featured", "sort_order")
    show_change_link = True


class ActivityInline(admin.TabularInline):
    model = Activity
    extra = 0
    fields = ("name", "activity_type", "difficulty_level", "is_featured")
    show_change_link = True


class CuisineInline(admin.TabularInline):
    model = Cuisine
    extra = 0
    fields = ("name", "cuisine_type", "meal_type", "is_featured")
    show_change_link = True


class AttractionImageInline(admin.TabularInline):
    model = AttractionImage
    extra = 0
    fields = ("image_url", "caption", "sort_order", "created_at")
    readonly_fields = ("created_at",)


class ActivityImageInline(admin.TabularInline):
    model = ActivityImage
    extra = 0
    fields = ("image_url", "caption", "sort_order", "created_at")
    readonly_fields = ("created_at",)


class CuisineImageInline(admin.TabularInline):
    model = CuisineImage
    extra = 0
    fields = ("image_url", "caption", "sort_order", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "country",
        "destination_type",
        "budget_tier",
        "difficulty_level",
        "status",
        "created_at",
    )
    list_filter = (
        "destination_type",
        "budget_tier",
        "difficulty_level",
        "status",
        "country_code",
    )
    search_fields = ("name", "country", "region", "slug", "tagline", "tags__name")
    readonly_fields = ("id", "slug", "created_at", "updated_at", "created_by", "updated_by")
    filter_horizontal = ("tags",)
    inlines = (DestinationImageInline, AttractionInline, ActivityInline, CuisineInline)
    ordering = ("name",)

    fieldsets = (
        ("Core", {"fields": ("id", "name", "slug", "destination_type", "status")}),
        ("Location", {"fields": ("country", "country_code", "region", "latitude", "longitude")}),
        (
            "Content",
            {"fields": ("tagline", "description", "cover_image", "tags")},
        ),
        (
            "Travel Info",
            {
                "fields": (
                    "min_stay_days",
                    "max_stay_days",
                    "budget_tier",
                    "difficulty_level",
                    "local_languages",
                    "best_travel_months",
                    "currency",
                    "currency_code",
                    "getting_around",
                    "visa_notes",
                    "notes",
                    "picking_reasons",
                )
            },
        ),
        (
            "Audit",
            {"fields": ("created_by", "updated_by", "created_at", "updated_at")},
        ),
    )


@admin.register(DestinationTag)
class DestinationTagAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "slug", "created_at")
    list_filter = ("category",)
    search_fields = ("name", "slug")
    readonly_fields = ("id", "slug", "created_at", "updated_at", "created_by", "updated_by")
    ordering = ("name",)


@admin.register(Attraction)
class AttractionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "destination",
        "attraction_type",
        "budget_tier",
        "best_time_of_day",
        "is_featured",
    )
    list_filter = ("attraction_type", "budget_tier", "best_time_of_day", "is_featured")
    search_fields = ("name", "destination__name", "slug", "address")
    readonly_fields = ("id", "slug", "created_at", "updated_at", "created_by", "updated_by")
    autocomplete_fields = ("destination",)
    inlines = (AttractionImageInline,)
    ordering = ("destination__name", "sort_order", "name")


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "destination",
        "activity_type",
        "difficulty_level",
        "budget_tier",
        "is_featured",
    )
    list_filter = ("activity_type", "difficulty_level", "budget_tier", "is_featured")
    search_fields = ("name", "destination__name", "slug")
    readonly_fields = ("id", "slug", "created_at", "updated_at", "created_by", "updated_by")
    autocomplete_fields = ("destination",)
    inlines = (ActivityImageInline,)
    ordering = ("destination__name", "name")


@admin.register(Cuisine)
class CuisineAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "destination",
        "cuisine_type",
        "meal_type",
        "spice_level",
        "is_featured",
    )
    list_filter = ("meal_type", "spice_level", "is_featured", "is_vegetarian_friendly")
    search_fields = ("name", "destination__name", "slug", "cuisine_type")
    readonly_fields = ("id", "slug", "created_at", "updated_at", "created_by", "updated_by")
    autocomplete_fields = ("destination",)
    inlines = (CuisineImageInline,)
    ordering = ("destination__name", "name")
