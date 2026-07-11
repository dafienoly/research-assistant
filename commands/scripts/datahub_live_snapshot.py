#!/usr/bin/env python3
"""Refresh canonical live snapshot under the global DataHub writer lock."""

from __future__ import annotations

import json

from factor_lab.datahub_ingestion.live_snapshot import LiveSnapshotIngestion


def main() -> int:
    try:
        manifest = LiveSnapshotIngestion().fetch_locked()
    except RuntimeError as error:
        if "writer active" not in str(error):
            raise
        print(json.dumps({"status": "DEFERRED", "reason": "datahub_writer_active"}))
        return 75
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
