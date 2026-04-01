from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views import View
from rest_framework.parsers import MultiPartParser
from rest_framework.views import APIView

from accounts.views import _require_carbon
from core.utils import api_response, error_response
from syncer.models import Silicon, Snapshot, SourceBinding
from syncer.services import claim_connector, create_snapshot, generate_connector_code


def _binding_from_token(token):
    if not token:
        return None
    return SourceBinding.objects.select_related("silicon").filter(source_token=token, is_active=True).first()


class SiliconDetailView(View):
    def get(self, request, username):
        carbon = _require_carbon(request)
        if not carbon:
            return redirect("/accounts/dashboard/")
        silicon = Silicon.objects.filter(owner=carbon, username=username).first()
        if not silicon:
            raise Http404
        connectors = silicon.connector_codes.order_by("-created_at")[:10]
        bindings = silicon.source_bindings.order_by("-claimed_at")[:10]
        snapshots = silicon.snapshots.order_by("-created_at")[:24]
        return render(
            request,
            "syncer/silicon_detail.html",
            {
                "silicon": silicon,
                "connectors": connectors,
                "bindings": bindings,
                "snapshots": snapshots,
            },
        )


class ConnectorGenerateView(View):
    def post(self, request, username):
        carbon = _require_carbon(request)
        if not carbon:
            return redirect("/accounts/dashboard/")
        silicon = Silicon.objects.filter(owner=carbon, username=username).first()
        if silicon:
            generate_connector_code(silicon)
        return redirect(f"/sync/silicons/{username}/")


class ConnectorGenerateApiView(APIView):
    def post(self, request, username):
        carbon = _require_carbon(request)
        if not carbon:
            return error_response("Not authenticated.", status=401)
        silicon = Silicon.objects.filter(owner=carbon, username=username).first()
        if not silicon:
            return error_response("Silicon not found.", status=404)
        connector = generate_connector_code(silicon)
        return api_response(
            {"code": connector.code, "silicon": silicon.username},
            meta={"code": "One-time 6 digit connector code", "silicon": "Silicon username"},
            status=201,
        )


class PullClaimApiView(APIView):
    def post(self, request):
        username = (request.data.get("username") or "").strip().lower()
        code = (request.data.get("connector_code") or "").strip()
        folder_label = (request.data.get("folder_label") or "").strip() or username
        folder_fingerprint = (request.data.get("folder_fingerprint") or "").strip() or folder_label
        if not username or not code:
            return error_response("username and connector_code are required.")

        silicon = Silicon.objects.filter(username=username, is_active=True).first()
        if not silicon:
            return error_response("Silicon not found.", status=404)

        binding, err = claim_connector(
            silicon=silicon,
            code=code,
            folder_label=folder_label,
            folder_fingerprint=folder_fingerprint,
        )
        if err:
            return error_response(err, status=401)

        snapshot = silicon.snapshots.order_by("-created_at").first()
        return api_response(
            {
                "silicon": silicon.username,
                "source_token": binding.source_token,
                "api_key": silicon.api_key,
                "has_snapshot": snapshot is not None,
                "latest_tree_hash": snapshot.tree_hash if snapshot else "",
            },
            meta={
                "silicon": "Silicon username",
                "source_token": "Folder-scoped push token to save locally in the pulled folder",
                "api_key": "Silicon bearer token for authenticated silicon messaging",
                "has_snapshot": "Whether a snapshot exists to download",
                "latest_tree_hash": "Tree hash of the latest snapshot if one exists",
            },
        )


class LatestSnapshotApiView(APIView):
    def get(self, request, username):
        token = request.headers.get("X-Source-Token", "")
        binding = _binding_from_token(token)
        if binding is None or binding.silicon.username != username:
            return error_response("Invalid source token.", status=401)
        snapshot = binding.silicon.snapshots.order_by("-created_at").first()
        if snapshot is None:
            return error_response("No snapshot exists yet.", status=404)
        return FileResponse(snapshot.archive.open("rb"), as_attachment=True, filename=f"{username}.tar.gz")


class PushApiView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request, username):
        token = request.headers.get("X-Source-Token", "")
        binding = _binding_from_token(token)
        if binding is None or binding.silicon.username != username:
            return error_response("Connector is stale.", status=401)

        archive = request.FILES.get("archive")
        tree_hash = (request.data.get("tree_hash") or "").strip()
        if archive is None or not tree_hash:
            return error_response("archive and tree_hash are required.")

        snapshot, created = create_snapshot(
            silicon=binding.silicon,
            binding=binding,
            tree_hash=tree_hash,
            incoming_file=archive,
        )
        return api_response(
            {
                "created": created,
                "snapshot_id": snapshot.id,
                "tree_hash": snapshot.tree_hash,
            },
            meta={
                "created": "Whether a new snapshot was stored",
                "snapshot_id": "Stored snapshot identifier",
                "tree_hash": "Hash of the uploaded tree",
            },
        )


class SnapshotListApiView(APIView):
    def get(self, request, username):
        silicon = Silicon.objects.filter(username=username, is_active=True).first()
        if not silicon:
            return error_response("Silicon not found.", status=404)
        snapshots = [
            {
                "id": snapshot.id,
                "tree_hash": snapshot.tree_hash,
                "created_at": snapshot.created_at.isoformat(),
                "archive_size": snapshot.archive_size,
            }
            for snapshot in silicon.snapshots.order_by("-created_at")[:24]
        ]
        return api_response({"snapshots": snapshots}, meta={"snapshots": "Most recent stored snapshots"})
