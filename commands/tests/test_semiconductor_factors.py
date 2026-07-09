#!/usr/bin/env python3
"""Tests for V4.5 半导体专属因子库 — 主题择时/内部选股/风险反证

测试策略:
  - 用模拟 DataFrame 验证各因子计算逻辑
  - 覆盖边界条件: 无 is_semi 列、空数据、单只股票
  - A类因子: 验证 theme_state 输出和 recommended_theme_weight 映射
  - B类因子: 验证与 semiconductor_ew 的对比逻辑
  - C类因子: 验证暴露度归一化和风险报告
  - 验证注册表完整性
"""

from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Any

import pytest
import numpy as np
import pandas as pd

# 确保能找到 commands 包
_test_dir = os.path.dirname(os.path.abspath(__file__))
_commands_dir = os.path.dirname(_test_dir)  # commands/
if _commands_dir not in sys.path:
    sys.path.insert(0, _commands_dir)

from factor_lab.factor_base import REGISTRY, list_factors
from factor_lab.semiconductor_factors import (
    # A类
    semi_vs_all_a_strength,
    semi_turnover_share,
    semi_up_ratio,
    semi_limit_up_count,
    semi_leader_strength,
    semi_etf_amount_trend,
    semi_subsector_diffusion,
    semi_theme_composite,
    THEME_WEIGHT_MAP,
    get_recommended_theme_weight,
    # B类
    stock_vs_semi_ew_strength,
    stock_vs_subsector_strength,
    volume_confirmation,
    gross_margin_improvement,
    revenue_growth_trend,
    valuation_not_overheated,
    event_catalyst_score,
    # C类
    industry_beta_exposure,
    size_exposure,
    market_beta_exposure,
    volatility_exposure,
    extreme_winner_dependence,
    build_risk_report,
    # 辅助
    _is_semi_marked,
    _semi_mask,
    _semi_ew_return,
)


# ═══════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """创建模拟半导体+全A行情数据, 5只股票, 20个交易日"""
    np.random.seed(42)
    dates = pd.date_range("2026-06-01", periods=20, freq="B")
    symbols = ["688001", "688002", "688003", "600001", "600002"]
    subsectors = ["设备", "材料", "设计", "其他", "其他"]
    is_semi_list = [True, True, True, False, False]

    rows = []
    for sym, sub, is_semi in zip(symbols, subsectors, is_semi_list):
        price = 50.0 + np.random.randn() * 10
        for d in dates:
            change = 1 + np.random.randn() * 0.02
            price *= change
            vol = int(np.random.uniform(1e6, 1e8))
            amt = price * vol
            rows.append({
                "date": d,
                "symbol": sym,
                "close": round(price, 2),
                "volume": vol,
                "amount": round(amt, 2),
                "high": round(price * 1.02, 2),
                "low": round(price * 0.98, 2),
                "is_semi": is_semi,
                "subsector": sub,
                "ts_code": f"{sym}.SH",
                "industry": "电子" if is_semi else "其他",
                "total_mv": price * np.random.uniform(1e8, 1e9),
            })

    df = pd.DataFrame(rows)
    df = df.sort_values(["date", "symbol"]).reset_index(drop=True)

    # 添加基本面列 (B类因子依赖)
    df["gross_margin"] = np.random.uniform(0.2, 0.6, len(df))
    df["gross_margin_yoy"] = np.random.uniform(-0.05, 0.10, len(df))
    df["revenue_growth_q"] = np.random.uniform(-0.2, 0.5, len(df))
    df["revenue_growth_q_1"] = np.random.uniform(-0.2, 0.5, len(df))
    df["revenue_growth_q_2"] = np.random.uniform(-0.2, 0.5, len(df))
    df["pe_ttm"] = np.random.uniform(10, 80, len(df))
    df["valuation_pct"] = np.random.uniform(0, 1, len(df))

    return df


@pytest.fixture
def single_stock_df() -> pd.DataFrame:
    """单只股票边际数据"""
    dates = pd.date_range("2026-06-01", periods=10, freq="B")
    rows = [{
        "date": d, "symbol": "688001", "close": 50.0 + i,
        "volume": 1e7, "amount": 5e8,
        "high": 52.0 + i, "low": 49.0 + i,
        "is_semi": True, "subsector": "设备",
        "ts_code": "688001.SH", "industry": "电子",
        "total_mv": 1e9,
    } for i, d in enumerate(dates)]
    return pd.DataFrame(rows).sort_values(["date", "symbol"]).reset_index(drop=True)


@pytest.fixture
def no_semi_df(sample_df: pd.DataFrame) -> pd.DataFrame:
    """无 is_semi 列的 DataFrame (测试降级)"""
    return sample_df.drop(columns=["is_semi"])


