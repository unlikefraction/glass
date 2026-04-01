import secrets
from pathlib import Path

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from accounts.models import Carbon

USERNAME_VALIDATOR = RegexValidator(
    regex=r"^[a-z0-9][a-z0-9_-]*$",
    message="Use lowercase letters, numbers, hyphens, and underscores.",
)


def snapshot_upload_path(instance, filename):
    return f"snapshots/{instance.silicon.username}/{filename}"


class Silicon(models.Model):
    owner = models.ForeignKey(Carbon, related_name="silicons", on_delete=models.CASCADE)
    username = models.CharField(max_length=64, unique=True, validators=[USERNAME_VALIDATOR])
    display_name = models.CharField(max_length=128, blank=True, default="")
    api_key = models.CharField(max_length=64, unique=True, default="", editable=False)
    api_key_last_used = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "silicons"

    def save(self, *args, **kwargs):
        if not self.api_key:
            self.api_key = secrets.token_hex(24)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if not self.username.endswith("silicon"):
            from django.core.exceptions import ValidationError

            raise ValidationError({"username": "Silicon usernames must end with 'silicon'."})

    def __str__(self):
        return self.username


class ConnectorCode(models.Model):
    silicon = models.ForeignKey(Silicon, related_name="connector_codes", on_delete=models.CASCADE)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)
    consumed_by_label = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "connector_codes"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.silicon.username}:{self.code}"


class SourceBinding(models.Model):
    silicon = models.ForeignKey(Silicon, related_name="source_bindings", on_delete=models.CASCADE)
    folder_label = models.CharField(max_length=255)
    folder_fingerprint = models.CharField(max_length=128)
    source_token = models.CharField(max_length=64, unique=True)
    connector_code = models.ForeignKey(ConnectorCode, null=True, blank=True, on_delete=models.SET_NULL)
    claimed_at = models.DateTimeField(auto_now_add=True)
    last_push_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "source_bindings"
        ordering = ["-claimed_at"]

    def __str__(self):
        return f"{self.silicon.username}:{self.folder_label}"


class Snapshot(models.Model):
    silicon = models.ForeignKey(Silicon, related_name="snapshots", on_delete=models.CASCADE)
    binding = models.ForeignKey(SourceBinding, related_name="snapshots", null=True, blank=True, on_delete=models.SET_NULL)
    tree_hash = models.CharField(max_length=64)
    archive = models.FileField(upload_to=snapshot_upload_path)
    archive_size = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "snapshots"
        ordering = ["-created_at"]

    def archive_path(self):
        return Path(settings.MEDIA_ROOT) / self.archive.name
