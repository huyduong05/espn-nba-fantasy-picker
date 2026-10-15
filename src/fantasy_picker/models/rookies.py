"""Phase 4 rookie and low-sample projection adjustments.

Only reviewed NCAA-to-NBA identity links enter this pipeline.  Unresolved
college rows remain excluded, and missing international coverage is surfaced as
an explicit low-information reason rather than inferred from a player's name.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

import yaml

from fantasy_picker.models.projections import (
    TARGET_STATS,
    ProjectionBundle,
    ProjectionError,
    project,
)

ROOKIE_MODEL_VERSION = "phase_4_rookie_low_sample_v1"


def load_phase4_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ProjectionError(f"Missing Phase 4 configuration: {path}")
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ProjectionError("Phase 4 configuration must be a mapping")
    required = {"translation_multiplier", "non_nba_seasons", "nba_weights", "uncertainty_penalties"}
    missing = required.difference(value)
    if missing:
        raise ProjectionError(f"Phase 4 configuration is missing {sorted(missing)}")
    multiplier = float(value["translation_multiplier"])
    if not 0 < multiplier <= 1:
        raise ProjectionError("translation_multiplier must be in (0, 1]")
    return cast(dict[str, Any], value)


def build_phase4_projections(
    records: list[dict[str, Any]],
    players: list[dict[str, Any]],
    eligibility: list[dict[str, Any]],
    unresolved: dict[str, Any],
    bundle: ProjectionBundle,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Blend NBA projections and translated reviewed non-NBA history for active players."""
    active_ids = {cast(str, row["canonical_player_id"]) for row in eligibility}
    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_player[cast(str, record["canonical_player_id"])].append(record)
    nba_projection = {row["canonical_player_id"]: row for row in project(records, bundle)}
    low_information_ids = _international_low_information_ids(players, unresolved)
    projection_year = (
        max(
            int(record["season_start_year"]) for record in records if record["league_type"] == "NBA"
        )
        + 1
    )
    rows = []
    for player_id in sorted(active_ids):
        history = by_player.get(player_id, [])
        nba = sorted(
            (record for record in history if record["league_type"] == "NBA"),
            key=lambda record: int(record["season_start_year"]),
        )
        non_nba = sorted(
            (record for record in history if record["league_type"] in {"COLLEGE", "INTERNATIONAL"}),
            key=lambda record: int(record["season_start_year"]),
        )[-int(config["non_nba_seasons"]) :]
        nba_seasons = len(nba)
        non_nba_projection = _translated_non_nba(non_nba, config)
        nba_row = nba_projection.get(player_id)
        tier = _tier(nba_seasons)
        nba_weight = _nba_weight(tier, nba_row is not None, non_nba_projection is not None, config)
        reasons: list[str] = []
        if nba_row is not None:
            reasons.append("NBA_HISTORY")
        if non_nba_projection is not None:
            reasons.append("TRANSLATED_NON_NBA_HISTORY")
        if player_id in low_information_ids:
            reasons.append("UNSUPPORTED_INTERNATIONAL_HISTORY")
        if nba_row is None and non_nba_projection is None:
            reasons.append("NO_SUPPORTED_HISTORY")
        penalty = _uncertainty_penalty(tier, len(non_nba), player_id in low_information_ids, config)
        row: dict[str, Any] = {
            "canonical_player_id": player_id,
            "projection_season_start_year": projection_year,
            "model_version": ROOKIE_MODEL_VERSION,
            "information_tier": tier,
            "nba_seasons": nba_seasons,
            "non_nba_seasons_used": len(non_nba),
            "nba_weight": nba_weight,
            "non_nba_weight": 1.0 - nba_weight if non_nba_projection is not None else 0.0,
            "translation_multiplier": float(config["translation_multiplier"]),
            "uncertainty_penalty": penalty,
            "recommendation_multiplier": 1.0 - penalty,
            "reason_codes": reasons,
            "source_season_ids": [
                cast(str, record["source_record_id"]) for record in [*nba, *non_nba]
            ],
        }
        for stat in TARGET_STATS:
            nba_value = float(nba_row[stat]) if nba_row is not None else 0.0
            non_nba_value = (
                float(non_nba_projection[stat]) if non_nba_projection is not None else 0.0
            )
            if nba_row is not None and non_nba_projection is not None:
                row[stat] = nba_weight * nba_value + (1.0 - nba_weight) * non_nba_value
            elif nba_row is not None:
                row[stat] = nba_value
            else:
                row[stat] = non_nba_value
        rows.append(row)
    return rows


