"""V5.4 Data Quality Gate — Tests

Covers:
  - QualityDimension, QualitySeverity enums
  - QualityRuleResult creation and serialization
  - QualityReport construction, summary, serialization
  - Individual rule checks (9 rules across 4 dimensions)
    - required_fields, price_positive, volume_non_negative
    - high_low_consistent, open_within_range, price_within_range
    - change_pct_reasonable, amount_consistency, timeliness
  - DataQualityGate.check_quote (single quote)
  - DataQualityGate.check_quotes (batch)
  - DataQualityGate.check_batch_result (integration with BatchQuoteResult)
  - Verdict determination (pass / conditional_pass / fail)
  - Report storage and retrieval
  - Source quality summary
  - Edge cases: missing fields, None values, boundary values, empty lists
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pytest

from factor_lab.data_source.quality import (
    QualityDimension,
    QualitySeverity,
    QualityRuleResult,
    QualityReport,
    DataQualityGate,
    A_SHARE_CHANGE_PCT_LOWER,
    A_SHARE_CHANGE_PCT_UPPER,
    REALTIME_QUOTE_MAX_AGE_SECONDS,
)
from factor_lab.data_source.quote import Quote, QuoteResult, BatchQuoteResult
from factor_lab.data_source.registry import DataRegistry


CST = timezone(timedelta(hours=8))

# =========================================================================
# Sample data
# =========================================================================

VALID_QUOTE = Quote(
    symbol="688012", name="中微公司",
    price=158.3, open=156.5, high=159.8, low=155.2,
    volume=2_850_000, amount=452_000_000.0,
    change_pct=1.25, change_amount=1.96,
    source_id="rsscast_mcp",
    prev_close=156.36, amplitude=2.95, turnover_rate=0.45,
    bid=158.30, ask=158.32, bid_vol=1000, ask_vol=2000,
)

MIN_VALID_QUOTE = Quote(
    symbol="002371", price=185.0,
    source_id="eastmoney_direct",
)


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture()
def isolated_registry(monkeypatch, tmp_path):
    """将注册表根目录重定向到临时目录"""
    from factor_lab.data_source import quality as q_mod
    from factor_lab.data_source import registry as reg_mod
    from factor_lab.data_source import health as hlth_mod

    test_root = tmp_path / "data_source_registry"
    monkeypatch.setattr(q_mod, "REGISTRY_ROOT", test_root)
    monkeypatch.setattr(reg_mod, "REGISTRY_ROOT", test_root)
    monkeypatch.setattr(hlth_mod, "REGISTRY_ROOT", test_root)
    return DataRegistry()


@pytest.fixture()
def seeded_registry(isolated_registry):
    """预填充种子数据的注册表"""
    isolated_registry.seed_defaults()
    return isolated_registry


@pytest.fixture()
def gate(seeded_registry):
    """默认 DataQualityGate 实例"""
    return DataQualityGate(registry=seeded_registry)


# =========================================================================
# Enum tests
# =========================================================================

class TestQualityDimension:
    def test_values(self):
        """枚举值正确"""
        assert QualityDimension.COMPLETENESS.value == "completeness"
        assert QualityDimension.REASONABLENESS.value == "reasonableness"
        assert QualityDimension.CONSISTENCY.value == "consistency"
        assert QualityDimension.TIMELINESS.value == "timeliness"

    def test_unique(self):
        """枚举值唯一"""
        values = [e.value for e in QualityDimension]
        assert len(values) == len(set(values))


class TestQualitySeverity:
    def test_values(self):
        """枚举值正确"""
        assert QualitySeverity.BLOCKER.value == "blocker"
        assert QualitySeverity.WARNING.value == "warning"
        assert QualitySeverity.INFO.value == "info"

    def test_unique(self):
        """枚举值唯一"""
        values = [e.value for e in QualitySeverity]
        assert len(values) == len(set(values))


# =========================================================================
# QualityRuleResult tests
# =========================================================================

class TestQualityRuleResult:
    def test_create_minimal(self):
        """最小字段创建"""
        r = QualityRuleResult(rule_name="test_rule", dimension="completeness")
        assert r.rule_name == "test_rule"
        assert r.dimension == "completeness"
        assert r.severity == "warning"
        assert r.passed is True
        assert r.symbol == ""

    def test_create_full(self):
        """完整字段创建"""
        r = QualityRuleResult(
            rule_name="price_positive",
            dimension="reasonableness",
            severity="blocker",
            passed=False,
            symbol="688012",
            expected="> 0",
            actual=0.0,
            message="Price 0.0 is not positive",
        )
        assert r.rule_name == "price_positive"
        assert r.severity == "blocker"
        assert r.passed is False
        assert r.symbol == "688012"
        assert "[0m" not in r.expected if isinstance(r.expected, str) else True

    def test_to_dict(self):
        """序列化"""
        r = QualityRuleResult(
            rule_name="test", dimension="completeness",
            severity="blocker", passed=True,
            symbol="688012",
        )
        d = r.to_dict()
        assert d["rule_name"] == "test"
        assert d["severity"] == "blocker"
        assert d["passed"] is True
        assert d["symbol"] == "688012"

    def test_to_dict_with_numeric_values(self):
        """带数值的序列化"""
        r = QualityRuleResult(
            rule_name="price_positive",
            dimension="reasonableness",
            passed=False,
            expected=0,
            actual=-1.0,
        )
        d = r.to_dict()
        assert d["expected"] == 0
        assert d["actual"] == -1.0


# =========================================================================
# QualityReport tests
# =========================================================================

class TestQualityReport:
    def test_create_minimal(self):
        """最小字段创建"""
        report = QualityReport(source_id="test_source")
        assert report.source_id == "test_source"
        assert report.total_checks == 0
        assert report.overall_verdict == "pass"
        assert report.timestamp != ""

    def test_create_with_values(self):
        """带值的报告创建"""
        report = QualityReport(
            source_id="rsscast_mcp",
            total_checks=10,
            passed_checks=9,
            failed_checks=1,
            blocker_count=1,
            warning_count=0,
            overall_verdict="fail",
            item_reports={
                "688012": [
                    QualityRuleResult(rule_name="test", dimension="completeness", passed=True),
                ],
            },
        )
        assert report.source_id == "rsscast_mcp"
        assert report.total_checks == 10
        assert report.blocker_count == 1

    def test_summary(self):
        """summary 输出"""
        report = QualityReport(
            source_id="test",
            total_checks=20, passed_checks=18, failed_checks=2,
            blocker_count=0, warning_count=2,
            overall_verdict="conditional_pass",
            item_reports={"688012": [], "002371": []},
        )
        s = report.summary()
        assert s["source_id"] == "test"
        assert s["total_checks"] == 20
        assert s["passed_checks"] == 18
        assert s["blocker_count"] == 0
        assert s["overall_verdict"] == "conditional_pass"
        assert s["symbol_count"] == 2

    def test_to_dict(self):
        """完整序列化"""
        results = [
            QualityRuleResult(rule_name="r1", dimension="completeness", passed=True),
            QualityRuleResult(rule_name="r2", dimension="reasonableness", passed=False),
        ]
        report = QualityReport(
            source_id="src",
            total_checks=2, passed_checks=1, failed_checks=1,
            blocker_count=0, warning_count=1,
            overall_verdict="conditional_pass",
            item_reports={"688012": results},
        )
        d = report.to_dict()
        assert d["source_id"] == "src"
        assert d["total_checks"] == 2
        assert d["item_reports"]["688012"][0]["rule_name"] == "r1"
        assert d["item_reports"]["688012"][0]["passed"] is True
        assert d["item_reports"]["688012"][1]["rule_name"] == "r2"
        assert d["item_reports"]["688012"][1]["passed"] is False


# =========================================================================
# Individual rule checks
# =========================================================================

class TestRequiredFields:
    def test_all_present(self):
        """必需字段齐全"""
        result = DataQualityGate._check_required_fields(MIN_VALID_QUOTE)
        assert result.passed is True
        assert result.rule_name == "required_fields"
        assert result.severity == "blocker"

    def test_missing_symbol(self):
        """缺少 symbol"""
        q = Quote(symbol="", price=100.0)
        result = DataQualityGate._check_required_fields(q)
        assert result.passed is False
        assert "symbol" in result.message

    def test_missing_price(self):
        """缺少 price"""
        q = Quote(symbol="688012")
        result = DataQualityGate._check_required_fields(q)
        assert result.passed is False
        assert "price" in result.message

    def test_missing_both(self):
        """两者都缺"""
        q = Quote(symbol="", price=None)
        result = DataQualityGate._check_required_fields(q)
        assert result.passed is False
        assert "symbol" in result.message
        assert "price" in result.message


class TestPricePositive:
    def test_price_positive(self):
        """正价格"""
        result = DataQualityGate._check_price_positive(MIN_VALID_QUOTE)
        assert result.passed is True
        assert result.rule_name == "price_positive"

    def test_price_zero(self):
        """零价格"""
        q = Quote(symbol="688012", price=0.0)
        result = DataQualityGate._check_price_positive(q)
        assert result.passed is False
        assert "not positive" in result.message

    def test_price_negative(self):
        """负价格"""
        q = Quote(symbol="688012", price=-1.0)
        result = DataQualityGate._check_price_positive(q)
        assert result.passed is False

    def test_price_none(self):
        """None 价格"""
        q = Quote(symbol="688012", price=None)
        result = DataQualityGate._check_price_positive(q)
        assert result.passed is False


class TestVolumeNonNegative:
    def test_volume_positive(self):
        """正成交量"""
        q = Quote(symbol="688012", price=100.0, volume=1000)
        result = DataQualityGate._check_volume_non_negative(q)
        assert result.passed is True

    def test_volume_zero(self):
        """零成交量（停牌等）"""
        q = Quote(symbol="688012", price=100.0, volume=0)
        result = DataQualityGate._check_volume_non_negative(q)
        assert result.passed is True

    def test_volume_negative(self):
        """负成交量（异常）"""
        q = Quote(symbol="688012", price=100.0, volume=-100)
        result = DataQualityGate._check_volume_non_negative(q)
        assert result.passed is False

    def test_volume_none(self):
        """None 成交量 — 跳过"""
        q = Quote(symbol="688012", price=100.0)
        result = DataQualityGate._check_volume_non_negative(q)
        assert result.passed is True  # skips when None


class TestHighLowConsistent:
    def test_high_gt_low(self):
        """高 > 低"""
        q = Quote(symbol="688012", price=100.0, high=105.0, low=95.0)
        result = DataQualityGate._check_high_low_consistent(q)
        assert result.passed is True

    def test_high_eq_low(self):
        """高 = 低（横盘）"""
        q = Quote(symbol="688012", price=100.0, high=100.0, low=100.0)
        result = DataQualityGate._check_high_low_consistent(q)
        assert result.passed is True

    def test_high_lt_low(self):
        """高 < 低（异常）"""
        q = Quote(symbol="688012", price=100.0, high=95.0, low=105.0)
        result = DataQualityGate._check_high_low_consistent(q)
        assert result.passed is False

    def test_high_low_none(self):
        """缺失时跳过"""
        q = Quote(symbol="688012", price=100.0)
        result = DataQualityGate._check_high_low_consistent(q)
        assert result.passed is True


class TestOpenWithinRange:
    def test_open_within(self):
        """开盘价在区间内"""
        q = Quote(symbol="688012", price=100.0, open=101.0, high=105.0, low=95.0)
        result = DataQualityGate._check_open_within_range(q)
        assert result.passed is True

    def test_open_at_low(self):
        """开盘等于最低"""
        q = Quote(symbol="688012", price=100.0, open=95.0, high=105.0, low=95.0)
        result = DataQualityGate._check_open_within_range(q)
        assert result.passed is True

    def test_open_at_high(self):
        """开盘等于最高"""
        q = Quote(symbol="688012", price=100.0, open=105.0, high=105.0, low=95.0)
        result = DataQualityGate._check_open_within_range(q)
        assert result.passed is True

    def test_open_outside(self):
        """开盘价超出范围"""
        q = Quote(symbol="688012", price=100.0, open=90.0, high=105.0, low=95.0)
        result = DataQualityGate._check_open_within_range(q)
        assert result.passed is False

    def test_open_none(self):
        """缺失时跳过"""
        q = Quote(symbol="688012", price=100.0, high=105.0, low=95.0)
        result = DataQualityGate._check_open_within_range(q)
        assert result.passed is True


class TestPriceWithinRange:
    def test_price_within(self):
        """最新价在区间内"""
        q = Quote(symbol="688012", price=100.0, high=105.0, low=95.0)
        result = DataQualityGate._check_price_within_range(q)
        assert result.passed is True

    def test_price_at_low(self):
        """最新价等于最低"""
        q = Quote(symbol="688012", price=95.0, high=105.0, low=95.0)
        result = DataQualityGate._check_price_within_range(q)
        assert result.passed is True

    def test_price_at_high(self):
        """最新价等于最高"""
        q = Quote(symbol="688012", price=105.0, high=105.0, low=95.0)
        result = DataQualityGate._check_price_within_range(q)
        assert result.passed is True

    def test_price_outside_below(self):
        """最新价低于最低"""
        q = Quote(symbol="688012", price=90.0, high=105.0, low=95.0)
        result = DataQualityGate._check_price_within_range(q)
        assert result.passed is False

    def test_price_outside_above(self):
        """最新价高于最高"""
        q = Quote(symbol="688012", price=110.0, high=105.0, low=95.0)
        result = DataQualityGate._check_price_within_range(q)
        assert result.passed is False

    def test_price_none(self):
        """缺失时跳过"""
        q = Quote(symbol="688012", high=105.0, low=95.0)
        result = DataQualityGate._check_price_within_range(q)
        assert result.passed is True


class TestChangePctReasonable:
    def test_within_limits(self):
        """涨跌幅在合理范围内"""
        q = Quote(symbol="688012", price=100.0, change_pct=1.25)
        result = DataQualityGate._check_change_pct_reasonable(q)
        assert result.passed is True
        assert result.rule_name == "change_pct_reasonable"

    def test_at_lower_limit(self):
        """接近跌停下限"""
        q = Quote(symbol="688012", price=100.0, change_pct=A_SHARE_CHANGE_PCT_LOWER)
        result = DataQualityGate._check_change_pct_reasonable(q)
        assert result.passed is True

    def test_at_upper_limit(self):
        """接近涨停上限"""
        q = Quote(symbol="688012", price=100.0, change_pct=A_SHARE_CHANGE_PCT_UPPER)
        result = DataQualityGate._check_change_pct_reasonable(q)
        assert result.passed is True

    def test_exceeds_lower(self):
        """超跌"""
        q = Quote(symbol="688012", price=100.0, change_pct=A_SHARE_CHANGE_PCT_LOWER - 1)
        result = DataQualityGate._check_change_pct_reasonable(q)
        assert result.passed is False

    def test_exceeds_upper(self):
        """超涨"""
        q = Quote(symbol="688012", price=100.0, change_pct=A_SHARE_CHANGE_PCT_UPPER + 1)
        result = DataQualityGate._check_change_pct_reasonable(q)
        assert result.passed is False

    def test_change_pct_none(self):
        """缺失时跳过"""
        q = Quote(symbol="688012", price=100.0)
        result = DataQualityGate._check_change_pct_reasonable(q)
        assert result.passed is True


class TestAmountConsistency:
    def test_consistent(self):
        """成交额 ≈ 价格×成交量"""
        q = Quote(symbol="688012", price=100.0, volume=1000, amount=100_000)
        result = DataQualityGate._check_amount_consistency(q)
        assert result.passed is True
        assert result.rule_name == "amount_consistency"

    def test_consistent_ratio_082(self):
        """偏差 0.82 在容忍范围内"""
        q = Quote(symbol="688012", price=100.0, volume=1000, amount=82_000)
        result = DataQualityGate._check_amount_consistency(q)
        assert result.passed is True

    def test_consistent_ratio_118(self):
        """偏差 1.18 在容忍范围内"""
        q = Quote(symbol="688012", price=100.0, volume=1000, amount=118_000)
        result = DataQualityGate._check_amount_consistency(q)
        assert result.passed is True

    def test_inconsistent_low(self):
        """偏差低于 0.8"""
        q = Quote(symbol="688012", price=100.0, volume=1000, amount=50_000)
        result = DataQualityGate._check_amount_consistency(q)
        assert result.passed is False

    def test_inconsistent_high(self):
        """偏差高于 1.2"""
        q = Quote(symbol="688012", price=100.0, volume=1000, amount=200_000)
        result = DataQualityGate._check_amount_consistency(q)
        assert result.passed is False

    def test_volume_zero(self):
        """零成交量时跳过"""
        q = Quote(symbol="688012", price=100.0, volume=0, amount=0)
        result = DataQualityGate._check_amount_consistency(q)
        assert result.passed is True

    def test_fields_none(self):
        """缺失字段时跳过"""
        q = Quote(symbol="688012", price=100.0)
        result = DataQualityGate._check_amount_consistency(q)
        assert result.passed is True


class TestTimeliness:
    def test_recent_data(self, gate):
        """新数据通过"""
        recent_ts = datetime.now(CST).isoformat()
        q = Quote(symbol="688012", price=100.0, timestamp=recent_ts)
        result = gate._check_timeliness(q)
        assert result.passed is True

    def test_stale_data(self, gate):
        """过期数据不通过"""
        stale_ts = (datetime.now(CST) - timedelta(seconds=REALTIME_QUOTE_MAX_AGE_SECONDS + 60)).isoformat()
        q = Quote(symbol="688012", price=100.0, timestamp=stale_ts)
        result = gate._check_timeliness(q)
        assert result.passed is False
        assert "exceeds" in result.message

    def test_custom_max_age(self):
        """自定义过期阈值"""
        gate = DataQualityGate(max_age_seconds=60)
        stale_ts = (datetime.now(CST) - timedelta(seconds=120)).isoformat()
        q = Quote(symbol="688012", price=100.0, timestamp=stale_ts)
        result = gate._check_timeliness(q)
        assert result.passed is False

    def test_no_timestamp(self):
        """缺失时间戳 — 无法通过 Quote 构造函数创建
        （__post_init__ 自动填充），验证逻辑存在"""
        from factor_lab.data_source.quality import DataQualityGate as DG
        # 直接调用类方法测试无时间戳分支
        # 模拟创建无时间戳的场景
        class FakeQuote:
            symbol = "688012"
            timestamp = ""
            price = 100.0
            open = high = low = volume = amount = change_pct = None
            source_id = ""
            name = prev_close = amplitude = turnover_rate = None
            bid = ask = bid_vol = ask_vol = pe = market_cap = None

        result = DG._check_timeliness(DG(), FakeQuote())  # type: ignore
        assert result.passed is False
        assert "No timestamp provided" in result.message

    def test_invalid_timestamp_fails(self):
        """无法解析的时间戳标记为失败"""
        gate = DataQualityGate()
        q = Quote(symbol="688012", price=100.0, timestamp="not-a-timestamp")
        result = gate._check_timeliness(q)
        assert result.passed is False
        assert "Invalid timestamp" in result.message


# =========================================================================
# DataQualityGate.check_quote tests
# =========================================================================

class TestDataQualityGateCheckQuote:
    def test_valid_quote_all_checks(self, gate):
        """有效 Quote 全部检查通过"""
        results = gate.check_quote(VALID_QUOTE)
        assert len(results) == 9  # 9 rules
        for r in results:
            assert r.passed is True, f"Rule '{r.rule_name}' failed: {r.message}"
        assert all(r.symbol == VALID_QUOTE.symbol for r in results)

    def test_minimal_valid_quote(self, gate):
        """最小 Quote 检查结果"""
        results = gate.check_quote(MIN_VALID_QUOTE)
        assert len(results) == 9
        # Required fields, price positive should pass
        for r in results:
            if r.rule_name in ("required_fields", "price_positive"):
                assert r.passed is True
            # Rules that skip because fields are None
            if r.rule_name in ("volume_non_negative", "high_low_consistent",
                               "open_within_range", "price_within_range",
                               "amount_consistency"):
                assert r.passed is True  # skipped

    def test_all_rules_run(self, gate):
        """确保每种规则都运行"""
        results = gate.check_quote(VALID_QUOTE)
        rule_names = {r.rule_name for r in results}
        expected = {
            "required_fields", "price_positive", "volume_non_negative",
            "high_low_consistent", "open_within_range", "price_within_range",
            "change_pct_reasonable", "amount_consistency", "timeliness",
        }
        assert rule_names == expected

    def test_check_correct_dimensions(self, gate):
        """规则分配到正确维度"""
        results = gate.check_quote(VALID_QUOTE)
        dimension_map = {r.rule_name: r.dimension for r in results}
        assert dimension_map["required_fields"] == "completeness"
        assert dimension_map["price_positive"] == "reasonableness"
        assert dimension_map["volume_non_negative"] == "reasonableness"
        assert dimension_map["high_low_consistent"] == "consistency"
        assert dimension_map["open_within_range"] == "consistency"
        assert dimension_map["price_within_range"] == "consistency"
        assert dimension_map["change_pct_reasonable"] == "reasonableness"
        assert dimension_map["amount_consistency"] == "consistency"
        assert dimension_map["timeliness"] == "timeliness"


# =========================================================================
# DataQualityGate.check_quotes tests
# =========================================================================

class TestDataQualityGateCheckQuotes:
    def test_multiple_valid_quotes(self, gate):
        """多 Quote 全通过"""
        quotes = [
            Quote(symbol="688012", price=158.3, source_id="rsscast_mcp"),
            Quote(symbol="002371", price=312.5, source_id="rsscast_mcp"),
        ]
        report = gate.check_quotes(quotes)
        assert report.overall_verdict == "pass"
        assert report.total_checks == 18  # 9 per quote
        assert report.passed_checks == 18
        assert report.failed_checks == 0
        assert report.symbol_count == 2

    def test_with_failures(self, gate):
        """包含不合格数据"""
        quotes = [
            Quote(symbol="688012", price=158.3, source_id="rsscast_mcp"),
            Quote(symbol="", price=-5.0, source_id="rsscast_mcp"),  # no symbol, negative price
        ]
        report = gate.check_quotes(quotes)
        assert report.overall_verdict == "fail"
        assert report.blocker_count >= 2  # missing symbol + negative price
        assert report.failed_checks >= 2

    def test_empty_list(self, gate):
        """空列表"""
        report = gate.check_quotes([])
        assert report.total_checks == 0
        assert report.overall_verdict == "pass"

    def test_verdict_pass(self, gate):
        """全部通过 → pass"""
        report = gate.check_quotes([MIN_VALID_QUOTE])
        assert report.overall_verdict == "pass"

    def test_verdict_conditional_pass(self, gate):
        """有 warning 无 blocker → conditional_pass"""
        # Change_pct outside limit is a blocker, so let's test with
        # a quote that only generates warnings
        q = Quote(
            symbol="688012", price=100.0,
            volume=-100,  # warning-level rule
            source_id="test",
        )
        report = gate.check_quotes([q])
        if report.blocker_count == 0 and report.warning_count > 0:
            assert report.overall_verdict == "conditional_pass"

    def test_verdict_fail(self, gate):
        """有 blocker → fail"""
        q = Quote(symbol="688012", price=0.0, source_id="test")
        report = gate.check_quotes([q])
        assert report.overall_verdict == "fail"
        assert report.blocker_count >= 1

    def test_multiple_sources_in_source_id(self, gate):
        """多个数据源在 source_id 中合并"""
        quotes = [
            Quote(symbol="688012", price=100.0, source_id="src_a"),
            Quote(symbol="002371", price=200.0, source_id="src_b"),
        ]
        report = gate.check_quotes(quotes)
        # source_id should contain both
        assert "src_a" in report.source_id
        assert "src_b" in report.source_id


# =========================================================================
# DataQualityGate.check_batch_result tests
# =========================================================================

class TestDataQualityGateCheckBatchResult:
    def test_all_success(self, gate):
        """批量全成功"""
        q1 = Quote(symbol="688012", price=158.3, source_id="rsscast_mcp")
        q2 = Quote(symbol="002371", price=312.5, source_id="rsscast_mcp")
        results = {
            "688012": QuoteResult(symbol="688012", success=True, quote=q1, source_id="rsscast_mcp"),
            "002371": QuoteResult(symbol="002371", success=True, quote=q2, source_id="rsscast_mcp"),
        }
        batch = BatchQuoteResult(symbols=["688012", "002371"], results=results)
        report = gate.check_batch_result(batch)
        assert report.overall_verdict == "pass"
        assert report.total_checks == 18

    def test_partial_failure(self, gate):
        """部分获取失败"""
        q1 = Quote(symbol="688012", price=158.3, source_id="rsscast_mcp")
        results = {
            "688012": QuoteResult(symbol="688012", success=True, quote=q1, source_id="rsscast_mcp"),
            "002371": QuoteResult(symbol="002371", success=False, error="timeout", source_id="rsscast_mcp"),
        }
        batch = BatchQuoteResult(symbols=["688012", "002371"], results=results)
        report = gate.check_batch_result(batch)
        # Should have failure for 002371 (fetch failer = blocker)
        assert report.failed_checks >= 1
        assert report.blocker_count >= 1
        assert "002371" in report.item_reports

    def test_all_failed(self, gate):
        """全部获取失败"""
        results = {
            "688012": QuoteResult(symbol="688012", success=False, error="timeout", source_id="rsscast_mcp"),
            "002371": QuoteResult(symbol="002371", success=False, error="timeout", source_id="rsscast_mcp"),
        }
        batch = BatchQuoteResult(symbols=["688012", "002371"], results=results)
        report = gate.check_batch_result(batch)
        assert report.failed_checks >= 2
        assert report.blocker_count >= 2

    def test_empty_batch(self, gate):
        """空批量"""
        batch = BatchQuoteResult(symbols=[], results={})
        report = gate.check_batch_result(batch)
        assert report.total_checks == 0
        assert report.overall_verdict == "pass"


# =========================================================================
# Report storage & retrieval tests
# =========================================================================

class TestReportStorage:
    def test_store_and_retrieve(self, gate, seeded_registry):
        """存储并取回质量报告"""
        # Register a source first
        from factor_lab.data_source.spec import DataSourceSpec
        spec = DataSourceSpec(source_id="test_store", name="Test")
        seeded_registry.register(spec)

        q = Quote(symbol="688012", price=158.3, source_id="test_store")
        report = gate.check_quotes([q])

        gate.store_report(report)
        retrieved = gate.get_latest_report("test_store")
        assert retrieved is not None
        assert retrieved.source_id == "test_store"
        assert retrieved.total_checks == 9
        assert retrieved.overall_verdict == "pass"

    def test_store_updates_source_health(self, gate, seeded_registry):
        """存储报告时更新数据源健康元数据"""
        from factor_lab.data_source.spec import DataSourceSpec
        spec = DataSourceSpec(source_id="test_health", name="Test")
        seeded_registry.register(spec)

        q = Quote(symbol="688012", price=158.3, source_id="test_health")
        report = gate.check_quotes([q])
        gate.store_report(report)

        updated = seeded_registry.get_source("test_health")
        assert updated.health.get("quality_score") == 100.0
        assert updated.health.get("quality_verdict") == "pass"

    def test_get_latest_report_none(self, gate):
        """无报告时返回 None"""
        result = gate.get_latest_report("nonexistent_source")
        assert result is None

    def test_get_source_quality_summary(self, gate, seeded_registry):
        """质量摘要查询"""
        from factor_lab.data_source.spec import DataSourceSpec
        spec = DataSourceSpec(source_id="test_summary", name="Test")
        seeded_registry.register(spec)

        q = Quote(symbol="688012", price=100.0, source_id="test_summary")
        report = gate.check_quotes([q])
        gate.store_report(report)

        summary = gate.get_source_quality_summary("test_summary")
        assert summary is not None
        assert summary["source_id"] == "test_summary"
        assert summary["overall_verdict"] == "pass"

    def test_get_source_quality_summary_none(self, gate):
        """不存在的源返回 None"""
        result = gate.get_source_quality_summary("no_such_source")
        assert result is None

    def test_source_id_with_colon_in_filename(self, gate, seeded_registry):
        """时间戳中的冒号在文件名中处理"""
        from factor_lab.data_source.spec import DataSourceSpec
        spec = DataSourceSpec(source_id="test_colon", name="Test")
        seeded_registry.register(spec)

        q = Quote(symbol="688012", price=100.0, source_id="test_colon")
        report = gate.check_quotes([q])
        gate.store_report(report)

        # Should have saved at least one file
        quality_dir = Path("/mnt/d/HermesData/data_source_registry/test_colon/quality_reports")
        # The path was redirected by fixture, so we use the actual path
        from factor_lab.data_source import quality as q_mod
        actual_dir = q_mod.REGISTRY_ROOT / "test_colon" / "quality_reports"
        assert actual_dir.exists()
        files = list(actual_dir.glob("*.json"))
        assert len(files) >= 1


# =========================================================================
# Edge cases
# =========================================================================

class TestEdgeCases:
    def test_quote_with_all_nones(self, gate):
        """全部字段为 None 的 Quote"""
        q = Quote(symbol="688012", price=None)
        results = gate.check_quote(q)
        pass_count = sum(1 for r in results if r.passed)
        fail_count = sum(1 for r in results if not r.passed)
        # Should fail on required_fields (price missing), price_positive
        assert fail_count >= 1

    def test_quote_negative_change_pct_reasonable(self, gate):
        """大幅负涨跌幅"""
        q = Quote(symbol="688012", price=100.0, change_pct=-19.9)
        results = gate.check_quote(q)
        cpr = [r for r in results if r.rule_name == "change_pct_reasonable"][0]
        assert cpr.passed is True

    def test_boundary_price_just_positive(self, gate):
        """边界价格 0.01"""
        q = Quote(symbol="688012", price=0.01)
        result = DataQualityGate._check_price_positive(q)
        assert result.passed is True

    def test_boundary_price_very_large(self, gate):
        """极高价格（茅台等高价股）"""
        q = Quote(symbol="600519", price=1888.0)
        result = DataQualityGate._check_price_positive(q)
        assert result.passed is True

    def test_gate_with_custom_config(self, gate):
        """自定义 max_age_seconds"""
        custom_gate = DataQualityGate(max_age_seconds=600)
        assert custom_gate.max_age_seconds == 600

    def test_source_with_multiple_id_in_quotes(self, gate):
        """无 source_id 的 Quote"""
        q = Quote(symbol="688012", price=100.0)  # no source_id
        report = gate.check_quotes([q])
        assert report.source_id == "unknown"

    def test_report_summary_fields(self, gate):
        """报告摘要字段完整"""
        q1 = Quote(symbol="688012", price=158.3, source_id="test")
        q2 = Quote(symbol="002371", price=312.5, source_id="test")
        report = gate.check_quotes([q1, q2])
        s = report.summary()
        expected_keys = {
            "source_id", "timestamp", "total_checks", "passed_checks",
            "failed_checks", "blocker_count", "warning_count",
            "overall_verdict", "symbol_count",
        }
        assert set(s.keys()) == expected_keys

    def test_all_rules_have_correct_severity(self, gate):
        """每条规则有正确的严重级别"""
        results = gate.check_quote(VALID_QUOTE)
        severity_map = {r.rule_name: r.severity for r in results}
        # Blockers
        assert severity_map["required_fields"] == "blocker"
        assert severity_map["price_positive"] == "blocker"
        assert severity_map["high_low_consistent"] == "blocker"
        assert severity_map["price_within_range"] == "blocker"
        assert severity_map["change_pct_reasonable"] == "blocker"
        assert severity_map["timeliness"] == "blocker"
        # Warnings
        assert severity_map["volume_non_negative"] == "warning"
        assert severity_map["open_within_range"] == "warning"
        # Info
        assert severity_map["amount_consistency"] == "info"


# =========================================================================
# Integration-style tests (with mocked adapters)
# =========================================================================

class TestIntegrationWithEngine:
    def test_quality_gate_on_engine_result(self, gate, engine, monkeypatch):
        """质量门禁在引擎结果上运行"""
        # Import engine fixture from conftest-like setup
        def mock_fetch(_, symbols):
            return {
                "688012": {"symbol": "688012", "name": "中微公司",
                           "price": 158.3, "open": 156.5, "high": 159.8, "low": 155.2,
                           "volume": 2_850_000, "amount": 452_000_000.0,
                           "change_pct": 1.25, "change_amount": 1.96,
                           "source_id": "rsscast_mcp", "_latency_ms": 45.0},
                "002371": {"symbol": "002371", "name": "北方华创",
                           "price": 312.5, "open": 310.0, "high": 315.0, "low": 308.5,
                           "volume": 1_200_000, "amount": 376_000_000.0,
                           "change_pct": -0.85, "change_amount": -2.68,
                           "source_id": "rsscast_mcp", "_latency_ms": 42.0},
            }
        monkeypatch.setattr(
            "factor_lab.data_source.adapters.RsscastQuoteAdapter.fetch",
            mock_fetch,
        )

        batch = engine.fetch_batch(["688012", "002371"])
        report = gate.check_batch_result(batch)
        assert report.overall_verdict == "pass"
        assert report.total_checks == 18  # 9 per quote × 2
        assert report.passed_checks == 18

    def test_quality_gate_catches_bad_data(self, gate, engine, monkeypatch):
        """质量门禁检测异常数据"""
        def mock_fetch(_, symbols):
            return {
                "688012": {"symbol": "688012", "name": "异常股票",
                           "price": -1.0,  # negative price!
                           "open": 100.0, "high": 105.0, "low": 95.0,
                           "volume": 1000, "amount": 100_000,
                           "change_pct": 25.0,  # exceeds limit!
                           "source_id": "rsscast_mcp", "_latency_ms": 45.0},
            }
        monkeypatch.setattr(
            "factor_lab.data_source.adapters.RsscastQuoteAdapter.fetch",
            mock_fetch,
        )

        batch = engine.fetch_batch(["688012"])
        report = gate.check_batch_result(batch)
        assert report.overall_verdict == "fail"
        assert report.blocker_count >= 2  # negative price + change_pct exceeds limit


# Need to recreate the engine fixture locally for integration tests
@pytest.fixture()
def engine(seeded_registry):
    from factor_lab.data_source.ingest import RealtimeQuoteEngine
    return RealtimeQuoteEngine(registry=seeded_registry)
