"""ret5_ma20_gate 盘前信号生成器

基于 ret5 (5日动量) + close_gt_ma20 (收盘价在MA20上方) 门控策略，
每日[盘前]生成目标候选、观察名单和调仓建议。

用法:
    from factor_lab.live.signal_generator import Ret5Ma20GateSignalGenerator

    gen = Ret5Ma20GateSignalGenerator()
    gen.load_data(symbols, start_date="2026-06-01", end_date="2026-07-04")

    signal = gen.generate_signals(
        signal_date="2026-07-04",
        top_n=20,
        watch_n=20,
        current_positions=[{"symbol": "000001.SZ", "weight": 0.05}],
    )
"""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from factor_lab.datahub_access import read_stock_name_map

# ─── 模块路径 ──────────────────────────────────────────────
_HERE = Path(__file__).parent.parent          # factor_lab/
sys.path.insert(0, str(_HERE.parent))         # commands/  (含 strategy_lab)

CST = timezone(timedelta(hours=8))


# ═══════════════════════════════════════════════════════════
# Ret5Ma20GateSignalGenerator
# ═══════════════════════════════════════════════════════════

class Ret5Ma20GateSignalGenerator:
    """ret5 + close_gt_ma20 门控策略的盘前信号生成器

    Attributes:
        df: pd.DataFrame | None — 加载后的 K 线数据（含计算列）
    """

    def __init__(self, symbol_data_df: pd.DataFrame = None):
        self.df = symbol_data_df
        self._name_cache: dict[str, str] = {}

    def _get_stock_name(self, symbol: str) -> str:
        """根据6位代码返回 canonical DataHub 股票名称。"""
        if symbol in self._name_cache:
            return self._name_cache[symbol]
        try:
            self._name_cache.update(read_stock_name_map())
            if symbol in self._name_cache:
                return self._name_cache[symbol]
        except (FileNotFoundError, OSError, UnicodeError, ValueError, pd.errors.ParserError):
            self._name_cache[symbol] = symbol
        self._name_cache[symbol] = symbol
        return symbol

    # ── 数据加载 ──────────────────────────────────────────

    def load_data(self, symbols: list, start_date: str, end_date: str):
        """加载 K 线数据，计算 ret5、ma20、close_gt_ma20

        参数:
            symbols: 股票代码列表
            start_date: 数据起始日（需至少早于信号日 25 个交易日）
            end_date:  数据截止日
        """
        from factor_lab.factor_engine import load_stock_kline

        df = load_stock_kline(
            symbols, start_date=start_date, end_date=end_date, min_days=60
        )
        if df.empty:
            self.df = df
            return

        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)

        # ret5 = 5 日收益率
        df["ret5"] = df.groupby("symbol", group_keys=False)["close"].transform(
            lambda x: x.pct_change(5)
        )
        # ma20 = 20 日均线
        df["ma20"] = df.groupby("symbol", group_keys=False)["close"].transform(
            lambda x: x.rolling(window=20).mean()
        )
        # close_gt_ma20 = 收盘价是否高于 MA20
        df["close_gt_ma20"] = df["close"] > df["ma20"]

        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        self.df = df

    # ── 信号生成 ──────────────────────────────────────────

    def generate_signals(
        self,
        signal_date: str = "latest",
        top_n: int = 20,
        watch_n: int = 20,
        current_positions: list = None,
    ) -> dict:
        """生成 ret5_ma20_gate 策略信号

        参数:
            signal_date:      信号日期，'latest' 自动取最近交易日，或 'YYYY-MM-DD'
            top_n:            target_candidates 数量（默认 20）
            watch_n:          watch_candidates 数量（默认 20，排在 target 之后）
            current_positions: 当前持仓 [{symbol, weight}, ...]

        返回:
            {
              'signal_date':             信号日期,
              'latest_data_date':        数据中最近交易日,
              'is_rebalance_day':        是否调仓日,
              'next_rebalance_date':     下个调仓日,
              'strategy_name':           'ret5_ma20_gate',
              'universe':                'all_watchlist',
              'total_symbols':           信号日总股票数,
              'data_status':             'ok' | 'partial' | 'failed',
              'target_candidates':       [候选],     # Top20
              'watch_candidates':        [候选],     # 21-40
              'remove_candidates':       [待移除],   # 原持仓不再满足
              'current_hold_candidates': [续持],     # 原持仓仍满足
              'risk_summary':            {风险摘要},
              'assumptions':             [假设声明],
            }
        """
        # ── 数据校验 ─────────────────────────────────
        if self.df is None or self.df.empty:
            return self._empty_result(
                signal_date=signal_date,
                data_status="failed",
                risk_warning="无数据，请先调用 load_data()",
            )

        # ── 解析 signal_date ─────────────────────────
        if signal_date == "latest":
            signal_date = self.get_latest_trading_day()
        signal_ts = pd.Timestamp(signal_date)

        available_dates = sorted(self.df["date"].unique())
        if signal_ts not in available_dates:
            # 向前取最近交易日
            past = [d for d in available_dates if d <= signal_ts]
            if past:
                signal_date = str(past[-1].date())
            else:
                return self._empty_result(
                    signal_date=str(signal_ts.date()),
                    data_status="failed",
                    risk_warning=f"信号日期 {signal_date} 在数据中无匹配交易日",
                )

        latest_data_date = str(self.df["date"].max().date())
        signal_ts = pd.Timestamp(signal_date)

        # ── 提取信号日截面 ─────────────────────────
        day_df = self.df[self.df["date"] == signal_ts].copy()
        if day_df.empty:
            return self._empty_result(
                signal_date=signal_date,
                data_status="failed",
                risk_warning=f"信号日期 {signal_date} 无截面数据",
            )

        total_raw = len(day_df)

        # ── ret5_ma20_gate 过滤 ─────────────────────
        # 条件：close_gt_ma20 > 0 (站上MA20) 且 ret5 非空
        filtered = day_df[
            (day_df["close_gt_ma20"] > 0) & day_df["ret5"].notna()
        ].copy()
        total_filtered = len(filtered)
        gate_pass_rate = round(total_filtered / total_raw, 4) if total_raw > 0 else 0.0

        # ── 状态判定（分离数据完整性与策略筛选） ──
        # data_status: 仅反映数据字段完整性
        data_status = "ok"

        # signal_status: 候选数量是否充足
        if total_filtered >= top_n:
            signal_status = "sufficient"
        elif total_filtered > 0:
            signal_status = "insufficient"
        else:
            signal_status = "empty"

        # live_readiness: 是否可用于盘前参考
        if signal_status == "sufficient":
            live_readiness = "ready"
        elif signal_status == "insufficient":
            live_readiness = "caution"
        else:
            live_readiness = "not_ready"

        # ── 按 ret5 降序排列 ─────────────────────
        filtered = filtered.sort_values("ret5", ascending=False).reset_index(drop=True)

        # ── 构建候选列表 ─────────────────────────
        def _to_candidate(row, rank):
            return {
                "symbol": str(row["symbol"]),
                "name": self._get_stock_name(str(row["symbol"])),
                "close": round(float(row["close"]), 2) if pd.notna(row["close"]) else None,
                "ret5": round(float(row["ret5"]), 6) if pd.notna(row["ret5"]) else None,
                "ma20": round(float(row["ma20"]), 2) if pd.notna(row["ma20"]) else None,
                "close_gt_ma20": bool(row["close_gt_ma20"]),
                "rank": rank,
            }

        all_candidates = [
            _to_candidate(row, i + 1)
            for i, (_, row) in enumerate(filtered.iterrows())
        ]

        target_candidates = all_candidates[:top_n]
        watch_candidates = all_candidates[top_n: top_n + watch_n]

        # ── 尾盘规则: 14:30 后禁新仓 ─────────────────
        if self._is_late_session():
            for c in target_candidates:
                c["blocked"] = True
                c["block_reason"] = "late_session"
            for c in watch_candidates:
                c["blocked"] = True
                c["block_reason"] = "late_session"

        # ── 处理 current_positions ────────────────
        remove_candidates = []
        current_hold_candidates = []

        if current_positions:
            # Top40 候选 symbol 集合
            top40_symbols = {c["symbol"] for c in all_candidates[: top_n + watch_n]}
            # 信号日所有 close_gt_ma20 == True 的 symbol
            gt_ma20_symbols = set(
                day_df.loc[day_df["close_gt_ma20"] == True, "symbol"].unique()
            )

            for pos in current_positions:
                sym = str(pos.get("symbol", ""))
                if not sym:
                    continue

                in_top40 = sym in top40_symbols
                above_ma20 = sym in gt_ma20_symbols

                if in_top40 and above_ma20:
                    # 仍在候选名单中 → 续持
                    match = [c for c in all_candidates if c["symbol"] == sym]
                    if match:
                        entry = dict(match[0])
                    else:
                        entry = {"symbol": sym}
                    entry["weight"] = pos.get("weight", 0)
                    current_hold_candidates.append(entry)
                else:
                    # 需要移除
                    reasons = []
                    if not in_top40:
                        reasons.append(f"不在 Top{top_n + watch_n} 候选名单")
                    if not above_ma20:
                        reasons.append("close_gt_ma20 为 False")
                    remove_candidates.append({
                        "symbol": sym,
                        "weight": pos.get("weight", 0),
                        "reason": "; ".join(reasons),
                    })

        # ── 风险总结 ─────────────────────────────
        risk_summary = self._build_risk_summary(day_df, filtered, data_status)

        # ── 假设声明 ─────────────────────────────
        assumptions = [
            "ret5 基于前 5 个交易日的收盘价计算（pct_change=5）",
            "MA20 基于前 20 个交易日的收盘价简单移动平均",
            "close_gt_ma20 判断为 close > MA20",
            "信号在盘前生成，基于前一日收盘数据",
            "候选按 ret5 降序排列，取 TopN 为目标候选",
        ]

        # ── 调仓日判断 ──────────────────────────
        next_rebalance = self._next_trading_day(signal_date)

        return {
            "signal_date": signal_date,
            "latest_data_date": latest_data_date,
            "is_rebalance_day": True,          # 每日盘前信号即视为调仓日
            "next_rebalance_date": next_rebalance,
            "strategy_name": "ret5_ma20_gate",
            "universe": "all_watchlist",
            "total_symbols": total_raw,
            "data_status": data_status,
            "target_candidates": target_candidates,
            "watch_candidates": watch_candidates,
            "remove_candidates": remove_candidates,
            "current_hold_candidates": current_hold_candidates,
            "risk_summary": risk_summary,
            "assumptions": assumptions,
            "gate_pass_rate": gate_pass_rate,
            "signal_status": signal_status,
            "live_readiness": live_readiness,
        }

    # ── 辅助方法 ────────────────────────────────────────

    def get_latest_trading_day(self) -> str:
        """获取数据中最近一个交易日"""
        if self.df is None or self.df.empty:
            return datetime.now(CST).strftime("%Y-%m-%d")
        return str(pd.Timestamp(self.df["date"].max()).date())

    # ── 内部工具 ─────────────────────────────────────────

    @staticmethod
    def _get_symbols_for_universe(universe_name: str = "all_watchlist") -> list:
        """从 universe 构建器加载股票列表

        参数:
            universe_name: 股票池名称（默认 'all_watchlist' = manual_watchlist + today_candidates）
        返回:
            sorted list of symbol strings
        """
        from strategy_lab.universe import build

        if universe_name == "all_watchlist":
            pool = set()
            for u_name in ["manual_watchlist", "today_candidates"]:
                try:
                    stocks, meta = build(u_name)
                    for s in stocks:
                        pool.add(s["symbol"])
                except Exception:
                    continue
            return sorted(pool)

        try:
            stocks, meta = build(universe_name)
            return [s["symbol"] for s in stocks]
        except Exception:
            return []

    @staticmethod
    def _next_trading_day(date_str: str) -> str:
        """返回下一个交易日（'YYYY-MM-DD'）"""
        from pandas.tseries.offsets import BDay

        ts = pd.Timestamp(date_str)
        return str((ts + BDay(1)).date())

    @staticmethod
    def _build_risk_summary(
        day_df: pd.DataFrame,
        filtered: pd.DataFrame,
        data_status: str,
    ) -> dict:
        """生成风险摘要"""
        warnings = []

        if data_status == "failed":
            warnings.append("数据加载失败或信号日期无数据")
        elif data_status == "partial":
            total = len(day_df)
            valid = len(filtered)
            if total > 0:
                warnings.append(
                    f"有效信号比例较低: {valid}/{total} "
                    f"({valid / total * 100:.1f}%) 通过门控过滤"
                )

        # ret5 缺失
        if "ret5" in day_df.columns:
            ret5_null = int(day_df["ret5"].isna().sum())
            if ret5_null > 0:
                warnings.append(f"{ret5_null} 只股票 ret5 为空（数据不足）")

        # MA20 缺失
        if "ma20" in day_df.columns:
            ma20_null = int(day_df["ma20"].isna().sum())
            if ma20_null > 0:
                warnings.append(f"{ma20_null} 只股票 MA20 为空（数据不足）")

        # close_gt_ma20 比例
        if "close_gt_ma20" in day_df.columns:
            above_ma20 = int(day_df["close_gt_ma20"].sum())
            total = len(day_df)
            if total > 0:
                pct_above = above_ma20 / total * 100
                if pct_above < 30:
                    warnings.append(
                        f"仅 {pct_above:.1f}% 股票在 MA20 上方，市场偏弱"
                    )

        return {
            "warnings": warnings,
            "n_warnings": len(warnings),
        }

    # ── 尾盘规则 ─────────────────────────────────────────

    @staticmethod
    def _is_late_session() -> bool:
        """检查当前是否在尾盘时段 (14:30 后)

        A 股交易时间为 9:30-11:30, 13:00-15:00。
        14:30 后禁新仓: 距收盘不足 30 分钟, 避免隔夜风险。

        Returns:
            True 如果当前时间 >= 14:30 CST
        """
        now = datetime.now(CST)
        cutoff = now.replace(hour=14, minute=30, second=0, microsecond=0)
        return now >= cutoff

    # ── 内部工具 ─────────────────────────────────────────

    @staticmethod
    def _empty_result(
        signal_date: str,
        data_status: str = "failed",
        risk_warning: str = "",
    ) -> dict:
        """返回空结果（失败兜底）"""
        warnings = [risk_warning] if risk_warning else []
        return {
            "signal_date": signal_date,
            "latest_data_date": "",
            "is_rebalance_day": False,
            "next_rebalance_date": "",
            "strategy_name": "ret5_ma20_gate",
            "universe": "all_watchlist",
            "total_symbols": 0,
            "data_status": data_status,
            "target_candidates": [],
            "watch_candidates": [],
            "remove_candidates": [],
            "current_hold_candidates": [],
            "risk_summary": {
                "warnings": warnings,
                "n_warnings": len(warnings),
            },
            "assumptions": [],
        }


