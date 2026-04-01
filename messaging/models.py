from django.db import models

from syncer.models import Silicon


class SiliconThread(models.Model):
    a = models.ForeignKey(Silicon, related_name="threads_as_a", on_delete=models.CASCADE)
    b = models.ForeignKey(Silicon, related_name="threads_as_b", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "silicon_threads"
        constraints = [
            models.UniqueConstraint(fields=["a", "b"], name="unique_silicon_thread_pair"),
        ]

    def __str__(self):
        return f"{self.a.username} <-> {self.b.username}"


class SiliconMessage(models.Model):
    KIND_CHOICES = [
        ("text", "Text"),
        ("image", "Image"),
        ("video", "Video"),
        ("document", "Document"),
        ("audio", "Audio"),
    ]

    thread = models.ForeignKey(SiliconThread, related_name="messages", on_delete=models.CASCADE)
    sender = models.ForeignKey(Silicon, related_name="sent_messages", on_delete=models.CASCADE)
    recipient = models.ForeignKey(Silicon, related_name="received_messages", on_delete=models.CASCADE)
    body = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default="text")
    attachment = models.FileField(upload_to="message_attachments/", blank=True, null=True)
    attachment_name = models.CharField(max_length=255, blank=True, default="")
    content_type = models.CharField(max_length=128, blank=True, default="")
    size_bytes = models.BigIntegerField(default=0)
    reply_to = models.ForeignKey("self", null=True, blank=True, related_name="replies", on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "silicon_messages"
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.sender.username} -> {self.recipient.username} ({self.kind})"
