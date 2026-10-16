from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

import pytest

from fantasy_picker.api import ApiConfigurationError, ArtifactPaths, create_app
from fantasy_picker.contracts import repository_root, validate

_ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


@pytest.fixture
def app(tmp_path: Path):
    root = repository_root()
    projections = tmp_path / "projections.jsonl"
    reference = tmp_path / "reference.json"
    config = tmp_path / "recommendation.yaml"
    injuries = tmp_path / "injuries.jsonl"
    shutil.copy(root / "artifacts/phase4/rookie_adjusted_projections.jsonl", projections)
    shutil.copy(root / "artifacts/phase6/reference_distribution.json", reference)
    shutil.copy(root / "config/recommendation-engine.yaml", config)
    rows = [json.loads(line) for line in projections.read_text().splitlines() if line]
    injuries.write_text(
        "".join(
            json.dumps(
                {
                    "canonical_player_id": row["canonical_player_id"],
                    "injury_penalty": 0.0,
                    "reason_codes": ["NO_INJURY_DATA"],
                    "data_status": "NO_INJURY_DATA",
                }
            )
            + "\n"
            for row in rows
        )
    )
    return create_app(
        ArtifactPaths(projections, reference, injuries, config), extension_origin=_ORIGIN
    )


def test_health_metadata_and_recommendations_use_loaded_artifacts(app: Any) -> None:
    client = app.test_client()

    health = client.get("/api/v1/health")
    metadata = client.get("/api/v1/metadata")
    response = client.post("/api/v1/recommendations", json=_state(app))

    assert health.status_code == 200
    assert health.json == {"status": "ready", "service_version": "0.1.0"}
    assert metadata.status_code == 200
    assert metadata.json["model_version"] == "phase_7_draft_recommendation_v1"
    assert metadata.json["data_version"]
    assert {artifact["name"] for artifact in metadata.json["artifacts"]} == {
        "projections",
        "reference",
        "injury_assessments",
        "recommender_config",
    }
    assert response.status_code == 200
    validate(response.json, "recommendation")
    assert len(response.json["recommendations"]) == 5
    assert response.json["latency_ms"] < 4_000


def test_invalid_requests_and_unresolved_roster_have_actionable_errors(app: Any) -> None:
    client = app.test_client()

    assert client.post("/api/v1/recommendations", data="not json").status_code == 415
    malformed = client.post("/api/v1/recommendations", data="{", content_type="application/json")
    assert malformed.status_code == 400
    assert malformed.json["error"]["code"] == "INVALID_JSON"

    invalid = _state(app)
    invalid["round"] = 0
    invalid_response = client.post("/api/v1/recommendations", json=invalid)
    assert invalid_response.status_code == 400
    assert invalid_response.json["error"]["details"][0]["field"] == "/round"

    unresolved = _state(app)
    unresolved["user_roster"] = [
        {
            "canonical_player_id": None,
            "display_name": "Unresolved roster player",
            "positions": ["PG"],
            "match_status": "UNRESOLVED",
        }
    ]
    unresolved_response = client.post("/api/v1/recommendations", json=unresolved)
    assert unresolved_response.status_code == 422
    assert unresolved_response.json["error"]["code"] == "UNRESOLVED_ROSTER_PLAYER"


def test_unresolved_remaining_players_are_excluded_with_warning(app: Any) -> None:
    state = _state(app)
    state["remaining_players"].append(
        {
            "canonical_player_id": None,
            "display_name": "Unresolved remaining player",
            "positions": [],
            "match_status": "UNRESOLVED",
        }
    )

    response = app.test_client().post("/api/v1/recommendations", json=state)

    assert response.status_code == 200
    assert "REMAINING_PLAYERS_EXCLUDED:1" in response.json["warnings"]


def test_unavailable_artifacts_and_cors_are_restricted(tmp_path: Path) -> None:
    missing = ArtifactPaths(
        tmp_path / "missing-projections.jsonl",
        tmp_path / "missing-reference.json",
        tmp_path / "missing-injuries.jsonl",
        tmp_path / "missing-config.yaml",
    )
    app = create_app(missing, extension_origin=_ORIGIN)
    client = app.test_client()

    assert client.get("/api/v1/health").status_code == 503
    allowed = client.get("/api/v1/health", headers={"Origin": _ORIGIN})
    denied = client.get("/api/v1/health", headers={"Origin": "https://example.test"})
    assert allowed.headers["Access-Control-Allow-Origin"] == _ORIGIN
    assert "Access-Control-Allow-Origin" not in denied.headers
    assert client.options("/api/v1/recommendations", headers={"Origin": _ORIGIN}).status_code == 204


def test_invalid_extension_origin_is_rejected(tmp_path: Path) -> None:
    paths = ArtifactPaths(tmp_path / "a", tmp_path / "b", tmp_path / "c", tmp_path / "d")
    with pytest.raises(ApiConfigurationError):
        create_app(paths, extension_origin="https://example.test")


def test_logs_exclude_player_and_request_content(
    app: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="fantasy_picker.api")
    state = _state(app)
    state["remaining_players"][0]["display_name"] = "Sensitive player name"

    response = app.test_client().post("/api/v1/recommendations", json=state)

    assert response.status_code == 200
    output = "\n".join(record.getMessage() for record in caplog.records)
    assert "Sensitive player name" not in output
    assert "remaining_players" not in output


def _state(app: Any) -> dict[str, Any]:
    projections = app.config["FANTASY_PICKER_RESOURCES"].projections
    remaining = [
        {
            "canonical_player_id": row["canonical_player_id"],
            "display_name": f"Player {index}",
            "positions": ["C"],
            "match_status": "EXACT_ID",
        }
        for index, row in enumerate(projections[:6], start=1)
    ]
    return {
        "schema_version": "1.0.0",
        "league_config_version": "1.0.0",
        "round": 3,
        "overall_pick": 25,
        "draft_slot": 1,
        "direction": "FORWARD",
        "user_roster": [],
        "remaining_players": remaining,
        "manual_overrides": {"added_player_names": [], "removed_player_names": []},
    }
