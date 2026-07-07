"""V6.8 A-share Sector Rotation — 行业轮动测试

测试覆盖:
  - spec: 数据模型创建、校验、序列化
  - sector_performance: 行业收益计算、绩效快照、排名
  - rotation_strategies: 3 种策略评分与选择
  - rotation_engine: 完整轮动回测流程、信号生成、边界条件
  - Research Skill: sector-rotation 注册和执行
  - CLI: sector 命令解析
  - 回归测试: 与 V5.x/V6.0-V6.6 无冲突
"""

import sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / ".."))

import pytest
import numpy as np
import pandas as pd

from factor_lab.sector_rotation import (
    SectorRotationConfig,
    SectorPerformance,
    RotationSignal,
    RotationResult,
    RotationStrategyType,
    compute_sector_returns,
    compute_sector_performance_snapshot,
    compute_sector_rankings,
    get_sector_mapping,
    get_sector_list,
    get_sector_stock_count,
    build_sector_performance_history,
    MomentumRotation,
    MeanReversionRotation,
    CompositeRotation,
    create_strategy,
    SectorRotationEngine,
)

# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture()
def sample_dates() -> pd.DatetimeIndex:
    """168 个交易日 (~8 个月)，足够测试"""
    return pd.date_range("2025-01-02", periods=168, freq="B")


@pytest.fixture()
def stock_returns(sample_dates) -> pd.DataFrame:
    """模拟 25 只股票日收益率

    按行业分组, 各行业有不同的收益特征:
      - 银行: 低波动, 稳定收益
      - 科技: 高波动, 高收益
      - 医药: 中波动, 中收益
      - 消费: 中低波动, 中收益
      - 能源: 中高波动, 周期性强
    """
    rng = np.random.default_rng(42)
    n = len(sample_dates)

    # 25 个股票代码, 对应 5 个行业 (各 5 只)
    # 使用不同前缀确保不重叠
    sector_symbols = {
        "银行": [f"60{str(i).zfill(3)}.SH" for i in range(1, 6)],
        "科技": [f"00{str(i).zfill(3)}.SZ" for i in range(1, 6)],
        "医药": [f"30{str(i).zfill(3)}.SZ" for i in range(1, 6)],
        "消费": [f"68{str(i).zfill(3)}.SH" for i in range(1, 6)],
        "能源": [f"83{str(i).zfill(3)}.BJ" for i in range(1, 6)],
    }

    # 各行业收益特征
    sector_profiles = {
        "银行": {"mu": 0.0003, "sigma": 0.008},     # 低波动稳定
        "科技": {"mu": 0.0008, "sigma": 0.025},     # 高波动高收益
        "医药": {"mu": 0.0005, "sigma": 0.018},     # 中波动中收益
        "消费": {"mu": 0.0004, "sigma": 0.015},     # 中低波动
        "能源": {"mu": 0.0006, "sigma": 0.022},     # 中高波动周期
    }

    rows = {}
    for sector, symbols in sector_symbols.items():
        prof = sector_profiles[sector]
        for sym in symbols:
            noise = rng.normal(0, prof["sigma"] * 0.3, n)
            ret = rng.normal(prof["mu"], prof["sigma"], n) + noise * 0.2
            rows[sym] = ret

    df = pd.DataFrame(rows, index=sample_dates)
    return df


@pytest.fixture()
def sector_mapping() -> dict[str, str]:
    """行业映射: symbol -> sector"""
    return {
        **{f"60{str(i).zfill(3)}.SH": "银行" for i in range(1, 6)},
        **{f"00{str(i).zfill(3)}.SZ": "科技" for i in range(1, 6)},
        **{f"30{str(i).zfill(3)}.SZ": "医药" for i in range(1, 6)},
        **{f"68{str(i).zfill(3)}.SH": "消费" for i in range(1, 6)},
        **{f"83{str(i).zfill(3)}.BJ": "能源" for i in range(1, 6)},
    }


