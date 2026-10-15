"""Deterministic Phase 6 nine-category starters-only roster evaluation."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any, cast

import yaml

from fantasy_picker.contracts import validate

EVALUATOR_MODEL_VERSION = "phase_6_roster_evaluator_v1"
CATEGORIES = ("PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO")
_COUNTING_FIELDS = {
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "3PM": "three_pm",
    "TO": "turnovers",
}
_RAW_STAT_FIELDS = (
    "pts",
    "reb",
    "ast",
    "stl",
    "blk",
    "three_pm",
    "turnovers",
    "fgm",
    "fga",
    "ftm",
    "fta",
)
_POSITION_SET = {"PG", "SG", "SF", "PF", "C"}
_POSITION_BITS = {"PG": 1, "SG": 2, "SF": 4, "PF": 8, "C": 16}
_SLOTS = ("PG", "SG", "SF", "PF", "C", "G", "F", "UTIL1", "UTIL2", "UTIL3")
_REQUIRED_CONFIG = {
    "schema_version",
    "model_version",
    "team_count",
    "roster_size",
    "starter_count",
    "top_player_count",
    "simulations",
    "seed",
    "optimization_passes",
}
_REQUIRED_PROJECTION_FIELDS = {
    "canonical_player_id",
    "pts",
    "reb",
    "ast",
    "stl",
    "blk",
    "three_pm",
    "turnovers",
    "fgm",
    "fga",
    "ftm",
    "fta",
}
_VALID_MATCH_STATUSES = {"EXACT_ID", "EXACT_ALIAS", "MANUAL"}


class EvaluatorError(RuntimeError):
    """An invalid local evaluator input, state, or artifact."""


@dataclass(frozen=True)
class Player:
    """The minimum identity, eligibility, and rate projection for scoring."""

    canonical_player_id: str
    display_name: str
    positions: tuple[str, ...]
    projection: Mapping[str, Any]


def load_evaluator_config(path: Path) -> dict[str, Any]:
    """Read a complete Phase 6 evaluator configuration."""
    if not path.is_file():
        raise EvaluatorError(f"Missing roster-evaluator configuration: {path}")
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise EvaluatorError("Roster-evaluator configuration must be a mapping")
    config = cast(dict[str, Any], value)
    _validate_config(config)
    return config


def load_projections(path: Path) -> list[dict[str, Any]]:
    """Load Phase 3 or Phase 4 JSONL projections with all nine-category inputs."""
    if not path.is_file():
        raise EvaluatorError(f"Missing projection table: {path}")
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise EvaluatorError(f"Invalid JSON in {path} line {line_number}") from error
        if not isinstance(row, dict):
            raise EvaluatorError(f"Expected object in {path} line {line_number}")
        missing = _REQUIRED_PROJECTION_FIELDS.difference(row)
        if missing:
            raise EvaluatorError(
                f"Projection in {path} line {line_number} missing {sorted(missing)}"
            )
        player_id = _player_id(row)
        if player_id in seen_ids:
            raise EvaluatorError(f"Duplicate projection for {player_id}")
        seen_ids.add(player_id)
        for field in _REQUIRED_PROJECTION_FIELDS - {"canonical_player_id"}:
            try:
                value = float(row[field])
            except (TypeError, ValueError) as error:
                raise EvaluatorError(f"Projection {player_id} has non-numeric {field}") from error
            if value < 0:
                raise EvaluatorError(f"Projection {player_id} has negative {field}")
        rows.append(cast(dict[str, Any], row))
    if not rows:
        raise EvaluatorError(f"No projections found in {path}")
    return rows


def load_reference_distribution(path: Path) -> dict[str, Any]:
    """Load a versioned, precomputed reference distribution."""
    if not path.is_file():
        raise EvaluatorError(f"Missing roster reference artifact: {path}")
    try:
        value = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise EvaluatorError(f"Invalid roster reference artifact: {path}") from error
    if not isinstance(value, dict):
        raise EvaluatorError("Roster reference artifact must be an object")
    _validate_reference(cast(dict[str, Any], value))
    return cast(dict[str, Any], value)


def build_reference_distribution(
    projections: Sequence[Mapping[str, Any]],
    eligibility: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a seeded distribution from plausible position-valid top-player rosters."""
    _validate_config(config)
    players = _players_from_projections_and_eligibility(projections, eligibility)
    target_count = min(int(config["top_player_count"]), len(players))
    if target_count < int(config["roster_size"]):
        raise EvaluatorError(
            "Need at least "
            f"{config['roster_size']} projected eligible players; found {target_count}"
        )
    pool = _top_player_pool(players, target_count)
    samples = _sample_valid_rosters(pool, config)
    provisional = _individual_reference(pool)
    lineups: list[dict[str, Any]] = []
    reference = provisional
    for _ in range(int(config["optimization_passes"])):
        lineups = [_lineup_for_players(roster, reference) for roster in samples]
        reference = _reference_from_lineups(lineups)
    return {
        "schema_version": "1.0.0",
        "model_version": EVALUATOR_MODEL_VERSION,
        "configuration": dict(config),
        "input_fingerprint": _fingerprint(projections, eligibility),
        "player_pool_count": len(pool),
        "reference_roster_count": len(lineups),
        "categories": reference["categories"],
    }


