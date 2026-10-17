from __future__ import annotations

import gzip
import io
import json
import zipfile
from datetime import date
from pathlib import Path

import pytest

from fantasy_picker.contracts import repository_root, validate
from fantasy_picker.data.normalize import NormalizationError, normalize_cached_data
from fantasy_picker.data.snapshots import SnapshotStore
from fantasy_picker.models.injuries import load_injury_config, score_injury_events


def test_normalization_creates_per_game_records_and_surfaces_unmatched_college_ids(
    tmp_path: Path,
) -> None:
    store = SnapshotStore(tmp_path, batch="2026-10-15")
    _store_json(
        store,
        "nba_stats",
        "nba_com/player_index/2026-27/response.json",
        _result(
            [
                "PERSON_ID",
                "PLAYER_FIRST_NAME",
                "PLAYER_LAST_NAME",
                "POSITION",
                "COLLEGE",
                "DRAFT_YEAR",
                "FROM_YEAR",
            ],
            [["10", "Alex", "Player", "G-F", "Example U", 2026, "2026"]],
        ),
    )
    _store_json(
        store,
        "nba_stats",
        "nba_com/season_averages/2025-26/response.json",
        _result(
            [
                "PLAYER_ID",
                "PLAYER_NAME",
                "TEAM_ABBREVIATION",
                "GP",
                "MIN",
                "PTS",
                "REB",
                "AST",
                "STL",
                "BLK",
                "FG3M",
                "TOV",
                "FGM",
                "FGA",
                "FTM",
                "FTA",
            ],
            [["10", "Alex Player", "EXM", 20, 30, 15, 4, 5, 1, 0.5, 2, 2, 5, 10, 3, 4]],
        ),
    )
    header = [
        "season",
        "player_id",
        "clean_name",
        "team",
        "mins",
        "pts",
        "orb",
        "drb",
        "ast",
        "stl",
        "blk",
        "tov",
        "fgm",
        "fga",
        "tpm",
        "ftm",
        "fta",
    ]
    rows = [
        [
            "2026",
            "college-10",
            "Alex Player",
            "Example U",
            "30",
            "20",
            "1",
            "4",
            "5",
            "1",
            "1",
            "2",
            "7",
            "14",
            "2",
            "4",
            "5",
        ],
        [
            "2026",
            "college-ambiguous",
            "Alex Player",
            "Other U",
            "20",
            "8",
            "1",
            "2",
            "2",
            "1",
            "0",
            "1",
            "3",
            "6",
            "1",
            "1",
            "2",
        ],
    ]
    college_body = gzip.compress(
        "\n".join([",".join(header), *[",".join(row) for row in rows], ""]).encode()
    )
    store.store(
        college_body,
        source_id="sportsdataverse_ncaa",
        dataset_id="ncaa_player_box_2026",
        relative_name="ncaa/player_box/2026/player_box.csv.gz",
        source_url="https://example.test/player_box.csv.gz",
        media_type="application/gzip",
        license_name="CC BY 4.0",
    )
    _store_injuries(
        store,
        [
            ["2025-10-01", "EXM", "", "Alex Player", "sprained left ankle"],
            ["2025-10-02", "EXM", "Alex Player", "", "activated from IL"],
            ["2025-10-03", "EXM", "", "Unmapped Player", "sore knee"],
            ["not-a-date", "EXM", "", "Alex Player", "bad source date"],
        ],
    )
    review_path = tmp_path / "identity-review.yaml"
    review_path.write_text(
        "manual_mappings: []\n"
        "injury_manual_mappings:\n"
        "  - injury_player_name: Alex Player\n"
        "    nba_player_id: '10'\n"
        "reviewed_pairs:\n"
        "  - nba_player_id: '10'\n"
        "    college_player_id: college-10\n"
    )

    result = normalize_cached_data(tmp_path, review_path)

    assert result["quality"]["reviewed_identity_sample"]["accuracy"] == 1.0
    stats = _read_jsonl(tmp_path / "data/processed/season_stats.jsonl")
    nba_stat = next(stat for stat in stats if stat["league_type"] == "NBA")
    college_stat = next(
        stat for stat in stats if stat["source_record_id"] == "ncaa_2026_college-10"
    )
    assert nba_stat["team"] == "NBA:EXM"
    assert college_stat["season_start_year"] == 2025
    assert college_stat["reb"] == 5
    assert college_stat["canonical_player_id"] == nba_stat["canonical_player_id"]
    unresolved = json.loads((tmp_path / "data/processed/unresolved_matches.json").read_text())
    assert unresolved["summary"]["unresolved_or_ambiguous_college_source_ids"] == 1
    injury_events = _read_jsonl(tmp_path / "data/processed/injury_events.jsonl")
    assert len(injury_events) == 1
    event = injury_events[0]
    validate(event, "injury")
    assert event["canonical_player_id"] == nba_stat["canonical_player_id"]
    assert event["status"] == "HISTORICAL"
    assert event["start_date"] == "2025-10-01"
    assert event["games_missed"] is None
    assert event["description"] == "sprained left ankle"
    injury_review = json.loads(
        (tmp_path / "data/processed/unresolved_injury_matches.json").read_text()
    )
    assert injury_review["summary"] == {
        "injury_events": 1,
        "invalid_injury_rows": 1,
        "skipped_acquisition_side_rows": 1,
        "unresolved_injury_rows": 1,
    }
    unmatched = next(
        record for record in injury_review["records"] if record["status"] == "UNRESOLVED"
    )
    assert unmatched["source_player_name"] == "Unmapped Player"
    assert unmatched["candidate_nba_player_ids"] == []
    assessments = score_injury_events(
        injury_events,
        date(2026, 10, 15),
        load_injury_config(repository_root() / "config/injury-risk.yaml"),
        player_ids=[nba_stat["canonical_player_id"]],
    )
    assert assessments[0]["data_status"] == "HISTORICAL_ONLY"

    normalize_cached_data(tmp_path, review_path)
    assert _read_jsonl(tmp_path / "data/processed/injury_events.jsonl") == injury_events


