from django.contrib import admin

from journals.models import Journal, JournalComment, JournalImage, JournalTag, SavedJournal


class JournalImageInline(admin.TabularInline):
    model = JournalImage
    extra = 0


@admin.register(Journal)
class JournalAdmin(admin.ModelAdmin):
    list_display = ("author", "visibility", "created_at")
    list_filter = ("visibility",)
    search_fields = ("content", "author__email", "tags__name")
    filter_horizontal = ("tags",)
    inlines = (JournalImageInline,)


admin.site.register(JournalTag)
admin.site.register(JournalComment)
admin.site.register(SavedJournal)
