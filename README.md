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

## Contract ownership

The JSON files in `schemas/v1/` are the source of truth for records exchanged by
the data pipeline, model code, Flask service, and extension. Both the Python and
TypeScript test suites validate the same fixtures against those schemas.

Breaking contract changes require a new schema directory and schema version.
Additive, backward-compatible changes may update the current schema only while the
project remains pre-release.

See [docs/contracts.md](docs/contracts.md) for identity, nullability, timestamp,
and provenance rules.
