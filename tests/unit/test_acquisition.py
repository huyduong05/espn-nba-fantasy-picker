from __future__ import annotations

import gzip
import io
import json
import zipfile
from collections.abc import Mapping
from pathlib import Path

import pytest

from fantasy_picker.data.coverage import build_coverage_report
from fantasy_picker.data.http import AcquisitionError, HttpResponse
from fantasy_picker.data.snapshots import SnapshotStore
from fantasy_picker.data.sources import (
    acquire_historical_injuries,
    acquire_nba_active_roster,
    acquire_nba_com_history,
    acquire_nba_history,
    acquire_ncaa_player_boxes,
)


class FakeClient:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, Mapping[str, str | int] | None]] = []

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        self.calls.append((url, params))
        if not self.responses:
            raise AssertionError("Unexpected HTTP request")
        return self.responses.pop(0)


def json_response(url: str, payload: object) -> HttpResponse:
    return HttpResponse(
        url=url,
        status=200,
        headers={"content-type": "application/json"},
        body=json.dumps(payload).encode(),
    )


def test_paginated_nba_download_is_cached_and_counted(tmp_path: Path) -> None:
    required_stats = {
        "gp": 80,
        "min": 30,
        "pts": 20,
        "reb": 5,
        "ast": 5,
        "stl": 1,
        "blk": 1,
        "fg3m": 2,
        "tov": 2,
        "fgm": 7,
        "fga": 14,
        "ftm": 4,
        "fta": 5,
    }
    client = FakeClient(
        [
            json_response(
                "https://api.example/page1",
                {"data": [{"stats": required_stats}], "meta": {"next_cursor": 42}},
            ),
            json_response(
                "https://api.example/page2", {"data": [{"stats": required_stats}], "meta": {}}
            ),
        ]
    )
    store = SnapshotStore(tmp_path, batch="2026-10-15")

    summary = acquire_nba_history(client, store, seasons=[2025], api_key="secret")

    assert summary[0].records == 2
    assert len(summary[0].files) == 2
    assert client.calls[1][1] is not None
    assert client.calls[1][1]["cursor"] == 42

    cached_client = FakeClient([])
    cached = acquire_nba_history(cached_client, store, seasons=[2025], api_key="secret")
    assert cached[0].reused_files == 2
    assert cached_client.calls == []

    report = build_coverage_report(tmp_path)
    assert report["nba"]["datasets"][0]["required_fields_present"] is True


def test_nba_download_requires_key_before_network_access(tmp_path: Path) -> None:
    client = FakeClient([])
    with pytest.raises(AcquisitionError, match="BALLDONTLIE_API_KEY"):
        acquire_nba_history(client, SnapshotStore(tmp_path), seasons=[2025], api_key=None)
    assert client.calls == []


def test_nba_com_educational_download_is_validated_and_cached(tmp_path: Path) -> None:
    headers = [
        "PLAYER_ID",
        "PLAYER_NAME",
        "GP",
        "MIN",
        "FGM",
        "FGA",
        "FG3M",
        "FTM",
        "FTA",
        "REB",
        "AST",
        "TOV",
        "STL",
        "BLK",
        "PTS",
    ]
    client = FakeClient(
        [
            json_response(
                "https://stats.nba.com/stats/leaguedashplayerstats",
                {"resultSets": [{"headers": headers, "rowSet": [[1, "Example Player"]]}]},
            )
        ]
    )
    store = SnapshotStore(tmp_path, batch="2026-10-15")

    summaries = acquire_nba_com_history(client, store, season_start_years=[2025])

    assert summaries[0].records == 1
    assert client.calls[0][1] is not None
    assert client.calls[0][1]["Season"] == "2025-26"
    manifest = json.loads(summaries[0].files[0].with_suffix(".json.manifest.json").read_text())
    assert "not approved as model input" in manifest["notes"]

    cached = acquire_nba_com_history(FakeClient([]), store, season_start_years=[2025])
    assert cached[0].reused_files == 1


def test_nba_com_download_rejects_missing_required_fields(tmp_path: Path) -> None:
    client = FakeClient(
        [
            json_response(
                "https://stats.nba.com/stats/leaguedashplayerstats",
                {"resultSets": [{"headers": ["PLAYER_ID"], "rowSet": []}]},
            )
        ]
    )

    with pytest.raises(AcquisitionError, match="missing required fields"):
        acquire_nba_com_history(client, SnapshotStore(tmp_path), season_start_years=[2025])


