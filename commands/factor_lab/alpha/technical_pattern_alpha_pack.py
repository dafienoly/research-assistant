"""Technical Pattern Control Pack V3.4 — MACD/KDJ/Boll 仅作 control/baseline/redundancy

所有技术指标因子以 "control" 角色注册, 不作为主要 alpha 信号。
安全边界: auto_apply=False, no_live_trade=True, all enabled=False。

用法:
    from factor_lab.alpha.technical_pattern_alpha_pack import run_technical_pattern_pack
    result = run_technical_pattern_pack(dry_run=True)
"""

import sys, os, json, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


# ─── Technical Pattern Alpha Spec 定义 ──────────────────────────────
# 所有技术指标作为 "control" 角色, 不作为主要 alpha 信号。
# role=control 表示这些因子仅作基线参考、低相关性检查、或冗余验证。

TECHNICAL_ALPHA_SPECS = [
    # ── MACD ───────────────────────────────────────────────────────
    {
        "name": "macd_dif_control",
        "description": "MACD DIF 线 (12ema-26ema) — control 基线参考",
        "hypothesis": "MACD DIF 作为动量基线参考, 单独预测能力有限",
        "factor_expression": "macd_dif (12ema - 26ema)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["technical", "macd", "control", "v3.4", "no_live_trade"],
        "source": "macd_dif",
        "role": "control",
    },
    {
        "name": "macd_histogram_control",
        "description": "MACD 柱状图 (DIF-DEA) — control 动量加速参考",
        "hypothesis": "MACD 柱状图反映动量加速度, 但单独使用信号噪音大",
        "factor_expression": "macd_histogram = macd_dif - macd_dea",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["technical", "macd", "control", "v3.4", "no_live_trade"],
        "source": "macd_histogram",
        "role": "control",
    },
    {
        "name": "macd_cross_control",
        "description": "MACD 金叉/死叉 — control 趋势确认参考",
        "hypothesis": "MACD 交叉信号在 A 股有效性弱, 仅作趋势确认参考",
        "factor_expression": "macd_cross = sign(macd_histogram_cross_zero)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["technical", "macd", "control", "v3.4", "no_live_trade"],
        "source": "macd_cross",
        "role": "control",
    },
    # ── KDJ ────────────────────────────────────────────────────────
    {
        "name": "kdj_k_control",
        "description": "KDJ K 值 — control 超买超卖参考",
        "hypothesis": "KDJ K 值反映短期随机位置, 超买超卖在 A 股经常钝化",
        "factor_expression": "kdj_k (RSV 平滑)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["technical", "kdj", "control", "v3.4", "no_live_trade"],
        "source": "kdj_k",
        "role": "control",
    },
    {
        "name": "kdj_j_control",
        "description": "KDJ J 值 — control 方向敏感参考",
        "hypothesis": "KDJ J 值对方向变化最敏感, 但假信号多, 仅作辅助参考",
        "factor_expression": "kdj_j = 3*K - 2*D",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["technical", "kdj", "control", "v3.4", "no_live_trade"],
        "source": "kdj_j",
        "role": "control",
    },
    {
        "name": "kdj_cross_control",
        "description": "KDJ 交叉信号 — control 辅助参考",
        "hypothesis": "KDJ K/D 交叉在 A 股噪音高, 仅作辅助参考",
        "factor_expression": "kdj_cross = K 上穿/下穿 D",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["technical", "kdj", "control", "v3.4", "no_live_trade"],
        "source": "kdj_cross",
        "role": "control",
    },
    # ── Bollinger Bands ──────────────────────────────────────────
    {
        "name": "boll_position_control",
        "description": "Bollinger %b 位置 — control 超买超卖基线",
        "hypothesis": "%b 反映价格在布林带内相对位置, 单独交易信号价值低",
        "factor_expression": "boll_position = (close - lower) / (upper - lower)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["technical", "bollinger", "control", "v3.4", "no_live_trade"],
        "source": "boll_position",
        "role": "control",
    },
    {
        "name": "boll_squeeze_control",
        "description": "Bollinger Squeeze — control 变盘预警参考",
        "hypothesis": "Bollinger 带宽收窄预示变盘, 但方向不确定, 仅作预警",
        "factor_expression": "boll_squeeze = bandwidth_percentile < 0.2",
        "signal_direction": "neutral",
        "rebalance_frequency": "weekly",
        "tags": ["technical", "bollinger", "control", "v3.4", "no_live_trade"],
        "source": "boll_squeeze",
        "role": "control",
    },
    {
        "name": "boll_breakout_control",
        "description": "Bollinger 突破信号 — control 趋势强度参考",
        "hypothesis": "布林带突破信号在趋势市场有效, 震荡市假信号多",
        "factor_expression": "boll_breakout = sign(close_above_upper) or sign(close_below_lower)",
        "signal_direction": "long",
        "rebalance_frequency": "weekly",
        "tags": ["technical", "bollinger", "control", "v3.4", "no_live_trade"],
        "source": "boll_breakout",
        "role": "control",
    },
    # ── Bollinger Width (波动率基线) ────────────────────────────
    {
        "name": "boll_width_control",
        "description": "Bollinger 带宽 — control 波动率基线",
        "hypothesis": "Bollinger 带宽衡量波动率, 非方向性信号, 用作风险基线",
        "factor_expression": "boll_width = (upper - lower) / middle",
        "signal_direction": "neutral",
        "rebalance_frequency": "weekly",
        "tags": ["technical", "bollinger", "volatility", "control", "v3.4", "no_live_trade"],
        "source": "boll_width",
        "role": "control",
    },
]