def write_reference_distribution(path: Path, reference: Mapping[str, Any]) -> None:
    """Persist a JSON artifact loaded once by later local inference phases."""
    _validate_reference(reference)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(reference), indent=2, sort_keys=True) + "\n")


def evaluate_candidates(
    draft_state: Mapping[str, Any],
    projections: Sequence[Mapping[str, Any]],
    reference: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Evaluate each resolved remaining player against the current draft roster."""
    _validate_reference(reference)
    _validate_draft_state(draft_state)
    projection_by_id = {_player_id(row): row for row in projections}
    roster = _players_from_draft_state(draft_state["user_roster"], projection_by_id, "user_roster")
    candidates = _players_from_draft_state(
        draft_state["remaining_players"], projection_by_id, "remaining_players"
    )
    if len(roster) > int(reference["configuration"]["roster_size"]):
        raise EvaluatorError("User roster exceeds the configured 13-player active roster")
    existing_ids = {player.canonical_player_id for player in roster}
    before = _score_roster(roster, reference)
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.canonical_player_id in existing_ids:
            raise EvaluatorError(
                f"Remaining player {candidate.canonical_player_id} is already rostered"
            )
        if len(roster) >= int(reference["configuration"]["roster_size"]):
            raise EvaluatorError("Cannot evaluate a candidate with a full 13-player roster")
        after = _score_roster([*roster, candidate], reference)
        deltas = {
            category: {
                "before_value": before["categories"][category]["value"],
                "after_value": after["categories"][category]["value"],
                "before_win_probability": before["categories"][category]["win_probability"],
                "after_win_probability": after["categories"][category]["win_probability"],
                "win_gain": round(
                    after["categories"][category]["win_probability"]
                    - before["categories"][category]["win_probability"],
                    6,
                ),
            }
            for category in CATEGORIES
        }
        starter = candidate.canonical_player_id in after["lineup"]["starter_player_ids"]
        results.append(
            {
                "canonical_player_id": candidate.canonical_player_id,
                "display_name": candidate.display_name,
                "positions": list(candidate.positions),
                "starter_status": "STARTER" if starter else "BENCH",
                "category_win_gain": round(sum(delta["win_gain"] for delta in deltas.values()), 6),
                "category_deltas": deltas,
                "before": before,
                "after": after,
                "reason_codes": (
                    ["ROSTER_FIT", "STARTER_CONTRIBUTION"]
                    if starter
                    else ["ROSTER_FIT", "BENCH_NO_IMMEDIATE_CATEGORY_GAIN"]
                ),
            }
        )
    return sorted(
        results,
        key=lambda row: (-float(row["category_win_gain"]), row["canonical_player_id"]),
    )


def write_candidate_evaluations(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """Write Phase 7-ready candidate evaluation JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(rows), indent=2, sort_keys=True) + "\n")


def _score_roster(players: Sequence[Player], reference: Mapping[str, Any]) -> dict[str, Any]:
    lineup = _lineup_for_players(players, reference)
    categories: dict[str, dict[str, float]] = {}
    for category, value in lineup["totals"].items():
        category_reference = cast(Mapping[str, Any], reference["categories"])[category]
        standard_deviation = float(category_reference["standard_deviation"])
        mean = float(category_reference["mean"])
        z_score = (
            (mean - value) / standard_deviation
            if category == "TO"
            else (value - mean) / standard_deviation
        )
        categories[category] = {
            "value": round(value, 6),
            "z_score": round(z_score, 6),
            "win_probability": round(_normal_cdf(z_score), 6),
        }
    return {"lineup": lineup, "categories": categories}


