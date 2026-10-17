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

Run `make test` immediately after installation if local Phase 4/6 artifacts do not exist yet;
`make check` also rebuilds the extension player index and therefore belongs after the preparation
steps below.

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

## Complete end-to-end process

Run the following sequence from a clean checkout when preparing a draft. Commands that download
data require external networking; once the server and extension are ready, draft-time inference is
local-only.

### 1. Install and validate the environment

Confirm macOS, Python 3.12.x, Node.js 22 or newer, and npm are available, then install the exact
locked environment:

```bash
make install
make test
.venv/bin/fantasy-picker validate-contracts
```

### 2. Acquire and normalize source data

Review [docs/sources.md](docs/sources.md), licensing, and the selected source versions before
downloading. Then run:

```bash
.venv/bin/fantasy-picker data sources
.venv/bin/fantasy-picker data fetch-all
.venv/bin/fantasy-picker data coverage
.venv/bin/fantasy-picker data normalize
```

Use `--refresh` only when a new immutable source snapshot is intended. Preserve the generated
provenance, unresolved-match, and coverage reports for review.

### 3. Train and prepare the local recommendation artifacts

Run these commands in order. They write ignored local artifacts under `artifacts/` and processed
datasets under `data/processed/`:

```bash
.venv/bin/fantasy-picker model train
.venv/bin/fantasy-picker model project
.venv/bin/fantasy-picker model phase4
.venv/bin/fantasy-picker injury score --as-of YYYY-MM-DD
.venv/bin/fantasy-picker ranking build-reference
```

Replace `YYYY-MM-DD` with the intended draft-date injury snapshot. Confirm these files exist before
continuing:

```text
artifacts/phase3/projection_bundle.pkl
artifacts/phase4/rookie_adjusted_projections.jsonl
artifacts/phase5/injury_assessments.jsonl
artifacts/phase6/reference_distribution.json
```

### 4. Build, load, and configure the extension

Generate the player index and production extension bundle:

```bash
.venv/bin/fantasy-picker extension build-player-index
npm --prefix extension run build
```

In Chrome, enable Developer mode at `chrome://extensions`, choose **Load unpacked**, and select
`extension/dist/`. Copy the 32-letter extension ID displayed by Chrome. Keep the loaded extension
open while completing the remaining setup.

### 5. Start and verify the local API

Export the exact loaded extension origin, then start the service in a terminal that remains open:

```bash
export FANTASY_PICKER_EXTENSION_ORIGIN='chrome-extension://<your-32-letter-extension-id>'
.venv/bin/fantasy-picker serve
```

In a second terminal, verify readiness and metadata:

```bash
curl --fail --silent http://127.0.0.1:8765/api/v1/health
curl --fail --silent http://127.0.0.1:8765/api/v1/metadata
```

The health response must report `"status":"ready"`. If it reports unavailable, rebuild the missing
Phase 4/5/6 artifact and restart the service. Do not start a second service on port 8765.

### 6. Run the Phase 10 benchmark and offline check

With the API running and the extension loaded, open
`chrome-extension://<your-extension-id>/benchmark.html`. Run the benchmark and save its JSON
output. It must cover early, middle, and late snake-draft boards; total click-to-render p95 must be
below 10 seconds. Then disconnect external networking and run it again to verify local-only startup
and inference.

### 7. Complete the manual draft rehearsal

On an ESPN Fantasy Basketball page, open the **Fantasy Picker** panel, select the draft slot, and
maintain the board manually:

- Add every simulated opponent selection to **Taken players**.
- Add each of your selections to **My roster**.
- Click **Suggest picks** only when the board says it is your turn.
- At each suggestion, review score, categories, injury adjustment, warnings, and data freshness.
- Refresh the page mid-draft and confirm session restoration.
- Correct an incomplete/not-your-turn board and verify the visible error.
- Stop and restart the API, then use **Retry suggestions** without losing the board.
- Never use the extension to click or submit an ESPN draft pick.

For the required 156-pick rehearsal and evidence fields, use
[docs/release-checklist.md](docs/release-checklist.md).

### 8. Create a source release after verification

Commit or stash all changes so the checkout is clean, then create the source-only release:

```bash
make release
```

Verify the archive checksum against its adjacent manifest before extracting it on the target Mac.
The release intentionally excludes datasets, model artifacts, generated indexes, built extension
files, virtual environments, caches, and secrets; repeat the preparation steps above after
extracting it.

## Phase 8 local inference API

After preparing the Phase 4 projections, Phase 5 injury assessments, and Phase 6
reference distribution, start the local-only service:

```bash
export FANTASY_PICKER_EXTENSION_ORIGIN='chrome-extension://<your-32-letter-extension-id>'
.venv/bin/fantasy-picker serve
```

The service binds only to `http://127.0.0.1:8765` and makes no network requests.
It serves `GET /api/v1/health`, `GET /api/v1/metadata`, and
`POST /api/v1/recommendations`; the recommendation request and response are the
existing `draft-state` and `recommendation` v1 contracts. The extension origin is
required so CORS is limited to that specific extension. Missing or invalid local
artifacts leave health and metadata unavailable; rerun the applicable earlier
phase, then restart the service. Logs contain endpoint status and timing only,
never draft payloads or player names.

