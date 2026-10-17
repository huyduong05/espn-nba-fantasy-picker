# ESPN NBA Fantasy Draft Assistant — Integration Plan

## 1. Goal

Build a personal Chrome extension and local Python service that recommend the five best available players during an ESPN fantasy basketball snake draft.

The system will:

- Support 12-team, head-to-head each-category leagues.
- Evaluate PTS, REB, AST, STL, BLK, 3PM, FG%, FT%, and TO.
- Optimize projected category wins while balancing all nine categories.
- Account for the user's current roster, positional eligibility, draft position, and likely availability at the user's next pick.
- Penalize injury and absence risk by up to 15%.
- Prefer NBA evidence over college or international evidence.
- Return five ranked recommendations with a 0–10 recommendation score, strongest categories, projected category-win gain, and injury adjustment.
- Run locally and respond in less than 10 seconds without draft-time network dependencies.

## 2. Confirmed Requirements

### League configuration

- Scoring: head-to-head each-category.
- Categories: PTS, REB, AST, STL, BLK, 3PM, FG%, FT%, and TO.
- Teams: 12.
- Draft: snake.
- Active roster: 13 players.
- Starters: PG, SG, SF, PF, C, G, F, and 3 UTIL.
- Bench: 3 BE slots.
- Injured reserve: 1 IR slot outside the active roster.
- No keepers, pre-drafted players, games-played limits, or acquisition limits.
- Strategy: balance all nine categories; do not intentionally punt a category.
- Selection method: greedy optimization of the current pick, informed by the current roster and likely player availability at the user's next pick.

### Projection configuration

- Use the five most recently completed NBA seasons.
- Use the prior two college or international seasons for newly drafted players when available.
- Limit international acquisition to rookies/newly drafted players on active NBA rosters.
- Omit unsupported international leagues and flag the affected player as low-information.
- Keep non-NBA history as an input after a player enters the NBA, but give NBA history greater weight.
- Apply an initial 0.5 translation multiplier to college and international production.
- Produce per-game projections.
- Rank low-sample players below established talent through uncertainty/sample-size penalties.
- Use public APIs and public datasets, with every source documented and cited.

### Injury configuration

- Prioritize games missed when calculating injury risk.
- Also consider recurring injuries, current injuries, suspensions, personal absences, and load management.
- Make the maximum injury-related recommendation penalty 15%.
- Consider expected return dates and IR eligibility.
- Use official NBA injury reports for current status under the educational-use source decision.
- Keep the raw per-game projection separate from the injury-adjusted recommendation score.

### Runtime configuration

- Python 3.12.1 on macOS 26.5.1.
- Flask server started manually before a draft.
- Fixed localhost port is acceptable.
- All required data and model artifacts must be available locally before the draft begins.
- The extension requests recommendations only when the user clicks a button.
- The user remains responsible for making the actual ESPN draft selection.
- The extension is shown on ESPN Fantasy Basketball pages but does not read ESPN page content or
  use authenticated ESPN APIs.
- The user manually maintains their roster and taken-player lists through the extension panel.

## 3. Proposed Architecture

```text
Historical public data sources
            |
            v
Download and normalization pipeline
            |
            v
Versioned local datasets
            |
            +--> Projection training pipeline
            |          |
            |          v
            |    Saved model artifacts
            |
            +--> Injury/absence feature pipeline
                       |
                       v
                Local inference bundle

ESPN draft page --> Manual extension panel --> Derived draft state
                                                |
                                                v
                                      Flask localhost API
                                                |
                          +---------------------+--------------------+
                          |                     |                    |
                          v                     v                    v
                   Bundled player index    Roster evaluator    Draft-aware ranker
                          |                     |                    |
                          +---------------------+--------------------+
                                                |
                                                v
                                    Top-five recommendations
```

The training pipeline and draft-time inference path are separate. Data downloads, feature generation,
model fitting, and player-index generation happen before the draft. During the draft, the service
only loads cached artifacts, validates the manual board, evaluates the current state, and ranks candidates.