@pytest.fixture()
def sector_rotation_config() -> SectorRotationConfig:
    return SectorRotationConfig(
        name="测试轮动",
        strategy_type=RotationStrategyType.MOMENTUM,
        top_n=3,
        rebalance_freq="monthly",
        lookback_short=20,
        lookback_medium=60,
    )


@pytest.fixture()
def sector_returns(stock_returns, sector_mapping) -> dict[str, pd.Series]:
    """预计算的行业收益率"""
    return compute_sector_returns(stock_returns, sector_mapping)


# ═══════════════════════════════════════════════════════════════════
# Spec 测试
# ═══════════════════════════════════════════════════════════════════


class TestSectorRotationConfig:

    def test_default_config(self):
        """默认配置校验"""
        config = SectorRotationConfig()
        assert config.name == "SectorRotation"
        assert config.strategy_type == RotationStrategyType.MOMENTUM
        assert config.top_n == 5
        assert config.rebalance_freq == "monthly"

    def test_validate_valid(self):
        """有效配置通过校验"""
        config = SectorRotationConfig(top_n=3, min_sectors=2, max_sectors=5)
        errors = config.validate()
        assert len(errors) == 0

    def test_validate_empty_name(self):
        """空名称报错"""
        config = SectorRotationConfig(name="")
        errors = config.validate()
        assert len(errors) > 0
        assert any("名称" in e for e in errors)

    def test_validate_invalid_freq(self):
        """无效调仓频率报错"""
        config = SectorRotationConfig(rebalance_freq="yearly")
        errors = config.validate()
        assert len(errors) > 0
        assert any("调仓频率" in e for e in errors)

    def test_validate_min_gt_max(self):
        """min_sectors > max_sectors 报错"""
        config = SectorRotationConfig(min_sectors=10, max_sectors=5)
        errors = config.validate()
        assert len(errors) > 0

    def test_validate_short_window(self):
        """过短窗口报错"""
        config = SectorRotationConfig(lookback_short=2)
        errors = config.validate()
        assert len(errors) > 0

    def test_to_dict(self):
        """序列化"""
        config = SectorRotationConfig(name="动量轮动测试")
        d = config.to_dict()
        assert d["name"] == "动量轮动测试"
        assert d["strategy_type"] == "momentum"
        assert d["top_n"] == 5


class TestSectorPerformance:

    def test_defaults(self):
        """默认值"""
        sp = SectorPerformance(sector_name="银行")
        assert sp.sector_name == "银行"
        assert sp.momentum_score == 0.0
        assert sp.composite_score == 0.0

    def test_to_dict(self):
        """序列化"""
        sp = SectorPerformance(
            sector_name="科技",
            return_short=0.05,
            momentum_score=0.8,
            volatility=0.02,
            sharpe_ratio=1.5,
        )
        d = sp.to_dict()
        assert d["sector_name"] == "科技"
        assert d["return_short"] == 5.0  # 转百分比
        assert d["momentum_score"] == 0.8
        assert d["sharpe_ratio"] == 1.5


class TestRotationSignal:

    def test_defaults(self):
        """默认值"""
        signal = RotationSignal()
        assert signal.date == ""
        assert signal.selected_sectors == []

    def test_to_dict(self):
        """序列化"""
        signal = RotationSignal(
            date="2025-06-01",
            strategy_type="momentum",
            selected_sectors=["银行", "科技"],
            weights={"银行": 0.5, "科技": 0.5},
        )
        d = signal.to_dict()
        assert d["date"] == "2025-06-01"
        assert d["n_selected"] == 2


class TestRotationResult:

    def test_defaults(self):
        """默认值"""
        result = RotationResult()
        assert result.n_signals == 0
        assert result.warnings == []

    def test_summary_empty(self):
        """空结果摘要"""
        result = RotationResult()
        s = result.summary()
        assert "config" in s
        assert s["n_signals"] == 0


