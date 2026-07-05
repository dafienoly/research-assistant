"""验证报告生成 — HTML + JSON + Markdown 统一输出

输出目录:
  /mnt/d/HermesReports/factor_validation/<run_id>/
    ├── anti_overfit.json
    ├── rolling_validation.json
    ├── factor_score.json
    ├── validation_summary.md
    ├── audit.log
    └── factor_report.html
"""
import sys, os, json, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

CST = timezone(timedelta(hours=8))
BASE_OUTPUT = Path("/mnt/d/HermesReports/factor_validation")


def generate_validation_report(
    anti_overfit: dict,
    factor_score: dict,
    rolling_validation: Optional[dict] = None,
    output_dir: Optional[str] = None,
    extra: Optional[dict] = None,
) -> dict:
    """生成完整验证报告

    返回:
        {"output_dir": ..., "report_path": ..., "files": [...]}
    """
    if extra is None:
        extra = {}

    run_id = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    factor_name = anti_overfit.get("factor_name", "unknown")
    out_dir = Path(output_dir or str(BASE_OUTPUT / f"{factor_name}_{run_id}"))
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. anti_overfit.json ──
    _write_json(out_dir / "anti_overfit.json", anti_overfit)

    # ── 2. rolling_validation.json ──
    if rolling_validation:
        _write_json(out_dir / "rolling_validation.json", rolling_validation)

    # ── 3. factor_score.json ──
    _write_json(out_dir / "factor_score.json", factor_score)

    # ── 4. validation_summary.md ──
    md = _build_markdown(anti_overfit, factor_score, rolling_validation, extra)
    _write_file(out_dir / "validation_summary.md", md)

    # ── 5. audit.log ──
    audit = _build_audit_log(anti_overfit, factor_score, rolling_validation, extra)
    _write_file(out_dir / "audit.log", audit)

    # ── 6. factor_report.html ──
    html = _build_html(anti_overfit, factor_score, rolling_validation, extra)
    _write_file(out_dir / "factor_report.html", html)

    files = sorted(p.name for p in out_dir.iterdir() if p.is_file())
    return {
        "output_dir": str(out_dir),
        "report_path": str(out_dir / "factor_report.html"),
        "files": files,
        "run_id": run_id,
    }


# ─── JSON 写入器 ──────────────────────────────────────────────

