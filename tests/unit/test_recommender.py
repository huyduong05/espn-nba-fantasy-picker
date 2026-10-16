from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fantasy_picker.cli import main
from fantasy_picker.contracts import repository_root, validate
from fantasy_picker.ranking.evaluator import CATEGORIES, write_reference_distribution
from fantasy_picker.ranking.recommender import (
    _eligible_slots,
    _intervening_picks,
    _local_ranks,
    _next_pick_distance,
    _scarcity,
    _score_candidates,
    load_recommender_config,
    recommend_with_details,
)


def test_snake_next_pick_distance_handles_directions_and_final_pick() -> None:
    assert _next_pick_distance(_state(draft_slot=1, direction="FORWARD", overall_pick=1)) == 23
    assert _intervening_picks(_state(draft_slot=1, direction="FORWARD", overall_pick=1)) == 22
    assert _next_pick_distance(_state(draft_slot=12, direction="FORWARD", overall_pick=12)) == 1
    assert _next_pick_distance(_state(draft_slot=1, direction="REVERSE", overall_pick=12)) == 1
    assert _next_pick_distance(_state(draft_slot=12, direction="REVERSE", overall_pick=1)) == 23
    assert _next_pick_distance(_state(overall_pick=156)) == 0

    projections, state = _inputs()
    state["overall_pick"] = 156
    _, details = recommend_with_details(
        state, projections, _reference(), _assessments(projections), _config()
    )
    assert all(detail["components"]["replacement_raw"] == 0 for detail in details)
    assert all(detail["components"]["survival_probability"] == 1 for detail in details)


def test_recommendations_are_schema_valid_with_local_category_evidence() -> None:
    projections, state = _inputs()
    response, details = recommend_with_details(
        state, projections, _reference(), _assessments(projections), _config()
    )

    validate(response, "recommendation")
    assert len(response["recommendations"]) == 5
    assert all("components" not in row for row in response["recommendations"])
    assert len(details) == 6
    assert set(details[0]["components"]["category_deltas"]) == set(CATEGORIES)
    assert "survival_probability" in details[0]["components"]


def test_positional_scarcity_uses_currently_unfilled_starter_slots() -> None:
    candidates: list[dict[str, Any]] = [
        {"usable_starter_slots": ["C", "UTIL1"]},
        {"usable_starter_slots": ["UTIL1"]},
        {"usable_starter_slots": ["UTIL1"]},
    ]

    assert _eligible_slots(["PG"], ["PG", "G", "F", "UTIL1"]) == ["PG", "G", "UTIL1"]
    assert _scarcity(candidates[0], candidates, ["C", "UTIL1"]) == 1.0
    assert _scarcity(candidates[1], candidates, ["C", "UTIL1"]) == pytest.approx(1 / 3)


def test_uncertainty_lowers_an_otherwise_equal_local_availability_rank() -> None:
    projections = [_projection(100, "C", value=2), _projection(101, "C", value=2, uncertainty=0.35)]
    evaluations = [{"canonical_player_id": row["canonical_player_id"]} for row in projections]
    by_id = {row["canonical_player_id"]: row for row in projections}

    assert _local_ranks(evaluations, by_id, _reference(), _config()) == {_id(100): 1, _id(101): 2}


def test_missing_assessments_are_excluded_and_injury_penalty_is_applied() -> None:
    projections, state = _inputs()
    assessments = _assessments(projections)
    missing_id = _id(105)
    del assessments[missing_id]
    response, _ = recommend_with_details(state, projections, _reference(), assessments, _config())

    assert response["warnings"] == ["INJURY_ASSESSMENT_MISSING:1"]
    assert missing_id not in {row["canonical_player_id"] for row in response["recommendations"]}

    baseline, _ = recommend_with_details(
        state, projections, _reference(), _assessments(projections), _config()
    )
    penalized = _assessments(projections)
    penalized[_id(104)]["injury_penalty"] = 0.15
    penalized[_id(104)]["reason_codes"] = ["CURRENT_INJURY"]
    adjusted, _ = recommend_with_details(state, projections, _reference(), penalized, _config())
    baseline_score = _score_for(baseline, _id(104))
    adjusted_score = _score_for(adjusted, _id(104))
    assert adjusted_score == pytest.approx(round(baseline_score * 0.85, 3), abs=0.001)


