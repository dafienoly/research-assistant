from __future__ import annotations

from pathlib import Path

from vnext_ci_gate import VNextCIGate


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_vnext_ci_gate_accepts_reviewed_locks_and_boundaries() -> None:
    result = VNextCIGate().run(PROJECT_ROOT)

    assert result["status"] == "OK"
    assert result["errors"] == []
    assert result["checks"]["ui_api_broker_boundary"]["findings"] == []
    assert result["checks"]["secret_scan"]["findings"] == []
    assert result["checks"]["core_prohibited_packages"] == []
