# Phase 11 Draft Rehearsal Record

Complete this record on the target Mac for each draft-ready artifact refresh. Do
not commit it with extension IDs, local paths, or generated artifacts; save the
completed copy beside the local release evidence.

## Release verification

- [ ] Archive filename and SHA-256 match its adjacent manifest.
- [ ] Manifest Git revision, package version, Python 3.12 runtime, Node 22 runtime,
  `requirements.lock`, and `extension/package-lock.json` are recorded.
- [ ] Clean extraction completed `make install` and `make check` successfully.
- [ ] The archive contains no raw/processed data, model artifacts, generated player index,
  built extension output, virtual environments, or secrets.

## Artifact refresh record

| Item | Version or fingerprint | Refreshed at (UTC) | Verified |
| --- | --- | --- | --- |
| Phase 4 projections | | | |
| Phase 5 injury assessments | | | |
| Phase 6 reference distribution | | | |
| Player index | | | |
| Recommendation model/configuration | | | |

- [ ] `GET /api/v1/health` reports `ready`.
- [ ] `GET /api/v1/metadata` matches the prepared artifact timestamps.
- [ ] The extension was rebuilt and loaded unpacked; its displayed ID was used in
  `FANTASY_PICKER_EXTENSION_ORIGIN` before starting the API.

## Full 156-pick rehearsal

- [ ] Record all 156 simulated snake picks in the manual board and receive advice at each
  of the 13 personal turns.
- [ ] Refresh the ESPN page after recording picks and confirm session board restoration.
- [ ] Trigger an incomplete/not-your-turn board error, correct it manually, and continue.
- [ ] Trigger an unavailable or timed-out service response, retain the board, and use
  **Retry suggestions** after recovery.
- [ ] With the extension page already open, disconnect external networking and obtain a
  local recommendation without ESPN or another remote request.
- [ ] Save the Phase 10 benchmark JSON for early, middle, and late boards; total p95 is
  below 10 seconds.

## Troubleshooting and limits

| Symptom | Recovery |
| --- | --- |
| API health is unavailable | Rebuild the missing Phase 4/5/6 artifact, then restart `fantasy-picker serve`. |
| Browser reports a CORS or unavailable service error | Reload the unpacked extension, copy its current ID, export the matching origin, and restart the API. |
| Port 8765 is busy | Stop the process using the port before starting the local service again. |
| Freshness warning | Rebuild the dated projections, injury assessment, and reference artifacts, then rebuild the player index and extension. |
| Board is invalid or not at your turn | Correct the selected draft slot and manually add/remove the relevant players; the extension will not guess. |
| Board did not restore | Confirm the current Chrome session is still open; session storage intentionally clears after the browser session ends. |
| Request exceeds five seconds | Confirm local artifacts are valid and the API is running, then use **Retry suggestions**. |

The extension never reads ESPN page content, never submits a draft pick, and does not need
external networking after startup. It does not redistribute data or generated model artifacts.
