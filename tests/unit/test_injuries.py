from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from fantasy_picker.cli import main
from fantasy_picker.contracts import repository_root
from fantasy_picker.models.injuries import (
    InjuryScoringError,
    load_injury_config,
    score_injury_events,
)

PLAYER = "plr_0123456789abcdef0123456789abcdef"
OTHER_PLAYER = "plr_fedcba9876543210fedcba9876543210"
AS_OF = date(2026, 10, 15)


def test_penalties_are_bounded_and_missing_data_is_explicit() -> None:
    rows = score_injury_events(
        [
            _event("OUT", "INJURY", "2026-10-01", games_missed=100, expected_return="2026-12-01"),
            _event("HISTORICAL", "INJURY", "2026-09-01", end="2026-09-30", games_missed=100),
            _event("HISTORICAL", "INJURY", "2026-08-01", end="2026-08-30", games_missed=100),
            _event("HISTORICAL", "INJURY", "2026-07-01", end="2026-07-30", games_missed=100),
        ],
        AS_OF,
        _config(),
        player_ids=[PLAYER, OTHER_PLAYER],
    )
    by_id = {row["canonical_player_id"]: row for row in rows}
    severe = by_id[PLAYER]
    missing = by_id[OTHER_PLAYER]
    assert severe["injury_penalty"] == 0.15
    assert severe["injury_penalty_pct"] == 15.0
    assert severe["recommendation_multiplier"] == 0.85
    assert "CURRENT_OUT" in severe["reason_codes"]
    assert "RECURRENT_ABSENCE_PATTERN" in severe["reason_codes"]
    assert missing["injury_penalty"] == 0.0
    assert missing["data_status"] == "NO_INJURY_DATA"
    assert "CURRENT_STATUS_UNAVAILABLE" in missing["reason_codes"]


def test_current_risk_ordering_return_timeline_and_ir_adjustment() -> None:
    healthy = _single(_event("ACTIVE", "INJURY", "2026-10-01"))
    questionable = _single(_event("QUESTIONABLE", "INJURY", "2026-10-01"))
    out_soon = _single(_event("OUT", "INJURY", "2026-10-01", expected_return="2026-10-20"))
    out_ir = _single(
        _event("OUT", "INJURY", "2026-10-01", expected_return="2026-10-20", ir_eligible=True)
    )
    suspension = _single(_event("OUT", "SUSPENSION", "2026-10-01"))
    assert healthy["injury_penalty"] == 0.0
    assert healthy["data_status"] == "CURRENT_STATUS_AVAILABLE"
    assert questionable["injury_penalty"] < out_soon["injury_penalty"]
    assert out_ir["injury_penalty"] < out_soon["injury_penalty"]
    standard_out = _single(_event("OUT", "INJURY", "2026-10-01"))
    assert suspension["injury_penalty"] > standard_out["injury_penalty"]
    assert "IR_ELIGIBLE_CURRENT_ABSENCE" in out_ir["reason_codes"]


def test_recent_absences_and_recurring_descriptions_score_higher() -> None:
    recent = _single(
        _event("HISTORICAL", "INJURY", "2026-09-01", end="2026-09-15", games_missed=10)
    )
    old = _single(_event("HISTORICAL", "INJURY", "2023-09-01", end="2023-09-15", games_missed=10))
    recurrence = _single(
        _event("HISTORICAL", "INJURY", "2026-09-01", end="2026-09-15", games_missed=10),
        _event("HISTORICAL", "INJURY", "2025-09-01", end="2025-09-15", games_missed=10),
    )
    assert recent["injury_penalty"] > old["injury_penalty"]
    assert recurrence["injury_penalty"] > recent["injury_penalty"]
    assert recurrence["features"]["recurring_event_count"] == 1


def test_rejects_a_penalty_cap_above_fifteen_percent(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    source = (repository_root() / "config/injury-risk.yaml").read_text()
    path.write_text(source.replace("maximum_penalty: 0.150", "maximum_penalty: 0.151"))
    with pytest.raises(InjuryScoringError, match="maximum_penalty"):
        load_injury_config(path)


def test_cli_writes_a_schema_validated_offline_assessment(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "event_id": "evt_fedcba9876543210fedcba9876543210",
                **_event("OUT", "INJURY", "2026-10-01", expected_return="2026-10-20"),
                "source": "fixture_source",
            }
        )
        + "\n"
    )
    players_path = tmp_path / "players.jsonl"
    players_path.write_text(json.dumps({"canonical_player_id": PLAYER}) + "\n")
    output_path = tmp_path / "assessments.jsonl"

    result = main(
        [
            "injury",
            "score",
            "--events",
            events_path.as_posix(),
            "--players",
            players_path.as_posix(),
            "--as-of",
            AS_OF.isoformat(),
            "--output",
            output_path.as_posix(),
        ]
    )

    assert result == 0
    row = json.loads(output_path.read_text())
    assert row["canonical_player_id"] == PLAYER
    assert row["injury_penalty"] == 0.1
    assert row["features"]["return_timeline_penalty"] == 0.03


def _config() -> dict[str, object]:
    return load_injury_config(repository_root() / "config/injury-risk.yaml")


def _single(*events: dict[str, object]) -> dict[str, object]:
    return score_injury_events(events, AS_OF, _config())[0]


def _event(
    status: str,
    event_type: str,
    start: str,
    *,
    end: str | None = None,
    games_missed: int | None = None,
    expected_return: str | None = None,
    ir_eligible: bool | None = None,
) -> dict[str, object]:
    return {
        "canonical_player_id": PLAYER,
        "event_type": event_type,
        "status": status,
        "start_date": start,
        "end_date": end,
        "games_missed": games_missed,
        "expected_return_date": expected_return,
        "ir_eligible": ir_eligible,
        "description": "left ankle sprain",
    }
