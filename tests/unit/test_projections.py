from __future__ import annotations

import json
from pathlib import Path

import pytest

from fantasy_picker.models.projections import (
    TARGET_STATS,
    build_examples,
    evaluate,
    load_bundle,
    project,
    save_artifacts,
    train_bundle,
    write_projection_table,
)


def test_features_contain_no_target_season_values() -> None:
    records = _records(players=1)
    examples = build_examples(records)
    first = next(example for example in examples if example.target_year == 2022)

    assert first.features["latest_pts"] == 10.0
    assert first.target["pts"] == 11.0
    assert first.features["experience_seasons"] == 1.0


def test_walk_forward_evaluation_uses_later_seasons_only() -> None:
    evaluation = evaluate(build_examples(_records()))

    assert evaluation["validation_years"] == [2023, 2024]
    assert evaluation["test_year"] == 2025
    assert set(evaluation["per_stat"]) == set(TARGET_STATS)
    assert evaluation["per_stat"]["pts"]["selected"] in {
        "latest_season",
        "minutes_weighted_history",
        "linear",
        "gradient_boosted",
    }


def test_saved_bundle_reproduces_projection_table(tmp_path: Path) -> None:
    records = _records()
    examples = build_examples(records)
    evaluation = evaluate(examples)
    bundle = train_bundle(examples, evaluation)
    stats_path = tmp_path / "season_stats.jsonl"
    stats_path.write_text("".join(json.dumps(record) + "\n" for record in records))
    paths = save_artifacts(tmp_path / "artifacts", bundle, evaluation, stats_path)

    expected = project(records, bundle)
    actual = project(records, load_bundle(paths["bundle"]))
    output = tmp_path / "projections.jsonl"
    write_projection_table(output, actual)

    assert actual == expected
    assert len(output.read_text().splitlines()) == 35
    metadata = json.loads(paths["metadata"].read_text())
    assert metadata["input"]["sha256"]


def test_duplicate_player_season_is_rejected() -> None:
    records = _records(players=1)
    with pytest.raises(Exception, match="Duplicate NBA player-season"):
        build_examples([*records, records[-1]])


def _records(players: int = 35) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for player in range(players):
        for year in range(2021, 2026):
            step = year - 2021
            base = 10.0 + player / 10
            rows.append(
                {
                    "league_type": "NBA",
                    "canonical_player_id": f"plr_{player:032x}",
                    "season_start_year": year,
                    "games": 60 + player % 20,
                    "minutes": 20.0 + player % 15,
                    "pts": base + step,
                    "reb": 3.0 + player / 100 + step / 4,
                    "ast": 2.0 + player / 50 + step / 3,
                    "stl": 0.7 + step / 20,
                    "blk": 0.4 + player / 200,
                    "three_pm": 1.0 + player / 100 + step / 5,
                    "turnovers": 1.0 + player / 100 + step / 10,
                    "fgm": 4.0 + player / 20 + step / 2,
                    "fga": 9.0 + player / 20 + step / 2,
                    "ftm": 2.0 + player / 100 + step / 4,
                    "fta": 2.5 + player / 100 + step / 4,
                }
            )
    return rows
