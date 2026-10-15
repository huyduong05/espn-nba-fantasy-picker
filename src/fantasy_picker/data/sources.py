"""Phase 1 source-specific acquisition workflows."""

from __future__ import annotations

import json
import os
import zipfile
from collections.abc import Iterable, Mapping
from csv import DictReader
from dataclasses import dataclass
from io import BytesIO, TextIOWrapper
from pathlib import Path
from typing import Any, cast

from fantasy_picker.data.http import AcquisitionError, HttpResponse, HttpTransport
from fantasy_picker.data.snapshots import SnapshotStore, StoredSnapshot

BALLDONTLIE_BASE_URL = "https://api.balldontlie.io"
NBA_STATS_URL = "https://stats.nba.com/stats/leaguedashplayerstats"
NBA_PLAYER_INDEX_URL = "https://stats.nba.com/stats/playerindex"
KAGGLE_INJURY_METADATA_URL = (
    "https://www.kaggle.com/api/v1/datasets/view/ghopkins/nba-injuries-2010-2018"
)
KAGGLE_INJURY_DOWNLOAD_URL = (
    "https://www.kaggle.com/api/v1/datasets/download/ghopkins/nba-injuries-2010-2018"
)
SPORTSDATAVERSE_RELEASE_URL = (
    "https://api.github.com/repos/sportsdataverse/sportsdataverse-data/releases/tags/"
    "ncaa_mbb_player_box"
)


@dataclass(frozen=True)
class AcquisitionSummary:
    source_id: str
    dataset_id: str
    files: tuple[Path, ...]
    records: int | None
    reused_files: int


def acquire_historical_injuries(
    client: HttpTransport,
    store: SnapshotStore,
) -> AcquisitionSummary:
    """Acquire the CC0 Kaggle injury event archive for 2010-11 through 2019-20."""
    metadata_snapshot, metadata = _load_or_fetch_json(
        client,
        store,
        source_id="kaggle_nba_injuries",
        dataset_id="nba_injuries_2010_2020_metadata",
        url=KAGGLE_INJURY_METADATA_URL,
        params=None,
        headers={"Accept": "application/json"},
        relative_name="injuries/2010-2020/metadata.json",
        license_name="CC0: Public Domain",
    )
    if metadata.get("licenseName") != "CC0: Public Domain":
        raise AcquisitionError("Kaggle injury dataset is no longer marked CC0")
    if metadata.get("currentVersionNumber") != 3:
        raise AcquisitionError("Kaggle injury dataset version changed; review before refreshing")

    relative_name = "injuries/2010-2020/dataset.zip"
    cached = store.read_valid("kaggle_nba_injuries", relative_name)
    if cached is None:
        response = client.get(
            KAGGLE_INJURY_DOWNLOAD_URL,
            params={"datasetVersionNumber": 3},
            headers={"Accept": "application/zip"},
        )
        records = _validate_injury_archive(response.body)
        snapshot = store.store(
            response.body,
            source_id="kaggle_nba_injuries",
            dataset_id="nba_injuries_2010_2020",
            relative_name=relative_name,
            source_url=response.url,
            media_type=response.headers.get("content-type", "application/zip"),
            license_name="CC0: Public Domain",
            notes=(
                "Randall Hopkins dataset, version 3; publisher states it was scraped "
                "from Pro Sports Transactions. Coverage ends after 2019-20."
            ),
        )
    else:
        snapshot = cached
        records = _validate_injury_archive(snapshot.path.read_bytes())
    return AcquisitionSummary(
        source_id="kaggle_nba_injuries",
        dataset_id="nba_injuries_2010_2020",
        files=(snapshot.path, metadata_snapshot.path),
        records=records,
        reused_files=int(snapshot.reused) + int(metadata_snapshot.reused),
    )


