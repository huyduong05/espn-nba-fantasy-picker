from __future__ import annotations

import json
from pathlib import Path

import pytest

from fantasy_picker.cli import main
from fantasy_picker.contracts import repository_root
from fantasy_picker.ranking.evaluator import (
    CATEGORIES,
    EvaluatorError,
    build_reference_distribution,
    evaluate_candidates,
    load_evaluator_config,
    load_reference_distribution,
    write_reference_distribution,
)


def test_percentages_use_aggregate_makes_and_attempts() -> None:
    projections, state = _state_with_candidates(
        [_projection(100, "C", fgm=9, fga=10, ftm=9, fta=10)]
    )
    result = evaluate_candidates(state, projections, _reference())[0]

    assert result["starter_status"] == "STARTER"
    assert result["after"]["categories"]["FG%"]["value"] == pytest.approx(18 / 28)
    assert result["after"]["categories"]["FT%"]["value"] == pytest.approx(18 / 28)
    assert result["after"]["categories"]["FG%"]["value"] != pytest.approx(0.54)


def test_lower_turnovers_improve_category_gain() -> None:
    projections, state = _state_with_candidates(
        [
            _projection(100, "C", turnovers=0),
            _projection(101, "C", turnovers=5),
        ]
    )
    results = evaluate_candidates(state, projections, _reference())
    by_id = {row["canonical_player_id"]: row for row in results}

    assert (
        by_id[_id(100)]["category_deltas"]["TO"]["win_gain"]
        > by_id[_id(101)]["category_deltas"]["TO"]["win_gain"]
    )


def test_lineup_uses_positions_and_can_bench_a_candidate() -> None:
    starters = [_projection(index, position, value=5) for index, position in enumerate(_slots())]
    candidate = _projection(100, "C", value=0)
    state = _draft_state(
        [
            _draft_player(row["canonical_player_id"], position)
            for row, position in zip(starters, _slots(), strict=True)
        ],
        [_draft_player(candidate["canonical_player_id"], "C")],
    )

    result = evaluate_candidates(state, [*starters, candidate], _reference())[0]

    assert result["starter_status"] == "BENCH"
    assert "BENCH_NO_IMMEDIATE_CATEGORY_GAIN" in result["reason_codes"]
    slots = {assignment["slot"] for assignment in result["after"]["lineup"]["slot_assignments"]}
    assert slots == {"PG", "SG", "SF", "PF", "C", "G", "F", "UTIL1", "UTIL2", "UTIL3"}


def test_balanced_contribution_beats_single_category_concentration() -> None:
    balanced = _projection(
        100,
        "C",
        pts=1,
        reb=1,
        ast=1,
        stl=1,
        blk=1,
        three_pm=1,
        turnovers=0,
        fgm=1,
        fga=1,
        ftm=1,
        fta=1,
    )
    concentrated = _projection(101, "C", pts=9, turnovers=0)
    projections, state = _state_with_candidates([balanced, concentrated], base_value=0)
    results = evaluate_candidates(state, projections, _reference())
    by_id = {row["canonical_player_id"]: row for row in results}

    assert by_id[_id(100)]["category_win_gain"] > by_id[_id(101)]["category_win_gain"]


def test_reference_artifact_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    config = _config()
    config["simulations"] = 12
    config["optimization_passes"] = 1
    projections = [
        _projection(index, _slots()[index % 10], value=1 + index / 100) for index in range(156)
    ]
    eligibility = [
        {"canonical_player_id": row["canonical_player_id"], "positions": [_slots()[index % 10]]}
        for index, row in enumerate(projections)
    ]

    first = build_reference_distribution(projections, eligibility, config)
    second = build_reference_distribution(projections, eligibility, config)
    output = tmp_path / "reference.json"
    write_reference_distribution(output, first)

    assert first == second
    assert first["reference_roster_count"] == 12
    assert set(first["categories"]) == set(CATEGORIES)
    assert load_reference_distribution(output) == first


def test_rejects_unresolved_draft_players_and_missing_projections() -> None:
    projections, state = _state_with_candidates([_projection(100, "C")])
    state["remaining_players"][0]["match_status"] = "UNRESOLVED"
    with pytest.raises(EvaluatorError, match="unresolved player identity"):
        evaluate_candidates(state, projections, _reference())

    state["remaining_players"][0]["match_status"] = "EXACT_ID"
    with pytest.raises(EvaluatorError, match="Missing projection"):
        evaluate_candidates(state, projections[:-1], _reference())


