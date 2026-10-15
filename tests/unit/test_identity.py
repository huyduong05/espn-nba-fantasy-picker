from fantasy_picker.identity import (
    new_canonical_player_id,
    normalized_name_candidate,
    source_identity_key,
)


def test_canonical_ids_are_unique_and_well_formed() -> None:
    first = new_canonical_player_id()
    second = new_canonical_player_id()
    assert first.startswith("plr_")
    assert len(first) == 36
    assert first != second


def test_source_identity_key_is_deterministic_and_namespaced() -> None:
    assert source_identity_key("provider_a", "42") == source_identity_key("provider_a", "42")
    assert source_identity_key("provider_a", "42") != source_identity_key("provider_b", "42")


def test_name_normalization_only_builds_candidate_keys() -> None:
    assert normalized_name_candidate("  José  Alvarado Jr. ") == "jose alvarado jr"