## Phase 9 manual draft-board extension

Prepare the player index and build the load-unpacked Chrome extension before the draft:

```bash
.venv/bin/fantasy-picker extension build-player-index
npm --prefix extension run build
```

Load `extension/dist/` through Chrome's **Load unpacked** developer-mode flow, then copy the
displayed extension ID into `FANTASY_PICKER_EXTENSION_ORIGIN` before starting the local API.
On any ESPN Fantasy Basketball page, the extension adds a closed **Fantasy Picker** panel. Select
your draft slot once, then search and explicitly add players to **My roster** or **Taken players**.
The remaining pool, snake direction, round, and pick are derived from that board. The panel stores
the board only in the current browser session, reads no ESPN page data, and requests suggestions
only when you select **Suggest picks**.

Each suggestion also checks the local API metadata. If the oldest projections, reference, or injury
artifact is seven days old, the panel warns but still lets you explicitly request advice. If the
service is offline, takes more than five seconds, or rejects the board, the panel retains the board,
explains the problem, and offers **Retry suggestions**; it never retries automatically.

## Phase 10 target-Mac benchmark

With the generated extension loaded and the local service running, open
`chrome-extension://<your-extension-id>/benchmark.html`. The page runs 30 valid early-, middle-,
and late-round boards through the real extension worker and localhost API, then prints JSON p50/p95
timings for search, board derivation, JSON serialization, API round trip, server scoring, rendering,
and click-to-render total. Save that output with the draft preparation record.

For the offline rehearsal, open this page after the extension and service are ready, disconnect the
Mac from external networking, and run it again. It must succeed without ESPN or any other remote
request. The recorded p95 targets are: manual-board validation ≤0.1 s, localhost request ≤0.2 s,
candidate scoring ≤4 s, rendering ≤0.5 s, and total click-to-render <10 s.

## Phase 11 clean-machine release and rehearsal

Create a source-only archive only from a clean, verified checkout:

```bash
make release
```

The archive and its JSON manifest are written to `dist/`. The archive contains source, schemas,
tests, and dependency locks, but never local datasets, trained artifacts, generated player indexes,
or built extension output. Verify and extract it on the target Mac, then install the exact release
environment:

```bash
shasum -a 256 -c <(printf '%s  %s\n' '<manifest archive_sha256>' '<archive filename>')
tar -xzf <archive filename>
cd espn-nba-fantasy-picker-<version>-<revision>
make install
make check
```

While external networking is available, run `fantasy-picker data fetch-all`, normalize the data,
train and prepare Phase 4/5/6 artifacts, then build the player index and extension as documented
above. Configure the newly loaded extension ID before starting the API. Record the clean-machine
result, artifact timestamps, benchmark JSON, and the complete 156-pick manual rehearsal in
[docs/release-checklist.md](docs/release-checklist.md). The service and extension work locally after
startup; known recovery steps and intentional limitations are in that checklist.

## Phase 5 injury and availability assessments

Once identity-resolved injury events are available locally, generate a dated
offline recommendation adjustment. This preserves raw per-game projections and
writes only the bounded injury penalty, data status, component features, and
reason codes:

```bash
.venv/bin/fantasy-picker injury score --as-of 2026-10-15
```

The default inputs are `data/processed/injury_events.jsonl` and active-player
records in `data/processed/eligibility.jsonl`; override either path as needed.
Events must pass the shared `injury` schema and have reviewed canonical player
IDs. The scoring rules are documented in `config/injury-risk.yaml` and never
penalize a player by more than 15%.

## Phase 6 roster evaluation

Before a draft, build the local nine-category reference distribution from the
Phase 4 projections and position eligibility. This offline preparation artifact
is reused during draft-time evaluation:

```bash
.venv/bin/fantasy-picker ranking build-reference
```

Evaluate resolved remaining players from a versioned draft-state JSON file:

```bash
.venv/bin/fantasy-picker ranking evaluate --draft-state path/to/draft-state.json
```

The evaluator uses a valid ten-player starting lineup (`PG`, `SG`, `SF`, `PF`,
`C`, `G`, `F`, and three `UTIL`), aggregate makes and attempts for shooting
percentages, and lower-is-better turnovers. Its output contains per-category
before/after values, expected category-win changes, lineup assignments, and
reason codes for Phase 7; it does not apply injury penalties.

## Phase 7 draft-aware recommendations

With the Phase 4 projections, Phase 5 injury assessments, and Phase 6 reference
artifact prepared, rank the available draft choices locally:

```bash
.venv/bin/fantasy-picker ranking recommend --draft-state path/to/draft-state.json
```

The public response is written to `artifacts/phase7/recommendations.json` and
remains valid against the existing `recommendation` contract. A companion
`artifacts/phase7/recommendation_details.json` keeps each candidate's raw
category-win gain, survival estimate, replacement and scarcity values,
uncertainty, injury penalty, and nine category deltas for inspection. The engine
weights current roster gain (60%), next-pick urgency (25%),
scarcity/replacement (10%), and certainty (5%), then applies the Phase 5 injury
penalty. It uses only deterministic local projection ranks—never ADP or a
draft-time network request. Candidates lacking any Phase 5 assessment are
excluded with a warning; an explicit `NO_INJURY_DATA` assessment remains
eligible.

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
