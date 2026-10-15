"""Leakage-safe baseline and regression projections for Phase 3.

The module deliberately works from the normalized JSONL records rather than a
notebook.  A training row at season ``Y`` contains only records from seasons
before ``Y`` and predicts the player's per-game record in ``Y``.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor  # type: ignore[import-untyped]
from sklearn.linear_model import Ridge  # type: ignore[import-untyped]

TARGET_STATS = (
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
)
MODEL_VERSION = "phase_3_projection_v1"
Selection = Literal["latest_season", "minutes_weighted_history", "linear", "gradient_boosted"]


class ProjectionError(RuntimeError):
    """A model input or artifact error suitable for CLI output."""


@dataclass(frozen=True)
class ProjectionExample:
    canonical_player_id: str
    target_year: int
    features: dict[str, float]
    target: dict[str, float]


@dataclass
class ProjectionBundle:
    feature_names: list[str]
    selections: dict[str, Selection]
    models: dict[str, Any]
    training_max_target_year: int


def load_nba_stats(path: Path) -> list[dict[str, Any]]:
    """Load and validate the NBA subset of normalized season records."""
    if not path.is_file():
        raise ProjectionError(f"Missing normalized season statistics: {path}")
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    nba = [record for record in records if record.get("league_type") == "NBA"]
    if not nba:
        raise ProjectionError("No NBA season records were found")
    required = {"canonical_player_id", "season_start_year", "games", "minutes", *TARGET_STATS}
    for index, record in enumerate(nba, start=1):
        missing = required.difference(record)
        if missing:
            raise ProjectionError(f"NBA record {index} is missing {sorted(missing)}")
    return nba


def build_examples(records: Iterable[dict[str, Any]]) -> list[ProjectionExample]:
    """Build one forward-looking example for every player season with history."""
    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("league_type") == "NBA":
            by_player[cast(str, record["canonical_player_id"])].append(record)

    examples: list[ProjectionExample] = []
    for player_id, player_records in by_player.items():
        ordered = sorted(player_records, key=lambda record: int(record["season_start_year"]))
        seen_years: set[int] = set()
        for index, current in enumerate(ordered):
            year = int(current["season_start_year"])
            if year in seen_years:
                raise ProjectionError(f"Duplicate NBA player-season for {player_id} in {year}")
            seen_years.add(year)
            history = ordered[:index]
            if not history:
                continue
            examples.append(
                ProjectionExample(
                    canonical_player_id=player_id,
                    target_year=year,
                    features=_feature_row(history),
                    target={stat: float(current[stat]) for stat in TARGET_STATS},
                )
            )
    return sorted(examples, key=lambda item: (item.target_year, item.canonical_player_id))


def _feature_row(history: list[dict[str, Any]]) -> dict[str, float]:
    latest = history[-1]
    row: dict[str, float] = {
        "experience_seasons": float(len(history)),
        "latest_games": float(latest["games"]),
        "latest_minutes": float(latest["minutes"]),
        "history_games": float(sum(float(record["games"]) for record in history)),
        "history_total_minutes": float(sum(_weight(record) for record in history)),
    }
    for stat in TARGET_STATS:
        values = [float(record[stat]) for record in history]
        row[f"latest_{stat}"] = values[-1]
        row[f"average_2_{stat}"] = _minutes_weighted(history[-2:], stat)
        row[f"average_3_{stat}"] = _minutes_weighted(history[-3:], stat)
        row[f"history_weighted_{stat}"] = _minutes_weighted(history, stat)
        row[f"trend_{stat}"] = values[-1] - values[-2] if len(values) > 1 else 0.0

    # Past production profiles are interpretable role proxies; no current or
    # future roster information is used.
    row["assist_role"] = _ratio(float(latest["ast"]), float(latest["pts"]) + 1.0)
    row["rebound_role"] = _ratio(float(latest["reb"]), float(latest["pts"]) + 1.0)
    row["rim_role"] = _ratio(float(latest["blk"]), float(latest["reb"]) + 1.0)
    row["perimeter_role"] = _ratio(float(latest["three_pm"]), float(latest["fga"]) + 1.0)
    return row


def _weight(record: dict[str, Any]) -> float:
    return max(0.0, float(record["games"]) * float(record["minutes"]))


def _minutes_weighted(records: list[dict[str, Any]], stat: str) -> float:
    weights = [_weight(record) for record in records]
    total = sum(weights)
    if total == 0:
        return float(sum(float(record[stat]) for record in records) / len(records))
    return (
        sum(weight * float(record[stat]) for weight, record in zip(weights, records, strict=True))
        / total
    )


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def feature_names(examples: list[ProjectionExample]) -> list[str]:
    if not examples:
        raise ProjectionError("No forward-looking examples can be built from the NBA records")
    return sorted(examples[0].features)


def evaluate(examples: list[ProjectionExample]) -> dict[str, Any]:
    """Evaluate baselines and candidates using two validation folds and a final test."""
    names = feature_names(examples)
    years = sorted({example.target_year for example in examples})
    if len(years) < 4:
        raise ProjectionError(
            "At least four target seasons are required for walk-forward evaluation"
        )
    validation_years, test_year = years[-3:-1], years[-1]
    candidates: dict[str, Any] = {
        "linear": lambda: Ridge(alpha=10.0),
        "gradient_boosted": lambda: HistGradientBoostingRegressor(
            learning_rate=0.05, max_leaf_nodes=12, l2_regularization=1.0, random_state=0
        ),
    }
    results: dict[str, Any] = {stat: {} for stat in TARGET_STATS}
    for stat in TARGET_STATS:
        methods: dict[str, Any] = {
            "latest_season": [],
            "minutes_weighted_history": [],
            "linear": [],
            "gradient_boosted": [],
        }
        for target_year in [*validation_years, test_year]:
            train = [example for example in examples if example.target_year < target_year]
            holdout = [example for example in examples if example.target_year == target_year]
            if not train or not holdout:
                raise ProjectionError(f"Cannot form leakage-safe split for {target_year}")
            actual = np.array([example.target[stat] for example in holdout])
            baseline_predictions = {
                "latest_season": np.array(
                    [example.features[f"latest_{stat}"] for example in holdout]
                ),
                "minutes_weighted_history": np.array(
                    [example.features[f"history_weighted_{stat}"] for example in holdout]
                ),
            }
            for method, prediction in baseline_predictions.items():
                methods[method].append(_metrics(actual, prediction, stat))
            x_train, y_train = (
                _matrix(train, names),
                np.array([example.target[stat] for example in train]),
            )
            x_holdout = _matrix(holdout, names)
            for method, factory in candidates.items():
                model = factory().fit(x_train, y_train)
                methods[method].append(_metrics(actual, model.predict(x_holdout), stat))
        for method, folds in methods.items():
            results[stat][method] = {
                "validation": _average_metrics(folds[:-1]),
                "test": folds[-1],
            }

    selections: dict[str, Selection] = {}
    for stat, methods in results.items():
        baseline = min(
            ("latest_season", "minutes_weighted_history"),
            key=lambda name: float(methods[name]["validation"]["mae"]),
        )
        candidate = min(
            ("linear", "gradient_boosted"),
            key=lambda name: float(methods[name]["validation"]["mae"]),
        )
        selections[stat] = cast(
            Selection,
            candidate
            if methods[candidate]["validation"]["mae"] < methods[baseline]["validation"]["mae"]
            else baseline,
        )
        methods["selected"] = selections[stat]
    return {"validation_years": validation_years, "test_year": test_year, "per_stat": results}


def train_bundle(examples: list[ProjectionExample], evaluation: dict[str, Any]) -> ProjectionBundle:
    names = feature_names(examples)
    selections = {
        stat: cast(Selection, evaluation["per_stat"][stat]["selected"]) for stat in TARGET_STATS
    }
    x = _matrix(examples, names)
    models: dict[str, Any] = {}
    for stat, selection in selections.items():
        if selection == "linear":
            models[stat] = Ridge(alpha=10.0).fit(x, [example.target[stat] for example in examples])
        elif selection == "gradient_boosted":
            models[stat] = HistGradientBoostingRegressor(
                learning_rate=0.05, max_leaf_nodes=12, l2_regularization=1.0, random_state=0
            ).fit(x, [example.target[stat] for example in examples])
    return ProjectionBundle(
        names, selections, models, max(example.target_year for example in examples)
    )


def project(records: list[dict[str, Any]], bundle: ProjectionBundle) -> list[dict[str, Any]]:
    """Create next-season projections from a clean artifact reload."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("league_type") == "NBA":
            grouped[cast(str, record["canonical_player_id"])].append(record)
    rows: list[dict[str, Any]] = []
    for player_id, history in grouped.items():
        ordered = sorted(history, key=lambda record: int(record["season_start_year"]))
        row = _feature_row(ordered)
        matrix = np.array([[row[name] for name in bundle.feature_names]], dtype=float)
        projection: dict[str, Any] = {
            "canonical_player_id": player_id,
            "projection_season_start_year": int(ordered[-1]["season_start_year"]) + 1,
            "model_version": MODEL_VERSION,
        }
        for stat in TARGET_STATS:
            selection = bundle.selections[stat]
            if selection == "latest_season":
                value = row[f"latest_{stat}"]
            elif selection == "minutes_weighted_history":
                value = row[f"history_weighted_{stat}"]
            else:
                value = float(bundle.models[stat].predict(matrix)[0])
            projection[stat] = max(0.0, value)
        rows.append(projection)
    return sorted(rows, key=lambda row: cast(str, row["canonical_player_id"]))


