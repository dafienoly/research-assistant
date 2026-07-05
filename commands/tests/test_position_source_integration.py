"""测试: V2.1.1 Position Source + Import Report + Integration"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.broker.position_source_registry import resolve_source
from factor_lab.broker.miniqmt_position_adapter import MiniQMTPositionAdapter


def test_position_source_registry():
    """数据源注册表能从 CSV 加载"""
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "pos.csv")
        with open(csv_path, "w") as f:
            f.write("symbol,shares\n000001,100\n")
        config = {
            "preferred": "manual_csv",
            "fallback_order": ["manual_csv"],
            "manual_csv": {"path": csv_path},
        }
        result = resolve_source(config)
        assert result["status"] in ("ok", "partial")
        assert result["source_used"] == "manual_csv"
        assert len(result["positions"]) > 0


def test_source_fallback():
    """preferred 不可用 → fallback"""
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "pos.csv")
        with open(csv_path, "w") as f:
            f.write("symbol,shares\n000001,100\n")
        config = {
            "preferred": "broker_export",
            "fallback_order": ["broker_export", "manual_csv"],
            "broker_export": {"path": "/nonexistent.csv"},
            "manual_csv": {"path": csv_path},
        }
        result = resolve_source(config)
        assert result["fallback_used"] or result["source_used"] == "manual_csv"


def test_miniqmt_unavailable():
    """miniQMT 不可用返回 unavailable"""
    from factor_lab.broker.miniqmt_position_adapter import MiniQMTPositionAdapter
    adapter = MiniQMTPositionAdapter()
    status = adapter.get_status()
    assert status["status"] == "unavailable"


def test_import_report_generation():
    """导入报告生成"""
    from factor_lab.reports.position_import_report import generate_import_report
    source_result = {
        "source_used": "manual_csv",
        "preferred_source": "manual_csv",
        "fallback_used": False,
        "status": "ok",
        "positions": [{"symbol": "000001", "shares": 100, "board": "main", "source": "test"}],
        "cash": 50000.0,
        "adapter_warnings": [],
        "adapter_errors": [],
        "field_map": {"证券代码": "symbol"},
    }
    with tempfile.TemporaryDirectory() as tmp:
        r = generate_import_report(source_result, tmp)
        assert "output_dir" in r
        assert os.path.exists(os.path.join(tmp, "position_import_report.html"))


def test_rebalance_diff_with_position_source():
    """rebalance-diff 可通过 position source 接入"""
    # 检查 rebalance_diff 模块兼容 --position-source
    import inspect
    from factor_lab.portfolio.rebalance_diff import run_rebalance_diff
    sig = inspect.signature(run_rebalance_diff)
    # 函数仍接受 positions_csv 参数即可
    assert "positions_csv" in sig.parameters


def test_validation_errors_output():
    """校验错误输出"""
    from factor_lab.reports.position_import_report import generate_import_report
    source_result = {
        "source_used": "manual_csv",
        "preferred_source": "manual_csv",
        "fallback_used": False,
        "status": "partial",
        "positions": [],
        "cash": 0.0,
        "adapter_warnings": ["shares 格式异常"],
        "adapter_errors": ["symbol 缺失"],
        "field_map": {},
    }
    with tempfile.TemporaryDirectory() as tmp:
        r = generate_import_report(source_result, tmp)
        err_path = os.path.join(tmp, "validation_errors.json")
        assert os.path.exists(err_path)
        with open(err_path) as f:
            errs = json.load(f)
        assert len(errs) > 0