def save_phase4_artifacts(
    output_dir: Path,
    rows: list[dict[str, Any]],
    input_paths: list[Path],
    config: dict[str, Any],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    projections_path = output_dir / "rookie_adjusted_projections.jsonl"
    projections_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    by_tier: dict[str, int] = defaultdict(int)
    for row in rows:
        by_tier[cast(str, row["information_tier"])] += 1
    metadata_path = output_dir / "rookie_projection_metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "model_version": ROOKIE_MODEL_VERSION,
                "config": config,
                "input_sha256": {path.name: _sha256(path) for path in input_paths},
                "output_count": len(rows),
                "tiers": dict(sorted(by_tier.items())),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return {"projections": projections_path, "metadata": metadata_path}


def _translated_non_nba(
    records: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, float] | None:
    if not records:
        return None
    total_weight = sum(
        max(1.0, float(record["games"]) * float(record["minutes"])) for record in records
    )
    multiplier = float(config["translation_multiplier"])
    return {
        stat: multiplier
        * sum(
            max(1.0, float(record["games"]) * float(record["minutes"])) * float(record[stat])
            for record in records
        )
        / total_weight
        for stat in TARGET_STATS
    }


def _tier(nba_seasons: int) -> str:
    if nba_seasons == 0:
        return "ROOKIE"
    if nba_seasons == 1:
        return "SECOND_YEAR"
    return "ESTABLISHED"


def _nba_weight(tier: str, has_nba: bool, has_non_nba: bool, config: dict[str, Any]) -> float:
    if not has_nba:
        return 0.0
    if not has_non_nba:
        return 1.0
    weights = cast(dict[str, Any], config["nba_weights"])
    return float(weights["second_year"] if tier == "SECOND_YEAR" else weights["established"])


def _uncertainty_penalty(
    tier: str, non_nba_seasons: int, international_gap: bool, config: dict[str, Any]
) -> float:
    penalties = cast(dict[str, Any], config["uncertainty_penalties"])
    if international_gap:
        return round(float(penalties["unsupported_international"]), 6)
    if tier == "ROOKIE":
        return round(
            max(
                0.0,
                float(penalties["rookie_base"])
                - float(penalties["rookie_per_non_nba_season"]) * non_nba_seasons,
            ),
            6,
        )
    if tier == "SECOND_YEAR":
        return round(
            max(
                0.0,
                float(penalties["second_year_base"])
                - float(penalties["second_year_per_non_nba_season"]) * non_nba_seasons,
            ),
            6,
        )
    return round(float(penalties["established"]), 6)


def _international_low_information_ids(
    players: list[dict[str, Any]], unresolved: dict[str, Any]
) -> set[str]:
    by_nba_id = {
        cast(str, player.get("source_ids", {}).get("nba_stats")): cast(
            str, player["canonical_player_id"]
        )
        for player in players
        if player.get("source_ids", {}).get("nba_stats") is not None
    }
    return {
        by_nba_id[cast(str, row["external_player_id"])]
        for row in cast(list[dict[str, Any]], unresolved.get("records", []))
        if row.get("status") == "INTERNATIONAL_LOW_INFORMATION"
        and cast(str, row.get("external_player_id")) in by_nba_id
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
