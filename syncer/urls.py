from django.urls import path

from syncer.views import (
    ConnectorGenerateApiView,
    ConnectorGenerateView,
    LatestSnapshotApiView,
    PullClaimApiView,
    PushApiView,
    SiliconControlView,
    SiliconConversationView,
    SiliconDetailView,
    SiliconDownloadView,
    SiliconFileView,
    SiliconMessagesView,
    SiliconSettingsView,
    SnapshotListApiView,
)

urlpatterns = [
    # HTML views
    path("silicons/<str:username>/", SiliconDetailView.as_view(), name="silicon_detail"),
    path("silicons/<str:username>/file/", SiliconFileView.as_view(), name="silicon_file"),
    path("silicons/<str:username>/download/", SiliconDownloadView.as_view(), name="silicon_download"),
    path("silicons/<str:username>/control/", SiliconControlView.as_view(), name="silicon_control"),
    path("silicons/<str:username>/messages/", SiliconMessagesView.as_view(), name="silicon_messages"),
    path("silicons/<str:username>/messages/<str:other_username>/", SiliconConversationView.as_view(), name="silicon_conversation"),
    path("silicons/<str:username>/settings/", SiliconSettingsView.as_view(), name="silicon_settings"),
    path("silicons/<str:username>/connector/", ConnectorGenerateView.as_view(), name="connector_generate"),
    # API views (unchanged)
    path("api/silicons/<str:username>/connector/", ConnectorGenerateApiView.as_view(), name="connector_generate_api"),
    path("api/pull/claim/", PullClaimApiView.as_view(), name="pull_claim"),
    path("api/silicons/<str:username>/latest.tar.gz", LatestSnapshotApiView.as_view(), name="latest_snapshot"),
    path("api/silicons/<str:username>/push/", PushApiView.as_view(), name="push_api"),
    path("api/silicons/<str:username>/snapshots/", SnapshotListApiView.as_view(), name="snapshot_list"),
]
