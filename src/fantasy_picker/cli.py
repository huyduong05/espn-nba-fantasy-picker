"""Developer commands for contract validation."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from fantasy_picker.contracts import SCHEMA_NAMES, load_schema, load_yaml, repository_root, validate
from fantasy_picker.data.coverage import write_coverage_report
from fantasy_picker.data.http import AcquisitionError, HttpClient
from fantasy_picker.data.normalize import NormalizationError, normalize_cached_data
from fantasy_picker.data.snapshots import SnapshotStore
from fantasy_picker.data.sources import (
    AcquisitionSummary,
    acquire_historical_injuries,
    acquire_nba_active_roster,
    acquire_nba_com_history,
    acquire_nba_history,
    acquire_nba_reference_data,
    acquire_ncaa_player_boxes,
)
from fantasy_picker.models.projections import (
    ProjectionError,
    build_examples,
    evaluate,
    load_bundle,
    load_nba_stats,
    project,
    save_artifacts,
    train_bundle,
    write_projection_table,
)


def validate_contracts() -> int:
    root = repository_root()
    for name in SCHEMA_NAMES:
        load_schema(name)

    validate(load_yaml(root / "config" / "league.example.yaml"), "league-config")
    validate(load_yaml(root / "config" / "sources.yaml"), "source-catalog")
    fixture_map = json.loads((root / "tests" / "fixtures" / "contract-map.json").read_text())
    for fixture_name, schema_name in fixture_map.items():
        instance = json.loads((root / "tests" / "fixtures" / fixture_name).read_text())
        validate(instance, schema_name)

    print(f"Validated {len(SCHEMA_NAMES)} schemas and {len(fixture_map)} fixtures.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fantasy-picker")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "validate-contracts", help="validate schemas, fixtures, and league config"
    )
    data_parser = subparsers.add_parser("data", help="acquire and inspect raw source data")
    data_subparsers = data_parser.add_subparsers(dest="data_command", required=True)

    nba_parser = data_subparsers.add_parser("fetch-nba", help="fetch five NBA seasons")
    nba_parser.add_argument(
        "--seasons", nargs="+", type=int, default=[2021, 2022, 2023, 2024, 2025]
    )
    _add_refresh_option(nba_parser)

    nba_com_parser = data_subparsers.add_parser(
        "fetch-nba-com",
        help="fetch educational NBA.com snapshots subject to NBA.com terms",
    )
    nba_com_parser.add_argument(
        "--seasons", nargs="+", type=int, default=[2021, 2022, 2023, 2024, 2025]
    )
    _add_refresh_option(nba_com_parser)

    roster_parser = data_subparsers.add_parser(
        "fetch-nba-roster", help="fetch the active NBA roster and rookie identity fields"
    )
    roster_parser.add_argument("--season", type=int, default=2026)
    _add_refresh_option(roster_parser)

    reference_parser = data_subparsers.add_parser(
        "fetch-nba-reference", help="fetch active players and current injuries"
    )
    _add_refresh_option(reference_parser)

    college_parser = data_subparsers.add_parser(
        "fetch-college", help="fetch two NCAA player-box seasons"
    )
    college_parser.add_argument("--seasons", nargs="+", type=int, default=[2025, 2026])
    _add_refresh_option(college_parser)

    injury_parser = data_subparsers.add_parser(
        "fetch-injuries", help="fetch the licensed 2010-2020 historical injury archive"
    )
    _add_refresh_option(injury_parser)

    all_parser = data_subparsers.add_parser("fetch-all", help="fetch all selected sources")
    _add_refresh_option(all_parser)
    data_subparsers.add_parser("coverage", help="write a coverage report for cached data")
    data_subparsers.add_parser("sources", help="print the reviewed source catalog")
    normalize_parser = data_subparsers.add_parser(
        "normalize", help="normalize cached snapshots into local processed datasets"
    )
    normalize_parser.add_argument(
        "--identity-review",
        type=str,
        default="config/identity-review.yaml",
        help="repository-relative reviewed identity mappings and sample",
    )
    model_parser = subparsers.add_parser("model", help="train and run local projection models")
    model_subparsers = model_parser.add_subparsers(dest="model_command", required=True)
    train_parser = model_subparsers.add_parser(
        "train", help="evaluate and save Phase 3 projections"
    )
    train_parser.add_argument("--stats", default="data/processed/season_stats.jsonl")
    train_parser.add_argument("--output-dir", default="artifacts/phase3")
    project_parser = model_subparsers.add_parser(
        "project", help="write projections from a saved artifact"
    )
    project_parser.add_argument("--stats", default="data/processed/season_stats.jsonl")
    project_parser.add_argument("--bundle", default="artifacts/phase3/projection_bundle.pkl")
    project_parser.add_argument("--output", default="artifacts/phase3/projections.jsonl")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "validate-contracts":
        return validate_contracts()
    if arguments.command == "data":
        return _run_data_command(arguments)
    if arguments.command == "model":
        return _run_model_command(arguments)
    raise AssertionError(f"Unhandled command: {arguments.command}")


def _run_model_command(arguments: argparse.Namespace) -> int:
    root = repository_root()
    stats_path = root / arguments.stats
    try:
        records = load_nba_stats(stats_path)
        if arguments.model_command == "train":
            examples = build_examples(records)
            evaluation = evaluate(examples)
            bundle = train_bundle(examples, evaluation)
            output_dir = root / arguments.output_dir
            paths = save_artifacts(output_dir, bundle, evaluation, stats_path)
            projections_path = output_dir / "projections.jsonl"
            write_projection_table(projections_path, project(records, bundle))
            print(
                json.dumps(
                    {
                        "artifacts": {key: value.as_posix() for key, value in paths.items()},
                        "projections": projections_path.as_posix(),
                        "evaluation": evaluation,
                    },
                    indent=2,
                )
            )
            return 0
        if arguments.model_command == "project":
            bundle = load_bundle(root / arguments.bundle)
            output = root / arguments.output
            write_projection_table(output, project(records, bundle))
            print(output)
            return 0
    except (ProjectionError, OSError, ValueError) as error:
        print(f"Projection modeling failed: {error}")
        return 2
    raise AssertionError(f"Unhandled model command: {arguments.model_command}")


def _add_refresh_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="create a timestamped batch instead of reusing today's verified cache",
    )


def _run_data_command(arguments: argparse.Namespace) -> int:
    root = repository_root()
    if arguments.data_command == "sources":
        print(json.dumps(load_yaml(root / "config" / "sources.yaml"), indent=2))
        return 0
    if arguments.data_command == "coverage":
        path = write_coverage_report(root)
        print(path)
        print(path.read_text(), end="")
        return 0
    if arguments.data_command == "normalize":
        review_path = root / arguments.identity_review
        try:
            result = normalize_cached_data(root, review_path)
        except (NormalizationError, OSError, ValueError) as error:
            print(f"Normalization failed: {error}")
            return 2
        print(json.dumps(result["quality"], indent=2))
        return 0

    batch = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ") if arguments.refresh else None
    store = SnapshotStore(root, batch=batch)
    client = HttpClient()
    try:
        summaries = _acquire_selected(arguments, client, store)
    except (AcquisitionError, OSError, ValueError) as error:
        print(f"Acquisition failed: {error}")
        return 2
    _print_summaries(summaries)
    return 0


def _acquire_selected(
    arguments: argparse.Namespace, client: HttpClient, store: SnapshotStore
) -> list[AcquisitionSummary]:
    if arguments.data_command == "fetch-nba":
        return acquire_nba_history(client, store, seasons=arguments.seasons)
    if arguments.data_command == "fetch-nba-com":
        return acquire_nba_com_history(client, store, season_start_years=arguments.seasons)
    if arguments.data_command == "fetch-nba-roster":
        return [acquire_nba_active_roster(client, store, season_start_year=arguments.season)]
    if arguments.data_command == "fetch-nba-reference":
        return acquire_nba_reference_data(client, store)
    if arguments.data_command == "fetch-college":
        return acquire_ncaa_player_boxes(client, store, seasons=arguments.seasons)
    if arguments.data_command == "fetch-injuries":
        return [acquire_historical_injuries(client, store)]
    if arguments.data_command == "fetch-all":
        summaries = acquire_ncaa_player_boxes(client, store, seasons=[2025, 2026])
        summaries.extend(
            acquire_nba_com_history(client, store, season_start_years=range(2021, 2026))
        )
        summaries.append(acquire_nba_active_roster(client, store, season_start_year=2026))
        summaries.append(acquire_historical_injuries(client, store))
        return summaries
    raise AssertionError(f"Unhandled data command: {arguments.data_command}")


def _print_summaries(summaries: list[AcquisitionSummary]) -> None:
    for summary in summaries:
        record_text = "unknown records" if summary.records is None else f"{summary.records} records"
        print(
            f"{summary.dataset_id}: {record_text}, {len(summary.files)} files, "
            f"{summary.reused_files} reused"
        )


if __name__ == "__main__":
    raise SystemExit(main())