## 4. Repository Layout Target

```text
espn-nba-fantasy-picker/
├── README.md
├── plan.md
├── pyproject.toml
├── config/
│   ├── league.example.yaml
│   └── sources.yaml
├── data/
│   ├── raw/                 # Ignored downloaded source files
│   ├── interim/             # Ignored normalized intermediate data
│   ├── processed/           # Ignored model-ready data
│   └── README.md            # Provenance, schemas, and refresh commands
├── artifacts/               # Ignored trained models and inference tables
├── src/fantasy_picker/
│   ├── data/
│   ├── features/
│   ├── models/
│   ├── ranking/
│   ├── api/
│   └── cli.py
├── extension/
│   ├── manifest.json
│   ├── package.json
│   ├── src/
│   └── tests/
├── tests/
│   ├── fixtures/
│   ├── unit/
│   ├── integration/
│   └── performance/
└── scripts/
```

Exact files and libraries will be selected during their corresponding phases.

## 5. Phase Plan

Each phase has an explicit completion gate. No later phase should be treated as complete until its gate is met.

### Phase 0 — Project foundation and contracts

Status: **Complete (2026-10-15).**

Tasks:

- Establish the Python package, TypeScript extension workspace, formatting, linting, and tests.
- Define a versioned league configuration schema.
- Define canonical player, season-stat, eligibility, injury, draft-state, and recommendation schemas.
- Define stable identifiers and the strategy for resolving player names across sources and ESPN.
- Define raw-data caching, checksums, refresh timestamps, and provenance metadata.
- Add environment and startup documentation for Python 3.12.1 and the extension toolchain.

Completion gate:

- Python and TypeScript test commands run locally.
- Schemas are documented and validated by fixture-based tests.
- No production data source or model choice is silently assumed.

### Phase 1 — Source research and historical data acquisition

Status: **Complete (2026-10-15).** NBA.com educational snapshots and a CC0
historical injury archive are locally cached with provenance. International
coverage is intentionally measured as unavailable for the scoped rookie cohort:
the documented policy omits unsupported leagues and flags affected players as
low-information pending a future licensed-source decision.

Tasks:

- Evaluate public sources for NBA per-game box-score history, player identity, position eligibility, draft/rookie history, college statistics, international statistics, and injury/absence history.
- Record source URL, owner, coverage, fields, update cadence, access method, terms or licensing notes, and known limitations.
- Select primary and fallback sources for each required data domain.
- Implement reproducible downloaders with retries, rate limiting, local caching, and clear failure messages.
- Save immutable raw snapshots and provenance manifests.
- Ensure draft-time execution never depends on these sources.

Completion gate:

- A documented command downloads or reuses cached source snapshots.
- Five completed NBA seasons can be obtained for the required counting and shooting-volume fields.
- Available college/international and injury coverage is measured rather than assumed.
- Every retained dataset has a citation and provenance record.
- Gaps that prevent a requirement from being met are presented for a user decision.

### Phase 2 — Normalization and player identity resolution

Status: **Complete (2026-10-15).** The local normalizer emits validated canonical
players, per-game NBA and NCAA season records, eligibility, provenance, quality,
and unresolved-match artifacts. A 15-pair reviewed NCAA↔NBA sample matched at
100%; 16,315 NCAA rows without provider IDs are retained with explicitly
unresolved local keys and are never auto-linked.

Tasks:

- Normalize season labels, teams, leagues, positions, units, and stat names.
- Preserve FGM/FGA and FTM/FTA so percentage-category impact can be calculated correctly.
- Create a canonical player table and source-to-canonical identifier mappings.
- Handle suffixes, accents, punctuation, name changes, and duplicate names.
- Link college/international records to NBA players without relying only on fuzzy matching.
- Produce an unresolved-match report for manual review.
- Validate completeness, uniqueness, plausible ranges, and season coverage.

Completion gate:

