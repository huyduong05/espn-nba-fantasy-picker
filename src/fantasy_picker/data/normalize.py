"""Phase 2 normalization and conservative player-identity resolution."""

from __future__ import annotations

import csv
import gzip
import json
import re
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime
from io import TextIOWrapper
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from fantasy_picker.cache import ProvenanceManifest, verify_provenance
from fantasy_picker.contracts import load_schema
from fantasy_picker.identity import (
    new_canonical_player_id,
    normalized_name_candidate,
    source_identity_key,
)

TRANSFORMATION_VERSION = "phase_2_normalization_v1"
NBA_STAT_FIELDS = {
    "GP": "games",
    "MIN": "minutes",
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "FG3M": "three_pm",
    "TOV": "turnovers",
    "FGM": "fgm",
    "FGA": "fga",
    "FTM": "ftm",
    "FTA": "fta",
}
COLLEGE_STAT_FIELDS = {
    "mins": "minutes",
    "pts": "pts",
    "orb": "orb",
    "drb": "drb",
    "ast": "ast",
    "stl": "stl",
    "blk": "blk",
    "tpm": "three_pm",
    "tov": "turnovers",
    "fgm": "fgm",
    "fga": "fga",
    "ftm": "ftm",
    "fta": "fta",
}
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
_SCHOOL_ALIASES = {
    "byu": "brigham young",
    "uconn": "connecticut",
    "miami fl": "miami",
    "michigan st": "michigan state",
    "nc state": "north carolina state",
    "ohio st": "ohio state",
    "iowa st": "iowa state",
    "kansas st": "kansas state",
    "oregon st": "oregon state",
    "south fla": "south florida",
}


class NormalizationError(RuntimeError):
    """A local input or identity-resolution error suitable for CLI output."""


class PlayerRegistry:
    """Persisted random player IDs, indexed by provider-owned source IDs."""

    def __init__(self, existing_players: Iterable[dict[str, Any]]) -> None:
        self.players: dict[str, dict[str, Any]] = {}
        self.by_source: dict[str, str] = {}
        for player in existing_players:
            canonical_id = cast(str, player["canonical_player_id"])
            self.players[canonical_id] = player
            source_ids = cast(dict[str, str], player["source_ids"])
            for source, external_id in source_ids.items():
                self.by_source[source_identity_key(source, external_id)] = canonical_id

    def resolve(self, source: str, external_id: str, display_name: str) -> str:
        key = source_identity_key(source, external_id)
        canonical_id = self.by_source.get(key)
        if canonical_id is None:
            canonical_id = new_canonical_player_id()
            self.players[canonical_id] = {
                "schema_version": "1.0.0",
                "canonical_player_id": canonical_id,
                "display_name": display_name,
                "birth_date": None,
                "aliases": [],
                "source_ids": {source: external_id},
            }
            self.by_source[key] = canonical_id
            return canonical_id

        player = self.players[canonical_id]
        aliases = cast(list[str], player["aliases"])
        if display_name != player["display_name"] and display_name not in aliases:
            aliases.append(display_name)
            aliases.sort()
        return canonical_id

    def attach(self, canonical_id: str, source: str, external_id: str, display_name: str) -> None:
        key = source_identity_key(source, external_id)
        current = self.by_source.get(key)
        if current is not None and current != canonical_id:
            self._merge(current, canonical_id)
        player = self.players[canonical_id]
        source_ids = cast(dict[str, str], player["source_ids"])
        existing_external_id = source_ids.get(source)
        if existing_external_id is not None and existing_external_id != external_id:
            raise NormalizationError(
                f"{canonical_id} already has a different {source} identifier: "
                f"{existing_external_id}"
            )
        source_ids[source] = external_id
        self.by_source[key] = canonical_id
        aliases = cast(list[str], player["aliases"])
        if display_name != player["display_name"] and display_name not in aliases:
            aliases.append(display_name)
            aliases.sort()

    def _merge(self, source_canonical_id: str, target_canonical_id: str) -> None:
        """Merge an independently-created source record into a reviewed NBA identity."""
        source_player = self.players[source_canonical_id]
        target_player = self.players[target_canonical_id]
        source_ids = cast(dict[str, str], source_player["source_ids"])
        target_source_ids = cast(dict[str, str], target_player["source_ids"])
        if "nba_stats" in source_ids:
            raise NormalizationError(
                f"Cannot merge two NBA-backed canonical records: {source_canonical_id} and "
                f"{target_canonical_id}"
            )
        for source, external_id in source_ids.items():
            target_external_id = target_source_ids.get(source)
            if target_external_id is not None and target_external_id != external_id:
                raise NormalizationError(
                    f"Merge would create two {source} IDs on {target_canonical_id}"
                )
            target_source_ids[source] = external_id
            self.by_source[source_identity_key(source, external_id)] = target_canonical_id
        source_aliases = cast(list[str], source_player["aliases"])
        target_aliases = cast(list[str], target_player["aliases"])
        for alias in [cast(str, source_player["display_name"]), *source_aliases]:
            if alias != target_player["display_name"] and alias not in target_aliases:
                target_aliases.append(alias)
        target_aliases.sort()
        del self.players[source_canonical_id]


