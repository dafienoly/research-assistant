"""Execution Matcher — 成交与调仓建议匹配"""
import os, json
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


def match_executions(date: str, rebalance_result: dict = None, execution_records: list = None) -> dict:
    """匹配执行记录与 rebalance diff 建议"""
    matched, missed, manual_overrides, partial_execs = [], [], [], []

    if not execution_records:
        return {"date": date, "matched": [], "missed": [], "manual_overrides": [], "partial": [], "status": "no_executions"}

    if not rebalance_result:
        return {"date": date, "matched": [], "missed": [], "manual_overrides": [], "partial": [], "status": "no_rebalance"}

    # 获取 rebalance 建议
    plan_b = rebalance_result.get("plans", {}).get("B", {})
    buy_recs = {r["symbol"] for r in plan_b.get("buy_candidate", [])}
    sell_recs = {r["symbol"] for r in plan_b.get("sell_candidate", []) + plan_b.get("risk_sell_candidate", [])}
    all_recommended = buy_recs | sell_recs

    # 已执行的 symbol
    executed_buy = set()
    executed_sell = set()
    for ex in execution_records:
        sym = ex.get("symbol", "")
        if ex.get("side") == "buy":
            executed_buy.add(sym)
        elif ex.get("side") == "sell":
            executed_sell.add(sym)

    # matched: 推荐且执行了
    for sym in buy_recs & executed_buy:
        matched.append({"symbol": sym, "action": "buy", "match_type": "matched"})
    for sym in sell_recs & executed_sell:
        matched.append({"symbol": sym, "action": "sell", "match_type": "matched"})

    # missed: 推荐但未执行
    for sym in buy_recs - executed_buy:
        missed.append({"symbol": sym, "action": "buy", "match_type": "missed"})
    for sym in sell_recs - executed_sell:
        missed.append({"symbol": sym, "action": "sell", "match_type": "missed"})

    # manual override: 执行了但未推荐
    for sym in executed_buy - buy_recs:
        manual_overrides.append({"symbol": sym, "action": "buy", "match_type": "manual_override"})
    for sym in executed_sell - sell_recs:
        manual_overrides.append({"symbol": sym, "action": "sell", "match_type": "manual_override"})

    return {
        "date": date,
        "matched": matched,
        "missed": missed,
        "manual_overrides": manual_overrides,
        "partial": partial_execs,
        "summary": {
            "n_matched": len(matched),
            "n_missed": len(missed),
            "n_manual_overrides": len(manual_overrides),
            "n_partial": len(partial_execs),
        },
        "status": "ok",
    }


def generate_match_report(match_result: dict, output_dir: str):
    """生成匹配报告 HTML"""
    os.makedirs(output_dir, exist_ok=True)

    # JSON
    with open(os.path.join(output_dir, "execution_match.json"), "w") as f:
        json.dump(match_result, f, indent=2, ensure_ascii=False)

    # HTML
    s = match_result.get("summary", {})
    rows = ""
    for cat in ("matched", "missed", "manual_overrides"):
        for item in match_result.get(cat, []):
            color = {"matched": "#00c853", "missed": "#ff1744", "manual_override": "#ff9100"}.get(item.get("match_type",""), "#888")
            rows += f"<tr><td>{item['symbol']}</td><td>{item['action']}</td><td style='color:{color}'>{item['match_type']}</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>执行匹配报告 {match_result['date']}</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:5px 8px; text-align:left; border-bottom:1px solid #333; }}
th {{ color:#888; font-size:0.85em; }}
</style></head><body>
<div class="card"><h1>📊 执行匹配报告</h1><p style="color:#aaa;">{match_result['date']}</p>
<p>Matched: {s.get('n_matched',0)} | Missed: {s.get('n_missed',0)} | Manual: {s.get('n_manual_overrides',0)} | Partial: {s.get('n_partial',0)}</p></div>
<div class="card"><h2>📋 匹配明细</h2><table><tr><th>代码</th><th>动作</th><th>类型</th></tr>{rows}</table></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V2.2 | {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</body></html>"""
    with open(os.path.join(output_dir, "execution_match_report.html"), "w") as f:
        f.write(html)