- Processed datasets pass schema and data-quality tests.
- Player matching accuracy is measured on a reviewed sample.
- Unresolved or ambiguous records are surfaced and never silently merged.

### Phase 3 — Baseline projections and evaluation framework

Status: **Complete (2026-10-15).** Walk-forward evaluation selected a
gradient-boosted model for steals and retained documented simple baselines for
the remaining statistics when the regression candidates did not improve
validation MAE.

Tasks:

- Establish simple baselines such as latest-season values and minutes-weighted multi-season averages.
- Define time-based train/validation/test splits with no future leakage.
- Establish per-stat error metrics and ranking-oriented evaluation metrics.
- Train separate initial regressors for PTS, REB, AST, STL, BLK, 3PM, TO, FGM, FGA, FTM, and FTA per game.
- Compare a regularized linear baseline with a gradient-boosted tree model.
- Add recency, age, minutes, games played, role, trend, and sample-size features.
- Save reproducible model artifacts and training metadata.

Completion gate:

- Models are evaluated only on later seasons than their training data.
- Chosen models outperform the documented simple baselines enough to justify their complexity.
- Saved artifacts can reproduce a projection table from a clean process.

### Phase 4 — Rookie and low-sample projections

Status: **Complete (2026-10-15).** The active-player artifact applies the
configured NCAA translation and NBA/non-NBA blend to 83 conservatively linked
players; two unsupported international cases are surfaced as low-information.

Tasks:

- Normalize available college and international per-game data.
- Apply the configured 0.5 initial translation multiplier.
- Make NBA evidence more influential than non-NBA evidence.
- Retain non-NBA history as a diminishing input after NBA experience begins.
- Add sample-size and uncertainty penalties that push poorly known players below similarly projected established players.
- Measure projection behavior separately for rookies, second-year players, and established NBA players.

Completion gate:

- Rookie projections are reproducible and traceable to their source seasons.
- NBA and non-NBA weighting is visible in configuration and tests.
- Low-sample penalties behave monotonically in controlled test cases.
- The limitations of the universal 0.5 translation factor are documented for later calibration.

### Phase 5 — Injury and availability scoring

Status: **Complete (2026-10-15).** The local Phase 5 scorer emits an
inspectable, configuration-driven 0–15% recommendation penalty from
identity-resolved absence events. It keeps raw per-game projections intact,
accounts for current status, return timelines, recurrence, recency-weighted
games missed, non-injury absences, and IR eligibility, while explicitly
labeling unavailable current-health data.

Tasks:

- Define the injury/absence event schema.
- Build recency-weighted games-missed, recurrence, current-status, return-timeline, suspension, personal-absence, and load-management features where source data supports them.
- Define a transparent injury-risk score.
- Map injury risk to a bounded 0–15% recommendation penalty.
- Account for current IR eligibility without changing the raw per-game projection.
- Expose reason codes so the recommendation can explain its penalty.

Completion gate:

- Injury penalties never exceed 15%.
- Current and historical risk components are inspectable.
- Missing injury data does not masquerade as evidence of perfect health.
- Synthetic and historical test cases produce expected penalty ordering.

### Phase 6 — Nine-category roster evaluator

Status: **Complete (2026-10-15).** The local evaluator builds a seeded,
position-valid starters-only reference distribution and returns deterministic
per-category expected-win deltas for each candidate. Shooting percentages use
aggregate makes and attempts, turnovers are reversed, and Phase 5 availability
penalties remain separate for Phase 7.

Tasks:

- Calculate team totals for counting categories from projected per-game production.
- Calculate team FG% and FT% from aggregate makes and attempts, not averages of player percentages.
- Reverse the direction of TO so lower values are better.
- Build a reference distribution representing plausible 12-team league rosters.
- Convert category totals into category win probabilities or another calibrated measure of projected category wins.
- Evaluate the marginal effect of adding each candidate to the current roster.
- Enforce position eligibility and the confirmed roster layout.

Completion gate:

