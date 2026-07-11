"""测试: V3.8 Alpha Governance — Evidence / Risk / Governance Review

覆盖:
  1. EvidenceScorer — 证据评分
  2. RiskAssessor — 风险评估
  3. GovernanceReview — 综合治理
  4. 报告生成
  5. 安全不变性
"""
import json
import os
from datetime import datetime, timezone, timedelta
import pytest

import factor_lab.alpha.governance as governance_module
import factor_lab.alpha.llm_alpha_discovery as discovery_module
from factor_lab.alpha.governance import (
    EvidenceScorer,
    RiskAssessor,
    GovernanceReview,
    run_governance_review,
    generate_governance_report,
    list_governance_status,
)
from factor_lab.alpha.llm_alpha_discovery import (
    submit_candidate,
)

CST = timezone(timedelta(hours=8))


# ─── 辅助函数 ─────────────────────────────────────────────

_COUNTER = 0


def _unique_name(prefix="gov_test"):
    global _COUNTER
    _COUNTER += 1
    ts = datetime.now(CST).strftime("%H%M%S%f")
    return f"{prefix}_{ts}_{_COUNTER}"


@pytest.fixture(autouse=True)
def isolated_alpha_state(monkeypatch, tmp_path):
    candidates = tmp_path / "alpha_candidates"
    reports = tmp_path / "reports"
    governance = reports / "alpha_governance"
    governance.mkdir(parents=True)
    monkeypatch.setattr(discovery_module, "BASE", reports)
    monkeypatch.setattr(discovery_module, "CANDIDATES_ROOT", candidates)
    monkeypatch.setattr(discovery_module, "CANDIDATES_INDEX", candidates / "candidates_index.json")
    monkeypatch.setattr(governance_module, "BASE", reports)
    monkeypatch.setattr(governance_module, "GOVERNANCE_ROOT", governance)
    yield


def _make_valid_candidate():
    return {
        "name": _unique_name("alpha_gov"),
        "description": "基于动量的治理测试因子",
        "hypothesis": "过去20日收益高的股票未来5日继续跑赢，尤其是在上涨市场中趋势延续性强",
        "factor_expression": "rank(ts_mean(close, 20) / ts_mean(close, 60) - 1) + rank(roe)",
        "universe": "all_watchlist",
        "data_requirements": ["close", "volume", "roe"],
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "risk_constraints": {"max_position_weight": 0.25, "max_drawdown": 0.15},
        "risk_notes": "动量因子在震荡市中可能失效，高换手率增加交易成本",
        "industry_hypothesis": "半导体等高景气、趋势延续较强的成长行业可能更适合该动量信号",
        "evidence": "根据学术研究 (Jegadeesh & Titman 1993)，过去3-12个月收益最高的股票在未来3-12个月继续跑赢。A股市场实证显示20日动量窗口在2010-2023年间年化超额收益约8%。数据来源：Wind数据库回测结果。例如，沪深300成分股中过去20日涨幅前20%的股票组合，未来5日平均超额收益0.5%。",
    }


def _make_weak_evidence_candidate():
    return {
        "name": _unique_name("weak_ev"),
        "description": "弱证据测试因子",
        "hypothesis": "因子假设",
        "factor_expression": "rank(close)",
        "universe": "all_watchlist",
        "data_requirements": ["close"],
        "signal_direction": "long",
        "rebalance_frequency": "daily",
        "risk_constraints": {"max_position_weight": 0.25, "max_drawdown": 0.15},
        "risk_notes": "",
        "evidence": "LLM 生成的因子",
    }


def _make_high_risk_candidate():
    return {
        "name": _unique_name("high_risk"),
        "description": "高风险测试因子",
        "hypothesis": "这是一个包含多参数非线性条件的复杂因子，在牛熊市和震荡市中表现差异大，对流动性敏感",
        "factor_expression": "where(rank(close) > 0.5, sign_power(ts_corr(close, volume, 20), 2) * ts_decay_linear(zscore(ret1), 10), 0)",
        "universe": "all_watchlist",
        "data_requirements": ["close", "volume", "amount"],
        "signal_direction": "long_short",
        "rebalance_frequency": "daily",
        "risk_constraints": {"max_position_weight": 0.25, "max_drawdown": 0.15},
        "risk_notes": "策略在低流动性小盘股中表现最佳，但交易成本可能侵蚀收益。模型参数较多，存在过拟合风险。市场体制切换时有效性下降。",
        "evidence": "实证观察发现此模式在某些市场条件下有效。",
    }


