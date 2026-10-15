"""Developer commands for contract validation."""

from __future__ import annotations

import argparse
import json

from fantasy_picker.contracts import SCHEMA_NAMES, load_schema, load_yaml, repository_root, validate


def validate_contracts() -> int:
    root = repository_root()
    for name in SCHEMA_NAMES:
        load_schema(name)

    validate(load_yaml(root / "config" / "league.example.yaml"), "league-config")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command == "validate-contracts":
        return validate_contracts()
    raise AssertionError(f"Unhandled command: {arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())
