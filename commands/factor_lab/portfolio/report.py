"""Portfolio Report V6.4 — 组合回测报告生成

提供:
  - print_summary(): 终端人类可读摘要输出
  - format_report(): 结构化报告输出 (dict)
  - save_report(): 保存为 JSON 文件
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from factor_lab.portfolio.spec import PortfolioResult

CST = timezone(timedelta(hours=8))
DEFAULT_OUTPUT_ROOT = Path(
    os.environ.get(
        "HERMES_REPORTS_DIR",
        "/mnt/d/HermesReports/portfolio",
    )
)


def print_summary(result: PortfolioResult) -> None:
    """打印组合回测摘要 (终端可读)

    Args:
        result: 组合回测结果
    """
    summary = result.summary()
    metrics = result.metrics
    sep = "=" * 62

    print(f"\n{sep}")
    print(f"  📊 组合回测报告: {summary.get('portfolio', 'N/A')}")
    print(f"{sep}")
    print(f"  基准:          {summary.get('benchmark', 'N/A')}")
    print(f"  子策略数:      {metrics.n_strategies}")
    print(f"  交易日数:      {metrics.n_trading_days}")
    if result.execution_log:
        print(f"  执行日志:      {len(result.execution_log)} 条")
    print()

    # ── 组合表现 ──
    print(f"  ┌─ 组合表现 ─────────────────────────────────────┐")
    print(f"  │  累计收益率:    {summary.get('cumulative_return_pct', 0):>8.2f}%")
    print(f"  │  年化收益率:    {summary.get('annualized_return_pct', 0):>8.2f}%")
    print(f"  │  Sharpe Ratio:  {summary.get('sharpe', 0):>10.4f}")
    print(f"  │  最大回撤:      {summary.get('max_drawdown_pct', 0):>8.2f}%")
    print(f"  │  Calmar Ratio:  {summary.get('calmar', 0):>10.4f}")
    print(f"  │  胜率 (日):     {summary.get('win_rate_pct', 0):>8.2f}%")
    print(f"  └────────────────────────────────────────────────┘")
    print()

    # ── 基准对比 ──
    if summary.get("benchmark_return_pct") is not None:
        print(f"  ┌─ 基准对比: {summary.get('benchmark', 'N/A')} ────────────────────┐")
        print(f"  │  基准累计收益: {summary.get('benchmark_return_pct', 0):>9.2f}%")
        print(f"  │  主动收益:     {summary.get('active_return_pct', 0):>9.2f}%")
        print(f"  │  跟踪误差:     {summary.get('tracking_error_pct', 0):>9.2f}%")
        print(f"  │  信息比率:     {summary.get('information_ratio', 0):>10.4f}")
        print(f"  │  Alpha:        {summary.get('alpha', 0):>10.4f}%")
        print(f"  │  Beta:         {summary.get('beta', 0):>10.4f}")
        print(f"  │  R²:           {summary.get('r_squared', 0):>10.4f}")
        print(f"  └────────────────────────────────────────────────┘")
        print()

    # ── 策略间相关性 ──
    print(f"  ┌─ 策略相关性 ─────────────────────────────────┐")
    print(f"  │  平均交叉相关性: {summary.get('avg_cross_correlation', 0):>8.4f}")
    print(f"  └────────────────────────────────────────────────┘")
    print()

    # ── 策略归因 ──
    if result.attribution:
        print(f"  ┌─ 策略归因 ─────────────────────────────────────┐")
        print(f"  │  {'策略':<16} {'权重':>6} {'贡献%':>8} {'独自收益':>8} {'Sharpe':>8}")
        print(f"  │  {'-'*16} {'-'*6} {'-'*8} {'-'*8} {'-'*8}")
        for a in result.attribution:
            print(
                f"  │  {a.strategy_name:<16} "
                f"{a.weight:>6.2f} "
                f"{a.contribution_pct:>7.1f}% "
                f"{a.standalone_return_pct:>7.2f}% "
                f"{a.sharpe:>8.4f}"
            )
        print(f"  └────────────────────────────────────────────────┘")
        print()

    # ── 警告 ──
    if result.warnings:
        print(f"  ⚠  Warnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"    - {w}")
        print()

    print(f"{sep}\n")


def format_report(result: PortfolioResult) -> dict:
    """生成结构化报告 dict

    Args:
        result: 组合回测结果

    Returns:
        可 JSON 序列化的完整报告
    """
    report = result.to_dict()

    # 添加序列化摘要
    summary = result.summary()

    # 添加各策略明细
    strat_details = {}
    for sname in result.individual_returns:
        s_ret = result.individual_returns[sname]
        s_equity = result.individual_equities.get(sname)
        strat_details[sname] = {
            "n_days": len(s_ret),
            "first_date": str(s_ret.index[0]) if len(s_ret) > 0 else "",
            "last_date": str(s_ret.index[-1]) if len(s_ret) > 0 else "",
        }
    report["strategy_details"] = strat_details

    # 权重历史头尾
    if result.weight_history is not None and not result.weight_history.empty:
        wh = result.weight_history
        report["weight_history_summary"] = {
            "n_periods": len(wh),
            "first_date": str(wh.index[0]),
            "last_date": str(wh.index[-1]),
        }

    # 交叉相关性 (Matrix → list)
    if result.cross_correlation is not None and not result.cross_correlation.empty:
        corr_list = []
        for i in result.cross_correlation.index:
            for j in result.cross_correlation.columns:
                val = result.cross_correlation.loc[i, j]
                if not pd.isna(val):
                    corr_list.append({
                        "strategy_i": str(i),
                        "strategy_j": str(j),
                        "correlation": round(val, 4),
                    })
        report["cross_correlation"] = corr_list

    report["summary"] = summary
    report["_generated_at"] = datetime.now(CST).isoformat()

    return report


def save_report(
    result: PortfolioResult,
    output_dir: Optional[str] = None,
    file_name: Optional[str] = None,
) -> str:
    """保存组合回测报告为 JSON 文件

    Args:
        result: 组合回测结果
        output_dir: 输出目录 (默认: HERMES_REPORTS_DIR/portfolio/)
        file_name: 文件名 (默认: {portfolio_name}_portfolio_report_{run_id}.json)

    Returns:
        写入的文件路径
    """
    out_dir = Path(output_dir or DEFAULT_OUTPUT_ROOT)
    os.makedirs(out_dir, exist_ok=True)

    if file_name is None:
        portfolio_name = (
            result.portfolio_spec.name.replace(" ", "_")
            if result.portfolio_spec
            else "portfolio"
        )
        file_name = (
            f"{portfolio_name}_portfolio_report_{result.run_id}.json"
        )

    out_path = out_dir / file_name

    report = format_report(result)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return str(out_path)
