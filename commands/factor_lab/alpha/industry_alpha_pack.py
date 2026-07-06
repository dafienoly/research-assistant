"""Industry Relative Alpha Pack V3.1 — 行业相对 / 行业中性 Alpha

注册行业相对 Alpha 到 Alpha Registry。
所有 Alpha 默认 enabled=False, 安全边界: auto_apply=False, no_live_trade=True。

用法:
    from factor_lab.alpha.industry_alpha_pack import run_industry_alpha_pack
    result = run_industry_alpha_pack(dry_run=True)
"""

import sys, os, json, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


# ─── Industry Alpha Spec 定义 ──────────────────────────────

INDUSTRY_ALPHA_SPECS = [
    {
        "name": "industry_relative_momentum",
        "description": "行业相对5日动量: ret5 行业中位数调整",
        "hypothesis": "行业内相对动量最强的股票在未来一个月继续跑赢同行业",
        "factor_expression": "ret5_industry_adj = ret5 - industry_median(ret5); rank(ret5_industry_adj, ascending=False)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["industry_relative", "momentum", "v3.1", "no_live_trade"],
        "source": "ret5_industry_adj",
    },
    {
        "name": "industry_relative_low_vol",
        "description": "行业相对低波动: volatility20 行业中位数调整 (取负)",
        "hypothesis": "行业内波动率最低的股票具有超额收益, 且行业中性化后更稳定",
        "factor_expression": "vol20_industry_adj = volatility20 - industry_median(volatility20); rank(-vol20_industry_adj)",
        "signal_direction": "long",
        "rebalance_frequency": "monthly",
        "tags": ["industry_relative", "low_vol", "v3.1", "no_live_trade"],
        "source": "volatility20_industry_adj",
    },
    {
        "name": "industry_neutral_quality",
        "description": "行业中性化质量: ROE/毛利率/净利率 行业内排名等权",
        "hypothesis": "行业内基本面最优的股票具有稳定超额收益",
        "factor_expression": "industry_neutral_quality = industry_rank(roe) + industry_rank(gross_margin) + industry_rank(net_margin)",
        "signal_direction": "long",
        "rebalance_frequency": "monthly",
        "tags": ["industry_neutral", "quality", "v3.1", "no_live_trade"],
        "source": "industry_neutral_quality",
    },
    {
        "name": "industry_relative_volume",
        "description": "行业相对量比: vol_ratio20 行业中位数调整",
        "hypothesis": "行业内成交量相对活跃的股票通常有资金关注",
        "factor_expression": "vr20_industry_adj = vol_ratio20 - industry_median(vol_ratio20)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["industry_relative", "volume", "v3.1", "no_live_trade"],
        "source": "vol_ratio20_industry_adj",
    },
    {
        "name": "industry_neutral_multi_factor",
        "description": "行业中性多因子复合: 动量+低波+量比 行业内rank等权",
        "hypothesis": "多因子行业内复合可分散单因子风险, 提升稳定性",
        "factor_expression": "industry_neutral_composite = (industry_rank(ret5) - industry_rank(vol20) + industry_rank(vr20)) / 3",
        "signal_direction": "long",
        "rebalance_frequency": "monthly",
        "tags": ["industry_neutral", "multi_factor", "composite", "v3.1", "no_live_trade"],
        "source": "industry_neutral_composite",
    },
    {
        "name": "cross_sector_strength",
        "description": "跨行业相对强度: ret5行业中位数调整 × ret20行业rank",
        "hypothesis": "短期动量强且中期趋势好的股票, 在同行业中最具领涨潜力",
        "factor_expression": "cross_sector_strength = ret5_industry_adj * industry_rank(ret20)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["industry_relative", "cross_sector", "momentum", "v3.1", "no_live_trade"],
        "source": "cross_sector_strength",
    },
    {
        "name": "industry_relative_fund_flow",
        "description": "行业相对资金流: net_main_force 行业内排名",
        "hypothesis": "行业内主力资金流入最强的股票后续上涨概率高",
        "factor_expression": "fund_flow_industry_adj = industry_rank(net_main_force)",
        "signal_direction": "long",
        "rebalance_frequency": "daily",
        "tags": ["industry_relative", "fund_flow", "v3.1", "no_live_trade"],
        "source": "fund_flow_industry_adj",
    },
]


