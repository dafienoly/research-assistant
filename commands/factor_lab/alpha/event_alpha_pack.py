"""Event-driven Alpha Pack V3.5 — 解禁/回购/分红/业绩预告 事件 Alpha

注册事件驱动 Alpha 到 Alpha Registry。
所有 Alpha 默认 enabled=False, 安全边界: auto_apply=False, no_live_trade=True。

用法:
    from factor_lab.alpha.event_alpha_pack import run_event_alpha_pack
    result = run_event_alpha_pack(dry_run=True)
"""

import sys, os, json, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


# ─── Event Alpha Spec 定义 ──────────────────────────────

EVENT_ALPHA_SPECS = [
    # ── 解禁事件 (Lockup Expiry) ────────────────────────────
    {
        "name": "lockup_expiry_guard",
        "description": "解禁预警: 解禁前5天信号 (抛压预警)",
        "hypothesis": "解禁前市场预期流通盘增加, 股价承压; 但若解禁落地后抛压不及预期, 反向反弹",
        "factor_expression": "lockup_expiry_proximity (解禁前5天=1, 解禁前30天=0.5, 刚解禁=-0.3)",
        "signal_direction": "short",
        "rebalance_frequency": "weekly",
        "tags": ["event", "lockup", "v3.5", "no_live_trade"],
        "source": "lockup_expiry_proximity",
    },
    {
        "name": "lockup_density_watch",
        "description": "解禁密集区: 近90天解禁公告数>0",
        "hypothesis": "解禁公告密集的股票短期内波动率增大, 可做事件套利",
        "factor_expression": "rank(lockup_announcement_activity, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "monthly",
        "tags": ["event", "lockup", "v3.5", "no_live_trade"],
        "source": "lockup_announcement_activity",
    },
    # ── 回购事件 (Share Buyback) ──────────────────────────
    {
        "name": "buyback_confidence",
        "description": "回购信心信号: 近30天有回购公告",
        "hypothesis": "公司回购股票表明管理层认为股价低于内在价值, 是强有力的信心信号",
        "factor_expression": "buyback_signal (0/1 binary)",
        "signal_direction": "long",
        "rebalance_frequency": "daily",
        "tags": ["event", "buyback", "v3.5", "no_live_trade"],
        "source": "buyback_signal",
    },
    {
        "name": "buyback_momentum",
        "description": "回购动量: 90天内回购公告数越多=信心越强",
        "hypothesis": "多次回购公告表明公司在持续支撑股价, 后续上涨概率高",
        "factor_expression": "rank(buyback_intensity, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["event", "buyback", "v3.5", "no_live_trade"],
        "source": "buyback_intensity",
    },
    {
        "name": "buyback_recent_surge",
        "description": "回购近期加速: 近30天回购公告数",
        "hypothesis": "近期回购加速(30天内)比远期回购更具信号价值",
        "factor_expression": "rank(buyback_recent_intensity, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["event", "buyback", "v3.5", "no_live_trade"],
        "source": "buyback_recent_intensity",
    },
    # ── 分红事件 (Dividend) ──────────────────────────────
    {
        "name": "dividend_yield_value",
        "description": "高股息率选股: 每股股息/股价",
        "hypothesis": "高股息率股票具有防御属性, 在震荡市中表现优异, 长期持有收益稳定",
        "factor_expression": "rank(dividend_yield_factor, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "monthly",
        "tags": ["event", "dividend", "v3.5", "no_live_trade"],
        "source": "dividend_yield_factor",
    },
    {
        "name": "dividend_fill_window",
        "description": "填权窗口: 除权除息后30天内",
        "hypothesis": "除息后填权效应: 多数A股在除息后30天内存在填权行情",
        "factor_expression": "ex_dividend_proximity (除息30天内=1, 30-60天=0.5)",
        "signal_direction": "long",
        "rebalance_frequency": "daily",
        "tags": ["event", "dividend", "v3.5", "no_live_trade"],
        "source": "ex_dividend_proximity",
    },
    {
        "name": "dividend_generosity",
        "description": "分红慷慨度: 每股股息金额越高=分红越慷慨",
        "hypothesis": "每股股息金额反映公司分红意愿和现金流状况, 高分红公司质量更好",
        "factor_expression": "rank(dividend_amount_factor, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "monthly",
        "tags": ["event", "dividend", "v3.5", "no_live_trade"],
        "source": "dividend_amount_factor",
    },
    # ── 业绩预告事件 (Earnings Forecast) ───────────────────
    {
        "name": "forecast_positive_catalyst",
        "description": "业绩预增催化剂: 预告类型为预增/略增/扭亏",
        "hypothesis": "业绩预增公告是股价上涨的催化剂, 预告后短期内正超额收益显著",
        "factor_expression": "forecast_upgrade_signal (预增=1, 略增=0.5, 扭亏=0.8)",
        "signal_direction": "long",
        "rebalance_frequency": "daily",
        "tags": ["event", "forecast", "v3.5", "no_live_trade"],
        "source": "forecast_upgrade_signal",
    },
    {
        "name": "forecast_negative_warning",
        "description": "业绩预减预警: 预告类型为预减/续亏/首亏",
        "hypothesis": "业绩预减公告是股价下跌的预警信号, 预告后应规避",
        "factor_expression": "forecast_downgrade_signal (预减=-1, 续亏=-0.8, 首亏=-1)",
        "signal_direction": "short",
        "rebalance_frequency": "daily",
        "tags": ["event", "forecast", "v3.5", "no_live_trade"],
        "source": "forecast_downgrade_signal",
    },
    {
        "name": "forecast_trend_momentum",
        "description": "业绩预告趋势动量: 90天内预增数-预减数",
        "hypothesis": "一段时间内正面预告多于负面预告的公司, 基本面趋势持续向好",
        "factor_expression": "rank(forecast_momentum_signal, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "monthly",
        "tags": ["event", "forecast", "momentum", "v3.5", "no_live_trade"],
        "source": "forecast_momentum_signal",
    },
    # ── 事件复合 ────────────────────────────────────────
    {
        "name": "event_composite_alpha",
        "description": "多事件复合: 回购+预增+除息-解禁预警",
        "hypothesis": "多事件信号共振比单一事件信号更稳定, 多事件正向叠加预示超额收益",
        "factor_expression": "event_composite_score (回购+1, 预增+0.5, 预减-0.5, 除息+0.3, 解禁-0.3)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["event", "composite", "multi_event", "v3.5", "no_live_trade"],
        "source": "event_composite_score",
    },
]


