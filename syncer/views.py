import io
import json
import mimetypes
import tarfile

from django.db import models
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils.html import escape
from django.views import View
from rest_framework.parsers import MultiPartParser
from rest_framework.views import APIView

from accounts.views import _require_carbon
from core.utils import api_response, error_response
from messaging.models import SiliconMessage, SiliconThread
from syncer.models import Silicon, Snapshot, SourceBinding
from syncer.services import claim_connector, create_snapshot, generate_connector_code


def _binding_from_token(token):
    if not token:
        return None
    return SourceBinding.objects.select_related("silicon").filter(source_token=token, is_active=True).first()


# ── File type helpers ────────────────────────────────────────

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".sh", ".bash", ".zsh", ".fish",
    ".rs", ".go", ".java", ".kt", ".c", ".cpp", ".h", ".hpp",
    ".rb", ".php", ".pl", ".lua", ".r", ".m", ".swift",
    ".sql", ".graphql", ".proto",
    ".xml", ".svg", ".csv", ".tsv",
    ".env", ".gitignore", ".dockerignore", ".editorconfig",
    ".txt", ".log", ".md", ".rst", ".tex",
    "Makefile", "Dockerfile", "Procfile", "Vagrantfile",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".svg"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".avi", ".mkv"}
PDF_EXTENSIONS = {".pdf"}
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".rst"}

# Files/dirs to hide from the browser
HIDDEN_NAMES = {"__pycache__", ".DS_Store", ".git", ".hg", ".svn"}


def _get_view_mode(filename):
    name_lower = filename.lower()
    ext = ""
    if "." in name_lower:
        ext = "." + name_lower.rsplit(".", 1)[1]

    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in MARKDOWN_EXTENSIONS:
        return "markdown"
    if ext in CODE_EXTENSIONS or name_lower in CODE_EXTENSIONS:
        return "code"
    # Try to detect text files
    if ext in {".txt", ".log", ".csv", ".tsv"}:
        return "code"
    return "binary"


def _extract_file_tree(snapshot, path_prefix=""):
    """Extract directory listing from a snapshot's tar.gz archive."""
    if not snapshot or not snapshot.archive:
        return [], 0

    entries = []
    try:
        snapshot.archive.seek(0)
        with tarfile.open(fileobj=snapshot.archive, mode="r:gz") as tar:
            dirs = {}
            files = []

            for member in tar.getmembers():
                name = member.name
                # Strip leading ./ or /
                if name.startswith("./"):
                    name = name[2:]
                if name.startswith("/"):
                    name = name[1:]
                if not name:
                    continue

                # Skip hidden files
                parts = name.split("/")
                if any(p in HIDDEN_NAMES for p in parts):
                    continue

                # Filter by path prefix
                if path_prefix:
                    if not name.startswith(path_prefix.rstrip("/") + "/"):
                        continue
                    name = name[len(path_prefix.rstrip("/")) + 1:]
                    if not name:
                        continue

                # Only show direct children (not nested)
                parts = name.split("/")
                if len(parts) == 1 and not member.isdir():
                    files.append({
                        "name": parts[0],
                        "path": (path_prefix + "/" + parts[0]).lstrip("/") if path_prefix else parts[0],
                        "size": member.size,
                        "is_dir": False,
                    })
                elif len(parts) >= 1:
                    dir_name = parts[0]
                    if dir_name not in dirs:
                        dirs[dir_name] = 0
                    dirs[dir_name] += 1

            # Build sorted entries: directories first, then files
            for dir_name, count in sorted(dirs.items()):
                entries.append({
                    "name": dir_name,
                    "path": (path_prefix + "/" + dir_name).lstrip("/") if path_prefix else dir_name,
                    "count": count,
                    "is_dir": True,
                })
            entries.extend(sorted(files, key=lambda f: f["name"]))

    except (tarfile.TarError, OSError):
        return [], 0

    total_files = sum(1 for e in entries if not e.get("is_dir"))
    total_files += sum(e.get("count", 0) for e in entries if e.get("is_dir"))
    return entries, total_files


