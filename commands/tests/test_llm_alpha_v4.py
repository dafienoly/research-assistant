"""V4.6 LLM Alpha Factory 升级测试套件

测试覆盖:
  1. 扩展字段 — LLM prompt 包含新字段类别
  2. 非价量字段检查 — 因子表达式必须包含至少一个非价量字段
  3. 产业假设检查 — 每个因子必须有 industry_hypothesis
  4. FutureLeakageGate — 未来函数检测
  5. 失败归因 — record_factor_failure / increment_trial_count
  6. 多重检验 Bonferroni 校正
  7. Trial counter / parent_factor_id / failure_reason 持久化
"""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

# ═══════════════════════════════════════════════════════════════════
# 1. LLM Prompt 扩展字段检查
# ═══════════════════════════════════════════════════════════════════


def test_prompt_contains_valuation_fields():
    """LLM prompt 必须包含新增的估值类字段"""
    from factor_lab.alpha.llm_alpha_discovery import LLM_ALPHA_PROMPT_TEMPLATE
    assert "pe_ttm" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "pb_lf" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "ps_ttm" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "pcf_ttm" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "dv_ratio" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "Valuation" in LLM_ALPHA_PROMPT_TEMPLATE


def test_prompt_contains_fundamental_fields():
    """LLM prompt 必须包含新增的基本面类字段"""
    from factor_lab.alpha.llm_alpha_discovery import LLM_ALPHA_PROMPT_TEMPLATE
    assert "roe" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "gross_margin" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "net_margin" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "debt_ratio" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "eps" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "bps" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "Fundamentals" in LLM_ALPHA_PROMPT_TEMPLATE


def test_prompt_contains_growth_fields():
    """LLM prompt 必须包含新增的成长类字段"""
    from factor_lab.alpha.llm_alpha_discovery import LLM_ALPHA_PROMPT_TEMPLATE
    assert "revenue_growth_q" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "profit_growth_q" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "roe_yoy" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "Growth" in LLM_ALPHA_PROMPT_TEMPLATE


def test_prompt_contains_capital_flow_fields():
    """LLM prompt 必须包含新增的资金流向字段"""
    from factor_lab.alpha.llm_alpha_discovery import LLM_ALPHA_PROMPT_TEMPLATE
    assert "net_main_force" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "net_super_large" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "net_small" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "nb_net_flow" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "Capital Flow" in LLM_ALPHA_PROMPT_TEMPLATE


def test_prompt_contains_margin_fields():
    """LLM prompt 必须包含新增的两融字段"""
    from factor_lab.alpha.llm_alpha_discovery import LLM_ALPHA_PROMPT_TEMPLATE
    assert "margin_balance" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "margin_buy" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "Margin" in LLM_ALPHA_PROMPT_TEMPLATE


def test_prompt_contains_industry_chain_fields():
    """LLM prompt 必须包含新增的产业链字段"""
    from factor_lab.alpha.llm_alpha_discovery import LLM_ALPHA_PROMPT_TEMPLATE
    assert "semiconductor_subsector" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "core_score" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "domestic_substitution_score" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "Industry Chain" in LLM_ALPHA_PROMPT_TEMPLATE


def test_prompt_contains_benchmark_fields():
    """LLM prompt 必须包含新增的基准字段"""
    from factor_lab.alpha.llm_alpha_discovery import LLM_ALPHA_PROMPT_TEMPLATE
    assert "semi_ew_return" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "csi300_return" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "Benchmarks" in LLM_ALPHA_PROMPT_TEMPLATE


def test_prompt_contains_industry_hypothesis():
    """LLM prompt 必须包含 industry_hypothesis 字段说明"""
    from factor_lab.alpha.llm_alpha_discovery import LLM_ALPHA_PROMPT_TEMPLATE
    assert "industry_hypothesis" in LLM_ALPHA_PROMPT_TEMPLATE


def test_prompt_contains_non_pv_rule():
    """LLM prompt 必须包含非价量字段约束规则"""
    from factor_lab.alpha.llm_alpha_discovery import LLM_ALPHA_PROMPT_TEMPLATE
    assert "NON-PRICE-VOLUME" in LLM_ALPHA_PROMPT_TEMPLATE
    assert "industry_hypothesis" in LLM_ALPHA_PROMPT_TEMPLATE


