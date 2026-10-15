from datetime import UTC, datetime

import pytest

from fantasy_picker.cache import build_provenance, verify_provenance


def test_build_and_verify_provenance(tmp_path) -> None:  # type: ignore[no-untyped-def]
    snapshot = tmp_path / "data" / "raw" / "example" / "2026-10-15" / "data.csv"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("player,pts\nExample,20\n")

    manifest = build_provenance(
        snapshot,
        repository_root=tmp_path,
        source_id="example",
        dataset_id="example_dataset",
        source_url="https://example.com/data.csv",
        media_type="text/csv",
        retrieved_at=datetime(2026, 10, 15, 12, 0, tzinfo=UTC),
    )

    assert verify_provenance(manifest, repository_root=tmp_path)
    snapshot.write_text("changed")
    assert not verify_provenance(manifest, repository_root=tmp_path)


def test_provenance_rejects_files_outside_raw_directory(tmp_path) -> None:  # type: ignore[no-untyped-def]
    snapshot = tmp_path / "other" / "data.csv"
    snapshot.parent.mkdir()
    snapshot.write_text("fixture")

    with pytest.raises(ValueError, match="data/raw"):
        build_provenance(
            snapshot,
            repository_root=tmp_path,
            source_id="example",
            dataset_id="example_dataset",
            source_url="https://example.com/data.csv",
            media_type="text/csv",
        )
