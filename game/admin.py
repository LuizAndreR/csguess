from django.contrib import admin

from .models import Player


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("nick", "name", "career_status", "current_team", "is_major_winner")
    search_fields = ("nick", "name")
    list_filter = ("career_status", "is_major_winner")
    readonly_fields = ("source_collected_at", "created_at", "updated_at")
    fieldsets = (
        ("Identificação", {"fields": ("nick", "name", "nationalities", "photo_url")}),
        ("Carreira", {"fields": ("career_status", "current_team", "roles", "years_active", "is_major_winner")}),
        ("Origem", {"fields": ("source", "source_id", "source_url", "source_collected_at")}),
        ("Registro", {"fields": ("created_at", "updated_at")}),
    )
