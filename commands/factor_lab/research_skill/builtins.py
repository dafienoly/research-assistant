"""Research Skill Built-ins — 内置投研 Skills

Built-in research skills that demonstrate the Research Skill Runtime capability.
Each skill is a self-contained analysis function registered in the SkillRegistry.

Built-in Skills:
  1. data-quality: 数据质量检查 — 检查各数据源的新鲜度与健康状态
  2. factor-ranking: 因子排名分析 — 按 IC/ICIR 排名因子表现
  3. universe-overview: 股票池概览 — 统计当前股票池信息
  4. market-snapshot: 市场快照 — 当前市场概况
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from factor_lab.research_skill.skill_spec import (
    SkillSpec,
    SkillParam,
    SkillCategory,
    SkillStatus,
)

CST = timezone(timedelta(hours=8))


# ─── Skill 1: Data Quality Check ───────────────────────────────────


def _execute_data_quality(ctx, params: dict) -> dict:
    """检查数据源健康状态和新鲜度"""
    results = {}

    # 检查 fetch_log 新鲜度
    try:
        log_path = Path("/home/ly/.hermes/research-assistant/data/audit/fetch_log.jsonl")
        if log_path.exists():
            lines = log_path.read_text().splitlines()
            results["fetch_log_count"] = len(lines)
            if lines:
                import json
                last = json.loads(lines[-1])
                results["last_fetch"] = last.get("timestamp", "unknown")
        else:
            results["fetch_log"] = "not_found"
    except Exception as e:
        results["fetch_log"] = {"error": str(e)}

    # 检查数据源注册表
    try:
        from factor_lab.data_source.registry import DataRegistry
        registry = DataRegistry()
        sources = registry.list_sources()
        results["sources"] = {
            "count": len(sources),
            "by_status": _count_by_key(sources, "status"),
            "by_category": _count_by_key(sources, "category"),
        }
    except Exception as e:
        results["sources"] = {"error": str(e)}

    return results


def _count_by_key(items: list[dict], key: str) -> dict:
    counts = {}
    for item in items:
        val = item.get(key, "unknown")
        counts[val] = counts.get(val, 0) + 1
    return dict(sorted(counts.items()))


DATA_QUALITY_SKILL = SkillSpec(
    skill_id="data-quality",
    name="数据质量检查",
    description="检查各数据源的健康状态、新鲜度和注册表信息",
    category=SkillCategory.DATA.value,
    params=[
        SkillParam(name="source_id", type="string", label="数据源ID",
                   required=False, description="可选，只检查指定数据源"),
    ],
    tags=["data", "quality", "freshness", "health"],
    execute=_execute_data_quality,
    handler="factor_lab.research_skill.builtins:_execute_data_quality",
    version="1.0.0",
)


# ─── Skill 2: Factor Ranking ───────────────────────────────────────


def _execute_factor_ranking(ctx, params: dict) -> dict:
    """按 IC/ICIR 排名因子表现"""
    try:
        from factor_lab.factor_base import list_factors
        factors = list_factors()
    except Exception:
        factors = []

    factor_list = []
    for f in factors:
        factor_list.append({
            "name": f.get("name", "?"),
            "category": f.get("category", "uncategorized"),
            "subcategory": f.get("subcategory", ""),
            "description": f.get("description", ""),
        })

    # 按分类统计
    by_category = _count_by_key(factor_list, "category")

    return {
        "total_factors": len(factor_list),
        "by_category": by_category,
        "factors": factor_list[:params.get("top_n", 50)],
        "note": "完整 IC/ICIR 分析需要回测数据，此处只列出注册表中的因子信息",
    }


FACTOR_RANKING_SKILL = SkillSpec(
    skill_id="factor-ranking",
    name="因子排名",
    description="列出所有注册因子，按分类统计，展示因子基本信息",
    category=SkillCategory.ANALYSIS.value,
    params=[
        SkillParam(name="top_n", type="int", label="展示数量",
                   default=50, required=False, description="返回前 N 个因子"),
        SkillParam(name="category", type="string", label="分类筛选",
                   required=False, description="可选，只返回指定分类的因子",
                   choices=["momentum", "volatility", "quality", "value",
                            "growth", "liquidity", "sentiment", "others"]),
    ],
    tags=["factor", "analysis", "ranking"],
    execute=_execute_factor_ranking,
    handler="factor_lab.research_skill.builtins:_execute_factor_ranking",
    version="1.0.0",
)


# ─── Skill 3: Universe Overview ────────────────────────────────────


def _execute_universe_overview(ctx, params: dict) -> dict:
    """构建并展示股票池信息"""
    results = {}

    # 尝试从 universe 加载
    try:
        from strategy_lab.universe import build
        universe_names = params.get("universes", ["manual_watchlist", "today_candidates"])
        if isinstance(universe_names, str):
            universe_names = [universe_names]

        all_symbols = {}
        for u_name in universe_names:
            try:
                stocks, meta = build(u_name)
                symbols = [s["symbol"] for s in stocks]
                all_symbols[u_name] = {
                    "count": len(symbols),
                    "symbols": symbols[:20],  # 只展示前 20 个
                    "meta": meta,
                }
            except Exception as e:
                all_symbols[u_name] = {"error": str(e)}

        results["universes"] = all_symbols
        total = sum(v.get("count", 0) for v in all_symbols.values() if "count" in v)
        results["total_unique"] = total

    except Exception as e:
        results["universes"] = {"error": str(e)}

    return results


UNIVERSE_OVERVIEW_SKILL = SkillSpec(
    skill_id="universe-overview",
    name="股票池概览",
    description="构建并显示各股票池的统计信息（数量、样本）",
    category=SkillCategory.UNIVERSE.value,
    params=[
        SkillParam(name="universes", type="list", label="股票池列表",
                   default="manual_watchlist,today_candidates",
                   required=False,
                   description="股票池名称，多个用逗号分隔"),
    ],
    tags=["universe", "stock-pool", "overview"],
    execute=_execute_universe_overview,
    handler="factor_lab.research_skill.builtins:_execute_universe_overview",
    version="1.0.0",
)


# ─── Skill 4: Market Snapshot ──────────────────────────────────────


def _execute_market_snapshot(ctx, params: dict) -> dict:
    """当前市场概况快照"""
    results = {
        "timestamp": datetime.now(CST).isoformat(),
        "note": "市场快照 — 基础信息概览",
    }

    # 尝试获取数据源状态
    try:
        from factor_lab.data_source.health import HealthTracker
        tracker = HealthTracker()
        summary = tracker.auto_update_status()
        results["data_sources"] = {
            "status": summary or "checked",
        }
    except Exception as e:
        results["data_sources"] = {"error": str(e)}

    # 获取已注册因子数量
    try:
        from factor_lab.factor_base import list_factors
        factors = list_factors()
        results["factors"] = {"registered": len(factors)}
    except Exception as e:
        results["factors"] = {"error": str(e)}

    # 获取 Alpha 注册数
    try:
        from factor_lab.alpha.registry import list_alpha
        alphas = list_alpha()
        results["alphas"] = {"registered": len(alphas)}
    except Exception as e:
        results["alphas"] = {"error": str(e)}

    # 获取工具与模块检查
    try:
        from factor_lab.leader.planner import inspect_system
        inspection = inspect_system()
        s = inspection.get("summary", {})
        results["system"] = {
            "modules": s.get("modules", 0),
            "cli_handlers": s.get("cli_handlers", 0),
            "test_files": s.get("test_files", 0),
            "stage": inspection.get("stage", {}).get("current", "unknown"),
        }
    except Exception as e:
        results["system"] = {"error": str(e)}

    return results


MARKET_SNAPSHOT_SKILL = SkillSpec(
    skill_id="market-snapshot",
    name="市场快照",
    description="当前系统状态概览：数据源健康度、因子数量、Alpha 注册数、模块统计",
    category=SkillCategory.MONITOR.value,
    params=[
        SkillParam(name="detail", type="bool", label="详细模式",
                   default=False, required=False,
                   description="是否输出详细信息"),
    ],
    tags=["market", "snapshot", "monitor", "overview"],
    execute=_execute_market_snapshot,
    handler="factor_lab.research_skill.builtins:_execute_market_snapshot",
    version="1.0.0",
)


# ─── Skill 5: Strategy Report ────────────────────────────────────


def _execute_strategy_report(ctx, params: dict) -> dict:
    """策略报告生成

    从 PortfolioResult (JSON 文件) 或收益率序列生成策略报告。
    使用 V6.5 Strategy Report Generator 生成 HTML 报告。

    参数:
      - source: 'portfolio_result' (来自 JSON 文件) 或 'demo' (演示数据)
      - portfolio_result_path: PortfolioResult JSON 文件路径 (source=portfolio_result 时必填)
      - output_dir: 输出目录 (默认: HERMES_REPORTS_DIR/strategies)
      - report_title: 报告标题
      - include_sections: 包含板块 (逗号分隔, 默认全部)
      - benchmark_name: 基准名称 (默认 CSI300)
    """
    results = {}

    source = params.get("source", "demo")

    if source == "portfolio_result":
        result_path = params.get("portfolio_result_path", "")
        if not result_path:
            return {"error": "portfolio_result_path 参数必填 (source=portfolio_result 时)"}
        try:
            path = Path(result_path)
            if not path.exists():
                return {"error": f"文件不存在: {result_path}"}
            import json as _json
            data = _json.loads(path.read_text())
            # 尝试重建 PortfolioResult (需要 Portfolio 模块)
            results["loaded"] = True
            results["source_file"] = result_path
            results["note"] = "数据已加载, 需要 V6.4 PortfolioResult 重建"
        except Exception as e:
            return {"error": f"加载失败: {e}"}

    # 使用演示数据生成报告 (适用于自动测试)
    report_title = params.get("report_title", "策略报告 (演示)")
    output_dir = params.get("output_dir", "")
    sections_str = params.get("include_sections", "")
    benchmark_name = params.get("benchmark_name", "CSI300")

    try:
        # 生成演示收益率数据
        import numpy as np
        rng = np.random.default_rng(42)
        dates = pd.date_range("2024-01-02", periods=504, freq="B")  # ~2 years
        n = len(dates)

        # 模拟策略 (年化 15%, Sharpe 1.0)
        demo_ret = pd.Series(
            rng.normal(0.15 / 252, 0.15 / np.sqrt(252), n),
            index=dates,
        )

        # 模拟基准 (年化 8%)
        bm_ret = pd.Series(
            rng.normal(0.08 / 252, 0.18 / np.sqrt(252), n),
            index=dates,
        )

        # 使用 StrategyReportGenerator
        from factor_lab.strategy_report import StrategyReportGenerator, StrategyReportConfig
        gen = StrategyReportGenerator()

        config = StrategyReportConfig(
            title=report_title,
            benchmark_name=benchmark_name,
        )

        if sections_str:
            config.include_sections = [
                s.strip() for s in sections_str.split(",") if s.strip()
            ]

        if output_dir:
            config.output_dir = output_dir

        # 生成报告
        report = gen.from_strategy_returns(
            strategy_returns=demo_ret,
            strategy_name=report_title,
            benchmark_returns=bm_ret,
            benchmark_name=benchmark_name,
        )

        results["status"] = "completed"
        results["output_path"] = report.output_path
        results["title"] = report.title
        results["sections"] = report.sections_generated
        results["n_days"] = report.n_days
        results["duration_ms"] = report.duration_ms
        results["n_warnings"] = len(report.warnings)

        if report.warnings:
            results["warnings"] = report.warnings

    except ImportError as e:
        results["status"] = "partial"
        results["error"] = f"StrategyReportGenerator 不可用: {e}"
        results["note"] = "V6.5 模块可能未完全安装"
    except Exception as e:
        results["status"] = "failed"
        results["error"] = f"{type(e).__name__}: {e}"

    return results


STRATEGY_REPORT_SKILL = SkillSpec(
    skill_id="strategy-report",
    name="策略报告生成",
    description="生成策略/组合的 HTML 分析报告，包含收益指标、回撤分析、月度收益、风险指标、盈亏分析等板块",
    category=SkillCategory.REPORT.value,
    params=[
        SkillParam(name="source", type="string", label="数据来源",
                   default="demo", required=False,
                   description="数据来源: demo (演示数据) / portfolio_result (从 JSON 结果文件)",
                   choices=["demo", "portfolio_result"]),
        SkillParam(name="portfolio_result_path", type="string", label="PortfolioResult 文件路径",
                   required=False,
                   description="PortfolioResult JSON 文件路径 (source=portfolio_result 时必填)"),
        SkillParam(name="report_title", type="string", label="报告标题",
                   default="策略分析报告", required=False,
                   description="报告标题"),
        SkillParam(name="benchmark_name", type="string", label="基准名称",
                   default="CSI300", required=False,
                   description="基准指数名称",
                   choices=["CSI300", "CSI500", "CSI1000", "CSI_ALL", "custom"]),
        SkillParam(name="include_sections", type="string", label="包含板块",
                   required=False,
                   description="逗号分隔的板块列表, 默认全部"),
        SkillParam(name="output_dir", type="string", label="输出目录",
                   required=False,
                   description="报告输出目录, 默认环境变量 HERMES_REPORTS_DIR"),
    ],
    tags=["report", "strategy", "html", "analysis"],
    execute=_execute_strategy_report,
    handler="factor_lab.research_skill.builtins:_execute_strategy_report",
    version="1.0.0",
)


# ─── Skill 6: Factor Mining ────────────────────────────────────


def _execute_factor_mining(ctx, params: dict) -> dict:
    """因子挖掘 — 自动发现新因子候选

    使用 Factor Mining Agent (V6.6) 自动发现、评估新的因子候选。
    支持窗口变体、横截面、组合三种生成策略。

    参数:
      - top_n: 返回 Top-N 候选 (默认 10)
      - include_window: 是否包含窗口变体 (默认 True)
      - include_cross_sectional: 是否包含横截面变体 (默认 True)
      - include_combinations: 是否包含组合变体 (默认 True)
      - generate_demo: 无真实数据时是否生成演示数据 (默认 True)
    """
    results = {}
    top_n = params.get("top_n", 10)

    results["config"] = {
        "top_n": top_n,
        "include_window": params.get("include_window", True),
        "include_cross_sectional": params.get("include_cross_sectional", True),
        "include_combinations": params.get("include_combinations", True),
        "generate_demo": params.get("generate_demo", True),
    }

    try:
        from factor_lab.factor_mining import FactorMiningEngine

        # 尝试加载真实数据或生成演示数据
        df = None
        try:
            from factor_lab.factor_base import list_factors
            registry = list_factors()
            results["existing_factors"] = len(registry)

            # 如果注册表不为空，尝试加载数据
            if registry and params.get("generate_demo", True):
                # 生成演示数据用于评估
                pass  # fall through to demo data generation
        except Exception:
            registry = []
            results["existing_factors"] = 0

        # 生成演示 K 线数据 (用于 IC 计算)
        if params.get("generate_demo", True):
            import numpy as np
            rng = np.random.default_rng(42)
            dates = pd.date_range("2025-01-02", periods=252, freq="B")
            symbols = [f"{i:06d}.SZ" for i in range(1, 101)]

            rows = []
            for sym in symbols:
                price = 50.0 + rng.random() * 100
                for d in dates:
                    ret = rng.normal(0, 0.025)
                    price *= (1 + ret)
                    rows.append({
                        "date": d, "symbol": sym,
                        "open": price * (1 + rng.normal(0, 0.005)),
                        "high": price * (1 + abs(rng.normal(0, 0.01))),
                        "low": price * (1 - abs(rng.normal(0, 0.01))),
                        "close": price,
                        "volume": max(1, int(rng.exponential(5e6))),
                    })
            df = pd.DataFrame(rows)

            # 计算 ret1
            df["ret1"] = df.groupby("symbol")["close"].transform(
                lambda x: x.pct_change(-1)
            )
            results["data_info"] = {
                "n_symbols": len(symbols),
                "n_dates": len(dates),
                "n_rows": len(df),
                "source": "demo",
            }

        if df is None or df.empty:
            return {"error": "无可用数据", "data_info": results.get("data_info", {})}

        # 运行挖掘引擎
        engine = FactorMiningEngine(registry=registry)
        report = engine.mine(df)

        results["report"] = {
            "timestamp": report.timestamp,
            "existing_factor_count": report.existing_factor_count,
            "candidates_generated": report.candidates_generated,
            "candidates_evaluated": report.candidates_evaluated,
            "duration_ms": report.duration_ms,
            "registry_summary": report.registry_summary,
            "candidate_summary": report.candidate_summary,
        }
        results["top_candidates"] = report.top_candidates
        results["status"] = "completed"

    except ImportError as e:
        results["status"] = "partial"
        results["error"] = f"FactorMiningEngine 不可用: {e}"
    except Exception as e:
        results["status"] = "failed"
        results["error"] = f"{type(e).__name__}: {e}"

    return results


FACTOR_MINING_SKILL = SkillSpec(
    skill_id="factor-mining",
    name="因子挖掘",
    description="自动发现并评估新因子候选：窗口变体、横截面排名/Z-Score、因子组合",
    category=SkillCategory.ANALYSIS.value,
    params=[
        SkillParam(name="top_n", type="int", label="返回数量",
                   default=10, required=False,
                   description="返回 Top-N 候选"),
        SkillParam(name="include_window", type="bool", label="包含窗口变体",
                   default=True, required=False,
                   description="是否生成不同窗口参数的因子变体"),
        SkillParam(name="include_cross_sectional", type="bool", label="包含横截面变体",
                   default=True, required=False,
                   description="是否生成排名/Z-Score 横截面变体"),
        SkillParam(name="include_combinations", type="bool", label="包含组合变体",
                   default=True, required=False,
                   description="是否生成因子组合变体"),
        SkillParam(name="generate_demo", type="bool", label="生成演示数据",
                   default=True, required=False,
                   description="无真实数据时是否生成演示 K 线"),
    ],
    tags=["factor", "mining", "discovery", "analysis"],
    execute=_execute_factor_mining,
    handler="factor_lab.research_skill.builtins:_execute_factor_mining",
    version="1.0.0",
)


# ─── Skill 7: Sector Rotation (V6.8) ────────────────────────────


def _execute_sector_rotation(ctx, params: dict) -> dict:
    """行业轮动分析

    使用 V6.8 Sector Rotation Engine 进行行业评分、排名和轮动回测。

    参数:
      - strategy: 轮动策略类型 momentum/mean_reversion/composite (默认 momentum)
      - top_n: 持有行业数量 (默认 5)
      - rebalance_freq: 调仓频率 weekly/monthly/quarterly (默认 monthly)
      - lookback: 动量回看窗口天数 (默认 60)
      - benchmark: 基准名称 (默认 CSI300)
      - generate_demo: 无真实数据时生成演示数据 (默认 True)
    """
    results = {}

    strategy_name = params.get("strategy", "momentum")
    top_n = int(params.get("top_n", 5))
    freq = params.get("rebalance_freq", "monthly")
    lookback = int(params.get("lookback", 60))
    benchmark = params.get("benchmark", "CSI300")
    generate_demo = params.get("generate_demo", True)

    results["config"] = {
        "strategy": strategy_name,
        "top_n": top_n,
        "rebalance_freq": freq,
        "lookback": lookback,
        "benchmark": benchmark,
    }

    try:
        from factor_lab.sector_rotation import (
            SectorRotationConfig,
            SectorRotationEngine,
            RotationStrategyType,
        )

        # 映射策略类型
        try:
            st = RotationStrategyType(strategy_name)
        except ValueError:
            return {"error": f"不支持的策略类型 '{strategy_name}', "
                            f"可选: momentum / mean_reversion / composite"}

        config = SectorRotationConfig(
            name=f"sector_rotation_{strategy_name}",
            strategy_type=st,
            top_n=top_n,
            rebalance_freq=freq,
            lookback_short=min(lookback, 20),
            lookback_medium=lookback,
            lookback_long=min(lookback * 2, 120),
            benchmark_name=benchmark,
        )

        # 生成演示数据
        if generate_demo:
            import numpy as np
            rng = np.random.default_rng(42)
            dates = pd.date_range("2024-01-02", periods=504, freq="B")
            n = len(dates)

            sector_symbols = {
                "银行": [f"60{i}.SH" for i in range(1, 6)],
                "科技": [f"00{i}.SZ" for i in range(11, 16)],
                "医药": [f"30{i}.SZ" for i in range(21, 26)],
                "消费": [f"00{i}.SZ" for i in range(31, 36)],
                "能源": [f"60{i}.SH" for i in range(41, 46)],
            }
            sector_mapping = {}
            for sector, syms in sector_symbols.items():
                for sym in syms:
                    sector_mapping[sym] = sector

            symbol_list = [s for syms in sector_symbols.values() for s in syms]
            rows = {s: rng.normal(0.0005, 0.018, n) for s in symbol_list}
            stock_returns = pd.DataFrame(rows, index=dates)
        else:
            stock_returns = pd.DataFrame()
            sector_mapping = {}

        if stock_returns.empty:
            return {"error": "无可用数据", "config": results["config"]}

        # 运行引擎
        engine = SectorRotationEngine(config)
        result = engine.run(stock_returns, sector_mapping)

        results["status"] = "completed"
        results["n_signals"] = result.n_signals
        results["avg_sectors_per_signal"] = round(result.avg_sectors_per_signal, 2)
        results["sector_turnover"] = round(result.sector_turnover, 4)

        if result.signals:
            results["last_signal"] = result.signals[-1].to_dict()
            results["recent_rankings"] = result.signals[-1].rankings[:10]

        if result.portfolio_result is not None:
            try:
                s = result.portfolio_result.summary()
                results["performance"] = {
                    "cumulative_return_pct": round(s["cumulative_return_pct"], 2),
                    "annualized_return_pct": round(s["annualized_return_pct"], 2),
                    "sharpe": round(s["sharpe"], 2),
                    "max_drawdown_pct": round(s["max_drawdown_pct"], 2),
                    "benchmark_return_pct": round(s["benchmark_return_pct"], 2),
                    "information_ratio": round(s["information_ratio"], 2),
                    "alpha": round(s["alpha"], 4),
                    "beta": round(s["beta"], 4),
                }
            except Exception:
                pass

        if result.warnings:
            results["warnings"] = result.warnings[:5]

    except ImportError as e:
        results["status"] = "partial"
        results["error"] = f"SectorRotationEngine 不可用: {e}"
    except Exception as e:
        results["status"] = "failed"
        results["error"] = f"{type(e).__name__}: {e}"

    return results


SECTOR_ROTATION_SKILL = SkillSpec(
    skill_id="sector-rotation",
    name="行业轮动分析",
    description="行业轮动回测与分析：动量轮动/均值回归/复合策略，基于 V6.8 Sector Rotation Engine",
    category=SkillCategory.ANALYSIS.value,
    params=[
        SkillParam(name="strategy", type="string", label="轮动策略",
                   default="momentum", required=False,
                   description="策略类型: momentum (动量) / mean_reversion (均值回归) / composite (复合)",
                   choices=["momentum", "mean_reversion", "composite"]),
        SkillParam(name="top_n", type="int", label="Top-N 行业数",
                   default=5, required=False,
                   description="每次调仓持有的行业数量"),
        SkillParam(name="rebalance_freq", type="string", label="调仓频率",
                   default="monthly", required=False,
                   description="调仓频率: weekly / monthly / quarterly",
                   choices=["weekly", "monthly", "quarterly"]),
        SkillParam(name="lookback", type="int", label="回看窗口",
                   default=60, required=False,
                   description="动量计算回看窗口 (交易日)"),
        SkillParam(name="benchmark", type="string", label="基准名称",
                   default="CSI300", required=False,
                   description="基准指数",
                   choices=["CSI300", "CSI500", "CSI1000", "CSI_ALL"]),
        SkillParam(name="generate_demo", type="bool", label="生成演示数据",
                   default=True, required=False,
                   description="无真实数据时是否生成演示数据"),
    ],
    tags=["sector", "rotation", "momentum", "reversion", "composite"],
    execute=_execute_sector_rotation,
    handler="factor_lab.research_skill.builtins:_execute_sector_rotation",
    version="1.0.0",
)


# ─── Export ─────────────────────────────────────────────────────────

BUILTIN_SKILLS = [
    DATA_QUALITY_SKILL,
    FACTOR_RANKING_SKILL,
    UNIVERSE_OVERVIEW_SKILL,
    MARKET_SNAPSHOT_SKILL,
    STRATEGY_REPORT_SKILL,
    FACTOR_MINING_SKILL,
    # V6.8: Sector Rotation
    SECTOR_ROTATION_SKILL,
]
