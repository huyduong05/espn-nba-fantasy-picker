# Data Contracts

All cross-component records use the JSON Schemas in `schemas/v1/`. Contract
version `1.0.0` is independent of the application package version.

## General rules

- Property names use `snake_case` in persisted data and API JSON.
- Timestamps use UTC RFC 3339 strings with a `Z` suffix.
- Dates use `YYYY-MM-DD`.
- Per-game statistics are numeric and non-negative. Shooting makes and attempts
  are retained; FG% and FT% are derived rather than stored as season-stat inputs.
- Unknown values use explicit `null` only where the schema permits it. They are
  never silently converted to zero or `false`.
- Producers reject undocumented properties. Consumers must validate the declared
  `schema_version` before using a record.

## Stable player identity

Canonical player IDs have the form `plr_<32 lowercase hex characters>`. They are
random UUIDv4 identifiers assigned once and persisted in the canonical player
registry. They are deliberately not derived from a name, team, or date of birth,
because each of those can change or be missing.

Each provider's stable identifier is stored under `source_ids`. The tuple
`(source_id, external_player_id)` must map to at most one canonical player. A
deterministic `src_<32 hex>` key may be generated for indexing that tuple, but it
is not a replacement for the canonical ID.

Resolution precedence is:

1. Existing source identifier mapping.
2. Exact match against a reviewed alias plus corroborating metadata.
3. Explicit manual mapping.
4. `AMBIGUOUS` or `UNRESOLVED`.

Normalized or fuzzy names are candidate-generation aids only. Code must never
silently merge two players from a name match. Accents, punctuation, suffixes, and
duplicate names are therefore preserved in source records and reviewed mappings.

## Normalized datasets

`fantasy-picker data normalize` writes local JSONL datasets beneath
`data/processed/`. NBA season averages retain their source player identifier and
are normalized to start-year seasons. NCAA source end-year seasons are converted
to start-year seasons; game rows are aggregated to per-game player-season records
while retaining FGM/FGA and FTM/FTA.

NBA IDs are the identity anchor. An NCAA record is linked automatically only when
one exact normalized name candidate is corroborated by both draft year and
school. `config/identity-review.yaml` can add an explicit reviewed mapping. NCAA
rows without a provider player ID are retained with an `unidentified:` local key,
reported as unresolved, and never eligible for automatic NBA matching. The
normalization manifest lists every verified raw provenance manifest consumed.

## Cache and provenance

Raw downloads live below `data/raw/<source_id>/<retrieval-date>/`. A downloaded
file is immutable once its provenance manifest is written. Re-fetching creates a
new snapshot rather than replacing the old one.

Every snapshot manifest records:

- A unique snapshot ID.
- A stable dataset ID.
- Source ID and exact URL.
- UTC retrieval timestamp.
- Repository-relative local path.
- SHA-256 digest and byte count.
- Media type, license when known, and notes.

Code verifies the digest before consuming a cached raw file. Missing licensing
information remains `null`; public availability is not treated as redistribution
permission.

## Contract summaries

- `league-config`: confirmed 12-team league and roster configuration.
- `player`: canonical identity, aliases, birth date, and provider identifiers.
- `eligibility`: dated, sourced NBA position eligibility.
- `season-stat`: source-level per-game counting and shooting-volume record. Team
  identifiers are normalized into provider namespaces (for example, `NBA:LAL`
  and `NCAA:duke`).
- `injury`: injury, suspension, personal absence, or load-management event. Current
  events may include `expected_return_date`; a missing date means the timeline is
  unknown, not that the player is available.
- `draft-state`: extension-to-server state, including unresolved matches and
  manual overrides.
- `recommendation`: server response with at most five explainable suggestions.
- `provenance`: immutable raw snapshot metadata.
- `source-catalog`: reviewed source status, coverage, access, licensing, and gaps.

Phase 6 evaluator artifacts are local implementation artifacts rather than a
cross-component public contract. They retain the projection/eligibility input
fingerprint, deterministic simulation configuration, reference category means
and standard deviations, and per-candidate category deltas for Phase 7.

Phase 7 writes the schema-valid recommendation response separately from its
local inspection artifact. The latter retains raw category-win gains, category
deltas, local rank and survival estimate, replacement and scarcity evidence,
uncertainty, and the pre- and post-injury score components without extending the
stable public recommendation schema.

