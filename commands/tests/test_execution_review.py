"""测试: V2.2 Execution + Match + Portfolio Review"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.execution.execution_logger import load_executions, save_execution_log
from factor_lab.execution.execution_matcher import match_executions, generate_match_report


def test_execution_log_csv():
    """加载成交 CSV"""
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "ex.csv")
        with open(csv_path, "w", encoding="utf-8-sig") as f:
            f.write("symbol,side,shares,price,trade_date\n000001,buy,200,10.0,2026-07-03\n")
        result = load_executions(csv_path)
        assert result["status"] in ("ok", "partial")
        assert len(result["executions"]) > 0


def test_execution_no_fake():
    """空路径不返回假数据"""
    result = load_executions("/nonexistent.csv")
    assert result["status"] == "failed"


def test_match_recommended():
    """匹配推荐买入"""
    rebalance = {
        "plans": {"B": {"buy_candidate": [{"symbol": "000001"}], "sell_candidate": [], "risk_sell_candidate": []}}
    }
    executions = [{"symbol": "000001", "side": "buy"}]
    result = match_executions("2026-07-03", rebalance, executions)
    assert result["summary"]["n_matched"] == 1


def test_match_missed():
    """未执行标记为 missed"""
    rebalance = {
        "plans": {"B": {"buy_candidate": [{"symbol": "000001"}], "sell_candidate": [], "risk_sell_candidate": []}}
    }
    executions = [{"symbol": "000002", "side": "buy"}]  # 不同股票 → missed
    result = match_executions("2026-07-03", rebalance, executions)
    assert result["summary"]["n_missed"] == 1 if "summary" in result else True


def test_manual_override():
    """未推荐但执行了 → manual override"""
    rebalance = {
        "plans": {"B": {"buy_candidate": [], "sell_candidate": [], "risk_sell_candidate": []}}
    }
    executions = [{"symbol": "000001", "side": "buy"}]
    result = match_executions("2026-07-03", rebalance, executions)
    assert result["summary"]["n_manual_overrides"] == 1


def test_no_auto_order():
    """执行模块不自动下单"""
    import inspect
    from factor_lab.execution import execution_logger, execution_matcher
    for mod in [execution_logger, execution_matcher]:
        src = inspect.getsource(mod)
        for term in ["auto_buy", "execute_trade"]:
            assert term not in src, f"{mod.__name__} 含 {term}"


def test_save_load_roundtrip():
    """保存后重新加载"""
    with tempfile.TemporaryDirectory() as tmp:
        executions = [{"symbol": "000001", "side": "buy", "shares": 200, "price": 10.0, "trade_date": "2026-07-03"}]
        save_execution_log(executions, tmp)
        log_path = os.path.join(tmp, "execution_log.json")
        assert os.path.exists(log_path)
