"""组合排行榜报告 — HTML + CSV + JSON + Markdown 统一输出

输出目录 (由调用方传入):
    <output_dir>/
    ├── composite_leaderboard.html   (暗色主题 HTML 排行榜)
    ├── composite_leaderboard.csv    (所有组合排行字段)
    ├── composite_leaderboard.json   (完整数据)
    ├── factor_correlation.json      (因子相关性矩阵)
    ├── candidate_pool.json          (候选池快照)
    ├── promoted_composites.md       (通过门禁的组合)
    ├── rejected_composites.md       (未通过的组合)
    └── audit.log                    (审计日志)

用法:
    from factor_lab.reports.composite_report import generate_composite_leaderboard
    report = generate_composite_leaderboard(
        composites=composites,
        corr_result={**corr_result, **overlap_result},
        candidate_pool=pool.to_dict(),
        output_dir="/mnt/d/HermesReports/composite_leaderboard/run_1",
    )
"""

import json, csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

CST = timezone(timedelta(hours=8))


# ─── 主入口 ─────────────────────────────────────────────────────

def generate_composite_leaderboard(
    composites: list[dict],
    corr_result: dict,
    candidate_pool: dict,
    output_dir: str,
) -> dict:
    """生成组合排行榜报告

    参数:
        composites:       list[dict], 每个元素是 composite_validation 的输出
        corr_result:      dict, factor_correlation + topN_overlap 合并结果
        candidate_pool:   dict, CandidatePool.to_dict() 输出
        output_dir:       str, 输出目录路径

    返回:
        {"output_dir": ..., "report_path": ..., "files": [...]}
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(CST)
    now_iso = now.isoformat()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # ── 1. 构建排行榜条目 ──
    entries = _build_entries(composites)
    entries.sort(key=lambda e: -e.get("score", 0))

    # 找到 ret5 基线行 (用于对比)
    ret5_entry = _find_ret5_entry(entries)

    # ── 2. 保存 JSON ──
    leaderboard_data = {
        "generated_at": now_iso,
        "n_composites": len(entries),
        "entries": entries,
        "corr_result": corr_result,
    }
    _write_json(out_dir / "composite_leaderboard.json", leaderboard_data)

    # ── 3. 保存 CSV ──
    _write_csv(out_dir / "composite_leaderboard.csv", entries)

    # ── 4. 保存相关性 ──
    _write_json(out_dir / "factor_correlation.json", corr_result)

    # ── 5. 保存候选池快照 ──
    _write_json(out_dir / "candidate_pool.json", candidate_pool)

    # ── 6. 分类 MD ──
    promoted = [e for e in entries if e.get("pass_gate")]
    rejected = [e for e in entries if not e.get("pass_gate")]
    _write_md(out_dir / "promoted_composites.md",
              _build_promoted_md(promoted, now_str))
    _write_md(out_dir / "rejected_composites.md",
              _build_rejected_md(rejected, now_str))

    # ── 7. Audit Log ──
    _write_md(out_dir / "audit.log",
              _build_audit_log(entries, corr_result, now_str))

    # ── 8. HTML 排行榜 ──
    html = _build_html(entries, ret5_entry, corr_result, now_str)
    _write_md(out_dir / "composite_leaderboard.html", html)

    files = sorted(p.name for p in out_dir.iterdir() if p.is_file())
    return {
        "output_dir": str(out_dir),
        "report_path": str(out_dir / "composite_leaderboard.html"),
        "files": files,
        "n_composites": len(entries),
        "n_promoted": len(promoted),
        "n_rejected": len(rejected),
    }


# ─── 数据提取 ───────────────────────────────────────────────────

def _build_entries(composites: list[dict]) -> list[dict]:
    """从原始 composite_validation 输出构建扁平化排行条目"""
    entries = []
    for comp in composites:
        if comp is None:
            continue
        ao = comp.get("anti_overfit", {}) or {}
        fs = comp.get("factor_score", {}) or {}
        peer = ao.get("peer_benchmark", {}) or {}
        placebo = ao.get("placebo", {}) or {}
        rv = comp.get("rolling_validation")

        # 从 factor_score 读取指标，带降级
        score = fs.get("overall_score", 0)
        grade = fs.get("grade", "D")
        pass_gate = fs.get("pass_gate", False)

        # 绩效指标
        cumulative_return = peer.get("strategy_cumulative_pct")
        max_drawdown = fs.get("absolute_max_drawdown")
        peer_max_drawdown = fs.get("peer_max_drawdown")
        relative_drawdown_vs_peer = fs.get("relative_drawdown_vs_peer")
        excess_return_vs_peer = peer.get("excess_return_pct")

        # 风险指标
        sharpe = peer.get("excess_sharpe")
        calmar = fs.get("calmar")

        # 验证通过标志
        placebo_pass = placebo.get("verdict") == "pass"
        walk_forward_pass = None
        if rv:
            walk_forward_pass = rv.get("overall_verdict") == "pass"

        reject_reasons = fs.get("reject_reasons", [])

        entry = {
            "composite_name": comp.get("composite_name", ""),
            "factors": comp.get("factor_names", []),
            "combine_method": comp.get("combine_method", ""),
            "score": round(score, 1),
            "grade": grade,
            "pass_gate": pass_gate,
            "cumulative_return": _fmt_pct(cumulative_return),
            "max_drawdown": _fmt_pct(max_drawdown),
            "peer_max_drawdown": _fmt_pct(peer_max_drawdown),
            "relative_drawdown_vs_peer": _fmt_num(relative_drawdown_vs_peer, 4),
            "excess_return_vs_peer": _fmt_pct(excess_return_vs_peer),
            "sharpe": _fmt_num(sharpe, 4),
            "calmar": _fmt_num(calmar, 4),
            "walk_forward_pass": walk_forward_pass,
            "placebo_pass": placebo_pass,
            "reject_reasons": reject_reasons,
            # 原始分项评分 (用于 HTML)
            "ic_stability_score": _fmt_num(fs.get("ic_stability_score"), 1),
            "monotonicity_score": _fmt_num(fs.get("monotonicity_score"), 1),
            "peer_excess_score": _fmt_num(fs.get("peer_excess_score"), 1),
            "risk_control_score": _fmt_num(fs.get("risk_control_score"), 1),
            "walk_forward_score": _fmt_num(fs.get("walk_forward_score"), 1),
            "simplicity_score": _fmt_num(fs.get("simplicity_score"), 1),
            # 原始数据指针 (保留给 HTML 细节)
            "_factor_names": comp.get("factor_names", []),
        }
        entries.append(entry)
    return entries


def _find_ret5_entry(entries: list[dict]) -> Optional[dict]:
    """在排行榜中查找 ret5 单因子基线条目"""
    for e in entries:
        name = e.get("composite_name", "").lower()
        factors = e.get("factors", [])
        if name == "ret5" or (len(factors) == 1 and factors[0] == "ret5"):
            return e
    return None


def _fmt_pct(val) -> str:
    """格式化百分比值, 保留 2 位小数 + % 号"""
    if val is None:
        return "--"
    try:
        return f"{float(val):.2f}%"
    except (ValueError, TypeError):
        return str(val)


def _fmt_num(val, decimals: int = 2) -> str:
    """格式化数值"""
    if val is None:
        return "--"
    try:
        return f"{float(val):.{decimals}f}"
    except (ValueError, TypeError):
        return str(val)


# ─── 写入函数 ───────────────────────────────────────────────────

def _write_json(path: Path, data: dict):
    """写入 JSON 文件"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _write_csv(path: Path, entries: list[dict]):
    """写入 CSV 文件 (UTF-8 BOM)"""
    fields = [
        "composite_name", "factors", "combine_method", "score", "grade", "pass_gate",
        "cumulative_return", "max_drawdown", "peer_max_drawdown",
        "relative_drawdown_vs_peer", "excess_return_vs_peer",
        "sharpe", "calmar", "walk_forward_pass", "placebo_pass",
        "reject_reasons",
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for e in entries:
            row = dict(e)
            # factors list → 逗号连接字符串
            if isinstance(row.get("factors"), list):
                row["factors"] = "+".join(row["factors"])
            # reject_reasons list → 分号连接
            if isinstance(row.get("reject_reasons"), list):
                row["reject_reasons"] = "; ".join(row["reject_reasons"])
            # bool → 中文
            for bk in ("walk_forward_pass", "placebo_pass"):
                v = row.get(bk)
                if v is True:
                    row[bk] = "是"
                elif v is False:
                    row[bk] = "否"
                else:
                    row[bk] = "--"
            # pass_gate → 中文
            v = row.get("pass_gate")
            if v is True:
                row["pass_gate"] = "是"
            elif v is False:
                row["pass_gate"] = "否"
            else:
                row["pass_gate"] = "--"
            w.writerow(row)


def _write_md(path: Path, content: str):
    """写入 Markdown / 纯文本文件"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ─── Markdown 报告 ──────────────────────────────────────────────

def _build_promoted_md(promoted: list[dict], now_str: str) -> str:
    """生成通过门禁的组合清单 Markdown"""
    if not promoted:
        return "# 🏆 通过门禁的组合\n\n当前批次无组合通过门禁。\n"
    lines = [
        "# 🏆 通过门禁的组合",
        "",
        f"共 **{len(promoted)}** 个组合通过门禁，可进入下一轮:",
        "",
        "| # | 组合名称 | 因子 | 方法 | 评分 | 等级 | 累积收益 | 回撤 | Sharpe |",
        "|---|----------|------|------|------|------|----------|------|--------|",
    ]
    for i, e in enumerate(promoted):
        factors = "+".join(e.get("factors", []))
        lines.append(
            f"| {i+1} | {e['composite_name']} | {factors} | {e.get('combine_method','')} "
            f"| {e.get('score','?')} | {e.get('grade','?')} "
            f"| {e.get('cumulative_return','--')} | {e.get('max_drawdown','--')} "
            f"| {e.get('sharpe','--')} |"
        )
    lines += [
        "",
        "---",
        f"_生成时间: {now_str}_",
    ]
    return "\n".join(lines)


def _build_rejected_md(rejected: list[dict], now_str: str) -> str:
    """生成未通过门禁的组合清单 Markdown"""
    if not rejected:
        return "# ❌ 未通过的组合\n\n所有组合均已通过门禁。\n"
    lines = [
        "# ❌ 未通过的组合",
        "",
        f"共 **{len(rejected)}** 个组合未通过门禁:",
        "",
        "| # | 组合名称 | 因子 | 方法 | 评分 | 等级 | 淘汰原因 |",
        "|---|----------|------|------|------|------|----------|",
    ]
    for i, e in enumerate(rejected):
        reasons = "; ".join(e.get("reject_reasons", [])[:3])
        factors = "+".join(e.get("factors", []))
        lines.append(
            f"| {i+1} | {e['composite_name']} | {factors} | {e.get('combine_method','')} "
            f"| {e.get('score','?')} | {e.get('grade','?')} | {reasons} |"
        )
    lines += [
        "",
        "---",
        f"_生成时间: {now_str}_",
    ]
    return "\n".join(lines)


# ─── Audit Log ──────────────────────────────────────────────────

def _build_audit_log(entries: list[dict], corr_result: dict, now_str: str) -> str:
    """生成审计日志"""
    n_passed = sum(1 for e in entries if e.get("pass_gate"))
    n_rejected = sum(1 for e in entries if not e.get("pass_gate"))
    grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for e in entries:
        g = e.get("grade", "D")
        grade_counts[g] = grade_counts.get(g, 0) + 1

    avg_corr = corr_result.get("avg_corr", "?")
    avg_overlap = corr_result.get("avg_overlap", "?")

    lines = [
        f"=== COMPOSITE LEADERBOARD AUDIT LOG ===",
        f"Time: {now_str}",
        f"Total composites: {len(entries)}",
        f"",
        f"--- Grade Distribution ---",
        f"A: {grade_counts.get('A', 0)}",
        f"B: {grade_counts.get('B', 0)}",
        f"C: {grade_counts.get('C', 0)}",
        f"D: {grade_counts.get('D', 0)}",
        f"",
        f"Passed: {n_passed}",
        f"Rejected: {n_rejected}",
        f"",
        f"--- Factor Correlation ---",
        f"Avg Pearson Corr: {avg_corr}",
        f"Avg TopN Overlap: {avg_overlap}",
        f"",
        f"--- Per Composite ---",
    ]
    for e in entries:
        factors = "+".join(e.get("factors", []))
        score_str = str(e.get("score", "?"))
        grade_str = str(e.get("grade", "?"))
        cum_ret_str = str(e.get("cumulative_return", "--"))
        dd_str = str(e.get("max_drawdown", "--"))
        lines.append(
            f"  {e['composite_name']:30s} | method={e.get('combine_method',''):20s} "
            f"| score={score_str:>5s} | grade={grade_str:1s} "
            f"| pass={e.get('pass_gate','?')} "
            f"| ret={cum_ret_str:>7s} "
            f"| dd={dd_str:>7s}"
        )
    lines += [
        f"",
        f"--- End Audit ---",
    ]
    return "\n".join(lines)


# ─── HTML 报告 ──────────────────────────────────────────────────

def _build_html(
    entries: list[dict],
    ret5_entry: Optional[dict],
    corr_result: dict,
    now_str: str,
) -> str:
    """生成暗色主题 HTML 排行榜报告"""
    grade_color = {"A": "#00c853", "B": "#64dd17", "C": "#ff9100", "D": "#ff1744"}

    # ── 汇总统计 ──
    n_passed = sum(1 for e in entries if e.get("pass_gate"))
    n_rejected = sum(1 for e in entries if not e.get("pass_gate"))
    grade_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for e in entries:
        g = e.get("grade", "D")
        grade_counts[g] = grade_counts.get(g, 0) + 1

    avg_corr = corr_result.get("avg_corr", "?")
    avg_overlap = corr_result.get("avg_overlap", "?")

    # ── 排行表 ──
    table_rows = ""
    for i, e in enumerate(entries):
        gc = grade_color.get(e.get("grade", "D"), "#888")
        pass_icon = "✅" if e.get("pass_gate") else "❌"
        reasons = "; ".join(e.get("reject_reasons", [])[:2])
        wf_pass = "✅" if e.get("walk_forward_pass") else ("❌" if e.get("walk_forward_pass") is False else "—")
        pb_pass = "✅" if e.get("placebo_pass") else ("❌" if e.get("placebo_pass") is False else "—")
        factors_str = "+".join(e.get("factors", []))
        method_str = e.get("combine_method", "")

        # 如果是 ret5 基线行, 加对比高亮
        row_class = ""
        is_ret5 = (e.get("composite_name", "").lower() == "ret5"
                   or e.get("composite_name", "").startswith("ret5_"))
        if is_ret5:
            row_class = ' class="ret5-row"'

        table_rows += f"""<tr{row_class}>
<td>{i+1}</td>
<td>{e['composite_name']}</td>
<td style="font-size:0.85em;color:#aaa;">{factors_str}</td>
<td style="font-size:0.85em;">{method_str}</td>
<td class="num">{e.get('score','--')}</td>
<td><span class="grade" style="color:{gc}">{e.get('grade','?')}</span></td>
<td>{pass_icon}</td>
<td class="num">{e.get('cumulative_return','--')}</td>
<td class="num">{e.get('max_drawdown','--')}</td>
<td class="num">{e.get('relative_drawdown_vs_peer','--')}</td>
<td class="num">{e.get('excess_return_vs_peer','--')}</td>
<td class="num">{e.get('sharpe','--')}</td>
<td class="num">{e.get('calmar','--')}</td>
<td>{wf_pass}</td>
<td>{pb_pass}</td>
<td style="font-size:0.8em;color:#aaa;max-width:180px;">{reasons}</td>
</tr>"""

    # ── 分项评分明细表 (Top 10) ──
    detail_rows = ""
    for i, e in enumerate(entries[:10]):
        gc = grade_color.get(e.get("grade", "D"), "#888")
        pass_icon = "✅" if e.get("pass_gate") else "❌"
        detail_rows += f"""<tr>
<td>{i+1}</td><td>{e['composite_name']}</td>
<td><span class="grade" style="color:{gc}">{e.get('grade','?')}</span></td>
<td class="num">{e.get('ic_stability_score','--')}</td>
<td class="num">{e.get('monotonicity_score','--')}</td>
<td class="num">{e.get('peer_excess_score','--')}</td>
<td class="num">{e.get('risk_control_score','--')}</td>
<td class="num">{e.get('walk_forward_score','--')}</td>
<td class="num">{e.get('simplicity_score','--')}</td>
<td>{pass_icon}</td>
</tr>"""

    # ── 相关性矩阵表 ──
    pearson = corr_result.get("pearson", {})
    corr_table = _build_corr_html(pearson)

    # ── ret5 对比行 ──
    ret5_compare_html = ""
    if ret5_entry:
        ret5_compare_html = _build_ret5_compare(entries, ret5_entry)

    # ── 组合方法说明 ──
    method_explain = _build_method_explain()

    # ── 完整 HTML ──
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>组合排行榜 — Composite Leaderboard</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", "Noto Sans SC", sans-serif; background: #1a1a2e; color: #e0e0e0; margin:0; padding:20px; }}
.card {{ background: #16213e; border-radius:8px; padding:20px; margin:12px 0; }}
.header {{ background: linear-gradient(135deg, #0f3460, #16213e); border-radius:8px; padding:24px; text-align:center; }}
h1 {{ margin:0; font-size:1.6em; color:#00bcd4; }}
h2 {{ color:#00bcd4; font-size:1.2em; border-bottom:1px solid #333; padding-bottom:6px; }}
table {{ width:100%; border-collapse:collapse; }}
th, td {{ padding:6px 8px; text-align:left; border-bottom:1px solid #333; white-space:nowrap; }}
th {{ color:#888; font-size:0.85em; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.grade {{ font-weight:bold; font-size:1.1em; }}
.summary-box {{ display:inline-block; padding:10px 20px; margin:4px; border-radius:6px; text-align:center; }}
.summary-num {{ font-size:1.8em; font-weight:bold; }}
.summary-label {{ font-size:0.8em; color:#aaa; }}
.ret5-row {{ background: #1a3a5c; }}
.ret5-row td {{ border-bottom: 1px solid #2a5a8c; }}
.corr-table td, .corr-table th {{ padding:4px 6px; font-size:0.85em; }}
.corr-high {{ color:#00c853; font-weight:bold; }}
.corr-mid {{ color:#ff9100; }}
.corr-low {{ color:#ff1744; }}
ul {{ padding-left:20px; }}
li {{ margin:6px 0; line-height:1.5; }}
.explain-card {{ background: #1a2744; border-radius:6px; padding:16px; margin:8px 0; }}
.explain-card h3 {{ color:#00bcd4; margin:0 0 8px 0; font-size:1em; }}
.badge {{ display:inline-block; padding:2px 10px; border-radius:3px; font-size:0.8em; margin:1px; }}
.badge-a {{ background:#00c85333; color:#00c853; }}
.badge-b {{ background:#64dd1733; color:#64dd17; }}
.badge-c {{ background:#ff910033; color:#ff9100; }}
.badge-d {{ background:#ff174433; color:#ff1744; }}
.scroll-box {{ overflow-x:auto; }}
</style>
</head>
<body>

<div class="header">
<h1>🏆 组合排行榜</h1>
<p style="color:#aaa;">{now_str} | {len(entries)} 个组合 | 通过 {n_passed} / 淘汰 {n_rejected}</p>
<p style="color:#666;font-size:0.9em;">相关性: avg_corr={avg_corr} | avg_overlap={avg_overlap}</p>
<div>
<div class="summary-box" style="background:#00c85322;"><div class="summary-num">{grade_counts.get('A',0)}</div><div class="summary-label">A 级</div></div>
<div class="summary-box" style="background:#64dd1722;"><div class="summary-num">{grade_counts.get('B',0)}</div><div class="summary-label">B 级</div></div>
<div class="summary-box" style="background:#ff910022;"><div class="summary-num">{grade_counts.get('C',0)}</div><div class="summary-label">C 级</div></div>
<div class="summary-box" style="background:#ff174422;"><div class="summary-num">{grade_counts.get('D',0)}</div><div class="summary-label">D 级</div></div>
<div class="summary-box" style="background:#00bcd422;"><div class="summary-num">{n_passed}</div><div class="summary-label">✅ 通过</div></div>
<div class="summary-box" style="background:#ff174422;"><div class="summary-num">{n_rejected}</div><div class="summary-label">❌ 淘汰</div></div>
</div>
</div>

<div class="card">
<h2>📊 组合排行 (按评分降序)</h2>
<div class="scroll-box">
<table>
<tr>
<th>#</th><th>组合名称</th><th>因子</th><th>方法</th><th class="num">评分</th><th>等级</th><th>通过</th>
<th class="num">累计收益</th><th class="num">最大回撤</th><th class="num">相对回撤</th><th class="num">超额收益</th>
<th class="num">Sharpe</th><th class="num">Calmar</th><th>WF</th><th>Placebo</th><th>淘汰原因</th>
</tr>
{table_rows}
</table>
</div>
</div>

{ret5_compare_html}

<div class="card">
<h2>📋 分项评分明细 (Top 10)</h2>
<div class="scroll-box">
<table>
<tr><th>#</th><th>组合</th><th>等级</th><th class="num">IC稳定</th><th class="num">单调性</th><th class="num">超额收益</th><th class="num">风控</th><th class="num">WF</th><th class="num">简洁性</th><th>通过</th></tr>
{detail_rows}
</table>
</div>
</div>

<div class="card">
<h2>🔗 因子相关性矩阵 (Pearson)</h2>
<div class="scroll-box">
<table class="corr-table">
{corr_table}
</table>
<p style="color:#888;font-size:0.85em;margin-top:8px;">
avg_corr={avg_corr} | avg_overlap={avg_overlap}
— <span class="corr-high">绿色</span>=高相关 ≥0.5,
<span class="corr-mid">橙色</span>=中相关 0.3~0.5,
<span class="corr-low">红色</span>=低相关 &lt;0.3
</p>
</div>
</div>

<div class="card">
<h2>💡 组合评价说明</h2>

<div class="explain-card">
<h3>🎯 为什么需要组合因子？</h3>
<ul>
<li>单因子往往存在"周期性失效"——某个时段有效，换个时段就失效。</li>
<li>组合多个低相关因子可以平滑收益曲线，降低最大回撤，提升稳健性。</li>
<li><strong>相关性越低</strong>的组合效果越好——如果两个因子高度相关，组合和单因子没区别。</li>
</ul>
</div>

<div class="explain-card">
<h3>📏 怎么判断组合优劣？</h3>
<ul>
<li><strong>评分 (Score)</strong>: 综合 IC 稳定性、分组单调性、同池超额、风控、Walk-Forward、简洁性六大维度的加权得分。</li>
<li><strong>等级 (Grade)</strong>: A/B 级通过门禁, C/D 级淘汰。硬性降级规则包括未跑赢同池、Walk-Forward 样本外为负等。</li>
<li><strong>Sharpe / Calmar</strong>: 风险调整收益指标。Sharpe>1 较好, Calmar>1 说明收益能覆盖回撤。</li>
<li><strong>Walk-Forward (WF)</strong>: 样本外验证通过 → ✅, 说明组合在样本外延续有效。</li>
<li><strong>Placebo</strong>: 安慰剂检验通过 → ✅, 排除偶然性。</li>
</ul>
</div>

<div class="explain-card">
<h3>📉 回撤相对阈值怎么理解？</h3>
<ul>
<li><strong>最大回撤 (Max DD)</strong>: 历史最高点到最低点的跌幅。动量/趋势因子允许更高回撤。</li>
<li><strong>相对回撤 (Relative DD vs Peer)</strong>: 组合最大回撤 / 同池等权最大回撤。<br>
  如果这个值 &gt; 1.20, 说明组合的波动比简单持有同池还大，触发风控警告。</li>
<li><strong>组合 vs 单因子 ret5 对比</strong>: 看组合是否在收益不减的同时降低了回撤——这是组合的核心价值。</li>
</ul>
</div>

{method_explain}
</div>

<div class="card" style="text-align:center;color:#666;font-size:0.8em;">
<p>Factor Lab — Composite Leaderboard | {now_str}</p>
</div>

</body>
</html>"""
    return html


def _build_corr_html(pearson: dict) -> str:
    """生成相关性矩阵的 HTML 表格"""
    if not pearson:
        return "<p>相关性数据不可用</p>"
    names = list(pearson.keys())
    if not names:
        return "<p>相关性数据不可用</p>"

    # 表头
    thead = "<tr><th>因子</th>"
    for n in names:
        short = n[:12] + ".." if len(n) > 14 else n
        thead += f"<th>{short}</th>"
    thead += "</tr>"

    # 表体
    tbody = ""
    for n1 in names:
        row = pearson.get(n1, {})
        tbody += f"<tr><td style='font-weight:bold;'>{n1[:14]}</td>"
        for n2 in names:
            val = row.get(n2)
            if val is None:
                tbody += "<td>--</td>"
                continue
            if n1 == n2:
                cls = "corr-high"
                display = f"{val:.2f}"
            else:
                av = abs(val)
                if av >= 0.5:
                    cls = "corr-high"
                elif av >= 0.3:
                    cls = "corr-mid"
                else:
                    cls = "corr-low"
                display = f"{val:.2f}"
            tbody += f'<td class="{cls}">{display}</td>'
        tbody += "</tr>"

    return thead + tbody


def _build_ret5_compare(entries: list[dict], ret5_entry: dict) -> str:
    """构建 ret5 基线对比 HTML 卡片"""
    rows = ""
    for e in entries:
        if e.get("composite_name") == ret5_entry.get("composite_name"):
            continue
        # 计算对比值
        ret5_ret = _parse_num(ret5_entry.get("cumulative_return", "--"))
        ret5_dd = _parse_num(ret5_entry.get("max_drawdown", "--"))
        ret5_sharpe = _parse_num(ret5_entry.get("sharpe", "--"))

        comp_ret = _parse_num(e.get("cumulative_return", "--"))
        comp_dd = _parse_num(e.get("max_drawdown", "--"))
        comp_sharpe = _parse_num(e.get("sharpe", "--"))

        ret_diff = _diff_str(comp_ret, ret5_ret) if (comp_ret is not None and ret5_ret is not None) else "--"
        dd_diff = _diff_str(comp_dd, ret5_dd, lower_better=True) if (comp_dd is not None and ret5_dd is not None) else "--"
        sharpe_diff = _diff_str(comp_sharpe, ret5_sharpe) if (comp_sharpe is not None and ret5_sharpe is not None) else "--"

        pass_icon = "✅" if e.get("pass_gate") else "❌"
        gc = {"A": "#00c853", "B": "#64dd17", "C": "#ff9100", "D": "#ff1744"}.get(e.get("grade", "D"), "#888")

        rows += f"""<tr>
<td>{pass_icon} {e['composite_name']}</td>
<td><span class="grade" style="color:{gc}">{e.get('grade','?')}</span></td>
<td class="num">{e.get('cumulative_return','--')} <span style="color:#888;font-size:0.85em;">({ret_diff})</span></td>
<td class="num">{e.get('max_drawdown','--')} <span style="color:#888;font-size:0.85em;">({dd_diff})</span></td>
<td class="num">{e.get('sharpe','--')} <span style="color:#888;font-size:0.85em;">({sharpe_diff})</span></td>
</tr>"""

    if not rows:
        return ""

    ret5_name = ret5_entry.get("composite_name", "ret5")
    ret5_ret = ret5_entry.get("cumulative_return", "--")
    ret5_dd = ret5_entry.get("max_drawdown", "--")
    ret5_sharpe = ret5_entry.get("sharpe", "--")

    return f"""<div class="card">
<h2>🔄 与单因子 {ret5_name} 的对比</h2>
<p style="color:#888;font-size:0.85em;">
基线: {ret5_name} → 收益 {ret5_ret} | 回撤 {ret5_dd} | Sharpe {ret5_sharpe}
</p>
<div class="scroll-box">
<table>
<tr><th>组合</th><th>等级</th><th class="num">累计收益 (vs {ret5_name})</th><th class="num">最大回撤 (vs {ret5_name})</th><th class="num">Sharpe (vs {ret5_name})</th></tr>
{rows}
</table>
</div>
<p style="color:#888;font-size:0.85em;margin-top:4px;">
括号内为与 {ret5_name} 的差值。收益↑红、↓绿; 回撤 (越小越好) ↓红、↑绿; Sharpe ↑红、↓绿。
</p>
</div>"""


def _build_method_explain() -> str:
    """生成组合方法说明 HTML"""
    methods = [
        ("equal_weight_score", "等权评分", "每个因子截面 rank 后等权平均。最简单稳健, 适合相关性较低的因子组合。"),
        ("weighted_score", "加权评分", "按因子质量 (如 IC_IR) 分配权重后求和。适合同类因子中强弱分明的场景。"),
        ("gated_score", "门控评分", "主因子 rank > 0.5 时才启用次要因子, 否则返回 0。适合 '用高置信度信号过滤' 的场景。"),
        ("zscore_blend", "Z-Score 混合", "每日截面 zscore 标准化后加权。保留因子数值分布信息, 适合数值分布稳定的因子。"),
        ("rank_blend", "Rank 混合", "与加权评分相同, 截面 rank 后加权。对极端值不敏感, 适合有噪声的因子。"),
    ]
    items = "".join(
        f"<li><strong>{m[0]}</strong> ({m[1]}): {m[2]}</li>"
        for m in methods
    )
    return f"""<div class="explain-card">
<h3>⚙️ 组合方法说明</h3>
<ul>{items}</ul>
</div>"""


def _parse_num(val_str: str) -> Optional[float]:
    """解析数字字符串, 去掉 % 后缀"""
    if val_str == "--" or val_str is None:
        return None
    try:
        return float(str(val_str).replace("%", ""))
    except (ValueError, TypeError):
        return None


def _diff_str(comp_val: Optional[float], base_val: Optional[float],
              lower_better: bool = False) -> str:
    """计算差值的可读字符串"""
    if comp_val is None or base_val is None:
        return "--"
    diff = comp_val - base_val
    if not lower_better:
        # 越大越好
        if diff > 0:
            return f"<span style='color:#ff5252;'>+{diff:.2f}</span>"
        elif diff < 0:
            return f"<span style='color:#69f0ae;'>{diff:.2f}</span>"
        else:
            return "<span style='color:#888;'>0.00</span>"
    else:
        # 越小越好 (回撤)
        if diff < 0:
            return f"<span style='color:#ff5252;'>{diff:.2f}</span>"
        elif diff > 0:
            return f"<span style='color:#69f0ae;'>+{diff:.2f}</span>"
        else:
            return "<span style='color:#888;'>0.00</span>"
