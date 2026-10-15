"""Stable identifiers and conservative name normalization helpers."""

from __future__ import annotations

import re
import unicodedata
from uuid import NAMESPACE_URL, uuid4, uuid5

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def new_canonical_player_id() -> str:
    """Assign a canonical ID that does not depend on mutable player attributes."""
    return f"plr_{uuid4().hex}"


def new_event_id() -> str:
    return f"evt_{uuid4().hex}"


def source_identity_key(source_id: str, external_player_id: str) -> str:
    """Create a deterministic lookup key for a provider-owned player ID."""
    if not source_id or not external_player_id:
        raise ValueError("source_id and external_player_id must be non-empty")
    value = f"https://fantasy-picker.local/source/{source_id}/{external_player_id}"
    return f"src_{uuid5(NAMESPACE_URL, value).hex}"


def normalized_name_candidate(display_name: str) -> str:
    """Normalize a name for candidate lookup, never for automatic identity merging."""
    decomposed = unicodedata.normalize("NFKD", display_name)
    ascii_name = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return _NON_ALPHANUMERIC.sub(" ", ascii_name.casefold()).strip()
