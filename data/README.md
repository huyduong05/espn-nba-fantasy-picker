# Local Data Layout

The contents of `raw/`, `interim/`, and `processed/` are generated and ignored by
Git. Their placeholder files keep the directory structure available in a clean
checkout.

- `raw/`: immutable source snapshots and adjacent provenance manifests.
- `interim/`: reproducible normalized outputs that may still contain source IDs.
- `processed/`: canonical, model-ready datasets.

Phase 1 acquisition commands are documented in the root README. Raw snapshots
must follow the provenance and checksum rules in `docs/contracts.md`. The
generated `coverage-report.json` measures the latest local batch and is ignored
by Git because it describes local downloaded state.

