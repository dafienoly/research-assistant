from pathlib import Path

from factor_lab.portfolio.position_loader import PositionLoader
import factor_lab.broker.miniqmt_position_adapter as adapter_module


def test_position_loader_uses_qmt_bridge_adapter(monkeypatch) -> None:
    monkeypatch.setattr(
        adapter_module.MiniQMTPositionAdapter,
        "load_positions",
        lambda _self: [{"stock_code": "688012", "volume": 200, "can_use_volume": 100, "last_price": 100, "open_price": 90}],
    )
    monkeypatch.setattr(
        adapter_module.MiniQMTPositionAdapter,
        "load_account_asset",
        lambda _self: {"status": "ok", "cash": 1000},
    )
    loader = PositionLoader()
    positions = loader.from_qmt()
    assert positions[0]["symbol"] == "688012"
    assert positions[0]["available_shares"] == 100
    assert loader.cash == 1000
    assert loader.errors == []


def test_position_loader_qmt_failure_is_not_silent(monkeypatch) -> None:
    monkeypatch.setattr(
        adapter_module.MiniQMTPositionAdapter,
        "load_positions",
        lambda _self: (_ for _ in ()).throw(RuntimeError("bridge unavailable")),
    )
    loader = PositionLoader()
    assert loader.from_qmt() == []
    assert loader.partial is True
    assert loader.errors == ["QMT Bridge 持仓读取失败: bridge unavailable"]


def test_position_loader_has_no_legacy_miniqmt_account_path() -> None:
    source = Path(__import__("factor_lab.portfolio.position_loader", fromlist=["x"]).__file__).read_text(encoding="utf-8")
    assert "from factor_lab.miniqmt" not in source
    assert "MiniQMTPositionAdapter" in source
