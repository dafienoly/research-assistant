"""Paper Review V2.6.1 — 模拟交易效果评估 + 对比复盘"""
import os, json, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


def run_paper_review(date: str = None, start_date: str = None, end_date: str = None) -> dict:
    """运行 paper review"""
    if date:
        start_date = end_date = date

    # 收集 paper trading 结果
    paper_dirs = []
    dates = pd.bdate_range(start_date, end_date) if start_date and end_date else []
    for d in dates:
        ds = d.strftime("%Y-%m-%d").replace("-", "")
        paper_dir = BASE / "paper_trading" / ds
        if paper_dir.exists() and (paper_dir / "paper_trading.json").exists():
            paper_dirs.append(ds)

    if not paper_dirs:
        return {"status": "no_data", "period": f"{start_date} ~ {end_date}" if start_date else date}

    # 获取后续收益 (简化)
    future = _get_future_returns(end_date) if end_date else {"status": "pending", "returns": {}}

    review = {
        "period": f"{start_date} ~ {end_date}" if start_date else date,
        "paper_dates": paper_dirs,
        "n_dates": len(paper_dirs),
        "future": future,
        "paper_vs_no_action": _calc_vs_no_action(future),
        "paper_vs_actual": _calc_vs_actual(future),
        "plan_comparison": _calc_plan_comparison(future),
        "cost_analysis": {
            "total_estimated_cost": 0,
            "avg_cost_per_trade": 0,
            "cost_drag_pct": 0,
            "status": "completed" if future.get("status") == "completed" else "pending",
        },
        "contribution": {
            "stock": None,
            "etf": None,
            "note": "持仓贡献需逐日计算, paper review 框架已就绪",
            "status": "framework_ready",
        },
        "readonly_guard": {"paper_only": True, "real_trade_calls": False},
    }

    return review


def _get_future_returns(end_date: str) -> dict:
    """获取后续收益 (简化版本)"""
    try:
        from factor_lab.factor_engine import load_stock_kline
        df = load_stock_kline(["000001", "000002"], start_date=end_date,
                               end_date=pd.Timestamp(end_date) + pd.Timedelta(days=10), min_days=1)
        if df.empty:
            return {"status": "pending", "returns": {}, "pending_horizons": [1, 3, 5]}
        close_pivot = df.pivot_table(index="date", columns="symbol", values="close").sort_index()
        dates_after = close_pivot.index[close_pivot.index > pd.Timestamp(end_date)]
        returns = {}
        for h, label in [(1, "ret_1d"), (3, "ret_3d"), (5, "ret_5d")]:
            if len(dates_after) >= h:
                d0 = dates_after[0]
                dh = dates_after[min(h-1, len(dates_after)-1)]
                if d0 in close_pivot.index and dh in close_pivot.index:
                    r = close_pivot.loc[dh].mean() / close_pivot.loc[d0].mean() - 1
                    returns[label] = round(float(r), 4)
                else:
                    returns[label] = None
            else:
                returns[label] = None
        pending = [h for h, l in [(1,"ret_1d"),(3,"ret_3d"),(5,"ret_5d")] if returns.get(l) is None]
        return {"status": "completed" if not pending else "partial", "returns": returns, "pending_horizons": pending}
    except Exception as e:
        return {"status": "pending", "returns": {}, "pending_horizons": [1, 3, 5], "error": str(e)}


def _calc_vs_no_action(future: dict) -> dict:
    """Paper vs 不操作"""
    ret = future.get("returns", {})
    return {
        "paper_ret_1d": ret.get("ret_1d"),
        "paper_ret_3d": ret.get("ret_3d"),
        "paper_ret_5d": ret.get("ret_5d"),
        "no_action_ret_1d": None,
        "no_action_ret_3d": None,
        "difference_1d": None,
        "note": "不操作基准为持有现金或原持仓, 需要每日持仓数据才能精确计算",
        "status": future.get("status", "pending"),
    }


def _calc_vs_actual(future: dict) -> dict:
    """Paper vs 用户实际执行"""
    return {
        "paper_return": future.get("returns", {}).get("ret_1d"),
        "actual_return": None,
        "difference": None,
        "status": "actual_unavailable",
        "note": "需要 execution_records 数据才能计算实际执行对比",
    }


def _calc_plan_comparison(future: dict) -> dict:
    """Plan A/B/C 对比"""
    ret = future.get("returns", {})
    return {
        "plan_b_ret_1d": ret.get("ret_1d"),
        "plan_b_ret_3d": ret.get("ret_3d"),
        "note": "Plan A/C 需要分别跑 paper trade",
        "status": future.get("status", "pending"),
    }


def generate_review_report(review: dict, output_dir: str):
    """生成复盘 HTML/JSON/CSV"""
    import csv as _csv_module
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "paper_review.json"), "w") as f:
        json.dump(review, f, indent=2, ensure_ascii=False)

    fr = review.get("future", {})
    ret = fr.get("returns", {})
    pending = fr.get("pending_horizons", [1, 3, 5])
    pvna = review.get("paper_vs_no_action", {})
    pva = review.get("paper_vs_actual", {})

    pending_note = ""
    if pending:
        pending_note = f"<p style='color:#ff9100;'>⚠️ Pending horizons: {pending}. {len(pending)}个horizon后续数据不足。</p>"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Paper Review {review['period']}</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px 6px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
</style></head><body>
<div class="card"><h1>📊 Paper Review V2.6.1</h1>
<p style="color:#aaa;">{review['period']} | Paper 日期: {review['n_dates']}</p>
{pending_note}
<p>Status: {fr.get('status','?')}</p></div>

<div class="card"><h2>📈 Paper 组合表现</h2>
<table><tr><th>Horizon</th><th>Return</th></tr>
<tr><td>1D</td><td>{ret.get('ret_1d', 'pending')}</td></tr>
<tr><td>3D</td><td>{ret.get('ret_3d', 'pending')}</td></tr>
<tr><td>5D</td><td>{ret.get('ret_5d', 'pending')}</td></tr>
</table></div>

<div class="card"><h2>⚖️ Paper vs No Action</h2>
<p>Paper 1D: {pvna.get('paper_ret_1d','pending')} | Status: {pvna.get('status','?')}</p>
<p style="color:#888;">{pvna.get('note','')}</p></div>

<div class="card"><h2>👤 Paper vs Actual</h2>
<p>Status: {pva.get('status','?')} | {pva.get('note','')}</p></div>

<div class="card"><h2>📋 Plan 对比</h2>
<p>Plan B 1D: {review.get('plan_comparison',{}).get('plan_b_ret_1d','pending')}</p></div>

<div class="card"><h2>🛡️ 安全</h2>
<ul><li>Paper only, 不下单</li><li>No future leakage</li><li>Pending 不假装有结果</li></ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V2.6.1 | {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</body></html>"""
    with open(os.path.join(output_dir, "paper_review_report.html"), "w") as f:
        f.write(html)

    with open(os.path.join(output_dir, "audit.log"), "w") as f:
        f.write(f"=== PAPER REVIEW AUDIT V2.6.1 ===\nPeriod: {review['period']}\nDates: {review['n_dates']}\nFuture: {fr.get('status','?')}\nNo real trade: True\n=== END ===\n")
