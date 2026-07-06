"""Data Enrichment Alpha Pack V3.3 — 北向/两融/资金流增强 Alpha

注册数据增强 Alpha 到 Alpha Registry。
所有 Alpha 默认 enabled=False, 安全边界: auto_apply=False, no_live_trade=True。

用法:
    from factor_lab.alpha.data_enrichment_alpha_pack import run_data_enrichment_pack
    result = run_data_enrichment_pack(dry_run=True)
"""

import sys, os, json, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


# ─── Data Enrichment Alpha Spec 定义 ──────────────────────────────

DATA_ENRICHMENT_ALPHA_SPECS = [
    # ── 资金流增强 (Fund Flow Enhanced) ────────────────────────
    {
        "name": "fund_flow_composite_alpha",
        "description": "资金流综合得分: 主力+超大单rank - 小单rank",
        "hypothesis": "机构买入+散户卖出的资金结构预示着健康的上涨趋势",
        "factor_expression": "rank(net_main_force) + rank(net_super_large) - rank(net_small), normalized",
        "signal_direction": "long",
        "rebalance_frequency": "daily",
        "tags": ["fund_flow", "composite", "v3.3", "no_live_trade"],
        "source": "net_flow_composite",
    },
    {
        "name": "institutional_flow_leader",
        "description": "机构资金主导: institutional_flow_ratio > 0.6",
        "hypothesis": "机构资金主导买盘的股票比散户主导的更有持续性",
        "factor_expression": "rank(institutional_flow_ratio, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "daily",
        "tags": ["fund_flow", "institutional", "v3.3", "no_live_trade"],
        "source": "institutional_flow_ratio",
    },
    {
        "name": "flow_divergence_momentum",
        "description": "5日资金分化动量",
        "hypothesis": "机构持续买入、散户持续卖出的股票具有最强的上涨动力",
        "factor_expression": "rank(flow_divergence_5d, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["fund_flow", "divergence", "momentum", "v3.3", "no_live_trade"],
        "source": "flow_divergence_5d",
    },
    {
        "name": "super_large_resonance",
        "description": "超大单共振: 超大单净流入 × 动量",
        "hypothesis": "机构级超大单配合上涨趋势是最强信号",
        "factor_expression": "rank(super_large_flow_mom, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["fund_flow", "super_large", "resonance", "v3.3", "no_live_trade"],
        "source": "super_large_flow_mom",
    },
    {
        "name": "consecutive_capital_inflow",
        "description": "连续资金流入: 主力连续净流入>=3天",
        "hypothesis": "连续多日主力资金流入说明有资金持续关注",
        "factor_expression": "rank(consecutive_inflow, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "daily",
        "tags": ["fund_flow", "consecutive", "v3.3", "no_live_trade"],
        "source": "consecutive_inflow",
    },
    # ── 北向资金 (North-bound Capital) ─────────────────────────
    {
        "name": "north_flow_alpha",
        "description": "北向净流入强度: 北向资金当日净流入",
        "hypothesis": "北向资金(外资)净流入的股票通常有超额收益",
        "factor_expression": "rank(nb_net_flow_1d, ascending=False) if nb_net_flow exists",
        "signal_direction": "long",
        "rebalance_frequency": "daily",
        "tags": ["north_bound", "capital_flow", "v3.3", "no_live_trade"],
        "source": "nb_net_flow_1d",
    },
    {
        "name": "north_holding_increase",
        "description": "北向持仓增加: 5日北向持仓变动为正",
        "hypothesis": "外资持续加仓的股票中长期表现更优",
        "factor_expression": "rank(nb_holding_change_5d, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["north_bound", "holding", "v3.3", "no_live_trade"],
        "source": "nb_holding_change_5d",
    },
    {
        "name": "north_flow_momentum",
        "description": "北向动量: 北向净流入 × 5日收益",
        "hypothesis": "外资流入叠加股价上涨=双确认, 预示趋势持续",
        "factor_expression": "rank(nb_flow_momentum, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["north_bound", "momentum", "v3.3", "no_live_trade"],
        "source": "nb_flow_momentum",
    },
    # ── 两融 (Margin Trading & Securities Lending) ──────────────
    {
        "name": "margin_net_buy_alpha",
        "description": "融资净买入强度: 融资买入-偿还",
        "hypothesis": "融资净买入代表杠杆资金做多意愿, 预示短期上涨",
        "factor_expression": "rank(margin_net_buy, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "daily",
        "tags": ["margin", "leverage", "v3.3", "no_live_trade"],
        "source": "margin_net_buy",
    },
    {
        "name": "margin_balance_surge",
        "description": "融资余额激增: 5日融资余额增速",
        "hypothesis": "融资余额快速增长说明杠杆资金持续看好",
        "factor_expression": "rank(margin_balance_change_5d, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["margin", "balance", "v3.3", "no_live_trade"],
        "source": "margin_balance_change_5d",
    },
    {
        "name": "margin_long_sentiment",
        "description": "融资融券比: 融资余额/融券余额",
        "hypothesis": "融资余额远高于融券余额代表市场做多情绪强烈",
        "factor_expression": "rank(margin_sec_lending_ratio, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "monthly",
        "tags": ["margin", "sentiment", "v3.3", "no_live_trade"],
        "source": "margin_sec_lending_ratio",
    },
    {
        "name": "margin_flow_momentum",
        "description": "两融动量: 融资净买入×5日收益",
        "hypothesis": "杠杆资金+上涨共振是最强短期信号",
        "factor_expression": "rank(margin_flow_momentum, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["margin", "momentum", "v3.3", "no_live_trade"],
        "source": "margin_flow_momentum",
    },
    {
        "name": "sec_lending_decrease",
        "description": "融券余额减少: 融券余额5日下降",
        "hypothesis": "融券余额下降代表做空力量减弱, 利好股价",
        "factor_expression": "rank(-sec_lending_change_5d, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["margin", "short_selling", "v3.3", "no_live_trade"],
        "source": "sec_lending_change_5d_neg",
    },
]


