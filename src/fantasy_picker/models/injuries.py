"""Phase 5 local injury and availability scoring.

The score is deliberately a recommendation adjustment, never an edit to a
player's per-game projection.  Injury records must already have resolved
canonical player IDs; this module does not perform name matching.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any, cast

import yaml
from jsonschema import ValidationError

from fantasy_picker.contracts import validate

INJURY_MODEL_VERSION = "phase_5_injury_availability_v1"
_CURRENT_STATUSES = {"OUT", "DOUBTFUL", "QUESTIONABLE", "PROBABLE", "ACTIVE", "UNKNOWN"}
_REQUIRED_CONFIG_KEYS = {
    "schema_version",
    "model_version",
    "historical_window_days",
    "recency_half_life_days",
    "games_missed",
    "recurrence",
    "current_status_penalties",
    "current_event_type_penalties",
    "maximum_current_penalty",
    "return_timeline_penalties",
    "ir_eligibility_reduction",
    "maximum_penalty",
}


class InjuryScoringError(RuntimeError):
    """A malformed local injury input or configuration."""


def load_injury_config(path: Path) -> dict[str, Any]:
    """Load and validate the transparent Phase 5 scoring configuration."""
    if not path.is_file():
        raise InjuryScoringError(f"Missing injury-risk configuration: {path}")
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise InjuryScoringError("Injury-risk configuration must be a mapping")
    missing = _REQUIRED_CONFIG_KEYS.difference(value)
    if missing:
        raise InjuryScoringError(f"Injury-risk configuration is missing {sorted(missing)}")
    _validate_config(cast(dict[str, Any], value))
    return cast(dict[str, Any], value)


def load_injury_events(path: Path) -> list[dict[str, Any]]:
    """Read schema-validated, identity-resolved injury events from JSONL."""
    if not path.is_file():
        raise InjuryScoringError(f"Missing injury event dataset: {path}")
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise InjuryScoringError(f"Invalid JSON in {path} line {line_number}") from error
        if not isinstance(event, dict):
            raise InjuryScoringError(f"Expected an object in {path} line {line_number}")
        try:
            validate(event, "injury")
        except ValidationError as error:
            raise InjuryScoringError(
                f"Invalid injury event in {path} line {line_number}: {error.message}"
            ) from error
        events.append(cast(dict[str, Any], event))
    return events


def score_injury_events(
    events: Iterable[Mapping[str, Any]],
    as_of_date: date,
    config: Mapping[str, Any],
    *,
    player_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Return one explainable availability assessment for every requested player.

    An empty event history creates a zero penalty, but is marked as unknown
    injury data so downstream ranking never mistakes it for confirmed health.
    """
    _validate_config(config)
    by_player: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        player_id = _required_text(event, "canonical_player_id")
        by_player[player_id].append(event)
    requested_ids = set(player_ids) | set(by_player)
    return [
        _score_player(player_id, by_player.get(player_id, []), as_of_date, config)
        for player_id in sorted(requested_ids)
    ]