def run_event_alpha_pack(dry_run=True):
    """创建 Event-driven Alpha Pack

    参数:
        dry_run: True=仅生成报告, 不实际注册到 Alpha Registry
                  False=实际注册到 Alpha Registry (所有 Alpha 为 disabled)

    返回:
        dict: 包含 run_id, 各统计量, 列表
    """
    from factor_lab.alpha.schema import AlphaSpec
    from factor_lab.factor_base import list_factors

    all_factors = list_factors()
    factor_names = {f["name"] for f in all_factors}

    registered = []
    sources_missing = []

    sid = datetime.now(CST).strftime("%Y%m%d_%H%M%S_%f")
    out_dir = BASE / "event_alpha_pack" / sid
    out_dir.mkdir(parents=True, exist_ok=True)

    for spec_def in EVENT_ALPHA_SPECS:
        source = spec_def.get("source", "")
        if source and source not in factor_names:
            sources_missing.append({"name": spec_def["name"], "missing": source})
            continue

        try:
            spec = AlphaSpec(
                name=spec_def["name"],
                description=spec_def["description"],
                hypothesis=spec_def["hypothesis"],
                factor_expression=spec_def["factor_expression"],
                universe="all_watchlist",
                signal_direction=spec_def["signal_direction"],
                rebalance_frequency=spec_def["rebalance_frequency"],
                status="registered",
                author="system",
                source=f"event_alpha_pack.py:{spec_def['name']}",
                enabled=False,
                paper_enabled=False,
                live_enabled=False,
                tags=spec_def["tags"] + ["no_live_trade"],
            )
            if not dry_run:
                from factor_lab.alpha.registry import register_alpha
                result = register_alpha(spec)
                registered.append({
                    "name": spec_def["name"],
                    "alpha_id": result["alpha_id"],
                    "alpha_dir": result["alpha_dir"],
                })
            else:
                registered.append({
                    "name": spec_def["name"],
                    "alpha_id": f"DRY_RUN_{spec_def['name']}",
                })
        except Exception as e:
            sources_missing.append({"name": spec_def["name"], "error": str(e)})

    result = {
        "run_id": sid,
        "dry_run": dry_run,
        "version": "V3.5",
        "label": "Event-driven Alpha Pack",
        "specs_defined": len(EVENT_ALPHA_SPECS),
        "registered": len(registered),
        "sources_missing": len(sources_missing),
        "registered_list": registered,
        "missing_list": sources_missing,
        "all_enabled_false": True,
        "auto_apply": False,
        "no_live_trade": True,
    }

    _write_event_alpha_outputs(result, out_dir)
    return result


