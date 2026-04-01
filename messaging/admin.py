from django.contrib import admin

from messaging.models import SiliconMessage, SiliconThread


@admin.register(SiliconThread)
class SiliconThreadAdmin(admin.ModelAdmin):
    list_display = ("a", "b", "updated_at")
    search_fields = ("a__username", "b__username")


@admin.register(SiliconMessage)
class SiliconMessageAdmin(admin.ModelAdmin):
    list_display = ("sender", "recipient", "kind", "created_at")
    search_fields = ("sender__username", "recipient__username", "body")
