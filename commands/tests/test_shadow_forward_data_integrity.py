from __future__ import annotations

from factor_lab.adaptive.shadow_forward import StandingShadowForward


def test_missing_market_returns_block_shadow_result_instead_of_fabricating_zero(tmp_path, monkeypatch):
    monkeypatch.setattr("factor_lab.adaptive.shadow_forward.BASE", tmp_path)
    runner = StandingShadowForward()
    monkeypatch.setattr(runner, "_fetch_strategy_candidates", lambda _date: ["600000.SH"])
    monkeypatch.setattr(runner, "_fetch_universe", lambda _date: ["600000.SH", "000001.SZ"])
    monkeypatch.setattr(runner, "_compute_stock_returns", lambda _symbols, _date: {"600000.SH": 0.01})
    monkeypatch.setattr(runner, "_fetch_csi300_return", lambda _date: None)

    result = runner.run_daily("2026-07-10")

    assert result["status"] == "BLOCKED"
    assert result["blocking_reason"] == "incomplete_real_market_returns"
    assert result["missing_symbols"] == ["000001.SZ"]
    assert result["shadow_return"] is None
    assert result["equal_weight_return"] is None
    assert result["csi300_return"] is None