def _write_json(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_file(path: Path, content: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ─── Markdown 摘要 ────────────────────────────────────────────

def _build_markdown(ao: dict, fs: dict, rv: Optional[dict], extra: dict) -> str:
    fn = ao.get("factor_name", "?")
    score = fs.get("overall_score", 0)
    grade = fs.get("grade", "D")
    lines = [
        f"# 因子验证摘要: {fn}",
        f"",
        f"**评分**: {score}/100 → **{grade}**",
        f"**是否通过**: {'✅ 通过' if fs.get('pass_gate') else '❌ 未通过'}",
        f"",
        f"## 反过拟合检查",
        f"",
    ]
    # IC
    ic = ao.get("ic_stability", {})
    lines.append(f"- **IC稳定性**: {ic.get('verdict','?')}  IC_IR={ic.get('ic_ir','?')}  POS={ic.get('positive_ic_ratio','?'):.0%}")
    # Stress
    st = ao.get("stress_test", {})
    subs = st.get("subsamples", [])
    lines.append(f"- **子样本压力**: {st.get('verdict','?')}  共{len(subs)}个子样本  稳定度={st.get('stability_score','?'):.2f}")
    # Placebo
    pb = ao.get("placebo", {})
    lines.append(f"- **安慰剂检验**: {pb.get('verdict','?')}  百分位={pb.get('factor_score_percentile','?'):.0f}%  Z-score={pb.get('zscore_vs_placebo','?'):.1f}")
    # Decay
    dc = ao.get("ic_decay", {})
    curve = dc.get("ic_decay_curve", {})
    curve_str = " ".join(f"{k}={v:.4f}" for k, v in sorted(curve.items()))
    lines.append(f"- **IC衰减**: {dc.get('verdict','?')}  半衰期={dc.get('half_life_days','?')}天  [{curve_str}]")
    # Peer
    pr = ao.get("peer_benchmark", {})
    lines.append(f"- **同池等权对照**: {pr.get('verdict','?')}  超额={pr.get('excess_return_pct','?'):.1f}%")

    if rv:
        lines += [
            f"",
            f"## Walk-Forward 验证",
            f"- **状态**: {rv.get('limitation','?')}",
            f"- **窗口数**: {len(rv.get('windows',[]))}",
            f"- **平均 Test Sharpe**: {rv.get('avg_test_sharpe','?'):.3f}",
            f"- **OOS 正收益比例**: {rv.get('oos_positive_ratio','?')*100:.0f}%",
            f"- **平均衰减**: {rv.get('avg_decay','?'):.3f}",
        ]

    if fs.get("reject_reasons"):
        lines += ["", "## 淘汰原因", ""]
        for r in fs["reject_reasons"]:
            lines.append(f"- ❌ {r}")

    if fs.get("improvement_suggestions"):
        lines += ["", "## 改进建议", ""]
        for s in fs["improvement_suggestions"]:
            lines.append(f"- 💡 {s}")

    lines += [
        "",
        f"---",
        f"_生成时间: {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}_",
    ]
    return "\n".join(lines)


# ─── Audit Log ─────────────────────────────────────────────────

def _build_audit_log(ao: dict, fs: dict, rv: Optional[dict], extra: dict) -> str:
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    fn = ao.get("factor_name", "?")
    grade = fs.get("grade", "D")
    lines = [
        f"=== AUDIT LOG ===",
        f"Time: {now}",
        f"Factor: {fn}",
        f"Grade: {grade}",
        f"Score: {fs.get('overall_score')}",
        f"Pass: {fs.get('pass_gate')}",
        f"",
        f"--- IC Stability ---",
        f"Verdict: {ao.get('ic_stability',{}).get('verdict','?')}",
        f"IC_IR: {ao.get('ic_stability',{}).get('ic_ir','?')}",
        f"Positive_IC: {ao.get('ic_stability',{}).get('positive_ic_ratio','?'):.2%}",
        f"",
        f"--- Stress Test ---",
        f"Verdict: {ao.get('stress_test',{}).get('verdict','?')}",
        f"Stability: {ao.get('stress_test',{}).get('stability_score','?'):.3f}",
        f"Worst: {ao.get('stress_test',{}).get('worst_subsample_score','?'):.3f}",
        f"N_subsamples: {len(ao.get('stress_test',{}).get('subsamples',[]))}",
        f"",
        f"--- Placebo ---",
        f"Verdict: {ao.get('placebo',{}).get('verdict','?')}",
        f"Percentile: {ao.get('placebo',{}).get('factor_score_percentile','?'):.1f}%",
        f"Z-score: {ao.get('placebo',{}).get('zscore_vs_placebo','?'):.2f}",
        f"",
        f"--- IC Decay ---",
        f"Verdict: {ao.get('ic_decay',{}).get('verdict','?')}",
        f"HalfLife: {ao.get('ic_decay',{}).get('half_life_days','?')}d",
        f"BestHorizon: {ao.get('ic_decay',{}).get('best_horizon','?')}d",
        f"",
        f"--- Peer Benchmark ---",
        f"Verdict: {ao.get('peer_benchmark',{}).get('verdict','?')}",
        f"Beats_Peer: {ao.get('peer_benchmark',{}).get('beats_peer','?')}",
        f"Excess: {ao.get('peer_benchmark',{}).get('excess_return_pct','?'):.1f}%",
    ]
    if rv:
        lines += [
            f"",
            f"--- Walk-Forward ---",
            f"Limitation: {rv.get('limitation','?')}",
            f"N_windows: {len(rv.get('windows',[]))}",
            f"Avg_Test_Sharpe: {rv.get('avg_test_sharpe')}",
            f"Avg_Decay: {rv.get('avg_decay')}",
            f"OOS_Positive: {rv.get('oos_positive_ratio',0):.0%}",
        ]
    lines += [
        f"",
        f"--- Reject Reasons ---",
    ]
    for r in fs.get("reject_reasons", []):
        lines.append(f"  - {r}")
    lines += [
        f"",
        f"--- End Audit ---",
    ]
    return "\n".join(lines)


# ─── HTML 报告 ────────────────────────────────────────────────

def _build_html(ao: dict, fs: dict, rv: Optional[dict], extra: dict) -> str:
    fn = ao.get("factor_name", "?")
    expr = ao.get("expression", "")
    score = fs.get("overall_score", 0)
    grade = fs.get("grade", "D")
    passed = fs.get("pass_gate", False)
    now = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")

    # 颜色
    grade_color = {"A": "#00c853", "B": "#64dd17", "C": "#ff9100", "D": "#ff1744"}.get(grade, "#888")
    pass_icon = "✅" if passed else "❌"

    # IC 衰减曲线
    ic_decay = ao.get("ic_decay", {}).get("ic_decay_curve", {})
    decay_rows = "".join(
        f"<tr><td>{k}</td><td>{v:.4f}</td></tr>" for k, v in sorted(ic_decay.items())
    )

    # 子样本表
    subs = ao.get("stress_test", {}).get("subsamples", [])
    sub_rows = ""
    for s in subs:
        sub_rows += f"<tr><td>{s.get('label','')}</td><td>{s.get('days','')}</td>"
        sub_rows += f"<td>{s.get('cumulative_return_pct','?')}%</td><td>{s.get('sharpe','?')}</td>"
        sub_rows += f"<td>{s.get('ic_mean','?')}</td><td>{s.get('max_drawdown_pct','?')}%</td></tr>"

    # Walk-Forward 窗口表
    wf_rows = ""
    if rv:
        for w in rv.get("windows", []):
            wf_rows += f"<tr><td>{w.get('window_name','')}</td>"
            wf_rows += f"<td>{w.get('train_sharpe','?')}</td><td>{w.get('train_cumulative_return_pct','?')}%</td>"
            wf_rows += f"<td>{w.get('val_sharpe','?')}</td><td>{w.get('val_cumulative_return_pct','?')}%</td>"
            wf_rows += f"<td>{w.get('test_sharpe','?')}</td><td>{w.get('test_cumulative_return_pct','?')}%</td>"
            wf_rows += f"<td>{w.get('decay_train_to_test','?')}</td></tr>"

    # 评分栏
    score_rows = ""
    for k, label in [("ic_stability_score", "IC 稳定性 (25%)"),
                      ("monotonicity_score", "分组单调性 (20%)"),
                      ("peer_excess_score", "同池超额 (20%)"),
                      ("risk_control_score", "回撤风控 (15%)"),
                      ("walk_forward_score", "Walk-Forward (15%)"),
                      ("simplicity_score", "简洁性 (5%)")]:
        val = fs.get(k, 0)
        bar_w = max(val, 5)
        bar_color = "#00c853" if val >= 70 else "#ff9100" if val >= 40 else "#ff1744"
        score_rows += f"""
        <tr><td>{label}</td><td>{val:.1f}</td>
        <td><div style="background:#333;border-radius:4px;width:200px;height:12px;">
        <div style="background:{bar_color};width:{bar_w}%;height:12px;border-radius:4px;"></div></div></td></tr>"""

    # 淘汰原因
    reject_html = "<ul>" + "".join(f"<li>❌ {r}</li>" for r in fs.get("reject_reasons", [])) + "</ul>" if fs.get("reject_reasons") else "<p>✅ 无淘汰原因</p>"

    # 改进建议
    suggest_html = "<ul>" + "".join(f"<li>💡 {s}</li>" for s in fs.get("improvement_suggestions", [])) + "</ul>" if fs.get("improvement_suggestions") else "<p>—</p>"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>因子验证报告 — {fn}</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", "Noto Sans SC", sans-serif; background: #1a1a2e; color: #e0e0e0; margin: 0; padding: 20px; }}
.card {{ background: #16213e; border-radius: 8px; padding: 20px; margin: 12px 0; }}
.header {{ background: linear-gradient(135deg, #0f3460, #16213e); border-radius: 8px; padding: 24px; text-align: center; }}
h1 {{ margin:0; font-size: 1.6em; }} h2 {{ color: #00bcd4; font-size: 1.2em; border-bottom: 1px solid #333; padding-bottom:6px; }}
table {{ width:100%; border-collapse: collapse; }}
th, td {{ padding: 6px 10px; text-align: left; border-bottom: 1px solid #333; }}
th {{ color: #888; font-size: 0.85em; }}
.badge {{ display: inline-block; padding: 4px 14px; border-radius: 4px; font-weight: bold; font-size: 1.2em; }}
.large-score {{ font-size: 2.5em; font-weight: bold; }}
.pass {{ color: #00c853; }} .warn {{ color: #ff9100; }} .fail {{ color: #ff1744; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 0.8em; margin: 2px; }}
.tag-pass {{ background:#00c85333; color:#00c853; }} .tag-fail {{ background:#ff174433; color:#ff1744; }} .tag-warn {{ background:#ff910033; color:#ff9100; }}
li {{ margin: 4px 0; }}
</style></head><body>

<div class="header">
<h1>{pass_icon} 因子验证报告: {fn}</h1>
<p style="color:#aaa;">{expr}</p>
<div class="badge" style="background:{grade_color}22; color:{grade_color};">
<span class="large-score">{score:.0f}</span> / {grade}
</div>
<p style="color:#aaa;">生成时间: {now}</p>
</div>

<div class="card">
<h2>📊 反过拟合摘要</h2>
<table>
<tr><th>检查项</th><th>结论</th><th>关键值</th></tr>
<tr><td>IC 稳定性</td><td class="{ao.get('ic_stability',{}).get('verdict','fail')}">{ao.get('ic_stability',{}).get('verdict','?')}</td>
<td>IR={ao.get('ic_stability',{}).get('ic_ir','?'):.4f}, POS={ao.get('ic_stability',{}).get('positive_ic_ratio','?'):.1%}</td></tr>
<tr><td>子样本压力</td><td class="{ao.get('stress_test',{}).get('verdict','fail')}">{ao.get('stress_test',{}).get('verdict','?')}</td>
<td>稳定度={ao.get('stress_test',{}).get('stability_score','?'):.3f}, {len(subs)}个子样本</td></tr>
<tr><td>安慰剂检验</td><td class="{ao.get('placebo',{}).get('verdict','fail')}">{ao.get('placebo',{}).get('verdict','?')}</td>
<td>百分位={ao.get('placebo',{}).get('factor_score_percentile','?'):.0f}%, Z={ao.get('placebo',{}).get('zscore_vs_placebo','?'):.2f}</td></tr>
<tr><td>IC 衰减</td><td class="{ao.get('ic_decay',{}).get('verdict','fail')}">{ao.get('ic_decay',{}).get('verdict','?')}</td>
<td>半衰期={ao.get('ic_decay',{}).get('half_life_days','?')}天</td></tr>
<tr><td>同池等权对照</td><td class="{'pass' if ao.get('peer_benchmark',{}).get('beats_peer',False) else 'fail'}">{'pass' if ao.get('peer_benchmark',{}).get('beats_peer',False) else 'fail'}</td>
<td>超额={ao.get('peer_benchmark',{}).get('excess_return_pct','?'):.1f}%</td></tr>
</table>
</div>

<img src="https://placehold.co/800x2/333/333" style="width:100%;height:2px;">

<div class="card">
<h2>📈 IC 衰减曲线</h2>
<table><tr><th>Horizon</th><th>IC</th></tr>{decay_rows}</table>
</div>

<img src="https://placehold.co/800x2/333/333" style="width:100%;height:2px;">

<div class="card">
<h2>📋 子样本压力测试</h2>
<table>
<tr><th>子样本</th><th>天数</th><th>收益</th><th>Sharpe</th><th>IC</th><th>回撤</th></tr>
{sub_rows}
</table>
</div>
"""
    if wf_rows:
        html += f"""
<img src="https://placehold.co/800x2/333/333" style="width:100%;height:2px;">
<div class="card">
<h2>🔄 Walk-Forward 验证</h2>
<p>状态: {rv.get('limitation','?')} | 窗口数: {len(rv.get('windows',[]))} | OOS正收益: {rv.get('oos_positive_ratio',0)*100:.0f}% | 平均衰减: {rv.get('avg_decay',0):.3f}</p>
<table>
<tr><th>窗口</th><th>Train SR</th><th>Train Cum</th><th>Val SR</th><th>Val Cum</th><th>Test SR</th><th>Test Cum</th><th>衰减</th></tr>
{wf_rows}
</table>
</div>
"""
    html += f"""
<img src="https://placehold.co/800x2/333/333" style="width:100%;height:2px;">

<div class="card">
<h2>🏆 因子评分</h2>
<table>{score_rows}</table>
<p><strong>综合评分: {score:.1f}</strong>  →  <span class="badge" style="background:{grade_color}22;color:{grade_color};">{grade}</span>
{pass_icon} {'通过门禁' if passed else '未通过'}</p>
</div>

<div class="card">
<h2>⛔ 淘汰原因</h2>
{reject_html}
</div>

<div class="card">
<h2>💡 改进建议</h2>
{suggest_html}
</div>

<div class="card" style="text-align:center;color:#666;font-size:0.8em;">
<p>Factor Lab Validation Report | 生成时间: {now}</p>
</div>

</body></html>"""
    return html
