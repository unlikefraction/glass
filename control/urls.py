from django.urls import path

from control.views import (
    AckCommandView,
    CompleteCommandView,
    CreateCommandView,
    HeartbeatView,
    PendingCommandsView,
    PostLogsView,
    SiliconLogsView,
    SiliconStatusView,
)

urlpatterns = [
    # Agent-facing (Bearer auth)
    path("api/heartbeat/", HeartbeatView.as_view(), name="control_heartbeat"),
    path("api/commands/pending/", PendingCommandsView.as_view(), name="control_pending"),
    path("api/commands/<int:command_id>/ack/", AckCommandView.as_view(), name="control_ack"),
    path("api/commands/<int:command_id>/complete/", CompleteCommandView.as_view(), name="control_complete"),
    path("api/logs/", PostLogsView.as_view(), name="control_post_logs"),
    # Carbon-facing (session auth)
    path("api/silicons/<str:username>/command/", CreateCommandView.as_view(), name="control_create_command"),
    path("api/silicons/<str:username>/status/", SiliconStatusView.as_view(), name="control_status"),
    path("api/silicons/<str:username>/logs/", SiliconLogsView.as_view(), name="control_logs"),
]