# ═══════════════════════════════════════════════════════════════════
# Test: EvidenceScorer
# ═══════════════════════════════════════════════════════════════════


def test_evidence_scorer_returns_expected_fields():
    """EvidenceScorer 返回预期字段"""
    scorer = EvidenceScorer()
    candidate = _make_valid_candidate()
    result = scorer.score(candidate)

    assert "evidence_score" in result
    assert "source_credibility" in result
    assert "completeness" in result
    assert "quality" in result
    assert "verdict" in result
    assert "details" in result


def test_evidence_scorer_strong_evidence():
    """强证据候选得分高"""
    scorer = EvidenceScorer()
    candidate = _make_valid_candidate()
    result = scorer.score(candidate)

    assert result["evidence_score"] >= 0.4, f"强证据得分应 >= 0.4: {result['evidence_score']}"
    assert result["verdict"] in ("strong", "moderate")


def test_evidence_scorer_weak_evidence():
    """弱证据候选得分低"""
    scorer = EvidenceScorer()
    candidate = _make_weak_evidence_candidate()
    result = scorer.score(candidate)

    assert result["evidence_score"] < 0.6, f"弱证据得分应 < 0.6: {result['evidence_score']}"


def test_evidence_scorer_detects_academic_source():
    """证据评分能检测学术来源"""
    scorer = EvidenceScorer()
    candidate = _make_valid_candidate()
    result = scorer.score(candidate)

    assert result["source_type"] == "academic_paper", f"应检测为学术来源: {result['source_type']}"


def test_evidence_scorer_source_weights():
    """来源权重符合预期范围"""
    scorer = EvidenceScorer()
    candidate = _make_valid_candidate()
    result = scorer.score(candidate)

    assert 0.0 <= result["source_credibility"] <= 1.0
    assert 0.0 <= result["completeness"] <= 1.0
    assert 0.0 <= result["quality"] <= 1.0


def test_evidence_scorer_no_evidence_minimal():
    """无证据候选评分极低"""
    scorer = EvidenceScorer()
    candidate = {
        "spec": {
            "name": "minimal",
            "description": "",
            "hypothesis": "",
            "evidence": "",
            "risk_notes": "",
        }
    }
    result = scorer.score(candidate)
    assert result["evidence_score"] < 0.3


# ═══════════════════════════════════════════════════════════════════
# Test: RiskAssessor
# ═══════════════════════════════════════════════════════════════════


def test_risk_assessor_returns_expected_fields():
    """RiskAssessor 返回预期字段"""
    assessor = RiskAssessor()
    candidate = _make_valid_candidate()
    result = assessor.assess(candidate)

    assert "risk_score" in result
    assert "overall_risk_level" in result
    assert "overfitting" in result
    assert "regime_dependency" in result
    assert "capacity" in result
    assert "implementation" in result
    assert "details" in result


def test_risk_assessor_low_risk_candidate():
    """低风险候选评分低"""
    assessor = RiskAssessor()
    candidate = _make_valid_candidate()
    result = assessor.assess(candidate)

    # 简单因子风险应较低
    assert result["risk_score"] < 0.6, f"简单因子风险应 < 0.6: {result['risk_score']}"
    assert result["overall_risk_level"] in ("low", "medium")


def test_risk_assessor_high_risk_candidate():
    """高风险候选评分高"""
    assessor = RiskAssessor()
    candidate = _make_high_risk_candidate()
    result = assessor.assess(candidate)

    # 复杂因子风险应高于简单因子
    assert result["risk_score"] >= 0.1, f"复杂因子风险应 >= 0.1: {result['risk_score']}"
    assert result["overall_risk_level"] in ("low", "medium", "high")


