#!/usr/bin/env python3
"""V1.11 Unified Premarket Decision Report — 合并 V1.9+V1.10 输出"""
import sys, os, json, argparse, csv
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from pathlib import Path
from datetime import datetime, timezone, timedelta
from copy import deepcopy

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")
LIVE_SIGNAL = BASE / "live_signals" / "20260703" / "premarket_signal.json"
ETF_SELECTOR = BASE / "etf_selector" / "20260704_211305" / "etf_selector.json"


def main():
    args = parse_args()
    capital = args.capital

    # 1. Load inputs
    live = _load_json(args.from_live_signal)
    etf = _load_json(args.from_etf_selector) if args.with_etf else {}

    # 2. Extract streams
    raw = live.get("raw_target_candidates", [])
    self_t = live.get("self_tradable_target_candidates", [])
    restricted = live.get("restricted_board_candidates", [])
    readiness = live.get("readiness", {})
    etf_candidates = etf.get("candidates", []) if etf else []
    etf_themes = etf.get("themes", []) if etf else []
    etf_plan = etf.get("capital_plan", {}) if etf else {}
    etf_missing = etf.get("missing_fields", {}) if etf else {}

    # 3. Capital plans
    plans = _build_plans(self_t, etf_candidates, capital)

    # 4. Unified readiness
    uni_readiness = _unified_readiness(readiness, etf)

    # 将 etf_substitution_readiness 从 framework_ready 改为 selector_ready_partial_data
    if readiness.get("etf_substitution_readiness") == "framework_ready":
        readiness["etf_substitution_readiness"] = "selector_ready_partial_data"
        readiness["etf_selector_readiness"] = "usable_with_warning"

    # 5. Build output
    out_dir = args.output or str(BASE / "unified_premarket" / args.signal_date.replace("-", ""))
    os.makedirs(out_dir, exist_ok=True)

    result = {
        "signal_date": args.signal_date,
        "generated_at": datetime.now(CST).isoformat(),
        "capital": capital,
        "unified_readiness": uni_readiness,
        "readiness": readiness,
        "etf_data_freshness": etf.get("data_status", "not_available") if etf else "not_available",
        "summary": _generate_summary(self_t, restricted, etf_themes, uni_readiness),
        "self_stock_candidates": {
            "top5": self_t[:5], "top8": self_t[:8],
            "total": len(self_t),
        },
        "restricted_signal_summary": {
            "total": len(restricted),
            "by_board": {},
        },
        "etf_substitution_summary": {
            "themes": etf_themes, "candidates": etf_candidates,
            "data_partial": bool("holdings" in str(etf_missing)),
        },
        "allocation_plans": plans,
        "excluded": _build_excluded(live),
    }

    # 写入
    _write_all(out_dir, result, self_t, etf_candidates)

    # 摘要
    _print_summary(result)
    print(f"\n📁 {out_dir}")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--signal-date", default="2026-07-03")
    p.add_argument("--capital", type=float, default=50000)
    p.add_argument("--from-live-signal", default=str(LIVE_SIGNAL))
    p.add_argument("--from-etf-selector", default=str(ETF_SELECTOR))
    p.add_argument("--with-etf", action="store_true", default=True)
    p.add_argument("--output", default=None)
    return p.parse_args()


def _load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _generate_summary(self_t, restricted, etf_themes, uni_readiness):
    return (
        f"今日 ret5_ma20_gate 信号可用。"
        f"主账户可交易候选 {len(self_t)} 只，"
        f"受限强信号 {len(restricted)} 只，"
        f"ETF 替代主题 {len(etf_themes)} 个。"
        f"建议优先关注主板 Top5/Top8，"
        f"同时{'、'.join(t['theme']+'ETF' for t in etf_themes[:2])}替代受限板块暴露。"
        f"Readiness: {uni_readiness}"
    )


def _unified_readiness(readiness, etf):
    sr = readiness.get("strategy_signal_readiness")
    sa = readiness.get("self_account_readiness")
    if not etf:
        return "usable_with_warning" if sa == "ready" else "partial"
    etf_ok = etf.get("data_status") == "ok"
    if sr == "ready" and sa == "ready":
        return "ready" if etf_ok else "usable_with_warning"
    return "partial" if sa or sr else "failed"