def acquire_nba_com_history(
    client: HttpTransport,
    store: SnapshotStore,
    *,
    season_start_years: Iterable[int],
) -> list[AcquisitionSummary]:
    """Acquire NBA.com snapshots for education, subject to NBA.com usage terms."""
    summaries = []
    for start_year in season_start_years:
        if start_year < 1946 or start_year > 2100:
            raise ValueError(f"Invalid NBA season start year: {start_year}")
        season = f"{start_year}-{str(start_year + 1)[-2:]}"
        dataset_id = f"nba_com_season_averages_{start_year}"
        relative_name = f"nba_com/season_averages/{season}/response.json"
        cached = store.read_valid("nba_stats", relative_name)
        if cached is None:
            response = client.get(
                NBA_STATS_URL,
                params=_nba_stats_parameters(season),
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Origin": "https://www.nba.com",
                    "Referer": "https://www.nba.com/",
                },
            )
            payload = _decode_json_object(response.body, response.url)
            records = _validate_nba_stats_payload(payload, season)
            snapshot = store.store(
                response.body,
                source_id="nba_stats",
                dataset_id=dataset_id,
                relative_name=relative_name,
                source_url=response.url,
                media_type=response.headers.get("content-type", "application/json"),
                license_name="NBA.com Terms of Use",
                notes=(
                    "User-directed educational snapshot. NBA.com terms restrict use in "
                    "connection with a fantasy game; not approved as model input."
                ),
            )
        else:
            snapshot = cached
            payload = _decode_json_object(snapshot.path.read_bytes(), snapshot.path.as_posix())
            records = _validate_nba_stats_payload(payload, season)
        summaries.append(
            AcquisitionSummary(
                source_id="nba_stats",
                dataset_id=dataset_id,
                files=(snapshot.path,),
                records=records,
                reused_files=int(snapshot.reused),
            )
        )
    return summaries


def acquire_nba_active_roster(
    client: HttpTransport,
    store: SnapshotStore,
    *,
    season_start_year: int,
) -> AcquisitionSummary:
    """Acquire the active NBA player index used to identify rookie candidates."""
    season = f"{season_start_year}-{str(season_start_year + 1)[-2:]}"
    snapshot, payload = _load_or_fetch_json(
        client,
        store,
        source_id="nba_stats",
        dataset_id=f"nba_active_roster_{season_start_year}",
        url=NBA_PLAYER_INDEX_URL,
        params={
            "Active": 1,
            "AllStar": "",
            "College": "",
            "Country": "",
            "DraftPick": "",
            "DraftYear": "",
            "Height": "",
            "Historical": 0,
            "LeagueID": "00",
            "PlayerPosition": "",
            "Season": season,
            "TeamID": 0,
            "Weight": "",
        },
        headers={
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.nba.com",
            "Referer": "https://www.nba.com/",
        },
        relative_name=f"nba_com/player_index/{season}/response.json",
        license_name="NBA.com Terms of Use",
    )
    return AcquisitionSummary(
        source_id="nba_stats",
        dataset_id=f"nba_active_roster_{season_start_year}",
        files=(snapshot.path,),
        records=_validate_player_index(payload, season),
        reused_files=int(snapshot.reused),
    )


def acquire_nba_history(
    client: HttpTransport,
    store: SnapshotStore,
    *,
    seasons: Iterable[int],
    api_key: str | None = None,
) -> list[AcquisitionSummary]:
    key = api_key or os.environ.get("BALLDONTLIE_API_KEY")
    if not key:
        raise AcquisitionError(
            "BALLDONTLIE_API_KEY is required. NBA season averages require the provider's "
            "GOAT NBA tier; do not commit the key."
        )

    summaries = []
    headers = {"Authorization": key}
    for season in seasons:
        if season < 1996 or season > 2100:
            raise ValueError(f"Invalid NBA season start year: {season}")
        summaries.append(
            _acquire_paginated_json(
                client,
                store,
                source_id="balldontlie_nba",
                dataset_id=f"nba_season_averages_{season}",
                url=f"{BALLDONTLIE_BASE_URL}/nba/v1/season_averages/general",
                params={
                    "season": season,
                    "season_type": "regular",
                    "type": "base",
                    "per_page": 100,
                },
                headers=headers,
                relative_directory=f"nba/season_averages/{season}",
                license_name="BALLDONTLIE Terms of Service (2026-09-17)",
            )
        )
    return summaries


