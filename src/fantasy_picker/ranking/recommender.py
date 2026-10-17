"""Phase 7 deterministic greedy draft recommendations built from local artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml

from fantasy_picker.contracts import validate
from fantasy_picker.ranking.evaluator import CATEGORIES, EvaluatorError, evaluate_candidates

RECOMMENDER_MODEL_VERSION = "phase_7_draft_recommendation_v1"
_REQUIRED_CONFIG = {
    "schema_version",
    "model_version",
    "top_n",
    "weights",
    "survival_logistic_scale",
    "likely_survival_probability",
    "maximum_uncertainty_penalty",
}
_REQUIRED_PROJECTION_FIELDS = {
    "canonical_player_id",
    "pts",
    "reb",
    "ast",
    "stl",
    "blk",
    "three_pm",
    "turnovers",
    "fgm",
    "fga",
    "ftm",
    "fta",
    "uncertainty_penalty",
}
_COUNTING_FIELDS = {
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "3PM": "three_pm",
    "TO": "turnovers",
}
_STARTER_SLOTS = ("PG", "SG", "SF", "PF", "C", "G", "F", "UTIL1", "UTIL2", "UTIL3")


class RecommendationError(RuntimeError):
    """A missing or invalid local recommendation input."""


@dataclass(frozen=True)
class PreparedRecommendationResources:
    """Draft-invariant recommendation inputs prepared once at API startup."""

    projections: Sequence[Mapping[str, Any]]
    reference: Mapping[str, Any]
    injury_assessments: Mapping[str, Mapping[str, Any]]
    config: Mapping[str, Any]
    projection_by_id: Mapping[str, Mapping[str, Any]]
    category_values_by_id: Mapping[str, Mapping[str, float]]
    data_version: str


def load_recommender_config(path: Path) -> dict[str, Any]:
    """Load the versioned local scoring weights and survival calibration."""
    if not path.is_file():
        raise RecommendationError(f"Missing recommendation-engine configuration: {path}")
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise RecommendationError("Recommendation-engine configuration must be a mapping")
    config = cast(dict[str, Any], value)
    _validate_config(config)
    return config


def load_injury_assessments(path: Path) -> dict[str, dict[str, Any]]:
    """Load Phase 5 assessments keyed by canonical player ID."""
    if not path.is_file():
        raise RecommendationError(f"Missing injury-assessment artifact: {path}")
    assessments: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise RecommendationError(f"Invalid JSON in {path} line {line_number}") from error
        if not isinstance(row, dict):
            raise RecommendationError(f"Expected object in {path} line {line_number}")
        player_id = row.get("canonical_player_id")
        penalty = row.get("injury_penalty")
        reasons = row.get("reason_codes")
        if not isinstance(player_id, str) or player_id in assessments:
            raise RecommendationError(
                f"Invalid or duplicate injury assessment in {path} line {line_number}"
            )
        if not isinstance(penalty, (int, float)) or not 0 <= float(penalty) <= 0.15:
            raise RecommendationError(f"Invalid injury penalty in {path} line {line_number}")
        if not isinstance(reasons, list) or not all(isinstance(reason, str) for reason in reasons):
            raise RecommendationError(f"Invalid injury reason codes in {path} line {line_number}")
        assessments[player_id] = cast(dict[str, Any], row)
    return assessments


def recommend(
    draft_state: Mapping[str, Any],
    projections: Sequence[Mapping[str, Any]],
    reference: Mapping[str, Any],
    injury_assessments: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the public, schema-valid top-five recommendation response."""
    response, _ = recommend_with_details(
        draft_state, projections, reference, injury_assessments, config
    )
    return response


