from django.db import models

from accounts.models import Carbon
from syncer.models import Silicon


class RemoteCommand(models.Model):
    COMMAND_CHOICES = [
        ("start", "Start"),
        ("stop", "Stop"),
        ("restart", "Restart"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("ack", "Acknowledged"),
        ("done", "Done"),
        ("failed", "Failed"),
        ("expired", "Expired"),
    ]

    silicon = models.ForeignKey(Silicon, related_name="commands", on_delete=models.CASCADE)
    command = models.CharField(max_length=16, choices=COMMAND_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    acked_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    result_message = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(Carbon, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        db_table = "remote_commands"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.silicon.username}:{self.command}({self.status})"


class DebugLog(models.Model):
    silicon = models.ForeignKey(Silicon, related_name="debug_logs", on_delete=models.CASCADE)
    chunk = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "debug_logs"
        ordering = ["id"]

    def __str__(self):
        return f"{self.silicon.username}:log#{self.id}"
