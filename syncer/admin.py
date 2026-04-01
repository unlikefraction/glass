from django.contrib import admin

from syncer.models import ConnectorCode, Silicon, Snapshot, SourceBinding


@admin.register(Silicon)
class SiliconAdmin(admin.ModelAdmin):
    list_display = ("username", "owner", "created_at", "is_active")
    search_fields = ("username", "owner__username", "owner__email")


@admin.register(ConnectorCode)
class ConnectorCodeAdmin(admin.ModelAdmin):
    list_display = ("silicon", "code", "created_at", "used_at", "is_active")
    search_fields = ("silicon__username", "code")


@admin.register(SourceBinding)
class SourceBindingAdmin(admin.ModelAdmin):
    list_display = ("silicon", "folder_label", "claimed_at", "last_push_at", "is_active")
    search_fields = ("silicon__username", "folder_label", "folder_fingerprint")


@admin.register(Snapshot)
class SnapshotAdmin(admin.ModelAdmin):
    list_display = ("silicon", "tree_hash", "archive_size", "created_at")
    search_fields = ("silicon__username", "tree_hash")