- The evaluator produces nine explainable category contributions.
- Percentage-volume behavior is covered by tests.
- Adding a candidate returns a measurable projected category-win gain.
- Balanced synthetic rosters are preferred over otherwise equivalent one-category concentrations.

### Phase 7 — Draft-aware greedy recommendation engine

Status: **Complete (2026-10-16).** The deterministic local ranker composes
Phase 6 category-win results with configured current-roster (60%), next-pick
urgency (25%), scarcity/replacement (10%), and certainty (5%) evidence, then
applies the Phase 5 injury penalty. It emits the unchanged public top-five
contract plus a separate inspectable scoring artifact; absent Phase 5 coverage
is warned and excluded while explicit `NO_INJURY_DATA` remains eligible.

Tasks:

- Implement candidate evaluation for the current pick.
- Combine roster gain, position scarcity, replacement value, uncertainty, and injury adjustment.
- Model the number of intervening picks in the snake draft.
- Estimate whether a candidate is likely to remain available at the user's next pick using a documented availability signal.
- Normalize the composite recommendation score to 0–10.
- Return the top five with score, strongest categories, category-win gain, injury adjustment, and concise reason codes.
- Ensure score normalization does not obscure the underlying category metrics.

Completion gate:

- Recommendations change appropriately as roster composition, available players, draft slot, and round change.
- The same input produces deterministic output.
- The 0–10 score and its components are documented.
- Unit scenarios cover roster needs, scarcity, injury risk, turnovers, percentage volume, and next-pick availability.

### Phase 8 — Local Flask inference service

Status: **Implementation complete (2026-10-16).** The local API and test suite
are complete. Live readiness additionally requires prepared Phase 4/5/6 artifacts
and `FANTASY_PICKER_EXTENSION_ORIGIN` set to the loaded extension's ID.

Tasks:

- Define a versioned localhost JSON API.
- Add health/status, recommendation, and metadata endpoints.
- Load models and local inference tables once at startup.
- Validate request schemas and return actionable errors.
- Configure localhost-only access and narrowly scoped CORS for the extension.
- Add structured local logs without storing sensitive ESPN page content unnecessarily.
- Add a manual-start command and readiness message.

Proposed request fields:

- League configuration and scoring categories.
- Draft round, pick, direction, and user's draft slot.
- User roster with position eligibility.
- Drafted or remaining players.
- Optional manual corrections.

Proposed response fields:

- Model/data versions and response time.
- Five ranked recommendations.
- For each recommendation: canonical player ID, name, 0–10 score, strong categories, category-win gain, injury penalty, position eligibility, and reason codes.

Completion gate:

- The API runs with networking disabled after artifacts are prepared.
- Invalid and ambiguous players are reported clearly.
- Warm recommendation latency stays safely below the end-to-end budget.

### Phase 9 — Manual draft-board Chrome extension

Status: **Implementation complete (2026-10-17).** The extension bundles a
session-scoped manual board, generated local player index, explicit-click local
API client, and no ESPN page parser. Loading it into Chrome and configuring its
generated extension ID remain pre-draft setup steps.

Tasks:

- Create a Manifest V3 TypeScript extension restricted to ESPN Fantasy Basketball pages and the localhost API.
- Add a closable in-page panel that does not read or parse ESPN page content.
- Generate a versioned local player index from active Phase 4 projections, canonical names and aliases, and historical eligibility.
- Require explicit search-result selection for separate user-roster and taken-player lists; prevent duplicates and unavailable players.
- Derive remaining players, round, pick, and snake direction from the manual board and configured draft slot.
- Persist the manual board in session-only extension storage and validate that suggestions are requested only at the user's turn.
- Add a visible `Suggest picks` action and display scores, strong categories, category-win gain, injury adjustment, errors, and data freshness.
- Never click the ESPN draft button or submit a pick.

Completion gate:

- The manual board produces a valid draft-state request for early, middle, and late snake-draft turns.
- Session restoration preserves the board after refresh without retaining it across browser sessions.
- The extension requests recommendations only after an explicit click.
- Extension permissions are minimal and documented.