# ═══════════════════════════════════════════════════════════
# 便捷入口
# ═══════════════════════════════════════════════════════════

def run_ret5_ma20_gate_signal(
    signal_date: str = "latest",
    top_n: int = 20,
    watch_n: int = 20,
    current_positions: list = None,
    start_date: str = None,
    end_date: str = None,
) -> dict:
    """一键生成 ret5_ma20_gate 信号

    加载 all_watchlist 股票池 → 获取 K 线 → 生成信号。

    参数:
        signal_date:       信号日期（默认 'latest' → 最近交易日）
        top_n:             目标候选数
        watch_n:           观察候选数
        current_positions: 当前持仓 [{symbol, weight}, ...]
        start_date:        数据起始日（默认 signal_date 往前 120 天，确保 MA20 和 min_days 过滤通过）
        end_date:          数据截止日（默认 signal_date 或今天）

    返回:
        generate_signals() 的完整 dict
    """
    gen = Ret5Ma20GateSignalGenerator()

    # 确定日期范围
    if end_date is None:
        end_date = datetime.now(CST).strftime("%Y-%m-%d")
    if start_date is None:
        ref = (
            signal_date if signal_date != "latest"
            else end_date
        )
        # 需要 ~120 天以保证 60 个以上交易日满足 min_days=60 过滤
        padding = pd.Timestamp(ref) - pd.Timedelta(days=120)
        start_date = str(padding.date())

    # 加载股票池
    symbols = Ret5Ma20GateSignalGenerator._get_symbols_for_universe("all_watchlist")
    if not symbols:
        return gen._empty_result(
            signal_date=signal_date,
            data_status="failed",
            risk_warning="股票池为空（all_watchlist 无股票）",
        )

    # 加载 K 线
    gen.load_data(symbols, start_date=start_date, end_date=end_date)

    # 生成信号
    return gen.generate_signals(
        signal_date=signal_date,
        top_n=top_n,
        watch_n=watch_n,
        current_positions=current_positions,
    )