def test_active_roster_download_validates_player_identity_fields(tmp_path: Path) -> None:
    headers = [
        "PERSON_ID",
        "PLAYER_FIRST_NAME",
        "PLAYER_LAST_NAME",
        "TEAM_ID",
        "TEAM_ABBREVIATION",
        "COLLEGE",
        "COUNTRY",
        "DRAFT_YEAR",
        "ROSTER_STATUS",
        "FROM_YEAR",
    ]
    client = FakeClient(
        [
            json_response(
                "https://stats.nba.com/stats/playerindex",
                {"resultSets": [{"headers": headers, "rowSet": [[1, "New", "Player"]]}]},
            )
        ]
    )

    summary = acquire_nba_active_roster(client, SnapshotStore(tmp_path), season_start_year=2026)

    assert summary.records == 1
    assert client.calls[0][1] is not None
    assert client.calls[0][1]["Season"] == "2026-27"


def test_historical_injury_download_verifies_license_and_archive(tmp_path: Path) -> None:
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w") as archive:
        archive.writestr(
            "injuries_2010-2020.csv",
            "Date,Team,Acquired,Relinquished,Notes\n2019-01-01,Test,,Player,ankle\n",
        )
    client = FakeClient(
        [
            json_response(
                "https://www.kaggle.com/api/v1/datasets/view/example",
                {"licenseName": "CC0: Public Domain", "currentVersionNumber": 3},
            ),
            HttpResponse(
                url="https://www.kaggle.com/api/v1/datasets/download/example",
                status=200,
                headers={"content-type": "application/zip"},
                body=body.getvalue(),
            ),
        ]
    )

    summary = acquire_historical_injuries(client, SnapshotStore(tmp_path, batch="2026-10-15"))

    assert summary.records == 1
    assert len(summary.files) == 2
    report = build_coverage_report(tmp_path)
    assert report["historical_injuries"]["status"] == "SELECTED"
    assert report["historical_injuries"]["datasets"][0]["records"] == 1


def test_college_release_asset_is_discovered_and_cached(tmp_path: Path) -> None:
    asset_url = "https://example.test/ncaa_mbb_player_box_2026.csv.gz"
    release = {
        "assets": [
            {
                "name": "ncaa_mbb_player_box_2026.csv.gz",
                "browser_download_url": asset_url,
            }
        ]
    }
    required_fields = [
        "player_id",
        "player",
        "clean_name",
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
        "season",
    ]
    sample_row = [
        "1",
        "Example Player",
        "Example Player",
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
        "2026",
    ]
    csv_body = gzip.compress(
        "\n".join([",".join(required_fields), ",".join(sample_row), ""]).encode()
    )
    client = FakeClient(
        [
            json_response("https://api.example/release", release),
            HttpResponse(
                url=asset_url,
                status=200,
                headers={"content-type": "application/octet-stream"},
                body=csv_body,
            ),
        ]
    )

    summaries = acquire_ncaa_player_boxes(
        client, SnapshotStore(tmp_path, batch="2026-10-15"), seasons=[2026]
    )

    assert summaries[0].dataset_id == "ncaa_player_box_2026"
    assert summaries[0].records == 1
    report = build_coverage_report(tmp_path)
    assert report["college"]["datasets"][0]["records"] == 1
    assert report["college"]["datasets"][0]["required_fields_present"] is True


def test_college_download_rejects_an_incomplete_release_asset(tmp_path: Path) -> None:
    release = {
        "assets": [
            {
                "name": "ncaa_mbb_player_box_2026.csv.gz",
                "browser_download_url": "https://example.test/ncaa_mbb_player_box_2026.csv.gz",
            }
        ]
    }
    client = FakeClient(
        [
            json_response("https://api.example/release", release),
            HttpResponse(
                url="https://example.test/ncaa_mbb_player_box_2026.csv.gz",
                status=200,
                headers={"content-type": "application/octet-stream"},
                body=gzip.compress(b"player_id,player\\n1,Example Player\\n"),
            ),
        ]
    )

    with pytest.raises(AcquisitionError, match="missing required fields"):
        acquire_ncaa_player_boxes(client, SnapshotStore(tmp_path), seasons=[2026])
