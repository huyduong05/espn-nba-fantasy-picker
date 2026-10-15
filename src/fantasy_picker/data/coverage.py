"""Raw acquisition coverage inspection."""

from __future__ import annotations

import csv
import gzip
import json
import zipfile
from pathlib import Path
from typing import Any

NBA_REQUIRED_STATS = {
    "gp",
    "min",
    "pts",
    "reb",
    "ast",
    "stl",
    "blk",
    "fg3m",
    "tov",
    "fgm",
    "fga",
    "ftm",
    "fta",
}

NBA_COM_REQUIRED_STATS = {
    "PLAYER_ID",
    "PLAYER_NAME",
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
}


def build_coverage_report(repository_root: Path) -> dict[str, Any]:
    raw_root = repository_root / "data" / "raw"
    nba_datasets = _inspect_nba(raw_root / "balldontlie_nba")
    nba_com_datasets = _inspect_nba_com(raw_root / "nba_stats")
    roster_datasets = _inspect_active_roster(raw_root / "nba_stats")
    injury_datasets = _inspect_injuries(raw_root / "kaggle_nba_injuries")
    college_datasets = _inspect_college(raw_root / "sportsdataverse_ncaa")
    nba_seasons = sorted(
        int(item["season"])
        for item in nba_datasets
        if item.get("season") is not None and item.get("required_fields_present") is True
    )
    college_seasons = sorted(int(item["season"]) for item in college_datasets)
    nba_com_seasons = sorted(
        int(item["season_start_year"])
        for item in nba_com_datasets
        if item["required_fields_present"] is True
    )
    return {
        "schema_version": "1.0.0",
        "nba": {
            "source": "balldontlie_nba",
            "downloaded_season_start_years": nba_seasons,
            "five_season_requirement_met": nba_seasons == [2021, 2022, 2023, 2024, 2025],
            "datasets": nba_datasets,
        },
        "nba_com_educational": {
            "source": "nba_stats",
            "selected_for_local_educational_model": True,
            "permissively_licensed": False,
            "usage_note": (
                "User-selected educational snapshots; NBA.com terms restrict fantasy-game use."
            ),
            "downloaded_season_start_years": nba_com_seasons,
            "five_season_requirement_met": nba_com_seasons == [2021, 2022, 2023, 2024, 2025],
            "datasets": nba_com_datasets,
        },
        "college": {
            "source": "sportsdataverse_ncaa",
            "downloaded_season_end_years": college_seasons,
            "two_season_requirement_met": college_seasons == [2025, 2026],
            "datasets": college_datasets,
        },
        "international": {
            "source": None,
            "status": "SOURCE_REQUIRED",
            "scope": "Rookies/newly drafted players on active NBA rosters only.",
            "active_roster_measurement": roster_datasets,
            "acquired_stat_records": 0,
            "unsupported_league_policy": "Omit international data and flag player as low-info.",
            "reason": (
                "The NBA player index exposes country and draft metadata, not prior club or league "
                "history. No international-stat source snapshot has been selected or acquired."
            ),
        },
        "historical_injuries": {
            "source": "kaggle_nba_injuries",
            "status": "SELECTED" if injury_datasets else "NOT_DOWNLOADED",
            "coverage_limitation": (
                "Event archive ends after 2019-20; recent availability comes from games played."
            ),
            "datasets": injury_datasets,
        },
    }


def write_coverage_report(repository_root: Path) -> Path:
    report_path = repository_root / "data" / "coverage-report.json"
    report_path.write_text(json.dumps(build_coverage_report(repository_root), indent=2) + "\n")
    return report_path


def _inspect_nba(source_root: Path) -> list[dict[str, Any]]:
    latest_batch = _latest_batch(source_root)
    if latest_batch is None:
        return []
    season_root = latest_batch / "nba" / "season_averages"
    results = []
    for directory in sorted(season_root.glob("[0-9][0-9][0-9][0-9]")):
        pages = sorted(directory.glob("page_*.json"))
        records = 0
        observed_fields: set[str] = set()
        for page in pages:
            payload = json.loads(page.read_text())
            data = payload.get("data", [])
            if not isinstance(data, list):
                continue
            records += len(data)
            for item in data:
                if isinstance(item, dict) and isinstance(item.get("stats"), dict):
                    observed_fields.update(item["stats"])
        results.append(
            {
                "season": int(directory.name),
                "pages": len(pages),
                "records": records,
                "observed_stat_fields": sorted(observed_fields),
                "required_fields_present": observed_fields >= NBA_REQUIRED_STATS,
                "missing_required_fields": sorted(NBA_REQUIRED_STATS - observed_fields),
            }
        )
    return results


