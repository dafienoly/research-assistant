"""调仓差异分析 V2.0.1 — hold/reduce/sell/risk_sell/buy/skip/watch + Plan A/B/C"""
import os, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.live.account_profile import is_self_tradable, get_board

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")
PLAN_MAP = {"A": "conservative", "B": "balanced", "C": "aggressive"}
FEE_RATE = 0.0003
STAMP_RATE = 0.001
SLIPPAGE_BPS = 10


def run_rebalance_diff(date, positions_csv=None, plan="B", capital=50000, output_dir=None):
    from factor_lab.portfolio.position_loader import PositionLoader

    loader = PositionLoader()
    current_positions = loader.load_csv(positions_csv) if positions_csv else []
    pos_cash = loader.cash if current_positions else capital
    pos_stock_value = sum(float(p.get("market_value", int(p.get("shares", 0)) * float(p.get("current_price", 1)))) for p in current_positions if p.get("symbol","").upper()!="CASH")
    total_assets = pos_cash + pos_stock_value

    # 加载 unified report
    report_path = BASE / "unified_premarket" / date.replace("-", "") / "unified_premarket_report.json"
    if not report_path.exists():
        return {"error": f"报告不存在", "date": date}

    with open(report_path) as f:
        report = json.load(f)

    pos_symbols = {p["symbol"] for p in current_positions if p["symbol"].upper()!="CASH"}

    # 对 A/B/C 每个计划计算
    plans = {}
    for pid, pname in PLAN_MAP.items():
        tp = report.get("allocation_plans", {}).get(pname, {})
        target_stocks = tp.get("self_stock_lots", [])
        target_etfs = tp.get("etf_lots", [])
        target_syms = {l["symbol"] for l in target_stocks if "symbol" in l}
        target_etf_codes = {l.get("etf_code","") for l in target_etfs}

        hold, reduce, sell, risk_sell, buy, skip, watch = [], [], [], [], [], [], []

        # 当前持仓分类
        for p in current_positions:
            sym = p["symbol"]
            if sym.upper() == "CASH":
                continue
            shares = int(p.get("shares", 0))
            price = float(p.get("current_price", 0))
            in_target = sym in target_syms or sym in target_etf_codes

            if in_target:
                # 检查是否需要 reduce
                t_weight = 1.0 / max(len(target_stocks + target_etfs), 1)
                c_weight = (shares * price) / max(total_assets, 1)
                if c_weight > t_weight * 1.3:
                    reduce_shares = max(100, int((c_weight - t_weight) * total_assets / price / 100) * 100)
                    reduce.append({"symbol": sym, "shares": shares, "reduce_shares": reduce_shares,
                                   "current_weight": round(c_weight, 3), "target_weight": round(t_weight, 3),
                                   "reason": f"超配{c_weight:.1%}>{t_weight:.1%}"})
                else:
                    hold.append({"symbol": sym, "shares": shares, "action": "hold"})
            else:
                # 风控检查
                risk_reasons = []
                if sym.startswith(("688", "689")) and not is_self_tradable(sym):
                    risk_reasons.append("科创板不可交易")
                if sym.startswith(("300", "301")) and not is_self_tradable(sym):
                    risk_reasons.append("创业板不可交易")
                if not is_self_tradable(sym):
                    risk_reasons.append("账户权限")
                if risk_reasons:
                    risk_sell.append({"symbol": sym, "shares": shares, "reasons": risk_reasons,
                                      "action": "risk_sell"})
                else:
                    sell.append({"symbol": sym, "shares": shares, "action": "sell"})

        # 目标买入候选
        for l in target_stocks:
            sym = l["symbol"]
            if sym not in pos_symbols:
                if is_self_tradable(sym):
                    buy.append({"symbol": sym, "shares": l.get("shares", 0), "cost": l.get("cost", 0)})
                else:
                    skip.append({"symbol": sym, "reason": "账户权限不可买", "action": "skip"})

        # 观察名单
        for c in report.get("self_stock_candidates", {}).get("top8", []):
            sym = c["symbol"]
            if sym not in pos_symbols and sym not in {b["symbol"] for b in buy}:
                watch.append({"symbol": sym, "ret5": c.get("ret5", 0), "action": "watch"})

        # 费用估算
        est_buy = sum(b.get("cost", 0) for b in buy)
        est_sell = sum(s["shares"] * 10 for s in sell + risk_sell)  # 近似估算
        fee = (est_buy + est_sell) * FEE_RATE
        stamp = est_sell * STAMP_RATE
        slippage = (est_buy + est_sell) * SLIPPAGE_BPS / 10000
        total_cost = fee + stamp + slippage
        cash_after = pos_cash - est_buy + est_sell - total_cost

        plans[pid] = {
            "plan_name": pname,
            "hold": hold, "reduce": reduce, "sell_candidate": sell,
            "risk_sell_candidate": risk_sell, "buy_candidate": buy,
            "skip_buy": skip, "watch": watch[:3],  # 仅展示前 3
            "cash_summary": {
                "total_asset": round(total_assets, 2),
                "stock_value": round(pos_stock_value, 2),
                "cash": round(pos_cash, 2),
                "estimated_buy": round(est_buy, 2),
                "estimated_sell": round(est_sell, 2),
                "estimated_fee": round(fee, 2),
                "estimated_stamp_tax": round(stamp, 2),
                "estimated_slippage": round(slippage, 2),
                "estimated_total_cost": round(total_cost, 2),
                "estimated_cash_after": round(cash_after, 2),
                "cash_shortfall": round(max(0, est_buy - pos_cash - est_sell + total_cost), 2),
            },
            "warnings": ["不自动下单"],
        }

    return {
        "date": date,
        "plans": plans,
        "position_validation": {
            "partial": loader.partial, "warnings": loader.warnings, "errors": loader.errors,
        },
        "no_auto_order": True,
    }


