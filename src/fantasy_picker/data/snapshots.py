"""Immutable raw snapshot storage."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fantasy_picker.cache import ProvenanceManifest, build_provenance, verify_provenance


@dataclass(frozen=True)
class StoredSnapshot:
    path: Path
    manifest_path: Path
    manifest: ProvenanceManifest
    reused: bool


class SnapshotStore:
    def __init__(self, repository_root: Path, *, batch: str | None = None) -> None:
        self.repository_root = repository_root.resolve()
        self.batch = batch or datetime.now(UTC).strftime("%Y-%m-%d")

    def target(self, source_id: str, relative_name: str) -> Path:
        relative_path = Path(relative_name)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("Snapshot relative_name must remain inside its source directory")
        return self.repository_root / "data" / "raw" / source_id / self.batch / relative_path

    def read_valid(self, source_id: str, relative_name: str) -> StoredSnapshot | None:
        path = self.target(source_id, relative_name)
        manifest_path = _manifest_path(path)
        if not path.exists() and not manifest_path.exists():
            return None
        if not path.is_file() or not manifest_path.is_file():
            raise ValueError(f"Incomplete cached snapshot at {path}")
        manifest = _read_manifest(manifest_path)
        if not verify_provenance(manifest, repository_root=self.repository_root):
            raise ValueError(f"Cached snapshot failed provenance verification: {path}")
        return StoredSnapshot(path, manifest_path, manifest, reused=True)

    def store(
        self,
        body: bytes,
        *,
        source_id: str,
        dataset_id: str,
        relative_name: str,
        source_url: str,
        media_type: str,
        license_name: str | None,
        notes: str | None = None,
    ) -> StoredSnapshot:
        cached = self.read_valid(source_id, relative_name)
        if cached is not None:
            return cached

        path = self.target(source_id, relative_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, body)
        manifest = build_provenance(
            path,
            repository_root=self.repository_root,
            source_id=source_id,
            dataset_id=dataset_id,
            source_url=source_url,
            media_type=media_type,
            license_name=license_name,
            notes=notes,
        )
        manifest_path = _manifest_path(path)
        serialized = json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"
        _atomic_write(manifest_path, serialized)
        return StoredSnapshot(path, manifest_path, manifest, reused=False)


def _manifest_path(snapshot_path: Path) -> Path:
    return snapshot_path.with_name(f"{snapshot_path.name}.manifest.json")


def _read_manifest(path: Path) -> ProvenanceManifest:
    value: Any = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"Invalid provenance manifest: {path}")
    return value  # type: ignore[return-value]


def _atomic_write(path: Path, body: bytes) -> None:
    file_descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