def normalize_cached_data(repository_root: Path, review_path: Path) -> dict[str, Any]:
    """Normalize current local snapshots into model-ready JSONL datasets."""
    root = repository_root.resolve()
    nba_batch = _latest_batch(root / "data" / "raw" / "nba_stats")
    college_batch = _latest_batch(root / "data" / "raw" / "sportsdataverse_ncaa")
    injury_batch = _latest_batch(root / "data" / "raw" / "kaggle_nba_injuries")
    if nba_batch is None or college_batch is None:
        raise NormalizationError("NBA and NCAA snapshots are required; run `data fetch-all` first")
    if injury_batch is None:
        raise NormalizationError(
            "Historical injury snapshots are required; run `data fetch-injuries` first"
        )

    output_root = root / "data" / "processed"
    registry = PlayerRegistry(_load_existing_players(output_root / "players.jsonl"))
    roster, eligibility, position_gaps, raw_manifest_paths = _normalize_nba_roster(
        nba_batch, registry
    )
    nba_stats, nba_manifest_paths = _normalize_nba_stats(nba_batch, registry)
    college_profiles, college_stats, input_issues, college_manifest_paths = _load_college_stats(
        college_batch
    )
    raw_manifest_paths.extend(nba_manifest_paths)
    raw_manifest_paths.extend(college_manifest_paths)

    overrides = _load_review_file(review_path)
    resolution = _resolve_college_identities(registry, roster, college_profiles, overrides)
    for college_id, canonical_id in resolution["matched"].items():
        profile = college_profiles[college_id]
        registry.attach(canonical_id, "sportsdataverse_ncaa", college_id, profile["display_name"])

    for record in college_stats:
        college_id = cast(str, record.pop("college_player_id"))
        profile = college_profiles[college_id]
        canonical_id = resolution["matched"].get(college_id)
        if canonical_id is None:
            canonical_id = registry.resolve(
                cast(str, profile["identity_source"]), college_id, profile["display_name"]
            )
        record["canonical_player_id"] = canonical_id

    injury_events, unresolved_injuries, injury_manifest_paths = _normalize_historical_injuries(
        injury_batch, registry, overrides
    )
    raw_manifest_paths.extend(injury_manifest_paths)

    players = sorted(
        registry.players.values(), key=lambda record: cast(str, record["canonical_player_id"])
    )
    stats = sorted(
        nba_stats + college_stats,
        key=lambda record: (
            cast(str, record["canonical_player_id"]),
            cast(int, record["season_start_year"]),
            cast(str, record["source"]),
        ),
    )
    unresolved = _build_unresolved_report(
        resolution, roster, college_profiles, nba_batch, position_gaps, input_issues
    )
    quality = _validate_processed_data(
        players, stats, eligibility, injury_events, unresolved, unresolved_injuries, overrides
    )
    manifest = {
        "schema_version": "1.0.0",
        "transformation_version": TRANSFORMATION_VERSION,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "input_provenance_manifests": sorted(set(raw_manifest_paths)),
        "outputs": {
            "players": len(players),
            "season_stats": len(stats),
            "eligibility": len(eligibility),
            "unresolved": len(cast(list[dict[str, Any]], unresolved["records"])),
            "injury_events": len(injury_events),
            "unresolved_injuries": len(cast(list[dict[str, Any]], unresolved_injuries["records"])),
        },
    }
    _write_jsonl(output_root / "players.jsonl", players)
    _write_jsonl(output_root / "season_stats.jsonl", stats)
    _write_jsonl(output_root / "eligibility.jsonl", eligibility)
    _write_jsonl(output_root / "injury_events.jsonl", injury_events)
    _write_json(output_root / "unresolved_matches.json", unresolved)
    _write_json(output_root / "unresolved_injury_matches.json", unresolved_injuries)
    _write_json(output_root / "data_quality_report.json", quality)
    _write_json(output_root / "normalization_manifest.json", manifest)
    return {"manifest": manifest, "quality": quality, "output_root": output_root.as_posix()}


