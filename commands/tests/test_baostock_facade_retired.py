from __future__ import annotations

from pathlib import Path

import pytest

import baostock_data


def test_baostock_facade_delegates_once_to_canonical_owners(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        baostock_data,
        "_run_daily_datahub",
        lambda: calls.append("daily") or {"status": "OK"},
    )

    class Projection:
        def __init__(self, root: Path) -> None:
            assert root == baostock_data.ROOT

        def build(self, target: str) -> dict:
            calls.append(target)
            return {"status": "OK", "rows": 1}

    monkeypatch.setattr(baostock_data, "FactorInputProjection", Projection)

    result = baostock_data.run_all()

    assert calls == ["daily", "fundamentals"]
    assert result["status"] == "OK"


def test_baostock_facade_rejects_legacy_per_code_scope() -> None:
    with pytest.raises(ValueError, match="retired"):
        baostock_data.run_all(["688012"])


def test_baostock_facade_contains_no_provider_or_parallel_writer() -> None:
    source = Path(baostock_data.__file__).read_text(encoding="utf-8").lower()
    forbidden = ("import baostock", "query_profit", "query_balance", "query_stock_industry", "csv.dictwriter", "open(")
    assert all(token not in source for token in forbidden)
    assert "datahub_cron.sh" in source
    assert "factorinputprojection" in source