def run_data_enrichment_pack(dry_run=True):
    """创建 Data Enrichment Alpha Pack

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
    out_dir = BASE / "data_enrichment_alpha_pack" / sid
    out_dir.mkdir(parents=True, exist_ok=True)

    for spec_def in DATA_ENRICHMENT_ALPHA_SPECS:
        source = spec_def.get("source", "")
        if source and source not in factor_names:
            # sec_lending_change_5d_neg 是计算派生名, 映射到实际因子
            alt_source = source.replace("_neg", "")
            if alt_source != source and alt_source in factor_names:
                pass  # 因子实际存在 (只是映射名不同)
            else:
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
                source=f"data_enrichment_alpha_pack.py:{spec_def['name']}",
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
        "version": "V3.3",
        "label": "Data Enrichment Alpha Pack",
        "specs_defined": len(DATA_ENRICHMENT_ALPHA_SPECS),
        "registered": len(registered),
        "sources_missing": len(sources_missing),
        "registered_list": registered,
        "missing_list": sources_missing,
        "all_enabled_false": True,
        "auto_apply": False,
        "no_live_trade": True,
    }

    _write_data_enrichment_outputs(result, out_dir)
    return result


def _write_data_enrichment_outputs(result, out_dir):
    """写入 V3.3 Data Enrichment Alpha Pack 报告"""
    registered = result.get("registered_list", [])
    missing = result.get("missing_list", [])

    # JSON
    with open(out_dir / "data_enrichment_alpha_pack.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # CSV: 已注册
    with open(out_dir / "data_enrichment_alphas_registered.csv", "w", newline="", encoding="utf-8-sig") as f:
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
    with open(out_dir / "data_enrichment_sources_missing.csv", "w", newline="", encoding="utf-8-sig") as f:
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
<html><head><meta charset="utf-8"><title>Data Enrichment Alpha Pack V3.3</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
</style></head><body>
<div class="card"><h1>📊 Data Enrichment Alpha Pack V3.3</h1>
<p>Run: {result['run_id']} | Dry-run: {result['dry_run']}</p>
<p>Specs Defined: {result['specs_defined']} | Registered: {result['registered']} | Missing Deps: {result['sources_missing']}</p></div>
<div class="card"><h2>📋 Registered Data Enrichment Alphas</h2>
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
<table><tr><th>Alpha</th><th>Factor Expression</th></tr>
""" + "\n".join(
    f"<tr><td>{s['name']}</td><td><code>{s['factor_expression']}</code></td></tr>"
    for s in DATA_ENRICHMENT_ALPHA_SPECS
) + """
</table></div>
<div class="card"><h2>📈 Data Source Coverage</h2>
<table><tr><th>Category</th><th>Data Source</th><th>Status</th></tr>
<tr><td>资金流 Fund Flow</td><td>fund_flow_timeseries.csv</td><td>✅ Available</td></tr>
<tr><td>北向 North-bound</td><td>north_flow_timeseries.csv</td><td>⏳ Pending</td></tr>
<tr><td>两融 Margin</td><td>margin_timeseries.csv</td><td>⏳ Pending</td></tr>
</table></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V3.3 — Data Enrichment Alpha Pack</p></div>
</body></html>"""
    with open(out_dir / "data_enrichment_alpha_pack_report.html", "w") as f:
        f.write(html)

    # Markdown 摘要
    spec_lines = "\n".join(
        f"  - **{s['name']}**: {s['hypothesis']}" for s in DATA_ENRICHMENT_ALPHA_SPECS
    )

    # 按类目分组
    categories = {}
    for s in DATA_ENRICHMENT_ALPHA_SPECS:
        cat = "资金流" if s["source"] in ("net_flow_composite", "institutional_flow_ratio",
                                            "flow_divergence_5d", "super_large_flow_mom",
                                            "consecutive_inflow") else \
              "北向" if "nb_" in s.get("source", "") or "north" in s["name"] else \
              "两融" if "margin_" in s.get("source", "") or "sec_lending" in s.get("source", "") else \
              "其他"
        categories.setdefault(cat, []).append(s)

    cat_summary = "\n".join(
        f"### {cat}\n" + "\n".join(f"  - **{s['name']}**: {s['hypothesis']}" for s in specs)
        for cat, specs in categories.items()
    )
    summary = f"""# Data Enrichment Alpha Pack V3.3

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
- Fund Flow (资金流): fund_flow_timeseries.csv ✅ Available
- North-bound (北向): north_flow_timeseries.csv ⏳ Pending
- Margin (两融): margin_timeseries.csv ⏳ Pending

## Next Steps (V3.4)
- Technical Pattern Control Pack (MACD/KDJ/Boll as control)
"""
    with open(out_dir / "data_enrichment_alpha_pack_summary.md", "w") as f:
        f.write(summary)

    # 打印
    print(f"\n{'='*60}")
    print(f"  📊 Data Enrichment Alpha Pack V3.3")
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
    run_data_enrichment_pack(dry_run=args.dry_run)
