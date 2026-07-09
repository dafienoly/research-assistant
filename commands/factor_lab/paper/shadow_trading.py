"""V4.8 ShadowTradingEngine — 影子交易闭环

与 PaperTradingV4 的区别:
  - 不产生真实持仓 (只观察)
  - 对比: 策略计划 vs 真实行情
  - 统计: 实际可买/可卖/风控拦截
  - 输出: 相对半导体同池等权表现
  - 输出: 风控拦截次数和原因

用法:
    from factor_lab.paper.shadow_trading import ShadowTradingEngine
    engine = ShadowTradingEngine(capital=50000)
    report = engine.run_shadow("2026-07-08")
    print(report["summary"])
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from factor_lab.paper.standing_paper_trading import PaperTradingV4
from factor_lab.risk.pretrade_risk_check import (
    _is_limit_up, _is_limit_down, _is_suspended,
)

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))
BASE = Path(__file__).resolve().parent.parent.parent  # commands/
OUTPUT_DIR = Path("/mnt/d/HermesReports/shadow_v4")


# ═══════════════════════════════════════════════════════════════════════════════
# ShadowTradingEngine
# ═══════════════════════════════════════════════════════════════════════════════

class ShadowTradingEngine:
    """V4.8 Shadow Trading Engine — 影子交易闭环

    影子交易只观察不交易，比较策略组合计划 vs 真实行情:
      - 哪些可买/可卖/被风控拦截
      - 相对半导体同池等权表现
      - 风控拦截原因统计
      - 跑输同池标记 NOT_READY
    """

    # 半导体等权基准名称
    BENCHMARK_NAME = "semiconductor_ew"

    def __init__(self, capital: float = 50000.0,
                 top_n: int = 10):
        """
        Args:
            capital: 观察资金
            top_n: 组合目标数量
        """
        self.capital = capital
        self.top_n = top_n
        self._paper_engine: Optional[PaperTradingV4] = None
        self._benchmark_cache: Optional[pd.Series] = None

    # ── 懒加载 ──────────────────────────────────────────────────────────────

    @property
    def paper_engine(self) -> PaperTradingV4:
        if self._paper_engine is None:
            self._paper_engine = PaperTradingV4(capital=self.capital)
        return self._paper_engine

    # ── 核心流程 ─────────────────────────────────────────────────────────────

    def run_shadow(
        self,
        date: str,
        factor_signals: Optional[list[dict]] = None,
        market_data: Optional[pd.DataFrame] = None,
        constraints: Optional[dict] = None,
    ) -> dict:
        """运行当日影子交易观察

        Args:
            date: 交易日 YYYY-MM-DD
            factor_signals: 因子信号列表 (None 则使用默认模拟信号)
            market_data: 市场数据 DataFrame (含 date/symbol/close/prev_close/volume)
            constraints: 组合约束覆盖

        Returns:
            {
                "date": str,
                "plan": { 组合计划 } ,
                "tradability": { 可交易统计 } ,
                "risk_interceptions": { 风控拦截统计 },
                "market_context": { 市场行情概况 } ,
                "performance": { 相对基准表现 } ,
                "not_ready": bool,  # 跑输同池基准 = True
                "summary": { 一句话摘要 } ,
            }
        """
        constraints = constraints or {}
        if "capital" not in constraints:
            constraints["capital"] = self.capital
        if "top_n" not in constraints:
            constraints["top_n"] = self.top_n

        # Step 1: 运行 Paper Trading 获取完整结果
        paper_result = self.paper_engine.run_paper(
            date, factor_signals, constraints, market_data
        )

        # Step 2: 可交易统计
        tradability = self._analyze_tradability(paper_result)

        # Step 3: 风控拦截统计
        risk_interceptions = self._analyze_risk_interceptions(paper_result)

        # Step 4: 市场行情概况
        market_context = self._build_market_context(date, market_data)

        # Step 5: 相对半导体等权基准表现
        performance = self._calc_relative_performance(
            date, paper_result["pnl"], market_data
        )

        # Step 6: NOT_READY 判断
        not_ready = self._check_not_ready(performance)

        # Step 7: 摘要
        summary = self._build_summary(
            date, tradability, risk_interceptions, performance, not_ready
        )

        return {
            "date": date,
            "plan": paper_result["plan"],
            "execution": paper_result["execution"],
            "pnl": paper_result["pnl"],
            "tradability": tradability,
            "risk_interceptions": risk_interceptions,
            "market_context": market_context,
            "performance": performance,
            "not_ready": not_ready,
            "summary": summary,
        }

    # ── 可交易统计 ─────────────────────────────────────────────────────────

    def _analyze_tradability(self, paper_result: dict) -> dict:
        """分析组合计划中各标的的实际可交易性"""
        plan = paper_result.get("plan", {})
        stocks = plan.get("stocks", [])
        tradability_check = paper_result.get("tradability_check", {})

        n_total = len(stocks)
        n_plannable = tradability_check.get("plannable", 0)
        n_blocked = tradability_check.get("blocked", 0)

        # 按板块统计受阻
        blocked_by_reason: dict[str, int] = {}
        for detail in tradability_check.get("details", []):
            if not detail.get("plannable", True):
                for reason in detail.get("reasons", []):
                    blocked_by_reason[reason] = blocked_by_reason.get(reason, 0) + 1

        # 按可交易状态分
        tradable_stocks = [s for s in stocks if s.get("is_tradable", False)]
        non_tradable_stocks = [s for s in stocks if not s.get("is_tradable", False)]

        return {
            "n_total": n_total,
            "n_tradable_planned": len(tradable_stocks),
            "n_non_tradable_planned": len(non_tradable_stocks),
            "n_check_plannable": n_plannable,
            "n_check_blocked": n_blocked,
            "tradable_weight_pct": round(sum(s.get("weight", 0) for s in tradable_stocks) * 100, 2) if tradable_stocks else 0,
            "blocked_by_reason": blocked_by_reason,
            "details": [{
                "symbol": s["symbol"],
                "name": s.get("name", ""),
                "is_tradable": s.get("is_tradable", False),
                "weight_pct": round(s.get("weight", 0) * 100, 2),
                "block_reasons": s.get("block_reasons", []),
            } for s in stocks],
        }

    # ── 风控拦截统计 ──────────────────────────────────────────────────────

    def _analyze_risk_interceptions(self, paper_result: dict) -> dict:
        """分析风控拦截原因统计"""
        interceptions = paper_result.get("risk_interceptions", [])

        total = len(interceptions)
        by_reason: dict[str, int] = {}
        by_stage: dict[str, int] = {}
        distinct_symbols: set[str] = set()

        for r in interceptions:
            reason = r.get("reason", "unknown")
            stage = r.get("stage", "unknown")
            by_reason[reason] = by_reason.get(reason, 0) + 1
            by_stage[stage] = by_stage.get(stage, 0) + 1
            distinct_symbols.add(r.get("symbol", ""))

        return {
            "total_interceptions": total,
            "distinct_symbols_blocked": len(distinct_symbols),
            "by_reason": by_reason,
            "by_stage": by_stage,
            "details": interceptions,
        }

    # ── 市场行情概况 ──────────────────────────────────────────────────────

    def _build_market_context(self, date: str,
                               market_data: Optional[pd.DataFrame] = None) -> dict:
        """构建当日市场行情概况"""
        context: dict[str, Any] = {
            "date": date,
        }

        if market_data is not None and "date" in market_data.columns:
            day_data = market_data[market_data["date"] == date]
            if not day_data.empty:
                closes = day_data["close"].dropna()
                volumes = day_data["volume"].dropna() if "volume" in day_data.columns else pd.Series(dtype=float)

                context.update({
                    "n_stocks_available": len(day_data),
                    "avg_close": round(float(closes.mean()), 2),
                    "median_close": round(float(closes.median()), 2),
                    "close_std": round(float(closes.std()), 2),
                    "total_volume": round(float(volumes.sum()), 0) if not volumes.empty else 0,
                    "n_up": int((day_data.get("close", 0) > day_data.get("prev_close", 0)).sum())
                    if "prev_close" in day_data.columns else None,
                    "n_down": int((day_data.get("close", 0) < day_data.get("prev_close", 0)).sum())
                    if "prev_close" in day_data.columns else None,
                })

        return context

    # ── 相对基准表现 ──────────────────────────────────────────────────────

    def _calc_relative_performance(
        self,
        date: str,
        pnl: dict,
        market_data: Optional[pd.DataFrame] = None,
    ) -> dict:
        """计算组合相对半导体等权基准的表现"""
        # 组合收益
        strategy_return_pct = pnl.get("total_return_pct", 0.0)

        # 获取基准收益
        benchmark_return_pct = self._get_benchmark_return_for_date(date, market_data)

        # 超额收益 (主动收益)
        excess_return_pct = strategy_return_pct - benchmark_return_pct if benchmark_return_pct is not None else 0.0

        # 同池对比依据
        vs_benchmark = "跑赢" if excess_return_pct >= 0 else "跑输"

        return {
            "date": date,
            "strategy_return_pct": round(strategy_return_pct, 4),
            "benchmark_name": self.BENCHMARK_NAME,
            "benchmark_label": "半导体同池等权",
            "benchmark_return_pct": round(benchmark_return_pct, 4) if benchmark_return_pct is not None else None,
            "excess_return_pct": round(excess_return_pct, 4) if benchmark_return_pct is not None else None,
            "vs_benchmark": vs_benchmark,
        }

    def _get_benchmark_return_for_date(
        self,
        date: str,
        market_data: Optional[pd.DataFrame] = None,
    ) -> Optional[float]:
        """获取指定日期半导体同池等权收益率

        使用 benchmarks_v4.get_benchmark_returns。
        """
        # 尝试使用已有基准模块
        try:
            from benchmarks_v4 import get_benchmark_returns
            rets = get_benchmark_returns(self.BENCHMARK_NAME)

            if rets is not None and not rets.empty:
                # 找到目标日期
                target_date = pd.Timestamp(date)
                if target_date in rets.index:
                    return float(rets.loc[target_date])

                # 找最近日期
                valid_dates = rets.index[rets.index <= target_date]
                if len(valid_dates) > 0:
                    closest = valid_dates[-1]
                    return float(rets.loc[closest])

            # 基准数据不可用 — 从 market_data 估算
            logger.warning(f"基准数据不可用, 尝试从 market_data 估算 (date={date})")
            return self._estimate_benchmark_from_data(date, market_data)

        except (ImportError, FileNotFoundError, Exception) as e:
            logger.warning(f"加载基准 {self.BENCHMARK_NAME} 失败: {e}")
            return self._estimate_benchmark_from_data(date, market_data)

    def _estimate_benchmark_from_data(
        self,
        date: str,
        market_data: Optional[pd.DataFrame] = None,
    ) -> Optional[float]:
        """从半导体同池标的估算等权收益率"""
        if market_data is None or "date" not in market_data.columns:
            return None

        try:
            from benchmarks_v4 import _get_universe_codes
            codes = _get_universe_codes("U3")
        except Exception:
            return None

        if not codes:
            return None

        day_data = market_data[market_data["date"] == date]
        if day_data.empty:
            return None

        # 只取 pool 中的标的
        pool_data = day_data[day_data["symbol"].isin(codes)]
        if pool_data.empty:
            return None

        # 等权平均日收益率
        rets = []
        for _, row in pool_data.iterrows():
            close = row.get("close", 0)
            prev_close = row.get("prev_close", row.get("pre_close", 0))
            if prev_close > 0:
                rets.append((close - prev_close) / prev_close)

        return float(np.mean(rets)) if rets else None

    # ── NOT_READY 判断 ────────────────────────────────────────────────────

    def _check_not_ready(self, performance: dict) -> bool:
        """若跑输同池基准 = NOT_READY"""
        excess = performance.get("excess_return_pct")
        if excess is None:
            return True  # 无基准数据默认 NOT_READY
        return excess < 0

    # ── 摘要 ──────────────────────────────────────────────────────────────

    def _build_summary(
        self,
        date: str,
        tradability: dict,
        risk_interceptions: dict,
        performance: dict,
        not_ready: bool,
    ) -> str:
        """生成一句话摘要"""
        parts = [
            f"📅 {date}",
            f"计划{tradability['n_total']}只",
            f"可交易{tradability['n_tradable_planned']}只",
            f"受阻{tradability['n_check_blocked']}只",
        ]

        if risk_interceptions["total_interceptions"] > 0:
            parts.append(f"风控拦截{risk_interceptions['total_interceptions']}次")

        bm_ret = performance.get("benchmark_return_pct")
        st_ret = performance.get("strategy_return_pct")
        if bm_ret is not None:
            parts.append(f"策略{st_ret:+.2f}%")
            parts.append(f"基准{bm_ret:+.2f}%")
            parts.append(performance.get("vs_benchmark", ""))

        if not_ready:
            parts.append("⚠️ NOT_READY")

        return " | ".join(parts)

    # ── 批量运行 ──────────────────────────────────────────────────────────

    def run_shadow_multi(
        self,
        dates: list[str],
        factor_signals: Optional[list[dict]] = None,
        market_data: Optional[pd.DataFrame] = None,
        constraints: Optional[dict] = None,
    ) -> list[dict]:
        """批量运行多日影子交易"""
        results = []
        for date in dates:
            result = self.run_shadow(date, factor_signals, market_data, constraints)
            results.append(result)
            logger.info(f"[Shadow] {date}: {result['summary']}")
        return results

    # ── 汇总报告 ──────────────────────────────────────────────────────────

    @staticmethod
    def build_report(results: list[dict]) -> dict:
        """从多日运行结果生成汇总报告"""
        if not results:
            return {"status": "error", "message": "无运行结果"}

        n_days = len(results)

        # 每日摘要
        daily_summaries = []
        for r in results:
            daily_summaries.append({
                "date": r["date"],
                "summary": r["summary"],
                "not_ready": r.get("not_ready", True),
                "strategy_return_pct": r.get("performance", {}).get("strategy_return_pct"),
                "benchmark_return_pct": r.get("performance", {}).get("benchmark_return_pct"),
                "excess_return_pct": r.get("performance", {}).get("excess_return_pct"),
                "n_blocked": r.get("tradability", {}).get("n_check_blocked", 0),
                "n_interceptions": r.get("risk_interceptions", {}).get("total_interceptions", 0),
            })

        # 聚合统计
        not_ready_days = sum(1 for r in results if r.get("not_ready", True))

        # 聚合风控统计
        all_risk_reasons: dict[str, int] = {}
        for r in results:
            for reason, count in r.get("risk_interceptions", {}).get("by_reason", {}).items():
                all_risk_reasons[reason] = all_risk_reasons.get(reason, 0) + count

        # 聚合基准 vs 策略
        perf_entries = [r.get("performance", {}) for r in results if r.get("performance")]
        strategy_rets = [p.get("strategy_return_pct", 0) for p in perf_entries if p.get("strategy_return_pct") is not None]
        benchmark_rets = [p.get("benchmark_return_pct", 0) for p in perf_entries if p.get("benchmark_return_pct") is not None]
        excess_rets = [p.get("excess_return_pct", 0) for p in perf_entries if p.get("excess_return_pct") is not None]

        avg_strategy_ret = np.mean(strategy_rets) if strategy_rets else None
        avg_benchmark_ret = np.mean(benchmark_rets) if benchmark_rets else None
        avg_excess_ret = np.mean(excess_rets) if excess_rets else None
        win_rate = (sum(1 for e in excess_rets if e > 0) / len(excess_rets) * 100) if excess_rets else None

        # 累计收益
        cum_strategy = (1 + np.array(strategy_rets) / 100).prod() - 1 if strategy_rets else None
        cum_benchmark = (1 + np.array(benchmark_rets) / 100).prod() - 1 if benchmark_rets else None

        # 计划 vs 实际差异
        total_planned = sum(
            r.get("tradability", {}).get("n_total", 0) for r in results
        )
        total_filled = sum(
            r.get("execution", {}).get("n_filled", 0) for r in results
        )

        return {
            "status": "success",
            "n_days": n_days,
            "date_range": f"{results[0]['date']} ~ {results[-1]['date']}",
            "strategy_name": "V4.8 低频组合策略",
            "benchmark_name": "semiconductor_ew",
            "benchmark_label": "半导体同池等权",

            # 收益表现
            "avg_strategy_return_pct": round(avg_strategy_ret, 4) if avg_strategy_ret is not None else None,
            "avg_benchmark_return_pct": round(avg_benchmark_ret, 4) if avg_benchmark_ret is not None else None,
            "avg_excess_return_pct": round(avg_excess_ret, 4) if avg_excess_ret is not None else None,
            "cumulative_strategy_return_pct": round(cum_strategy * 100, 4) if cum_strategy is not None else None,
            "cumulative_benchmark_return_pct": round(cum_benchmark * 100, 4) if cum_benchmark is not None else None,
            "excess_cumulative_pct": round((cum_strategy - cum_benchmark) * 100, 4) if (cum_strategy is not None and cum_benchmark is not None) else None,
            "win_rate_pct": round(win_rate, 2) if win_rate is not None else None,

            # 风控统计
            "total_risk_interceptions": sum(
                r.get("risk_interceptions", {}).get("total_interceptions", 0) for r in results
            ),
            "avg_risk_interceptions_per_day": round(
                sum(r.get("risk_interceptions", {}).get("total_interceptions", 0) for r in results) / n_days,
                2,
            ) if n_days > 0 else 0,
            "risk_interception_reasons": all_risk_reasons,
            "avg_blocked_per_day": round(
                sum(r.get("tradability", {}).get("n_check_blocked", 0) for r in results) / n_days,
                2,
            ) if n_days > 0 else 0,

            # 执行质量
            "total_planned_stocks": total_planned,
            "total_filled_stocks": total_filled,
            "overall_fill_rate_pct": round(total_filled / total_planned * 100, 2) if total_planned > 0 else 0,

            # NOT_READY
            "not_ready_days": not_ready_days,
            "not_ready_days_pct": round(not_ready_days / n_days * 100, 2) if n_days > 0 else 0,
            "status": "NOT_READY" if not_ready_days > n_days / 2 else "READY",

            # 每日明细
            "daily_summaries": daily_summaries,
        }

    # ── CLI 入口 ──────────────────────────────────────────────────────────

    @staticmethod
    def cmd_v4_run(args: list[str]):
        """CLI: shadow:v4-run"""
        import sys
        from datetime import datetime

        date = ""
        capital = 50000.0
        top_n = 10

        for i, a in enumerate(args):
            if a == "--date" and i + 1 < len(args):
                date = args[i + 1]
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

        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        engine = ShadowTradingEngine(capital=capital, top_n=top_n)
        result = engine.run_shadow(date)

        print(f"\n👁️  V4.8 Shadow Trading — {date}")
        print(f"{'=' * 50}")
        print(f"  观察资金: {capital:,.0f}")
        print(f"  目标数量: {top_n}")
        print()
        print(f"  {result['summary']}")
        print()

        # 可交易性
        trad = result["tradability"]
        print(f"━━━ 可交易性 ━━━")
        print(f"  计划: {trad['n_total']} 只  |  可交易: {trad['n_tradable_planned']} 只  |  受阻: {trad['n_check_blocked']} 只")
        print()

        # 风控拦截原因
        risk_info = result["risk_interceptions"]
        if risk_info["total_interceptions"] > 0:
            print(f"━━━ 风控拦截 ({risk_info['total_interceptions']} 次) ━━━")
            for reason, count in sorted(risk_info["by_reason"].items(), key=lambda x: -x[1]):
                print(f"  🛑 {reason}: {count} 次")
            print()

        # 相对基准
        perf = result["performance"]
        print(f"━━━ 相对基准表现 ━━━")
        print(f"  策略收益: {perf['strategy_return_pct']:+.4f}%")
        if perf.get("benchmark_return_pct") is not None:
            print(f"  基准收益 ({perf['benchmark_label']}): {perf['benchmark_return_pct']:+.4f}%")
            print(f"  超额收益: {perf['excess_return_pct']:+.4f}%")
            print(f"  对比: {perf['vs_benchmark']}")
        print()

        # NOT_READY
        if result["not_ready"]:
            print(f"  ⚠️  NOT_READY: 策略跑输半导体同池等权")
            print()

        return result

    @staticmethod
    def cmd_v4_report(args: list[str]):
        """CLI: shadow:v4-report — 多日影子交易报告"""
        import json
        from pathlib import Path

        # 查找最新的结果
        if not OUTPUT_DIR.exists():
            print("❌ 无历史 Shadow 记录")
            return

        files = sorted(OUTPUT_DIR.glob("shadow_v4_*.json"), reverse=True)
        if not files:
            print("❌ 无历史 Shadow 记录文件")
            return

        latest_file = files[0]

        # 允许多文件合并
        report_type = ""
        for i, a in enumerate(args):
            if a == "--file" and i + 1 < len(args):
                p = Path(args[i + 1])
                if p.exists():
                    latest_file = p
            elif a == "--from-dir" and i + 1 < len(args):
                dp = Path(args[i + 1])
                if dp.exists():
                    files = sorted(dp.glob("shadow_v4_*.json"), reverse=True)
                    if files:
                        latest_file = files[0]

        with open(latest_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            report = ShadowTradingEngine.build_report(data)
        else:
            # 单日 — 用列表包裹
            report = ShadowTradingEngine.build_report([data])

        print(f"\n📊 V4.8 Shadow Trading 报告")
        print(f"{'=' * 55}")
        print(f"  日期范围: {report.get('date_range', 'N/A')}")
        print(f"  策略: {report.get('strategy_name', 'N/A')}")
        print(f"  基准: {report.get('benchmark_label', 'N/A')}")
        print(f"  状态: {report.get('status', 'N/A')}")
        print()
        print(f"━━━ 收益表现 ━━━")
        if report.get("avg_strategy_return_pct") is not None:
            print(f"  策略(日均): {report['avg_strategy_return_pct']:+.4f}%")
        if report.get("avg_benchmark_return_pct") is not None:
            print(f"  基准(日均): {report['avg_benchmark_return_pct']:+.4f}%")
        if report.get("avg_excess_return_pct") is not None:
            print(f"  超额(日均): {report['avg_excess_return_pct']:+.4f}%")
        if report.get("cumulative_strategy_return_pct") is not None:
            print(f"  策略累计: {report['cumulative_strategy_return_pct']:+.4f}%")
        if report.get("cumulative_benchmark_return_pct") is not None:
            print(f"  基准累计: {report['cumulative_benchmark_return_pct']:+.4f}%")
        if report.get("excess_cumulative_pct") is not None:
            print(f"  超额累计: {report['excess_cumulative_pct']:+.4f}%")
        if report.get("win_rate_pct") is not None:
            print(f"  胜率: {report['win_rate_pct']:.2f}%")
        print()
        print(f"━━━ 风控统计 ━━━")
        print(f"  总拦截次数: {report.get('total_risk_interceptions', 0)}")
        print(f"  日均拦截: {report.get('avg_risk_interceptions_per_day', 0):.2f}")
        print(f"  日均受阻: {report.get('avg_blocked_per_day', 0):.2f}")
        print(f"  风控原因:")
        for reason, count in sorted(report.get("risk_interception_reasons", {}).items(), key=lambda x: -x[1]):
            print(f"    🛑 {reason}: {count} 次")
        print()
        print(f"━━━ NOT_READY 统计 ━━━")
        print(f"  达标天数: {report.get('n_days', 0) - report.get('not_ready_days', 0)}/{report.get('n_days', 0)}")
        print(f"  NOT_READY 占比: {report.get('not_ready_days_pct', 0):.2f}%")
        print()

        return report