def test_urgent_high_rank_can_beat_a_slightly_stronger_survivor() -> None:
    candidates = [
        _scored_candidate(100, roster_gain=0.0, urgency=0.0),
        _scored_candidate(101, roster_gain=0.51, urgency=0.99),
        _scored_candidate(102, roster_gain=0.52, urgency=0.10),
        _scored_candidate(103, roster_gain=1.0, urgency=1.0),
    ]
    rows = _score_candidates(candidates, _config())
    ranks = {row["canonical_player_id"]: row["rank"] for row in rows}

    assert ranks[_id(101)] < ranks[_id(102)]


def test_ranking_details_are_deterministic_and_ties_use_canonical_id() -> None:
    projections, state = _inputs(value=2)
    for projection in projections:
        if projection["canonical_player_id"] >= _id(100):
            _set_projection_value(projection, 2.0)
            projection["uncertainty_penalty"] = 0.0
    assessments = _assessments(projections)
    first, first_details = recommend_with_details(
        state, projections, _reference(), assessments, _config()
    )
    second, second_details = recommend_with_details(
        state, projections, _reference(), assessments, _config()
    )

    assert first["recommendations"] == second["recommendations"]
    assert first_details == second_details
    assert [row["recommendation"]["canonical_player_id"] for row in first_details] == sorted(
        row["recommendation"]["canonical_player_id"] for row in first_details
    )


def test_cli_writes_public_and_inspection_artifacts(tmp_path: Path) -> None:
    projections, state = _inputs()
    projections_path = tmp_path / "projections.jsonl"
    projections_path.write_text("".join(f"{json.dumps(row)}\n" for row in projections))
    reference_path = tmp_path / "reference.json"
    write_reference_distribution(reference_path, _reference())
    state_path = tmp_path / "draft-state.json"
    state_path.write_text(json.dumps(state))
    injuries_path = tmp_path / "injuries.jsonl"
    injuries_path.write_text(
        "".join(f"{json.dumps(row)}\n" for row in _assessments(projections).values())
    )
    output_path = tmp_path / "recommendations.json"
    details_path = tmp_path / "details.json"

    assert (
        main(
            [
                "ranking",
                "recommend",
                "--projections",
                projections_path.as_posix(),
                "--reference",
                reference_path.as_posix(),
                "--injury-assessments",
                injuries_path.as_posix(),
                "--draft-state",
                state_path.as_posix(),
                "--output",
                output_path.as_posix(),
                "--details-output",
                details_path.as_posix(),
            ]
        )
        == 0
    )
    validate(json.loads(output_path.read_text()), "recommendation")
    assert len(json.loads(details_path.read_text())) == 6


def _inputs(*, value: float = 1.0) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    roster_positions = ["PG", "SG", "SF", "PF", "C", "PG", "SF", "PG", "SG"]
    roster = [
        _projection(index, position, value=value) for index, position in enumerate(roster_positions)
    ]
    candidates = [
        _projection(index, "C", value=value + (index - 99) / 5, uncertainty=(index - 100) / 100)
        for index in range(100, 106)
    ]
    state = _state(
        roster=[
            _draft_player(row, position)
            for row, position in zip(roster, roster_positions, strict=True)
        ],
        remaining=[_draft_player(row, "C") for row in candidates],
    )
    return [*roster, *candidates], state


def _state(
    *,
    roster: list[dict[str, Any]] | None = None,
    remaining: list[dict[str, Any]] | None = None,
    draft_slot: int = 1,
    direction: str = "FORWARD",
    overall_pick: int = 25,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "league_config_version": "1.0.0",
        "round": 3,
        "overall_pick": overall_pick,
        "draft_slot": draft_slot,
        "direction": direction,
        "user_roster": [] if roster is None else roster,
        "remaining_players": [] if remaining is None else remaining,
        "manual_overrides": {"added_player_names": [], "removed_player_names": []},
    }