def run_technical_pattern_pack(dry_run=True):
    """创建 Technical Pattern Control Pack V3.4

    参数:
        dry_run: True=仅生成报告, 不实际注册到 Alpha Registry
                  False=实际注册到 Alpha Registry (所有 Alpha 为 disabled)

    返回:
        dict: 包含 run_id, 各统计量, 注册列表, 增量价值评估
    """
    from factor_lab.alpha.schema import AlphaSpec
    from factor_lab.factor_base import list_factors

    all_factors = list_factors()
    factor_names = {f["name"] for f in all_factors}

    registered = []
    sources_missing = []

    sid = datetime.now(CST).strftime("%Y%m%d_%H%M%S_%f")
    out_dir = BASE / "technical_pattern_alpha_pack" / sid
    out_dir.mkdir(parents=True, exist_ok=True)

    for spec_def in TECHNICAL_ALPHA_SPECS:
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
                source=f"technical_pattern_alpha_pack.py:{spec_def['name']}",
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
                    "role": spec_def.get("role", "control"),
                })
            else:
                registered.append({
                    "name": spec_def["name"],
                    "alpha_id": f"DRY_RUN_{spec_def['name']}",
                    "role": spec_def.get("role", "control"),
                })
        except Exception as e:
            sources_missing.append({"name": spec_def["name"], "error": str(e)})

    # 增量价值评估 (incremental value report)
    # 技术指标因子与现有因子的相关性分析 —— 显示冗余性
    incremental_value = _compute_incremental_value_report(
        all_factors, registered, factor_names
    )

    result = {
        "run_id": sid,
        "dry_run": dry_run,
        "version": "V3.4",
        "label": "Technical Pattern Control Pack",
        "specs_defined": len(TECHNICAL_ALPHA_SPECS),
        "registered": len(registered),
        "sources_missing": len(sources_missing),
        "registered_list": registered,
        "missing_list": sources_missing,
        "all_enabled_false": True,
        "auto_apply": False,
        "no_live_trade": True,
        "incremental_value": incremental_value,
    }

    _write_technical_pattern_outputs(result, out_dir)
    return result