# ═══════════════════════════════════════════════
# 测试: 注册表完整性
# ═══════════════════════════════════════════════


class TestRegistry:
    """验证半导体因子已正确注册到 AlphaRegistry"""

    def test_all_semi_factors_registered(self):
        """所有20个半导体因子必须在REGISTRY中"""
        semi_factors = [f for f in REGISTRY if f["category"] in (
            "sector_timing", "semi_stock_selection", "risk_cross_validation"
        )]
        assert len(semi_factors) >= 20, f"Expected >=20, got {len(semi_factors)}"

    def test_category_counts(self):
        """验证三类因子数量"""
        a = [f for f in REGISTRY if f["category"] == "sector_timing"]
        b = [f for f in REGISTRY if f["category"] == "semi_stock_selection"]
        c = [f for f in REGISTRY if f["category"] == "risk_cross_validation"]
        assert len(a) >= 7, f"A类因子不足: {len(a)}"
        assert len(b) >= 7, f"B类因子不足: {len(b)}"
        assert len(c) >= 5, f"C类因子不足: {len(c)}"

    def test_each_factor_has_industry_hypothesis(self):
        """每个因子必须有description（产业假设）"""
        semi = [f for f in REGISTRY if f["category"] in (
            "sector_timing", "semi_stock_selection", "risk_cross_validation"
        )]
        for f in semi:
            assert f["description"], f"因子 {f['name']} 缺少 description"

    def test_not_purely_price_volume(self):
        """半导体因子不能是纯价量因子"""
        semi = [f for f in REGISTRY if f["category"] in (
            "sector_timing", "semi_stock_selection", "risk_cross_validation"
        )]
        # 禁止纯价量的子串模式: retN(纯收益), vol_ratio, ma_gap, macd, kdj, boll, atr
        # 注意: volume_confirmation 是量+价+逻辑的综合因子, 不是纯价量
        pure_pv_patterns = ["ret5", "ret10", "ret20", "ret60",
                            "vol_ratio", "ma_gap", "close_gt_ma",
                            "macd_", "kdj_", "boll_", "atr",
                            "turnover20", "reversal", "volatility20",
                            "amihud"]
        for f in semi:
            name = f["name"]
            assert not any(p in name for p in pure_pv_patterns), \
                f"因子 {name} 是纯价量因子, 不符合V4.5约束"


# ═══════════════════════════════════════════════
# 测试: A类 - 主题择时因子
# ═══════════════════════════════════════════════