def acquire_nba_reference_data(
    client: HttpTransport,
    store: SnapshotStore,
    *,
    api_key: str | None = None,
) -> list[AcquisitionSummary]:
    key = api_key or os.environ.get("BALLDONTLIE_API_KEY")
    if not key:
        raise AcquisitionError(
            "BALLDONTLIE_API_KEY is required. Active players and injuries require the "
            "provider's ALL-STAR NBA tier or higher."
        )
    headers = {"Authorization": key}
    return [
        _acquire_paginated_json(
            client,
            store,
            source_id="balldontlie_nba",
            dataset_id="nba_active_players",
            url=f"{BALLDONTLIE_BASE_URL}/nba/v1/players/active",
            params={"per_page": 100},
            headers=headers,
            relative_directory="nba/active_players",
            license_name="BALLDONTLIE Terms of Service (2026-09-17)",
        ),
        _acquire_paginated_json(
            client,
            store,
            source_id="balldontlie_nba",
            dataset_id="nba_current_injuries",
            url=f"{BALLDONTLIE_BASE_URL}/nba/v1/player_injuries",
            params={"per_page": 100},
            headers=headers,
            relative_directory="nba/current_injuries",
            license_name="BALLDONTLIE Terms of Service (2026-09-17)",
        ),
    ]


def acquire_ncaa_player_boxes(
    client: HttpTransport,
    store: SnapshotStore,
    *,
    seasons: Iterable[int],
) -> list[AcquisitionSummary]:
    release_snapshot, release = _load_or_fetch_json(
        client,
        store,
        source_id="sportsdataverse_ncaa",
        dataset_id="ncaa_player_box_release_metadata",
        url=SPORTSDATAVERSE_RELEASE_URL,
        params=None,
        headers={"Accept": "application/vnd.github+json"},
        relative_name="ncaa/player_box/release.json",
        license_name="CC BY 4.0",
    )
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise AcquisitionError("SportsDataverse release metadata did not contain an asset list")

    summaries = []
    for season in seasons:
        asset = _select_college_asset(assets, season)
        asset_url = asset.get("browser_download_url")
        asset_name = asset.get("name")
        if not isinstance(asset_url, str) or not isinstance(asset_name, str):
            raise AcquisitionError(f"Malformed SportsDataverse asset metadata for season {season}")
        relative_name = f"ncaa/player_box/{season}/{asset_name}"
        cached = store.read_valid("sportsdataverse_ncaa", relative_name)
        if cached is None:
            response = client.get(asset_url, headers={"Accept": "application/octet-stream"})
            records = _validate_ncaa_player_boxes(response.body, asset_name)
            snapshot = store.store(
                response.body,
                source_id="sportsdataverse_ncaa",
                dataset_id=f"ncaa_player_box_{season}",
                relative_name=relative_name,
                source_url=response.url,
                media_type=response.headers.get("content-type", "application/octet-stream"),
                license_name="CC BY 4.0",
                notes="Produced from stats.ncaa.org by sportsdataverse/ncaa-mbb-hoops-data.",
            )
        else:
            snapshot = cached
            records = _validate_ncaa_player_boxes(snapshot.path.read_bytes(), asset_name)
        summaries.append(
            AcquisitionSummary(
                source_id="sportsdataverse_ncaa",
                dataset_id=f"ncaa_player_box_{season}",
                files=(snapshot.path, release_snapshot.path),
                records=records,
                reused_files=int(snapshot.reused) + int(release_snapshot.reused),
            )
        )
    return summaries


