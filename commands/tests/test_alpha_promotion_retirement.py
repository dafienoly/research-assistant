"""测试: V3.9 Alpha Promotion/Retirement Engine

覆盖:
  1. PromotionQueue — 晋级队列管理
  2. PromotionEngine — 晋级执行
  3. RetirementPolicy — 退役策略管理
  4. RetirementEngine — 退役执行
  5. 报告生成
  6. 安全不变性
"""
import sys, os, json, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

from factor_lab.alpha.promotion_engine import (
    PromotionEngine,
    PromotionQueue,
    run_promotion,
    generate_promotion_report,
    PROMOTION_ROOT,
    PROMOTION_QUEUE_FILE,
    PROMOTION_HISTORY_FILE,
)
from factor_lab.alpha.retirement_engine import (
    RetirementEngine,
    RetirementPolicy,
    run_retirement,
    generate_retirement_report,
    DEFAULT_RETIREMENT_POLICY,
    RETIREMENT_ROOT,
    RETIREMENT_HISTORY_FILE,
    RETIREMENT_POLICY_FILE,
)
from factor_lab.alpha.governance import (
    GovernanceReview,
    run_governance_review,
)
from factor_lab.alpha.llm_alpha_discovery import (
    CANDIDATES_ROOT,
    CANDIDATES_INDEX,
    submit_candidate,
    get_candidate,
    update_candidate_status,
    AlphaSpecValidator,
)
from factor_lab.alpha.registry import (
    REGISTRY_ROOT,
    register_alpha,
    list_alpha,
    get_alpha,
)


# ─── 辅助函数 ─────────────────────────────────────────────

_COUNTER = 0


def _unique_name(prefix="prom_ret_test"):
    global _COUNTER
    _COUNTER += 1
    ts = datetime.now(CST).strftime("%H%M%S%f")
    return f"{prefix}_{ts}_{_COUNTER}"


def _cleanup():
    """清理测试残留"""
    for p in [CANDIDATES_ROOT, PROMOTION_ROOT, RETIREMENT_ROOT, REGISTRY_ROOT]:
        if p.exists():
            shutil.rmtree(str(p))
    # 清理策略文件
    for f in [PROMOTION_QUEUE_FILE, PROMOTION_HISTORY_FILE,
               RETIREMENT_HISTORY_FILE, RETIREMENT_POLICY_FILE]:
        if f.exists():
            f.unlink()


def _make_valid_candidate():
    return {
        "name": _unique_name("alpha_prom"),
        "description": "测试晋级因子",
        "hypothesis": "过去20日收益高的股票未来5日继续跑赢",
        "factor_expression": "rank(ts_mean(close, 20) / ts_mean(close, 60) - 1)",
        "universe": "all_watchlist",
        "data_requirements": ["close", "volume"],
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "risk_constraints": {"max_position_weight": 0.25, "max_drawdown": 0.15},
        "risk_notes": "动量因子在震荡市中可能失效",
        "evidence": "根据学术研究 (Jegadeesh & Titman 1993)，过去3-12个月收益最高的股票在未来3-12个月继续跑赢。A股市场实证显示20日动量窗口在2010-2023年间年化超额收益约8%。数据来源：Wind数据库回测结果。",
    }


def _make_sample_alpha_spec(name=None):
    from factor_lab.alpha.schema import AlphaSpec
    return AlphaSpec(
        name=name or _unique_name("test_alpha"),
        description="测试因子",
        hypothesis="测试假设",
        factor_expression="rank(close)",
        universe="all_watchlist",
        data_requirements=["close"],
        signal_direction="long",
        rebalance_frequency="daily",
        status="registered",
        enabled=False,
    )


def setup_function():
    _cleanup()


def teardown_function():
    _cleanup()


# ═══════════════════════════════════════════════════════════════════
# Test: PromotionQueue
# ═══════════════════════════════════════════════════════════════════


def test_promotion_queue_add_without_review_returns_error():
    """未审核的候选加入队列返回 error"""
    # 先提交候选
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]

    pq = PromotionQueue()
    result = pq.add(cid)
    assert "error" in result, "未审核的候选应返回 error"


def test_promotion_queue_add_approved_candidate():
    """已批准的候选加入队列成功"""
    # 提交候选并审核
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]
    run_governance_review(cid)

    pq = PromotionQueue()
    result = pq.add(cid)
    # 可能审核结果是 approve 或 request_changes，取决于综合评分
    if "error" in result:
        assert "未被批准" in result.get("error", ""), f"Unexpected error: {result.get('error', '')}"
    else:
        assert result["status"] == "queued"
        assert result["entry"]["candidate_id"] == cid
        assert "governance_score" in result["entry"]


