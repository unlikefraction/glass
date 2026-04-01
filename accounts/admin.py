from django.contrib import admin

from accounts.models import Carbon


@admin.register(Carbon)
class CarbonAdmin(admin.ModelAdmin):
    list_display = ("username", "email", "created_at", "is_active")
    search_fields = ("username", "email", "google_sub")