def _acquire_paginated_json(
    client: HttpTransport,
    store: SnapshotStore,
    *,
    source_id: str,
    dataset_id: str,
    url: str,
    params: Mapping[str, str | int],
    headers: Mapping[str, str],
    relative_directory: str,
    license_name: str,
) -> AcquisitionSummary:
    page = 1
    cursor: str | int | None = None
    seen_cursors: set[str] = set()
    snapshots: list[StoredSnapshot] = []
    record_count = 0

    while True:
        page_params = dict(params)
        if cursor is not None:
            page_params["cursor"] = cursor
        relative_name = f"{relative_directory}/page_{page:04d}.json"
        snapshot, payload = _load_or_fetch_json(
            client,
            store,
            source_id=source_id,
            dataset_id=dataset_id,
            url=url,
            params=page_params,
            headers=headers,
            relative_name=relative_name,
            license_name=license_name,
        )
        snapshots.append(snapshot)
        data = payload.get("data")
        meta = payload.get("meta", {})
        if not isinstance(data, list) or not isinstance(meta, dict):
            raise AcquisitionError(f"Unexpected paginated response shape for {dataset_id}")
        record_count += len(data)
        next_cursor = meta.get("next_cursor")
        if next_cursor is None:
            break
        cursor_key = str(next_cursor)
        if cursor_key in seen_cursors:
            raise AcquisitionError(f"Pagination cursor repeated for {dataset_id}: {cursor_key}")
        seen_cursors.add(cursor_key)
        cursor = cast(str | int, next_cursor)
        page += 1
        if page > 1000:
            raise AcquisitionError(f"Pagination exceeded 1000 pages for {dataset_id}")

    return AcquisitionSummary(
        source_id=source_id,
        dataset_id=dataset_id,
        files=tuple(snapshot.path for snapshot in snapshots),
        records=record_count,
        reused_files=sum(snapshot.reused for snapshot in snapshots),
    )


def _load_or_fetch_json(
    client: HttpTransport,
    store: SnapshotStore,
    *,
    source_id: str,
    dataset_id: str,
    url: str,
    params: Mapping[str, str | int] | None,
    headers: Mapping[str, str],
    relative_name: str,
    license_name: str,
) -> tuple[StoredSnapshot, dict[str, Any]]:
    cached = store.read_valid(source_id, relative_name)
    if cached is not None:
        return cached, _decode_json_object(cached.path.read_bytes(), cached.path.as_posix())

    response: HttpResponse = client.get(url, params=params, headers=headers)
    payload = _decode_json_object(response.body, response.url)
    snapshot = store.store(
        response.body,
        source_id=source_id,
        dataset_id=dataset_id,
        relative_name=relative_name,
        source_url=response.url,
        media_type=response.headers.get("content-type", "application/json"),
        license_name=license_name,
    )
    return snapshot, payload


def _decode_json_object(body: bytes, source: str) -> dict[str, Any]:
    try:
        payload: Any = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcquisitionError(f"Expected a JSON object from {source}") from error
    if not isinstance(payload, dict):
        raise AcquisitionError(f"Expected a JSON object from {source}")
    return payload


def _select_college_asset(assets: list[Any], season: int) -> dict[str, Any]:
    suffixes = (f"_{season}.csv.gz", f"_{season}.parquet")
    matches = [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and isinstance(asset.get("name"), str)
        and cast(str, asset["name"]).endswith(suffixes)
    ]
    if not matches:
        raise AcquisitionError(
            f"No NCAA player-box release asset was published for end-year season {season}"
        )
    matches.sort(key=lambda asset: 0 if cast(str, asset["name"]).endswith(".csv.gz") else 1)
    return cast(dict[str, Any], matches[0])


