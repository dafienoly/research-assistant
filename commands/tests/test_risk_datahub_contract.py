from __future__ import annotations

import ast
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from factor_lab.risk.pretrade_risk_check import run_pretrade_risk_check
from factor_lab.risk.regulatory_watchlist import RegulatoryWatchlist
from factor_lab.risk.st_watchlist import STWatchlist


ROOT = Path(__file__).resolve().parents[2]


def write_reference_manifest(source: Path) -> None:
    payload = {
        "status": "OK",
        "generated_at": datetime.now().astimezone().isoformat(),
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "conflicts": [],
    }
    (source.parent / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_st_watchlist_reads_canonical_reference_without_writes(tmp_path: Path) -> None:
    source = tmp_path / "stock_basic.csv"
    pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "600001.SH", "600002.SH"],
            "name": ["平安银行", "ST示例", "*ST风险"],
            "list_status": ["L", "L", "L"],
        }
    ).to_csv(source, index=False)
    write_reference_manifest(source)
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
    write_reference_manifest(stock_basic)
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


def test_st_truth_rejects_hash_mismatch_and_stale_manifest(tmp_path: Path) -> None:
    source = tmp_path / "stock_basic.csv"
    source.write_text("ts_code,name,list_status\n600001.SH,ST示例,L\n", encoding="utf-8")
    write_reference_manifest(source)
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    mismatched = STWatchlist(source)
    assert mismatched.load_cache() is False
    assert "hash mismatch" in (mismatched.error or "")

    write_reference_manifest(source)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["generated_at"] = "2020-01-01T00:00:00+08:00"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    stale = STWatchlist(source)
    assert stale.load_cache() is False
    assert "stale" in (stale.error or "")
