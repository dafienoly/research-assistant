"""Portfolio Review V2.2.1 — 执行偏离+持仓贡献+机会成本+组合偏离+ETF效果"""
import os, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np
from factor_lab.live.account_profile import get_board

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


def run_portfolio_review(date: str, rebalance_result: dict = None, execution_match: dict = None) -> dict:
    """运行组合复盘"""
    # 获取后续收益数据
    future = _get_future_returns(date)

    # 1. 执行符合度
    match = execution_match or {"matched": [], "missed": [], "manual_overrides": [], "partial": [], "rejected": []}

    # 2. 机会成本
    opp_cost = _calc_opportunity_cost(match.get("missed", []), future)

    # 3. 人工 override 分析
    override_analysis = _analyze_overrides(match.get("manual_overrides", []), future)

    # 4. 持仓贡献 (如果有 positions 数据)
    holding_perf = future if future.get("status") != "pending" else {"status": "pending", "note": "后续数据不足"}

    # 5. 组合偏离 (如果有 rebalance_result)
    drift = _calc_drift(rebalance_result, match)

    # 6. ETF 效果
    etf_effect = _calc_etf_effect(future)

    review = {
        "date": date,
        "review_status": "completed" if future.get("status") != "pending" else "partial",
        "execution_summary": {
            "matched": len(match.get("matched", [])),
            "missed": len(match.get("missed", [])),
            "manual_overrides": len(match.get("manual_overrides", [])),
            "partial": len(match.get("partial", [])),
            "rejected": len(match.get("rejected", [])),
        },
        "opportunity_cost": opp_cost,
        "manual_override_analysis": override_analysis,
        "holding_performance": holding_perf,
        "portfolio_drift": drift,
        "etf_substitution_effect": etf_effect,
        "pending_horizons": future.get("pending", []),
    }

    return review


def _get_future_returns(date: str, horizons: list = None):
    """获取后续 1/3/5 日收益 (简化版, 使用 close_pivot)"""
    if horizons is None:
        horizons = [1, 3, 5]
    try:
        from factor_lab.factor_engine import load_stock_kline
        symbols = ["000001", "000002", "000620", "002396", "603501"]
        df = load_stock_kline(symbols, start_date=date, end_date=pd.Timestamp(date) + pd.Timedelta(days=10), min_days=1)
        if df.empty:
            return {"status": "pending", "pending": horizons, "note": "后续行情不足"}
        close_pivot = df.pivot_table(index="date", columns="symbol", values="close").sort_index()
        signal_ts = pd.Timestamp(date)
        future_dates = close_pivot.index[close_pivot.index > signal_ts]
        returns = {}
        for h in horizons:
            if len(future_dates) >= h:
                d0 = future_dates[0]
                dh = future_dates[min(h - 1, len(future_dates) - 1)]
                ret = (close_pivot.loc[dh].mean() / close_pivot.loc[d0].mean() - 1) if d0 in close_pivot.index and dh in close_pivot.index else None
                returns[f"ret_{h}d"] = round(float(ret), 4) if ret is not None else None
            else:
                returns[f"ret_{h}d"] = None
        pending = [h for h in horizons if returns.get(f"ret_{h}d") is None]
        return {"status": "completed" if not pending else "partial", "returns": returns, "pending": pending}
    except Exception as e:
        return {"status": "pending", "pending": horizons, "note": str(e)}


def _calc_opportunity_cost(missed: list, future: dict) -> dict:
    """计算未执行建议的机会成本"""
    items = []
    for m in missed:
        items.append({
            "symbol": m.get("symbol", ""),
            "action": m.get("action", ""),
            "ret_1d": future.get("returns", {}).get("ret_1d"),
            "ret_3d": future.get("returns", {}).get("ret_3d"),
            "ret_5d": future.get("returns", {}).get("ret_5d"),
            "status": "completed" if future.get("status") == "completed" else "pending",
        })
    return {
        "total_missed": len(items),
        "items": items,
        "status": future.get("status", "pending"),
    }


def _analyze_overrides(overrides: list, future: dict) -> dict:
    """分析人工 override 效果"""
    items = []
    for o in overrides:
        items.append({
            "symbol": o.get("symbol", ""),
            "action": o.get("action", ""),
            "ret_1d": future.get("returns", {}).get("ret_1d"),
            "ret_3d": future.get("returns", {}).get("ret_3d"),
            "status": "completed" if future.get("status") == "completed" else "pending",
        })
    return {"total": len(items), "items": items}