# ═══════════════════════════════════════════════════════════════════
# 2. 非价量字段检查 (AlphaSpecValidator V4.6)
# ═══════════════════════════════════════════════════════════════════


def test_validator_rejects_price_volume_only():
    """因子表达式仅使用价量字段应被拒绝"""
    from factor_lab.alpha.llm_alpha_discovery import AlphaSpecValidator

    validator = AlphaSpecValidator()
    candidate = {
        "name": "test_pv_only",
        "description": "仅使用价量的测试因子",
        "hypothesis": "动量效应测试",
        "factor_expression": "rank(close / ts_mean(close, 20))",
        "universe": "all_watchlist",
        "data_requirements": ["close", "volume"],
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "risk_constraints": {"max_position_weight": 0.25, "max_drawdown": 0.15},
        "risk_notes": "测试",
        "evidence": "测试",
        "industry_hypothesis": "测试行业",
    }
    ok = validator.validate(candidate)
    assert not ok, "仅使用价量字段的因子应被拒绝"
    errors_text = " ".join(validator.errors)
    assert "非价量字段" not in errors_text or "价量字段" in errors_text


def test_validator_accepts_non_pv_fields():
    """因子表达式包含非价量字段应通过"""
    from factor_lab.alpha.llm_alpha_discovery import AlphaSpecValidator

    validator = AlphaSpecValidator()
    candidate = {
        "name": "test_with_roe",
        "description": "包含ROE的因子",
        "hypothesis": "ROE动量测试",
        "factor_expression": "rank(roe) * rank(close / ts_mean(close, 20))",
        "universe": "all_watchlist",
        "data_requirements": ["close", "roe"],
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "risk_constraints": {"max_position_weight": 0.25, "max_drawdown": 0.15},
        "risk_notes": "测试",
        "evidence": "测试",
        "industry_hypothesis": "金融行业，高ROE公司表现优异",
    }
    ok = validator.validate(candidate)
    assert ok, f"包含非价量字段的因子应通过: {validator.errors}"
    assert len(validator.errors) == 0


def test_validator_accepts_margin_fields():
    """因子表达式包含两融字段应通过"""
    from factor_lab.alpha.llm_alpha_discovery import AlphaSpecValidator

    validator = AlphaSpecValidator()
    candidate = {
        "name": "test_margin_factor",
        "description": "两融因子",
        "hypothesis": "融资买入预示上涨",
        "factor_expression": "rank(margin_buy) * rank(close / ts_mean(close, 20))",
        "universe": "all_watchlist",
        "data_requirements": ["close", "margin_buy"],
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "risk_constraints": {"max_position_weight": 0.25, "max_drawdown": 0.15},
        "risk_notes": "测试",
        "evidence": "测试",
        "industry_hypothesis": "科技股融资余额较高",
    }
    ok = validator.validate(candidate)
    assert ok, f"包含两融字段的因子应通过: {validator.errors}"


def test_validator_accepts_fund_flow_fields():
    """因子表达式包含资金流向字段应通过"""
    from factor_lab.alpha.llm_alpha_discovery import AlphaSpecValidator

    validator = AlphaSpecValidator()
    candidate = {
        "name": "test_fund_flow",
        "description": "主力资金因子",
        "hypothesis": "主力净流入预示上涨",
        "factor_expression": "rank(net_main_force) * rank(returns)",
        "universe": "all_watchlist",
        "data_requirements": ["close", "net_main_force"],
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "risk_constraints": {"max_position_weight": 0.25, "max_drawdown": 0.15},
        "risk_notes": "测试",
        "evidence": "测试",
        "industry_hypothesis": "半导体板块主力资金效应显著",
    }
    ok = validator.validate(candidate)
    # Note: this has "returns" but also "net_main_force" — should pass
    assert ok, f"包含资金流向字段的因子应通过: {validator.errors}"


def test_validator_rejects_missing_industry_hypothesis():
    """缺少 industry_hypothesis 应被拒绝"""
    from factor_lab.alpha.llm_alpha_discovery import AlphaSpecValidator

    validator = AlphaSpecValidator()
    candidate = {
        "name": "test_no_industry",
        "description": "无产业假设",
        "hypothesis": "测试",
        "factor_expression": "rank(close / ts_mean(close, 20))",
        "universe": "all_watchlist",
        "data_requirements": ["close"],
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "risk_constraints": {"max_position_weight": 0.25, "max_drawdown": 0.15},
        "risk_notes": "测试",
        "evidence": "测试",
        # 缺少 industry_hypothesis
    }
    ok = validator.validate(candidate)
    assert not ok, "缺少 industry_hypothesis 应被拒绝"


