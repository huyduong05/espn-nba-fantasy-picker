#!/usr/bin/env python3
"""Create the verified source-only release archive for the current checkout."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fantasy_picker.release import ReleaseError, create_release


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        result = create_release(root, root / "dist")
    except ReleaseError as error:
        print(f"Release packaging failed: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "archive": result.archive.as_posix(),
                "manifest": result.manifest.as_posix(),
                "sha256": result.sha256,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