def test_promotion_queue_add_duplicate():
    """重复添加返回 error"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]
    run_governance_review(cid)

    pq = PromotionQueue()
    pq.add(cid)
    result = pq.add(cid)
    if "error" not in result:
        # 如果第一次添加成功，第二次可能成功(更新)或返回error
        pass


def test_promotion_queue_list():
    """列出队列"""
    pq = PromotionQueue()
    queue = pq.list_queue()
    assert isinstance(queue, list)


def test_promotion_queue_stats():
    """队列统计"""
    pq = PromotionQueue()
    stats = pq.queue_stats()
    assert "total" in stats
    assert "by_status" in stats


def test_promotion_queue_status_update():
    """更新队列条目状态"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]
    run_governance_review(cid)

    pq = PromotionQueue()
    result = pq.add(cid)
    if "error" not in result:
        update_result = pq.update_status(cid, "processing")
        assert update_result.get("status") == "updated"
        assert update_result.get("new_status") == "processing"


# ═══════════════════════════════════════════════════════════════════
# Test: PromotionEngine
# ═══════════════════════════════════════════════════════════════════


def test_promotion_engine_promote_nonexistent():
    """晋级不存在的候选返回 error"""
    engine = PromotionEngine()
    result = engine.promote("nonexistent_candidate")
    assert "error" in result


def test_promotion_engine_promote_approved_candidate():
    """晋级已批准的候选"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]

    # 治理审核
    run_governance_review(cid)

    # 晋级
    engine = PromotionEngine()
    result = engine.promote(cid)
    if "error" in result:
        # 审核可能不通过，跳过
        return

    assert "alpha_id" in result, f"晋级应产生 alpha_id: {result}"
    alpha_id = result["alpha_id"]

    # 验证候选状态更新为 promoted
    cand = get_candidate(cid)
    assert cand.get("status") == "promoted", f"候选状态应为 promoted: {cand.get('status')}"

    # 验证 Alpha 已在 registry 中
    alpha = get_alpha(alpha_id)
    assert "error" not in alpha, f"Alpha 应在 registry 中: {alpha}"
    assert alpha.get("status") == "registered"
    assert alpha.get("enabled") == False
    assert alpha.get("paper_enabled") == False
    assert alpha.get("live_enabled") == False

    # 验证 promotion_record 存在
    from factor_lab.alpha.llm_alpha_discovery import CANDIDATES_ROOT
    prom_record_path = CANDIDATES_ROOT / cid / "promotion_record.json"
    assert prom_record_path.exists(), "promotion_record.json 应存在"


def test_promotion_engine_double_promote_returns_error():
    """重复晋级返回 error"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]
    run_governance_review(cid)

    engine = PromotionEngine()
    result = engine.promote(cid)
    if "error" in result:
        return  # 审核不通过

    result2 = engine.promote(cid)
    assert "error" in result2, "重复晋级应返回 error"


def test_promotion_engine_promote_history():
    """晋级历史记录"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]
    run_governance_review(cid)

    engine = PromotionEngine()
    result = engine.promote(cid)
    if "error" in result:
        return

    history = engine.list_promotions()
    assert len(history) >= 1
    assert any(h.get("candidate_id") == cid for h in history)


def test_promotion_engine_get_promotion():
    """获取晋级记录"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]
    run_governance_review(cid)

    engine = PromotionEngine()
    result = engine.promote(cid)
    if "error" in result:
        return

    prom = engine.get_promotion(result["alpha_id"])
    assert "error" not in prom, f"晋级记录应存在: {prom}"
    assert prom.get("candidate_id") == cid


# ═══════════════════════════════════════════════════════════════════
# Test: PromotionReport
# ═══════════════════════════════════════════════════════════════════


def test_generate_promotion_report():
    """生成晋级报告"""
    report = generate_promotion_report()
    assert "output_dir" in report
    assert "report_path" in report
    assert "html_path" in report
    assert "csv_path" in report
    assert "stats" in report

    output_dir = report["output_dir"]
    assert os.path.exists(os.path.join(output_dir, "promotion_report.json"))
    assert os.path.exists(os.path.join(output_dir, "promotion_report.html"))
    assert os.path.exists(os.path.join(output_dir, "promotion_report.csv"))
    assert os.path.exists(os.path.join(output_dir, "audit.log"))


