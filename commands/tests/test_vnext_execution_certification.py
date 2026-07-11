from __future__ import annotations

import json
from pathlib import Path

from factor_lab.vnext.contracts import sha256_payload
from factor_lab.vnext.execution_certification import ExecutionCertificationLab


def _write_snapshot(root: Path) -> None:
    data_path = root / "data" / "snapshot" / "data.json"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "ts_code": "512480.SH",
            "trade_date": "20260710",
            "close": 1.369,
            "vol": 25_192_139.88,
        }
    ]
    data_path.write_text(json.dumps(rows), encoding="utf-8")
    artifact_root = root / "artifacts" / "vnext"
    artifact_root.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "data_snapshot_id": "vnext-test-snapshot",
        "snapshot_id_valid": True,
        "silent_fallback_used": False,
        "entries": [
            {
                "instrument_id": "512480.SH",
                "dataset": "fund_daily",
                "provider": "tushare",
                "verified": True,
                "data_file": str(data_path),
                "raw_snapshot_id": "raw-test",
                "content_hash": sha256_payload(rows),
                "quality_status": "OK",
            }
        ],
    }
    (artifact_root / "snapshot_manifest.json").write_text(json.dumps(snapshot), encoding="utf-8")


def test_execution_certification_uses_signed_one_time_envelopes(tmp_path: Path) -> None:
    _write_snapshot(tmp_path)
    output = tmp_path / "artifacts" / "vnext" / "execution_certification.json"

    result = ExecutionCertificationLab().run(tmp_path, as_of="2026-07-10", output_path=output)

    assert result["status"] == "OK"
    assert result["real_broker_called"] is False
    assert result["production_recommendation"] is False
    assert result["market_evidence"]["content_hash_verified"] is True
    assert result["runs"]["PAPER"]["execution"]["status"] == "PAPER_FILLED"
    assert result["runs"]["SHADOW"]["execution"]["status"] == "SHADOW_RECORDED"
    assert result["runs"]["LIVE_DRY_RUN"]["execution"]["status"] == "LIVE_DRY_RUN"
    assert all(run["nonce_replay"]["reason"] == "approval_nonce_reused" for run in result["runs"].values())
    assert all(run["ledger_chain"]["valid"] is True for run in result["runs"].values())
    assert output.exists()


def test_execution_certification_rejects_tampered_market_evidence(tmp_path: Path) -> None:
    _write_snapshot(tmp_path)
    data_path = tmp_path / "data" / "snapshot" / "data.json"
    data_path.write_text("[]", encoding="utf-8")

    try:
        ExecutionCertificationLab().run(
            tmp_path,
            as_of="2026-07-10",
            output_path=tmp_path / "artifacts" / "vnext" / "execution_certification.json",
        )
    except ValueError as exc:
        assert "content hash mismatch" in str(exc)
    else:
        raise AssertionError("tampered market evidence must be rejected")