def _inspect_college(source_root: Path) -> list[dict[str, Any]]:
    latest_batch = _latest_batch(source_root)
    if latest_batch is None:
        return []
    season_root = latest_batch / "ncaa" / "player_box"
    results = []
    for directory in sorted(season_root.glob("[0-9][0-9][0-9][0-9]")):
        files = [path for path in directory.iterdir() if not path.name.endswith(".manifest.json")]
        if not files:
            continue
        data_path = files[0]
        fields: list[str] = []
        records: int | None = None
        if data_path.name.endswith(".csv.gz"):
            with gzip.open(data_path, "rt", encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream)
                fields = next(reader, [])
                records = sum(1 for _ in reader)
        results.append(
            {
                "season": int(directory.name),
                "file": data_path.name,
                "byte_count": data_path.stat().st_size,
                "records": records,
                "fields": fields,
                "required_fields_present": set(fields) >= {
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
                },
            }
        )
    return results


def _inspect_nba_com(source_root: Path) -> list[dict[str, Any]]:
    latest_batch = _latest_batch(source_root)
    if latest_batch is None:
        return []
    season_root = latest_batch / "nba_com" / "season_averages"
    results = []
    for directory in sorted(season_root.iterdir()) if season_root.is_dir() else []:
        data_path = directory / "response.json"
        if not data_path.is_file():
            continue
        payload = json.loads(data_path.read_text())
        result_sets = payload.get("resultSets", [])
        result = result_sets[0] if isinstance(result_sets, list) and result_sets else {}
        headers = result.get("headers", []) if isinstance(result, dict) else []
        rows = result.get("rowSet", []) if isinstance(result, dict) else []
        results.append(
            {
                "season": directory.name,
                "season_start_year": int(directory.name.split("-", maxsplit=1)[0]),
                "file": data_path.name,
                "byte_count": data_path.stat().st_size,
                "records": len(rows) if isinstance(rows, list) else None,
                "fields": headers if isinstance(headers, list) else [],
                "required_fields_present": (
                    isinstance(headers, list) and set(headers) >= NBA_COM_REQUIRED_STATS
                ),
                "missing_required_fields": (
                    sorted(NBA_COM_REQUIRED_STATS - set(headers))
                    if isinstance(headers, list)
                    else sorted(NBA_COM_REQUIRED_STATS)
                ),
            }
        )
    return results


def _inspect_active_roster(source_root: Path) -> list[dict[str, Any]]:
    latest_batch = _latest_batch(source_root)
    if latest_batch is None:
        return []
    roster_root = latest_batch / "nba_com" / "player_index"
    results = []
    for directory in sorted(roster_root.iterdir()) if roster_root.is_dir() else []:
        data_path = directory / "response.json"
        if not data_path.is_file():
            continue
        payload = json.loads(data_path.read_text())
        result_sets = payload.get("resultSets", [])
        result = result_sets[0] if isinstance(result_sets, list) and result_sets else {}
        headers = result.get("headers", []) if isinstance(result, dict) else []
        rows = result.get("rowSet", []) if isinstance(result, dict) else []
        if not isinstance(headers, list) or not isinstance(rows, list):
            continue
        indices = {field: index for index, field in enumerate(headers) if isinstance(field, str)}
        required = {"PERSON_ID", "PLAYER_FIRST_NAME", "PLAYER_LAST_NAME", "DRAFT_YEAR", "FROM_YEAR"}
        if not required <= indices.keys():
            continue
        season_start_year = int(directory.name.split("-", maxsplit=1)[0])
        rookie_rows = [
            row
            for row in rows
            if isinstance(row, list)
            and len(row) > indices["FROM_YEAR"]
            and str(row[indices["FROM_YEAR"]]) == str(season_start_year)
        ]
        results.append(
            {
                "season": directory.name,
                "active_players": len(rows),
                "new_nba_players": len(rookie_rows),
                "identity_fields": sorted(required),
                "prior_league_history_available": False,
            }
        )
    return results


def _inspect_injuries(source_root: Path) -> list[dict[str, Any]]:
    latest_batch = _latest_batch(source_root)
    if latest_batch is None:
        return []
    data_path = latest_batch / "injuries" / "2010-2020" / "dataset.zip"
    if not data_path.is_file():
        return []
    with (
        zipfile.ZipFile(data_path) as archive,
        archive.open("injuries_2010-2020.csv") as stream,
    ):
        reader = csv.reader(line.decode("utf-8-sig") for line in stream)
        fields = next(reader, [])
        records = sum(1 for _ in reader)
    return [
        {
            "seasons": "2010-11 through 2019-20",
            "file": data_path.name,
            "byte_count": data_path.stat().st_size,
            "records": records,
            "fields": fields,
            "license": "CC0: Public Domain",
        }
    ]


def _latest_batch(source_root: Path) -> Path | None:
    if not source_root.is_dir():
        return None
    batches = sorted(path for path in source_root.iterdir() if path.is_dir())
    return batches[-1] if batches else None
