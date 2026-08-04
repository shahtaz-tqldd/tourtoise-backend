from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from accounts.models import User, UserProfile


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-created_at",)
    list_display = ("email", "name", "provider", "status", "is_email_verified", "is_active", "deleted_at", "is_staff", "is_superuser")
    list_filter = ("provider", "status", "is_staff", "is_superuser", "is_email_verified")
    search_fields = ("email", "name", "phone", "firebase_uid")
    readonly_fields = ("id", "created_at", "updated_at", "last_login", "deleted_at")

    fieldsets = (
        ("Credentials", {"fields": ("email", "password")}),
        ("Profile", {"fields": ("name", "phone")}),
        ("Auth provider", {"fields": ("provider", "firebase_uid", "firebase_id_token", "google_access_token")}),
        ("Access", {"fields": ("status", "is_email_verified", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "deleted_at", "created_at", "updated_at")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "name", "password1", "password2", "status"),
            },
        ),
    )


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "username",
        "timezone",
        "total_country_visited",
        "total_trip_count",
        "total_journal_count",
        "is_location_sharing_enabled",
        "is_alert_notification_enabled",
        "is_public_profile",
    )
    list_filter = (
        "travel_pace",
        "preferred_currency",
        "preferred_language",
        "timezone",
        "is_public_profile",
        "is_location_sharing_enabled",
        "is_alert_notification_enabled",
    )
    search_fields = ("user__email", "username", "city", "country_of_residence")
    autocomplete_fields = ("user",)
    readonly_fields = (
        "total_country_visited",
        "visited_country_list",
        "total_trip_count",
        "total_journal_count",
    )
