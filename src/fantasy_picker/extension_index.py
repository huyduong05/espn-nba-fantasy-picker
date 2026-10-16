"""Generate the local player index consumed by the manual draft-board extension."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fantasy_picker.identity import normalized_name_candidate

INDEX_VERSION = "phase_9_player_index_v1"
_POSITIONS = {"PG", "SG", "SF", "PF", "C"}


class PlayerIndexError(RuntimeError):
    """A required local input cannot produce a trustworthy player index."""


def build_player_index(
    players: Iterable[Mapping[str, Any]],
    eligibility: Iterable[Mapping[str, Any]],
    active_projection_ids: Iterable[str],
    *,
    generated_at: str,
) -> dict[str, Any]:
    """Return a deterministic active-player index with explicit alias evidence."""
    active_ids = set(active_projection_ids)
    if not active_ids:
        raise PlayerIndexError("Phase 4 projection artifact has no active players")
    players_by_id = _players_by_id(players)
    positions_by_id = _positions_by_id(eligibility)
    missing_players = sorted(active_ids.difference(players_by_id))
    missing_positions = sorted(active_ids.difference(positions_by_id))
    if missing_players or missing_positions:
        details = []
        if missing_players:
            details.append(f"missing player records for {len(missing_players)} active projections")
        if missing_positions:
            details.append(
                f"missing eligibility records for {len(missing_positions)} active projections"
            )
        raise PlayerIndexError("; ".join(details))

    entries = []
    for player_id in sorted(active_ids):
        player = players_by_id[player_id]
        display_name = _text(player, "display_name", player_id)
        aliases = sorted(
            {
                alias
                for alias in cast(list[Any], player.get("aliases", []))
                if isinstance(alias, str) and alias and alias != display_name
            },
            key=lambda value: (normalized_name_candidate(value), value),
        )
        entries.append(
            {
                "canonical_player_id": player_id,
                "display_name": display_name,
                "aliases": aliases,
                "positions": positions_by_id[player_id],
            }
        )
    payload = {"index_version": INDEX_VERSION, "players": entries}
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": "1.0.0",
        "index_version": INDEX_VERSION,
        "generated_at": generated_at,
        "input_fingerprint": f"phase9-{fingerprint[:16]}",
        "players": entries,
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL artifact with object records only."""
    if not path.is_file():
        raise PlayerIndexError(f"Missing local artifact: {path}")
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not all(isinstance(record, dict) for record in records):
        raise PlayerIndexError(f"Expected JSON object records in {path}")
    return cast(list[dict[str, Any]], records)


def write_player_index(path: Path, index: Mapping[str, Any]) -> None:
    """Persist the index as a single static extension asset."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(index), indent=2, sort_keys=True) + "\n")


def current_timestamp() -> str:
    """Return the generator timestamp using the common contract timestamp format."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _players_by_id(players: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for player in players:
        player_id = _text(player, "canonical_player_id", "player")
        if player_id in result:
            raise PlayerIndexError(f"Duplicate canonical player ID in player registry: {player_id}")
        result[player_id] = player
    return result


def _positions_by_id(eligibility: Iterable[Mapping[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for record in eligibility:
        player_id = _text(record, "canonical_player_id", "eligibility")
        positions = record.get("positions")
        if not isinstance(positions, list) or not positions:
            raise PlayerIndexError(f"Eligibility record for {player_id} has no positions")
        normalized = sorted(set(cast(list[str], positions)))
        if not set(normalized).issubset(_POSITIONS):
            raise PlayerIndexError(f"Eligibility record for {player_id} has invalid positions")
        if player_id in result:
            raise PlayerIndexError(f"Duplicate eligibility record for {player_id}")
        result[player_id] = normalized
    return result


def _text(record: Mapping[str, Any], field: str, label: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise PlayerIndexError(f"{label} is missing {field}")
    return value