def recommend_with_details(
    draft_state: Mapping[str, Any],
    projections: Sequence[Mapping[str, Any]],
    reference: Mapping[str, Any],
    injury_assessments: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return the public response plus local-only raw scoring details."""
    return recommend_prepared_with_details(
        draft_state,
        prepare_recommendation_resources(projections, reference, injury_assessments, config),
    )


def prepare_recommendation_resources(
    projections: Sequence[Mapping[str, Any]],
    reference: Mapping[str, Any],
    injury_assessments: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
) -> PreparedRecommendationResources:
    """Validate and cache values that cannot change during a draft request."""
    _validate_config(config)
    projection_by_id = _projection_index(projections)
    category_values_by_id = {
        player_id: _projection_category_values(projection)
        for player_id, projection in projection_by_id.items()
    }
    return PreparedRecommendationResources(
        projections=projections,
        reference=reference,
        injury_assessments=injury_assessments,
        config=config,
        projection_by_id=projection_by_id,
        category_values_by_id=category_values_by_id,
        data_version=_data_version(projections, reference, injury_assessments),
    )


def recommend_prepared(
    draft_state: Mapping[str, Any], resources: PreparedRecommendationResources
) -> dict[str, Any]:
    """Score a draft state against startup-prepared immutable resources."""
    response, _ = recommend_prepared_with_details(draft_state, resources)
    return response


def recommend_prepared_with_details(
    draft_state: Mapping[str, Any], resources: PreparedRecommendationResources
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return recommendations without rebuilding static artifact indexes."""
    started = time.perf_counter()
    try:
        evaluations = evaluate_candidates(
            draft_state,
            resources.projections,
            resources.reference,
            projection_by_id=resources.projection_by_id,
        )
    except EvaluatorError as error:
        raise RecommendationError(str(error)) from error
    if not evaluations:
        raise RecommendationError("Draft state has no resolved remaining candidates")

    local_ranks = _local_ranks(
        evaluations,
        resources.projection_by_id,
        resources.reference,
        resources.config,
        category_values_by_id=resources.category_values_by_id,
    )
    next_pick_distance = _next_pick_distance(draft_state)
    intervening_picks = _intervening_picks(draft_state)
    candidates: list[dict[str, Any]] = []
    missing_injury_count = 0
    for evaluation in evaluations:
        player_id = cast(str, evaluation["canonical_player_id"])
        assessment = resources.injury_assessments.get(player_id)
        if assessment is None:
            missing_injury_count += 1
            continue
        candidates.append(
            {
                "evaluation": evaluation,
                "projection": resources.projection_by_id[player_id],
                "assessment": assessment,
                "local_rank": local_ranks[player_id],
            }
        )
    if not candidates:
        raise RecommendationError("No remaining candidates have Phase 5 injury assessments")

    unfilled_starter_slots = _unfilled_starter_slots(evaluations)
    _attach_raw_components(candidates, intervening_picks, unfilled_starter_slots, resources.config)
    _attach_replacement_components(candidates, intervening_picks, resources.config)
    scored = _score_candidates(candidates, resources.config)
    public_rows = [_public_recommendation(row) for row in scored]
    response = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "data_version": resources.data_version,
        "model_version": RECOMMENDER_MODEL_VERSION,
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "recommendations": public_rows[: int(resources.config["top_n"])],
        "warnings": (
            [f"INJURY_ASSESSMENT_MISSING:{missing_injury_count}"] if missing_injury_count else []
        ),
    }
    try:
        validate(response, "recommendation")
    except Exception as error:
        raise RecommendationError(
            f"Generated response did not meet recommendation contract: {error}"
        ) from error
    details = [
        {
            "recommendation": _public_recommendation(row),
            "components": row["components"],
            "next_pick_distance": next_pick_distance,
        }
        for row in scored
    ]
    return response, details


def write_recommendations(path: Path, response: Mapping[str, Any]) -> None:
    """Persist a Phase 7 response for local inspection or later API loading."""
    try:
        validate(dict(response), "recommendation")
    except Exception as error:
        raise RecommendationError(f"Invalid recommendation response: {error}") from error
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(response), indent=2, sort_keys=True) + "\n")


