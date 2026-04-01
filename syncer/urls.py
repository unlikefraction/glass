from django.urls import path

from syncer.views import (
    ConnectorGenerateApiView,
    ConnectorGenerateView,
    LatestSnapshotApiView,
    PullClaimApiView,
    PushApiView,
    SiliconDetailView,
    SnapshotListApiView,
)

urlpatterns = [
    path("silicons/<str:username>/", SiliconDetailView.as_view(), name="silicon_detail"),
    path("silicons/<str:username>/connector/", ConnectorGenerateView.as_view(), name="connector_generate"),
    path("api/silicons/<str:username>/connector/", ConnectorGenerateApiView.as_view(), name="connector_generate_api"),
    path("api/pull/claim/", PullClaimApiView.as_view(), name="pull_claim"),
    path("api/silicons/<str:username>/latest.tar.gz", LatestSnapshotApiView.as_view(), name="latest_snapshot"),
    path("api/silicons/<str:username>/push/", PushApiView.as_view(), name="push_api"),
    path("api/silicons/<str:username>/snapshots/", SnapshotListApiView.as_view(), name="snapshot_list"),
]