def _players_from_projections_and_eligibility(
    projections: Sequence[Mapping[str, Any]], eligibility: Sequence[Mapping[str, Any]]
) -> list[Player]:
    projection_by_id = {_player_id(row): row for row in projections}
    positions_by_id: dict[str, tuple[str, ...]] = {}
    for row in eligibility:
        player_id = _player_id(row)
        positions_by_id[player_id] = _positions(row.get("positions"), player_id)
    players = [
        Player(
            canonical_player_id=player_id,
            display_name=player_id,
            positions=positions_by_id[player_id],
            projection=projection,
        )
        for player_id, projection in projection_by_id.items()
        if player_id in positions_by_id
    ]
    if not players:
        raise EvaluatorError("No projections have corresponding position eligibility")
    return sorted(players, key=lambda player: player.canonical_player_id)


def _top_player_pool(players: Sequence[Player], target_count: int) -> list[Player]:
    reference = _individual_reference(players)
    ranked = sorted(
        players,
        key=lambda player: (-_composite(_totals([player]), reference), player.canonical_player_id),
    )
    return ranked[:target_count]


def _sample_valid_rosters(pool: Sequence[Player], config: Mapping[str, Any]) -> list[list[Player]]:
    rng = random.Random(int(config["seed"]))
    roster_size = int(config["roster_size"])
    simulations = int(config["simulations"])
    samples: list[list[Player]] = []
    attempts = 0
    maximum_attempts = simulations * 100
    while len(samples) < simulations and attempts < maximum_attempts:
        attempts += 1
        roster = rng.sample(list(pool), roster_size)
        if _lineup_assignment(roster, int(config["starter_count"])) is not None:
            samples.append(sorted(roster, key=lambda player: player.canonical_player_id))
    if len(samples) != simulations:
        raise EvaluatorError(
            "Could not sample enough position-valid reference rosters from the player pool"
        )
    return samples


def _lineup_for_players(players: Sequence[Player], reference: Mapping[str, Any]) -> dict[str, Any]:
    starter_count = min(len(_SLOTS), len(players))
    assignment = _lineup_assignment(players, starter_count, reference)
    if assignment is None:
        assignment = _best_partial_assignment(players, reference)
    if assignment is None:
        return {"starter_player_ids": [], "slot_assignments": [], "totals": _totals([])}
    selected = [players[index] for index in assignment[0]]
    slot_assignments = [
        {"slot": slot, "canonical_player_id": players[index].canonical_player_id}
        for slot, index in assignment[1]
    ]
    return {
        "starter_player_ids": sorted(player.canonical_player_id for player in selected),
        "slot_assignments": slot_assignments,
        "totals": _totals(selected),
    }


def _best_partial_assignment(
    players: Sequence[Player], reference: Mapping[str, Any]
) -> tuple[tuple[int, ...], tuple[tuple[str, int], ...]] | None:
    for count in range(min(len(players), len(_SLOTS)) - 1, 0, -1):
        assignment = _lineup_assignment(players, count, reference)
        if assignment is not None:
            return assignment
    return None


def _lineup_assignment(
    players: Sequence[Player],
    count: int,
    reference: Mapping[str, Any] | None = None,
) -> tuple[tuple[int, ...], tuple[tuple[str, int], ...]] | None:
    """Choose a valid maximum-composite subset and one deterministic slot matching."""
    best: tuple[tuple[int, ...], tuple[tuple[str, int], ...]] | None = None
    best_key: tuple[float, tuple[str, ...], tuple[tuple[str, str], ...]] | None = None
    all_raw = _raw_totals(players)
    for indices in itertools.combinations(range(len(players)), count):
        for slots in itertools.combinations(_SLOTS, count):
            matching = _match_slots(players, indices, slots)
            if matching is None:
                continue
            selected = [players[index] for index in indices]
            score = (
                _composite(_totals_for_indices(players, indices, all_raw), reference)
                if reference is not None
                else 0.0
            )
            key = (
                -round(score, 12),
                tuple(sorted(player.canonical_player_id for player in selected)),
                tuple((slot, players[index].canonical_player_id) for slot, index in matching),
            )
            if best_key is None or key < best_key:
                best = (indices, matching)
                best_key = key
    return best


def _match_slots(
    players: Sequence[Player], indices: Sequence[int], slots: Sequence[str]
) -> tuple[tuple[str, int], ...] | None:
    """Match position patterns once, then map the result to canonical player IDs."""
    player_indices = tuple(sorted(indices, key=lambda index: players[index].canonical_player_id))
    masks_by_index = {index: _position_mask(players[index].positions) for index in player_indices}
    pattern = tuple(sorted(masks_by_index.values()))
    pattern_assignment = _match_position_pattern(pattern, tuple(slots))
    if pattern_assignment is None:
        return None
    available_by_mask: dict[int, list[int]] = {}
    for index in player_indices:
        available_by_mask.setdefault(masks_by_index[index], []).append(index)
    result = []
    for slot, pattern_index in zip(slots, pattern_assignment, strict=True):
        mask = pattern[pattern_index]
        result.append((slot, available_by_mask[mask].pop(0)))
    return tuple(result)