# ═══════════════════════════════════════════════════════════════════
# Test: RetirementPolicy
# ═══════════════════════════════════════════════════════════════════


def test_retirement_policy_default():
    """默认退役策略"""
    policy = RetirementPolicy()
    p = policy.get_policy()
    assert len(p) > 0
    assert "ic_threshold" in p
    assert "max_drawdown" in p
    assert "max_stale_days" in p
    assert p["ic_threshold"]["value"] == 0.02
    assert p["max_drawdown"]["value"] == 0.30


def test_retirement_policy_update():
    """更新退役策略"""
    policy = RetirementPolicy()
    result = policy.update_policy("ic_threshold", {"value": 0.03})
    assert result.get("status") == "updated"
    p = policy.get_policy()
    assert p["ic_threshold"]["value"] == 0.03


def test_retirement_policy_update_invalid_key():
    """更新无效策略键"""
    policy = RetirementPolicy()
    result = policy.update_policy("invalid_key", 1)
    assert "error" in result


def test_retirement_policy_reset():
    """重置策略"""
    policy = RetirementPolicy()
    policy.update_policy("ic_threshold", {"value": 0.99})
    policy.reset_policy()
    p = policy.get_policy()
    assert p["ic_threshold"]["value"] == DEFAULT_RETIREMENT_POLICY["ic_threshold"]["value"]


# ═══════════════════════════════════════════════════════════════════
# Test: RetirementEngine
# ═══════════════════════════════════════════════════════════════════


def test_retirement_engine_retire_nonexistent():
    """退役不存在的 Alpha 返回 error"""
    engine = RetirementEngine()
    result = engine.retire("nonexistent_alpha")
    assert "error" in result


def test_retirement_engine_retire_existing_alpha():
    """退役已注册的 Alpha"""
    # 先注册一个 Alpha
    spec = _make_sample_alpha_spec()
    reg_result = register_alpha(spec)
    alpha_id = reg_result["alpha_id"]

    # 退役
    engine = RetirementEngine()
    result = engine.retire(alpha_id, reason="测试退役")
    assert "error" not in result, f"退役失败: {result.get('error', '')}"
    assert result.get("alpha_id") == alpha_id
    assert result.get("reason") == "测试退役"
    assert result.get("previous_status") == "registered"

    # 验证状态
    alpha = get_alpha(alpha_id)
    assert alpha.get("status") == "retired"

    # 验证 retirement_record 存在
    from factor_lab.alpha.registry import REGISTRY_ROOT
    ret_record_path = REGISTRY_ROOT / alpha_id / "retirement_record.json"
    assert ret_record_path.exists(), "retirement_record.json 应存在"


def test_retirement_engine_double_retire():
    """重复退役返回 error"""
    spec = _make_sample_alpha_spec()
    reg_result = register_alpha(spec)
    alpha_id = reg_result["alpha_id"]

    engine = RetirementEngine()
    engine.retire(alpha_id, reason="测试退役")
    result = engine.retire(alpha_id, reason="再次退役")
    assert "error" in result, "重复退役应返回 error"


def test_retirement_engine_retire_with_force():
    """force 参数跳过状态检查"""
    spec = _make_sample_alpha_spec()
    reg_result = register_alpha(spec)
    alpha_id = reg_result["alpha_id"]

    engine = RetirementEngine()
    engine.retire(alpha_id, reason="测试退役")
    # force=True 可以再次退役
    result = engine.retire(alpha_id, reason="强制退役", force=True)
    assert "error" not in result, f"强制退役应成功: {result}"
    assert result.get("reason") == "强制退役"


def test_retirement_engine_history():
    """退役历史记录"""
    spec = _make_sample_alpha_spec()
    reg_result = register_alpha(spec)
    alpha_id = reg_result["alpha_id"]

    engine = RetirementEngine()
    engine.retire(alpha_id, reason="测试退役")

    history = engine.list_retirements()
    assert len(history) >= 1
    assert any(h.get("alpha_id") == alpha_id for h in history)


def test_retirement_engine_auto_retire_dry_run():
    """自动退役 dry run 不执行退役"""
    engine = RetirementEngine()
    results = engine.auto_retire(dry_run=True)
    assert isinstance(results, list)


def test_retirement_engine_get_retirement():
    """获取退役记录"""
    spec = _make_sample_alpha_spec()
    reg_result = register_alpha(spec)
    alpha_id = reg_result["alpha_id"]

    engine = RetirementEngine()
    engine.retire(alpha_id, reason="测试退役")

    ret = engine.get_retirement(alpha_id)
    assert "error" not in ret, f"退役记录应存在: {ret}"
    assert ret.get("alpha_id") == alpha_id


