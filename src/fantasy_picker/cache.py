"""Raw snapshot checksum and provenance helpers."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from fantasy_picker.contracts import validate


class ProvenanceManifest(TypedDict):
    schema_version: str
    snapshot_id: str
    dataset_id: str
    source_id: str
    source_url: str
    retrieved_at: str
    local_path: str
    sha256: str
    byte_count: int
    media_type: str
    license: str | None
    notes: str | None


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def build_provenance(
    path: Path,
    *,
    repository_root: Path,
    source_id: str,
    dataset_id: str,
    source_url: str,
    media_type: str,
    retrieved_at: datetime | None = None,
    license_name: str | None = None,
    notes: str | None = None,
) -> ProvenanceManifest:
    """Build and validate a manifest for an immutable file under data/raw."""
    resolved_path = path.resolve()
    resolved_root = repository_root.resolve()
    relative_path = resolved_path.relative_to(resolved_root)
    if relative_path.parts[:2] != ("data", "raw"):
        raise ValueError("Raw snapshots must live below data/raw")

    timestamp = retrieved_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("retrieved_at must be timezone-aware")

    manifest = ProvenanceManifest(
        schema_version="1.0.0",
        snapshot_id=f"snp_{uuid4().hex}",
        dataset_id=dataset_id,
        source_id=source_id,
        source_url=source_url,
        retrieved_at=timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        local_path=relative_path.as_posix(),
        sha256=sha256_file(resolved_path),
        byte_count=resolved_path.stat().st_size,
        media_type=media_type,
        license=license_name,
        notes=notes,
    )
    validate(manifest, "provenance")
    return manifest


def verify_provenance(manifest: ProvenanceManifest, *, repository_root: Path) -> bool:
    validate(manifest, "provenance")
    path = repository_root.resolve() / manifest["local_path"]
    return (
        path.is_file()
        and path.stat().st_size == manifest["byte_count"]
        and sha256_file(path) == manifest["sha256"]
    )
