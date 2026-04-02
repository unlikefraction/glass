from datetime import timedelta

from django.utils import timezone
from rest_framework.views import APIView

from accounts.views import _require_carbon
from control.models import DebugLog, RemoteCommand
from core.utils import api_response, error_response
from syncer.models import Silicon

COMMAND_EXPIRE_SECONDS = 300  # 5 minutes
MAX_LOG_CHUNKS = 200


# ── Agent-facing endpoints (Bearer auth) ─────────────────────


class HeartbeatView(APIView):
    def post(self, request):
        silicon = getattr(request, "silicon", None)
        if not silicon:
            return error_response("Bearer token required.", status=401)
        status = (request.data.get("status") or "").strip()
        silicon.last_heartbeat = timezone.now()
        if status:
            silicon.reported_status = status
        silicon.save(update_fields=["last_heartbeat", "reported_status"])
        return api_response({"ok": True})


class PendingCommandsView(APIView):
    def get(self, request):
        silicon = getattr(request, "silicon", None)
        if not silicon:
            return error_response("Bearer token required.", status=401)
        cutoff = timezone.now() - timedelta(seconds=COMMAND_EXPIRE_SECONDS)
        RemoteCommand.objects.filter(
            silicon=silicon, status="pending", created_at__lt=cutoff
        ).update(status="expired")
        commands = RemoteCommand.objects.filter(silicon=silicon, status="pending").order_by("created_at")
        return api_response({
            "commands": [
                {"id": c.id, "command": c.command, "created_at": c.created_at.isoformat()}
                for c in commands
            ]
        })


class AckCommandView(APIView):
    def post(self, request, command_id):
        silicon = getattr(request, "silicon", None)
        if not silicon:
            return error_response("Bearer token required.", status=401)
        cmd = RemoteCommand.objects.filter(id=command_id, silicon=silicon, status="pending").first()
        if not cmd:
            return error_response("Command not found or already processed.", status=404)
        cmd.status = "ack"
        cmd.acked_at = timezone.now()
        cmd.save(update_fields=["status", "acked_at"])
        return api_response({"ok": True})


class CompleteCommandView(APIView):
    def post(self, request, command_id):
        silicon = getattr(request, "silicon", None)
        if not silicon:
            return error_response("Bearer token required.", status=401)
        cmd = RemoteCommand.objects.filter(
            id=command_id, silicon=silicon, status__in=("pending", "ack")
        ).first()
        if not cmd:
            return error_response("Command not found or already completed.", status=404)
        result_status = (request.data.get("status") or "done").strip()
        message = (request.data.get("message") or "").strip()
        cmd.status = result_status if result_status in ("done", "failed") else "done"
        cmd.completed_at = timezone.now()
        cmd.result_message = message
        cmd.save(update_fields=["status", "completed_at", "result_message"])
        return api_response({"ok": True})


class PostLogsView(APIView):
    def post(self, request):
        silicon = getattr(request, "silicon", None)
        if not silicon:
            return error_response("Bearer token required.", status=401)
        lines = (request.data.get("lines") or "").strip()
        if not lines:
            return api_response({"ok": True, "skipped": True})
        DebugLog.objects.create(silicon=silicon, chunk=lines)
        # Prune old chunks
        count = DebugLog.objects.filter(silicon=silicon).count()
        if count > MAX_LOG_CHUNKS:
            oldest_ids = (
                DebugLog.objects.filter(silicon=silicon)
                .order_by("id")
                .values_list("id", flat=True)[: count - MAX_LOG_CHUNKS]
            )
            DebugLog.objects.filter(id__in=list(oldest_ids)).delete()
        return api_response({"ok": True})


# ── Carbon-facing endpoints (session auth) ───────────────────


class CreateCommandView(APIView):
    def post(self, request, username):
        carbon = _require_carbon(request)
        if not carbon:
            return error_response("Not authenticated.", status=401)
        silicon = Silicon.objects.filter(owner=carbon, username=username).first()
        if not silicon:
            return error_response("Bud not found.", status=404)
        command = (request.data.get("command") or "").strip().lower()
        if command not in ("start", "stop", "restart"):
            return error_response("Invalid command. Use start, stop, or restart.")
        # Expire existing pending commands for this silicon
        RemoteCommand.objects.filter(silicon=silicon, status="pending").update(status="expired")
        cmd = RemoteCommand.objects.create(
            silicon=silicon, command=command, created_by=carbon
        )
        return api_response({
            "id": cmd.id,
            "command": cmd.command,
            "status": cmd.status,
            "created_at": cmd.created_at.isoformat(),
        }, status=201)


class SiliconStatusView(APIView):
    def get(self, request, username):
        carbon = _require_carbon(request)
        if not carbon:
            return error_response("Not authenticated.", status=401)
        silicon = Silicon.objects.filter(owner=carbon, username=username).first()
        if not silicon:
            return error_response("Bud not found.", status=404)
        agent_connected = False
        if silicon.last_heartbeat:
            age = (timezone.now() - silicon.last_heartbeat).total_seconds()
            agent_connected = age < 45
        pending = RemoteCommand.objects.filter(silicon=silicon, status__in=("pending", "ack")).order_by("-created_at")[:5]
        recent = RemoteCommand.objects.filter(silicon=silicon).order_by("-created_at")[:10]
        return api_response({
            "agent_connected": agent_connected,
            "last_heartbeat": silicon.last_heartbeat.isoformat() if silicon.last_heartbeat else None,
            "reported_status": silicon.reported_status,
            "pending_commands": [
                {"id": c.id, "command": c.command, "status": c.status, "created_at": c.created_at.isoformat()}
                for c in pending
            ],
            "recent_commands": [
                {
                    "id": c.id,
                    "command": c.command,
                    "status": c.status,
                    "created_at": c.created_at.isoformat(),
                    "result_message": c.result_message,
                }
                for c in recent
            ],
        })


class SiliconLogsView(APIView):
    def get(self, request, username):
        carbon = _require_carbon(request)
        if not carbon:
            return error_response("Not authenticated.", status=401)
        silicon = Silicon.objects.filter(owner=carbon, username=username).first()
        if not silicon:
            return error_response("Bud not found.", status=404)
        after_id = request.GET.get("after")
        logs = DebugLog.objects.filter(silicon=silicon)
        if after_id:
            try:
                logs = logs.filter(id__gt=int(after_id))
            except ValueError:
                pass
        else:
            # Return last 20 chunks if no cursor
            logs = logs.order_by("-id")[:20]
            logs = sorted(logs, key=lambda x: x.id)
        chunks = [{"id": l.id, "chunk": l.chunk, "created_at": l.created_at.isoformat()} for l in logs[:50]]
        return api_response({"logs": chunks})
