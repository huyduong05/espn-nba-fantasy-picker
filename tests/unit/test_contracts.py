from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from fantasy_picker.contracts import SCHEMA_NAMES, load_schema, load_yaml, repository_root, validate


def fixture_map() -> dict[str, str]:
    path = repository_root() / "tests" / "fixtures" / "contract-map.json"
    return json.loads(path.read_text())


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
def test_schema_is_valid(schema_name: str) -> None:
    assert load_schema(schema_name)["$schema"].endswith("2020-12/schema")


@pytest.mark.parametrize(("fixture_name", "schema_name"), fixture_map().items())
def test_shared_fixture_matches_schema(fixture_name: str, schema_name: str) -> None:
    path = repository_root() / "tests" / "fixtures" / fixture_name
    validate(json.loads(path.read_text()), schema_name)


def test_example_league_config_matches_schema() -> None:
    path = repository_root() / "config" / "league.example.yaml"
    validate(load_yaml(path), "league-config")


def test_source_catalog_matches_schema() -> None:
    path = repository_root() / "config" / "sources.yaml"
    validate(load_yaml(path), "source-catalog")


def test_contract_rejects_unknown_properties() -> None:
    path = repository_root() / "tests" / "fixtures" / "player.valid.json"
    player = json.loads(path.read_text())
    player["silent_extra"] = True
    with pytest.raises(ValidationError):
        validate(player, "player")


def test_contract_rejects_invalid_date_format() -> None:
    path = repository_root() / "tests" / "fixtures" / "injury.valid.json"
    injury = json.loads(path.read_text())
    injury["start_date"] = "October 15"
    with pytest.raises(ValidationError):
        validate(injury, "injury")


def test_repository_root_contains_plan() -> None:
    assert (repository_root() / "plan.md").is_file()
    assert isinstance(repository_root(), Path)