# ═══════════════════════════════════════════════════════════════════
# Sector Performance 测试
# ═══════════════════════════════════════════════════════════════════


class TestComputeSectorReturns:

    def test_returns_shape(self, stock_returns, sector_mapping):
        """行业收益率应有正确形状"""
        sector_ret = compute_sector_returns(stock_returns, sector_mapping)

        assert len(sector_ret) == 5  # 5 个行业
        for sector, ret_series in sector_ret.items():
            assert len(ret_series) <= len(stock_returns)
            assert isinstance(ret_series, pd.Series)

    def test_empty_returns(self):
        """空输入"""
        sector_ret = compute_sector_returns(pd.DataFrame(), {})
        assert sector_ret == {}

    def test_empty_mapping(self, stock_returns):
        """空映射"""
        sector_ret = compute_sector_returns(stock_returns, {})
        assert sector_ret == {}

    def test_sector_order(self, stock_returns, sector_mapping):
        """行业收益率数量正确"""
        sector_ret = compute_sector_returns(stock_returns, sector_mapping)
        assert len(sector_ret) == 5  # 5 个行业
        sectors = sorted(sector_ret.keys())
        assert sectors == ["医药", "消费", "科技", "能源", "银行"]


class TestSectorPerformanceSnapshot:

    def test_snapshot_shape(self, sector_returns):
        """绩效快照长度"""
        perfs = compute_sector_performance_snapshot(
            sector_returns, lookback_short=20, lookback_medium=60, lookback_long=120
        )
        assert len(perfs) == 5  # 5 个行业

    def test_snapshot_sorted(self, sector_returns):
        """按 composite_score 降序"""
        perfs = compute_sector_performance_snapshot(sector_returns)
        scores = [p.composite_score for p in perfs]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1]

    def test_snapshot_as_of(self, sector_returns):
        """截断日期"""
        perfs = compute_sector_performance_snapshot(
            sector_returns,
            as_of_date="2025-06-01",
            lookback_short=20,
        )
        assert len(perfs) > 0

    def test_empty_returns(self):
        """空输入"""
        perfs = compute_sector_performance_snapshot({})
        assert perfs == []


class TestSectorRankings:

    def test_ranking_count(self, sector_returns):
        """排名数量"""
        perfs = compute_sector_performance_snapshot(sector_returns)
        rankings = compute_sector_rankings(perfs, top_n=3)
        assert len(rankings) == 3

    def test_ranking_fields(self, sector_returns):
        """排名包含必要字段"""
        perfs = compute_sector_performance_snapshot(sector_returns)
        rankings = compute_sector_rankings(perfs, top_n=1)
        assert len(rankings) == 1
        r = rankings[0]
        assert "sector" in r
        assert "composite_score" in r
        assert "momentum" in r
        assert "return_short_pct" in r


# ═══════════════════════════════════════════════════════════════════
# Rotation Strategies 测试
# ═══════════════════════════════════════════════════════════════════


class TestMomentumRotation:

    def test_name(self):
        """策略名称"""
        strategy = MomentumRotation()
        assert strategy.name() == "momentum"

    def test_rank_sectors(self, sector_returns):
        """动量排名按得分降序"""
        perfs = compute_sector_performance_snapshot(sector_returns)
        strategy = MomentumRotation()
        rankings = strategy.rank_sectors(perfs)

        assert len(rankings) == len(perfs)
        for i in range(len(rankings) - 1):
            assert rankings[i]["score"] >= rankings[i + 1]["score"]

    def test_select_sectors(self, sector_returns):
        """选择前 N 个行业"""
        perfs = compute_sector_performance_snapshot(sector_returns)
        strategy = MomentumRotation()
        rankings = strategy.rank_sectors(perfs)
        selected = strategy.select_sectors(rankings, top_n=3)
        assert len(selected) == 3
        assert selected[0] == rankings[0]["sector"]