def test_cli_builds_and_uses_reference_artifact(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (repository_root() / "config/roster-evaluator.yaml")
        .read_text()
        .replace("simulations: 2000", "simulations: 12")
        .replace("optimization_passes: 2", "optimization_passes: 1")
    )
    projections = [
        _projection(index, _slots()[index % 10], value=1 + index / 100) for index in range(156)
    ]
    eligibility = [
        {"canonical_player_id": row["canonical_player_id"], "positions": [_slots()[index % 10]]}
        for index, row in enumerate(projections)
    ]
    projections_path = tmp_path / "projections.jsonl"
    eligibility_path = tmp_path / "eligibility.jsonl"
    projections_path.write_text("".join(f"{json.dumps(row)}\n" for row in projections))
    eligibility_path.write_text("".join(f"{json.dumps(row)}\n" for row in eligibility))
    reference_path = tmp_path / "reference.json"

    assert (
        main(
            [
                "ranking",
                "build-reference",
                "--projections",
                projections_path.as_posix(),
                "--eligibility",
                eligibility_path.as_posix(),
                "--config",
                config_path.as_posix(),
                "--output",
                reference_path.as_posix(),
            ]
        )
        == 0
    )
    state = _draft_state(
        [
            _draft_player(row["canonical_player_id"], position)
            for row, position in zip(projections[:9], _slots()[:9], strict=True)
        ],
        [_draft_player(projections[9]["canonical_player_id"], _slots()[9])],
    )
    state_path = tmp_path / "draft-state.json"
    state_path.write_text(json.dumps(state))
    output_path = tmp_path / "evaluations.json"

    assert load_reference_distribution(reference_path)["reference_roster_count"] == 12
    assert (
        main(
            [
                "ranking",
                "evaluate",
                "--projections",
                projections_path.as_posix(),
                "--reference",
                reference_path.as_posix(),
                "--draft-state",
                state_path.as_posix(),
                "--output",
                output_path.as_posix(),
            ]
        )
        == 0
    )
    assert len(json.loads(output_path.read_text())) == 1


def _reference() -> dict[str, object]:
    categories = {}
    for category in CATEGORIES:
        if category in {"FG%", "FT%"}:
            categories[category] = {"mean": 0.5, "standard_deviation": 0.1}
        elif category == "TO":
            categories[category] = {"mean": 10.0, "standard_deviation": 5.0}
        else:
            categories[category] = {"mean": 10.0, "standard_deviation": 5.0}
    return {
        "schema_version": "1.0.0",
        "model_version": "phase_6_roster_evaluator_v1",
        "configuration": _config(),
        "input_fingerprint": "fixture",
        "player_pool_count": 156,
        "reference_roster_count": 12,
        "categories": categories,
    }


def _config() -> dict[str, object]:
    return load_evaluator_config(repository_root() / "config/roster-evaluator.yaml")


def _state_with_candidates(
    candidates: list[dict[str, object]], *, base_value: float = 1
) -> tuple[list[dict[str, object]], dict[str, object]]:
    base_positions = _slots()[:9]
    base = [
        _projection(index, position, value=base_value)
        for index, position in enumerate(base_positions)
    ]
    state = _draft_state(
        [
            _draft_player(row["canonical_player_id"], position)
            for row, position in zip(base, base_positions, strict=True)
        ],
        [_draft_player(row["canonical_player_id"], "C") for row in candidates],
    )
    return [*base, *candidates], state


def _draft_state(
    roster: list[dict[str, object]], remaining: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "league_config_version": "1.0.0",
        "round": 3,
        "overall_pick": 25,
        "user_roster": roster,
        "remaining_players": remaining,
        "manual_overrides": {"added_player_names": [], "removed_player_names": []},
    }


def _draft_player(player_id: object, position: str) -> dict[str, object]:
    return {
        "canonical_player_id": player_id,
        "display_name": f"Player {player_id}",
        "positions": [position],
        "match_status": "EXACT_ID",
    }


def _projection(
    index: int,
    position: str,
    *,
    value: float = 1,
    pts: float | None = None,
    reb: float | None = None,
    ast: float | None = None,
    stl: float | None = None,
    blk: float | None = None,
    three_pm: float | None = None,
    turnovers: float | None = None,
    fgm: float | None = None,
    fga: float | None = None,
    ftm: float | None = None,
    fta: float | None = None,
) -> dict[str, object]:
    del position
    return {
        "canonical_player_id": _id(index),
        "pts": value if pts is None else pts,
        "reb": value if reb is None else reb,
        "ast": value if ast is None else ast,
        "stl": value if stl is None else stl,
        "blk": value if blk is None else blk,
        "three_pm": value if three_pm is None else three_pm,
        "turnovers": value if turnovers is None else turnovers,
        "fgm": value if fgm is None else fgm,
        "fga": value * 2 if fga is None else fga,
        "ftm": value if ftm is None else ftm,
        "fta": value * 2 if fta is None else fta,
    }


def _slots() -> list[str]:
    return ["PG", "SG", "SF", "PF", "C", "PG", "SF", "PG", "SG", "C"]


def _id(index: int) -> str:
    return f"plr_{index:032x}"
