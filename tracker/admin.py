from django.contrib import admin

from .models import Follow, Season, Show
from .models import Episode, Follow, Season, Show, ShowEvent

admin.site.register(Episode)

class SeasonInline(admin.TabularInline):
    model = Season
    extra = 0
    fields = ("season_number", "name", "episode_count", "air_date")
    readonly_fields = ("season_number", "name", "episode_count", "air_date")
    can_delete = False


@admin.register(Show)
class ShowAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "next_air_date", "synced_at")
    search_fields = ("name",)
    readonly_fields = ("synced_at", "genres", "networks")
    inlines = [SeasonInline]

@admin.register(ShowEvent)
class ShowEventAdmin(admin.ModelAdmin):
    list_display = ("show", "kind", "created_at")
    list_filter = ("kind",)

admin.site.register(Season)
admin.site.register(Follow)