@cache
def _match_position_pattern(
    masks: tuple[int, ...], slots: tuple[str, ...]
) -> tuple[int, ...] | None:
    """Cached deterministic bipartite matching for a sorted position-mask pattern."""
    candidates_by_slot = {
        slot: tuple(index for index, mask in enumerate(masks) if mask & _slot_mask(slot))
        for slot in slots
    }
    if any(not candidates for candidates in candidates_by_slot.values()):
        return None
    player_to_slot: dict[int, str] = {}

    def place(slot: str, seen_players: set[int]) -> bool:
        for index in candidates_by_slot[slot]:
            if index in seen_players:
                continue
            seen_players.add(index)
            existing = player_to_slot.get(index)
            if existing is None or place(existing, seen_players):
                player_to_slot[index] = slot
                return True
        return False

    for slot in sorted(slots, key=lambda value: (len(candidates_by_slot[value]), value)):
        if not place(slot, set()):
            return None
    slot_to_pattern_index = {slot: index for index, slot in player_to_slot.items()}
    return tuple(slot_to_pattern_index[slot] for slot in slots)


def _eligible_for_slot(player: Player, slot: str) -> bool:
    return bool(_position_mask(player.positions) & _slot_mask(slot))


def _position_mask(positions: Sequence[str]) -> int:
    return sum(_POSITION_BITS[position] for position in positions)


def _slot_mask(slot: str) -> int:
    if slot.startswith("UTIL"):
        return sum(_POSITION_BITS.values())
    if slot == "G":
        return _POSITION_BITS["PG"] | _POSITION_BITS["SG"]
    if slot == "F":
        return _POSITION_BITS["SF"] | _POSITION_BITS["PF"]
    return _POSITION_BITS[slot]


def _totals(players: Sequence[Player]) -> dict[str, float]:
    return _totals_from_raw(_raw_totals(players))


def _totals_for_indices(
    players: Sequence[Player], indices: Sequence[int], all_raw: Mapping[str, float]
) -> dict[str, float]:
    if len(indices) >= len(players) - 3:
        selected = set(indices)
        raw = {
            field: all_raw[field]
            - sum(
                float(players[index].projection[field])
                for index in range(len(players))
                if index not in selected
            )
            for field in _RAW_STAT_FIELDS
        }
        return _totals_from_raw(raw)
    return _totals([players[index] for index in indices])


def _raw_totals(players: Sequence[Player]) -> dict[str, float]:
    return {
        field: sum(float(player.projection[field]) for player in players)
        for field in _RAW_STAT_FIELDS
    }


def _totals_from_raw(raw: Mapping[str, float]) -> dict[str, float]:
    totals = {category: 0.0 for category in CATEGORIES}
    for category, field in _COUNTING_FIELDS.items():
        totals[category] = float(raw[field])
    totals["FG%"] = raw["fgm"] / raw["fga"] if raw["fga"] else 0.0
    totals["FT%"] = raw["ftm"] / raw["fta"] if raw["fta"] else 0.0
    return totals


def _individual_reference(players: Sequence[Player]) -> dict[str, Any]:
    return _reference_from_totals([_totals([player]) for player in players])