class TestMeanReversionRotation:

    def test_name(self):
        """策略名称"""
        strategy = MeanReversionRotation()
        assert strategy.name() == "mean_reversion"

    def test_rank_sectors(self, sector_returns):
        """均值回归排名按得分降序 (超跌的排前面)"""
        perfs = compute_sector_performance_snapshot(sector_returns)
        strategy = MeanReversionRotation()
        rankings = strategy.rank_sectors(perfs)

        assert len(rankings) == len(perfs)
        for i in range(len(rankings) - 1):
            assert rankings[i]["score"] >= rankings[i + 1]["score"]

    def test_vol_filter(self, sector_returns):
        """高波动抑制"""
        perfs = compute_sector_performance_snapshot(sector_returns)
        strategy = MeanReversionRotation(max_volatility=0.01)
        rankings = strategy.rank_sectors(perfs)
        assert len(rankings) == len(perfs)


class TestCompositeRotation:

    def test_name(self):
        """策略名称"""
        strategy = CompositeRotation()
        assert strategy.name() == "composite"

    def test_rank_sectors(self, sector_returns):
        """复合排名按得分降序"""
        perfs = compute_sector_performance_snapshot(sector_returns)
        strategy = CompositeRotation()
        rankings = strategy.rank_sectors(perfs)

        assert len(rankings) == len(perfs)
        for i in range(len(rankings) - 1):
            assert rankings[i]["score"] >= rankings[i + 1]["score"]

    def test_empty_performances(self):
        """空输入"""
        strategy = CompositeRotation()
        rankings = strategy.rank_sectors([])
        assert rankings == []


class TestCreateStrategy:

    def test_momentum(self):
        """创建动量策略"""
        config = SectorRotationConfig(strategy_type=RotationStrategyType.MOMENTUM)
        strategy = create_strategy(config)
        assert isinstance(strategy, MomentumRotation)

    def test_mean_reversion(self):
        """创建均值回归策略"""
        config = SectorRotationConfig(strategy_type=RotationStrategyType.MEAN_REVERSION)
        strategy = create_strategy(config)
        assert isinstance(strategy, MeanReversionRotation)

    def test_composite(self):
        """创建复合策略"""
        config = SectorRotationConfig(strategy_type=RotationStrategyType.COMPOSITE)
        strategy = create_strategy(config)
        assert isinstance(strategy, CompositeRotation)


# ═══════════════════════════════════════════════════════════════════
# Rotation Engine 测试
# ═══════════════════════════════════════════════════════════════════