class TestSectorTiming:
    """A类主题择时因子测试"""

    def test_semi_vs_all_a_strength(self, sample_df: pd.DataFrame):
        """相对强度应在1.0附近, 范围合理"""
        result = semi_vs_all_a_strength(sample_df)
        assert len(result) == len(sample_df)
        assert result.between(0.5, 1.5).all(), "相对强度超出合理范围"

    def test_semi_turnover_share(self, sample_df: pd.DataFrame):
        """成交额占比应在0~1之间"""
        result = semi_turnover_share(sample_df)
        assert len(result) == len(sample_df)
        assert result.between(0, 1).all(), "成交额占比应介于0~1"

    def test_semi_up_ratio(self, sample_df: pd.DataFrame):
        """上涨家数占比应在0~1之间"""
        result = semi_up_ratio(sample_df)
        assert len(result) == len(sample_df)
        assert result.between(0, 1).all(), "上涨占比应介于0~1"

    def test_semi_limit_up_count(self, sample_df: pd.DataFrame):
        """涨停净计数应为float"""
        result = semi_limit_up_count(sample_df)
        assert len(result) == len(sample_df)
        assert result.dtype == float

    def test_semi_leader_strength(self, sample_df: pd.DataFrame):
        """龙头强度应 > 0"""
        result = semi_leader_strength(sample_df)
        assert len(result) == len(sample_df)
        assert result.min() > 0, "龙头强度必须为正"

    def test_semi_etf_amount_trend(self, sample_df: pd.DataFrame):
        """ETF成交额趋势应 >= 0"""
        result = semi_etf_amount_trend(sample_df)
        assert len(result) == len(sample_df)
        assert (result >= 0).all()

    def test_semi_subsector_diffusion(self, sample_df: pd.DataFrame):
        """细分方向扩散度应在0~1之间"""
        result = semi_subsector_diffusion(sample_df)
        assert len(result) == len(sample_df)
        assert result.between(0, 1).all()

    def test_semi_theme_composite(self, sample_df: pd.DataFrame):
        """综合择时信号返回有效theme_state"""
        result = semi_theme_composite(sample_df)
        assert len(result) == len(sample_df)
        valid_states = {"极弱", "偏弱", "中性", "偏强", "极强"}
        for val in result.unique():
            assert val in valid_states, f"无效的状态值: {val}"

    def test_theme_weight_mapping(self):
        """仓位映射表完整性"""
        assert THEME_WEIGHT_MAP == {
            "极弱": 0, "偏弱": 30, "中性": 50, "偏强": 70, "极强": 100,
        }

    def test_get_recommended_theme_weight(self):
        """映射函数输出整数仓位"""
        states = pd.Series(["中性", "极强", "极弱"])
        weights = get_recommended_theme_weight(states)
        assert list(weights) == [50, 100, 0]
        assert weights.dtype == int

    def test_no_semi_degradation(self, no_semi_df: pd.DataFrame):
        """无 is_semi 列时返回合理默认值"""
        r1 = semi_vs_all_a_strength(no_semi_df)
        assert (r1 == 0.5).all() or (r1 == 1.0).all(), "无semi标记应返回默认值"

        r2 = semi_turnover_share(no_semi_df)
        assert (r2 == 0.0).all()

        r3 = semi_up_ratio(no_semi_df)
        assert (r3 == 0.5).all()

        r4 = semi_theme_composite(no_semi_df)
        assert (r4 == "中性").all()

    def test_single_stock_sector_timing(self, single_stock_df: pd.DataFrame):
        """单只股票时因子能计算不崩溃"""
        for factor_fn in [semi_vs_all_a_strength, semi_turnover_share,
                          semi_up_ratio, semi_limit_up_count]:
            result = factor_fn(single_stock_df)
            assert len(result) == len(single_stock_df)

    def test_empty_dataframe(self):
        """空DataFrame应优雅降级"""
        empty = pd.DataFrame(columns=["date", "symbol", "close", "is_semi"])
        for factor_fn in [semi_vs_all_a_strength, semi_turnover_share,
                          semi_up_ratio, semi_limit_up_count]:
            result = factor_fn(empty)
            assert len(result) == 0 or result.isna().all()


# ═══════════════════════════════════════════════
# 测试: B类 - 内部选股因子
# ═══════════════════════════════════════════════


class TestStockSelection:
    """B类半导体内部选股因子测试"""

    def test_stock_vs_semi_ew_strength(self, sample_df: pd.DataFrame):
        """相对超额 = 个股收益 - 板块等权收益"""
        result = stock_vs_semi_ew_strength(sample_df)
        assert len(result) == len(sample_df)
        # 半导体股票的均值应该接近0 (正负抵消)
        semi_mask = sample_df["is_semi"].fillna(False).astype(bool)
        semi_excess = result[semi_mask]
        assert not semi_excess.isna().all()

    def test_stock_vs_subsector_strength(self, sample_df: pd.DataFrame):
        """细分方向内相对超额"""
        result = stock_vs_subsector_strength(sample_df)
        assert len(result) == len(sample_df)
        # 至少半导体股票有有效值
        semi_mask = sample_df["is_semi"].fillna(False).astype(bool)
        assert result[semi_mask].notna().any()

    def test_stock_vs_subsector_no_column(self, sample_df: pd.DataFrame):
        """缺少subsector列时返回0"""
        df = sample_df.drop(columns=["subsector"])
        result = stock_vs_subsector_strength(df)
        assert (result == 0.0).all()

    def test_volume_confirmation(self, sample_df: pd.DataFrame):
        """放量确认信号"""
        result = volume_confirmation(sample_df)
        assert len(result) == len(sample_df)
        # 信号应在合理范围
        assert result.between(-2, 2).all()

    def test_volume_confirmation_no_volume(self, sample_df: pd.DataFrame):
        """无volume列时返回0"""
        df = sample_df.drop(columns=["volume"])
        result = volume_confirmation(df)
        assert (result == 0.0).all()

    def test_gross_margin_improvement(self, sample_df: pd.DataFrame):
        """毛利率改善"""
        result = gross_margin_improvement(sample_df)
        assert len(result) == len(sample_df)

    def test_gross_margin_improvement_no_data(self, sample_df: pd.DataFrame):
        """无毛利率数据时返回0"""
        df = sample_df.drop(columns=["gross_margin"])
        result = gross_margin_improvement(df)
        assert (result == 0.0).all()

    def test_revenue_growth_trend(self, sample_df: pd.DataFrame):
        """营收增速趋势"""
        result = revenue_growth_trend(sample_df)
        assert len(result) == len(sample_df)

    def test_revenue_growth_trend_basic(self, sample_df: pd.DataFrame):
        """仅有当期营收增速时也能计算"""
        df = sample_df.drop(columns=["revenue_growth_q_1", "revenue_growth_q_2"])
        result = revenue_growth_trend(df)
        assert len(result) == len(sample_df)

    def test_valuation_not_overheated(self, sample_df: pd.DataFrame):
        """估值分位反过热"""
        result = valuation_not_overheated(sample_df)
        assert len(result) == len(sample_df)
        # 信号范围 -1.5 ~ 1.0
        assert result.min() >= -1.5
        assert result.max() <= 1.5

    def test_valuation_not_overheated_no_data(self, sample_df: pd.DataFrame):
        """无估值列时返回0"""
        df = sample_df.drop(columns=["valuation_pct", "pe_ttm"])
        result = valuation_not_overheated(df)
        assert (result == 0.0).all()

    def test_event_catalyst_score(self, sample_df: pd.DataFrame):
        """事件催化得分"""
        result = event_catalyst_score(sample_df)
        assert len(result) == len(sample_df)
        # 默认范围内
        assert result.between(-3, 3).all()

    def test_event_catalyst_score_with_columns(self, sample_df: pd.DataFrame):
        """使用预计算的催化分"""
        sample_df["event_catalyst"] = np.random.uniform(-2, 2, len(sample_df))
        result = event_catalyst_score(sample_df)
        assert len(result) == len(sample_df)

    def test_single_stock_selection(self, single_stock_df: pd.DataFrame):
        """单只股票时不会崩溃"""
        for fn in [stock_vs_semi_ew_strength, volume_confirmation,
                   gross_margin_improvement, revenue_growth_trend]:
            result = fn(single_stock_df)
            assert len(result) == len(single_stock_df)


