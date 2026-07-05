"""修复 composite_leaderboard 报告: 颜色逻辑 + 结论修正

基于现有 JSON 数据重新生成 HTML/MD/audit，不重跑验证。
"""
import json, os
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np

CST = timezone(timedelta(hours=8))
DATA_DIR = Path("/mnt/d/HermesReports/composite_leaderboard/20260704_161840")


def fix_reports():
    with open(DATA_DIR / "composite_leaderboard.json") as f:
        data = json.load(f)

    entries = data.get("entries", [])
    corr = data.get("corr_result", {})

    # 找到 ret5 基线
    ret5_entry = None
    for e in entries:
        if e["composite_name"] == "ret5":
            ret5_entry = e
            break

    if not ret5_entry:
        print("❌ 未找到 ret5 基线")
        return

    r_ret = _pct(ret5_entry.get("cumulative_return", "0%"))
    r_dd = _pct(ret5_entry.get("max_drawdown", "0%"))
    r_sr = _float(ret5_entry.get("sharpe", "0"))

    def _vs_ret5(e):
        """返回与 ret5 的差异: (ret_diff, dd_diff, sr_diff)"""
        er = _pct(e.get("cumulative_return", "0%"))
        ed = _pct(e.get("max_drawdown", "0%"))
        es = _float(e.get("sharpe", "0"))
        return (er - r_ret, ed - r_dd, es - r_sr)

    # 生成 HTML
    html = _build_html(entries, ret5_entry, corr, _vs_ret5)
    with open(DATA_DIR / "composite_leaderboard.html", "w", encoding="utf-8") as f:
        f.write(html)

    # 生成 promoted_composites.md
    promoted = [e for e in entries if e.get("pass_gate") and e.get("grade") in ("A", "B")]
    rejected = [e for e in entries if not (e.get("pass_gate") and e.get("grade") in ("A", "B"))]
    md = _build_promoted_md(promoted, _vs_ret5)
    with open(DATA_DIR / "promoted_composites.md", "w", encoding="utf-8") as f:
        f.write(md)
    md2 = _build_rejected_md(rejected)
    with open(DATA_DIR / "rejected_composites.md", "w", encoding="utf-8") as f:
        f.write(md2)

    # 重写 audit.log 结尾
    audit = _build_audit(entries, corr, _vs_ret5)
    with open(DATA_DIR / "audit.log", "w", encoding="utf-8") as f:
        f.write(audit)

    print(f"✅ 修复完成: {DATA_DIR}")
    print(f"   composite_leaderboard.html  (颜色修复 + 结论修正)")
    print(f"   promoted_composites.md      (结论修正)")
    print(f"   rejected_composites.md")
    print(f"   audit.log                   (结论摘要)")


def _pct(s: str) -> float:
    """从 '285.66%' 提取数值"""
    if isinstance(s, (int, float)):
        return float(s)
    return float(s.replace("%", "").strip())


def _float(s) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    return float(s)


def _color(val: float, better_higher: bool) -> str:
    """返回颜色: better_higher=True 时高=绿, 否则低=绿"""
    if abs(val) < 0.01:
        return "#888"
    if better_higher:
        return "#00c853" if val > 0 else "#ff1744"
    else:
        return "#00c853" if val < 0 else "#ff1744"


def _delta_str(val) -> str:
    if val > 0:
        return f"+{val:.2f}"
    return f"{val:.2f}"


# ─── HTML ──────────────────────────────────────────────────