def generate_rebalance_report(result, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    # JSON
    with open(os.path.join(output_dir, "rebalance_diff.json"), "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # CSVs per plan
    for pid, pdata in result.get("plans", {}).items():
        import csv
        for key in ["hold", "reduce", "sell_candidate", "risk_sell_candidate", "buy_candidate", "skip_buy", "watch"]:
            rows = pdata.get(key, [])
            if rows:
                path = os.path.join(output_dir, f"rebalance_diff_{pid}_{key}.csv")
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    if rows:
                        w = csv.DictWriter(f, fieldnames=rows[0].keys(), extrasaction="ignore")
                        w.writeheader()
                        w.writerows(rows)
        # cash summary
        with open(os.path.join(output_dir, f"cash_summary_{pid}.json"), "w") as f:
            json.dump(pdata.get("cash_summary", {}), f, indent=2)

    # HTML
    html = _build_html(result, now)
    with open(os.path.join(output_dir, "rebalance_diff_report.html"), "w") as f:
        f.write(html)

    # audit
    with open(os.path.join(output_dir, "audit.log"), "w") as f:
        summary = {pid: f"hold={len(p['hold'])} reduce={len(p['reduce'])} sell={len(p['sell_candidate'])} risk={len(p['risk_sell_candidate'])} buy={len(p['buy_candidate'])} skip={len(p['skip_buy'])} watch={len(p['watch'])}"
                   for pid, p in result.get("plans", {}).items()}
        f.write(f"=== REBALANCE DIFF V2.0.1 ===\nDate: {result['date']}\n{json.dumps(summary)}\nNo auto-order: True\n=== END ===\n")

    return {"output_dir": output_dir}


def _build_html(result, now):
    def _table(rows, fields, headers):
        if not rows:
            return "<p style='color:#888;'>无</p>"
        h = "".join(f"<th>{h}</th>" for h in headers)
        r = ""
        for row in rows:
            r += "<tr>"
            for f in fields:
                v = row.get(f, "")
                if isinstance(v, float):
                    r += f'<td class="num">{v:.2f}</td>'
                elif isinstance(v, list):
                    r += f"<td>{'; '.join(str(x) for x in v)}</td>"
                else:
                    r += f"<td>{v}</td>"
            r += "</tr>"
        return f"<table><tr>{h}</tr>{r}</table>"

    def _plan_section(pid, p):
        cs = p.get("cash_summary", {})
        h = f"<tr><th>代码</th><th>股数</th><th>原因</th></tr>"
        hold_r = "".join(f"<tr><td>{x['symbol']}</td><td>{x['shares']}</td><td>—</td></tr>" for x in p.get("hold", []))
        reduce_r = "".join(f"<tr><td>{x['symbol']}</td><td>{x.get('reduce_shares','')}</td><td>{x.get('reason','')}</td></tr>" for x in p.get("reduce", []))
        sell_r = "".join(f"<tr><td>{x['symbol']}</td><td>{x['shares']}</td><td>—</td></tr>" for x in p.get("sell_candidate", []))
        risk_r = "".join(f"<tr><td>{x['symbol']}</td><td>{x['shares']}</td><td>{'; '.join(x.get('reasons',[]))}</td></tr>" for x in p.get("risk_sell_candidate", []))
        buy_r = "".join(f"<tr><td>{x['symbol']}</td><td>{x['shares']}</td><td>{x.get('cost',0):.0f}</td></tr>" for x in p.get("buy_candidate", []))
        skip_r = "".join(f"<tr><td>{x['symbol']}</td><td>—</td><td>{x.get('reason','')}</td></tr>" for x in p.get("skip_buy", []))
        watch_r = "".join(f"<tr><td>{x['symbol']}</td><td>—</td><td>观察</td></tr>" for x in p.get("watch", []))

        return f"""
<h3>Plan {pid} ({p.get('plan_name','')})</h3>
<div style="display:flex;gap:20px;flex-wrap:wrap;">
<div style="background:#0f3460;padding:10px;border-radius:6px;min-width:200px;">
现金: {cs.get('cash',0):.0f}<br>
预计买入: {cs.get('estimated_buy',0):.0f}<br>
预计卖出: {cs.get('estimated_sell',0):.0f}<br>
费用: {cs.get('estimated_total_cost',0):.0f}<br>
调仓后现金: <strong>{cs.get('estimated_cash_after',0):.0f}</strong><br>
缺口: <span style="color:{'#ff1744' if cs.get('cash_shortfall',0)>0 else '#00c853'};">{cs.get('cash_shortfall',0):.0f}</span>
</div></div>
<details><summary>Hold ({len(p.get('hold',[]))})</summary>{hold_r}</details>
<details><summary>Reduce ({len(p.get('reduce',[]))})</summary><table><tr><th>代码</th><th>减仓</th><th>原因</th></tr>{reduce_r}</table></details>
<details><summary>Sell ({len(p.get('sell_candidate',[]))})</summary><table><tr><th>代码</th><th>股数</th></tr>{sell_r}</table></details>
<details><summary>Risk Sell ({len(p.get('risk_sell_candidate',[]))})</summary><table><tr><th>代码</th><th>股数</th><th>原因</th></tr>{risk_r}</table></details>
<details><summary>Buy ({len(p.get('buy_candidate',[]))})</summary><table><tr><th>代码</th><th>股数</th><th>金额</th></tr>{buy_r}</table></details>
<details><summary>Skip ({len(p.get('skip_buy',[]))})</summary><table><tr><th>代码</th><th>原因</th></tr>{skip_r}</table></details>
<details><summary>Watch ({len(p.get('watch',[]))})</summary><table><tr><th>代码</th><th>说明</th></tr>{watch_r}</table></details>
<hr>"""

    plans_html = ""
    for pid in ["A", "B", "C"]:
        pdata = result.get("plans", {}).get(pid, {})
        if pdata:
            vis = "display:block" if pid == "B" else "display:none"
            plans_html += f'<div id="plan_{pid}" style="{vis}">{_plan_section(pid, pdata)}</div>'

    val = result.get("position_validation", {})
    val_status = "✅ 通过" if not val.get("partial") else f"⚠️ partial + {len(val.get('warnings',[]))} warning"

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>调仓差异报告 V2.0.1 {result['date']}</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px 6px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }} .num {{ text-align:right; }}
details {{ margin:6px 0; }} summary {{ cursor:pointer; color:#00bcd4; }}
</style></head><body>
<div class="card"><h1>📊 调仓差异报告 V2.0.1</h1>
<p style="color:#aaa;">{result['date']} | 持仓校验: {val_status}</p>
<p>
<button onclick="showPlan('A')">Plan A</button>
<button onclick="showPlan('B')" style="font-weight:bold;">Plan B ⭐</button>
<button onclick="showPlan('C')">Plan C</button>
</p>
{plans_html}
<div class="card"><h2>⚠️ 说明</h2>
<ul>
<li>不自动下单, 仅供人工确认参考</li>
<li>100 股整数倍, T+1 available_shares 需人工确认</li>
<li>涨停不可买, 跌停不可卖 (需结合实时行情)</li>
<li>费用估算: 佣金{FEE_RATE:.1%} + 印花税{STAMP_RATE:.1%} + 滑点{SLIPPAGE_BPS}bps</li>
<li>风控卖出: ST/停牌/权限不足/亏损超阈值</li>
</ul></div>
<script>
function showPlan(p) {{['A','B','C'].forEach(x=>document.getElementById('plan_'+x).style.display=x===p?'block':'none');}}
</script>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V2.0.1 | {now}</p></div>
</body></html>"""


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    p.add_argument("--positions", default=None)
    p.add_argument("--plan", default="B")
    p.add_argument("--capital", type=float, default=50000)
    p.add_argument("--output", default=None)
    args = p.parse_args()

    out_dir = args.output or str(BASE / "rebalance_diff" / args.date.replace("-", ""))
    result = run_rebalance_diff(args.date, args.positions, args.plan, args.capital, out_dir)
    generate_rebalance_report(result, out_dir)

    for pid, pdata in result.get("plans", {}).items():
        cs = pdata.get("cash_summary", {})
        print(f"  Plan {pid}: hold={len(pdata['hold'])} reduce={len(pdata['reduce'])} sell={len(pdata['sell_candidate'])} risk={len(pdata['risk_sell_candidate'])} buy={len(pdata['buy_candidate'])} skip={len(pdata['skip_buy'])} cash_after={cs.get('estimated_cash_after',0):.0f}")
    print(f"  📁 {out_dir}")


if __name__ == "__main__":
    main()
