#!/usr/bin/env python3
"""V1.10 ETF Selector — 从 restricted 受限信号筛选 ETF 替代"""
import sys, os, json, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from pathlib import Path
from datetime import datetime, timezone, timedelta
import csv

CST = timezone(timedelta(hours=8))
BASE_OUTPUT = Path("/mnt/d/HermesReports/etf_selector")


def main():
    args = parse_args()
    print(f"\n{'='*60}")
    print(f"  V1.10 ETF Selector")
    print(f"  来源: {args.from_live_signal}")
    print(f"{'='*60}\n")

    # 1. 加载 V1.9 signal JSON
    with open(args.from_live_signal) as f:
        signal = json.load(f)

    restricted = signal.get("restricted_board_candidates", [])
    if not restricted:
        print("❌ restricted_board_candidates 为空")
        return
    print(f"  受限股票: {len(restricted)} 只")

    # 2. 加载 ETF registry
    from factor_lab.etf.etf_selector import run_etf_selector
    from factor_lab.etf.etf_universe import load_etf_registry

    registry = load_etf_registry()
    print(f"  ETF 注册表: {len(registry)} 只")

    # 3. 运行选择器
    print(f"\n  运行 ETF 选择器...")
    result = run_etf_selector(
        restricted_candidates=restricted,
        capital=args.capital,
    )

    # 4. 输出
    out_dir = args.output or str(BASE_OUTPUT / datetime.now(CST).strftime("%Y%m%d_%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)

    _write_reports(out_dir, result, registry, args.from_live_signal)
    _print_summary(result)
    print(f"\n📁 输出目录: {out_dir}")


def _print_summary(result):
    candidates = result.get("candidates", [])
    rejected = result.get("rejected", [])
    themes = result.get("themes", [])
    plan = result.get("capital_plan", {})
    print(f"\n{'='*60}")
    print(f"  V1.10 ETF Selector 完成")
    print(f"  主题: {len(themes)} | 候选: {len(candidates)} | 淘汰: {len(rejected)}")
    for t in themes:
        print(f"  📌 {t['theme']}: {t['n_candidates']} 候选, {t['n_rejected']} 淘汰, Top={t['top_etf']}")
    if plan.get("allocations"):
        print(f"  💰 资金计划: {len(plan['allocations'])} 只ETF, 已分配{plan.get('total_allocated',0):.0f}")
    print(f"{'='*60}\n")


def parse_args():
    p = argparse.ArgumentParser(description="V1.10 ETF Selector")
    p.add_argument("--from-live-signal", default="/mnt/d/HermesReports/live_signals/20260703/premarket_signal.json")
    p.add_argument("--capital", type=float, default=50000)
    p.add_argument("--output", default=None)
    return p.parse_args()


def _write_reports(out_dir, result, registry, source_path):
    # JSON
    now = datetime.now(CST).isoformat()
    report = {
        "generated_at": now,
        "source": source_path,
        **result,
    }
    with open(os.path.join(out_dir, "etf_selector.json"), "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # CSV — candidates
    _write_csv(out_dir, "etf_candidates.csv", result.get("candidates", []),
               ["etf_code", "etf_name", "theme_source", "score", "trigger_count",
                "avg_amount_20d", "aum", "expense_ratio"])
    _write_csv(out_dir, "etf_rejected.csv", result.get("rejected", []),
               ["etf_code", "etf_name", "reject_reasons"])

    # Registry snapshot
    _write_csv(out_dir, "etf_registry_snapshot.csv", registry,
               ["etf_code", "etf_name", "theme", "exchange", "tracked_index",
                "expense_ratio", "aum", "avg_amount_20d"])

    # Theme summary
    with open(os.path.join(out_dir, "etf_theme_summary.json"), "w") as f:
        json.dump(result.get("themes", []), f, indent=2)

    # Freshness
    freshness = {
        "checked_at": now,
        "registry_count": len(registry),
        "restricted_count": result.get("restricted_source_count", 0),
        "candidate_count": len(result.get("candidates", [])),
        "rejected_count": len(result.get("rejected", [])),
        "data_status": result.get("data_status", "ok"),
        "missing_fields": result.get("missing_fields", []),
    }
    with open(os.path.join(out_dir, "etf_data_freshness.json"), "w") as f:
        json.dump(freshness, f, indent=2)

    # HTML
    html = _build_html(result)
    with open(os.path.join(out_dir, "etf_selector_report.html"), "w", encoding="utf-8") as f:
        f.write(html)

    # Audit
    with open(os.path.join(out_dir, "audit.log"), "w") as f:
        f.write(_build_audit(result))


def _write_csv(out_dir, name, rows, fields):
    path = os.path.join(out_dir, name)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _build_html(result):
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    themes = result.get("themes", [])
    candidates = result.get("candidates", [])
    rejected = result.get("rejected", [])
    plan = result.get("capital_plan", {})

    t_rows = "".join(f"<tr><td>{t['theme']}</td><td>{t['trigger_count']}</td><td>{t['top_etf'] or '-'}</td><td>{t['n_candidates']}</td><td>{t['n_rejected']}</td></tr>" for t in themes)
    c_rows = "".join(f"<tr><td>{e['etf_code']}</td><td>{e['etf_name']}</td><td>{e.get('theme_source','')}</td><td class=\"num\">{e.get('score',0)}</td><td class=\"num\">{e.get('avg_amount_20d','?')}</td><td class=\"num\">{e.get('aum','?')}</td><td class=\"num\">{e.get('expense_ratio','?')}%</td><td>{e.get('score_details',{}).get('grade','?')}</td></tr>" for e in candidates[:10])
    r_rows = "".join(f"<tr><td>{e['etf_code']}</td><td>{e['etf_name']}</td><td>{'; '.join(e.get('reject_reasons',[]))}</td></tr>" for e in rejected[:10])
    p_rows = "".join(f"<tr><td>{a['etf_code']}</td><td>{a['etf_name']}</td><td>{a['theme']}</td><td class=\"num\">{a['score']}</td><td class=\"num\">{a['allocated']}</td><td class=\"num\">{a['weight_pct']}%</td></tr>" for a in plan.get("allocations", []))

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>ETF Selector V1.10 {now}</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:5px 8px; text-align:left; border-bottom:1px solid #333; }}
th {{ color:#888; font-size:0.85em; }} .num {{ text-align:right; }}
</style></head><body>
<div class="card"><h1>📈 ETF Selector V1.10</h1><p style="color:#aaa;">{now}</p>
<p>受限信号: {result.get('restricted_source_count',0)} | ETF 候选: {len(candidates)} | 淘汰: {len(rejected)} | 主题: {len(themes)}</p></div>

<div class="card"><h2>📊 受限主题汇总</h2>
<table><tr><th>主题</th><th>触发数</th><th>Top ETF</th><th>候选数</th><th>淘汰数</th></tr>{t_rows}</table></div>

<div class="card"><h2>🏆 ETF 候选排行榜 (Top10)</h2>
<table><tr><th>代码</th><th>名称</th><th>主题</th><th class="num">评分</th><th class="num">日均成交</th><th class="num">规模</th><th class="num">费率</th><th>等级</th></tr>{c_rows}</table></div>

{f'<div class="card"><h2>❌ 淘汰 ETF (Top10)</h2><table><tr><th>代码</th><th>名称</th><th>原因</th></tr>{r_rows}</table></div>' if rejected else ''}

<div class="card"><h2>💰 ETF 替代资金计划</h2>
<p>总资金: {plan.get('capital',0):.0f} | 已分配: {plan.get('total_allocated',0):.0f} | 剩余: {plan.get('remaining',0):.0f}</p>
<table><tr><th>ETF</th><th>名称</th><th>主题</th><th class="num">评分</th><th class="num">分配金额</th><th class="num">占比</th></tr>{p_rows}</table>
<p style="color:#ff9100;font-size:0.85em;">{plan.get('note','')} | 不自动下单</p></div>

<div class="card"><h2>📋 说明</h2>
<ul>
<li>ETF 注册表: {len(load_etf_registry())} 只 | 主题: {', '.join(sorted(set(e['theme'] for e in load_etf_registry())))}</li>
<li>硬性过滤: 日均成交≥3000万, 规模≥5亿, 费率≤0.6%</li>
<li>ETF 替代不是一比一复制个股收益, 而是主题暴露替代</li>
<li>持有相关 ETF 不等同于持有 trigger_symbols 股票</li>
</ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V1.10 | {now}</p></div>
</body></html>"""


def _build_audit(result):
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"=== ETF SELECTOR AUDIT V1.10 ===\n"
        f"Time: {now}\n"
        f"Restricted Source: {result.get('restricted_source_count',0)}\n"
        f"Themes: {len(result.get('themes',[]))}\n"
        f"ETF Candidates: {len(result.get('candidates',[]))}\n"
        f"ETF Rejected: {len(result.get('rejected',[]))}\n"
        f"Data Status: {result.get('data_status','?')}\n"
        f"Missing Fields: {result.get('missing_fields',[])}\n"
        f"Capital Plan: {json.dumps(result.get('capital_plan',{}))}\n"
        f"=== END ===\n"
    )


from factor_lab.etf.etf_universe import load_etf_registry

if __name__ == "__main__":
    main()