def _build_html(entries, ret5_entry, corr, vs_ret5_fn) -> str:
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    gc = {"A": 0, "B": 0, "C": 0, "D": 0}
    for e in entries:
        gc[e.get("grade", "D")] = gc.get(e.get("grade", "D"), 0) + 1

    # ret5 基线摘要行
    r5_ret = _pct(ret5_entry.get("cumulative_return", "0%"))
    r5_dd = _pct(ret5_entry.get("max_drawdown", "0%"))
    r5_sr = _float(ret5_entry.get("sharpe", "0"))

    # 排行表
    table_rows = ""
    ret5_name = ret5_entry["composite_name"]
    for i, e in enumerate(entries):
        color = {"A": "#00c853", "B": "#64dd17", "C": "#ff9100", "D": "#ff1744"}.get(e["grade"], "#888")
        pi = "✅" if e["pass_gate"] else "❌"
        factors = "+".join(e.get("factors", []))
        reasons = "; ".join(e.get("reject_reasons", [])[:2])

        # vs ret5 对比
        if e["composite_name"] != ret5_name:
            dr, dd, dsr = vs_ret5_fn(e)
            ret_color = _color(dr, better_higher=True)
            dd_color = _color(dd, better_higher=False)
            sr_color = _color(dsr, better_higher=True)
            vs_html = (
                f'<td style="color:{ret_color}">{_delta_str(dr)}pp</td>'
                f'<td style="color:{dd_color}">{_delta_str(dd)}pp</td>'
                f'<td style="color:{sr_color}">{_delta_str(dsr)}</td>'
            )
        else:
            vs_html = '<td style="color:#00c853">— 基准 —</td>' * 3

        is_ret5_row = e["composite_name"] == ret5_name
        row_style = 'style="background:#00c85311;font-weight:bold;"' if is_ret5_row else ""

        table_rows += f"""<tr {row_style}>
<td>{i+1}</td><td>{e['composite_name']}</td><td>{factors}</td>
<td>{e['combine_method']}</td>
<td class="num">{e['score']:.1f}</td>
<td style="color:{color};font-weight:bold;">{e['grade']}</td>
<td>{pi}</td>
<td class="num">{e.get('cumulative_return','--')}</td>
<td class="num">{e.get('max_drawdown','--')}</td>
<td class="num">{e.get('sharpe','--')}</td>
{vs_html}
<td style="font-size:0.8em;color:#aaa;">{reasons}</td>
</tr>"""

    # 相关性矩阵
    corr_rows = ""
    pearson = corr.get("pearson", {})
    all_cols = list(pearson.keys())
    if all_cols:
        corr_rows += "<tr><td></td>" + "".join(f"<th>{c}</th>" for c in all_cols) + "</tr>"
        for f1 in all_cols:
            corr_rows += f"<tr><th>{f1}</th>"
            for f2 in all_cols:
                v = pearson.get(f1, {}).get(f2, "--")
                if isinstance(v, float):
                    bg = "#ff174433" if abs(v) > 0.5 else "#ff910022" if abs(v) > 0.3 else ""
                else:
                    bg = ""
                corr_rows += f'<td style="text-align:right;{bg}">{v}</td>'
            corr_rows += "</tr>"

    overlap = corr.get("overlap_matrix", {})
    overlap_rows = ""
    if overlap:
        cols2 = list(overlap.keys())
        overlap_rows += "<tr><td></td>" + "".join(f"<th>{c}</th>" for c in cols2) + "</tr>"
        for f1 in cols2:
            overlap_rows += f"<tr><th>{f1}</th>"
            for f2 in cols2:
                v = overlap.get(f1, {}).get(f2, "--")
                bg = "#ff174433" if isinstance(v, (int, float)) and v > 0.5 else ""
                overlap_rows += f'<td style="text-align:right;{bg}">{v}</td>'
            overlap_rows += "</tr>"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>多因子组合排行榜 — V1.5 (修复版)</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", "Noto Sans SC", sans-serif; background: #1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background: #16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; padding-bottom:6px; }}
