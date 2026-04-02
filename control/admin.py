from django.contrib import admin

from control.models import DebugLog, RemoteCommand

admin.site.register(RemoteCommand)
admin.site.register(DebugLog)
