from __future__ import annotations

import json

from factor_lab.vnext.contracts import DataStatus
from factor_lab.vnext.data_audit import export_vnext_data_audit


def test_data_audit_export_blocks_production_when_gaps_or_stale_data_remain(tmp_path):
    data = tmp_path / "data"
    market = data / "normalized" / "market"
    market.mkdir(parents=True)
    (market / "000001.SZ.csv").write_text("trade_date,close\n20260710,10\n", encoding="utf-8")
    (market / "000002.SZ.csv").write_text("trade_date,close\n20260710,11\n", encoding="utf-8")
    (market / "valuation_000001.SZ.csv").write_text("trade_date,pb\n20260710,1.2\n", encoding="utf-8")
    (market / "valuation_999999.SH.csv").write_text("trade_date,pb\n20260710,1.3\n", encoding="utf-8")
    (data / "universes.json").write_text(
        json.dumps(
            {
                "universes": {
                    "U0": {
                        "stocks": [
                            {"ts_code": "000001.SZ"},
                            {"ts_code": "000002.SZ"},
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    audit = data / "audit"
    audit.mkdir()
    (audit / "data_gap_report.json").write_text(
        json.dumps({"gaps": [], "summary": {"total_gaps": 0}}),
        encoding="utf-8",
    )
    (audit / "data_freshness_report.json").write_text(
        json.dumps(
            {
                "check_time": "2026-07-11T01:00:00+08:00",
                "overall_status": "stale",
                "blocking": True,
                "files": [{"path": "market/live_snapshot.csv", "status": "stale"}],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "artifacts" / "vnext"
    output.mkdir(parents=True)
    (output / "snapshot_manifest.json").write_text(
        json.dumps({"status": DataStatus.OK.value}),
        encoding="utf-8",
    )

    result = export_vnext_data_audit(tmp_path, as_of="2026-07-10", output_root=output)

    gap = json.loads((output / "data_gap_report.json").read_text(encoding="utf-8"))
    freshness = json.loads((output / "data_freshness_report.json").read_text(encoding="utf-8"))
    assert result["status"] == DataStatus.PARTIAL.value
    assert result["formal_ml_status"] == DataStatus.BLOCKED.value
    assert result["shadow_status"] == DataStatus.BLOCKED.value
    assert "critical_freshness_check_failed" in result["blocking_reasons"]
    assert gap["status"] == DataStatus.PARTIAL.value
    assert "daily_valuation" in gap["partial_datasets"]
    valuation = next(item for item in gap["coverage"] if item["dataset"] == "daily_valuation")
    assert valuation["observed_files_or_rows"] == 2
    assert valuation["matched_expected_symbols"] == 1
    assert valuation["missing_symbols"] == ["000002.SZ"]
    assert valuation["extra_symbols"] == ["999999.SH"]
    assert valuation["coverage_ratio"] == 0.5
    assert freshness["production_signal_eligible"] is False
    assert result["no_mock_or_fallback"] is True