def run_industry_alpha_pack(dry_run=True):
    """创建 Industry Relative Alpha Pack

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
    out_dir = BASE / "industry_alpha_pack" / sid
    out_dir.mkdir(parents=True, exist_ok=True)

    for spec_def in INDUSTRY_ALPHA_SPECS:
        # 检查来源因子是否已注册
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
                source=f"industry_alpha_pack.py:{spec_def['name']}",
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
        "version": "V3.1",
        "label": "Industry Relative Alpha Pack",
        "specs_defined": len(INDUSTRY_ALPHA_SPECS),
        "registered": len(registered),
        "sources_missing": len(sources_missing),
        "registered_list": registered,
        "missing_list": sources_missing,
        "all_enabled_false": True,
        "auto_apply": False,
        "no_live_trade": True,
    }

    _write_industry_alpha_outputs(result, out_dir)
    return result


def _write_industry_alpha_outputs(result, out_dir):
    """写入 V3.1 Industry Alpha Pack 报告"""
    registered = result.get("registered_list", [])
    missing = result.get("missing_list", [])

    # JSON
    with open(out_dir / "industry_alpha_pack.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # CSV: 已注册
    with open(out_dir / "industry_alphas_registered.csv", "w", newline="", encoding="utf-8-sig") as f:
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
    with open(out_dir / "industry_alpha_sources_missing.csv", "w", newline="", encoding="utf-8-sig") as f:
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
<html><head><meta charset="utf-8"><title>Industry Relative Alpha Pack V3.1</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
</style></head><body>
<div class="card"><h1>🏭 Industry Relative Alpha Pack V3.1</h1>
<p>Run: {result['run_id']} | Dry-run: {result['dry_run']}</p>
<p>Specs Defined: {result['specs_defined']} | Registered: {result['registered']} | Missing Deps: {result['sources_missing']}</p></div>
<div class="card"><h2>📋 Registered Industry Alphas</h2>
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
    for s in INDUSTRY_ALPHA_SPECS
) + """
</table></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V3.1 — Industry Relative Alpha Pack</p></div>
</body></html>"""
    with open(out_dir / "industry_alpha_pack_report.html", "w") as f:
        f.write(html)

    # Markdown 摘要
    spec_lines = "\n".join(
        f"  - **{s['name']}**: {s['hypothesis']}" for s in INDUSTRY_ALPHA_SPECS
    )
    summary = f"""# Industry Relative Alpha Pack V3.1

Run: {result['run_id']} | Dry-run: {result['dry_run']}

## Overview
- Specs defined: {result['specs_defined']}
- Registered: {result['registered']}
- Missing dependencies: {result['sources_missing']}
- All alphas disabled: {result['all_enabled_false']}

## Alpha Specs

{spec_lines}

## Safety
- All enabled=False, paper_enabled=False, live_enabled=False
- auto_apply=False, no_live_trade=True
- No broker/miniqmt
- No auto-backtest triggered

## Next Steps (V3.2)
- Backtest industry-relative alphas via existing V2 pipeline
- Evaluate IC/IR of industry-neutral factors vs raw factors
- Walk-forward validation on industry-relative signals
"""
    with open(out_dir / "industry_alpha_pack_summary.md", "w") as f:
        f.write(summary)

    # 打印
    print(f"\n{'='*60}")
    print(f"  🏭 Industry Relative Alpha Pack V3.1")
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
    run_industry_alpha_pack(dry_run=args.dry_run)