def _reference_from_lineups(lineups: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    totals = [cast(Mapping[str, float], lineup["totals"]) for lineup in lineups]
    return _reference_from_totals(totals)


def _reference_from_totals(totals_rows: Sequence[Mapping[str, float]]) -> dict[str, Any]:
    if not totals_rows:
        raise EvaluatorError("Cannot calculate a reference distribution from no lineups")
    categories = {}
    for category in CATEGORIES:
        values = [float(row[category]) for row in totals_rows]
        deviation = pstdev(values)
        categories[category] = {
            "mean": round(fmean(values), 12),
            "standard_deviation": round(deviation if deviation > 1e-9 else 1.0, 12),
        }
    return {"categories": categories}


def _composite(totals: Mapping[str, float], reference: Mapping[str, Any] | None) -> float:
    if reference is None:
        return 0.0
    categories = cast(Mapping[str, Any], reference["categories"])
    return sum(
        (float(categories[category]["mean"]) - float(totals[category]))
        / float(categories[category]["standard_deviation"])
        if category == "TO"
        else (float(totals[category]) - float(categories[category]["mean"]))
        / float(categories[category]["standard_deviation"])
        for category in CATEGORIES
    )


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _players_from_draft_state(
    records: Any, projection_by_id: Mapping[str, Mapping[str, Any]], label: str
) -> list[Player]:
    if not isinstance(records, list):
        raise EvaluatorError(f"Draft state {label} must be a list")
    players: list[Player] = []
    seen_ids: set[str] = set()
    for index, record in enumerate(records, start=1):
        if not isinstance(record, Mapping):
            raise EvaluatorError(f"Draft state {label} record {index} must be an object")
        status = record.get("match_status")
        if status not in _VALID_MATCH_STATUSES:
            raise EvaluatorError(
                f"Draft state {label} record {index} has unresolved player identity"
            )
        player_id = record.get("canonical_player_id")
        if not isinstance(player_id, str):
            raise EvaluatorError(f"Draft state {label} record {index} lacks canonical_player_id")
        if player_id in seen_ids:
            raise EvaluatorError(f"Duplicate player {player_id} in draft state {label}")
        if player_id not in projection_by_id:
            raise EvaluatorError(f"Missing projection for {player_id}")
        display_name = record.get("display_name")
        if not isinstance(display_name, str) or not display_name:
            raise EvaluatorError(f"Draft state {label} record {index} lacks display_name")
        players.append(
            Player(
                canonical_player_id=player_id,
                display_name=display_name,
                positions=_positions(record.get("positions"), player_id),
                projection=projection_by_id[player_id],
            )
        )
        seen_ids.add(player_id)
    return players


def _positions(value: Any, player_id: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise EvaluatorError(f"Player {player_id} requires at least one valid position")
    positions = tuple(sorted(cast(list[str], value)))
    if len(set(positions)) != len(positions) or not set(positions).issubset(_POSITION_SET):
        raise EvaluatorError(f"Player {player_id} has invalid positions")
    return positions


def _player_id(row: Mapping[str, Any]) -> str:
    value = row.get("canonical_player_id")
    if not isinstance(value, str) or not value:
        raise EvaluatorError("Record lacks canonical_player_id")
    return value


def _validate_draft_state(state: Mapping[str, Any]) -> None:
    try:
        validate(dict(state), "draft-state")
    except Exception as error:
        raise EvaluatorError(f"Invalid draft state: {error}") from error


def _validate_config(config: Mapping[str, Any]) -> None:
    missing = _REQUIRED_CONFIG.difference(config)
    if missing:
        raise EvaluatorError(f"Roster-evaluator config missing {sorted(missing)}")
    if config["model_version"] != EVALUATOR_MODEL_VERSION:
        raise EvaluatorError("Unexpected roster-evaluator model version")
    if int(config["team_count"]) != 12 or int(config["roster_size"]) != 13:
        raise EvaluatorError("Phase 6 supports the configured 12-team, 13-player league only")
    if int(config["starter_count"]) != len(_SLOTS):
        raise EvaluatorError("starter_count must equal the configured ten starter slots")
    if int(config["top_player_count"]) != int(config["team_count"]) * int(config["roster_size"]):
        raise EvaluatorError("top_player_count must equal teams multiplied by roster_size")
    if int(config["simulations"]) <= 0 or int(config["optimization_passes"]) <= 0:
        raise EvaluatorError("simulations and optimization_passes must be positive")


def _validate_reference(reference: Mapping[str, Any]) -> None:
    if reference.get("schema_version") != "1.0.0":
        raise EvaluatorError("Unexpected reference schema version")
    if reference.get("model_version") != EVALUATOR_MODEL_VERSION:
        raise EvaluatorError("Unexpected reference model version")
    config = reference.get("configuration")
    categories = reference.get("categories")
    if not isinstance(config, Mapping) or not isinstance(categories, Mapping):
        raise EvaluatorError("Reference artifact lacks configuration or categories")
    _validate_config(cast(Mapping[str, Any], config))
    if set(categories) != set(CATEGORIES):
        raise EvaluatorError("Reference artifact categories do not match the nine-category league")
    for category in CATEGORIES:
        row = categories[category]
        if not isinstance(row, Mapping) or float(row.get("standard_deviation", 0.0)) <= 0:
            raise EvaluatorError(f"Reference artifact has invalid {category} distribution")


def _fingerprint(
    projections: Sequence[Mapping[str, Any]], eligibility: Sequence[Mapping[str, Any]]
) -> str:
    value = {"projections": list(projections), "eligibility": list(eligibility)}
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
