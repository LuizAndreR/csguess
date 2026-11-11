from django.contrib import admin

from .models import Player, Team


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("nick", "name", "career_status", "team", "is_major_winner")
    search_fields = ("nick", "name", "team__name")
    list_filter = ("career_status", "is_major_winner")
    list_select_related = ("team",)
    autocomplete_fields = ("team",)
    readonly_fields = ("source_collected_at", "created_at", "updated_at")
    fieldsets = (
        ("Identificação", {"fields": ("nick", "name", "nationalities", "photo_url")}),
        ("Carreira", {"fields": ("career_status", "team", "roles", "years_active", "is_major_winner")}),
        ("Origem", {"fields": ("source", "source_id", "source_url", "source_collected_at")}),
        ("Registro", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "photo_url")
    search_fields = ("name",)
