# Local Data Layout

The contents of `raw/`, `interim/`, and `processed/` are generated and ignored by
Git. Their placeholder files keep the directory structure available in a clean
checkout.

- `raw/`: immutable source snapshots and adjacent provenance manifests.
- `interim/`: reproducible normalized outputs that may still contain source IDs.
- `processed/`: canonical, model-ready datasets.

No downloader exists in Phase 0. Phase 1 will select and cite sources before it
implements acquisition. Raw snapshots must follow the provenance and checksum
rules in `docs/contracts.md`.