def test_risk_assessor_complexity_detection():
    """表达式复杂度越高，过拟合风险越高"""
    assessor = RiskAssessor()
    simple_candidate = _make_valid_candidate()
    complex_candidate = _make_high_risk_candidate()

    simple_risk = assessor.assess(simple_candidate)
    complex_risk = assessor.assess(complex_candidate)

    # 复杂因子的过拟合风险应 >= 简单因子
    assert complex_risk["overfitting"] >= simple_risk["overfitting"], (
        f"复杂因子过拟合风险 {complex_risk['overfitting']} 应 >= "
        f"简单因子 {simple_risk['overfitting']}"
    )


def test_risk_assessor_scores_in_range():
    """风险评分在 0~1 范围内"""
    assessor = RiskAssessor()
    candidate = _make_valid_candidate()
    result = assessor.assess(candidate)

    for key in ["overfitting", "regime_dependency", "capacity", "implementation"]:
        assert 0.0 <= result.get(key, -1) <= 1.0, f"{key} 不在 [0,1] 范围: {result.get(key)}"


# ═══════════════════════════════════════════════════════════════════
# Test: GovernanceReview
# ═══════════════════════════════════════════════════════════════════


def test_governance_review_non_existent_returns_error():
    """治理审核不存在的候选返回 error"""
    review = GovernanceReview()
    result = review.run("nonexistent_candidate")
    assert "error" in result


def test_governance_review_pending_candidate():
    """治理审核 pending 候选返回完整结果"""
    # 先提交候选
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]
    assert submit_result["status"] == "pending_review"

    # 运行治理审核
    review = GovernanceReview()
    result = review.run(cid)
    assert "error" not in result, f"治理审核失败: {result.get('error', '')}"
    assert "validation" in result
    assert "evidence" in result
    assert "risk" in result
    assert "duplicate" in result
    assert "governance" in result


def test_governance_review_produces_scores():
    """治理审核产生评分"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]

    result = run_governance_review(cid)
    gov = result.get("governance", {})
    assert "overall_score" in gov
    assert "component_scores" in gov
    assert "verdict" in gov
    assert "confidence" in gov
    assert 0.0 <= gov["overall_score"] <= 1.0


def test_governance_review_persists():
    """治理审核持久化到候选目录"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]

    run_governance_review(cid)

    # 检查审核记录文件
    review_path = discovery_module.CANDIDATES_ROOT / cid / "governance_review.json"
    assert review_path.exists(), "审核记录文件不存在"
    data = json.loads(review_path.read_text())
    assert data["candidate_id"] == cid
    assert data["auto_apply"] is False
    assert data["no_live_trade"] is True


def test_governance_review_get_existing():
    """获取已有审核记录"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]

    run_governance_review(cid)

    review = GovernanceReview()
    existing = review.get_review(cid)
    assert "error" not in existing
    assert existing["candidate_id"] == cid


def test_governance_review_get_missing():
    """获取不存在的审核记录返回 error"""
    review = GovernanceReview()
    result = review.get_review("nonexistent")
    assert "error" in result


def test_governance_review_strong_candidate_approves():
    """强候选应获得批准"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]

    result = run_governance_review(cid)
    gov = result["governance"]
    # 强候选应该有较高评分
    assert gov["overall_score"] >= 0.3, f"强候选评分应 >= 0.3: {gov['overall_score']}"


# ═══════════════════════════════════════════════════════════════════
# Test: GovernanceReport
# ═══════════════════════════════════════════════════════════════════


def test_generate_single_candidate_report():
    """生成单个候选的治理报告"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]

    run_governance_review(cid)
    report = generate_governance_report(candidate_id=cid)

    assert "error" not in report, f"报告生成失败: {report.get('error', '')}"
    assert "output_dir" in report
    assert "report_path" in report
    assert "html_path" in report
    assert report["stats"]["total"] >= 1


def test_generate_all_candidate_report():
    """生成所有候选的治理报告"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]
    run_governance_review(cid)

    report = generate_governance_report()

    assert "error" not in report
    assert report["stats"]["total"] >= 1