def save_artifacts(
    output_dir: Path, bundle: ProjectionBundle, evaluation: dict[str, Any], records_path: Path
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "projection_bundle.pkl"
    model_path.write_bytes(pickle.dumps(bundle, protocol=pickle.HIGHEST_PROTOCOL))
    metadata = {
        "model_version": MODEL_VERSION,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "training_max_target_year": bundle.training_max_target_year,
        "feature_names": bundle.feature_names,
        "selected_methods": bundle.selections,
        "evaluation": evaluation,
        "input": {"path": records_path.as_posix(), "sha256": _sha256(records_path)},
    }
    metadata_path = output_dir / "training_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    return {"bundle": model_path, "metadata": metadata_path}


def load_bundle(path: Path) -> ProjectionBundle:
    if not path.is_file():
        raise ProjectionError(f"Missing projection artifact: {path}")
    value = pickle.loads(path.read_bytes())
    if not isinstance(value, ProjectionBundle):
        raise ProjectionError(f"Unexpected projection artifact type in {path}")
    return value


def write_projection_table(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def _matrix(examples: list[ProjectionExample], names: list[str]) -> np.ndarray:
    return np.array(
        [[example.features[name] for name in names] for example in examples], dtype=float
    )


def _metrics(actual: np.ndarray, predicted: np.ndarray, stat: str) -> dict[str, float]:
    error = predicted - actual
    # Turnovers are better when lower; all other categories rank descending.
    descending = stat != "turnovers"
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "bias": float(np.mean(error)),
        "spearman": _spearman(actual, predicted),
        "top_30_overlap": _top_overlap(actual, predicted, descending),
    }


def _average_metrics(values: list[dict[str, float]]) -> dict[str, float]:
    return {key: float(np.mean([value[key] for value in values])) for key in values[0]}


def _spearman(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 2 or np.std(left) == 0 or np.std(right) == 0:
        return 0.0
    left_ranks = np.argsort(np.argsort(left)).astype(float)
    right_ranks = np.argsort(np.argsort(right)).astype(float)
    return float(np.corrcoef(left_ranks, right_ranks)[0, 1])


def _top_overlap(actual: np.ndarray, predicted: np.ndarray, descending: bool) -> float:
    count = min(30, len(actual))
    if descending:
        expected = set(np.argsort(-actual)[:count])
        observed = set(np.argsort(-predicted)[:count])
    else:
        expected = set(np.argsort(actual)[:count])
        observed = set(np.argsort(predicted)[:count])
    return len(expected.intersection(observed)) / count if count else 0.0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