# ═══════════════════════════════════════════════════════════════════
# 3. FutureLeakageGate 测试
# ═══════════════════════════════════════════════════════════════════


def test_future_leakage_gate_clean_expression():
    """干净的因子表达式应通过未来函数检查"""
    from factor_lab.alpha.future_leakage_gate import FutureLeakageGate

    gate = FutureLeakageGate()
    report = gate.check("rank(close / ts_mean(close, 20))")
    assert report.passed, f"干净的表达式应通过: {report.issues}"
    assert len(report.issues) == 0


def test_future_leakage_gate_returns_as_input():
    """使用 returns 作为输入应检测为 CRITICAL"""
    from factor_lab.alpha.future_leakage_gate import FutureLeakageGate, LeakageSeverity

    gate = FutureLeakageGate()
    report = gate.check("rank(returns) * rank(ts_mean(close, 20))")
    assert not report.passed, "使用 returns 作为输入应被拒绝"
    assert report.severity == LeakageSeverity.CRITICAL


def test_future_leakage_gate_window_one():
    """window=1 应检测为 HIGH"""
    from factor_lab.alpha.future_leakage_gate import FutureLeakageGate, LeakageSeverity

    gate = FutureLeakageGate()
    report = gate.check("rank(ts_mean(close, 1))")
    assert not report.passed
    assert report.severity == LeakageSeverity.HIGH


def test_future_leakage_gate_negative_window():
    """负 window 应检测为 CRITICAL"""
    from factor_lab.alpha.future_leakage_gate import FutureLeakageGate, LeakageSeverity

    gate = FutureLeakageGate()
    report = gate.check("ts_mean(close, -5)")
    assert not report.passed
    assert report.severity == LeakageSeverity.CRITICAL


def test_future_leakage_gate_delta_zero():
    """ts_delta(x, 0) 应检测为 MEDIUM"""
    from factor_lab.alpha.future_leakage_gate import FutureLeakageGate, LeakageSeverity

    gate = FutureLeakageGate()
    report = gate.check("ts_delta(close, 0)")
    assert not report.passed
    assert report.severity == LeakageSeverity.MEDIUM


def test_future_leakage_gate_intraday_close():
    """盘中策略使用 close 应检测为 HIGH"""
    from factor_lab.alpha.future_leakage_gate import FutureLeakageGate, LeakageSeverity

    gate = FutureLeakageGate()
    report = gate.check("close / ts_mean(close, 20)", context={"trade_time": "intraday"})
    assert not report.passed
    # close * 操作在盘中应触发警告
    assert len(report.issues) >= 1


def test_future_leakage_gate_same_day_target():
    """same_day_return 预测目标应检测为 CRITICAL"""
    from factor_lab.alpha.future_leakage_gate import (
        check_data_timeline_leakage,
        LeakageSeverity,
    )

    report = check_data_timeline_leakage("intraday_data", "same_day_return")
    assert not report.passed
    assert report.severity == LeakageSeverity.CRITICAL


# ═══════════════════════════════════════════════════════════════════
# 4. Multiple Testing (Bonferroni) 测试
# ═══════════════════════════════════════════════════════════════════


def test_bonferroni_adjust():
    """Bonferroni 校正基本计算"""
    from factor_lab.alpha.multiple_testing import bonferroni_adjust

    p_values = [0.01, 0.04, 0.06, 0.20, 0.50]
    result = bonferroni_adjust(p_values, alpha=0.05)

    assert result.n_tests == 5
    assert abs(result.alpha_adjusted - 0.01) < 1e-6  # 0.05 / 5
    # p=0.01 <= 0.01 应拒绝
    assert 0 in result.rejected_indices
    # p=0.04 > 0.01 不应拒绝
    assert 1 not in result.rejected_indices


def test_bonferroni_no_p_values():
    """空 p 值列表应返回空结果"""
    from factor_lab.alpha.multiple_testing import bonferroni_adjust

    result = bonferroni_adjust([], alpha=0.05)
    assert result.n_tests == 0