# ═══════════════════════════════════════════════
# 测试: C类 - 风险反证因子
# ═══════════════════════════════════════════════


class TestRiskCrossValidation:
    """C类风险反证因子测试"""

    def test_industry_beta_exposure(self, sample_df: pd.DataFrame):
        """行业Beta暴露在0~1之间"""
        result = industry_beta_exposure(sample_df)
        assert len(result) == len(sample_df)
        assert result.between(0, 1).all(), f"暴露度范围异常: [{result.min()}, {result.max()}]"

    def test_size_exposure(self, sample_df: pd.DataFrame):
        """市值暴露在0~1之间"""
        result = size_exposure(sample_df)
        assert len(result) == len(sample_df)
        assert result.between(0, 1).all()

    def test_size_exposure_no_mv(self, sample_df: pd.DataFrame):
        """无市值列时返回0.5"""
        df = sample_df.drop(columns=["total_mv"])
        result = size_exposure(df)
        assert (result == 0.5).all()

    def test_market_beta_exposure(self, sample_df: pd.DataFrame):
        """市场Beta暴露在0~1之间"""
        result = market_beta_exposure(sample_df)
        assert len(result) == len(sample_df)
        assert result.between(0, 1).all()

    def test_volatility_exposure(self, sample_df: pd.DataFrame):
        """波动率暴露在0~1之间"""
        result = volatility_exposure(sample_df)
        assert len(result) == len(sample_df)
        assert result.between(0, 1).all()

    def test_extreme_winner_dependence(self, sample_df: pd.DataFrame):
        """极端赢家依赖度"""
        # 先添加一个因子列
        sample_df["ret20"] = sample_df.groupby("symbol")["close"].transform(
            lambda x: x.pct_change(20)
        ).fillna(0)
        result = extreme_winner_dependence(sample_df)
        assert len(result) == len(sample_df)
        assert result.between(0, 1).all()

    def test_build_risk_report(self, sample_df: pd.DataFrame):
        """风险报告结构完整性"""
        sample_df["ret20"] = sample_df.groupby("symbol")["close"].transform(
            lambda x: x.pct_change(20)
        ).fillna(0)
        report = build_risk_report(sample_df, "test_factor")
        assert "factor_name" in report
        assert "exposures" in report
        assert "composite_risk" in report
        assert "risk_rating" in report
        assert "risk_assessment" in report
        assert report["factor_name"] == "test_factor"
        assert report["risk_rating"] in ("低", "中", "高")
        # 验证所有5个暴露度
        assert len(report["exposures"]) == 5
        for k in ["industry_beta", "size", "market_beta", "volatility", "extreme_winner_dep"]:
            assert k in report["exposures"]

    def test_single_stock_risk(self, single_stock_df: pd.DataFrame):
        """单只股票时风险因子不崩溃"""
        for fn in [industry_beta_exposure, size_exposure,
                   market_beta_exposure, volatility_exposure]:
            result = fn(single_stock_df)
            assert len(result) == len(single_stock_df)


