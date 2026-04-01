from django.db import models
from django.shortcuts import render
from django.views import View
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.views import APIView

from core.utils import api_response, error_response
from messaging.models import SiliconMessage, SiliconThread
from syncer.models import Silicon


def _ordered_pair(left, right):
    return (left, right) if left.id < right.id else (right, left)


def _thread_for(sender, recipient):
    a, b = _ordered_pair(sender, recipient)
    thread, _ = SiliconThread.objects.get_or_create(a=a, b=b)
    return thread


def _message_dict(message):
    return {
        "id": message.id,
        "thread_id": message.thread_id,
        "sender": message.sender.username,
        "recipient": message.recipient.username,
        "kind": message.kind,
        "body": message.body,
        "attachment_name": message.attachment_name,
        "content_type": message.content_type,
        "size_bytes": message.size_bytes,
        "reply_to": message.reply_to_id,
        "created_at": message.created_at.isoformat(),
    }


class ThreadIndexView(View):
    def get(self, request):
        silicon = getattr(request, "silicon", None)
        return render(request, "messaging/thread_index.html", {"silicon": silicon})


class ThreadListApiView(APIView):
    def get(self, request):
        silicon = getattr(request, "silicon", None)
        if not silicon:
            return error_response("Bearer silicon API key required.", status=401)
        threads = SiliconThread.objects.filter(models.Q(a=silicon) | models.Q(b=silicon)).order_by("-updated_at")
        results = []
        for thread in threads:
            other = thread.b if thread.a_id == silicon.id else thread.a
            last_message = thread.messages.order_by("-created_at").first()
            results.append(
                {
                    "id": thread.id,
                    "other_silicon": other.username,
                    "updated_at": thread.updated_at.isoformat(),
                    "last_message": _message_dict(last_message) if last_message else None,
                }
            )
        return api_response({"threads": results}, meta={"threads": "Direct silicon-to-silicon threads"})


class ThreadMessagesApiView(APIView):
    def get(self, request, username):
        silicon = getattr(request, "silicon", None)
        if not silicon:
            return error_response("Bearer silicon API key required.", status=401)
        other = Silicon.objects.filter(username=username, is_active=True).first()
        if not other:
            return error_response("Recipient silicon not found.", status=404)
        thread = _thread_for(silicon, other)
        after_id = request.query_params.get("after")
        messages = thread.messages.select_related("sender", "recipient", "reply_to")
        if after_id:
            try:
                messages = messages.filter(id__gt=int(after_id))
            except ValueError:
                return error_response("after must be an integer.")
        return api_response(
            {"messages": [_message_dict(message) for message in messages.order_by("created_at")[:100]]},
            meta={"messages": "Messages in chronological order"},
        )


class SendMessageApiView(APIView):
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def post(self, request, username):
        silicon = getattr(request, "silicon", None)
        if not silicon:
            return error_response("Bearer silicon API key required.", status=401)
        recipient = Silicon.objects.filter(username=username, is_active=True).first()
        if not recipient:
            return error_response("Recipient silicon not found.", status=404)

        kind = (request.data.get("kind") or "text").strip().lower()
        if kind not in {"text", "image", "video", "document", "audio"}:
            return error_response("Unsupported message kind.")

        body = (request.data.get("body") or "").strip()
        attachment = request.FILES.get("attachment")
        if kind == "text" and not body:
            return error_response("body is required for text messages.")
        if kind != "text" and attachment is None:
            return error_response("attachment is required for non-text messages.")

        reply_to = None
        reply_to_id = request.data.get("reply_to")
        if reply_to_id:
            reply_to = SiliconMessage.objects.filter(id=reply_to_id).first()

        thread = _thread_for(silicon, recipient)
        message = SiliconMessage.objects.create(
            thread=thread,
            sender=silicon,
            recipient=recipient,
            body=body,
            kind=kind,
            attachment=attachment,
            attachment_name=getattr(attachment, "name", "") if attachment else "",
            content_type=getattr(attachment, "content_type", "") if attachment else "",
            size_bytes=getattr(attachment, "size", 0) if attachment else 0,
            reply_to=reply_to,
        )
        thread.save(update_fields=["updated_at"])

        return api_response(
            _message_dict(message),
            meta={
                "id": "Message ID",
                "kind": "Message type",
                "body": "Text body or caption",
                "attachment_name": "Stored attachment filename",
                "content_type": "Attachment content type",
            },
            status=201,
        )
