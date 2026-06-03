from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from accounts.models import User, UserProfile


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-created_at",)
    list_display = ("email", "name", "status", "is_email_verified", "is_staff", "is_superuser")
    list_filter = ("status", "is_staff", "is_superuser", "is_email_verified")
    search_fields = ("email", "name", "phone")
    readonly_fields = ("id", "created_at", "updated_at", "last_login")

    fieldsets = (
        ("Credentials", {"fields": ("email", "password")}),
        ("Profile", {"fields": ("name", "phone")}),
        ("Access", {"fields": ("status", "is_email_verified", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "created_at", "updated_at")}),
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
    list_display = ("user", "username", "travel_pace", "preferred_currency", "preferred_language", "is_public_profile")
    list_filter = ("travel_pace", "preferred_currency", "preferred_language", "is_public_profile")
    search_fields = ("user__email", "username", "city", "country_of_residence")
    autocomplete_fields = ("user",)
