from __future__ import annotations

import json
from pathlib import Path

import pytest

from fantasy_picker.cli import main
from fantasy_picker.extension_index import PlayerIndexError, build_player_index


def test_index_joins_active_projection_players_aliases_and_positions() -> None:
    index = build_player_index(
        [
            {
                "canonical_player_id": _id(1),
                "display_name": "José Player",
                "aliases": ["Jose Player", "J. Player"],
            },
            {
                "canonical_player_id": _id(2),
                "display_name": "Inactive Player",
                "aliases": [],
            },
        ],
        [
            {"canonical_player_id": _id(1), "positions": ["SG", "PG"]},
            {"canonical_player_id": _id(2), "positions": ["C"]},
        ],
        [_id(1)],
        generated_at="2026-10-17T12:00:00Z",
    )

    assert index["index_version"] == "phase_9_player_index_v1"
    assert index["players"] == [
        {
            "canonical_player_id": _id(1),
            "display_name": "José Player",
            "aliases": ["J. Player", "Jose Player"],
            "positions": ["PG", "SG"],
        }
    ]


def test_index_rejects_missing_or_invalid_active_inputs() -> None:
    with pytest.raises(PlayerIndexError, match="missing player records"):
        build_player_index([], [], [_id(1)], generated_at="2026-10-17T12:00:00Z")

    with pytest.raises(PlayerIndexError, match="invalid positions"):
        build_player_index(
            [{"canonical_player_id": _id(1), "display_name": "Player", "aliases": []}],
            [{"canonical_player_id": _id(1), "positions": ["QB"]}],
            [_id(1)],
            generated_at="2026-10-17T12:00:00Z",
        )


def test_cli_writes_a_generated_player_index(tmp_path: Path) -> None:
    players = tmp_path / "players.jsonl"
    eligibility = tmp_path / "eligibility.jsonl"
    projections = tmp_path / "projections.jsonl"
    output = tmp_path / "player-index.json"
    players.write_text(json.dumps(_player(_id(1))) + "\n")
    eligibility.write_text(json.dumps({"canonical_player_id": _id(1), "positions": ["C"]}) + "\n")
    projections.write_text(json.dumps(_projection(_id(1))) + "\n")

    assert (
        main(
            [
                "extension",
                "build-player-index",
                "--players",
                players.as_posix(),
                "--eligibility",
                eligibility.as_posix(),
                "--projections",
                projections.as_posix(),
                "--output",
                output.as_posix(),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text())["players"][0]["canonical_player_id"] == _id(1)


def _player(player_id: str) -> dict[str, object]:
    return {"canonical_player_id": player_id, "display_name": "Player", "aliases": []}


def _projection(player_id: str) -> dict[str, object]:
    return {
        "canonical_player_id": player_id,
        "pts": 1.0,
        "reb": 1.0,
        "ast": 1.0,
        "stl": 1.0,
        "blk": 1.0,
        "three_pm": 1.0,
        "turnovers": 1.0,
        "fgm": 1.0,
        "fga": 1.0,
        "ftm": 1.0,
        "fta": 1.0,
    }


def _id(number: int) -> str:
    return f"plr_{number:032x}"