def write_injury_assessments(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """Write deterministic JSONL assessments for later local inference."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(dict(row), sort_keys=True) + "\n" for row in rows))


def _score_player(
    player_id: str,
    events: list[Mapping[str, Any]],
    as_of: date,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    historical = [event for event in events if _is_historical(event, as_of)]
    current = [event for event in events if _is_current(event, as_of)]
    historical_games = _historical_games_penalty(historical, as_of, config)
    recurrence, recurrence_count = _recurrence_penalty(historical, as_of, config)
    current_status, current_type, return_timeline, ir_reduction, has_current_status = (
        _current_penalties(current, as_of, config)
    )
    current_total = min(
        float(config["maximum_current_penalty"]), current_status + current_type + return_timeline
    )
    uncapped = historical_games + recurrence + current_total
    penalty = max(0.0, min(float(config["maximum_penalty"]), uncapped - ir_reduction))
    reasons = _reason_codes(
        events,
        historical,
        current,
        recurrence_count,
        has_current_status,
        ir_reduction,
    )
    data_status = _data_status(events, current, has_current_status)
    return {
        "canonical_player_id": player_id,
        "as_of_date": as_of.isoformat(),
        "model_version": cast(str, config["model_version"]),
        "data_status": data_status,
        "injury_risk_score": round(uncapped, 6),
        "injury_penalty": round(penalty, 6),
        "injury_penalty_pct": round(penalty * 100, 3),
        "recommendation_multiplier": round(1.0 - penalty, 6),
        "reason_codes": reasons,
        "features": {
            "event_count": len(events),
            "historical_event_count": len(historical),
            "current_event_count": len(current),
            "recurring_event_count": recurrence_count,
            "current_status_available": has_current_status,
            "current_ir_eligible": _current_ir_eligible(current),
            "historical_games_missed_penalty": round(historical_games, 6),
            "recurrence_penalty": round(recurrence, 6),
            "current_status_penalty": round(current_status, 6),
            "current_event_type_penalty": round(current_type, 6),
            "return_timeline_penalty": round(return_timeline, 6),
            "ir_eligibility_reduction": round(ir_reduction, 6),
        },
    }


def _historical_games_penalty(
    events: Iterable[Mapping[str, Any]], as_of: date, config: Mapping[str, Any]
) -> float:
    weighted_games = 0.0
    for event in events:
        missed = event.get("games_missed")
        if missed is None:
            continue
        age = (as_of - _event_end_date(event)).days
        if age < 0 or age > int(config["historical_window_days"]):
            continue
        weight = math.pow(0.5, age / float(config["recency_half_life_days"]))
        weighted_games += float(missed) * weight
    settings = cast(Mapping[str, Any], config["games_missed"])
    return min(
        float(settings["maximum_penalty"]),
        float(settings["maximum_penalty"]) * weighted_games / float(settings["normalizing_games"]),
    )


def _recurrence_penalty(
    events: Iterable[Mapping[str, Any]], as_of: date, config: Mapping[str, Any]
) -> tuple[float, int]:
    groups: dict[str, int] = defaultdict(int)
    for event in events:
        age = (as_of - _event_end_date(event)).days
        if 0 <= age <= int(config["historical_window_days"]):
            groups[_recurrence_key(event)] += 1
    largest_group = max(groups.values(), default=0)
    repeats = max(0, largest_group - 1)
    settings = cast(Mapping[str, Any], config["recurrence"])
    divisor = max(1, int(settings["events_for_maximum"]) - 1)
    penalty = float(settings["maximum_penalty"]) * min(1.0, repeats / divisor)
    return penalty, repeats


def _current_penalties(
    current: Iterable[Mapping[str, Any]], as_of: date, config: Mapping[str, Any]
) -> tuple[float, float, float, float, bool]:
    current_events = list(current)
    if not current_events:
        return 0.0, 0.0, 0.0, 0.0, False
    status_penalties = cast(Mapping[str, Any], config["current_status_penalties"])
    type_penalties = cast(Mapping[str, Any], config["current_event_type_penalties"])
    status = max(
        float(status_penalties[_required_text(event, "status")]) for event in current_events
    )
    event_type = max(
        float(type_penalties[_required_text(event, "event_type")]) for event in current_events
    )
    return_timeline = max(
        _return_timeline_penalty(event, as_of, config) for event in current_events
    )
    reduction = (
        float(config["ir_eligibility_reduction"]) if _current_ir_eligible(current_events) else 0.0
    )
    return status, event_type, return_timeline, reduction, True


def _return_timeline_penalty(
    event: Mapping[str, Any], as_of: date, config: Mapping[str, Any]
) -> float:
    expected = event.get("expected_return_date")
    if expected is None:
        return 0.0
    days = (date.fromisoformat(cast(str, expected)) - as_of).days
    if days <= 0:
        return 0.0
    settings = cast(Mapping[str, Any], config["return_timeline_penalties"])
    if days <= 7:
        return float(settings["within_7_days"])
    if days <= 30:
        return float(settings["within_30_days"])
    return float(settings["beyond_30_days"])


def _reason_codes(
    events: list[Mapping[str, Any]],
    historical: list[Mapping[str, Any]],
    current: list[Mapping[str, Any]],
    recurrence_count: int,
    has_current_status: bool,
    ir_reduction: float,
) -> list[str]:
    reasons: list[str] = []
    if historical:
        reasons.append("HISTORICAL_ABSENCE_EVIDENCE")
    if recurrence_count:
        reasons.append("RECURRENT_ABSENCE_PATTERN")
    if not has_current_status:
        reasons.append("CURRENT_STATUS_UNAVAILABLE")
    for event in current:
        status = _required_text(event, "status")
        event_type = _required_text(event, "event_type")
        reasons.append(f"CURRENT_{status}")
        reasons.append(f"CURRENT_{event_type}")
        if event.get("expected_return_date") is not None:
            reasons.append("EXPECTED_RETURN_REPORTED")
    if ir_reduction:
        reasons.append("IR_ELIGIBLE_CURRENT_ABSENCE")
    if not events:
        reasons.append("NO_INJURY_EVENTS")
    return sorted(set(reasons))


def _data_status(
    events: list[Mapping[str, Any]], current: list[Mapping[str, Any]], has_current: bool
) -> str:
    if not events:
        return "NO_INJURY_DATA"
    if not has_current:
        return "HISTORICAL_ONLY"
    if any(_required_text(event, "status") == "UNKNOWN" for event in current):
        return "CURRENT_STATUS_UNKNOWN"
    return "CURRENT_STATUS_AVAILABLE"


def _is_historical(event: Mapping[str, Any], as_of: date) -> bool:
    return _required_text(event, "status") == "HISTORICAL" and _event_end_date(event) <= as_of


def _is_current(event: Mapping[str, Any], as_of: date) -> bool:
    if _required_text(event, "status") not in _CURRENT_STATUSES:
        return False
    if date.fromisoformat(_required_text(event, "start_date")) > as_of:
        return False
    end = event.get("end_date")
    return end is None or date.fromisoformat(cast(str, end)) >= as_of


def _event_end_date(event: Mapping[str, Any]) -> date:
    end = event.get("end_date")
    return (
        date.fromisoformat(cast(str, end))
        if end is not None
        else date.fromisoformat(_required_text(event, "start_date"))
    )


def _recurrence_key(event: Mapping[str, Any]) -> str:
    description = str(event.get("description") or "").lower()
    normalized = "".join(character if character.isalnum() else " " for character in description)
    return f"{_required_text(event, 'event_type')}:{' '.join(normalized.split()) or 'unspecified'}"


def _current_ir_eligible(events: Iterable[Mapping[str, Any]]) -> bool:
    return any(event.get("ir_eligible") is True for event in events)


def _required_text(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise InjuryScoringError(f"Injury event is missing a non-empty {field}")
    return value


def _validate_config(config: Mapping[str, Any]) -> None:
    missing = _REQUIRED_CONFIG_KEYS.difference(config)
    if missing:
        raise InjuryScoringError(f"Injury-risk configuration is missing {sorted(missing)}")
    if config["model_version"] != INJURY_MODEL_VERSION:
        raise InjuryScoringError("Unexpected injury-risk model version")
    maximum = float(config["maximum_penalty"])
    if not 0 < maximum <= 0.15:
        raise InjuryScoringError("maximum_penalty must be in (0, 0.15]")
    if float(config["recency_half_life_days"]) <= 0:
        raise InjuryScoringError("recency_half_life_days must be positive")
    if int(config["historical_window_days"]) <= 0:
        raise InjuryScoringError("historical_window_days must be positive")
    if not 0 <= float(config["ir_eligibility_reduction"]) <= maximum:
        raise InjuryScoringError(
            "ir_eligibility_reduction must be between zero and maximum_penalty"
        )
    _validate_penalty_mapping(config, "current_status_penalties", _CURRENT_STATUSES)
    _validate_penalty_mapping(
        config,
        "current_event_type_penalties",
        {"INJURY", "SUSPENSION", "PERSONAL", "LOAD_MANAGEMENT"},
    )


def _validate_penalty_mapping(config: Mapping[str, Any], name: str, required: set[str]) -> None:
    values = config[name]
    if not isinstance(values, Mapping) or set(values) != required:
        raise InjuryScoringError(f"{name} must define exactly {sorted(required)}")
    if any(float(value) < 0 for value in values.values()):
        raise InjuryScoringError(f"{name} cannot contain negative penalties")