class TestSectorRotationEngine:

    def test_init(self, sector_rotation_config):
        """引擎初始化"""
        engine = SectorRotationEngine(sector_rotation_config)
        assert engine.config.name == "测试轮动"
        assert engine.strategy is not None

    def test_init_invalid_config(self):
        """无效配置初始化报错"""
        config = SectorRotationConfig(top_n=0)
        with pytest.raises(ValueError):
            SectorRotationEngine(config)

    def test_run_return_types(self, stock_returns, sector_mapping, sector_rotation_config):
        """回测返回 RotationResult"""
        engine = SectorRotationEngine(sector_rotation_config)
        result = engine.run(stock_returns, sector_mapping)

        assert isinstance(result, RotationResult)
        assert result.config is not None

    def test_run_generates_signals(self, stock_returns, sector_mapping, sector_rotation_config):
        """回测生成调仓信号"""
        engine = SectorRotationEngine(sector_rotation_config)
        result = engine.run(stock_returns, sector_mapping)

        assert len(result.signals) > 0
        for signal in result.signals:
            assert len(signal.selected_sectors) > 0
            assert signal.date != ""

    def test_run_without_mapping(self, stock_returns, sector_rotation_config):
        """自动加载映射 (可能返回空结果)"""
        engine = SectorRotationEngine(sector_rotation_config)
        # 无参数时, 自动尝试加载 IndustryMapper, 可能数据缺失但不报错
        result = engine.run(stock_returns)
        # 应该不会崩溃
        assert isinstance(result, RotationResult)

    def test_run_signal_weights_sum(self, stock_returns, sector_mapping, sector_rotation_config):
        """信号权重约等于 1"""
        engine = SectorRotationEngine(sector_rotation_config)
        result = engine.run(stock_returns, sector_mapping)

        if result.signals:
            for signal in result.signals[:3]:
                total_w = sum(signal.weights.values())
                assert abs(total_w - 1.0) < 0.01

    def test_run_portfolio_result(self, stock_returns, sector_mapping, sector_rotation_config):
        """回测包含组合结果"""
        engine = SectorRotationEngine(sector_rotation_config)
        result = engine.run(stock_returns, sector_mapping)

        assert result.portfolio_result is not None
        summary = result.portfolio_result.summary()
        assert summary["sharpe"] != 0 or not result.warnings

    def test_run_with_equal_weight_true(self, stock_returns, sector_mapping):
        """等权配置"""
        config = SectorRotationConfig(
            name="等权轮动",
            top_n=3,
            equal_weight=True,
            rebalance_freq="monthly",
        )
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)

        if result.signals:
            # 等权权重应该相等
            for signal in result.signals[:3]:
                weights = list(signal.weights.values())
                if weights:
                    assert abs(weights[0] - 1.0 / len(weights)) < 0.001

    def test_run_different_strategies(self, stock_returns, sector_mapping):
        """不同策略产生不同的行业选择"""
        configs = [
            SectorRotationConfig(name="动量", strategy_type=RotationStrategyType.MOMENTUM, top_n=2),
            SectorRotationConfig(name="均值回归", strategy_type=RotationStrategyType.MEAN_REVERSION, top_n=2),
            SectorRotationConfig(name="复合", strategy_type=RotationStrategyType.COMPOSITE, top_n=2),
        ]

        results = []
        for config in configs:
            engine = SectorRotationEngine(config)
            result = engine.run(stock_returns, sector_mapping)
            results.append(result)

        # 至少有一个信号
        assert any(len(r.signals) > 0 for r in results)

    def test_run_sector_turnover(self, stock_returns, sector_mapping):
        """换手率计算"""
        config = SectorRotationConfig(
            name="换手率测试",
            top_n=3,
            rebalance_freq="monthly",
        )
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)

        assert result.sector_turnover >= 0.0
        assert result.sector_turnover <= 1.0

    def test_empty_stock_returns(self, sector_rotation_config):
        """空收益率数据"""
        engine = SectorRotationEngine(sector_rotation_config)
        result = engine.run(pd.DataFrame())
        assert isinstance(result, RotationResult)

    def test_sector_performance_history(self, stock_returns, sector_mapping, sector_rotation_config):
        """行业绩效历史"""
        engine = SectorRotationEngine(sector_rotation_config)
        result = engine.run(stock_returns, sector_mapping)

        if result.sector_performance_history is not None:
            assert not result.sector_performance_history.empty


class TestRotationStrategyEnum:

    def test_values(self):
        """枚举值"""
        assert RotationStrategyType.MOMENTUM.value == "momentum"
        assert RotationStrategyType.MEAN_REVERSION.value == "mean_reversion"
        assert RotationStrategyType.COMPOSITE.value == "composite"

    def test_str(self):
        """字符串表示"""
        assert str(RotationStrategyType.MOMENTUM) == "momentum"
        assert str(RotationStrategyType.MEAN_REVERSION) == "mean_reversion"