def _write_event_alpha_outputs(result, out_dir):
    """写入 V3.5 Event-driven Alpha Pack 报告"""
    registered = result.get("registered_list", [])
    missing = result.get("missing_list", [])

    # JSON
    with open(out_dir / "event_alpha_pack.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # CSV: 已注册
    with open(out_dir / "event_alphas_registered.csv", "w", newline="", encoding="utf-8-sig") as f:
        if registered:
            fieldnames = list(registered[0].keys())
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(registered)
        else:
            w = csv.writer(f)
            w.writerow(["name", "alpha_id"])
            for r in registered:
                w.writerow([r["name"], r["alpha_id"]])

    # CSV: 缺失依赖
    with open(out_dir / "event_sources_missing.csv", "w", newline="", encoding="utf-8-sig") as f:
        fieldnames = ["name", "missing"] if not any("error" in m for m in missing) else ["name", "error"]
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(missing)

    # HTML 报告
    rows_reg = "".join(
        f"<tr><td>{r['name']}</td><td>{r.get('alpha_id','')}</td><td>🔴 disabled</td></tr>"
        for r in registered
    )
    rows_missing = "".join(
        f"<tr><td>{m['name']}</td><td>{m.get('missing', m.get('error',''))}</td></tr>"
        for m in missing
    )
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Event-driven Alpha Pack V3.5</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#ff6b6b; }} h2 {{ color:#ff6b6b; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
.event-badge {{ display:inline-block; padding:2px 8px; border-radius:4px; margin:2px; font-size:0.8em; }}
.lockup {{ background:#c0392b; }} .buyback {{ background:#27ae60; }}
.dividend {{ background:#f39c12; }} .forecast {{ background:#2980b9; }}
.composite {{ background:#8e44ad; }}
</style></head><body>
<div class="card"><h1>📅 Event-driven Alpha Pack V3.5</h1>
<p>Run: {result['run_id']} | Dry-run: {result['dry_run']}</p>
<p>Specs Defined: {result['specs_defined']} | Registered: {result['registered']} | Missing Deps: {result['sources_missing']}</p></div>
<div class="card"><h2>📋 Registered Event Alphas</h2>
<table><tr><th>Name</th><th>Alpha ID</th><th>Status</th></tr>{rows_reg}</table></div>
""" + (f"""<div class="card"><h2>⚠️ Missing Dependencies</h2>
<table><tr><th>Name</th><th>Missing Source</th></tr>{rows_missing}</table></div>""" if missing else "") + """
<div class="card"><h2>🛡️ Safety</h2>
<ul>
<li>All enabled=False, paper_enabled=False, live_enabled=False</li>
<li>auto_apply=False, no_live_trade=True</li>
<li>No broker/miniqmt called</li>
<li>No paper/live config modified</li>
<li>No auto-backtest triggered</li>
</ul></div>
<div class="card"><h2>📊 Factor Composition</h2>
<table><tr><th>Alpha</th><th>Factor Expression</th><th>Event Type</th></tr>
""" + "\n".join(
    f"<tr><td>{s['name']}</td><td><code>{s['factor_expression']}</code></td>"
    f"<td>{'🔴 解禁' if 'lockup' in s['name'] else '🟢 回购' if 'buyback' in s['name'] else '🟡 分红' if 'dividend' in s['name'] else '🔵 业绩预告' if 'forecast' in s['name'] else '🟣 复合'}</td></tr>"
    for s in EVENT_ALPHA_SPECS
) + """
</table></div>
<div class="card"><h2>📈 Data Sources</h2>
<table><tr><th>Category</th><th>Data Source</th><th>Status</th></tr>
<tr><td>🔴 解禁 / 回购 / 分红公告</td><td>announcements_extracted.csv</td><td>⏳ Available</td></tr>
<tr><td>🟡 分红除权数据</td><td>adjust_factor.csv (dividend字段)</td><td>⏳ Available</td></tr>
<tr><td>🔵 业绩预告</td><td>forecast_report.csv</td><td>⏳ Available</td></tr>
</table></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V3.5 — Event-driven Alpha Pack | 解禁 · 回购 · 分红 · 业绩预告</p></div>
</body></html>"""
    with open(out_dir / "event_alpha_pack_report.html", "w") as f:
        f.write(html)

    # Markdown 摘要
    # 按类别分组
    categories = {}
    for s in EVENT_ALPHA_SPECS:
        if "lockup" in s["name"]:
            cat = "解禁 Lockup"
        elif "buyback" in s["name"]:
            cat = "回购 Buyback"
        elif "dividend" in s["name"]:
            cat = "分红 Dividend"
        elif "forecast" in s["name"]:
            cat = "业绩预告 Forecast"
        else:
            cat = "复合 Composite"
        categories.setdefault(cat, []).append(s)

    cat_summary = "\n".join(
        f"### {cat}\n" + "\n".join(f"  - **{s['name']}**: {s['hypothesis']}" for s in specs)
        for cat, specs in categories.items()
    )
    summary = f"""# Event-driven Alpha Pack V3.5

Run: {result['run_id']} | Dry-run: {result['dry_run']}

## Overview
- Specs defined: {result['specs_defined']}
- Registered: {result['registered']}
- Missing dependencies: {result['sources_missing']}
- All alphas disabled: {result['all_enabled_false']}

## Alpha Specs by Category

{cat_summary}

## Safety
- All enabled=False, paper_enabled=False, live_enabled=False
- auto_apply=False, no_live_trade=True
- No broker/miniqmt
- No auto-backtest triggered

## Data Sources
- Announcements (解禁/回购/分红公告): announcements_extracted.csv
- Adjust Factor (分红数据): adjust_factor.csv
- Forecast Report (业绩预告): forecast_report.csv

## Gate: Event Date Separation
V3.5 的关键验证: 事件日期分离。确保事件在公告日后有独立的影响窗口,
避免事件日与其他因子(动量/反转)的信息污染。
"""
    with open(out_dir / "event_alpha_pack_summary.md", "w") as f:
        f.write(summary)

    # 打印
    print(f"\n{'='*60}")
    print(f"  📅 Event-driven Alpha Pack V3.5")
    print(f"  Dry-run: {result['dry_run']}")
    print(f"  Specs: {result['specs_defined']} | Registered: {result['registered']} | Missing: {result['sources_missing']}")
    print(f"  All enabled=False | auto_apply=False | no_live_trade=True")
    print(f"  📁 {out_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    args = parser.parse_args()
    run_event_alpha_pack(dry_run=args.dry_run)