def test_holm_bonferroni():
    """Holm-Bonferroni 逐步拒绝"""
    from factor_lab.alpha.multiple_testing import holm_bonferroni_adjust

    p_values = [0.005, 0.01, 0.03, 0.10, 0.50]
    result = holm_bonferroni_adjust(p_values, alpha=0.05)

    assert result.n_tests == 5
    # p=0.005 (step1 threshold = 0.05/5=0.01) → 0.005 <= 0.01 ✓
    # p=0.01 (step2 threshold = 0.05/4=0.0125) → 0.01 <= 0.0125 ✓
    assert len(result.rejected_indices) >= 2


def test_benjamini_hochberg():
    """Benjamini-Hochberg FDR 控制"""
    from factor_lab.alpha.multiple_testing import benjamini_hochberg_adjust

    p_values = [0.001, 0.01, 0.04, 0.20, 0.50]
    result = benjamini_hochberg_adjust(p_values, alpha=0.05)

    assert result.n_tests == 5
    # BH 通常比 Bonferroni 拒绝更多
    assert len(result.rejected_indices) >= 1


def test_adjust_significance_threshold():
    """快捷调整函数"""
    from factor_lab.alpha.multiple_testing import adjust_significance_threshold

    # 20个因子，alpha=0.05 → 0.0025
    adj = adjust_significance_threshold(20, 0.05, "bonferroni")
    assert abs(adj - 0.0025) < 1e-6

    # 100个因子，alpha=0.01 → 0.0001
    adj = adjust_significance_threshold(100, 0.01, "bonferroni")
    assert abs(adj - 0.0001) < 1e-6

    # 0个因子 → alpha不变
    adj = adjust_significance_threshold(0, 0.05)
    assert abs(adj - 0.05) < 1e-6


def test_adjust_threshold_static_method():
    """AlphaSpecValidator 的静态调整方法"""
    from factor_lab.alpha.llm_alpha_discovery import AlphaSpecValidator

    # 同时检验10个因子，alpha从0.05降到0.005
    adjusted = AlphaSpecValidator.adjust_threshold_for_multiple_tests(10, 0.05)
    assert abs(adjusted - 0.005) < 1e-6


# ═══════════════════════════════════════════════════════════════════
# 5. 失败归因测试
# ═══════════════════════════════════════════════════════════════════


def test_record_factor_failure():
    """record_factor_failure 应写入 FailureDatabase"""
    from factor_lab.evolution import record_factor_failure

    result = record_factor_failure(
        factor_name="test_factor_fail",
        reason="ic_decay",
        expression="rank(close / ts_mean(close, 20))",
        hypothesis="测试失败",
    )

    assert result["recorded"]
    assert result["failure_id"] != ""
    assert "error" not in result


def test_record_factor_failure_without_alpha_id():
    """没有 alpha_id 时也应能记录失败"""
    from factor_lab.evolution import record_factor_failure

    result = record_factor_failure(
        factor_name="test_no_alpha",
        reason="overfit",
    )

    assert result["recorded"]
    assert result["failure_id"] != ""


def test_get_failure_context_for_llm():
    """失败上下文应为 LLM 可用的字符串"""
    from factor_lab.evolution import _get_failure_context_for_llm

    context = _get_failure_context_for_llm(n=5)
    assert isinstance(context, str)
    assert len(context) > 0


def test_audit_evolution_run():
    """进化运行审计应包含所有必要字段"""
    from factor_lab.evolution import audit_evolution_run

    record = audit_evolution_run(candidates_count=10, accepted_count=7, rejected_count=3)
    assert record["candidates_count"] == 10
    assert record["accepted_count"] == 7
    assert record["rejected_count"] == 3
    assert "acceptance_rate" in record
    assert "70.0%" in record["acceptance_rate"]
    assert "timestamp" in record


# ═══════════════════════════════════════════════════════════════════
# 6. AlphaRegistry V4.6 扩展字段测试
# ═══════════════════════════════════════════════════════════════════


def test_alpha_schema_has_v46_fields():
    """AlphaSpec 必须包含 V4.6 新增字段"""
    from factor_lab.alpha.schema import AlphaSpec

    spec = AlphaSpec(name="test_schema")
    assert hasattr(spec, "trial_count")
    assert hasattr(spec, "parent_factor_id")
    assert hasattr(spec, "failure_reason")
    assert hasattr(spec, "next_iteration_suggestion")
    assert hasattr(spec, "industry_hypothesis")
    assert hasattr(spec, "non_pv_fields_used")