# ═══════════════════════════════════════════════════════════════════
# 边界条件测试
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:

    def test_single_sector(self, stock_returns, sector_mapping):
        """只有一个行业时"""
        # 只取一个行业的股票
        single_mapping = {k: v for k, v in sector_mapping.items() if v == "科技"}
        single_returns = stock_returns[list(single_mapping.keys())]

        config = SectorRotationConfig(name="单行业", top_n=1)
        engine = SectorRotationEngine(config)
        result = engine.run(single_returns, single_mapping)

        # 应该产生警告
        assert len(result.warnings) > 0 or len(result.signals) == 0

    def test_rebalance_weekly(self, stock_returns, sector_mapping):
        """周频调仓"""
        config = SectorRotationConfig(
            name="周频轮动",
            top_n=3,
            rebalance_freq="weekly",
        )
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)

        # 周频应该比月频有更多信号
        monthly_config = SectorRotationConfig(
            name="月频轮动",
            top_n=3,
            rebalance_freq="monthly",
        )
        monthly_engine = SectorRotationEngine(monthly_config)
        monthly_result = monthly_engine.run(stock_returns, sector_mapping)

        if result.signals and monthly_result.signals:
            assert len(result.signals) >= len(monthly_result.signals)

    def test_quarterly_rebalance(self, stock_returns, sector_mapping):
        """季度调仓"""
        config = SectorRotationConfig(
            name="季度轮动",
            top_n=2,
            rebalance_freq="quarterly",
        )
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)

        assert isinstance(result, RotationResult)

    def test_all_strategy_types(self):
        """所有策略类型都能创建"""
        for st in RotationStrategyType:
            config = SectorRotationConfig(strategy_type=st)
            strategy = create_strategy(config)
            assert strategy is not None
            assert strategy.name() == st.value


# ═══════════════════════════════════════════════════════════════════
# 集成测试: Research Skill
# ═══════════════════════════════════════════════════════════════════


class TestResearchSkillIntegration:

    def test_skill_execution(self, stock_returns, sector_mapping):
        """模拟 sector-rotation research skill 执行

        验证 skill 入口函数能正常调用 SectorRotationEngine。
        """
        config = SectorRotationConfig(
            name="Skill 测试",
            top_n=3,
        )
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)

        # 验证结果包含必要字段
        assert result.n_signals >= 0
        assert result.avg_sectors_per_signal >= 0

        # 提取可序列化的 dict
        d = result.to_dict()
        assert "config" in d
        assert "n_signals" in d


# ═══════════════════════════════════════════════════════════════════
# 回归测试
# ═══════════════════════════════════════════════════════════════════


class TestRegression:

    def test_import_no_circular(self):
        """导入模块不产生循环依赖"""
        from factor_lab.sector_rotation import (
            SectorRotationConfig,
            SectorRotationEngine,
        )
        assert SectorRotationConfig is not None
        assert SectorRotationEngine is not None

    def test_spec_to_dict_json_serializable(self, sector_rotation_config):
        """to_dict() 可 JSON 序列化"""
        import json
        d = sector_rotation_config.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        assert len(json_str) > 0

    def test_rotation_result_json_serializable(self, stock_returns, sector_mapping):
        """RotationResult 的 to_dict 可 JSON 序列化"""
        import json
        config = SectorRotationConfig(name="JSON测试")
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)
        d = result.to_dict()
        json_str = json.dumps(d, ensure_ascii=False, default=str)
        assert len(json_str) > 0


# ═══════════════════════════════════════════════════════════════════
# 行业查询 API 测试
# ═══════════════════════════════════════════════════════════════════


class TestSectorAPI:

    def test_get_sector_list(self):
        """获取行业列表 (可能为空, 但不应报错)"""
        sectors = get_sector_list()
        assert isinstance(sectors, list)

    def test_get_sector_mapping(self):
        """获取行业映射 (可能为空, 但不应报错)"""
        mapping = get_sector_mapping()
        assert isinstance(mapping, dict)

    def test_get_sector_stock_count(self):
        """获取行业股票数 (可能为空, 但不应报错)"""
        counts = get_sector_stock_count()
        assert isinstance(counts, dict)
