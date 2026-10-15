from __future__ import annotations

from fantasy_picker.models.projections import TARGET_STATS, ProjectionBundle
from fantasy_picker.models.rookies import build_phase4_projections


def test_phase4_translates_college_and_prefers_nba_evidence() -> None:
    config = _config()
    rows = build_phase4_projections(
        _records(), _players(), _eligibility(), _unresolved(), _bundle(), config
    )
    by_id = {row["canonical_player_id"]: row for row in rows}

    rookie = by_id["rookie_two"]
    second_year = by_id["second_year"]
    assert rookie["pts"] == 10.0  # 0.5 * 20 college PTS
    assert rookie["nba_weight"] == 0.0
    assert rookie["uncertainty_penalty"] == 0.20
    assert second_year["pts"] == 11.5  # 75% NBA 12 PTS + 25% translated college 10 PTS
    assert second_year["nba_weight"] == 0.75
    assert "TRANSLATED_NON_NBA_HISTORY" in second_year["reason_codes"]


def test_phase4_penalty_is_monotonic_and_flags_unsupported_international() -> None:
    rows = build_phase4_projections(
        _records(), _players(), _eligibility(), _unresolved(), _bundle(), _config()
    )
    by_id = {row["canonical_player_id"]: row for row in rows}

    assert by_id["rookie_two"]["uncertainty_penalty"] < by_id["rookie_one"]["uncertainty_penalty"]
    assert by_id["rookie_one"]["uncertainty_penalty"] < by_id["rookie_none"]["uncertainty_penalty"]
    assert by_id["international_gap"]["uncertainty_penalty"] == 0.35
    assert "UNSUPPORTED_INTERNATIONAL_HISTORY" in by_id["international_gap"]["reason_codes"]


def _bundle() -> ProjectionBundle:
    return ProjectionBundle(
        feature_names=[],
        selections={stat: "latest_season" for stat in TARGET_STATS},
        models={},
        training_max_target_year=2025,
    )


def _config() -> dict[str, object]:
    return {
        "translation_multiplier": 0.5,
        "non_nba_seasons": 2,
        "nba_weights": {"second_year": 0.75, "established": 0.9},
        "uncertainty_penalties": {
            "rookie_base": 0.30,
            "rookie_per_non_nba_season": 0.05,
            "second_year_base": 0.12,
            "second_year_per_non_nba_season": 0.02,
            "established": 0.0,
            "unsupported_international": 0.35,
        },
    }


def _records() -> list[dict[str, object]]:
    return [
        _record("rookie_two", "COLLEGE", 2023, 20),
        _record("rookie_two", "COLLEGE", 2024, 20),
        _record("rookie_one", "COLLEGE", 2024, 20),
        _record("second_year", "NBA", 2025, 12),
        _record("second_year", "COLLEGE", 2024, 20),
    ]


def _record(player_id: str, league: str, year: int, pts: float) -> dict[str, object]:
    row: dict[str, object] = {
        "canonical_player_id": player_id,
        "league_type": league,
        "season_start_year": year,
        "source_record_id": f"{player_id}-{league}-{year}",
        "games": 30,
        "minutes": 30.0,
    }
    for stat in TARGET_STATS:
        row[stat] = pts if stat == "pts" else 1.0
    return row


def _players() -> list[dict[str, object]]:
    return [
        {"canonical_player_id": player, "source_ids": {"nba_stats": external}}
        for player, external in [
            ("rookie_two", "1"),
            ("rookie_one", "2"),
            ("rookie_none", "3"),
            ("international_gap", "4"),
            ("second_year", "5"),
        ]
    ]


def _eligibility() -> list[dict[str, object]]:
    return [
        {"canonical_player_id": player}
        for player in [
            "rookie_two",
            "rookie_one",
            "rookie_none",
            "international_gap",
            "second_year",
        ]
    ]


def _unresolved() -> dict[str, object]:
    return {"records": [{"status": "INTERNATIONAL_LOW_INFORMATION", "external_player_id": "4"}]}