def _reference() -> dict[str, Any]:
    categories = {}
    for category in CATEGORIES:
        categories[category] = {
            "mean": 0.5 if category in {"FG%", "FT%"} else 10.0,
            "standard_deviation": 0.1 if category in {"FG%", "FT%"} else 5.0,
        }
    return {
        "schema_version": "1.0.0",
        "model_version": "phase_6_roster_evaluator_v1",
        "configuration": {
            "schema_version": "1.0.0",
            "model_version": "phase_6_roster_evaluator_v1",
            "team_count": 12,
            "roster_size": 13,
            "starter_count": 10,
            "top_player_count": 156,
            "simulations": 12,
            "seed": 1,
            "optimization_passes": 1,
        },
        "input_fingerprint": "fixture",
        "player_pool_count": 156,
        "reference_roster_count": 12,
        "categories": categories,
    }


def _projection(
    index: int, position: str, *, value: float, uncertainty: float = 0.0
) -> dict[str, Any]:
    del position
    return {
        "canonical_player_id": _id(index),
        "pts": value,
        "reb": value,
        "ast": value,
        "stl": value,
        "blk": value,
        "three_pm": value,
        "turnovers": value,
        "fgm": value,
        "fga": value * 2,
        "ftm": value,
        "fta": value * 2,
        "uncertainty_penalty": uncertainty,
    }


def _draft_player(projection: dict[str, Any], position: str) -> dict[str, Any]:
    return {
        "canonical_player_id": projection["canonical_player_id"],
        "display_name": f"Player {projection['canonical_player_id']}",
        "positions": [position],
        "match_status": "EXACT_ID",
    }


def _assessments(projections: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        row["canonical_player_id"]: {
            "canonical_player_id": row["canonical_player_id"],
            "injury_penalty": 0.0,
            "reason_codes": ["NO_INJURY_DATA"],
            "data_status": "NO_INJURY_DATA",
        }
        for row in projections
    }


def _score_for(response: dict[str, Any], player_id: str) -> float:
    return float(
        next(
            row["score"]
            for row in response["recommendations"]
            if row["canonical_player_id"] == player_id
        )
    )


def _set_projection_value(projection: dict[str, Any], value: float) -> None:
    for field in ("pts", "reb", "ast", "stl", "blk", "three_pm", "turnovers", "fgm", "ftm"):
        projection[field] = value
    projection["fga"] = value * 2
    projection["fta"] = value * 2


def _scored_candidate(index: int, *, roster_gain: float, urgency: float) -> dict[str, Any]:
    deltas = {category: {"win_gain": roster_gain / len(CATEGORIES)} for category in CATEGORIES}
    return {
        "evaluation": {
            "canonical_player_id": _id(index),
            "display_name": f"Player {index}",
            "positions": ["C"],
            "category_win_gain": roster_gain,
            "category_deltas": deltas,
            "reason_codes": ["ROSTER_FIT"],
            "starter_status": "STARTER",
        },
        "projection": {"uncertainty_penalty": 0.0},
        "assessment": {"injury_penalty": 0.0, "reason_codes": ["NO_INJURY_DATA"]},
        "local_rank": index,
        "intervening_picks": 22,
        "roster_gain_raw": roster_gain,
        "survival_probability": 1.0 - urgency,
        "next_pick_urgency_raw": urgency,
        "certainty_raw": 1.0,
        "scarcity_raw": 0.5,
        "replacement_raw": 0.5,
        "usable_starter_slots": ["UTIL1"],
    }


def _config() -> dict[str, Any]:
    return load_recommender_config(repository_root() / "config/recommendation-engine.yaml")


def _id(index: int) -> str:
    return f"plr_{index:032x}"