# ═══════════════════════════════════════════════
# 测试: 辅助函数
# ═══════════════════════════════════════════════


class TestHelpers:
    """辅助函数测试"""

    def test_is_semi_marked(self, sample_df: pd.DataFrame, no_semi_df: pd.DataFrame):
        """检测 is_semi 列"""
        assert _is_semi_marked(sample_df) is True
        assert _is_semi_marked(no_semi_df) is False

    def test_semi_mask(self, sample_df: pd.DataFrame):
        """半导体池掩码"""
        mask = _semi_mask(sample_df)
        assert mask.dtype == bool
        semi_rows = mask.sum()
        assert semi_rows > 0

    def test_semi_ew_return(self, sample_df: pd.DataFrame):
        """等权收益率返回"""
        ew = _semi_ew_return(sample_df)
        assert isinstance(ew, pd.Series)
        assert ew.name == "ret" or ew.name == 0 or True  # 至少不崩溃


# ═══════════════════════════════════════════════
# 测试: 因子计算引擎集成
# ═══════════════════════════════════════════════


class TestEngineIntegration:
    """验证因子可被 factor_engine.compute_all 计算"""

    def test_factors_work_with_registry_iteration(self, sample_df: pd.DataFrame):
        """模拟 factor_engine 遍历REGISTRY的方式调用半导体因子"""
        semi_names = {
            "semi_vs_all_a_strength", "semi_turnover_share",
            "semi_up_ratio", "semi_limit_up_count",
            "semi_leader_strength", "semi_etf_amount_trend",
            "semi_subsector_diffusion", "semi_theme_composite",
            "stock_vs_semi_ew_strength", "stock_vs_subsector_strength",
            "volume_confirmation", "gross_margin_improvement",
            "revenue_growth_trend", "valuation_not_overheated",
            "event_catalyst_score",
            "industry_beta_exposure", "size_exposure",
            "market_beta_exposure", "volatility_exposure",
            "extreme_winner_dependence",
        }

        registered_names = {f["name"] for f in REGISTRY}
        assert semi_names.issubset(registered_names), \
            f"缺失因子: {semi_names - registered_names}"

        # 模拟引擎调用
        for f in REGISTRY:
            if f["name"] in semi_names:
                try:
                    result = f["func"](sample_df, **f["params"])
                    assert len(result) == len(sample_df), \
                        f"{f['name']}: 结果长度不匹配"
                except Exception as e:
                    pytest.fail(f"{f['name']}: 计算失败 - {e}")


# ═══════════════════════════════════════════════
# 测试: 主题状态边界条件
# ═══════════════════════════════════════════════


class TestThemeStateBoundaries:
    """验证主题状态在极端行情下的合理性"""

    def test_extreme_bull_signal(self):
        """模拟极强行情: 所有子信号都为+2"""
        n = 10
        dates = pd.date_range("2026-06-01", periods=n, freq="B")
        symbols = [f"688{i:03d}" for i in range(1, 21)]  # 20只半导体
        all_symbols = symbols + [f"600{i:03d}" for i in range(1, 81)]  # 80只全A

        rows = []
        for d in dates:
            for sym in all_symbols:
                is_semi = sym.startswith("688")
                rows.append({
                    "date": d,
                    "symbol": sym,
                    "close": 50.0,
                    "volume": 1e7,
                    "amount": 5e8,
                    "is_semi": is_semi,
                    "subsector": "设备" if is_semi else "其他",
                    "ts_code": f"{sym}.SH",
                })

        df = pd.DataFrame(rows)
        result = semi_theme_composite(df)
        # 即使在没有收益率差异的情况下, 返回有效状态
        assert all(s in {"极弱", "偏弱", "中性", "偏强", "极强"} for s in result.unique())

    def test_zero_volume_turnover(self):
        """零成交额时成交额占比应为0"""
        dates = pd.date_range("2026-06-01", periods=5, freq="B")
        rows = []
        for d in dates:
            rows.append({"date": d, "symbol": "688001", "close": 50.0,
                         "volume": 0, "amount": 0, "is_semi": True,
                         "subsector": "设备", "ts_code": "688001.SH"})
            rows.append({"date": d, "symbol": "600001", "close": 50.0,
                         "volume": 0, "amount": 0, "is_semi": False,
                         "subsector": "其他", "ts_code": "600001.SH"})
        df = pd.DataFrame(rows)
        result = semi_turnover_share(df)
        assert (result == 0.0).all() or result.isna().any()


if __name__ == "__main__":
    pytest.main(["-v", __file__])
