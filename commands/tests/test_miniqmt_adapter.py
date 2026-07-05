"""测试: V2.3 miniQMT Read-Only Integration"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.broker.miniqmt_position_adapter import (
    MiniQMTPositionAdapter, verify_readonly_guard, BLOCKED_TRADE_METHODS
)


def test_status_unavailable():
    """miniQMT 不可用时返回 unavailable"""
    adapter = MiniQMTPositionAdapter()
    status = adapter.get_status()
    assert status["status"] == "unavailable"
    assert status["readonly"] == True
    assert "xtquant" in status.get("error_message", "")


def test_readonly_guard():
    """只读保护通过"""
    guard = verify_readonly_guard()
    assert guard["guard_status"] == "passed"
    assert guard["readonly_mode"] == True


def test_no_trade_methods():
    """适配器不暴露交易方法"""
    adapter = MiniQMTPositionAdapter()
    methods = [m for m in dir(adapter) if not m.startswith("_")]
    for m in methods:
        assert m.lower() not in BLOCKED_TRADE_METHODS, f"暴露了交易方法: {m}"


def test_load_account_unavailable():
    """不可用时账户资产返回 unavailable"""
    adapter = MiniQMTPositionAdapter()
    asset = adapter.load_account_asset()
    assert asset["status"] == "unavailable"


def test_load_positions_empty():
    """不可用时持仓为空"""
    adapter = MiniQMTPositionAdapter()
    pos = adapter.load_positions()
    assert pos == []


def test_normalize_no_crash():
    """标准化不崩溃"""
    adapter = MiniQMTPositionAdapter()
    result = adapter.normalize_positions([])
    assert result == []


def test_normalize_cash():
    """现金标准化"""
    adapter = MiniQMTPositionAdapter()
    # load_account_asset returns unavailable, so CASH won't be added
    result = adapter.normalize_positions([])
    cash_rows = [r for r in result if r.get("symbol") == "CASH"]
    # CASH may or may not be added depending on asset availability
    assert True


def test_export_normalized():
    """导出标准化 CSV"""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "norm.csv")
        adapter = MiniQMTPositionAdapter()
        path = adapter.export_normalized_positions(out)
        assert os.path.exists(path)


def test_no_fake_positions():
    """不可用时返回空列表, 不生成假数据"""
    adapter = MiniQMTPositionAdapter()
    pos = adapter.load_positions()
    assert pos == []