def _build_plans(self_t, etf_candidates, capital):
    def _stock_alloc(symbols, alloc):
        lots, remaining = [], alloc
        for c in symbols:
            close = float(c.get("close", 10) or 10)
            shares = max(100, int(remaining * 0.25 / close / 100) * 100)
            cost = shares * close
            if cost > remaining:
                shares = max(100, int(remaining / close / 100) * 100)
                cost = shares * close
            if shares < 100 or cost > remaining:
                break
            lots.append({"symbol": c["symbol"], "close": round(close, 2),
                         "shares": shares, "cost": round(cost, 2),
                         "weight": round(cost / capital * 100, 1)})
            remaining -= cost
        return lots, round(remaining, 2)

    def _etf_alloc(etfs, alloc):
        if not etfs or alloc <= 0:
            return [], alloc
        per = alloc / len(etfs)
        lots = []
        for e in etfs:
            shares = max(100, int(per / 1.0 / 100) * 100)
            lots.append({"etf_code": e["etf_code"], "etf_name": e["etf_name"],
                         "theme": e.get("theme_source", ""),
                         "shares": shares, "cost": round(shares * 1.0, 2),
                         "weight": round(shares * 1.0 / capital * 100, 1)})
        total = sum(l["cost"] for l in lots)
        return lots, round(capital - sum(l["cost"] for l in lots) - alloc + total, 2)

    top5 = self_t[:5]
    top8 = self_t[:8]
    top_etf = etf_candidates[:2] if etf_candidates else []

    plans = {}
    for name, stock_share, etf_share, stocks in [
        ("conservative", 0.70, 0.30, top5),
        ("balanced", 0.50, 0.50, top8),
        ("aggressive", 0.30, 0.70, top5),
    ]:
        s_alloc = capital * stock_share
        e_alloc = capital * etf_share
        s_lots, s_rem = _stock_alloc(stocks, s_alloc)
        e_lots, e_rem = _etf_alloc(top_etf, e_alloc)
        used = sum(l["cost"] for l in s_lots) + sum(l["cost"] for l in e_lots)
        plans[name] = {
            "desc": {"conservative": "70%股票+30%ETF", "balanced": "50%股票+50%ETF",
                     "aggressive": "30%股票+70%ETF"}[name],
            "self_stock_alloc": round(s_alloc, 2),
            "etf_alloc": round(e_alloc, 2),
            "self_stock_lots": s_lots,
            "etf_lots": e_lots,
            "total_used": round(used, 2),
            "remaining_cash": round(capital - used, 2),
        }
    return plans


def _build_excluded(live):
    excluded = []
    risk = live.get("risk_excluded", [])
    for r in risk:
        excluded.append({"symbol": r.get("symbol", ""), "reason": f"风控: {r.get('risk_type','')}", "type": "risk"})
    non_tradable = [{"symbol": c.get("symbol", ""), "reason": "账户权限: 科创/创业板", "type": "permission"}
                    for c in live.get("restricted_board_candidates", [])]
    excluded.extend(non_tradable)
    return excluded


