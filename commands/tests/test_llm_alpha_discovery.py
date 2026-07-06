"""测试: V3.7 LLM Alpha Discovery"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

from factor_lab.alpha.llm_alpha_discovery import (
    AlphaSpecValidator,
    submit_candidate,
    list_candidates,
    get_candidate,
    approve_candidate,
    reject_candidate,
    generate_rejected_reason_report,
    CANDIDATES_ROOT,
    CANDIDATES_INDEX,
)


# ─── 辅助函数 ─────────────────────────────────────────────

_COUNTER = 0


def _unique_name(prefix="test"):
    """生成唯一名称避免测试间冲突"""
    global _COUNTER
    _COUNTER += 1
    ts = datetime.now(CST).strftime("%H%M%S%f")
    return f"{prefix}_{ts}_{_COUNTER}"


def _clean_candidates():
    """清理测试产生的候选目录"""
    if CANDIDATES_ROOT.exists():
        import shutil
        shutil.rmtree(CANDIDATES_ROOT)


def _make_valid_candidate():
    """构造一个合法的 AlphaSpec 候选"""
    return {
        "name": _unique_name("alpha"),
        "description": "基于动量的测试因子",
        "hypothesis": "过去20日收益高的股票未来5日继续跑赢",
        "factor_expression": "rank(ts_mean(close, 20) / ts_mean(close, 60) - 1)",
        "universe": "all_watchlist",
        "data_requirements": ["close", "volume"],
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "risk_constraints": {"max_position_weight": 0.25, "max_drawdown": 0.15},
        "risk_notes": "动量因子在震荡市中可能失效",
        "evidence": "A股市场动量效应在20日窗口显著",
    }


def _make_invalid_candidate():
    """构造一个缺少必需字段的候选"""
    return {
        "name": _unique_name("bad"),
        "description": "缺少 hypothesis 和 factor_expression",
        # 缺少 hypothesis
        # 缺少 factor_expression
        "universe": "all_watchlist",
        "data_requirements": ["close"],
        "signal_direction": "long",
        "rebalance_frequency": "daily",
        "risk_notes": "无风险说明",
        "evidence": "无证据",
    }


def _make_future_function_candidate():
    """构造一个包含未来函数的候选"""
    return {
        "name": _unique_name("future"),
        "description": "包含未来函数的因子",
        "hypothesis": "测试未来函数检测",
        "factor_expression": "ts_mean(close, -5)",
        "universe": "all_watchlist",
        "data_requirements": ["close"],
        "signal_direction": "long",
        "rebalance_frequency": "daily",
        "risk_constraints": {"max_position_weight": 0.25, "max_drawdown": 0.15},
        "risk_notes": "含未来函数",
        "evidence": "测试用例",
    }


def _make_uncomputable_candidate():
    """构造一个不可计算的候选（语法错误）"""
    return {
        "name": _unique_name("uncomp"),
        "description": "不可计算因子",
        "hypothesis": "测试不可计算检测",
        "factor_expression": "rank(close + * volume)",  # syntax error: + *
        "universe": "all_watchlist",
        "data_requirements": ["close", "volume"],
        "signal_direction": "long",
        "rebalance_frequency": "daily",
        "risk_constraints": {"max_position_weight": 0.25, "max_drawdown": 0.15},
        "risk_notes": "语法错误",
        "evidence": "测试用例",
    }


def setup_function():
    """每个测试前清理候选目录"""
    _clean_candidates()


def teardown_function():
    """每个测试后清理候选目录"""
    _clean_candidates()


# ─── Test: AlphaSpecValidator ─────────────────────────────


def test_validator_passes_valid_candidate():
    validator = AlphaSpecValidator()
    ok = validator.validate(_make_valid_candidate())
    report = validator.get_report()
    assert ok, f"合法候选应通过验证: {report['errors']}"
    assert len(report["errors"]) == 0


def test_validator_rejects_missing_fields():
    validator = AlphaSpecValidator()
    ok = validator.validate(_make_invalid_candidate())
    report = validator.get_report()
    assert not ok, "缺少字段的候选应被拒绝"
    assert len(report["errors"]) > 0
    # 检查是否检测到缺少 hypothesis
    error_fields = " ".join(report["errors"])
    assert "hypothesis" in error_fields


def test_validator_rejects_future_function():
    validator = AlphaSpecValidator()
    ok = validator.validate(_make_future_function_candidate())
    report = validator.get_report()
    assert not ok, "包含未来函数的候选应被拒绝"
    assert any("未来函数" in e for e in report["errors"])


def test_validator_rejects_uncomputable():
    validator = AlphaSpecValidator()
    ok = validator.validate(_make_uncomputable_candidate())
    report = validator.get_report()
    assert not ok, "不可计算的候选应被拒绝"
    assert any("不可计算" in e for e in report["errors"])


def test_validator_rejects_invalid_signal_direction():
    validator = AlphaSpecValidator()
    candidate = _make_valid_candidate()
    candidate["signal_direction"] = "diagonal"
    ok = validator.validate(candidate)
    assert not ok
    assert any("signal_direction" in e for e in validator.errors)


def test_validator_rejects_invalid_rebalance():
    validator = AlphaSpecValidator()
    candidate = _make_valid_candidate()
    candidate["rebalance_frequency"] = "yearly"
    ok = validator.validate(candidate)
    assert not ok
    assert any("rebalance_frequency" in e for e in validator.errors)


def test_validator_rejects_empty_expression():
    validator = AlphaSpecValidator()
    candidate = _make_valid_candidate()
    candidate["factor_expression"] = ""
    ok = validator.validate(candidate)
    assert not ok


def test_validator_rejects_too_long_expression():
    validator = AlphaSpecValidator()
    candidate = _make_valid_candidate()
    candidate["factor_expression"] = "rank(" + "close + " * 100 + "close)"
    ok = validator.validate(candidate)
    assert not ok


def test_validator_rejects_non_list_data_requirements():
    validator = AlphaSpecValidator()
    candidate = _make_valid_candidate()
    candidate["data_requirements"] = "close, volume"
    ok = validator.validate(candidate)
    assert not ok


def test_validator_passes_minimum_window():
    """window=2 应通过（最小值）"""
    validator = AlphaSpecValidator()
    candidate = _make_valid_candidate()
    candidate["factor_expression"] = "rank(ts_mean(close, 2))"
    ok = validator.validate(candidate)
    assert ok, f"window=2 应通过: {validator.errors}"


def test_validator_rejects_ts_delta_zero():
    """ts_delta(x, 0) 应被拒绝"""
    validator = AlphaSpecValidator()
    candidate = _make_valid_candidate()
    candidate["factor_expression"] = "ts_delta(close, 0)"
    ok = validator.validate(candidate)
    assert not ok


# ─── Test: submit_candidate ────────────────────────────────


def test_submit_valid_candidate_goes_to_pending_review():
    candidate = _make_valid_candidate()
    result = submit_candidate(candidate, source="test")
    assert result["status"] == "pending_review"
    assert not result.get("rejected", True)
    assert result["candidate_id"].startswith("cand_")


def test_submit_invalid_candidate_is_rejected():
    candidate = _make_invalid_candidate()
    result = submit_candidate(candidate, source="test")
    assert result["status"] == "rejected"
    assert result.get("rejected", False)
    assert len(result.get("rejected_reasons", [])) > 0


def test_submit_future_function_candidate_is_rejected():
    candidate = _make_future_function_candidate()
    result = submit_candidate(candidate, source="test")
    assert result["status"] == "rejected"
    assert result.get("rejected", False)


def test_submit_creates_candidate_directory():
    candidate = _make_valid_candidate()
    result = submit_candidate(candidate, source="test")
    cid = result["candidate_id"]
    assert (CANDIDATES_ROOT / cid).exists()
    assert (CANDIDATES_ROOT / cid / "candidate.json").exists()


def test_submit_updates_index():
    candidate = _make_valid_candidate()
    submit_candidate(candidate, source="test")
    index = json.loads(CANDIDATES_INDEX.read_text())
    assert len(index) >= 1
    assert index[-1]["name"] == candidate["name"]


def test_submit_validates_safety():
    """确保提交的候选包含安全标记"""
    candidate = _make_valid_candidate()
    result = submit_candidate(candidate, source="test")
    cid = result["candidate_id"]
    record = json.loads((CANDIDATES_ROOT / cid / "candidate.json").read_text())
    spec = record.get("spec", {})
    assert spec.get("enabled") == False
    assert spec.get("paper_enabled") == False
    assert spec.get("live_enabled") == False


# ─── Test: list_candidates / get_candidate ─────────────────


def test_list_candidates_returns_all():
    _clean_candidates()
    c1 = _make_valid_candidate()
    submit_candidate(c1, source="test")
    c2 = _make_valid_candidate()
    submit_candidate(c2, source="test")

    candidates = list_candidates()
    assert len(candidates) >= 2


def test_list_candidates_filters_by_status():
    _clean_candidates()
    c = _make_valid_candidate()
    submit_candidate(c, source="test")

    pending = list_candidates(status="pending_review")
    assert len(pending) >= 1

    approved = list_candidates(status="approved")
    assert isinstance(approved, list)


def test_get_candidate_returns_record():
    c = _make_valid_candidate()
    result = submit_candidate(c, source="test")
    cid = result["candidate_id"]

    record = get_candidate(cid)
    assert "error" not in record
    assert record["candidate_id"] == cid
    assert record["spec"]["name"] == c["name"]


def test_get_candidate_missing_returns_error():
    record = get_candidate("nonexistent_id")
    assert "error" in record


# ─── Test: approve_candidate ────────────────────────────────


def test_approve_pending_candidate():
    _clean_candidates()
    c = _make_valid_candidate()
    result = submit_candidate(c, source="test")
    cid = result["candidate_id"]

    approved = approve_candidate(cid)
    assert "error" not in approved, f"审批失败: {approved}"

    # 检查候选状态已更新
    record = get_candidate(cid)
    assert record["status"] == "approved"
    assert "alpha_id" in record


def test_approve_non_existent_returns_error():
    result = approve_candidate("nonexistent")
    assert "error" in result


def test_approve_rejected_candidate_returns_error():
    c = _make_invalid_candidate()
    result = submit_candidate(c, source="test")
    cid = result["candidate_id"]

    approved = approve_candidate(cid)
    assert "error" in approved  # 已拒绝的不能审批


# ─── Test: reject_candidate ────────────────────────────────


def test_reject_pending_candidate():
    _clean_candidates()
    c = _make_valid_candidate()
    result = submit_candidate(c, source="test")
    cid = result["candidate_id"]

    rejected = reject_candidate(cid, reason="不符合投资逻辑")
    assert "error" not in rejected

    record = get_candidate(cid)
    assert record["status"] == "rejected"
    assert "不符合投资逻辑" in str(record.get("rejected_reasons", []))


def test_reject_non_existent_returns_error():
    result = reject_candidate("nonexistent")
    assert "error" in result


# ─── Test: rejected_reason_report ──────────────────────────


def test_rejected_reason_report_generates():
    _clean_candidates()
    # 提交一个非法候选（会被自动拒绝）
    c = _make_invalid_candidate()
    submit_candidate(c, source="test")

    report = generate_rejected_reason_report()
    assert report["report_type"] == "rejected_reason_report"
    assert report["total_rejected"] >= 1
    assert "reason_counts" in report


# ─── Test: duplicate detection ─────────────────────────────


def test_duplicate_in_queue_detects_same_name():
    _clean_candidates()
    name = _unique_name("dup_test")
    c = _make_valid_candidate()
    c["name"] = name
    submit_candidate(c, source="test")

    # 用相同名字提交另一个候选
    dup = _make_valid_candidate()
    dup["name"] = name
    result = submit_candidate(dup, source="test")
    # 应该检测到重复
    assert result["duplicate_check"]["queue"]["is_duplicate"]


def test_no_false_positive_duplicate():
    _clean_candidates()
    c1 = _make_valid_candidate()
    c1["name"] = _unique_name("unique_a")
    submit_candidate(c1, source="test")

    c2 = _make_valid_candidate()
    c2["name"] = _unique_name("unique_b")
    c2["factor_expression"] = "rank(ts_mean(volume, 20) / ts_mean(volume, 60))"
    result = submit_candidate(c2, source="test")

    # 名字、表达式都不同，不应判为重复
    assert not result["duplicate_check"]["queue"]["is_duplicate"]


# ─── Test: safety invariants ───────────────────────────────


def test_no_broker_import_in_llm_alpha():
    """确保 llm_alpha_discovery.py 不包含 broker/miniqmt 模块导入"""
    src = open("/home/ly/.hermes/research-assistant/commands/factor_lab/alpha/llm_alpha_discovery.py").read()
    # 不检查注释中的文本，只检查 import 语句和函数调用
    assert "import broker" not in src
    assert "import miniqmt" not in src
    assert "from broker" not in src
    assert "from miniqmt" not in src


def test_llm_discovery_default_disabled():
    """所有通过 llm_discovery 注册的 Alpha 默认 disabled"""
    from factor_lab.alpha.llm_alpha_discovery import approve_candidate, submit_candidate
    _clean_candidates()
    c = _make_valid_candidate()
    c["name"] = _unique_name("disabled_check")
    result = submit_candidate(c, source="test")
    cid = result["candidate_id"]
    approved = approve_candidate(cid)
    assert "error" not in approved
    # 验证注册后的 Alpha 全部 disabled
    from factor_lab.alpha.registry import get_alpha
    spec = get_alpha(approved["alpha_id"])
    assert spec.get("enabled") == False
    assert spec.get("paper_enabled") == False
    assert spec.get("live_enabled") == False