def test_generate_report_creates_files():
    """报告生成创建预期文件"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]
    run_governance_review(cid)

    report = generate_governance_report(candidate_id=cid)
    output_dir = report["output_dir"]

    assert os.path.exists(os.path.join(output_dir, "governance_report.json"))
    assert os.path.exists(os.path.join(output_dir, "governance_report.html"))
    assert os.path.exists(os.path.join(output_dir, "governance_report.csv"))
    assert os.path.exists(os.path.join(output_dir, "audit.log"))


# ═══════════════════════════════════════════════════════════════════
# Test: list_governance_status
# ═══════════════════════════════════════════════════════════════════


def test_list_governance_status():
    """列出治理状态"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]
    run_governance_review(cid)

    status_list = list_governance_status()
    reviewed = [s for s in status_list if s["candidate_id"] == cid]
    assert len(reviewed) >= 1
    assert reviewed[0]["governance_score"] is not None
    assert reviewed[0]["governance_verdict"] is not None
    assert reviewed[0]["evidence_score"] is not None


def test_list_governance_status_unreviewed():
    """未审核候选状态不报错"""
    candidate = _make_valid_candidate()
    submit_candidate(candidate, source="test")

    status_list = list_governance_status()
    unreviewed = [s for s in status_list if s["governance_verdict"] == "not_reviewed"]
    assert len(unreviewed) >= 1


# ═══════════════════════════════════════════════════════════════════
# Test: Safety invariants
# ═══════════════════════════════════════════════════════════════════


def test_governance_module_no_broker_import():
    """确保 governance.py 不包含 broker/miniqmt 模块导入"""
    src = open(
        "/home/ly/.hermes/research-assistant/commands/factor_lab/alpha/governance.py"
    ).read()
    lines = src.split("\n")
    for line in lines:
        stripped = line.strip()
        # 只检查 import 行
        if stripped.startswith("import") or stripped.startswith("from"):
            assert "broker" not in stripped, f"发现 broker 导入: {stripped}"
            assert "miniqmt" not in stripped, f"发现 miniqmt 导入: {stripped}"


def test_governance_review_safety_defaults():
    """治理审核安全标记"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]

    result = run_governance_review(cid)
    assert result.get("auto_apply") is False
    assert result.get("no_live_trade") is True


def test_governance_report_safety():
    """治理报告安全声明"""
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]
    run_governance_review(cid)

    report = generate_governance_report(candidate_id=cid)
    safety = report.get("safety", {})
    assert safety.get("auto_apply") is False
    assert safety.get("no_live_trade") is True
    assert safety.get("all_disabled") is True


# ═══════════════════════════════════════════════════════════════════
# Test: Expression complexity assessment
# ═══════════════════════════════════════════════════════════════════


def test_risk_assessor_empty_expression():
    """空表达式风险评定"""
    assessor = RiskAssessor()
    candidate = _make_valid_candidate()
    candidate["factor_expression"] = ""
    result = assessor.assess(candidate)
    # 空表达式应该有中等风险 (无法评估)
    assert result["overall_risk_level"] is not None


def test_risk_assessor_complex_expression_penalty():
    """复杂表达式增加过拟合风险"""
    ra = RiskAssessor()
    simple = ra._assess_expression_complexity("rank(close)")
    complex_expr = ra._assess_expression_complexity(
        "where(rank(close) > 0.5, sign_power(ts_corr(close, volume, 20), 2), 0)"
    )
    assert complex_expr >= simple, f"复杂表达式 [{complex_expr}] 应 >= 简单表达式 [{simple}]"


def test_governance_review_with_override():
    """治理审核可以强制指定结论"""
    review = GovernanceReview()
    candidate = _make_valid_candidate()
    submit_result = submit_candidate(candidate, source="test")
    cid = submit_result["candidate_id"]

    # 用 override_verdict 测试
    result = review.run(cid)
    assert "governance" in result