def _normalize_historical_injuries(
    batch: Path, registry: PlayerRegistry, review: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Convert reviewed Kaggle absence transactions into historical injury events."""
    path = batch / "injuries" / "2010-2020" / "dataset.zip"
    if not path.is_file():
        raise NormalizationError(
            "No historical injury archive found; run `data fetch-injuries` before `data normalize`"
        )
    _verify_snapshot(path)
    mappings = _injury_mapping_index(review)
    nba_players = _nba_player_index(registry)
    events: list[dict[str, Any]] = []
    review_records: list[dict[str, Any]] = []
    invalid_rows = 0
    skipped_acquisitions = 0

    try:
        with zipfile.ZipFile(path) as archive:
            if "injuries_2010-2020.csv" not in archive.namelist():
                raise NormalizationError(
                    "Historical injury archive is missing injuries_2010-2020.csv"
                )
            with archive.open("injuries_2010-2020.csv") as raw_stream:
                reader = csv.DictReader(TextIOWrapper(raw_stream, encoding="utf-8-sig", newline=""))
                fields = set(reader.fieldnames or [])
                required_fields = {"Date", "Team", "Acquired", "Relinquished", "Notes"}
                if not required_fields <= fields:
                    raise NormalizationError(
                        "Historical injury archive is missing required CSV fields: "
                        f"{sorted(required_fields - fields)}"
                    )
                for row_number, row in enumerate(reader, start=2):
                    acquired_name = _optional_text(row.get("Acquired"))
                    relinquished_name = _optional_text(row.get("Relinquished"))
                    if acquired_name is not None:
                        skipped_acquisitions += 1
                        review_records.append(
                            {
                                "source": "kaggle_nba_injuries",
                                "row_number": row_number,
                                "source_player_name": acquired_name,
                                "status": "ACQUISITION_SIDE_SKIPPED",
                                "reason": (
                                    "Acquired entries are activation/return transactions and "
                                    "do not create a historical absence event."
                                ),
                            }
                        )
                    if relinquished_name is None:
                        continue
                    try:
                        start_date = date.fromisoformat(
                            _required_text(row, "Date", path)
                        ).isoformat()
                    except ValueError:
                        invalid_rows += 1
                        review_records.append(
                            {
                                "source": "kaggle_nba_injuries",
                                "row_number": row_number,
                                "source_player_name": relinquished_name,
                                "status": "INVALID_SOURCE_ROW",
                                "reason": f"Invalid Date value: {row.get('Date')!r}",
                            }
                        )
                        continue
                    nba_player_id = mappings.get(relinquished_name)
                    if nba_player_id is None:
                        review_records.append(
                            {
                                "source": "kaggle_nba_injuries",
                                "row_number": row_number,
                                "source_player_name": relinquished_name,
                                "status": "UNRESOLVED",
                                "candidate_nba_player_ids": _injury_candidate_nba_ids(
                                    registry, relinquished_name
                                ),
                                "reason": (
                                    "No exact reviewed injury mapping; normalized names are review "
                                    "aids and are never merged automatically."
                                ),
                            }
                        )
                        continue
                    canonical_player_id = nba_players.get(nba_player_id)
                    if canonical_player_id is None:
                        raise NormalizationError(
                            "Injury mapping references absent NBA player "
                            f"{nba_player_id!r} for {relinquished_name!r}"
                        )
                    event_identity = f"kaggle_nba_injuries/v3/{row_number}/relinquished"
                    events.append(
                        {
                            "schema_version": "1.0.0",
                            "event_id": f"evt_{uuid5(NAMESPACE_URL, event_identity).hex}",
                            "canonical_player_id": canonical_player_id,
                            "event_type": "INJURY",
                            "status": "HISTORICAL",
                            "start_date": start_date,
                            "end_date": None,
                            "games_missed": None,
                            "ir_eligible": None,
                            "description": _optional_text(row.get("Notes")),
                            "source": "kaggle_nba_injuries",
                        }
                    )
    except zipfile.BadZipFile as error:
        raise NormalizationError(
            f"Historical injury archive is not a valid ZIP file: {path}"
        ) from error

    events.sort(
        key=lambda event: (event["canonical_player_id"], event["start_date"], event["event_id"])
    )
    review_records.sort(key=lambda record: (cast(int, record["row_number"]), record["status"]))
    return (
        events,
        {
            "schema_version": "1.0.0",
            "policy": (
                "Historical injury names require exact reviewed mappings; "
                "candidate names are never merged automatically."
            ),
            "records": review_records,
            "summary": {
                "injury_events": len(events),
                "unresolved_injury_rows": sum(
                    1 for record in review_records if record["status"] == "UNRESOLVED"
                ),
                "skipped_acquisition_side_rows": skipped_acquisitions,
                "invalid_injury_rows": invalid_rows,
            },
        },
        [_manifest_for(path)],
    )


def _injury_mapping_index(review: dict[str, Any]) -> dict[str, str]:
    mappings: dict[str, str] = {}
    for index, item in enumerate(
        cast(list[dict[str, Any]], review["injury_manual_mappings"]), start=1
    ):
        source_name = item["injury_player_name"]
        if source_name in mappings:
            raise NormalizationError(
                f"Duplicate injury mapping for {source_name!r} at entry {index}"
            )
        mappings[source_name] = item["nba_player_id"]
    return mappings


def _nba_player_index(registry: PlayerRegistry) -> dict[str, str]:
    return {
        nba_player_id: canonical_player_id
        for canonical_player_id, player in registry.players.items()
        if (nba_player_id := cast(dict[str, str], player["source_ids"]).get("nba_stats"))
        is not None
    }


def _injury_candidate_nba_ids(registry: PlayerRegistry, source_name: str) -> list[str]:
    candidate = normalized_name_candidate(source_name)
    results = []
    for player in registry.players.values():
        source_ids = cast(dict[str, str], player["source_ids"])
        nba_player_id = source_ids.get("nba_stats")
        names = [cast(str, player["display_name"]), *cast(list[str], player["aliases"])]
        if nba_player_id is not None and any(
            normalized_name_candidate(name) == candidate for name in names
        ):
            results.append(nba_player_id)
    return sorted(results)


def _normalize_nba_roster(
    batch: Path, registry: PlayerRegistry
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    paths = sorted(batch.glob("nba_com/player_index/*/response.json"))
    if not paths:
        raise NormalizationError("No NBA player-index snapshot found")
    path = paths[-1]
    _verify_snapshot(path)
    result = _nba_result(path)
    rows = _named_rows(result)
    as_of_date = _retrieved_date(path)
    roster: dict[str, dict[str, Any]] = {}
    eligibility: list[dict[str, Any]] = []
    position_gaps: list[dict[str, Any]] = []
    for row in rows:
        external_id = _required_text(row, "PERSON_ID", path)
        display_name = _player_name(row, "PLAYER_FIRST_NAME", "PLAYER_LAST_NAME", path)
        canonical_id = registry.resolve("nba_stats", external_id, display_name)
        roster[external_id] = {
            "external_id": external_id,
            "canonical_id": canonical_id,
            "display_name": display_name,
            "college": _optional_text(row.get("COLLEGE")),
            "draft_year": _optional_int(row.get("DRAFT_YEAR")),
            "from_year": _optional_int(row.get("FROM_YEAR")),
        }
        raw_position = _optional_text(row.get("POSITION"))
        if raw_position is None:
            position_gaps.append(
                {
                    "source": "nba_stats",
                    "external_player_id": external_id,
                    "display_name": display_name,
                    "status": "UNRESOLVED_POSITION",
                    "reason": "NBA player-index snapshot did not provide a position.",
                }
            )
        else:
            eligibility.append(
                {
                    "schema_version": "1.0.0",
                    "canonical_player_id": canonical_id,
                    "as_of_date": as_of_date,
                    "source": "nba_stats",
                    "positions": _normalize_positions(raw_position),
                }
            )
    return roster, eligibility, position_gaps, [_manifest_for(path)]


def _normalize_nba_stats(
    batch: Path, registry: PlayerRegistry
) -> tuple[list[dict[str, Any]], list[str]]:
    paths = sorted(batch.glob("nba_com/season_averages/*/response.json"))
    if not paths:
        raise NormalizationError("No NBA season-average snapshots found")
    records: list[dict[str, Any]] = []
    manifest_paths: list[str] = []
    for path in paths:
        _verify_snapshot(path)
        season_start_year = int(path.parent.name.split("-", maxsplit=1)[0])
        result = _nba_result(path)
        for row in _named_rows(result):
            external_id = _required_text(row, "PLAYER_ID", path)
            display_name = _required_text(row, "PLAYER_NAME", path)
            record: dict[str, Any] = {
                "schema_version": "1.0.0",
                "canonical_player_id": registry.resolve("nba_stats", external_id, display_name),
                "source": "nba_stats",
                "source_record_id": f"nba_com_{season_start_year}_{external_id}",
                "league_type": "NBA",
                "league": "NBA",
                "team": f"NBA:{_required_text(row, 'TEAM_ABBREVIATION', path).upper()}",
                "season_start_year": season_start_year,
            }
            for raw_name, normalized_name in NBA_STAT_FIELDS.items():
                record[normalized_name] = _nonnegative_number(row.get(raw_name), raw_name, path)
            record["games"] = int(record["games"])
            records.append(record)
        manifest_paths.append(_manifest_for(path))
    return records, manifest_paths


def _load_college_stats(
    batch: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    paths = sorted(batch.glob("ncaa/player_box/*/*.csv.gz"))
    if not paths:
        raise NormalizationError("No NCAA player-box snapshots found")
    aggregates: dict[tuple[int, str], dict[str, Any]] = {}
    manifest_paths: list[str] = []
    input_issues: list[dict[str, Any]] = []
    for path in paths:
        _verify_snapshot(path)
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            for row_number, row in enumerate(reader, start=2):
                try:
                    season_end = int(_required_text(row, "season", path))
                    display_name = _optional_text(row.get("clean_name"))
                    if display_name is None:
                        display_name = _required_text(row, "player", path)
                    team = _required_text(row, "team", path)
                    values = {
                        normalized_name: _nonnegative_number(row.get(raw_name), raw_name, path)
                        for raw_name, normalized_name in COLLEGE_STAT_FIELDS.items()
                    }
                except NormalizationError as error:
                    input_issues.append(
                        {
                            "source_file": path.name,
                            "row_number": row_number,
                            "reason": str(error),
                        }
                    )
                    continue
                college_id = _optional_text(row.get("player_id"))
                identity_source = "sportsdataverse_ncaa"
                if college_id is None:
                    identity_source = "sportsdataverse_ncaa_unidentified"
                    college_id = _unidentified_college_key(season_end, display_name, team)
                    input_issues.append(
                        {
                            "kind": "MISSING_PROVIDER_ID",
                            "source_file": path.name,
                            "row_number": row_number,
                            "reason": (
                                "The source row has no player_id or clean_name; retained "
                                "with a derived "
                                "unresolved key."
                            ),
                        }
                    )
                key = (season_end, college_id)
                aggregate = aggregates.get(key)
                if aggregate is None:
                    aggregate = {
                        "college_player_id": college_id,
                        "season_end_year": season_end,
                        "display_name": display_name,
                        "identity_source": identity_source,
                        "teams": set(),
                        "games": 0,
                        **{field: 0.0 for field in COLLEGE_STAT_FIELDS.values()},
                    }
                    aggregates[key] = aggregate
                aggregate["teams"].add(team)
                aggregate["games"] += 1
                for normalized_name, value in values.items():
                    aggregate[normalized_name] += value
        manifest_paths.append(_manifest_for(path))

    profiles: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    for aggregate in aggregates.values():
        games = cast(int, aggregate["games"])
        college_id = cast(str, aggregate["college_player_id"])
        teams = sorted(cast(set[str], aggregate["teams"]))
        profile = profiles.setdefault(
            college_id,
            {
                "display_name": aggregate["display_name"],
                "identity_source": aggregate["identity_source"],
                "season_end_years": set(),
                "teams": set(),
            },
        )
        cast(set[int], profile["season_end_years"]).add(cast(int, aggregate["season_end_year"]))
        cast(set[str], profile["teams"]).update(teams)
        record = {
            "schema_version": "1.0.0",
            "source": "sportsdataverse_ncaa",
            "source_record_id": f"ncaa_{aggregate['season_end_year']}_{college_id}",
            "league_type": "COLLEGE",
            "league": "NCAA Division I",
            "team": _college_team_code(teams),
            "season_start_year": cast(int, aggregate["season_end_year"]) - 1,
            "games": games,
            "college_player_id": college_id,
        }
        for field in COLLEGE_STAT_FIELDS.values():
            record[field] = cast(float, aggregate[field]) / games
        record["reb"] = (cast(float, aggregate["orb"]) + cast(float, aggregate["drb"])) / games
        del record["orb"]
        del record["drb"]
        records.append(record)
    return profiles, records, input_issues, manifest_paths


def _resolve_college_identities(
    registry: PlayerRegistry,
    roster: dict[str, dict[str, Any]],
    college_profiles: dict[str, dict[str, Any]],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for player in roster.values():
        by_name[normalized_name_candidate(cast(str, player["display_name"]))].append(player)
    override_map = {
        cast(str, item["college_player_id"]): cast(str, item["nba_player_id"])
        for item in cast(list[dict[str, Any]], overrides["manual_mappings"])
    }
    matched: dict[str, str] = {}
    unresolved: list[dict[str, Any]] = []
    for college_id, profile in sorted(college_profiles.items()):
        identity_source = cast(str, profile["identity_source"])
        source_key = source_identity_key(identity_source, college_id)
        existing_id = registry.by_source.get(source_key)
        if existing_id is not None:
            existing_sources = cast(dict[str, str], registry.players[existing_id]["source_ids"])
            if "nba_stats" in existing_sources:
                matched[college_id] = existing_id
                continue
        candidates = by_name[normalized_name_candidate(cast(str, profile["display_name"]))]
        if identity_source != "sportsdataverse_ncaa":
            unresolved.append(
                {
                    "source": identity_source,
                    "external_player_id": college_id,
                    "display_name": profile["display_name"],
                    "status": "UNRESOLVED_SOURCE_ID",
                    "candidate_nba_player_ids": [],
                    "reason": (
                        "The NCAA source supplied no stable player ID; automatic NBA matching "
                        "is disabled."
                    ),
                }
            )
            continue
        requested_nba_id = override_map.get(college_id)
        if requested_nba_id is not None:
            override_player = roster.get(requested_nba_id)
            if override_player is None:
                raise NormalizationError(
                    f"Identity override references absent NBA player {requested_nba_id}"
                )
            matched[college_id] = cast(str, override_player["canonical_id"])
            continue
        corroborated = [
            candidate
            for candidate in candidates
            if _corroborates_college_profile(candidate, profile)
        ]
        if len(corroborated) == 1:
            matched[college_id] = cast(str, corroborated[0]["canonical_id"])
            continue
        status = "AMBIGUOUS" if len(candidates) > 1 or len(corroborated) > 1 else "UNRESOLVED"
        unresolved.append(
            {
                "source": "sportsdataverse_ncaa",
                "external_player_id": college_id,
                "display_name": profile["display_name"],
                "status": status,
                "candidate_nba_player_ids": sorted(
                    cast(str, candidate["external_id"]) for candidate in candidates
                ),
                "reason": "No exact-name NBA candidate"
                if not candidates
                else "Draft-year or school metadata did not uniquely corroborate the name",
            }
        )
    return {"matched": matched, "unresolved": unresolved}


def _corroborates_college_profile(candidate: dict[str, Any], profile: dict[str, Any]) -> bool:
    draft_year = cast(int | None, candidate["draft_year"])
    season_end_years = cast(set[int], profile["season_end_years"])
    college = cast(str | None, candidate["college"])
    teams = cast(set[str], profile["teams"])
    return (
        draft_year is not None
        and draft_year in season_end_years
        and college is not None
        and _normalize_school(college) in {_normalize_school(team) for team in teams}
    )


def _build_unresolved_report(
    resolution: dict[str, Any],
    roster: dict[str, dict[str, Any]],
    college_profiles: dict[str, dict[str, Any]],
    nba_batch: Path,
    position_gaps: list[dict[str, Any]],
    input_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    player_index_path = sorted(nba_batch.glob("nba_com/player_index/*"))[-1]
    season_start_year = int(player_index_path.name.split("-", 1)[0])
    college_names = {
        normalized_name_candidate(cast(str, profile["display_name"]))
        for profile in college_profiles.values()
    }
    international_low_information = [
        {
            "source": "nba_stats",
            "external_player_id": player_id,
            "display_name": player["display_name"],
            "status": "INTERNATIONAL_LOW_INFORMATION",
            "reason": (
                "New NBA player has no NCAA record in the retained datasets; "
                "no international-stat source is available."
            ),
        }
        for player_id, player in sorted(roster.items())
        if player["draft_year"] == season_start_year
        and normalized_name_candidate(cast(str, player["display_name"])) not in college_names
    ]
    records = (
        cast(list[dict[str, Any]], resolution["unresolved"])
        + international_low_information
        + position_gaps
    )
    identifier_gaps = [
        issue for issue in input_issues if issue.get("kind") == "MISSING_PROVIDER_ID"
    ]
    invalid_rows = [issue for issue in input_issues if issue.get("kind") != "MISSING_PROVIDER_ID"]
    issue_counts = Counter(cast(str, issue["reason"]) for issue in input_issues)
    return {
        "schema_version": "1.0.0",
        "policy": "Unresolved or ambiguous records are never merged automatically.",
        "records": records,
        "summary": {
            "matched_college_source_ids": len(cast(dict[str, str], resolution["matched"])),
            "unresolved_or_ambiguous_college_source_ids": len(
                cast(list[dict[str, Any]], resolution["unresolved"])
            ),
            "international_low_information_players": len(international_low_information),
            "source_rows_without_provider_ids": len(identifier_gaps),
            "invalid_source_rows": len(invalid_rows),
        },
        "input_quality": {
            "source_rows_without_provider_ids": len(identifier_gaps),
            "invalid_rows": len(invalid_rows),
            "reason_counts": [
                {"reason": reason, "count": count} for reason, count in sorted(issue_counts.items())
            ],
            "examples": input_issues[:20],
        },
    }


def _validate_processed_data(
    players: list[dict[str, Any]],
    stats: list[dict[str, Any]],
    eligibility: list[dict[str, Any]],
    injury_events: list[dict[str, Any]],
    unresolved: dict[str, Any],
    unresolved_injuries: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    validators = {
        name: Draft202012Validator(load_schema(name), format_checker=FormatChecker())
        for name in ("player", "season-stat", "eligibility", "injury")
    }
    for player in players:
        validators["player"].validate(player)
    for stat in stats:
        validators["season-stat"].validate(stat)
        _validate_stat_ranges(stat)
    for record in eligibility:
        validators["eligibility"].validate(record)
    for event in injury_events:
        validators["injury"].validate(event)
    source_keys = [
        (cast(str, stat["source"]), cast(str, stat["source_record_id"])) for stat in stats
    ]
    if len(source_keys) != len(set(source_keys)):
        raise NormalizationError("Processed season statistics contain duplicate source records")
    event_ids = [cast(str, event["event_id"]) for event in injury_events]
    if len(event_ids) != len(set(event_ids)):
        raise NormalizationError("Processed injury events contain duplicate event IDs")
    nba_years = sorted(
        {cast(int, stat["season_start_year"]) for stat in stats if stat["league_type"] == "NBA"}
    )
    college_years = sorted(
        {cast(int, stat["season_start_year"]) for stat in stats if stat["league_type"] == "COLLEGE"}
    )
    reviewed = _review_accuracy(players, review)
    if reviewed["incorrect"]:
        raise NormalizationError("Reviewed identity sample contains incorrect matches")
    return {
        "schema_version": "1.0.0",
        "players": len(players),
        "season_stats": len(stats),
        "eligibility_records": len(eligibility),
        "injury_events": len(injury_events),
        "unresolved_records": len(cast(list[dict[str, Any]], unresolved["records"])),
        "unresolved_injury_records": len(
            cast(list[dict[str, Any]], unresolved_injuries["records"])
        ),
        "invalid_source_rows": cast(dict[str, int], unresolved["summary"])["invalid_source_rows"],
        "source_rows_without_provider_ids": cast(dict[str, int], unresolved["summary"])[
            "source_rows_without_provider_ids"
        ],
        "invalid_injury_rows": cast(dict[str, int], unresolved_injuries["summary"])[
            "invalid_injury_rows"
        ],
        "nba_season_start_years": nba_years,
        "college_season_start_years": college_years,
        "reviewed_identity_sample": reviewed,
    }


def _validate_stat_ranges(stat: dict[str, Any]) -> None:
    if cast(int, stat["games"]) <= 0:
        raise NormalizationError(f"Non-positive games in {stat['source_record_id']}")
    if cast(float, stat["fgm"]) > cast(float, stat["fga"]):
        raise NormalizationError(f"FGM exceeds FGA in {stat['source_record_id']}")
    if cast(float, stat["ftm"]) > cast(float, stat["fta"]):
        raise NormalizationError(f"FTM exceeds FTA in {stat['source_record_id']}")
    if cast(float, stat["three_pm"]) > cast(float, stat["fgm"]):
        raise NormalizationError(f"3PM exceeds FGM in {stat['source_record_id']}")
    if cast(float, stat["minutes"]) > 60:
        raise NormalizationError(f"Implausible per-game minutes in {stat['source_record_id']}")


def _review_accuracy(players: list[dict[str, Any]], review: dict[str, Any]) -> dict[str, Any]:
    observed: dict[tuple[str, str], str] = {}
    for player in players:
        source_ids = cast(dict[str, str], player["source_ids"])
        nba_id = source_ids.get("nba_stats")
        college_id = source_ids.get("sportsdataverse_ncaa")
        if nba_id is not None and college_id is not None:
            observed[(nba_id, college_id)] = cast(str, player["canonical_player_id"])
    sample = cast(list[dict[str, Any]], review["reviewed_pairs"])
    incorrect = [
        pair
        for pair in sample
        if (cast(str, pair["nba_player_id"]), cast(str, pair["college_player_id"])) not in observed
    ]
    return {
        "sample_size": len(sample),
        "correct": len(sample) - len(incorrect),
        "incorrect": incorrect,
        "accuracy": 1.0 if sample else None,
    }


def _load_review_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise NormalizationError(f"Missing identity review file: {path}")
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise NormalizationError("Identity review file must be a YAML object")
    for key in ("manual_mappings", "reviewed_pairs", "injury_manual_mappings"):
        if not isinstance(value.get(key), list):
            raise NormalizationError(f"Identity review file requires a {key} list")
    seen_injury_names: set[str] = set()
    for index, mapping in enumerate(value["injury_manual_mappings"], start=1):
        if not isinstance(mapping, dict):
            raise NormalizationError(f"Injury mapping {index} must be an object")
        source_name = mapping.get("injury_player_name")
        nba_player_id = mapping.get("nba_player_id")
        if not isinstance(source_name, str) or not source_name.strip():
            raise NormalizationError(f"Injury mapping {index} requires injury_player_name")
        if not isinstance(nba_player_id, str) or not nba_player_id.strip():
            raise NormalizationError(f"Injury mapping {index} requires nba_player_id")
        if source_name in seen_injury_names:
            raise NormalizationError(f"Duplicate injury mapping for {source_name!r}")
        seen_injury_names.add(source_name)
    return cast(dict[str, Any], value)


def _load_existing_players(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records = []
    for line in path.read_text().splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise NormalizationError(f"Invalid existing player registry: {path}")
            records.append(cast(dict[str, Any], value))
    return records


def _nba_result(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise NormalizationError(f"Malformed NBA snapshot: {path}")
    result_sets = payload.get("resultSets")
    if not isinstance(result_sets, list) or not result_sets or not isinstance(result_sets[0], dict):
        raise NormalizationError(f"Malformed NBA result set: {path}")
    return cast(dict[str, Any], result_sets[0])


def _named_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    headers = result.get("headers")
    rows = result.get("rowSet")
    if not isinstance(headers, list) or not all(isinstance(header, str) for header in headers):
        raise NormalizationError("NBA result set has invalid headers")
    if not isinstance(rows, list) or not all(isinstance(row, list) for row in rows):
        raise NormalizationError("NBA result set has invalid rows")
    if any(len(row) != len(headers) for row in rows):
        raise NormalizationError("NBA result set row does not match header length")
    return [dict(zip(cast(list[str], headers), row, strict=True)) for row in rows]


def _verify_snapshot(path: Path) -> None:
    manifest_path = path.with_name(f"{path.name}.manifest.json")
    if not manifest_path.is_file():
        raise NormalizationError(f"Missing provenance manifest for {path}")
    value = json.loads(manifest_path.read_text())
    if not isinstance(value, dict) or not verify_provenance(
        cast(ProvenanceManifest, value), repository_root=_repository_root_for_snapshot(path)
    ):
        raise NormalizationError(f"Provenance verification failed for {path}")


def _manifest_for(path: Path) -> str:
    return (
        path.with_name(f"{path.name}.manifest.json")
        .relative_to(_repository_root_for_snapshot(path))
        .as_posix()
    )


def _retrieved_date(path: Path) -> str:
    manifest = json.loads(path.with_name(f"{path.name}.manifest.json").read_text())
    return cast(str, manifest["retrieved_at"])[:10]


def _latest_batch(source_root: Path) -> Path | None:
    batches = (
        sorted(path for path in source_root.iterdir() if path.is_dir())
        if source_root.is_dir()
        else []
    )
    return batches[-1] if batches else None


def _repository_root_for_snapshot(path: Path) -> Path:
    for ancestor in path.parents:
        if ancestor.name == "raw" and ancestor.parent.name == "data":
            return ancestor.parent.parent
    raise NormalizationError(f"Snapshot is not stored below data/raw: {path}")


def _required_text(row: dict[str, Any], key: str, path: Path) -> str:
    value = row.get(key)
    text = str(value).strip() if value is not None else ""
    if not text or text == "-":
        raise NormalizationError(f"Missing {key} in {path}")
    return text


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text if text and text != "-" else None


def _optional_int(value: Any) -> int | None:
    text = _optional_text(value)
    return int(text) if text is not None else None


def _nonnegative_number(value: Any, field: str, path: Path) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise NormalizationError(f"Invalid {field} in {path}: {value!r}") from error
    if number < 0:
        raise NormalizationError(f"Negative {field} in {path}: {number}")
    return number


def _player_name(row: dict[str, Any], first: str, last: str, path: Path) -> str:
    return f"{_required_text(row, first, path)} {_required_text(row, last, path)}"


def _normalize_positions(raw_position: str) -> list[str]:
    mapping = {"G": ["PG", "SG"], "F": ["SF", "PF"], "C": ["C"]}
    positions = sorted(
        {
            position
            for token in raw_position.upper().split("-")
            for position in mapping.get(token, [])
        }
    )
    if not positions:
        raise NormalizationError(f"Unsupported NBA position: {raw_position}")
    return positions


def _normalize_school(name: str) -> str:
    normalized = normalized_name_candidate(name)
    return _SCHOOL_ALIASES.get(normalized, normalized)


def _unidentified_college_key(season_end_year: int, display_name: str, team: str) -> str:
    """Stable local key for a source row with no provider player ID.

    This key is never eligible for automatic NBA matching. It only preserves a
    source row and gives a future manual correction a stable local target.
    """
    return ":".join(
        [
            "unidentified",
            str(season_end_year),
            normalized_name_candidate(team),
            normalized_name_candidate(display_name),
        ]
    )


def _college_team_code(teams: list[str]) -> str:
    if len(teams) == 1:
        return f"NCAA:{_NON_ALPHANUMERIC.sub('-', normalized_name_candidate(teams[0])).strip('-')}"
    return "NCAA:MULTI"


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
