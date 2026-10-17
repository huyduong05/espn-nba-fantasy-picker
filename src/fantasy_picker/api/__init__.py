"""Local Flask API for prepared draft recommendation artifacts."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, g, jsonify, request
from jsonschema import ValidationError

from fantasy_picker import __version__
from fantasy_picker.contracts import validate
from fantasy_picker.ranking.evaluator import (
    EvaluatorError,
    load_projections,
    load_reference_distribution,
)
from fantasy_picker.ranking.recommender import (
    PreparedRecommendationResources,
    RecommendationError,
    load_injury_assessments,
    load_recommender_config,
    prepare_recommendation_resources,
    recommend_prepared,
)

_EXTENSION_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")
_RESOLVED_STATUSES = {"EXACT_ID", "EXACT_ALIAS", "MANUAL"}
type JsonResponse = Response | tuple[Response, int]


class ApiConfigurationError(ValueError):
    """A server configuration cannot be made safe to run."""


@dataclass(frozen=True)
class ArtifactPaths:
    """The precomputed artifacts required for local inference."""

    projections: Path
    reference: Path
    injury_assessments: Path
    recommender_config: Path


@dataclass(frozen=True)
class InferenceResources:
    """In-memory artifacts used by every recommendation request."""

    projections: list[dict[str, Any]]
    reference: dict[str, Any]
    injury_assessments: dict[str, dict[str, Any]]
    recommender_config: dict[str, Any]
    prepared_recommender: PreparedRecommendationResources
    metadata: dict[str, Any]


def create_app(
    artifact_paths: ArtifactPaths,
    *,
    extension_origin: str | None = None,
) -> Flask:
    """Create a localhost-only API application without making network calls."""
    origin = (
        extension_origin
        if extension_origin is not None
        else os.environ.get("FANTASY_PICKER_EXTENSION_ORIGIN")
    )
    if not isinstance(origin, str) or not _EXTENSION_ORIGIN.fullmatch(origin):
        raise ApiConfigurationError(
            "FANTASY_PICKER_EXTENSION_ORIGIN must be chrome-extension:// followed by a 32-letter ID"
        )

    app = Flask(__name__)
    app.config["FANTASY_PICKER_EXTENSION_ORIGIN"] = origin
    app.config["FANTASY_PICKER_RESOURCES"] = _load_resources(artifact_paths)

    @app.before_request
    def _start_request() -> None:
        g.request_started = time.perf_counter()

    @app.after_request
    def _add_cors_and_log(response: Response) -> Response:
        request_origin = request.headers.get("Origin")
        if request_origin == app.config["FANTASY_PICKER_EXTENSION_ORIGIN"]:
            response.headers["Access-Control-Allow-Origin"] = request_origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Vary"] = "Origin"
        started = getattr(g, "request_started", None)
        latency_ms = round((time.perf_counter() - started) * 1000, 3) if started else 0.0
        _log_event(
            "request_complete",
            method=request.method,
            path=request.path,
            status=response.status_code,
            latency_ms=latency_ms,
        )
        return response

    @app.route("/api/v1/health", methods=["GET"])
    def health() -> JsonResponse:
        resources = _resources(app)
        if resources is None:
            return _unavailable()
        return jsonify({"status": "ready", "service_version": __version__})

    @app.route("/api/v1/metadata", methods=["GET"])
    def metadata() -> JsonResponse:
        resources = _resources(app)
        if resources is None:
            return _unavailable()
        return jsonify(resources.metadata)

    @app.route("/api/v1/recommendations", methods=["OPTIONS"])
    def recommendations_options() -> Response:
        return Response(status=204)

    @app.route("/api/v1/recommendations", methods=["POST"])
    def recommendations() -> JsonResponse:
        resources = _resources(app)
        if resources is None:
            return _unavailable()
        if request.mimetype != "application/json":
            return _error("UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json", 415)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("INVALID_JSON", "Request body must be a JSON object", 400)
        try:
            validate(payload, "draft-state")
        except ValidationError as error:
            return _error(
                "INVALID_REQUEST",
                "Request does not satisfy draft-state v1",
                400,
                [_detail(error)],
            )
        except Exception:
            return _error("INVALID_REQUEST", "Request does not satisfy draft-state v1", 400)

        invalid_roster = _unresolved_indexes(payload.get("user_roster"))
        if invalid_roster:
            return _error(
                "UNRESOLVED_ROSTER_PLAYER",
                "Every roster player must have a resolved identity before scoring",
                422,
                [
                    {"field": f"/user_roster/{index}", "message": "unresolved player identity"}
                    for index in invalid_roster
                ],
            )
        state, excluded_count = _exclude_unresolved_remaining(payload)
        try:
            response = recommend_prepared(state, resources.prepared_recommender)
        except (EvaluatorError, RecommendationError) as error:
            _log_event("recommendation_rejected", code="UNPROCESSABLE_DRAFT_STATE")
            return _error("UNPROCESSABLE_DRAFT_STATE", str(error), 422)
        if excluded_count:
            response["warnings"] = [
                *response["warnings"],
                f"REMAINING_PLAYERS_EXCLUDED:{excluded_count}",
            ]
        return jsonify(response)

    _log_event("service_initialized", ready=app.config["FANTASY_PICKER_RESOURCES"] is not None)
    return app


def _load_resources(paths: ArtifactPaths) -> InferenceResources | None:
    try:
        projections = load_projections(paths.projections)
        reference = load_reference_distribution(paths.reference)
        assessments = load_injury_assessments(paths.injury_assessments)
        config = load_recommender_config(paths.recommender_config)
        prepared_recommender = prepare_recommendation_resources(
            projections, reference, assessments, config
        )
    except (EvaluatorError, RecommendationError, OSError, ValueError) as error:
        _log_event("artifact_load_failed", error_type=type(error).__name__)
        return None
    return InferenceResources(
        projections=projections,
        reference=reference,
        injury_assessments=assessments,
        recommender_config=config,
        prepared_recommender=prepared_recommender,
        metadata={
            "schema_version": "1.0.0",
            "service_version": __version__,
            "model_version": str(config["model_version"]),
            "data_version": str(reference["input_fingerprint"]),
            "reference_model_version": str(reference["model_version"]),
            "artifacts": [_artifact_metadata(name, path) for name, path in vars(paths).items()],
        },
    )


def _artifact_metadata(name: str, path: Path) -> dict[str, str]:
    modified_at = (
        datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat().replace("+00:00", "Z")
    )
    return {"name": name, "modified_at": modified_at}


def _resources(app: Flask) -> InferenceResources | None:
    value = app.config["FANTASY_PICKER_RESOURCES"]
    return value if isinstance(value, InferenceResources) else None


def _unresolved_indexes(records: Any) -> list[int]:
    if not isinstance(records, list):
        return []
    return [
        index
        for index, record in enumerate(records)
        if not isinstance(record, Mapping) or record.get("match_status") not in _RESOLVED_STATUSES
    ]


def _exclude_unresolved_remaining(payload: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    state = copy.deepcopy(dict(payload))
    remaining = state["remaining_players"]
    assert isinstance(remaining, list)
    resolved = [
        record
        for record in remaining
        if isinstance(record, Mapping) and record.get("match_status") in _RESOLVED_STATUSES
    ]
    state["remaining_players"] = resolved
    return state, len(remaining) - len(resolved)


def _detail(error: ValidationError) -> dict[str, str]:
    location = "/" + "/".join(str(part) for part in error.absolute_path)
    return {"field": location if location != "/" else "/", "message": error.message}


def _error(
    code: str, message: str, status: int, details: list[dict[str, str]] | None = None
) -> JsonResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return jsonify(body), status


def _unavailable() -> JsonResponse:
    return _error("SERVICE_UNAVAILABLE", "Prepared inference artifacts are unavailable", 503)


def _log_event(event: str, **fields: Any) -> None:
    logging.getLogger("fantasy_picker.api").info(
        json.dumps({"event": event, **fields}, sort_keys=True)
    )
