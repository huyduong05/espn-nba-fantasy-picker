"""Shared JSON Schema loading and validation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_VERSION = "1.0.0"
SCHEMA_NAMES = (
    "draft-state",
    "eligibility",
    "injury",
    "league-config",
    "player",
    "provenance",
    "recommendation",
    "season-stat",
    "source-catalog",
)


def repository_root() -> Path:
    """Return the checkout root, with an override for installed deployments."""
    configured = os.environ.get("FANTASY_PICKER_ROOT")
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[2]


def schema_directory() -> Path:
    return repository_root() / "schemas" / "v1"


def load_schema(name: str) -> dict[str, Any]:
    if name not in SCHEMA_NAMES:
        raise ValueError(f"Unknown schema {name!r}; expected one of {SCHEMA_NAMES}")
    path = schema_directory() / f"{name}.schema.json"
    return _load_json(path)


def validate(instance: Any, schema_name: str) -> None:
    """Validate an instance, including RFC 3339 date and timestamp formats."""
    schema = load_schema(schema_name)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(instance)


def load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value: dict[str, Any] = json.load(stream)
    return value