def _nba_stats_parameters(season: str) -> dict[str, str | int]:
    return {
        "College": "",
        "Conference": "",
        "Country": "",
        "DateFrom": "",
        "DateTo": "",
        "Division": "",
        "DraftPick": "",
        "DraftYear": "",
        "GameScope": "",
        "GameSegment": "",
        "Height": "",
        "LastNGames": 0,
        "LeagueID": "00",
        "Location": "",
        "MeasureType": "Base",
        "Month": 0,
        "OpponentTeamID": 0,
        "Outcome": "",
        "PORound": 0,
        "PaceAdjust": "N",
        "PerMode": "PerGame",
        "Period": 0,
        "PlayerExperience": "",
        "PlayerPosition": "",
        "PlusMinus": "N",
        "Rank": "N",
        "Season": season,
        "SeasonSegment": "",
        "SeasonType": "Regular Season",
        "ShotClockRange": "",
        "StarterBench": "",
        "TeamID": 0,
        "TwoWay": 0,
        "VsConference": "",
        "VsDivision": "",
        "Weight": "",
    }


def _validate_nba_stats_payload(payload: dict[str, Any], season: str) -> int:
    result_sets = payload.get("resultSets")
    if not isinstance(result_sets, list) or not result_sets:
        raise AcquisitionError(f"NBA.com returned no resultSets for {season}")
    result = result_sets[0]
    if not isinstance(result, dict):
        raise AcquisitionError(f"NBA.com returned a malformed result set for {season}")
    headers = result.get("headers")
    rows = result.get("rowSet")
    required = {
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
    }
    if not isinstance(headers, list) or not required <= set(headers):
        raise AcquisitionError(f"NBA.com response for {season} is missing required fields")
    if not isinstance(rows, list):
        raise AcquisitionError(f"NBA.com response for {season} has no rowSet")
    return len(rows)


def _validate_injury_archive(body: bytes) -> int:
    try:
        with zipfile.ZipFile(BytesIO(body)) as archive:
            names = archive.namelist()
            if names != ["injuries_2010-2020.csv"]:
                raise AcquisitionError("Kaggle injury archive contains unexpected files")
            with archive.open(names[0]) as binary_stream:
                stream = TextIOWrapper(binary_stream, encoding="utf-8-sig", newline="")
                header = stream.readline().rstrip("\r\n").split(",")
                required = ["Date", "Team", "Acquired", "Relinquished", "Notes"]
                if header != required:
                    raise AcquisitionError("Kaggle injury CSV fields changed")
                return sum(1 for line in stream if line.strip())
    except zipfile.BadZipFile as error:
        raise AcquisitionError("Kaggle injury download was not a valid ZIP archive") from error


def _validate_player_index(payload: dict[str, Any], season: str) -> int:
    result_sets = payload.get("resultSets")
    if not isinstance(result_sets, list) or not result_sets:
        raise AcquisitionError(f"NBA.com returned no player index for {season}")
    result = result_sets[0]
    if not isinstance(result, dict):
        raise AcquisitionError(f"NBA.com returned a malformed player index for {season}")
    headers = result.get("headers")
    rows = result.get("rowSet")
    required = {
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
    }
    if not isinstance(headers, list) or not required <= set(headers):
        raise AcquisitionError(f"NBA.com player index for {season} is missing required fields")
    if not isinstance(rows, list):
        raise AcquisitionError(f"NBA.com player index for {season} has no rowSet")
    return len(rows)


def _validate_ncaa_player_boxes(body: bytes, asset_name: str) -> int:
    """Validate the CSV release before preserving it as an immutable raw input."""
    if not asset_name.endswith(".csv.gz"):
        raise AcquisitionError(
            f"Unsupported NCAA player-box asset {asset_name}; expected a .csv.gz release asset"
        )
    required = {
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
    }
    try:
        import gzip

        with gzip.open(BytesIO(body), "rt", encoding="utf-8-sig", newline="") as stream:
            reader = DictReader(stream)
            fields = set(reader.fieldnames or [])
            if not required <= fields:
                missing = ", ".join(sorted(required - fields))
                raise AcquisitionError(f"NCAA player-box CSV is missing required fields: {missing}")
            return sum(1 for _ in reader)
    except OSError as error:
        raise AcquisitionError("NCAA player-box release was not a valid gzip CSV") from error