def _write_all(out_dir, result, self_t, etf_candidates):
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    # JSON
    with open(os.path.join(out_dir, "unified_premarket_report.json"), "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # readiness
    with open(os.path.join(out_dir, "readiness_summary.json"), "w") as f:
        json.dump(result["unified_readiness"], f, indent=2)

    # CSVs
    _csv(out_dir, "self_stock_plan.csv", self_t[:10],
         ["symbol", "close", "ret5", "rank"])
    _csv(out_dir, "etf_substitution_plan.csv", etf_candidates[:3],
         ["etf_code", "etf_name", "theme", "score"])
    _csv(out_dir, "restricted_signal_summary.csv", result.get("restricted", []),
         ["symbol", "board", "original_rank", "ret5", "suggested_path"])
    _csv(out_dir, "excluded_signal_summary.csv", result.get("excluded", []),
         ["symbol", "reason", "type"])

    # Plan details
    for pname, pdata in result.get("allocation_plans", {}).items():
        _csv(out_dir, f"allocation_plan_{pname}.csv", pdata.get("self_stock_lots", []) + pdata.get("etf_lots", []),
             ["symbol", "etf_code", "shares", "cost", "weight"])

    # HTML
    html = _build_html(result, now)
    with open(os.path.join(out_dir, "unified_premarket_report.html"), "w", encoding="utf-8") as f:
        f.write(html)

    # audit
    with open(os.path.join(out_dir, "audit.log"), "w") as f:
        f.write(_audit(result, now))


def _csv(out_dir, name, rows, fields):
    path = os.path.join(out_dir, name)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _build_html(result, now):
    r = result
    ur = r["unified_readiness"]
    ur_c = {"ready": "#00c853", "usable_with_warning": "#ff9100", "partial": "#ff1744", "failed": "#888"}.get(ur, "#888")

    def bdg(v):
        c = {"ready": "#00c853", "partial": "#ff9100", "not_ready": "#ff1744", "no_signal": "#888"}.get(v, "#888")
        return f'<span class="badge" style="background:{c}22;color:{c};">{v}</span>'

    ri = r["readiness"]
    top5 = r.get("self_stock_candidates", {}).get("top5", [])
    top8 = r.get("self_stock_candidates", {}).get("top8", [])

    st5 = "".join(f"<tr><td>{i+1}</td><td>{c['symbol']}</td><td class=\"num\">{c.get('ret5',0)*100:.1f}%</td><td class=\"num\">{c.get('close','')}</td></tr>" for i,c in enumerate(top5))
    st8 = "".join(f"<tr><td>{i+1}</td><td>{c['symbol']}</td><td class=\"num\">{c.get('ret5',0)*100:.1f}%</td></tr>" for i,c in enumerate(top8))

    etf_cands = r.get("etf_substitution_summary", {}).get("candidates", [])
    etf_rows = "".join(f"<tr><td>{c['etf_code']} {c['etf_name']}</td><td>{c.get('theme_source','')}</td><td class=\"num\">{c.get('score',0)}</td></tr>" for c in etf_cands)
    etf_section = ""
    if etf_cands:
        etf_section = f"""<div class="card"><h2>📈 ETF 替代方案</h2><table><tr><th>ETF</th><th>主题</th><th class="num">评分</th></tr>{etf_rows}</table>
<p style="color:#ff9100;font-size:0.85em;">数据 partial, 持仓数据不可用, 替代存在误差</p></div>"""

    plan_b = r.get("allocation_plans", {}).get("balanced", {})
    pb_rows = "".join(f"<tr><td>{l.get('symbol') or l.get('etf_code','')}</td><td>{'ETF' if l.get('etf_code') else '股票'}</td><td class=\"num\">{l['shares']}</td><td class=\"num\">{l['cost']}</td><td class=\"num\">{l['weight']}%</td></tr>" for l in (plan_b.get("self_stock_lots",[]) + plan_b.get("etf_lots",[])))

    pa = r.get("allocation_plans", {}).get("conservative", {})
    pc = r.get("allocation_plans", {}).get("aggressive", {})

    excl_rows = "".join(f"<tr><td>{e['symbol']}</td><td>{e['reason']}</td></tr>" for e in r.get("excluded", [])[:15])

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>盘前决策报告 {r['signal_date']}</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:5px 8px; text-align:left; border-bottom:1px solid #333; }}
th {{ color:#888; font-size:0.85em; }} .num {{ text-align:right; }}
.badge {{ display:inline-block; padding:2px 10px; border-radius:3px; font-size:0.85em; }}
</style></head><body>
<div class="card"><h1>📊 盘前决策报告</h1>
<p style="color:#aaa;">{r['signal_date']} | 资金: {r['capital']:.0f}</p>
<p>统一: <span class="badge" style="background:{ur_c}22;color:{ur_c};">{ur}</span>
策略: {bdg(ri.get('strategy_signal_readiness','?'))}
自营: {bdg(ri.get('self_account_readiness','?'))}
受限: {bdg(ri.get('restricted_signal_readiness','?'))}
ETF: {bdg(ri.get('etf_substitution_readiness','?'))}</p>
</div>

<div class="card"><h2>📋 今日主结论</h2><p>{r['summary']}</p></div>

<div class="card"><h2>✅ Self 股票 Top5</h2><table><tr><th>#</th><th>代码</th><th class="num">ret5</th><th class="num">收盘</th></tr>{st5}</table></div>

<div class="card"><h2>✅ Self 股票 Top8</h2><table><tr><th>#</th><th>代码</th><th class="num">ret5</th></tr>{st8}</table></div>

{etf_section}

<div class="card"><h2>💰 默认资金计划 (均衡版 Plan B)</h2>
<table><tr><th>标的</th><th>类型</th><th class="num">股数</th><th class="num">金额</th><th class="num">占比</th></tr>
{pb_rows}</table>
<p style="color:#aaa;">已分配 {plan_b.get('total_used',0):.0f} 剩余 {plan_b.get('remaining_cash',0):.0f}</p></div>

<div class="card"><h2>💰 三套参考方案</h2>
<table><tr><th>方案</th><th>股票%</th><th>ETF%</th><th class="num">已分配</th><th class="num">剩余</th></tr>
<tr><td>A 保守</td><td>70%</td><td>30%</td><td class="num">{pa.get('total_used',0):.0f}</td><td class="num">{pa.get('remaining_cash',0):.0f}</td></tr>
<tr><td>B 均衡</td><td>50%</td><td>50%</td><td class="num">{plan_b.get('total_used',0):.0f}</td><td class="num">{plan_b.get('remaining_cash',0):.0f}</td></tr>
<tr><td>C 进攻</td><td>30%</td><td>70%</td><td class="num">{pc.get('total_used',0):.0f}</td><td class="num">{pc.get('remaining_cash',0):.0f}</td></tr>
</table></div>

<div class="card"><h2>🚫 不执行清单 ({len(r.get('excluded',[]))} 项)</h2>
<table><tr><th>代码</th><th>原因</th></tr>{excl_rows}</table>
<p style="color:#888;font-size:0.85em;">仅展示前 15 项。完整列表见 restricted_signal_summary.csv / excluded_signal_summary.csv</p></div>

<div class="card"><h2>⚠️ 风险提示</h2>
<ul>
<li>本信号仅供参考, 不构成投资建议, 不自动下单</li>
<li>ETF 替代不等于持有个股, 持仓数据不可用(partial)</li>
<li>盘中行情和公告可能改变结论, 需人工确认</li>
<li>资金计划为参考配置, 不自动执行</li>
<li>禁止借用他人账户交易</li>
</ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V1.11 Unified Premarket | {now}</p></div>
</body></html>"""


def _audit(result, now):
    r = result
    return (
        f"=== UNIFIED PREMARKET AUDIT V1.11 ===\n"
        f"Time: {now}\nSignal Date: {r['signal_date']}\n"
        f"Capital: {r['capital']}\n"
        f"Unified Readiness: {r['unified_readiness']}\n"
        f"Self Stock Top5: {[c['symbol'] for c in r.get('self_stock_candidates',{}).get('top5',[])]}\n"
        f"Restricted: {r.get('restricted_signal_summary',{}).get('total',0)}\n"
        f"ETF Candidates: {len(r.get('etf_substitution_summary',{}).get('candidates',[]))}\n"
        f"Excluded: {len(r.get('excluded',[]))}\n"
        f"Plans: {list(r.get('allocation_plans',{}).keys())}\n"
        f"No auto-order: True\nNo borrowed account: True\n"
        f"=== END ===\n"
    )


def _print_summary(result):
    r = result
    print(f"\n{'='*60}")
    print(f"  V1.11 Unified Premarket Report")
    print(f"  Readiness: {r['unified_readiness']}")
    print(f"  Self: {r.get('self_stock_candidates',{}).get('total',0)} | Restricted: {r.get('restricted_signal_summary',{}).get('total',0)}")
    print(f"  ETF: {len(r.get('etf_substitution_summary',{}).get('candidates',[]))} 候选 | Excluded: {len(r.get('excluded',[]))} 项")
    print(f"  Plans: A={r.get('allocation_plans',{}).get('conservative',{}).get('total_used',0):.0f} "
          f"B={r.get('allocation_plans',{}).get('balanced',{}).get('total_used',0):.0f} "
          f"C={r.get('allocation_plans',{}).get('aggressive',{}).get('total_used',0):.0f}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
