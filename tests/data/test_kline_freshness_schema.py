"""Retired legacy K-line checks.

The old test suite walked ``data/market/daily_kline`` and required a root
``data/manifest.json``.  Those paths are no longer the governed DataHub
contract, and keeping the test active made a full pytest run report false
failures (or encourage someone to recreate an untracked data mirror).

Canonical, bounded K-line checks live in
``commands/tests/data/test_kline_freshness_schema.py``.  Full coverage,
freshness, integrity, and missing-data decisions belong to the DataHub audit
manifests, not to a repository-wide test that scans data files.
"""

import pytest


pytestmark = pytest.mark.skip(
    reason=(
        "legacy data/market/daily_kline checks retired; use canonical "
        "DataHub tests and audit manifests"
    )
)


def test_legacy_kline_checks_retired() -> None:
    """Keep a discoverable test node while preventing legacy data scanning."""
    pytest.skip("legacy K-line checks are retired")
