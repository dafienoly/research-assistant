#!/usr/bin/env python3
"""Retired one-off strategy promotion script.

Production alpha lifecycle changes must originate from versioned evidence,
OOS validation, Paper/Shadow records and an explicit human approval.  This
entry remains only to fail loudly for old operator instructions.
"""

from __future__ import annotations


def main() -> None:
    raise SystemExit(
        "retired: use the governed alpha candidate -> OOS -> Paper/Shadow -> human approval workflow"
    )


if __name__ == "__main__":
    main()