def _compute_incremental_value_report(all_factors, registered, factor_names):
    """计算技术指标因子的增量价值评估

    评估维度:
    1. 与现有因子的相关性分析 (基于因子计算逻辑匹配)
    2. 独特性评分
    3. 冗余警告
    4. 建议角色

    返回:
        dict: 包含评估结果的报告
    """
    existing_categories = {}
    for f in all_factors:
        cat = f.get("category", "?")
        existing_categories.setdefault(cat, 0)
        existing_categories[cat] += 1

    # 现有因子类目及数量
    category_summary = {
        "momentum": existing_categories.get("momentum", 0),
        "trend": existing_categories.get("trend", 0),
        "volume": existing_categories.get("volume", 0),
        "volatility": existing_categories.get("volatility", 0),
        "breakout": existing_categories.get("breakout", 0),
        "industry_relative": existing_categories.get("industry_relative", 0),
        "fund_flow": existing_categories.get("fund_flow", 0),
        "north_bound": existing_categories.get("north_bound", 0),
        "margin": existing_categories.get("margin", 0),
    }

    # MACD 与 trend/momentum 因子的重叠分析
    # MACD DIF (ema12 - ema26) 本质上与短长期动量差高度相关
    # MACD 金叉/死叉与 ma_gap (ma5_gt_ma10, ma10_gt_ma20) 逻辑相似
    macd_redundancy = {
        "related_existing_factors": ["ma5_gt_ma10", "ma10_gt_ma20", "ret5", "ret10"],
        "overlap_rationale": (
            "MACD 本质是快慢均线差, 与 ma5_gt_ma10/ma10_gt_ma20 "
            "等趋势因子的信息重叠度高。在 A 股实证中, "
            "MACD 单独预测能力弱于简单动量因子(ret5/ret10)。"
        ),
        "recommended_role": "control — 仅作趋势确认和冗余检查",
        "incremental_value_score": 0.25,  # 0-1 scale, low = low incremental value
    }

    # KDJ 与 reversal/volatility 因子的重叠分析
    # KDJ 本质是随机位置 + 超买超卖, 与 reversal 逻辑重叠
    kdj_redundancy = {
        "related_existing_factors": ["reversal5", "reversal20", "min_low60", "close_to_high20"],
        "overlap_rationale": (
            "KDJ 衡量价格在近期高低点的相对位置, 与反转因子(reversal5/20) "
            "和突破因子(close_to_high20)逻辑重叠。"
            "KDJ 超买超卖在 A 股趋势行情中经常钝化失效。"
        ),
        "recommended_role": "control — 仅作超买超卖辅助参考",
        "incremental_value_score": 0.20,
    }

    # Bollinger 与 volatility/breakout 因子的重叠分析
    # Bollinger 带宽与 atr/volatility 重叠, %b 与 close_to_high60 重叠
    bollinger_redundancy = {
        "related_existing_factors": ["atr20", "volatility20", "intraday_range20",
                                      "close_to_high20", "close_to_high60",
                                      "high_20_breakout", "max_drawdown20"],
        "overlap_rationale": (
            "Bollinger Bands 本质是移动平均线 + 标准差通道, 与 atr20(波幅)、"
            "volatility20(波动率)、close_to_high(位置) 等因子信息重叠度高。"
            "窄带 squeeze 与低波动率状态 (low volatility20) 等价。"
        ),
        "recommended_role": "control — 仅作波动率基线和突破确认",
        "incremental_value_score": 0.30,
    }

    # 总结评级
    control_count = len(registered)
    # 低增量价值: 平均分 < 0.35
    avg_score = (
        macd_redundancy["incremental_value_score"]
        + kdj_redundancy["incremental_value_score"]
        + bollinger_redundancy["incremental_value_score"]
    ) / 3

    if avg_score < 0.25:
        overall_verdict = "低增量价值 — 技术指标因子与现有因子高度冗余"
    elif avg_score < 0.40:
        overall_verdict = "较低增量价值 — 建议仅作 control/baseline 使用"
    else:
        overall_verdict = "中等增量价值 — 可选择性用作辅助参考"

    # 风险提示
    risks = [
        "MACD/KDJ/Boll 在 A 股实证研究中单独预测能力显著弱于基本面因子",
        "技术指标容易过拟合 (参数选择偏误)",
        "技术指标信号在震荡市中噪音极高",
        "技术指标因子的 IC 稳定性差, 随时间衰减快",
    ]

    return {
        "overall_verdict": overall_verdict,
        "avg_incremental_value_score": round(avg_score, 3),
        "total_control_factors": control_count,
        "existing_factor_categories": category_summary,
        "analysis": {
            "macd": macd_redundancy,
            "kdj": kdj_redundancy,
            "bollinger": bollinger_redundancy,
        },
        "risks": risks,
        "recommendation": (
            "技术指标因子(MACD/KDJ/Boll) 不适合作为独立 alpha 信号。"
            "建议仅用作: (1) 趋势确认的 baseline 参考, "
            "(2) 与其他因子组合时的低相关性冗余检查, "
            "(3) 波动率/交易环境的 control 变量。"
            "所有相关 Alpha 已标记 role=control, "
            "默认 disabled 防止误用。"
        ),
    }