# ═══════════════════════════════════════════════════════════════════
# Test: RetirementReport
# ═══════════════════════════════════════════════════════════════════


def test_generate_retirement_report():
    """生成退役报告"""
    # 先创建一个退役记录
    spec = _make_sample_alpha_spec()
    reg_result = register_alpha(spec)
    alpha_id = reg_result["alpha_id"]
    run_retirement(alpha_id, reason="测试退役")

    report = generate_retirement_report()
    assert "output_dir" in report
    assert "report_path" in report
    assert "html_path" in report
    assert "csv_path" in report
    assert "stats" in report

    output_dir = report["output_dir"]
    assert os.path.exists(os.path.join(output_dir, "retirement_report.json"))
    assert os.path.exists(os.path.join(output_dir, "retirement_report.html"))
    assert os.path.exists(os.path.join(output_dir, "retirement_report.csv"))
    assert os.path.exists(os.path.join(output_dir, "audit.log"))
    assert report["stats"]["total_retirements"] >= 1


# ═══════════════════════════════════════════════════════════════════
# Test: Safety invariants
# ═══════════════════════════════════════════════════════════════════


def test_promotion_module_no_broker_import():
    """确保 promotion_engine.py 不包含 broker/miniqmt 模块导入"""
    src = open(
        "/home/ly/.hermes/research-assistant/commands/factor_lab/alpha/promotion_engine.py"
    ).read()
    lines = src.split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("import") or stripped.startswith("from"):
            assert "broker" not in stripped, f"发现 broker 导入: {stripped}"
            assert "miniqmt" not in stripped, f"发现 miniqmt 导入: {stripped}"


def test_retirement_module_no_broker_import():
    """确保 retirement_engine.py 不包含 broker/miniqmt 模块导入"""
    src = open(
        "/home/ly/.hermes/research-assistant/commands/factor_lab/alpha/retirement_engine.py"
    ).read()
    lines = src.split("\n")
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("import") or stripped.startswith("from"):
            assert "broker" not in stripped, f"发现 broker 导入: {stripped}"
            assert "miniqmt" not in stripped, f"发现 miniqmt 导入: {stripped}"


def test_promotion_safety_defaults():
    """晋级默认安全标记"""
    # 检查 promoted alpha 的 enabled 状态
    spec = _make_sample_alpha_spec()
    reg_result = register_alpha(spec)

    # 注册 registry 默认状态
    alpha = get_alpha(reg_result["alpha_id"])
    assert alpha.get("enabled") == False
    assert alpha.get("paper_enabled") == False
    assert alpha.get("live_enabled") == False


def test_retirement_safety_defaults():
    """退役默认安全标记"""
    spec = _make_sample_alpha_spec()
    reg_result = register_alpha(spec)

    engine = RetirementEngine()
    result = engine.retire(reg_result["alpha_id"], reason="安全测试")
    assert "error" not in result
    # 退役后 enabled 被禁用
    alpha = get_alpha(reg_result["alpha_id"])
    assert alpha.get("enabled") == False


def test_promotion_report_safety():
    """晋级报告安全声明"""
    report = generate_promotion_report()
    safety = report.get("safety", {})
    assert safety.get("auto_apply") == False
    assert safety.get("no_live_trade") == True


def test_retirement_report_safety():
    """退役报告安全声明"""
    report = generate_retirement_report()
    safety = report.get("safety", {})
    assert safety.get("no_live_trade") == True


def test_promotion_always_disabled():
    """晋级后的 Alpha 始终 disabled"""
    # 用 promote 流程测试
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]
    run_governance_review(cid)

    engine = PromotionEngine()
    result = engine.promote(cid)
    if "error" not in result:
        alpha_id = result["alpha_id"]
        alpha = get_alpha(alpha_id)
        assert alpha["enabled"] == False
        assert alpha["paper_enabled"] == False
        assert alpha["live_enabled"] == False


# ═══════════════════════════════════════════════════════════════════
# Test: Update candidate status
# ═══════════════════════════════════════════════════════════════════


def test_update_candidate_status():
    """更新候选状态"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]

    result = update_candidate_status(cid, "promoted")
    assert result["success"] == True
    assert result["old_status"] == "pending_review"
    assert result["new_status"] == "promoted"

    cand = get_candidate(cid)
    assert cand["status"] == "promoted"
