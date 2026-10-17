# ESPN NBA Fantasy Draft Assistant

A local-first assistant for a 12-team, head-to-head, nine-category ESPN NBA fantasy
draft. It maintains a manual draft board, evaluates roster needs, and returns local
recommendations through a Chrome extension and a localhost API.

The extension never reads ESPN page content and never submits draft picks. You enter
the draft board manually; the assistant uses that board to calculate available players,
snake-draft state, roster fit, category needs, projection uncertainty, and injury risk.

## Requirements

- macOS
- Python 3.12.x
- Node.js 22 or newer and npm
- Google Chrome desktop with Developer mode available
- Internet access for the initial data download and dependency installation

Draft-time recommendations run locally after data and model artifacts have been prepared.

## Install dependencies

From the repository root:

```bash
make install
make test
```

`make install` creates `.venv`, installs the locked Python dependencies from
`requirements.lock`, installs the package in editable mode, and installs the locked
extension dependencies from `extension/package-lock.json`.

Useful validation commands:

```bash
.venv/bin/fantasy-picker validate-contracts
make check
```

Run `make check` after the local data and model artifacts have been prepared because it
also rebuilds the extension player index.

## Prepare local data and model artifacts

The following commands download source snapshots, normalize them, and create the files
used by the local API:

```bash
.venv/bin/fantasy-picker data fetch-all
.venv/bin/fantasy-picker data coverage
.venv/bin/fantasy-picker data normalize
.venv/bin/fantasy-picker model train
.venv/bin/fantasy-picker model project
.venv/bin/fantasy-picker model phase4
.venv/bin/fantasy-picker injury score --as-of YYYY-MM-DD
.venv/bin/fantasy-picker ranking build-reference
```

Replace `YYYY-MM-DD` with the intended draft-date snapshot. The main generated inputs
are:

```text
data/processed/players.jsonl
data/processed/eligibility.jsonl
data/processed/injury_events.jsonl
artifacts/phase3/projections.jsonl
artifacts/phase4/rookie_adjusted_projections.jsonl
artifacts/phase5/injury_assessments.jsonl
artifacts/phase6/reference_distribution.json
```

The historical injury archive ends in 2019-20. Add exact reviewed source-name mappings
to `injury_manual_mappings` in [config/identity-review.yaml](config/identity-review.yaml)
before normalization if historical injury events are needed. Unmapped names are written
to `data/processed/unresolved_injury_matches.json` and are never linked automatically.
Current injury status is not supplied by the historical archive.

Use `--refresh` on a fetch command only when a new immutable source snapshot is intended.
The downloaded data and generated artifacts are local and ignored by Git.

## Build and load the Chrome extension

Build the player index and extension bundle:

```bash
.venv/bin/fantasy-picker extension build-player-index
npm --prefix extension run build
```

In Chrome:

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select the repository’s `extension/dist/` directory.
5. Copy the extension ID displayed by Chrome.

The extension does not open a toolbar popup. It injects a **Fantasy Picker** button into
matching ESPN Fantasy Basketball pages.

## Start the local API

Use the extension ID from Chrome to restrict API access to this extension:

```bash
export FANTASY_PICKER_EXTENSION_ORIGIN='chrome-extension://<your-extension-id>'
.venv/bin/fantasy-picker serve
```

Leave this terminal running. The service listens only on `127.0.0.1:8765` and makes no
network requests after startup.

Verify readiness from a second terminal:

```bash
curl --fail --silent http://127.0.0.1:8765/api/v1/health
curl --fail --silent http://127.0.0.1:8765/api/v1/metadata
```

The health response must contain `"status":"ready"`. If it reports unavailable, rebuild
the missing local artifact and restart the service.

## Open and use the Fantasy Picker panel

Open an ESPN Fantasy Basketball page matching:

```text
https://fantasy.espn.com/basketball/*
```

Refresh the page after loading or reloading the extension. Click the **Fantasy Picker**
button above ESPN Fantasy Chat. The right-side drawer opens above the button.

In the panel:

- Search by player name or alias and choose from the top five matches.
- Add the selected player to **My roster** or mark them as **Taken** at any time.
- Maintain the board manually as the draft progresses.
- Click **Suggest picks** whenever you want an updated recommendation set.
- Review the recommendation score, categories, injury adjustment, warnings, and data freshness.

The board is stored only for the current browser session. The extension does not click or
submit ESPN draft selections.

If the panel does not appear, confirm that the page is an ESPN Fantasy Basketball URL,
reload the extension from `chrome://extensions`, and refresh the ESPN page. The extension’s
**Errors** button in Chrome can show failed content-script or bundled-index errors.

## Run the benchmark

With the extension loaded and the API running, open:

```text
chrome-extension://<your-extension-id>/benchmark.html
```

Click **Run benchmark**. It runs early-, middle-, and late-round boards through the real
extension worker and localhost API, then prints JSON timing results. Save the online and
offline outputs with your local release evidence.

For the offline run, leave the benchmark page and local API ready, turn off Wi-Fi and any
VPN or Ethernet connection, then run the benchmark again. Localhost remains available while
external networking is disconnected.

The target total click-to-render p95 is below 10 seconds. Other targets are:

```text
Manual board validation       <= 0.1 s
Extension-to-localhost call   <= 0.2 s
Candidate scoring             <= 4.0 s
Response rendering            <= 0.5 s
```

## Main components

- `src/fantasy_picker/data`: source acquisition, provenance verification, normalization, and identity review.
- `src/fantasy_picker/models`: projections, rookie adjustments, and injury scoring.
- `src/fantasy_picker/ranking`: roster evaluation and draft-aware recommendations.
- `src/fantasy_picker/api`: the local Flask service used by the extension.
- `extension/src`: the manual draft board, player search, recommendation UI, and benchmark.
- `schemas/v1`: shared JSON contracts used by the data pipeline, API, and extension.
- `config`: source decisions, identity mappings, projection settings, and scoring settings.

## Data and licensing notes

Source snapshots are stored under `data/raw/` with provenance manifests. Processed datasets
are stored under `data/processed/`, and model outputs are stored under `artifacts/`; these
directories are local and excluded from source releases.

The project records source licensing and usage limitations in
[docs/sources.md](docs/sources.md). In particular, NBA.com snapshots are retained for the
user-directed educational workflow and remain subject to NBA.com terms. The historical injury
archive is a separate CC0 source and does not provide current injury status.

See [docs/contracts.md](docs/contracts.md) for schema, identity, nullability, and provenance
rules.
