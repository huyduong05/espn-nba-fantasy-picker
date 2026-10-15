# ESPN NBA Fantasy Draft Assistant

A local-first draft assistant for a 12-team, head-to-head, nine-category ESPN NBA
fantasy league. The implementation is being delivered in the phases defined in
[plan.md](plan.md).

## Phase 0 development setup

Requirements:

- macOS
- Python 3.12.x (the target machine uses 3.12.1)
- Node.js 22 or newer and npm

Install the development environments:

```bash
make install
```

Run every formatter check, linter, type checker, and test:

```bash
make check
```

Run tests without the other checks:

```bash
make test
```

Validate the shared contracts and example league configuration directly:

```bash
.venv/bin/fantasy-picker validate-contracts
```

Phase 0 does not download production data, select a data provider, train a model,
or communicate with ESPN. Those choices remain gated by later phases.

## Phase 1 data acquisition

Review the source decisions and unresolved gaps in
[docs/sources.md](docs/sources.md), then inspect the machine-readable catalog:

```bash
.venv/bin/fantasy-picker data sources
```

Download the two selected NCAA seasons. This source requires no credentials:

```bash
.venv/bin/fantasy-picker data fetch-college
```

Download five NBA.com season-average snapshots:

```bash
.venv/bin/fantasy-picker data fetch-nba-com
.venv/bin/fantasy-picker data fetch-nba-roster
```

These user-selected educational snapshots are deliberately distinguished from
permissively licensed data. NBA.com's current terms restrict using NBA Statistics
in connection with a fantasy game; see [docs/sources.md](docs/sources.md) before
using the files.

Download the separately licensed CC0 historical injury archive:

```bash
.venv/bin/fantasy-picker data fetch-injuries
```

Generate a coverage report from the newest cached batch:

```bash
.venv/bin/fantasy-picker data coverage
```

Same-day runs verify and reuse cached files. Add `--refresh` to a fetch command to
create a new timestamped immutable batch. Data acquisition is the only phase that
requires network access; draft-time inference will use local artifacts.

## Phase 2 normalization and identity resolution

Build the local processed datasets from the verified snapshots:

```bash
.venv/bin/fantasy-picker data normalize
```

The command writes ignored local artifacts under `data/processed/`: canonical
players, normalized per-game season statistics, active NBA eligibility, source
provenance, data-quality results, and an unresolved-match report. It is safe to
rerun: existing canonical IDs are retained from the local player registry.

`config/identity-review.yaml` contains reviewed NCAA-to-NBA pairs and optional
manual corrections. Exact normalized names alone never cause a merge: automated
links also require a matching draft year and school. NCAA source rows that lack a
provider player ID are retained under a derived unresolved key, never linked to
an NBA player automatically, and counted in the quality report.

## Phase 3 baseline projections

Train the local NBA-only baseline and regression models after normalization:

```bash
.venv/bin/fantasy-picker model train
```

This writes an ignored `artifacts/phase3/` bundle, metrics metadata, and a
next-season per-game projection table. The comparison uses two walk-forward
validation seasons and a later held-out test season; every feature for season
`Y` uses NBA records from seasons before `Y` only. Each statistic selects the
best validation method from latest-season and minutes-weighted-history
baselines, a ridge regressor, and a deterministic gradient-boosted tree.

To reproduce the saved projection table from a new process:

```bash
.venv/bin/fantasy-picker model project
```

The Phase 3 scope intentionally does not use current injuries, college or
international translations, or guessed ages. Those inputs are handled in later
phases; past NBA production profiles act as the initial role features.

## Phase 4 rookie and low-sample projections

Run the Phase 4 adjustment after Phase 3 training:

```bash
.venv/bin/fantasy-picker model phase4
```

This emits active-player projections under `artifacts/phase4/`. Reviewed NCAA
records use the configurable 0.5 per-stat translation multiplier; NBA evidence
receives 75% weight in a second season and 90% once established. Players without
NBA history receive a monotonic uncertainty penalty based on their available
non-NBA seasons. Unsupported international histories are not guessed: they are
flagged low-information with a 35% recommendation multiplier penalty. The
universal 0.5 translation factor is an intentionally uncalibrated initial
assumption and should be revisited when a licensed, comparable international
dataset is available.

## Contract ownership

The JSON files in `schemas/v1/` are the source of truth for records exchanged by
the data pipeline, model code, Flask service, and extension. Both the Python and
TypeScript test suites validate the same fixtures against those schemas.

Breaking contract changes require a new schema directory and schema version.
Additive, backward-compatible changes may update the current schema only while the
project remains pre-release.

See [docs/contracts.md](docs/contracts.md) for identity, nullability, timestamp,
and provenance rules.