def test_normalization_requires_historical_injury_snapshot(tmp_path: Path) -> None:
    (tmp_path / "data/raw/nba_stats/2026-10-15").mkdir(parents=True)
    (tmp_path / "data/raw/sportsdataverse_ncaa/2026-10-15").mkdir(parents=True)
    review_path = tmp_path / "identity-review.yaml"
    review_path.write_text("manual_mappings: []\ninjury_manual_mappings: []\nreviewed_pairs: []\n")

    with pytest.raises(NormalizationError, match="data fetch-injuries"):
        normalize_cached_data(tmp_path, review_path)


def test_normalization_rejects_an_injury_mapping_to_an_absent_nba_player(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path, batch="2026-10-15")
    _store_json(
        store,
        "nba_stats",
        "nba_com/player_index/2026-27/response.json",
        _result(
            [
                "PERSON_ID",
                "PLAYER_FIRST_NAME",
                "PLAYER_LAST_NAME",
                "POSITION",
                "COLLEGE",
                "DRAFT_YEAR",
                "FROM_YEAR",
            ],
            [["10", "Alex", "Player", "G", "Example U", 2026, "2026"]],
        ),
    )
    _store_json(
        store,
        "nba_stats",
        "nba_com/season_averages/2025-26/response.json",
        _result(
            [
                "PLAYER_ID",
                "PLAYER_NAME",
                "TEAM_ABBREVIATION",
                "GP",
                "MIN",
                "PTS",
                "REB",
                "AST",
                "STL",
                "BLK",
                "FG3M",
                "TOV",
                "FGM",
                "FGA",
                "FTM",
                "FTA",
            ],
            [["10", "Alex Player", "EXM", 20, 30, 15, 4, 5, 1, 0.5, 2, 2, 5, 10, 3, 4]],
        ),
    )
    _store_college_snapshot(store)
    _store_injuries(store, [["2025-10-01", "EXM", "", "Alex Player", "sprained ankle"]])
    review_path = tmp_path / "identity-review.yaml"
    review_path.write_text(
        "manual_mappings: []\n"
        "injury_manual_mappings:\n"
        "  - injury_player_name: Alex Player\n"
        "    nba_player_id: '999'\n"
        "reviewed_pairs: []\n"
    )

    with pytest.raises(NormalizationError, match="absent NBA player"):
        normalize_cached_data(tmp_path, review_path)


def _store_json(store: SnapshotStore, source_id: str, relative_name: str, value: object) -> None:
    store.store(
        json.dumps(value).encode(),
        source_id=source_id,
        dataset_id="example",
        relative_name=relative_name,
        source_url="https://example.test/data.json",
        media_type="application/json",
        license_name="Example",
    )


def _store_injuries(store: SnapshotStore, rows: list[list[str]]) -> None:
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w") as archive:
        archive.writestr(
            "injuries_2010-2020.csv",
            "\n".join(
                [
                    "Date,Team,Acquired,Relinquished,Notes",
                    *[",".join(row) for row in rows],
                    "",
                ]
            ),
        )
    store.store(
        body.getvalue(),
        source_id="kaggle_nba_injuries",
        dataset_id="nba_injuries_2010_2020",
        relative_name="injuries/2010-2020/dataset.zip",
        source_url="https://example.test/injuries.zip",
        media_type="application/zip",
        license_name="CC0: Public Domain",
    )


def _store_college_snapshot(store: SnapshotStore) -> None:
    header = [
        "season",
        "player_id",
        "clean_name",
        "team",
        "mins",
        "pts",
        "orb",
        "drb",
        "ast",
        "stl",
        "blk",
        "tov",
        "fgm",
        "fga",
        "tpm",
        "ftm",
        "fta",
    ]
    row = [
        "2026",
        "college-10",
        "Alex Player",
        "Example U",
        "30",
        "20",
        "1",
        "4",
        "5",
        "1",
        "1",
        "2",
        "7",
        "14",
        "2",
        "4",
        "5",
    ]
    store.store(
        gzip.compress("\n".join([",".join(header), ",".join(row), ""]).encode()),
        source_id="sportsdataverse_ncaa",
        dataset_id="ncaa_player_box_2026",
        relative_name="ncaa/player_box/2026/player_box.csv.gz",
        source_url="https://example.test/player_box.csv.gz",
        media_type="application/gzip",
        license_name="CC BY 4.0",
    )


def _result(headers: list[str], rows: list[list[object]]) -> dict[str, object]:
    return {"resultSets": [{"headers": headers, "rowSet": rows}]}


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]
