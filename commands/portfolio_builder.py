#!/usr/bin/env python3
"""
V4.7 低频组合构建与推荐系统 (从因子信号到可执行组合建议)

核心管线:
  1. build_portfolio(factor_signals, constraints) — 从因子信号构建组合
  2. apply_constraints(portfolio, universe) — 应用交易约束
  3. build_etf_replacement(portfolio) — 输出ETF替代方案
  4. portfolio_report(portfolio) — 输出完整组合报告

用法:
  from portfolio_builder import PortfolioBuilder

  builder = PortfolioBuilder()
  portfolio = builder.build_portfolio(factor_signals=[...], constraints={...})
  report = builder.portfolio_report(portfolio)
  print(json.dumps(report, ensure_ascii=False, indent=2))
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))
BASE = Path(__file__).resolve().parent.parent  # research-assistant/
DATA_DIR = BASE / "data"
OUTPUT_DIR = DATA_DIR / "portfolio"

# ─── 常量 ──────────────────────────────────────────────────────────────────
DEFAULT_CONSTRAINTS: dict[str, Any] = {
    "position_cap": 0.15,          # 单票仓位上限 15%
    "industry_cap": 0.30,          # 行业集中度上限 30% (申万一级)
    "subsector_cap": 0.25,         # 细分方向集中度上限 25%
    "mainboard_multiplier": 1.5,   # 主板优先权重乘数
    "min_turnover": 10_000_000,    # 最低日成交额 1000万
    "late_session_cutoff": "14:55",  # 尾盘禁新仓时间
    "lot_size": 100,               # A股整手
    "top_n": 10,                   # 目标组合数量
    "capital": 50_000,             # 总资金
}

# ETF 替代池 (与 universes.py 对齐)
ETF_REPLACEMENT_POOL: list[dict[str, str]] = [
    {"ts_code": "512480.SH", "name": "半导体ETF", "track_index": "中证全指半导体产品与设备指数", "board_tag": "通用"},
    {"ts_code": "512760.SH", "name": "芯片ETF", "track_index": "中华交易服务芯片产业指数", "board_tag": "通用"},
    {"ts_code": "159813.SZ", "name": "半导体ETF", "track_index": "国证半导体芯片指数", "board_tag": "通用"},
    {"ts_code": "159995.SZ", "name": "芯片ETF", "track_index": "国证芯片指数", "board_tag": "通用"},
    {"ts_code": "588000.SH", "name": "科创50ETF", "track_index": "上证科创板50成份指数", "board_tag": "科创板"},
    {"ts_code": "588050.SH", "name": "科创芯片ETF", "track_index": "上证科创板芯片指数", "board_tag": "科创板"},
    {"ts_code": "159859.SZ", "name": "科创芯片ETF", "track_index": "国证半导体芯片指数", "board_tag": "科创板"},
    {"ts_code": "515050.SH", "name": "AI算力ETF", "track_index": "中证人工智能主题指数", "board_tag": "通用"},
    {"ts_code": "159997.SZ", "name": "电子ETF", "track_index": "中证电子指数", "board_tag": "通用"},
]


# ═══════════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class FactorSignalItem:
    """单个因子信号条目"""
    ts_code: str
    symbol: str
    name: str = ""
    factor_value: float = 0.0
    factor_rank: int = 0
    factor_zscore: float = 0.0
    signal_source: str = ""       # 因子名称
    selection_reason: str = ""    # 入选原因


@dataclass
class ConstraintViolation:
    """约束违反记录"""
    rule: str
    severity: str = "warning"  # blocker / warning / info
    message: str = ""
    symbol: str = ""
    actual_value: float = 0.0
    threshold: float = 0.0


@dataclass
class RiskStatus:
    """单票风控状态"""
    symbol: str = ""
    name: str = ""
    is_st: bool = False
    is_suspended: bool = False
    is_limit_up: bool = False
    is_limit_down: bool = False
    is_low_liquidity: bool = False
    is_non_tradable_board: bool = False  # 科创/创业无权限
    is_blocked: bool = False
    block_reasons: list[str] = field(default_factory=list)
    etf_replacement: Optional[dict[str, Any]] = None  # 当不可交易时推荐ETF


@dataclass
class PortfolioStock:
    """组合中的单只股票"""
    ts_code: str
    symbol: str
    name: str = ""
    weight: float = 0.0         # 目标权重
    shares: int = 0             # 目标股数
    estimated_amount: float = 0.0
    factor_rank: int = 0
    factor_zscore: float = 0.0
    board: str = ""             # 主板/创业板/科创板
    industry: str = ""          # 申万一级行业
    semiconductor_subsector: str = ""  # 半导体细分方向
    selection_reason: str = ""  # 入选原因
    risk: RiskStatus = field(default_factory=RiskStatus)
    constraint_violations: list[ConstraintViolation] = field(default_factory=list)
    is_core: bool = True        # True=核心组合, False=卫星组合
    is_tradable: bool = True    # False=不可交易 (用ETF替代)


@dataclass
class Portfolio:
    """完整组合"""
    name: str = ""
    built_at: str = ""
    signal_date: str = ""
    capital: float = DEFAULT_CONSTRAINTS["capital"]
    target_n: int = DEFAULT_CONSTRAINTS["top_n"]
    stocks: list[PortfolioStock] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_CONSTRAINTS))
    violations: list[ConstraintViolation] = field(default_factory=list)
    etf_replacements: list[dict[str, Any]] = field(default_factory=list)
    theme_position: str = ""  # 主题仓位建议: 0/30/50/70/100%


# ═══════════════════════════════════════════════════════════════════════════
# PortfolioBuilder
# ═══════════════════════════════════════════════════════════════════════════

class PortfolioBuilder:
    """低频组合构建器 — 从因子信号到可执行组合建议"""

    def __init__(self):
        self._universe_cache: dict[str, dict] = {}
        self._kline_cache: dict[str, pd.DataFrame] = {}
        self._benchmark_cache: dict[str, pd.Series] = {}

    # ── 公开接口 ────────────────────────────────────────────────────────

    def build_portfolio(
        self,
        factor_signals: list[dict[str, Any]],
        constraints: Optional[dict[str, Any]] = None,
        signal_date: str = "",
    ) -> Portfolio:
        """从因子信号构建组合

        Args:
            factor_signals: 因子信号列表, 每项包含 {ts_code, symbol, name,
                           factor_value, signal_source}
            constraints: 约束字典, 覆盖 DEFAULT_CONSTRAINTS
            signal_date: 信号日期 YYYY-MM-DD

        Returns:
            Portfolio 组合对象
        """
        merged_constraints = dict(DEFAULT_CONSTRAINTS)
        if constraints:
            merged_constraints.update(constraints)

        target_n = merged_constraints.get("top_n", 10)
        capital = merged_constraints.get("capital", 50000)

        # Step 1: 信号归一化 (rank, zscore)
        normalized = self._normalize_signals(factor_signals)

        # Step 2: 取 Top-N 候选
        top_candidates = normalized[:target_n]

        # Step 3: 加载股票池上下文
        universe_data = self._load_universe_context(top_candidates)

        # Step 4: 计算权重并构建 PortfolioStock 列表
        stocks: list[PortfolioStock] = []

        # 4a: 计算原始 ranking-based 权重
        max_rank = max((c.get("factor_rank", 1) for c in top_candidates), default=1)
        for item in top_candidates:
            ts_code = item["ts_code"]
            ctx = universe_data.get(ts_code, {})
            board = ctx.get("board", "")
            rank = item.get("factor_rank", 1)

            raw_weight = (max_rank - rank + 1) / sum(
                (max_rank - c.get("factor_rank", 1) + 1) for c in top_candidates
            ) if top_candidates else 0

            # 主板优先
            if board == "主板":
                raw_weight *= merged_constraints.get("mainboard_multiplier", 1.5)

            item["_raw_weight"] = raw_weight

        # 4b: 统一归一化
        total_raw = sum(c.get("_raw_weight", 0) for c in top_candidates) or 1.0
        for item in top_candidates:
            item["_weight"] = item.get("_raw_weight", 0) / total_raw

        # 4c: 构建 PortfolioStock 对象
        for item in top_candidates:
            ts_code = item["ts_code"]
            ctx = universe_data.get(ts_code, {})
            board = ctx.get("board", "")
            industry = ctx.get("industry", "")

            weight = item.get("_weight", 0)
            rank = item.get("factor_rank", 1)
            zscore = item.get("factor_zscore", 0.0)

            shares = self._calc_shares(weight, capital, merged_constraints.get("lot_size", 100))

            stock = PortfolioStock(
                ts_code=ts_code,
                symbol=item.get("symbol", ""),
                name=item.get("name", ""),
                weight=round(weight, 4),
                shares=shares,
                estimated_amount=round(weight * capital, 2),
                factor_rank=rank,
                factor_zscore=round(zscore, 4),
                board=board,
                industry=industry,
                semiconductor_subsector=ctx.get("semiconductor_subsector", ""),
                selection_reason=item.get("selection_reason", item.get("signal_source", "")),
                risk=RiskStatus(symbol=item.get("symbol", ""), name=item.get("name", "")),
                is_core=True,
            )
            stocks.append(stock)

        # Step 5: 应用约束
        portfolio = Portfolio(
            name=f"V4.7 低频组合 {signal_date}",
            built_at=datetime.now(CST).isoformat(),
            signal_date=signal_date,
            capital=capital,
            target_n=target_n,
            stocks=stocks,
            constraints=merged_constraints,
        )

        portfolio = self.apply_constraints(portfolio, universe_data)

        # Step 6: 构建ETF替代方案
        portfolio = self.build_etf_replacement(portfolio)

        # Step 7: 确定主题仓位
        portfolio.theme_position = self._determine_theme_position(portfolio)

        return portfolio

    def apply_constraints(
        self,
        portfolio: Portfolio,
        universe_data: Optional[dict[str, Any]] = None,
    ) -> Portfolio:
        """应用交易约束, 标记不可交易股票和违反项

        逐一检查:
          - 单票仓位上限 (默认 15%)
          - 行业集中度上限 (默认 30%)
          - 细分方向集中度上限 (25%)
          - 主板优先 (权重 1.5x 已在 build 中处理)
          - 创业板/科创板权限过滤
          - 日成交额过滤 (<1000万)
          - 涨停禁买 / 跌停禁卖 / 停牌禁交易
          - 100股整数倍
          - 尾盘禁新仓 (14:55后)
        """
        constraints = portfolio.constraints
        all_violations: list[ConstraintViolation] = []
        late_session = self._is_late_session(constraints.get("late_session_cutoff", "14:55"))

        if universe_data is None:
            universe_data = self._load_universe_context(
                [{"ts_code": s.ts_code, "symbol": s.symbol} for s in portfolio.stocks]
            )

        # ── 1) 单票仓位上限 ──
        position_cap = constraints.get("position_cap", 0.15)
        for stock in portfolio.stocks:
            if stock.weight > position_cap:
                v = ConstraintViolation(
                    rule="position_cap",
                    severity="blocker",
                    message=f"仓位 {stock.weight:.2%} 超过上限 {position_cap:.0%}",
                    symbol=stock.symbol,
                    actual_value=stock.weight,
                    threshold=position_cap,
                )
                stock.constraint_violations.append(v)
                all_violations.append(v)
                stock.weight = position_cap
                stock.is_tradable = False

        # 重新归一化权重 (仓位上限调整后)
        total_w = sum(s.weight for s in portfolio.stocks) or 1.0
        for stock in portfolio.stocks:
            stock.weight = stock.weight / total_w
            capital = portfolio.capital
            stock.estimated_amount = round(stock.weight * capital, 2)
            stock.shares = self._calc_shares(
                stock.weight, capital, constraints.get("lot_size", 100)
            )

        # ── 2) 行业集中度 ──
        industry_cap = constraints.get("industry_cap", 0.30)
        industry_weights: dict[str, float] = {}
        for stock in portfolio.stocks:
            ind = stock.industry or "其他"
            industry_weights[ind] = industry_weights.get(ind, 0) + stock.weight

        for ind, w in industry_weights.items():
            if w > industry_cap:
                v = ConstraintViolation(
                    rule="industry_cap",
                    severity="warning",
                    message=f"行业 '{ind}' 集中度 {w:.2%} 超过上限 {industry_cap:.0%}",
                    symbol="",
                    actual_value=w,
                    threshold=industry_cap,
                )
                all_violations.append(v)

        # ── 3) 细分方向集中度 ──
        subsector_cap = constraints.get("subsector_cap", 0.25)
        subsector_weights: dict[str, float] = {}
        for stock in portfolio.stocks:
            sub = stock.semiconductor_subsector or "其他"
            subsector_weights[sub] = subsector_weights.get(sub, 0) + stock.weight

        for sub, w in subsector_weights.items():
            if w > subsector_cap and sub != "其他":
                v = ConstraintViolation(
                    rule="subsector_cap",
                    severity="warning",
                    message=f"细分方向 '{sub}' 集中度 {w:.2%} 超过上限 {subsector_cap:.0%}",
                    symbol="",
                    actual_value=w,
                    threshold=subsector_cap,
                )
                all_violations.append(v)

        # ── 4) 权限过滤 & 行情过滤 ──
        min_turnover = constraints.get("min_turnover", 10_000_000)

        for stock in portfolio.stocks:
            ctx = universe_data.get(stock.ts_code, {})

            risk = stock.risk
            block_reasons: list[str] = []

            # 板块权限
            board = stock.board or ctx.get("board", "")
            stock.board = board
            is_star = board == "科创板"
            is_chinext = board == "创业板"

            if is_star:
                risk.is_non_tradable_board = True
                block_reasons.append("科创板 (需科创板权限)")
            if is_chinext:
                risk.is_non_tradable_board = True
                block_reasons.append("创业板 (需创业板权限)")

            # ST标记
            is_st = ctx.get("is_st", False)
            risk.is_st = is_st
            if is_st:
                block_reasons.append("ST/*ST")

            # 停牌
            is_suspended = ctx.get("is_suspended", False)
            risk.is_suspended = is_suspended
            if is_suspended:
                block_reasons.append("停牌")

            # 涨停/跌停
            is_limit_up = ctx.get("is_limit_up", False)
            is_limit_down = ctx.get("is_limit_down", False)
            risk.is_limit_up = is_limit_up
            risk.is_limit_down = is_limit_down
            if is_limit_up:
                block_reasons.append("涨停封板 (禁买)")
            if is_limit_down:
                block_reasons.append("跌停封板 (禁卖)")

            # 低流动性
            avg_amount = ctx.get("avg_amount_20d", 0) or 0
            if avg_amount < min_turnover:
                risk.is_low_liquidity = True
                block_reasons.append(f"低流动性 (日均成交{avg_amount/10000:.0f}万<{min_turnover/10000:.0f}万)")

            # 尾盘禁新仓
            if late_session:
                block_reasons.append(f"尾盘禁新仓 ({constraints.get('late_session_cutoff', '14:55')}后)")

            # 更新风控状态
            risk.is_blocked = len(block_reasons) > 0
            risk.block_reasons = block_reasons

            if risk.is_blocked:
                stock.is_tradable = False
                v = ConstraintViolation(
                    rule="tradability",
                    severity="blocker" if any(r in str(block_reasons) for r in ["ST", "停牌"]) else "warning",
                    message="; ".join(block_reasons),
                    symbol=stock.symbol,
                )
                stock.constraint_violations.append(v)
                all_violations.append(v)

        # ── 5) 100股整数倍 ──
        lot_size = constraints.get("lot_size", 100)
        for stock in portfolio.stocks:
            stock.shares = self._round_to_lot(stock.shares, lot_size)

        portfolio.violations = all_violations
        return portfolio

    def build_etf_replacement(self, portfolio: Portfolio) -> Portfolio:
        """为不可交易的科创板/创业板股票构建ETF替代方案

        对每只 is_tradable=False 且 is_non_tradable_board=True 的股票,
        推荐合适的ETF替代。
        """
        etf_replacements: list[dict[str, Any]] = []
        seen_etfs: set[str] = set()

        for stock in portfolio.stocks:
            if not stock.is_tradable and stock.risk.is_non_tradable_board:
                # 找到最匹配的ETF
                replacement = self._find_etf_match(stock)
                if replacement:
                    stock.risk.etf_replacement = replacement
                    etf_key = replacement.get("ts_code", "")
                    if etf_key not in seen_etfs:
                        seen_etfs.add(etf_key)
                        etf_replacements.append({
                            "ts_code": etf_key,
                            "name": replacement.get("name", ""),
                            "track_index": replacement.get("track_index", ""),
                            "replaces": [stock.symbol],
                            "reason": f"替代科创板票 {stock.name} ({stock.symbol})",
                        })
                else:
                    # 通用ETF兜底
                    if "588000.SH" not in seen_etfs:
                        seen_etfs.add("588000.SH")
                        etf_replacements.append({
                            "ts_code": "588000.SH",
                            "name": "科创50ETF",
                            "track_index": "上证科创板50成份指数",
                            "replaces": [stock.symbol],
                            "reason": f"通用替代 {stock.name} ({stock.symbol})",
                        })

        portfolio.etf_replacements = etf_replacements
        return portfolio

    def portfolio_report(self, portfolio: Portfolio) -> dict[str, Any]:
        """输出完整组合报告

        包含:
          - 主题仓位建议
          - 核心组合 + 卫星组合
          - 每只股票入选原因和风控状态
          - ETF替代方案
          - 与半导体同池等权对比
          - 组合风险暴露
          - 次日风险提示
        """
        core_stocks = [s for s in portfolio.stocks if s.is_core]
        satellite_stocks = [s for s in portfolio.stocks if not s.is_core]
        tradable_stocks = [s for s in portfolio.stocks if s.is_tradable]
        blocked_stocks = [s for s in portfolio.stocks if not s.is_tradable]

        # 行业分布
        industry_exposure = self._compute_industry_exposure(portfolio.stocks)

        # 市值分布
        market_cap_exposure = self._compute_market_cap_exposure(portfolio.stocks)

        # Beta暴露 (估算)
        beta_exposure = self._compute_beta_exposure(portfolio.stocks)

        # 与半导体基准对比
        benchmark_comparison = self._get_benchmark_comparison()

        # 次日风险提示
        risk_tips = self._generate_risk_tips(portfolio)

        report = {
            "report_type": "V4.7 低频组合构建报告",
            "portfolio_name": portfolio.name,
            "built_at": portfolio.built_at,
            "signal_date": portfolio.signal_date,
            "capital": portfolio.capital,
            "target_n": portfolio.target_n,
            "n_stocks_total": len(portfolio.stocks),
            "n_tradable": len(tradable_stocks),
            "n_blocked": len(blocked_stocks),

            # ── 主题仓位建议 ──
            "theme_position": {
                "suggestion": portfolio.theme_position,
                "description": self._theme_position_description(portfolio.theme_position),
                "narrative": self._theme_position_narrative(portfolio.theme_position),
            },

            # ── 组合明细 ──
            "core_composition": self._stock_list_detail(core_stocks),
            "satellite_composition": self._stock_list_detail(satellite_stocks),

            # ── 风控概览 ──
            "risk_overview": {
                "n_blocked": len(blocked_stocks),
                "n_violations": len(portfolio.violations),
                "blocker_count": sum(1 for v in portfolio.violations if v.severity == "blocker"),
                "warning_count": sum(1 for v in portfolio.violations if v.severity == "warning"),
                "violations": [asdict(v) for v in portfolio.violations],
            },

            # ── ETF替代方案 ──
            "etf_replacements": portfolio.etf_replacements,

            # ── 行业暴露 ──
            "industry_exposure": industry_exposure,

            # ── 市值暴露 ──
            "market_cap_exposure": market_cap_exposure,

            # ── Beta暴露 ──
            "beta_exposure": beta_exposure,

            # ── 基准对比 ──
            "benchmark_comparison": benchmark_comparison,

            # ── 次日风险提示 ──
            "next_day_risk_tips": risk_tips,

            # ── 约束摘要 ──
            "constraints_summary": {
                k: v for k, v in portfolio.constraints.items()
                if k in ("position_cap", "industry_cap", "subsector_cap",
                         "mainboard_multiplier", "min_turnover", "late_session_cutoff")
            },
        }

        return report

    # ── CLI 入口 ────────────────────────────────────────────────────────

    @staticmethod
    def cmd_build_lowfreq(args: list[str]) -> None:
        """CLI: portfolio:build-lowfreq

        从模拟信号或指定信号文件构建低频组合。
        """
        signal_file = ""
        signal_date = datetime.now(CST).strftime("%Y-%m-%d")
        capital = DEFAULT_CONSTRAINTS["capital"]
        top_n = DEFAULT_CONSTRAINTS["top_n"]

        for i, a in enumerate(args):
            if a == "--signal-file" and i + 1 < len(args):
                signal_file = args[i + 1]
            elif a == "--signal-date" and i + 1 < len(args):
                signal_date = args[i + 1]
            elif a == "--capital" and i + 1 < len(args):
                try:
                    capital = float(args[i + 1])
                except ValueError:
                    pass
            elif a == "--top-n" and i + 1 < len(args):
                try:
                    top_n = int(args[i + 1])
                except ValueError:
                    pass

        builder = PortfolioBuilder()

        # 加载信号
        if signal_file:
            sig_path = Path(signal_file)
            if not sig_path.exists():
                print(f"❌ 信号文件不存在: {signal_file}")
                return
            with open(sig_path, "r", encoding="utf-8") as f:
                factor_signals = json.load(f)
        else:
            # 生成模拟信号 (U3 股票池)
            factor_signals = builder._generate_mock_signals()

        if not factor_signals:
            print("❌ 因子信号为空")
            return

        constraints = {"capital": capital, "top_n": top_n}
        portfolio = builder.build_portfolio(factor_signals, constraints, signal_date)
        report = builder.portfolio_report(portfolio)

        # 输出
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / f"portfolio_v47_{signal_date.replace('-','')}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n📊 V4.7 低频组合构建完成")
        print(f"   信号日期: {signal_date}")
        print(f"   资金: {capital:,.0f}")
        print(f"   目标数量: {top_n}")
        print(f"   实际入选: {report['n_stocks_total']} 只")
        print(f"   可交易: {report['n_tradable']} 只")
        print(f"   受阻: {report['n_blocked']} 只")
        print(f"   主题仓位: {report['theme_position']['suggestion']}")
        print(f"   ETF替代方案: {len(report['etf_replacements'])} 个")
        print(f"   报告已保存: {out_path}")
        print()

        # 打印核心组合
        print(f"━━━ 核心组合 ━━━")
        for s in report.get("core_composition", []):
            icon = "✅" if s.get("is_tradable") else "❌"
            print(f"  {icon} {s['symbol']} {s['name']:10s}  "
                  f"权重={s['weight']:.1%}  "
                  f"股数={s['shares']}  "
                  f"金额={s['estimated_amount']:,.0f}")
            if s.get("selection_reason"):
                print(f"     入选: {s['selection_reason']}")
            if not s.get("is_tradable"):
                print(f"     风控: {', '.join(s.get('risk',{}).get('block_reasons',[]))}")
        print()

        # ETF替代
        if report.get("etf_replacements"):
            print(f"━━━ ETF替代方案 ━━━")
            for etf in report["etf_replacements"]:
                print(f"  {etf['ts_code']} {etf['name']:12s}  替代: {', '.join(etf.get('replaces',[]))}")
            print()

        # 风险提示
        if report.get("next_day_risk_tips"):
            print("━━━ 次日风险提示 ━━━")
            for tip in report["next_day_risk_tips"]:
                print(f"  ⚠️  {tip}")
            print()

    @staticmethod
    def cmd_recommend(args: list[str]) -> None:
        """CLI: portfolio:recommend — 输出组合推荐摘要"""
        # 查找最新报告
        if not OUTPUT_DIR.exists():
            print("❌ 无历史组合报告, 请先运行 portfolio:build-lowfreq")
            return

        reports = sorted(OUTPUT_DIR.glob("portfolio_v47_*.json"), reverse=True)
        if not reports:
            print("❌ 无组合报告文件")
            return

        latest = reports[0]
        with open(latest, "r", encoding="utf-8") as f:
            report = json.load(f)

        print(f"\n📊 组合推荐摘要")
        print(f"   {'=' * 45}")
        print(f"   报告: {latest.name}")
        print(f"   日期: {report.get('signal_date', 'N/A')}")
        print(f"   主题仓位: {report['theme_position']['suggestion']} — {report['theme_position']['description']}")
        print(f"   核心组合: {len(report.get('core_composition', []))} 只")
        print(f"   卫星组合: {len(report.get('satellite_composition', []))} 只")
        print(f"   可交易: {report.get('n_tradable', 0)} 只")
        print(f"   受阻: {report.get('n_blocked', 0)} 只")
        print(f"   ETF替代: {len(report.get('etf_replacements', []))} 个")
        print(f"   风控违反: {report['risk_overview']['n_violations']} 项 "
              f"(blocker={report['risk_overview']['blocker_count']}, "
              f"warning={report['risk_overview']['warning_count']})")

        # 行业分布
        print(f"\n   行业分布:")
        for ind in report.get("industry_exposure", []):
            bar = "█" * int(ind["weight"] * 30)
            print(f"     {ind['industry']:10s} {ind['weight']:6.1%} {bar}")

        # ETF推荐
        if report.get("etf_replacements"):
            print(f"\n   ETF推荐:")
            for etf in report["etf_replacements"]:
                print(f"     • {etf['ts_code']} {etf['name']} ({etf['reason']})")

        print()

    @staticmethod
    def cmd_risk(args: list[str]) -> None:
        """CLI: portfolio:risk — 查看组合风险暴露"""
        # 查找最新报告
        if not OUTPUT_DIR.exists():
            print("❌ 无历史组合报告")
            return
        reports = sorted(OUTPUT_DIR.glob("portfolio_v47_*.json"), reverse=True)
        if not reports:
            print("❌ 无组合报告文件")
            return

        latest = reports[0]
        with open(latest, "r", encoding="utf-8") as f:
            report = json.load(f)

        print(f"\n🛡️  组合风险暴露")
        print(f"   {'=' * 45}")

        # 行业
        print(f"\n   行业暴露:")
        for ind in report.get("industry_exposure", []):
            risk = "⚠️" if ind["weight"] > 0.25 else "✅"
            print(f"     {risk} {ind['industry']:10s} {ind['weight']:6.1%}")

        # 市值
        print(f"\n   市值暴露:")
        for cap in report.get("market_cap_exposure", []):
            print(f"     {cap['bucket']:10s} {cap['weight']:6.1%}")

        # Beta
        print(f"\n   Beta暴露:")
        for b in report.get("beta_exposure", []):
            print(f"     {b['bucket']:10s} {b['weight']:6.1%} (平均Beta={b.get('avg_beta', 'N/A')})")

        # 风险提示
        if report.get("next_day_risk_tips"):
            print(f"\n   次日风险提示:")
            for tip in report["next_day_risk_tips"]:
                print(f"     ⚠️  {tip}")

        # 风控违反
        if report["risk_overview"]["n_violations"] > 0:
            print(f"\n   约束违反:")
            for v in report["risk_overview"]["violations"]:
                icon = "🔴" if v["severity"] == "blocker" else "🟡"
                sym_info = f" ({v['symbol']})" if v.get("symbol") else ""
                print(f"     {icon} {v['rule']}{sym_info}: {v['message']}")

        print()

    @staticmethod
    def cmd_premarket_v4(args: list[str]) -> None:
        """CLI: premarket:v4 — 盘前组合建议 (V4版)"""
        # 等同于 build-lowfreq + recommend
        PortfolioBuilder.cmd_build_lowfreq(args)

    # ── 内部方法 ────────────────────────────────────────────────────────

    def _normalize_signals(self, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """信号归一化: rank + zscore

        Args:
            signals: 原始信号列表

        Returns:
            增强后的信号列表 (含 factor_rank, factor_zscore)
        """
        if not signals:
            import logging
            logging.getLogger(__name__).warning("normalize_signals: 空信号列表，返回 [] (degraded)")
            return []

        values = [s.get("factor_value", s.get("value", 0)) for s in signals]
        arr = np.array(values, dtype=float)

        # Rank (降序, 值越大信号越强)
        ranks = len(arr) - np.argsort(np.argsort(arr))  # 1-based rank
        max_rank = len(arr)

        # Z-score
        mean = np.nanmean(arr)
        std = np.nanstd(arr) or 1.0
        zscores = (arr - mean) / std

        for i, s in enumerate(signals):
            s["factor_rank"] = int(ranks[i])
            s["factor_zscore"] = round(float(zscores[i]), 4)

        # 按rank排序
        signals.sort(key=lambda x: x.get("factor_rank", 999))
        return signals

    def _load_universe_context(self, top_candidates: list[dict]) -> dict[str, Any]:
        """从 universes.json 加载股票上下文

        尝试加载 U0/U1/U3 数据用于约束检查。
        """
        result: dict[str, Any] = {}

        # 检查 universes.json 是否存在
        if not (BASE / "data" / "universes.json").exists():
            logger.info("universes.json 不存在, 使用空上下文")
            return result

        try:
            from commands.universes import get_universe  # type: ignore
        except ImportError:
            try:
                from universes import get_universe
            except ImportError:
                logger.warning("universes 模块不可用, 使用空上下文")
                return result

        # 构建 ts_code → symbol 映射
        code_to_symbol = {c.get("ts_code", ""): c.get("symbol", "") for c in top_candidates}
        codes_needed = list(code_to_symbol.keys())

        # 尝试加载 U3 (半导体核心池)
        try:
            u3 = get_universe("U3")
            for s in u3.get("stocks", []):
                ts_code = s.get("ts_code", "")
                if ts_code in codes_needed:
                    result[ts_code] = {
                        "industry": s.get("industry", ""),
                        "semiconductor_subsector": ", ".join(
                            s.get("semiconductor_subsector", [])
                        ) if isinstance(s.get("semiconductor_subsector"), list) else s.get("semiconductor_subsector", ""),
                        "board": "",
                        "is_st": False,
                        "is_suspended": False,
                        "is_limit_up": False,
                        "is_limit_down": False,
                        "avg_amount_20d": 0,
                    }
        except Exception:
            pass

        # 加载 U1 补充交易标记
        try:
            u1 = get_universe("U1")
            for s in u1.get("stocks", []):
                ts_code = s.get("ts_code", "")
                if ts_code in codes_needed:
                    if ts_code not in result:
                        result[ts_code] = {}
                    result[ts_code].update({
                        "board": s.get("is_star", False) and "科创板" or
                                 s.get("is_chinext", False) and "创业板" or
                                 s.get("is_mainboard", False) and "主板" or "",
                        "is_st": s.get("is_st", False),
                        "is_suspended": s.get("is_suspended", False),
                        "is_limit_up": s.get("is_limit_up", False),
                        "is_limit_down": s.get("is_limit_down", False),
                        "avg_amount_20d": s.get("avg_amount_20d", 0),
                    })
        except Exception:
            pass

        # 加载 U0 补充行业信息
        try:
            u0 = get_universe("U0")
            for s in u0.get("stocks", []):
                ts_code = s.get("ts_code", "")
                if ts_code in codes_needed:
                    if ts_code not in result:
                        result[ts_code] = {}
                    if "industry" not in result[ts_code]:
                        result[ts_code]["industry"] = s.get("industry", "")
                    if "board" not in result[ts_code]:
                        result[ts_code]["board"] = s.get("board", "")
        except Exception:
            pass

        return result

    def _calc_shares(self, weight: float, capital: float, lot_size: int = 100) -> int:
        """根据权重和资金计算股数 (整手)"""
        amount = weight * capital
        shares = int(amount / 10)  # 估算股价~10元
        return self._round_to_lot(shares, lot_size)

    @staticmethod
    def _round_to_lot(shares: int, lot_size: int = 100) -> int:
        """向下取整到 100 的整数倍, 至少 100"""
        if shares <= 0:
            return 0
        lots = shares // lot_size
        return lots * lot_size if lots > 0 else lot_size

    @staticmethod
    def _is_late_session(cutoff_str: str = "14:55") -> bool:
        """检查当前是否在尾盘禁新仓时段"""
        now = datetime.now(CST)
        parts = cutoff_str.split(":")
        cutoff_hour = int(parts[0])
        cutoff_min = int(parts[1]) if len(parts) > 1 else 0
        cutoff = now.replace(hour=cutoff_hour, minute=cutoff_min, second=0, microsecond=0)
        return now >= cutoff

    def _find_etf_match(self, stock: PortfolioStock) -> Optional[dict[str, str]]:
        """为不可交易的股票匹配合适的ETF

        匹配逻辑:
          - 科创板 → 优先匹配 588050.SH 科创芯片ETF
          - 通用 → 匹配 512480.SH 半导体ETF
        """
        board = stock.board or ""
        if "科创板" in board:
            # 优先科创芯片ETF
            for etf in ETF_REPLACEMENT_POOL:
                if "科创" in etf.get("name", "") and "芯片" in etf.get("name", ""):
                    return etf
            # 兜底科创50ETF
            for etf in ETF_REPLACEMENT_POOL:
                if "科创50" in etf.get("name", ""):
                    return etf
        # 通用半导体ETF
        for etf in ETF_REPLACEMENT_POOL:
            if "半导体" in etf.get("name", ""):
                return etf
        return None

    @staticmethod
    def _determine_theme_position(portfolio: Portfolio) -> str:
        """确定主题仓位建议

        基于组合中可交易股票的比例和约束违反严重程度。
        """
        if not portfolio.stocks:
            return "0%"

        tradable_ratio = sum(1 for s in portfolio.stocks if s.is_tradable) / len(portfolio.stocks)
        blocker_count = sum(1 for v in portfolio.violations if v.severity == "blocker")

        if tradable_ratio >= 0.8 and blocker_count == 0:
            return "100%"
        elif tradable_ratio >= 0.6 and blocker_count <= 1:
            return "70%"
        elif tradable_ratio >= 0.4:
            return "50%"
        elif tradable_ratio >= 0.2:
            return "30%"
        else:
            return "0%"

    @staticmethod
    def _theme_position_description(position: str) -> str:
        descriptions = {
            "100%": "满仓配置 — 信号明确, 组合结构合理",
            "70%": "较高仓位 — 大部分标的可交易, 少量受限",
            "50%": "半仓配置 — 部分标的受限, 建议观望",
            "30%": "低仓位试探 — 多数标的受限, 谨慎参与",
            "0%": "空仓观望 — 当前无合适可交易标的",
        }
        return descriptions.get(position, position)

    @staticmethod
    def _theme_position_narrative(position: str) -> str:
        narratives = {
            "100%": "因子信号清晰, 组合风控全部通过, 建议满仓执行。注意尾盘时间和单票仓位。",
            "70%": "大部分标的通过约束检查, 少量标的因权限/流动性受阻。核心组合以70%仓位执行, 受阻部分用ETF替代。",
            "50%": "约半数的因子候选受约束限制, 建议半仓配置核心可交易标的, 其余通过ETF获取暴露。",
            "30%": "当前市场环境下多数因子候选存在交易障碍, 建议低仓位试探, 重点使用ETF替代。",
            "0%": "因子候选均不满足交易约束, 建议空仓观望, 等待更合适的入场时机。",
        }
        return narratives.get(position, position)

    @staticmethod
    def _stock_list_detail(stocks: list[PortfolioStock]) -> list[dict[str, Any]]:
        """输出股票明细"""
        return [
            {
                "ts_code": s.ts_code,
                "symbol": s.symbol,
                "name": s.name,
                "weight": round(s.weight, 4),
                "shares": s.shares,
                "estimated_amount": round(s.estimated_amount, 2),
                "factor_rank": s.factor_rank,
                "factor_zscore": s.factor_zscore,
                "board": s.board,
                "industry": s.industry,
                "semiconductor_subsector": s.semiconductor_subsector,
                "selection_reason": s.selection_reason,
                "is_core": s.is_core,
                "is_tradable": s.is_tradable,
                "risk": {
                    "is_st": s.risk.is_st,
                    "is_suspended": s.risk.is_suspended,
                    "is_limit_up": s.risk.is_limit_up,
                    "is_limit_down": s.risk.is_limit_down,
                    "is_low_liquidity": s.risk.is_low_liquidity,
                    "is_non_tradable_board": s.risk.is_non_tradable_board,
                    "is_blocked": s.risk.is_blocked,
                    "block_reasons": s.risk.block_reasons,
                    "etf_replacement": s.risk.etf_replacement,
                },
                "constraint_violations": [asdict(v) for v in s.constraint_violations],
            }
            for s in stocks
        ]

    @staticmethod
    def _compute_industry_exposure(
        stocks: list[PortfolioStock],
    ) -> list[dict[str, Any]]:
        """计算行业暴露"""
        weights: dict[str, float] = {}
        for s in stocks:
            ind = s.industry or "其他"
            weights[ind] = weights.get(ind, 0) + s.weight

        exposure = sorted(
            [{"industry": k, "weight": round(v, 4)} for k, v in weights.items()],
            key=lambda x: x["weight"],
            reverse=True,
        )
        return exposure

    @staticmethod
    def _compute_market_cap_exposure(
        stocks: list[PortfolioStock],
    ) -> list[dict[str, Any]]:
        """估算市值暴露 (基于粗略假设)

        大型: >500亿, 中型: 100-500亿, 小型: <100亿
        """
        # 使用粗略映射
        buckets = {"大盘": 0.0, "中盘": 0.0, "小盘": 0.0}
        for s in stocks:
            # 简单根据代码前缀估算
            sym = s.symbol
            if sym.startswith("688") or sym.startswith("300"):
                buckets["小盘"] += s.weight * 0.5
                buckets["中盘"] += s.weight * 0.5
            elif sym.startswith("60") or sym.startswith("000"):
                buckets["大盘"] += s.weight * 0.3
                buckets["中盘"] += s.weight * 0.7
            else:
                buckets["中盘"] += s.weight

        return sorted(
            [{"bucket": k, "weight": round(v, 4)} for k, v in buckets.items()],
            key=lambda x: x["weight"],
            reverse=True,
        )

    @staticmethod
    def _compute_beta_exposure(
        stocks: list[PortfolioStock],
    ) -> list[dict[str, Any]]:
        """估算Beta暴露

        半导体设备/设计类通常高Beta, 封测/材料中等, ETF低Beta。
        """
        buckets = {"高Beta (>1.2)": 0.0, "中Beta (0.8-1.2)": 0.0, "低Beta (<0.8)": 0.0}
        for s in stocks:
            sub = s.semiconductor_subsector or ""
            if any(k in sub for k in ["设计", "设备", "制造"]):
                buckets["高Beta (>1.2)"] += s.weight
            elif any(k in sub for k in ["封测", "材料", "功率"]):
                buckets["中Beta (0.8-1.2)"] += s.weight
            else:
                buckets["中Beta (0.8-1.2)"] += s.weight

        return sorted(
            [{"bucket": k, "weight": round(v, 4)} for k, v in buckets.items()],
            key=lambda x: x["weight"],
            reverse=True,
        )

    @staticmethod
    def _get_benchmark_comparison() -> dict[str, Any]:
        """与半导体同池等权对比

        尝试从 benchmarks_v4 获取半导体等权基准数据。
        """
        try:
            from commands.benchmarks_v4 import get_benchmark_report  # type: ignore
        except ImportError:
            try:
                from benchmarks_v4 import get_benchmark_report
            except ImportError:
                return {"available": False, "reason": "benchmarks_v4 不可用"}

        try:
            report = get_benchmark_report("semiconductor_ew")
            return {
                "available": True,
                "benchmark": "semiconductor_ew",
                "label": "半导体300池等权",
                **{k: v for k, v in report.items() if k != "name"},
            }
        except Exception as e:
            return {"available": False, "reason": str(e)}

    @staticmethod
    def _generate_risk_tips(portfolio: Portfolio) -> list[str]:
        """生成次日风险提示"""
        tips: list[str] = []
        now = datetime.now(CST)

        # 时间检查
        if now.hour >= 14 and now.minute >= 30:
            tips.append(f"当前已过 {portfolio.constraints.get('late_session_cutoff', '14:55')}, "
                        "禁止新开仓, 新建组合建议次日盘前执行")

        # 市场风险
        if portfolio.stocks:
            # 检查半导体细分集中
            subsectors: dict[str, float] = {}
            for s in portfolio.stocks:
                sub = s.semiconductor_subsector or "其他"
                subsectors[sub] = subsectors.get(sub, 0) + s.weight
            for sub, w in subsectors.items():
                if w > 0.4 and sub != "其他":
                    tips.append(f"细分方向 '{sub}' 集中度 {w:.0%}, 单方向风险偏高, 建议分散")

            # 检查不可交易比例
            blocked_ratio = sum(1 for s in portfolio.stocks if not s.is_tradable) / len(portfolio.stocks)
            if blocked_ratio > 0.5:
                tips.append(f"超过 {blocked_ratio:.0%} 的候选标的存在交易障碍, "
                            "优先使用ETF替代获取暴露")

            # 权限提示
            board_needs = set()
            for s in portfolio.stocks:
                if s.risk.is_non_tradable_board and "科创板" in (s.board or ""):
                    board_needs.add("科创板")
                elif s.risk.is_non_tradable_board and "创业板" in (s.board or ""):
                    board_needs.add("创业板")
            if board_needs:
                tips.append(f"需要{'/'.join(board_needs)}权限, 未开通请使用ETF替代方案")

        return tips

    @staticmethod
    def _generate_mock_signals() -> list[dict[str, Any]]:
        """生成模拟因子信号 (用于测试/演示)

        从 U3 半导体核心池提取股票, 生成随机因子信号。
        """
        # 检查 universes.json 是否存在
        from pathlib import Path as _P
        _univ_file = _P(__file__).resolve().parent.parent / "data" / "universes.json"
        if not _univ_file.exists():
            return _fallback_mock_signals()

        try:
            from commands.universes import get_universe  # type: ignore
        except ImportError:
            try:
                from universes import get_universe
            except ImportError:
                return _fallback_mock_signals()

        try:
            u3 = get_universe("U3")
        except Exception:
            return _fallback_mock_signals()

        stocks = u3.get("stocks", [])
        if not stocks:
            return _fallback_mock_signals()

        # 按 core_score 排序取前 30
        sorted_stocks = sorted(
            stocks, key=lambda x: x.get("core_score", 0), reverse=True
        )[:30]

        rng = np.random.default_rng(42)
        signals = []
        for s in sorted_stocks:
            ts_code = s.get("ts_code", "")
            symbol = ts_code.split(".")[0] if "." in ts_code else ts_code
            signals.append({
                "ts_code": ts_code,
                "symbol": symbol,
                "name": s.get("name", ""),
                "factor_value": round(float(rng.normal(0.02, 0.05)), 6),
                "signal_source": "模拟信号 (V4.7 Mock)",
                "selection_reason": f"半导体核心票, "
                                    f"细分={s.get('semiconductor_subsector', 'N/A')}, "
                                    f"核心度={s.get('core_score', 0)}",
            })

        return signals


# ═══════════════════════════════════════════════════════════════════════════
# Fallback 模拟信号 (当 universes 不可用时)
# ═══════════════════════════════════════════════════════════════════════════

_FALLBACK_SIGNALS = [
    {"ts_code": "688012.SH", "symbol": "688012", "name": "中微公司",
     "factor_value": 0.035, "signal_source": "模拟信号",
     "selection_reason": "半导体设备龙头, 刻蚀/薄膜核心标的"},
    {"ts_code": "688981.SH", "symbol": "688981", "name": "中芯国际",
     "factor_value": 0.028, "signal_source": "模拟信号",
     "selection_reason": "晶圆代工龙头, 国产替代核心标的"},
    {"ts_code": "688126.SH", "symbol": "688126", "name": "沪硅产业",
     "factor_value": 0.025, "signal_source": "模拟信号",
     "selection_reason": "硅片材料龙头, 上游关键环节"},
    {"ts_code": "688008.SH", "symbol": "688008", "name": "澜起科技",
     "factor_value": 0.032, "signal_source": "模拟信号",
     "selection_reason": "接口芯片设计龙头, DDR5渗透率提升"},
    {"ts_code": "688396.SH", "symbol": "688396", "name": "华润微",
     "factor_value": 0.022, "signal_source": "模拟信号",
     "selection_reason": "功率半导体IDM, 特色工艺平台"},
    {"ts_code": "002371.SZ", "symbol": "002371", "name": "北方华创",
     "factor_value": 0.038, "signal_source": "模拟信号",
     "selection_reason": "半导体设备平台型龙头"},
    {"ts_code": "603501.SH", "symbol": "603501", "name": "韦尔股份",
     "factor_value": 0.030, "signal_source": "模拟信号",
     "selection_reason": "CIS图像传感器设计龙头"},
    {"ts_code": "300661.SZ", "symbol": "300661", "name": "圣邦股份",
     "factor_value": 0.026, "signal_source": "模拟信号",
     "selection_reason": "模拟芯片设计龙头"},
    {"ts_code": "688005.SH", "symbol": "688005", "name": "容百科技",
     "factor_value": 0.020, "signal_source": "模拟信号",
     "selection_reason": "正极材料龙头, 新能源产业链"},
    {"ts_code": "600703.SH", "symbol": "600703", "name": "三安光电",
     "factor_value": 0.024, "signal_source": "模拟信号",
     "selection_reason": "化合物半导体龙头 (SiC/GaN)"},
    {"ts_code": "688256.SH", "symbol": "688256", "name": "寒武纪",
     "factor_value": 0.040, "signal_source": "模拟信号",
     "selection_reason": "AI芯片设计龙头, 算力核心标的"},
    {"ts_code": "300782.SZ", "symbol": "300782", "name": "卓胜微",
     "factor_value": 0.018, "signal_source": "模拟信号",
     "selection_reason": "射频前端芯片设计龙头"},
    {"ts_code": "688099.SH", "symbol": "688099", "name": "晶晨股份",
     "factor_value": 0.021, "signal_source": "模拟信号",
     "selection_reason": "多媒体SoC设计龙头"},
    {"ts_code": "002049.SZ", "symbol": "002049", "name": "紫光国微",
     "factor_value": 0.027, "signal_source": "模拟信号",
     "selection_reason": "FPGA/智能安全芯片龙头"},
    {"ts_code": "688385.SH", "symbol": "688385", "name": "复旦微电",
     "factor_value": 0.019, "signal_source": "模拟信号",
     "selection_reason": "FPGA/安全芯片设计, 高可靠领域"},
]


def _fallback_mock_signals() -> list[dict[str, Any]]:
    """兜底模拟信号"""
    rng = np.random.default_rng(42)
    result = []
    for s in _FALLBACK_SIGNALS:
        entry = dict(s)
        # 稍微扰动因子值
        noise = round(float(rng.normal(0, 0.005)), 6)
        entry["factor_value"] = round(entry.get("factor_value", 0) + noise, 6)
        result.append(entry)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 portfolio_builder.py <command> [options]")
        print("命令:")
        print("  build-lowfreq   [--signal-file PATH] [--signal-date YYYY-MM-DD]")
        print(f"                  [--capital {DEFAULT_CONSTRAINTS['capital']}] [--top-n {DEFAULT_CONSTRAINTS['top_n']}]")
        print("  recommend       显示最新组合推荐摘要")
        print("  risk            显示最新组合风险暴露")
        print("  premarket-v4    盘前组合建议 (V4版)")
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "build-lowfreq":
        PortfolioBuilder.cmd_build_lowfreq(args)
    elif cmd == "recommend":
        PortfolioBuilder.cmd_recommend(args)
    elif cmd == "risk":
        PortfolioBuilder.cmd_risk(args)
    elif cmd == "premarket-v4":
        PortfolioBuilder.cmd_premarket_v4(args)
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)
