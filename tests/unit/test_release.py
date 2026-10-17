from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from fantasy_picker import release
from fantasy_picker.contracts import repository_root
from fantasy_picker.release import ReleaseError, create_release, filter_archive_members


def test_release_filters_local_artifacts_from_archive_members() -> None:
    source = _tar(
        {
            "release/README.md": b"readme",
            "release/artifacts/.gitkeep": b"",
            "release/data/raw/.gitkeep": b"",
            "release/extension/generated/player-index.json": b"generated",
        }
    )

    assert filter_archive_members(source, "release/") == ["release/README.md"]


def test_create_release_writes_manifest_for_exact_source_and_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nversion = '0.1.0'\n")
    (root / "requirements.lock").write_text("Flask==3.1.3\n")
    extension = root / "extension"
    extension.mkdir()
    (extension / "package-lock.json").write_text('{"lockfileVersion": 3}\n')
    source = _tar(
        {
            "espn-nba-fantasy-picker-0.1.0-abc123def456/README.md": b"readme",
            "espn-nba-fantasy-picker-0.1.0-abc123def456/artifacts/.gitkeep": b"",
        }
    )
    monkeypatch.setattr(release, "_require_clean_worktree", lambda _: None)
    monkeypatch.setattr(
        release,
        "_git",
        lambda _root, *arguments: (
            "abc123def4567890\n" if arguments[0] == "rev-parse" else "1760659200\n"
        ),
    )
    monkeypatch.setattr(
        release.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=source),
    )

    result = create_release(root, root / "dist")
    repeated = create_release(root, root / "dist")

    members = _members(result.archive)
    assert members == ["espn-nba-fantasy-picker-0.1.0-abc123def456/README.md"]
    assert repeated.sha256 == result.sha256
    manifest = json.loads(result.manifest.read_text())
    assert manifest["git_revision"] == "abc123def4567890"
    assert manifest["archive_sha256"] == hashlib.sha256(result.archive.read_bytes()).hexdigest()
    assert set(manifest["lockfile_sha256"]) == {
        "extension/package-lock.json",
        "requirements.lock",
    }


def test_release_rejects_a_dirty_worktree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(release, "_git", lambda *_: " M README.md\n")

    with pytest.raises(ReleaseError, match="dirty"):
        release._require_clean_worktree(tmp_path)


def test_release_instructions_pin_installation_and_cover_recovery() -> None:
    root = repository_root()
    makefile = (root / "Makefile").read_text()
    checklist = (root / "docs" / "release-checklist.md").read_text()

    assert "pip install --requirement requirements.lock" in makefile
    assert "npm --prefix extension ci" in makefile
    for required_text in (
        "CORS",
        "Port 8765",
        "Freshness warning",
        "Retry suggestions",
        "never reads ESPN page content",
        "never submits a draft pick",
        "156 simulated snake picks",
    ):
        assert required_text in checklist


def _tar(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, contents in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(contents)
            member.mtime = 1
            archive.addfile(member, io.BytesIO(contents))
    return output.getvalue()


def _members(path: Path) -> list[str]:
    with tarfile.open(path, mode="r:gz") as archive:
        return archive.getnames()