def _extract_file_content(snapshot, file_path):
    """Extract a single file's content from a snapshot's tar.gz archive."""
    if not snapshot or not snapshot.archive:
        return None, 0

    try:
        snapshot.archive.seek(0)
        with tarfile.open(fileobj=snapshot.archive, mode="r:gz") as tar:
            for member in tar.getmembers():
                name = member.name
                if name.startswith("./"):
                    name = name[2:]
                if name.startswith("/"):
                    name = name[1:]

                if name == file_path and not member.isdir():
                    f = tar.extractfile(member)
                    if f:
                        return f.read(), member.size
            return None, 0
    except (tarfile.TarError, OSError):
        return None, 0


def _build_breadcrumb(path):
    """Build breadcrumb parts from a file path."""
    if not path:
        return []
    parts = path.split("/")
    result = []
    for i, part in enumerate(parts):
        result.append({
            "name": part,
            "path": "/".join(parts[: i + 1]),
        })
    return result


# ── HTML Views ───────────────────────────────────────────────


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
        snapshots = list(silicon.snapshots.order_by("-created_at")[:24])

        # Determine which snapshot to show
        snapshot_id = request.GET.get("snapshot")
        selected_snapshot = None
        if snapshot_id:
            selected_snapshot = Snapshot.objects.filter(id=snapshot_id, silicon=silicon).first()
        if not selected_snapshot and snapshots:
            selected_snapshot = snapshots[0]

        # File browser
        current_path = request.GET.get("path", "")
        file_tree, file_count = _extract_file_tree(selected_snapshot, current_path)

        # Build breadcrumb for current path
        breadcrumb_parts = _build_breadcrumb(current_path) if current_path else []

        # Parent path for ".." link
        parent_path = None
        if current_path:
            parts = current_path.rstrip("/").split("/")
            parent_path = "/".join(parts[:-1]) if len(parts) > 1 else ""

        return render(
            request,
            "syncer/silicon_detail.html",
            {
                "silicon": silicon,
                "connectors": connectors,
                "bindings": bindings,
                "snapshots": snapshots,
                "selected_snapshot": selected_snapshot,
                "latest_snapshot": snapshots[0] if snapshots else None,
                "file_tree": file_tree,
                "file_count": file_count,
                "current_path": current_path,
                "breadcrumb_parts": breadcrumb_parts,
                "parent_path": parent_path,
                "active_tab": "code",
            },
        )


class SiliconFileView(View):
    def get(self, request, username):
        carbon = _require_carbon(request)
        if not carbon:
            return redirect("/accounts/dashboard/")
        silicon = Silicon.objects.filter(owner=carbon, username=username).first()
        if not silicon:
            raise Http404

        snapshot_id = request.GET.get("snapshot")
        file_path = request.GET.get("path", "")
        raw = request.GET.get("raw")

        snapshot = Snapshot.objects.filter(id=snapshot_id, silicon=silicon).first() if snapshot_id else None
        if not snapshot:
            raise Http404

        content_bytes, file_size = _extract_file_content(snapshot, file_path)
        if content_bytes is None:
            raise Http404

        file_name = file_path.split("/")[-1] if "/" in file_path else file_path

        # Raw download
        if raw:
            content_type, _ = mimetypes.guess_type(file_name)
            content_type = content_type or "application/octet-stream"
            response = HttpResponse(content_bytes, content_type=content_type)
            if "image" not in content_type and "video" not in content_type and "pdf" not in content_type:
                response["Content-Disposition"] = f'attachment; filename="{file_name}"'
            return response

        view_mode = _get_view_mode(file_name)
        breadcrumb_parts = _build_breadcrumb(file_path)

        context = {
            "silicon": silicon,
            "snapshot": snapshot,
            "file_path": file_path,
            "file_name": file_name,
            "file_size": file_size,
            "view_mode": view_mode,
            "breadcrumb_parts": breadcrumb_parts,
        }

        if view_mode in ("code", "json"):
            try:
                text = content_bytes.decode("utf-8", errors="replace")
                context["content"] = escape(text)
                context["line_count"] = text.count("\n") + 1
            except Exception:
                context["view_mode"] = "binary"
        elif view_mode == "markdown":
            try:
                text = content_bytes.decode("utf-8", errors="replace")
                # Pass as JSON string for safe JS embedding
                context["content"] = json.dumps(text)
                context["line_count"] = text.count("\n") + 1
            except Exception:
                context["view_mode"] = "binary"

        return render(request, "syncer/file_view.html", context)


