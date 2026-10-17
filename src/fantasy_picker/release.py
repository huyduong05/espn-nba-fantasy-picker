"""Build deterministic source-only local release archives."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import subprocess
import tarfile
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_EXCLUDED_PREFIXES = (
    "artifacts/",
    "data/raw/",
    "data/interim/",
    "data/processed/",
    "extension/dist/",
    "extension/generated/",
)


class ReleaseError(RuntimeError):
    """A source release cannot be safely assembled."""


@dataclass(frozen=True)
class ReleaseResult:
    """Paths and checksum for a completed source release."""

    archive: Path
    manifest: Path
    sha256: str


def create_release(root: Path, output_dir: Path) -> ReleaseResult:
    """Create a source archive from a clean Git revision and its manifest."""
    _require_clean_worktree(root)
    revision = _git(root, "rev-parse", "HEAD").strip()
    commit_timestamp = int(_git(root, "show", "-s", "--format=%ct", revision).strip())
    version = _project_version(root)
    archive_stem = f"espn-nba-fantasy-picker-{version}-{revision[:12]}"
    archive = output_dir / f"{archive_stem}.tar.gz"
    manifest = output_dir / f"{archive_stem}.manifest.json"
    prefix = f"{archive_stem}/"
    source_tar = subprocess.run(
        ["git", "archive", "--format=tar", f"--prefix={prefix}", revision],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    archive_bytes = _filtered_archive(source_tar, prefix)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(archive_bytes)
    digest = _sha256(archive)
    payload = {
        "archive": archive.name,
        "archive_sha256": digest,
        "git_revision": revision,
        "package_version": version,
        "source_date": datetime.fromtimestamp(commit_timestamp, UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "runtime_requirements": {"node": ">=22", "python": ">=3.12,<3.13"},
        "lockfile_sha256": {
            "extension/package-lock.json": _sha256(root / "extension/package-lock.json"),
            "requirements.lock": _sha256(root / "requirements.lock"),
        },
    }
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return ReleaseResult(archive=archive, manifest=manifest, sha256=digest)


def filter_archive_members(source_tar: bytes, prefix: str) -> list[str]:
    """Return source member names that are permitted in a release archive."""
    with tarfile.open(fileobj=io.BytesIO(source_tar), mode="r:") as source:
        return [
            member.name for member in source.getmembers() if _include_member(member.name, prefix)
        ]


def _filtered_archive(source_tar: bytes, prefix: str) -> bytes:
    output = io.BytesIO()
    with (
        tarfile.open(fileobj=io.BytesIO(source_tar), mode="r:") as source,
        gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as destination,
    ):
        for member in source.getmembers():
            if not _include_member(member.name, prefix):
                continue
            contents = source.extractfile(member) if member.isfile() else None
            destination.addfile(member, contents)
    return output.getvalue()


def _include_member(name: str, prefix: str) -> bool:
    if not name.startswith(prefix):
        raise ReleaseError(f"Archive member is outside the expected release prefix: {name}")
    relative = name.removeprefix(prefix)
    return bool(relative) and not any(
        relative.startswith(excluded) for excluded in _EXCLUDED_PREFIXES
    )


def _project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as stream:
        payload = tomllib.load(stream)
    version = payload.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ReleaseError("pyproject.toml has no project version")
    return version


def _require_clean_worktree(root: Path) -> None:
    status = _git(root, "status", "--porcelain", "--untracked-files=all")
    if status.strip():
        raise ReleaseError(
            "Refusing to package a dirty working tree; commit or stash changes first"
        )


def _git(root: Path, *arguments: str) -> str:
    try:
        return subprocess.run(
            ["git", *arguments], cwd=root, check=True, capture_output=True, text=True
        ).stdout
    except subprocess.CalledProcessError as error:
        raise ReleaseError(error.stderr.strip() or "Git command failed") from error


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