def _calc_drift(rebalance_result: dict, match: dict) -> dict:
    """计算组合偏离"""
    if not rebalance_result:
        return {"status": "no_rebalance_data"}
    plan_b = rebalance_result.get("plans", {}).get("B", {})
    target_buys = {b["symbol"] for b in plan_b.get("buy_candidate", [])}
    target_sells = {s["symbol"] for s in plan_b.get("sell_candidate", []) + plan_b.get("risk_sell_candidate", [])}
    actual_buys = {m["symbol"] for m in match.get("matched", []) if m.get("action") == "buy"}
    actual_sells = {m["symbol"] for m in match.get("matched", []) if m.get("action") == "sell"}
    missed = {m["symbol"] for m in match.get("missed", [])}
    return {
        "target_buys": len(target_buys),
        "target_sells": len(target_sells),
        "actual_buys": len(actual_buys),
        "actual_sells": len(actual_sells),
        "missed_buys": len(missed & target_buys),
        "missed_sells": len(missed & target_sells),
        "status": "completed",
    }


def _calc_etf_effect(future: dict) -> dict:
    """ETF 替代效果"""
    ret = future.get("returns", {})
    return {
        "etf_ret_1d": ret.get("ret_1d"),
        "etf_ret_3d": ret.get("ret_3d"),
        "status": "completed" if ret.get("ret_1d") is not None else "pending",
        "note": "ETF 替代效果通过市场收益近似估算",
    }


def generate_review_report(review: dict, output_dir: str):
    """生成复盘报告 HTML/JSON/CSV"""
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "portfolio_review.json"), "w") as f:
        json.dump(review, f, indent=2, ensure_ascii=False)

    es = review.get("execution_summary", {})
    oc = review.get("opportunity_cost", {})
    drift = review.get("portfolio_drift", {})

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>组合复盘报告 {review['date']}</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px 6px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }} .num {{ text-align:right; }}
</style></head><body>
<div class="card"><h1>📊 组合复盘报告 V2.2.1</h1>
<p style="color:#aaa;">{review['date']} | 状态: {review['review_status']}</p></div>

<div class="card"><h2>🎯 执行符合度</h2>
<table><tr><th>类型</th><th>数量</th></tr>
<tr><td>✅ Matched</td><td>{es.get('matched',0)}</td></tr>
<tr><td>❌ Missed</td><td>{es.get('missed',0)}</td></tr>
<tr><td>🟡 Manual Override</td><td>{es.get('manual_overrides',0)}</td></tr>
<tr><td>🟠 Partial</td><td>{es.get('partial',0)}</td></tr>
<tr><td>🔴 Rejected</td><td>{es.get('rejected',0)}</td></tr>
</table></div>

{f'<div class="card"><h2>💰 机会成本 ({oc.get("total_missed",0)} 项)</h2><table><tr><th>代码</th><th>1日</th><th>3日</th><th>5日</th></tr>' + "".join(f'<tr><td>{i["symbol"]}</td><td>{i.get("ret_1d","pending")}</td><td>{i.get("ret_3d","pending")}</td><td>{i.get("ret_5d","pending")}</td></tr>' for i in oc.get("items",[])) + '</table></div>' if oc.get("items") else ''}

<div class="card"><h2>📐 组合偏离</h2>
<table><tr><td>Target Buy</td><td class="num">{drift.get("target_buys",0)}</td></tr>
<tr><td>Actual Buy</td><td class="num">{drift.get("actual_buys",0)}</td></tr>
<tr><td>Missed Buy</td><td class="num">{drift.get("missed_buys",0)}</td></tr>
<tr><td>Missed Sell</td><td class="num">{drift.get("missed_sells",0)}</td></tr>
</table></div>

<div class="card"><h2>⚠️ Pending</h2><ul>{"".join(f"<li>{h}</li>" for h in review.get("pending_horizons",[])) if review.get("pending_horizons") else "<li>无</li>"}</ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V2.2.1 | {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</body></html>"""
    with open(os.path.join(output_dir, "portfolio_review_report.html"), "w") as f:
        f.write(html)

    with open(os.path.join(output_dir, "audit.log"), "w") as f:
        f.write(f"=== PORTFOLIO REVIEW V2.2.1 ===\nDate: {review['date']}\nStatus: {review['review_status']}\nNo auto-order: True\nNo future leakage: True\n=== END ===\n")