### Phase 10 — End-to-end integration and latency hardening

Status: **Implementation complete (2026-10-17); target-Mac benchmark results
are still required before the completion gate is met.**

Tasks:

- Validate extension payloads against the Flask API contract with representative manual boards for early, middle, and late rounds.
- Profile index search, board-state derivation, JSON transfer, candidate scoring, and rendering separately.
- Precompute all invariant values and keep models resident in memory.
- Add timeouts and useful recovery paths if the service is unavailable or data is stale.
- Verify that no external network request is required after startup.

Latency budget target:

```text
Manual board validation           <= 0.1 s
Extension-to-localhost request    <= 0.2 s
Candidate scoring                 <= 4.0 s
Response rendering                <= 0.5 s
Contingency                       <= 3.5 s
Total                             < 10.0 s
```

Completion gate:

- End-to-end p95 latency is below 10 seconds on the target Mac.
- Offline draft simulation succeeds.
- Invalid manual-board state is shown instead of producing silent incorrect recommendations.

### Phase 11 — Draft rehearsal and release checklist

Tasks:

- Run a complete mock draft using the manual board.
- Test server startup, model loading, extension installation, permissions, and connectivity.
- Test manual-board session restoration, incomplete-board recovery, and extension-origin CORS setup.
- Record dataset and model refresh timestamps.
- Write a pre-draft checklist and troubleshooting guide.
- Package a reproducible local release.

Completion gate:

- A user can follow the README from a clean environment to prepare data, train or obtain artifacts, start the server, load the extension, and get recommendations.
- The entire draft workflow works locally once the extension page is already open.
- Known limitations and fallback procedures are documented.

## 6. Testing Strategy

### Data tests

- Required columns, types, units, and season coverage.
- Unique canonical identifiers and valid source mappings.
- Plausible ranges for minutes, games, makes, attempts, and percentages.
- Snapshot provenance and checksum verification.

### Model tests

- Time-based backtesting with no leakage.
- Comparison to simple baselines.
- Per-stat errors plus downstream ranking quality.
- Separate evaluation for rookies, low-minute players, injured players, and established players.

### Ranking tests

- Percentage categories respect shooting volume.
- TO rewards lower totals.
- Injury penalties remain bounded.
- Position eligibility and remaining slots affect recommendations.
- Next-pick survival affects opportunity cost.
- Recommendation explanations agree with score components.

### Extension tests

- Generated player-index coverage, manual-board state derivation, session persistence, and explicit-click requests.
- Loading, empty, stale, invalid-board, server-offline, and success states.
- No automated draft submission.

### Performance tests

- Cold server startup measured separately from recommendation latency.
- Warm API p50 and p95 latency.
- End-to-end extension click-to-render latency.
- Largest expected available-player pool and roster payload.

## 7. Reproducibility and Data Governance

- Raw source snapshots will be immutable and excluded from Git unless their license and size make committing appropriate.
- Each processed dataset will reference source snapshots, transformation version, creation timestamp, and schema version.
- Model artifacts will store training seasons, feature list, code version, evaluation results, and dataset fingerprints.
- The repository will cite sources without implying that public accessibility permits unrestricted redistribution.
- Secrets, authenticated ESPN session data, invite tokens, and scraped ESPN page content will not be written to datasets or logs.

## 8. Decisions Recorded

- Historical eligibility records are the position authority for the manual board.
- Flask binds to `127.0.0.1:8765`; prepared local artifacts are required and no prebuilt fallback or startup training is supported.
- The extension is a closable in-page manual panel backed by a bundled player index.
- ESPN page parsing is out of scope for the manual workflow.

## 9. Recommended Execution Order

Execute phases in numeric order. Phases 3–5 can be iterated independently after Phase 2 establishes stable datasets and identities. Phase 9 depends on the Phase 8 API contract and prepared player-index inputs; Phase 10 validates the complete manual-board workflow.

The user will explicitly authorize each phase before implementation begins.