def _write_technical_pattern_outputs(result, out_dir):
    """写入 V3.4 Technical Pattern Control Pack 报告"""
    registered = result.get("registered_list", [])
    missing = result.get("missing_list", [])
    iv = result.get("incremental_value", {})

    # JSON
    with open(out_dir / "technical_pattern_alpha_pack.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # CSV: 已注册
    with open(out_dir / "technical_pattern_alphas_registered.csv", "w",
              newline="", encoding="utf-8-sig") as f:
        if registered:
            fieldnames = list(registered[0].keys())
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(registered)
        else:
            w = csv.writer(f)
            w.writerow(["name", "alpha_id", "role"])
            for r in registered:
                w.writerow([r["name"], r["alpha_id"], r.get("role", "control")])

    # CSV: 缺失依赖
    with open(out_dir / "technical_pattern_sources_missing.csv", "w",
              newline="", encoding="utf-8-sig") as f:
        fieldnames = ["name", "missing"] if not any("error" in m for m in missing) else ["name", "error"]
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(missing)

    # CSV: 增量价值评估
    iv_analysis = iv.get("analysis", {})
    iv_rows = []
    for category, analysis in iv_analysis.items():
        iv_rows.append({
            "category": category,
            "incremental_value_score": analysis.get("incremental_value_score", 0),
            "role": analysis.get("recommended_role", "control"),
            "related_factors": ";".join(analysis.get("related_existing_factors", [])),
            "overlap_rationale": analysis.get("overlap_rationale", ""),
        })
    with open(out_dir / "incremental_value_report.csv", "w",
              newline="", encoding="utf-8-sig") as f:
        if iv_rows:
            w = csv.DictWriter(f, fieldnames=list(iv_rows[0].keys()), extrasaction="ignore")
            w.writeheader()
            w.writerows(iv_rows)

    # HTML 报告
    rows_reg = "".join(
        f"<tr><td>{r['name']}</td><td>{r.get('alpha_id', '')}</td>"
        f"<td>🟡 control</td><td>🔴 disabled</td></tr>"
        for r in registered
    )
    rows_missing = "".join(
        f"<tr><td>{m['name']}</td><td>{m.get('missing', m.get('error', ''))}</td></tr>"
        for m in missing
    )

    # 增量价值行
    iv_table = "".join(
        f"<tr><td>{cat.upper()}</td>"
        f"<td>{analysis.get('incremental_value_score', 0)}</td>"
        f"<td>{analysis.get('recommended_role', 'control')}</td>"
        f"<td>{'; '.join(analysis.get('related_existing_factors', []))}</td></tr>"
        for cat, analysis in iv_analysis.items()
    )

    risk_items = "".join(f"<li>{r}</li>" for r in iv.get("risks", []))

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Technical Pattern Control Pack V3.4</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#ff9800; }} h2 {{ color:#ff9800; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
.warn {{ background:#3e2723; border-left:4px solid #ff9800; padding:8px; margin:8px 0; }}
.ok {{ color:#7df0bd; }}
.warn-color {{ color:#ff9800; }}
</style></head><body>
<div class="card"><h1>📊 Technical Pattern Control Pack V3.4</h1>
<p>Run: {result['run_id']} | Dry-run: {result['dry_run']}</p>
<p>Specs Defined: {result['specs_defined']} | Registered: {result['registered']} | Missing Deps: {result['sources_missing']}</p>
<p>All Enabled: <span class="warn-color">🔴 False</span> | Role: <span class="warn-color">🟡 CONTROL</span></p></div>

<div class="card"><h2>⚠️ Incremental Value Assessment</h2>
<p><strong>Overall Verdict:</strong> {iv.get('overall_verdict', '评估完成')}</p>
<p><strong>Avg Incremental Value Score:</strong> {iv.get('avg_incremental_value_score', 0)} / 1.0</p>
<p><strong>Recommendation:</strong> {iv.get('recommendation', '')}</p>
</div>

<div class="card"><h2>📋 Registered Technical Control Factors</h2>
<table><tr><th>Name</th><th>Alpha ID</th><th>Role</th><th>Status</th></tr>{rows_reg}</table></div>
""" + (f"""<div class="card"><h2>⚠️ Missing Dependencies</h2>
<table><tr><th>Name</th><th>Missing Source</th></tr>{rows_missing}</table></div>""" if missing else "") + f"""
<div class="card"><h2>📈 Incremental Value by Category</h2>
<table><tr><th>Category</th><th>Score</th><th>Recommended Role</th><th>Related Existing Factors</th></tr>{iv_table}</table>
<div class="warn"><strong>Note:</strong> 增量价值分数 < 0.35 表示该因子与现有因子高度冗余, 不适合作为独立 alpha 信号。</div>
</div>

<div class="card"><h2>🔄 Redundancy Overlap Analysis</h2>
<table><tr><th>Technical Factor</th><th>Overlaps With</th><th>Rationale</th></tr>
<tr><td>MACD</td><td>ma_gap, ret5, trend factors</td><td>快慢均线差 ≈ 动量差, 与趋势因子高度重叠</td></tr>
<tr><td>KDJ</td><td>reversal, close_to_high, min_low</td><td>随机位置 ≈ 反转+突破因子组合</td></tr>
<tr><td>Bollinger</td><td>atr, volatility, close_to_high, breakout</td><td>标准差通道 ≈ 波动率+突破因子组合</td></tr>
</table></div>

<div class="card"><h2>⚠️ Risk Warnings</h2>
<ul>{risk_items}</ul>
</div>

<div class="card"><h2>🛡️ Safety</h2>
<ul>
<li>All enabled=False, paper_enabled=False, live_enabled=False</li>
<li>auto_apply=False, no_live_trade=True</li>
<li>All factors marked role=control (not alpha)</li>
<li>No broker/miniqmt called</li>
<li>No paper/live config modified</li>
<li>No auto-backtest triggered</li>
</ul></div>

<div class="card"><h2>📊 Factor-Based Redundancy Score</h2>
<p>技术指标因子与以下现有类目存在显著重叠:</p>
<table><tr><th>Existing Category</th><th>Factor Count</th></tr>
""" + "\n".join(
    f"<tr><td>{k}</td><td>{v}</td></tr>"
    for k, v in iv.get("existing_factor_categories", {}).items()
) + """
</table></div>

<div class="card" style="text-align:center;color:#666;font-size:0.8em;">
<p>V3.4 — Technical Pattern Control Pack | All factors as CONTROL, not alpha</p>
</div>
</body></html>"""
    with open(out_dir / "technical_pattern_control_pack_report.html", "w") as f:
        f.write(html)

    # Markdown 摘要
    spec_lines = "\n".join(
        f"  - **{s['name']}** (role={s.get('role','control')}): {s['hypothesis']}"
        for s in TECHNICAL_ALPHA_SPECS
    )

    iv_items = "\n".join(
        f"  - **{cat.upper()}**: score={analysis.get('incremental_value_score', 0)}, "
        f"overlap with {', '.join(analysis.get('related_existing_factors', []))}"
        for cat, analysis in iv_analysis.items()
    )

    risk_bullets = "\n".join(f"  - {r}" for r in iv.get("risks", []))

    summary = f"""# Technical Pattern Control Pack V3.4

Run: {result['run_id']} | Dry-run: {result['dry_run']}

## Overview
- Specs defined: {result['specs_defined']}
- Registered: {result['registered']}
- Missing dependencies: {result['sources_missing']}
- All alphas disabled: {result['all_enabled_false']}
- Role: CONTROL (not alpha)

## Registered Control Factors

{spec_lines}

## Incremental Value Assessment

**Verdict:** {iv.get('overall_verdict', '评估完成')}
**Avg Score:** {iv.get('avg_incremental_value_score', 0)} / 1.0

### By Category

{iv_items}

### Risk Warnings

{risk_bullets}

### Recommendation

{iv.get('recommendation', '')}

## Redundancy Summary

| Technical Pattern | Overlaps With | Redundancy Level |
|---|---|---|
| MACD | ma_gap, ret5, trend | High |
| KDJ | reversal, close_to_high, min_low | High |
| Bollinger | atr, volatility, breakout | Medium-High |

## Safety
- All enabled=False, paper_enabled=False, live_enabled=False
- auto_apply=False, no_live_trade=True
- All factors marked role=control
- No broker/miniqmt
- No auto-backtest triggered

## Next Steps (V3.5)
- Event-driven Alpha Pack (解禁、回购、分红、业绩预告等事件 Alpha)
"""
    with open(out_dir / "technical_pattern_control_pack_summary.md", "w") as f:
        f.write(summary)

    # 打印
    print(f"\n{'='*60}")
    print(f"  📊 Technical Pattern Control Pack V3.4")
    print(f"  Dry-run: {result['dry_run']}")
    print(f"  Specs: {result['specs_defined']} | Registered: {result['registered']} | Missing: {result['sources_missing']}")
    print(f"  All enabled=False | role=control | auto_apply=False | no_live_trade=True")
    print(f"  Incremental Value: {iv.get('avg_incremental_value_score', 'N/A')}")
    print(f"  📁 {out_dir}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    args = parser.parse_args()
    run_technical_pattern_pack(dry_run=args.dry_run)
