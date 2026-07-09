#!/usr/bin/env python3
"""
V4.3 基准体系 — 半导体同池等权与对照基准

提供6个核心基准的日收益率计算:
  - semiconductor_ew:     半导体300池等权收益率 (U3)
  - semiconductor_core_ew: 半导体核心池等权收益率 (U3 别名)
  - matched_control_ew:    匹配对照池等权收益率 (U4)
  - ew_a_share:            全A等权收益率 (U0)
  - ew_tradable:           全A可交易池等权收益率 (U1 tradable)
  - etf_basket_ew:         ETF替代池等权收益率 (ETF)

数据来源: /mnt/c/Users/ly/.codex/data/a-share-data-hub/market/daily_kline/
交易日历对齐: universes 中的交易日 (从 universes.json 或 Tushare trade_cal 获取)

用法:
    from benchmarks_v4 import list_benchmarks, get_benchmark_returns
    rets = get_benchmark_returns("semiconductor_ew")
    print(rets.tail())
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))

# ─── 路径 ────────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent  # research-assistant/
DATA_DIR = BASE / "data"
UNIVERSES_FILE = DATA_DIR / "universes.json"
# A 股日K线数据目录 (从 Windows Codex data hub 读取)
KLINE_DIR = Path("/mnt/c/Users/ly/.codex/data/a-share-data-hub/market/daily_kline")

# ─── 基准定义 ────────────────────────────────────────────────────────────
BENCHMARK_META = {
    "semiconductor_ew": {
        "name": "半导体等权",
        "label": "半导体300池等权收益率",
        "universe": "U3",
        "description": "U3 半导体核心池内所有标的等权组合日收益率",
    },
    "semiconductor_core_ew": {
        "name": "半导体核心等权",
        "label": "半导体核心池等权收益率",
        "universe": "U3",
        "description": "U3 半导体核心池等权组合日收益率 (与 semiconductor_ew 相同)",
    },
    "matched_control_ew": {
        "name": "匹配对照等权",
        "label": "匹配对照池等权收益率",
        "universe": "U4",
        "description": "U4 匹配对照池内所有标的等权组合日收益率",
    },
    "ew_a_share": {
        "name": "全A等权",
        "label": "全A等权收益率",
        "universe": "U0",
        "description": "U0 全A基础池所有标的等权组合日收益率",
    },
    "ew_tradable": {
        "name": "可交易等权",
        "label": "全A可交易池等权收益率",
        "universe": "U1",
        "description": "U1 中标记为 tradable_by_user=True 的标的等权组合日收益率",
    },
    "etf_basket_ew": {
        "name": "ETF替代池等权",
        "label": "ETF替代池等权收益率",
        "universe": "ETF",
        "description": "ETF 替代池内所有 ETF 的等权组合日收益率",
    },
}

VALID_BENCHMARK_NAMES = set(BENCHMARK_META.keys())

# ─── 辅助函数 ────────────────────────────────────────────────────────────


def _load_universes() -> dict:
    """加载 universes.json"""
    if not UNIVERSES_FILE.exists():
        raise FileNotFoundError(
            f"universes.json 不存在, 请先运行 universe:build\n"
            f"  python3 hermes_cli.py universe:build"
        )
    with open(UNIVERSES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_universe_codes(universe_name: str) -> list[str]:
    """从 universes.json 获取指定池的所有标的代码 (symbol 格式, 6位数字)

    Returns:
        ["688012", "688981", ...]  — 含 6 位数字代码
    """
    data = _load_universes()

    # U1_TRADABLE: U1 的子集, 不是 universes.json 中的独立池
    if universe_name == "U1_TRADABLE":
        u1 = data.get("universes", {}).get("U1", {})
        codes: list[str] = []
        for s in u1.get("stocks", []):
            if s.get("tradable_by_user", False):
                ts_code = s.get("ts_code", "")
                symbol = ts_code.split(".")[0] if "." in ts_code else ts_code
                if symbol:
                    codes.append(symbol)
        return sorted(set(codes))

    universe = data.get("universes", {}).get(universe_name)
    if not universe:
        raise KeyError(f"未找到股票池: {universe_name}")

    stocks = universe.get("stocks", [])
    codes: list[str] = []

    if universe_name in ("U0", "U1", "U2", "U3"):
        for s in stocks:
            ts_code = s.get("ts_code", "")
            symbol = ts_code.split(".")[0] if "." in ts_code else ts_code
            if symbol:
                codes.append(symbol)

    elif universe_name == "U4":
        # U4 结构: stock 有 matched_stocks (list)
        for s in stocks:
            for m in s.get("matched_stocks", []):
                ts_code = m.get("ts_code", "")
                symbol = ts_code.split(".")[0] if "." in ts_code else ts_code
                if symbol:
                    codes.append(symbol)

    elif universe_name == "U1_TRADABLE":
        # U1 中 tradable_by_user=True 的标的
        u1 = data.get("universes", {}).get("U1", {})
        stocks = u1.get("stocks", u1.get("members", u1.get("items", [])))
        for s in stocks:
            if isinstance(s, dict) and s.get("tradable_by_user", False):
                symbol = s.get("symbol") or s.get("ts_code", "")
                if symbol:
                    codes.append(symbol)

    elif universe_name == "ETF":
        for s in stocks:
            ts_code = s.get("ts_code", "")
            symbol = ts_code.split(".")[0] if "." in ts_code else ts_code
            if symbol:
                codes.append(symbol)

    return sorted(set(codes))


def _load_kline_for_codes(codes: list[str],
                           start_date: Optional[str] = None,
                           end_date: Optional[str] = None,
                           max_codes: int = 1000) -> pd.DataFrame:
    """加载指定股票代码的日K线数据

    对于大型池(如 U0 全A), 会限制最大数量以避免读过多文件。

    Args:
        codes: 股票代码列表 (6位数字)
        start_date: "YYYY-MM-DD" 或 "YYYYMMDD"
        end_date: "YYYY-MM-DD" 或 "YYYYMMDD"
        max_codes: 最大读取的股票数 (默认 1000, None=不限制)

    Returns:
        DataFrame with columns: date, symbol, close
    """
    if not codes:
        logger.warning("股票代码列表为空, 返回空 DataFrame")
        return pd.DataFrame(columns=["date", "symbol", "close"])

    # 限制最大数量
    limited_codes = codes
    if max_codes is not None and len(codes) > max_codes:
        limited_codes = sorted(codes)[:max_codes]
        logger.info(f"代码列表从 {len(codes)} 限制到 {max_codes} 只")

    all_rows: list[dict] = []

    for code in limited_codes:
        csv_path = KLINE_DIR / f"{code}.csv"
        if not csv_path.exists():
            continue
        try:
            df = pd.read_csv(
                csv_path,
                dtype={"code": str},
                parse_dates=["date"],
                usecols=["code", "date", "close"],
            )
            if df.empty:
                continue
            df = df.rename(columns={"code": "symbol"})
            df["symbol"] = df["symbol"].astype(str).str.strip()
            all_rows.append(df)
        except Exception as e:
            logger.debug(f"读取 {csv_path} 失败: {e}")
            continue

    if not all_rows:
        logger.warning(f"未能读取任何K线数据 (codes 示例: {codes[:3]})")
        return pd.DataFrame(columns=["date", "symbol", "close"])

    result = pd.concat(all_rows, ignore_index=True)

    # 日期过滤
    if start_date:
        if len(start_date) == 8:
            start_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        result = result[result["date"] >= start_date]
    if end_date:
        if len(end_date) == 8:
            end_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
        result = result[result["date"] <= end_date]

    result = result.sort_values(["date", "symbol"]).reset_index(drop=True)
    return result[["date", "symbol", "close"]]


def _compute_equal_weight_returns(codes: list[str],
                                    start_date: Optional[str] = None,
                                    end_date: Optional[str] = None) -> pd.Series:
    """计算等权组合日收益率

    Args:
        codes: 股票代码列表
        start_date: 起始日期
        end_date: 截止日期

    Returns:
        pd.Series of daily returns, index=DatetimeIndex
    """
    if not codes:
        logger.warning("codes 为空, 返回空 Series")
        return pd.Series(dtype=float)

    kline = _load_kline_for_codes(codes, start_date, end_date)
    if kline.empty:
        logger.warning(f"K线数据为空 (codes={len(codes)}), 返回空 Series")
        return pd.Series(dtype=float)

    # Pivot: date × symbol → close
    pivot = kline.pivot_table(index="date", columns="symbol", values="close")

    # 计算日收益率
    daily_returns = pivot.pct_change().dropna(how="all")

    # 等权平均: 对每个交易日, 取所有可用股票的平均收益率
    ew_returns = daily_returns.mean(axis=1).dropna()
    ew_returns.name = "ew_return"

    return ew_returns.sort_index()


# ─── 核心函数 ────────────────────────────────────────────────────────────


def get_benchmark_returns(
    name: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.Series:
    """获取指定基准的日收益率序列

    Args:
        name: 基准名称, 如 "semiconductor_ew", "ew_a_share"
        start_date: 起始日期 "YYYY-MM-DD" 或 "YYYYMMDD"
        end_date: 截止日期 "YYYY-MM-DD" 或 "YYYYMMDD"

    Returns:
        pd.Series of daily returns, index=DatetimeIndex
    """
    name = name.lower().strip()
    if name not in VALID_BENCHMARK_NAMES:
        raise ValueError(
            f"不支持的基准 '{name}', 可选: {sorted(VALID_BENCHMARK_NAMES)}"
        )

    meta = BENCHMARK_META[name]
    universe_key = meta["universe"]

    if universe_key == "U1":
        codes = _get_universe_codes("U1_TRADABLE")
    else:
        codes = _get_universe_codes(universe_key)

    if not codes:
        logger.warning(f"基准 {name}: 标的代码列表为空 (universe={universe_key})")
        return pd.Series(dtype=float)

    logger.info(
        f"基准 {name}: {len(codes)} 个标的, "
        f"日期范围 {start_date or 'auto'} ~ {end_date or 'auto'}"
    )

    returns = _compute_equal_weight_returns(codes, start_date, end_date)
    returns.name = name

    if len(returns) > 0:
        logger.info(
            f"  → {len(returns)} 个交易日, "
            f"{returns.index[0].date()} ~ {returns.index[-1].date()}"
        )
    else:
        # ETF 池可能没有数据, 记录但不等同于失败
        if universe_key == "ETF":
            logger.info("  → ETF池数据为空 (可能无对应K线文件)")
        else:
            logger.warning(f"  → 返回空序列")

    return returns


def list_benchmarks() -> list[dict]:
    """列出所有可用基准及其元信息

    Returns:
        [{name, label, universe, description, available_days, date_range}, ...]
    """
    results = []
    for name, meta in BENCHMARK_META.items():
        try:
            rets = get_benchmark_returns(name, end_date=datetime.now(CST).strftime("%Y%m%d"))
            available_days = len(rets)
            date_range = (
                f"{rets.index[0].date()} ~ {rets.index[-1].date()}"
                if available_days > 0
                else "N/A"
            )
            ann_vol = float(rets.std() * np.sqrt(252)) if available_days > 0 else None
        except Exception as e:
            available_days = 0
            date_range = f"error: {e}"
            ann_vol = None

        results.append({
            "name": name,
            "label": meta["label"],
            "universe": meta["universe"],
            "description": meta["description"],
            "available_days": available_days,
            "date_range": date_range,
            "annualized_volatility": round(ann_vol, 4) if ann_vol else None,
        })

    return results


def get_benchmark_report(name: str, n_days: int = 60) -> dict:
    """输出指定基准近 N 日表现报告

    Args:
        name: 基准名称
        n_days: 回溯交易日数 (默认 60)

    Returns:
        dict with stats
    """
    rets = get_benchmark_returns(name)
    if rets.empty:
        return {"name": name, "error": "无数据", "available_days": 0}

    # 取最近 N 日
    recent = rets.tail(n_days)
    cum_ret = (1 + recent).prod() - 1
    ann_ret = (1 + cum_ret) ** (252 / len(recent)) - 1 if len(recent) > 0 else 0
    ann_vol = recent.std() * np.sqrt(252)
    sharpe = (ann_ret - 0.02) / ann_vol if ann_vol > 0 else 0
    max_dd = _max_drawdown(recent)

    return {
        "name": name,
        "label": BENCHMARK_META[name]["label"],
        "n_days": len(recent),
        "date_range": f"{recent.index[0].date()} ~ {recent.index[-1].date()}",
        "cumulative_return_pct": round(cum_ret * 100, 2),
        "annualized_return_pct": round(ann_ret * 100, 2),
        "annualized_volatility_pct": round(ann_vol * 100, 2),
        "sharpe_ratio": round(sharpe, 4),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "positive_day_ratio": round((recent > 0).mean(), 4),
    }


def _max_drawdown(rets: pd.Series) -> float:
    """计算最大回撤"""
    if len(rets) < 2:
        return 0.0
    cum = (1 + rets).cumprod()
    peak = cum.expanding().max()
    dd = (cum - peak) / peak
    return float(dd.min())


# ─── CLI 命令 ────────────────────────────────────────────────────────────


def cmd_list():
    """列所有基准"""
    benchmarks = list_benchmarks()
    print(f"\n📊 V4.3 基准体系 ({len(benchmarks)} 个基准)\n")
    for b in benchmarks:
        vol_str = f"{b['annualized_volatility']:.1%}" if b["annualized_volatility"] else "N/A"
        print(f"  {b['name']:25s}  {b['label']}")
        print(f"  {'':25s}  池: {b['universe']}  |  数据: {b['available_days']}d  |  年化波动: {vol_str}")
        print(f"  {'':25s}  日期: {b['date_range']}")
        print()


def cmd_report(name: str, n_days: int = 60):
    """输出指定基准报告"""
    if name not in VALID_BENCHMARK_NAMES:
        print(f"❌ 不支持的基准: {name}")
        print(f"   可选: {', '.join(sorted(VALID_BENCHMARK_NAMES))}")
        return

    report = get_benchmark_report(name, n_days=n_days)
    if "error" in report:
        print(f"❌ {name}: {report['error']}")
        return

    print(f"\n📊 基准报告: {report['label']} ({report['name']})")
    print(f"   {'=' * 45}")
    print(f"   回溯天数:          {report['n_days']}")
    print(f"   日期范围:          {report['date_range']}")
    print(f"   累计收益率:        {report['cumulative_return_pct']:+.2f}%")
    print(f"   年化收益率:        {report['annualized_return_pct']:+.2f}%")
    print(f"   年化波动率:        {report['annualized_volatility_pct']:.2f}%")
    print(f"   Sharpe Ratio:      {report['sharpe_ratio']:.4f}")
    print(f"   最大回撤:          {report['max_drawdown_pct']:.2f}%")
    print(f"   上涨日占比:        {report['positive_day_ratio']:.2%}")


# ═══════════════════════════════════════════════════════════════════════════
# Ensure universe exists before use
# ═══════════════════════════════════════════════════════════════════════════


def ensure_universes():
    """确保 universes.json 已构建"""
    if not UNIVERSES_FILE.exists():
        logger.info("universes.json 不存在, 自动构建...")
        from universes import build_all
        build_all()
        logger.info("universes.json 构建完成")


if __name__ == "__main__":
    import sys

    # 确保池已构建
    ensure_universes()

    if len(sys.argv) < 2:
        print("用法: python3 benchmarks_v4.py <list|report> [name] [--days N]")
        sys.exit(1)

    action = sys.argv[1]
    if action == "list":
        cmd_list()
    elif action == "report":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        n_days = 60
        if "--days" in sys.argv:
            try:
                idx = sys.argv.index("--days")
                n_days = int(sys.argv[idx + 1])
            except (ValueError, IndexError):
                pass
        cmd_report(name, n_days=n_days)
    else:
        print(f"未知命令: {action}")
        sys.exit(1)
