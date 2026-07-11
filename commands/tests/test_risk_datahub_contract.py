from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd

from factor_lab.risk.pretrade_risk_check import run_pretrade_risk_check
from factor_lab.risk.regulatory_watchlist import RegulatoryWatchlist
from factor_lab.risk.st_watchlist import STWatchlist


ROOT = Path(__file__).resolve().parents[2]


def test_st_watchlist_reads_canonical_reference_without_writes(tmp_path: Path) -> None:
    source = tmp_path / "stock_basic.csv"
    pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "600001.SH", "600002.SH"],
            "name": ["平安银行", "ST示例", "*ST风险"],
            "list_status": ["L", "L", "L"],
        }
    ).to_csv(source, index=False)
    watchlist = STWatchlist(source)
    assert watchlist.ensure_fresh() == 2
    assert watchlist.is_st("600001") is True
    assert watchlist.get_st_status("600002.SH") == "star_st"
    assert watchlist.is_st("000001") is False


def test_missing_regulatory_truth_is_explicit_and_blocks_pretrade_buy(tmp_path: Path) -> None:
    stock_basic = tmp_path / "stock_basic.csv"
    pd.DataFrame(
        {"ts_code": ["000001.SZ"], "name": ["平安银行"], "list_status": ["L"]}
    ).to_csv(stock_basic, index=False)
    st = STWatchlist(stock_basic)
    regulatory = RegulatoryWatchlist(tmp_path / "missing_regulatory.json")
    frame = pd.DataFrame(
        {
            "date": ["2026-07-10"],
            "symbol": ["000001"],
            "close": [10.0],
            "amount": [10_000_000.0],
        }
    )
    result = run_pretrade_risk_check(
        [{"symbol": "000001"}],
        frame,
        "2026-07-10",
        st_watchlist=st,
        regulatory_watchlist=regulatory,
    )
    assert result["status"] == "fail"
    assert result["n_data_unavailable"] == 1
    assert "regulatory_truth_unavailable" in result["details"][0]["risk_type"]


def test_risk_consumers_do_not_import_network_providers() -> None:
    for relative in (
        "commands/factor_lab/risk/st_watchlist.py",
        "commands/factor_lab/risk/regulatory_watchlist.py",
    ):
        path = ROOT / relative
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        assert not any(name.startswith(("akshare", "requests", "urllib")) for name in imported)