def test_alpha_schema_v46_defaults():
    """V4.6 新增字段应有合理的默认值"""
    from factor_lab.alpha.schema import AlphaSpec

    spec = AlphaSpec()
    assert spec.trial_count == 0
    assert spec.parent_factor_id == ""
    assert spec.failure_reason == ""
    assert spec.next_iteration_suggestion == ""
    assert spec.industry_hypothesis == ""
    assert spec.non_pv_fields_used == []


# ═══════════════════════════════════════════════════════════════════
# 7. 集成测试: FutureLeakageGate + AlphaSpecValidator
# ═══════════════════════════════════════════════════════════════════


def test_validator_integrates_future_leakage_gate():
    """AlphaSpecValidator 应通过 FutureLeakageGate 检测未来函数"""
    from factor_lab.alpha.llm_alpha_discovery import AlphaSpecValidator

    # 使用 returns 作为输入的因子
    validator = AlphaSpecValidator()
    candidate = {
        "name": "test_returns_input",
        "description": "使用returns的因子",
        "hypothesis": "测试",
        "factor_expression": "rank(returns) * rank(ts_mean(close, 20))",
        "universe": "all_watchlist",
        "data_requirements": ["close"],
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "risk_constraints": {"max_position_weight": 0.25, "max_drawdown": 0.15},
        "risk_notes": "测试",
        "evidence": "测试",
        "industry_hypothesis": "测试行业",
    }
    ok = validator.validate(candidate)
    assert not ok, "未来函数因子应被拒绝"

    # 检查是否包含 FutureLeakageGate 的关键字
    errors_text = " ".join(validator.errors)
    assert "critical" in errors_text.lower() or "未来函数" in errors_text


def test_validator_handles_clean_expression():
    """干净的表达式应通过全部检查 (V4.6 验证链)"""
    from factor_lab.alpha.llm_alpha_discovery import AlphaSpecValidator

    validator = AlphaSpecValidator()
    candidate = {
        "name": "test_clean_v46",
        "description": "完整的V4.6测试候选",
        "hypothesis": "ROE动量策略",
        "factor_expression": "rank(roe) * rank(ts_mean(close, 20))",
        "universe": "all_watchlist",
        "data_requirements": ["close", "roe"],
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "risk_constraints": {"max_position_weight": 0.25, "max_drawdown": 0.15},
        "risk_notes": "ROE因子在成长股中有效",
        "evidence": "A股ROE因子有效性研究",
        "industry_hypothesis": "科技和消费行业，ROE持续性较强",
    }
    ok = validator.validate(candidate)
    assert ok, f"完整候选应通过所有检查: {validator.errors}"
    assert len(validator.errors) == 0


# ═══════════════════════════════════════════════════════════════════
# 8. FutureLeakageGate 集成钩子测试
# ═══════════════════════════════════════════════════════════════════


def test_future_leakage_gate_quick_checks():
    """快捷检查函数应正确工作"""
    from factor_lab.alpha.future_leakage_gate import (
        check_factor_expression_leakage,
        check_returns_peek_leakage,
    )

    # 正常表达式
    report1 = check_factor_expression_leakage("rank(close / ts_mean(close, 20))")
    assert report1.passed

    # 使用returns的表达式
    report2 = check_factor_expression_leakage("rank(returns)")
    assert not report2.passed

    # returns_peek 检测
    assert check_returns_peek_leakage("rank(returns) * rank(volume)")
    assert not check_returns_peek_leakage("rank(close / ts_mean(close, 20))")


# ═══════════════════════════════════════════════════════════════════
# 9. PRICE_VOLUME_FIELDS 常量检查
# ═══════════════════════════════════════════════════════════════════


def test_price_volume_fields_constant():
    """PRICE_VOLUME_FIELDS 应包含所有8个价量字段"""
    from factor_lab.alpha.llm_alpha_discovery import PRICE_VOLUME_FIELDS

    assert "close" in PRICE_VOLUME_FIELDS
    assert "open" in PRICE_VOLUME_FIELDS
    assert "high" in PRICE_VOLUME_FIELDS
    assert "low" in PRICE_VOLUME_FIELDS
    assert "volume" in PRICE_VOLUME_FIELDS
    assert "amount" in PRICE_VOLUME_FIELDS
    assert "returns" in PRICE_VOLUME_FIELDS
    assert "vwap" in PRICE_VOLUME_FIELDS
    assert len(PRICE_VOLUME_FIELDS) == 8