def write_recommendation_details(path: Path, details: Sequence[Mapping[str, Any]]) -> None:
    """Persist local-only component evidence without extending the public schema."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(details), indent=2, sort_keys=True) + "\n")


def _projection_index(projections: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in projections:
        player_id = row.get("canonical_player_id")
        if not isinstance(player_id, str) or player_id in result:
            raise RecommendationError(
                "Projection artifact has an invalid or duplicate canonical_player_id"
            )
        missing = _REQUIRED_PROJECTION_FIELDS.difference(row)
        if missing:
            raise RecommendationError(f"Projection {player_id} missing {sorted(missing)}")
        result[player_id] = row
    return result


def _local_ranks(
    evaluations: Sequence[Mapping[str, Any]],
    projections: Mapping[str, Mapping[str, Any]],
    reference: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    category_values_by_id: Mapping[str, Mapping[str, float]] | None = None,
) -> dict[str, int]:
    category_reference = cast(Mapping[str, Any], reference["categories"])
    maximum_uncertainty = float(config["maximum_uncertainty_penalty"])
    scores = []
    for evaluation in evaluations:
        player_id = cast(str, evaluation["canonical_player_id"])
        values = (
            category_values_by_id[player_id]
            if category_values_by_id is not None
            else _projection_category_values(projections[player_id])
        )
        composite = sum(
            (float(category_reference[category]["mean"]) - values[category])
            / float(category_reference[category]["standard_deviation"])
            if category == "TO"
            else (values[category] - float(category_reference[category]["mean"]))
            / float(category_reference[category]["standard_deviation"])
            for category in CATEGORIES
        )
        uncertainty = min(
            max(float(projections[player_id]["uncertainty_penalty"]), 0.0), maximum_uncertainty
        )
        availability_score = composite - uncertainty * len(CATEGORIES)
        scores.append((-availability_score, player_id))
    return {player_id: rank for rank, (_, player_id) in enumerate(sorted(scores), start=1)}


def _projection_category_values(projection: Mapping[str, Any]) -> dict[str, float]:
    values = {category: float(projection[field]) for category, field in _COUNTING_FIELDS.items()}
    fga = float(projection["fga"])
    fta = float(projection["fta"])
    values["FG%"] = float(projection["fgm"]) / fga if fga else 0.0
    values["FT%"] = float(projection["ftm"]) / fta if fta else 0.0
    return values


def _next_pick_distance(draft_state: Mapping[str, Any]) -> int:
    overall_pick = _integer(draft_state, "overall_pick")
    draft_slot = _integer(draft_state, "draft_slot")
    direction = draft_state.get("direction")
    if overall_pick >= 156:
        return 0
    if direction == "FORWARD":
        distance = 2 * (12 - draft_slot) + 1
    elif direction == "REVERSE":
        distance = 2 * (draft_slot - 1) + 1
    else:
        raise RecommendationError("Draft state direction must be FORWARD or REVERSE")
    return distance if overall_pick + distance <= 156 else 0


def _intervening_picks(draft_state: Mapping[str, Any]) -> int:
    """Return opponent selections before the next personal pick, if one remains."""
    distance = _next_pick_distance(draft_state)
    return max(0, distance - 1)


def _attach_raw_components(
    candidates: list[dict[str, Any]],
    intervening_picks: int,
    unfilled_starter_slots: Sequence[str],
    config: Mapping[str, Any],
) -> None:
    scale = float(config["survival_logistic_scale"])
    maximum_uncertainty = float(config["maximum_uncertainty_penalty"])
    for candidate in candidates:
        rank = int(candidate["local_rank"])
        survival = (
            1.0 if intervening_picks == 0 else _sigmoid((rank - (intervening_picks + 1)) / scale)
        )
        projection = cast(Mapping[str, Any], candidate["projection"])
        candidate["intervening_picks"] = intervening_picks
        candidate["roster_gain_raw"] = float(candidate["evaluation"]["category_win_gain"])
        candidate["survival_probability"] = survival
        candidate["next_pick_urgency_raw"] = 0.0 if intervening_picks == 0 else 1.0 - survival
        candidate["certainty_raw"] = (
            1.0
            - min(max(float(projection["uncertainty_penalty"]), 0.0), maximum_uncertainty)
            / maximum_uncertainty
        )
        positions = cast(list[str], candidate["evaluation"]["positions"])
        candidate["usable_starter_slots"] = _eligible_slots(positions, unfilled_starter_slots)
    for candidate in candidates:
        candidate["scarcity_raw"] = _scarcity(candidate, candidates, unfilled_starter_slots)


def _attach_replacement_components(
    candidates: list[dict[str, Any]], intervening_picks: int, config: Mapping[str, Any]
) -> None:
    if intervening_picks == 0:
        for candidate in candidates:
            candidate["replacement_raw"] = 0.0
        return
    threshold = float(config["likely_survival_probability"])
    for candidate in candidates:
        usable_slots = set(cast(list[str], candidate["usable_starter_slots"]))
        alternatives = [
            float(other["roster_gain_raw"])
            for other in candidates
            if other is not candidate
            and float(other["survival_probability"]) >= threshold
            and usable_slots.intersection(set(cast(list[str], other["usable_starter_slots"])))
        ]
        candidate["replacement_raw"] = max(
            0.0, float(candidate["roster_gain_raw"]) - max(alternatives, default=0.0)
        )


def _unfilled_starter_slots(evaluations: Sequence[Mapping[str, Any]]) -> list[str]:
    """Find current roster starter slots with no Phase 6 lineup assignment."""
    first_evaluation = evaluations[0]
    assignments = cast(
        Sequence[Mapping[str, Any]], first_evaluation["before"]["lineup"]["slot_assignments"]
    )
    filled = {assignment["slot"] for assignment in assignments}
    return [slot for slot in _STARTER_SLOTS if slot not in filled]


def _eligible_slots(positions: Sequence[str], slots: Sequence[str]) -> list[str]:
    """Return canonical starter slots a player can fill from NBA position eligibility."""
    position_set = set(positions)
    eligible = []
    for slot in slots:
        can_fill = (
            slot in position_set
            or (slot == "G" and bool(position_set & {"PG", "SG"}))
            or (slot == "F" and bool(position_set & {"SF", "PF"}))
            or slot.startswith("UTIL")
        )
        if can_fill:
            eligible.append(slot)
    return eligible


def _scarcity(
    candidate: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    unfilled_starter_slots: Sequence[str],
) -> float:
    usable_slots = cast(list[str], candidate["usable_starter_slots"])
    if not usable_slots:
        return 0.0
    supply_by_slot = {
        slot: sum(slot in cast(list[str], other["usable_starter_slots"]) for other in candidates)
        for slot in unfilled_starter_slots
    }
    return max(1.0 / supply_by_slot[slot] for slot in usable_slots if supply_by_slot[slot])


def _score_candidates(
    candidates: list[dict[str, Any]], config: Mapping[str, Any]
) -> list[dict[str, Any]]:
    roster_gain = _normalize(candidates, "roster_gain_raw")
    urgency = _normalize(candidates, "next_pick_urgency_raw")
    certainty = _normalize(candidates, "certainty_raw")
    replacement = _normalize(candidates, "replacement_raw")
    scarcity = _normalize(candidates, "scarcity_raw")
    weights = cast(Mapping[str, Any], config["weights"])
    scored = []
    for index, candidate in enumerate(candidates):
        context = (replacement[index] + scarcity[index]) / 2.0
        pre_injury = (
            float(weights["roster_gain"]) * roster_gain[index]
            + float(weights["next_pick_urgency"]) * urgency[index]
            + float(weights["scarcity_replacement"]) * context
            + float(weights["certainty"]) * certainty[index]
        )
        assessment = cast(Mapping[str, Any], candidate["assessment"])
        injury_penalty = float(assessment["injury_penalty"])
        evaluation = cast(Mapping[str, Any], candidate["evaluation"])
        player_id = cast(str, evaluation["canonical_player_id"])
        deltas = cast(Mapping[str, Any], evaluation["category_deltas"])
        strong_categories = [
            category
            for category, _ in sorted(
                (
                    (category, float(cast(Mapping[str, Any], deltas[category])["win_gain"]))
                    for category in CATEGORIES
                    if float(cast(Mapping[str, Any], deltas[category])["win_gain"]) > 0
                ),
                key=lambda item: (-item[1], item[0]),
            )[:3]
        ]
        score = max(0.0, min(10.0, 10.0 * pre_injury * (1.0 - injury_penalty)))
        scored.append(
            {
                "canonical_player_id": player_id,
                "display_name": evaluation["display_name"],
                "score": round(score, 3),
                "strong_categories": strong_categories,
                "category_win_gain": round(float(evaluation["category_win_gain"]), 6),
                "injury_penalty_pct": round(injury_penalty * 100, 3),
                "positions": evaluation["positions"],
                "reason_codes": _reason_codes(
                    candidate, assessment, scarcity[index], urgency[index]
                ),
                "components": {
                    "local_rank": candidate["local_rank"],
                    "intervening_picks": candidate["intervening_picks"],
                    "survival_probability": round(float(candidate["survival_probability"]), 6),
                    "roster_gain_raw": round(float(candidate["roster_gain_raw"]), 6),
                    "next_pick_urgency_raw": round(float(candidate["next_pick_urgency_raw"]), 6),
                    "replacement_raw": round(float(candidate["replacement_raw"]), 6),
                    "scarcity_raw": round(float(candidate["scarcity_raw"]), 6),
                    "certainty_raw": round(float(candidate["certainty_raw"]), 6),
                    "uncertainty_penalty": float(
                        cast(Mapping[str, Any], candidate["projection"])["uncertainty_penalty"]
                    ),
                    "injury_penalty": injury_penalty,
                    "pre_injury_score": round(pre_injury * 10.0, 6),
                    "post_injury_score": round(score, 6),
                    "normalized_components": {
                        "roster_gain": round(roster_gain[index], 6),
                        "next_pick_urgency": round(urgency[index], 6),
                        "scarcity_replacement": round(context, 6),
                        "certainty": round(certainty[index], 6),
                    },
                    "starter_status": evaluation["starter_status"],
                    "usable_starter_slots": candidate["usable_starter_slots"],
                    "category_deltas": evaluation["category_deltas"],
                },
            }
        )
    ordered = sorted(
        scored,
        key=lambda row: (-float(row["score"]), row["canonical_player_id"]),
    )
    for rank, row in enumerate(ordered, start=1):
        row["rank"] = rank
    return ordered


def _public_recommendation(row: Mapping[str, Any]) -> dict[str, Any]:
    """Keep local scoring evidence out of the stable public recommendation schema."""
    fields = (
        "rank",
        "canonical_player_id",
        "display_name",
        "score",
        "strong_categories",
        "category_win_gain",
        "injury_penalty_pct",
        "positions",
        "reason_codes",
    )
    return {field: row[field] for field in fields}


def _normalize(candidates: Sequence[Mapping[str, Any]], field: str) -> list[float]:
    values = [float(candidate[field]) for candidate in candidates]
    minimum, maximum = min(values), max(values)
    if math.isclose(minimum, maximum):
        return [0.5] * len(values)
    return [(value - minimum) / (maximum - minimum) for value in values]


def _reason_codes(
    candidate: Mapping[str, Any],
    assessment: Mapping[str, Any],
    normalized_scarcity: float,
    normalized_urgency: float,
) -> list[str]:
    evaluation = cast(Mapping[str, Any], candidate["evaluation"])
    reasons = set(cast(list[str], evaluation["reason_codes"]))
    reasons.update(cast(list[str], assessment["reason_codes"]))
    if normalized_urgency >= 0.75:
        reasons.add("NEXT_PICK_RISK")
    if normalized_scarcity >= 0.75:
        reasons.add("POSITION_SCARCITY")
    if float(assessment["injury_penalty"]) > 0:
        reasons.add("INJURY_ADJUSTED")
    return sorted(reasons)


def _data_version(
    projections: Sequence[Mapping[str, Any]],
    reference: Mapping[str, Any],
    assessments: Mapping[str, Mapping[str, Any]],
) -> str:
    payload = {
        "projections": list(projections),
        "reference": dict(reference),
        "assessments": dict(assessments),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    return f"phase7-{digest[:16]}"


def _integer(record: Mapping[str, Any], field: str) -> int:
    value = record.get(field)
    if not isinstance(value, int):
        raise RecommendationError(f"Draft state {field} must be an integer")
    return value


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


def _validate_config(config: Mapping[str, Any]) -> None:
    missing = _REQUIRED_CONFIG.difference(config)
    if missing:
        raise RecommendationError(f"Recommendation-engine config missing {sorted(missing)}")
    if config["model_version"] != RECOMMENDER_MODEL_VERSION:
        raise RecommendationError("Unexpected recommendation-engine model version")
    if int(config["top_n"]) != 5:
        raise RecommendationError("Phase 7 top_n must be five")
    weights = config["weights"]
    expected = {"roster_gain", "next_pick_urgency", "scarcity_replacement", "certainty"}
    if not isinstance(weights, Mapping) or set(weights) != expected:
        raise RecommendationError("Recommendation-engine weights are incomplete")
    if not math.isclose(sum(float(value) for value in weights.values()), 1.0):
        raise RecommendationError("Recommendation-engine weights must sum to one")
    if float(config["survival_logistic_scale"]) <= 0:
        raise RecommendationError("survival_logistic_scale must be positive")
    if not 0 < float(config["likely_survival_probability"]) < 1:
        raise RecommendationError("likely_survival_probability must be between zero and one")
    if not 0 < float(config["maximum_uncertainty_penalty"]) <= 1:
        raise RecommendationError("maximum_uncertainty_penalty must be in (0, 1]")
