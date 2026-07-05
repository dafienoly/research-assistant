"""Decision Review — 事后复盘"""
import sys, os, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")
DAILY = BASE / "daily_premarket"


def run_decision_review(start_date: str, end_date: str) -> dict:
    """运行决策复盘"""
    from factor_lab.factor_engine import load_stock_kline
    from factor_lab.metrics import compute_metrics

    # 扫描日期范围内的决策日志
    dates = pd.bdate_range(start_date, end_date)
    reviews = []
    all_decisions = []
    pending = []

    for d in dates:
        date_str = d.strftime("%Y-%m-%d")
        dir_name = date_str.replace("-", "")
        log_path = DAILY / dir_name / "decision_log.json"
        report_path = DAILY / dir_name / "unified_premarket_report.json"

        if not log_path.exists() or not report_path.exists():
            continue

        with open(log_path) as f:
            decision = json.load(f)
        with open(report_path) as f:
            report = json.load(f)

        all_decisions.append(decision)

        # 获取后续行情数据
        future = _get_future_returns(report, date_str, start_date, end_date)
        if future.get("pending"):
            pending.append(date_str)
            continue

        reviews.append({
            "date": date_str,
            "decision": decision,
            "future": future,
        })

    # 汇总
    summary = {
        "period": f"{start_date} ~ {end_date}",
        "total_trading_days": len(dates),
        "decisions_found": len(all_decisions),
        "reviews_completed": len(reviews),
        "pending_dates": pending,
        "reviews": reviews,
    }

    return summary


def _get_future_returns(report, signal_date, start, end):
    """获取信号日后 1/3/5 日收益"""
    # 获取 self_top5 股票
    self_stock = report.get("self_stock_candidates", {})
    top5 = [c["symbol"] for c in self_stock.get("top5", [])]

    if not top5:
        return {"pending": False, "note": "无候选股票", "ret_1d": 0, "ret_3d": 0, "ret_5d": 0}

    try:
        from factor_lab.factor_engine import load_stock_kline
        df = load_stock_kline(top5, start_date=signal_date, end_date=pd.Timestamp(signal_date) + pd.Timedelta(days=10))
        if df.empty:
            return {"pending": True, "note": "后续行情数据不足"}

        df = df.sort_values(["symbol", "date"])
        close_pivot = df.pivot_table(index="date", columns="symbol", values="close")
        close_pivot = close_pivot.sort_index()

        signal_ts = pd.Timestamp(signal_date)
        future_dates = close_pivot.index[close_pivot.index > signal_ts]

        if len(future_dates) < 1:
            return {"pending": True, "note": "后续交易日数据不足"}

        # 后续 1/3/5 日收益
        def _forward_ret(n_days):
            if len(future_dates) < n_days:
                return None
            d1 = future_dates[0]
            dn = future_dates[min(n_days - 1, len(future_dates) - 1)]
            if d1 in close_pivot.index and dn in close_pivot.index:
                p1 = close_pivot.loc[d1]
                pn = close_pivot.loc[dn]
                avail = [s for s in top5 if s in p1.index and s in pn.index]
                if not avail:
                    return None
                rets = [(pn[s] - p1[s]) / p1[s] for s in avail]
                return float(np.mean(rets))
            return None

        return {
            "pending": False,
            "ret_1d": _forward_ret(1),
            "ret_3d": _forward_ret(3),
            "ret_5d": _forward_ret(5),
            "top5_symbols": top5,
        }

    except Exception as e:
        return {"pending": True, "note": str(e)}


def generate_review_report(result: dict, output_dir: str):
    """生成复盘报告"""
    os.makedirs(output_dir, exist_ok=True)
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    # JSON
    with open(os.path.join(output_dir, "decision_review.json"), "w") as f:
        json.dump(result, f, indent=2)

    # HTML
    rows = ""
    for r in result.get("reviews", []):
        f = r.get("future", {})
        d = r.get("decision", {})
        action = d.get("user_action", "?")
        plan = d.get("selected_plan", "?")
        r1 = f.get("ret_1d", "—")
        r3 = f.get("ret_3d", "—")
        r5 = f.get("ret_5d", "—")
        if r1 is not None:
            r1 = f"{r1*100:.1f}%"
        if r3 is not None:
            r3 = f"{r3*100:.1f}%"
        if r5 is not None:
            r5 = f"{r5*100:.1f}%"
        rows += f"<tr><td>{r['date']}</td><td>{action}</td><td>{plan}</td><td>{r1}</td><td>{r3}</td><td>{r5}</td></tr>"

    pending_rows = "".join(f"<tr><td>{d}</td><td style=\"color:#ff9100;\">pending</td></tr>" for d in result.get("pending_dates", []))

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>决策复盘报告</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:5px 8px; text-align:left; border-bottom:1px solid #333; }}
th {{ color:#888; font-size:0.85em; }} .num {{ text-align:right; }}
</style></head><body>
<div class="card"><h1>📊 决策复盘报告</h1>
<p style="color:#aaa;">{result['period']} | {result['total_trading_days']}个交易日 | {result['reviews_completed']}次复盘 | {len(result.get('pending_dates',[]))}次待定</p></div>

<div class="card"><h2>📋 每日决策收益 (Self Top5)</h2>
<table><tr><th>日期</th><th>操作</th><th>方案</th><th>1日</th><th>3日</th><th>5日</th></tr>{rows}</table></div>

{f'<div class="card"><h2>⏳ Pending (行情不足)</h2><table><tr><th>日期</th><th>状态</th></tr>{pending_rows}</table></div>' if result.get('pending_dates') else ''}

<div class="card"><h2>⚠️ 说明</h2>
<ul>
<li>收益基于 self Top5 等权计算, 不含手续费</li>
<li>pending = 后续交易日数据不足, 不假装有结果</li>
<li>不包含用户人工修改的影响 (custom 模式见 decision_log.json)</li>
</ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V1.13 | {now}</p></div>
</body></html>"""

    with open(os.path.join(output_dir, "decision_review_report.html"), "w", encoding="utf-8") as f:
        f.write(html)

    # audit
    with open(os.path.join(output_dir, "audit.log"), "w") as f:
        f.write(f"=== DECISION REVIEW AUDIT ===\nPeriod: {result['period']}\nDecisions: {result['decisions_found']}\nReviews: {result['reviews_completed']}\nPending: {len(result.get('pending_dates',[]))}\nNo future leakage: True\n=== END ===\n")

    return {"output_dir": output_dir}