class SiliconDownloadView(View):
    def get(self, request, username):
        carbon = _require_carbon(request)
        if not carbon:
            return redirect("/accounts/dashboard/")
        silicon = Silicon.objects.filter(owner=carbon, username=username).first()
        if not silicon:
            raise Http404

        snapshot_id = request.GET.get("snapshot")
        if snapshot_id:
            snapshot = Snapshot.objects.filter(id=snapshot_id, silicon=silicon).first()
        else:
            snapshot = silicon.snapshots.order_by("-created_at").first()

        if not snapshot:
            raise Http404

        return FileResponse(
            snapshot.archive.open("rb"),
            as_attachment=True,
            filename=f"{username}-{snapshot.tree_hash[:8]}.tar.gz",
        )


class SiliconMessagesView(View):
    def get(self, request, username):
        carbon = _require_carbon(request)
        if not carbon:
            return redirect("/accounts/dashboard/")
        silicon = Silicon.objects.filter(owner=carbon, username=username).first()
        if not silicon:
            raise Http404

        # Get all threads involving this silicon
        threads = SiliconThread.objects.filter(
            models.Q(a=silicon) | models.Q(b=silicon)
        ).select_related("a", "b").order_by("-updated_at")

        thread_data = []
        for thread in threads:
            other = thread.b if thread.a_id == silicon.id else thread.a
            last_msg = thread.messages.order_by("-created_at").first()
            thread_data.append({
                "other_username": other.username,
                "other_display_name": other.display_name,
                "updated_at": thread.updated_at,
                "last_message": last_msg,
            })

        return render(
            request,
            "syncer/silicon_detail.html",
            {
                "silicon": silicon,
                "connectors": [],
                "bindings": [],
                "snapshots": [],
                "threads": thread_data,
                "active_tab": "messages",
            },
        )


class SiliconConversationView(View):
    def get(self, request, username, other_username):
        carbon = _require_carbon(request)
        if not carbon:
            return redirect("/accounts/dashboard/")
        silicon = Silicon.objects.filter(owner=carbon, username=username).first()
        if not silicon:
            raise Http404

        other = Silicon.objects.filter(username=other_username, is_active=True).first()
        if not other:
            raise Http404

        # Get or find the thread
        a, b = (silicon, other) if silicon.id < other.id else (other, silicon)
        thread = SiliconThread.objects.filter(a=a, b=b).first()

        messages = []
        if thread:
            messages = list(
                thread.messages.select_related("sender", "recipient")
                .order_by("created_at")
            )

        return render(
            request,
            "syncer/messages.html",
            {
                "silicon": silicon,
                "other_username": other_username,
                "other_display_name": other.display_name,
                "messages": messages,
            },
        )


class SiliconControlView(View):
    def get(self, request, username):
        carbon = _require_carbon(request)
        if not carbon:
            return redirect("/accounts/dashboard/")
        silicon = Silicon.objects.filter(owner=carbon, username=username).first()
        if not silicon:
            raise Http404
        return render(
            request,
            "syncer/silicon_detail.html",
            {
                "silicon": silicon,
                "connectors": [],
                "bindings": [],
                "snapshots": [],
                "active_tab": "control",
            },
        )


class SiliconSettingsView(View):
    def get(self, request, username):
        carbon = _require_carbon(request)
        if not carbon:
            return redirect("/accounts/dashboard/")
        silicon = Silicon.objects.filter(owner=carbon, username=username).first()
        if not silicon:
            raise Http404

        connectors = silicon.connector_codes.order_by("-created_at")[:10]
        bindings = silicon.source_bindings.order_by("-claimed_at")[:10]

        return render(
            request,
            "syncer/silicon_detail.html",
            {
                "silicon": silicon,
                "connectors": connectors,
                "bindings": bindings,
                "snapshots": [],
                "active_tab": "settings",
            },
        )


# ── API Views (unchanged) ───────────────────────────────────


class ConnectorGenerateView(View):
    def post(self, request, username):
        carbon = _require_carbon(request)
        if not carbon:
            return redirect("/accounts/dashboard/")
        silicon = Silicon.objects.filter(owner=carbon, username=username).first()
        if silicon:
            generate_connector_code(silicon)
        return redirect(f"/sync/silicons/{username}/settings/")


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