table {{ width:100%; border-collapse:collapse; }}
th, td {{ padding:6px 8px; text-align:left; border-bottom:1px solid #333; white-space:nowrap; }}
th {{ color:#888; font-size:0.85em; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.green {{ color:#00c853; }} .red {{ color:#ff1744; }}
li {{ margin:6px 0; }}
</style></head><body>

<div class="card" style="text-align:center;">
<h1>📊 多因子组合排行榜</h1>
<p style="color:#aaa;">{now} | 共 {len(entries)} 个 | A={gc.get('A',0)} B={gc.get('B',0)} C={gc.get('C',0)} D={gc.get('D',0)}</p>
<div class="card" style="background:#0f3460;text-align:left;">
<h3>🎯 核心结论</h3>
<p><strong>当前多因子组合没有超越单因子 ret5。</strong></p>
<ul>
<li>相对 ret5（收益 285.7%, 回撤 49.3%, Sharpe 2.91），所有组合均表现为：<span class="red">收益下降</span>、<span class="red">最大回撤上升</span>、<span class="red">Sharpe 下降</span></li>
<li>ret10 和 close_gt_ma20 暂不适合与 ret5 简单加权合成</li>
<li>三个因子皮尔逊相关性均 &lt; 0.02（几乎正交），但 TopN 选股重合度达 54–75%，说明在多头端冗余</li>
<li>ret10 / close_gt_ma20 更适合作为 <strong>确认信号、过滤条件或风控信号</strong>，而非等权/加权合成</li>
<li>颜色说明: 绿色 = 优于 ret5 基线, 红色 = 劣于 ret5 基线</li>
</ul>
</div>
</div>

<div class="card">
<h2>🏆 组合排行 (vs ret5 基准)</h2>
<div style="overflow-x:auto;">
<table>
<tr><th>#</th><th>组合</th><th>因子</th><th>方法</th><th class="num">评分</th><th>等级</th><th>通过</th><th class="num">收益</th><th class="num">回撤</th><th class="num">Sharpe</th>
<th class="num" style="color:#aaa;">收益Δ</th><th class="num" style="color:#aaa;">回撤Δ</th><th class="num" style="color:#aaa;">SharpeΔ</th><th>淘汰原因</th></tr>
{table_rows}
</table>
<p style="color:#666;font-size:0.85em;">Δ 列为与 ret5 基线的差异。绿色=优于ret5, 红色=劣于ret5。注意回撤更高(正值)标红, Sharpe更低(负值)标红。</p>
</div></div>

<div class="card">
<h2>📊 因子相关性</h2>
<p>平均 Pearson 相关: <strong style="color:#ff9100">{corr.get('avg_corr', '--')}</strong> (几乎正交) | 平均 TopN 重合: <strong style="color:#ff9100">{corr.get('avg_overlap', '--')}</strong> (中等偏高)</p>
<table style="display:inline-block;vertical-align:top;width:48%;"><caption style="color:#aaa;font-size:0.85em;">Pearson 相关系数</caption>{corr_rows}</table>
<table style="display:inline-block;vertical-align:top;width:48%;"><caption style="color:#aaa;font-size:0.85em;">TopN 选股重合度</caption>{overlap_rows}</table>
<p style="color:#666;font-size:0.85em;">低 Pearson + 高 TopN 重合 = 因子结构不同但多头端选股趋同, 简单加权合成收益会被稀释。</p>
</div>

<div class="card">
<h2>💡 分析与建议</h2>
<ul>
<li><strong>组合 vs ret5</strong>: 所有组合的收益/回撤/Sharpe 均差于 ret5 单因子。当前市场阶段下, ret5 是最优动量因子。</li>
<li><strong>为什么组合没有更好?</strong>: 三个因子在多头端选股高度重合(54-75%), 合成后实际选出的股票池和 ret5 单独选出的高度相似, 但权重被稀释。</li>
<li><strong>更好的用法</strong>: ret10 和 close_gt_ma20 应作为 ret5 的<strong>确认信号</strong>——例如 ret5 选出 Top20, 再用另外两个因子过滤或排序, 而不是等权混合。</li>
<li><strong>门控组合更保守</strong>: gated_score(63.7/B) 要求 ret5 在前 50% 才启用, 收益降低但可能在某些市场环境下更稳健。</li>
<li><strong>同池等权仍是硬性下限</strong>: 所有组合都跑赢同池等权, 但组合相对 ret5 没有 alpha 增益。</li>
</ul>
</div>

<div class="card" style="text-align:center;color:#666;font-size:0.8em;">
<p>Factor Lab Composite Leaderboard (修复版) | {now}</p>
</div>

</body></html>"""
    return html


def _build_promoted_md(promoted, vs_ret5_fn) -> str:
    lines = ["# 推荐组合", "", "## ⚠️ 注意"]
    lines.append("")
    lines.append("当前多因子组合**没有超越单因子 ret5**。所有组合的收益、回撤、Sharpe 均劣于 ret5 基线。")
    lines.append("")
    lines.append("ret10 和 close_gt_ma20 暂不适合与 ret5 简单加权合成，更适合作为确认信号或风控信号。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"共 {len(promoted)} 个组合通过门禁（全部 B 级）:")
    lines.append("")
    for e in promoted:
        factors = "+".join(e.get("factors", []))
        lines.append(f"- **{e['composite_name']}** ({e['combine_method']}) 评分={e['score']:.1f}/{e['grade']}")
        lines.append(f"  - 因子: {factors}")
        if e.get("reject_reasons"):
            lines.append(f"  - ⚠️ {'; '.join(e['reject_reasons'][:2])}")
        if e["composite_name"] != "ret5" and e["composite_name"] not in ("ret10", "close_gt_ma20"):
            dr, dd, dsr = vs_ret5_fn(e)
            lines.append(f"  - vs ret5: 收益{dr:+.1f}pp, 回撤{dd:+.1f}pp, Sharpe{dsr:+.2f}")
    lines.append("")
    lines.append("---")
    lines.append("_结论: 当前不建议将 ret10 和 close_gt_ma20 与 ret5 简单加权组合。推荐开发门控/过滤式混合信号。_")
    return "\n".join(lines)


def _build_rejected_md(rejected) -> str:
    if not rejected:
        return "# 淘汰组合\n\n所有组合均通过。"
    lines = ["# 淘汰组合", "", f"共 {len(rejected)} 个:", ""]
    for e in rejected:
        reasons = "; ".join(e.get("reject_reasons", [])[:3])
        lines.append(f"- **{e['composite_name']}** ({e['combine_method']}) 评分={e['score']:.1f}/{e['grade']}")
        if reasons:
            lines.append(f"  - ❌ {reasons}")
    return "\n".join(lines)


def _build_audit(entries, corr, vs_ret5_fn) -> str:
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    ret5_entry = None
    for e in entries:
        if e["composite_name"] == "ret5":
            ret5_entry = e
            break
    gc = {"A": 0, "B": 0, "C": 0, "D": 0}
    for e in entries:
        gc[e.get("grade", "D")] = gc.get(e.get("grade", "D"), 0) + 1

    lines = [
        f"=== COMPOSITE VALIDATION AUDIT LOG (修复版) ===",
        f"Time: {now}",
        f"Total composites: {len(entries)}",
        f"A={gc.get('A',0)} B={gc.get('B',0)} C={gc.get('C',0)} D={gc.get('D',0)}",
        f"Avg Correlation: {corr.get('avg_corr', '?'):.4f}",
        f"Avg TopN Overlap: {corr.get('avg_overlap', '?'):.4f}",
        f"",
        f"--- Core Conclusion ---",
        f"RESULT: No composite factor beats single-factor ret5.",
        f"ret5 baseline: ret=285.7% dd=49.3% Sharpe=2.91",
        f"Best composite (equal_weight): ret=205.2% dd=53.5% Sharpe=2.07",
        f"ret10 and close_gt_ma20 are NOT suitable for simple weighted blending with ret5.",
        f"Suggested next step: use ret10/close_gt_ma20 as confirmation/gating signals, not blend factors.",
        f"",
        f"--- Per Composite ---",
    ]
    for e in entries:
        name = e["composite_name"]
        er = e.get("cumulative_return", "--")
        ed = e.get("max_drawdown", "--")
        es = e.get("sharpe", "--")
        vs = ""
        if name not in ("ret5",):
            dr, dd, dsr = vs_ret5_fn(e)
            vs = f" | vs_ret5: ret={dr:+.1f}pp dd={dd:+.1f}pp sr={dsr:+.2f}"
        lines.append(f"  {name:35s} score={e['score']:5.1f}/{e['grade']:1s} ret={er} dd={ed} sr={es}{vs}")
    lines.append("")
    lines.append(f"--- End Audit ---")
    return "\n".join(lines)


if __name__ == "__main__":
    fix_reports()
