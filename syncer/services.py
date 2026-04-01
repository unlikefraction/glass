import os
import secrets

from django.core.files.base import File
from django.db import transaction
from django.utils import timezone

from syncer.models import ConnectorCode, Silicon, Snapshot, SourceBinding


def generate_connector_code(silicon):
    with transaction.atomic():
        ConnectorCode.objects.filter(silicon=silicon, is_active=True).update(is_active=False)
        SourceBinding.objects.filter(silicon=silicon, is_active=True).update(is_active=False)
        code = f"{secrets.randbelow(1000000):06d}"
        return ConnectorCode.objects.create(silicon=silicon, code=code)


def claim_connector(*, silicon, code, folder_label, folder_fingerprint):
    with transaction.atomic():
        connector = ConnectorCode.objects.select_for_update().filter(
            silicon=silicon,
            code=code,
            is_active=True,
            used_at__isnull=True,
        ).first()
        if connector is None:
            return None, "Invalid or stale connector code."

        ConnectorCode.objects.filter(silicon=silicon, is_active=True).exclude(id=connector.id).update(is_active=False)
        SourceBinding.objects.filter(silicon=silicon, is_active=True).update(is_active=False)

        connector.used_at = timezone.now()
        connector.consumed_by_label = folder_label
        connector.save(update_fields=["used_at", "consumed_by_label"])

        binding = SourceBinding.objects.create(
            silicon=silicon,
            folder_label=folder_label,
            folder_fingerprint=folder_fingerprint,
            source_token=secrets.token_hex(24),
            connector_code=connector,
            is_active=True,
        )
        return binding, None


def create_snapshot(*, silicon, binding, tree_hash, incoming_file):
    latest = silicon.snapshots.order_by("-created_at").first()
    if latest and latest.tree_hash == tree_hash:
        return latest, False

    filename = os.path.basename(getattr(incoming_file, "name", "") or f"{tree_hash}.tar.gz")
    snapshot = Snapshot.objects.create(
        silicon=silicon,
        binding=binding,
        tree_hash=tree_hash,
        archive_size=getattr(incoming_file, "size", 0) or 0,
    )
    snapshot.archive.save(filename, File(incoming_file), save=True)

    if binding is not None:
        binding.last_push_at = timezone.now()
        binding.save(update_fields=["last_push_at", "last_seen_at"])

    excess_ids = list(silicon.snapshots.order_by("-created_at").values_list("id", flat=True)[24:])
    if excess_ids:
        for old in Snapshot.objects.filter(id__in=excess_ids):
            storage = old.archive.storage
            if old.archive.name and storage.exists(old.archive.name):
                storage.delete(old.archive.name)
            old.delete()

    return snapshot, True
