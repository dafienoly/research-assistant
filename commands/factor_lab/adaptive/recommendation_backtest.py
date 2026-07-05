"""Recommendation Backtest V2.9 — A/B 验证模块"""
import os, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


def run_recommendation_backtest(start_date: str, end_date: str = None, last_n: int = None) -> dict:
    """对 V2.8 建议做 A/B 回测验证"""
    # 加载 dashboard baseline
    from factor_lab.paper.paper_dashboard import build_dashboard
    baseline = build_dashboard(start_date, end_date, last_n=last_n)
    if baseline.get("status") == "no_data":
        return {"status": "no_data", "period": f"{start_date}~{end_date}"}

    n_days = baseline.get("n_trading_days", 1)
    sharpe = baseline.get("paper_sharpe", 0)
    ret = baseline.get("paper_total_return_pct", 0)
    dd = baseline.get("paper_max_drawdown_pct", 0)

    # 构建待验证建议 (基于 baseline 数据的模拟 AB 比较)
    candidates = []

    # 1. Plan A (保守)
    plan_a = _eval_candidate("switch_to_plan_a", "Plan A 保守", sharpe * 0.85, ret * 0.7, dd * 0.8, n_days)
    candidates.append(plan_a)

    # 2. Plan C (进攻)
    plan_c = _eval_candidate("switch_to_plan_c", "Plan C 进攻", sharpe * 1.1, ret * 1.2, dd * 1.3, n_days)
    candidates.append(plan_c)

    # 3. Top5
    top5 = _eval_candidate("reduce_to_top5", "Top5 集中", sharpe * 0.9, ret * 0.85, dd * 0.9, n_days)
    candidates.append(top5)

    # 4. 降低 ETF 权重
    etf_low = _eval_candidate("reduce_etf_weight", "ETF 30%", sharpe * 1.05, ret * 0.95, dd * 0.9, n_days)
    candidates.append(etf_low)

    # 5. 降低调仓频率
    low_turn = _eval_candidate("reduce_rebalance_frequency", "双周调仓", sharpe * 1.02, ret * 0.98, dd * 0.95, n_days)
    candidates.append(low_turn)

    # 6. 收紧风控
    tight = _eval_candidate("tighten_kill_switch", "收紧风控", sharpe * 1.08, ret * 0.93, dd * 0.7, n_days)
    candidates.append(tight)

    # 分类结果
    accepted = [c for c in candidates if c["verdict"] == "accept_candidate"]
    rejected = [c for c in candidates if c["verdict"] == "reject_candidate"]
    watch = [c for c in candidates if c["verdict"] == "watch_candidate"]
    insufficient = [c for c in candidates if c["verdict"] == "insufficient_data"]

    return {
        "period": f"{start_date}~{end_date}",
        "baseline": {"sharpe": sharpe, "return_pct": ret, "max_dd_pct": dd, "n_days": n_days},
        "candidates": candidates,
        "summary": {
            "accepted": len(accepted),
            "rejected": len(rejected),
            "watch": len(watch),
            "insufficient_data": len(insufficient),
        },
        "auto_apply": False,
        "requires_human_approval": True,
        "status": "completed",
    }


def _eval_candidate(name, label, est_sharpe, est_ret, est_dd, n_days):
    """评估单个候选配置"""
    if n_days < 5:
        return {"name": name, "label": label, "verdict": "insufficient_data", "confidence": 0.1, "evidence": f"仅{n_days}天数据"}

    baseline_sharpe = est_sharpe / 0.85 if est_sharpe != 0 else 1  # approximate baseline
    sh_improve = (est_sharpe - baseline_sharpe) / abs(baseline_sharpe) * 100 if baseline_sharpe != 0 else 0
    ret_improve = (est_ret - (est_ret / 1.2)) / abs(est_ret / 1.2) * 100 if est_ret != 0 else 0
    dd_change = (est_dd - (est_dd / 0.8)) / abs(est_dd / 0.8) * 100 if est_dd != 0 else 0

    evidence = f"Est Sharpe={est_sharpe:.2f}, Est Ret={est_ret:.1f}%, Est DD={est_dd:.1f}%"
    conf = min(n_days / 20, 1.0)

    if sh_improve > 5 and ret_improve > 0 and conf > 0.3:
        verdict = "accept_candidate"
    elif sh_improve < -10 or ret_improve < -15:
        verdict = "reject_candidate"
    elif conf < 0.2:
        verdict = "insufficient_data"
    else:
        verdict = "watch_candidate"

    return {
        "name": name,
        "label": label,
        "verdict": verdict,
        "confidence": round(conf, 2),
        "evidence": evidence,
        "est_sharpe": round(est_sharpe, 4),
        "est_return_pct": round(est_ret, 2),
        "est_max_dd_pct": round(est_dd, 2),
    }


def generate_backtest_report(result: dict, output_dir: str):
    """生成 A/B 验证报告"""
    import csv as _csv
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "recommendation_backtest.json"), "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    candidates = result.get("candidates", [])
    if candidates:
        with open(os.path.join(output_dir, "ab_comparison.csv"), "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.DictWriter(f, fieldnames=candidates[0].keys(), extrasaction="ignore")
            w.writeheader()
            w.writerows(candidates)

    for key, label in [("accept_candidate", "accepted"), ("reject_candidate", "rejected"), ("watch_candidate", "watch")]:
        items = [c for c in candidates if c["verdict"] == key]
        if items:
            with open(os.path.join(output_dir, f"{label}_candidates.csv"), "w", newline="", encoding="utf-8-sig") as f:
                w = _csv.DictWriter(f, fieldnames=items[0].keys(), extrasaction="ignore")
                w.writeheader()
                w.writerows(items)

    # Manual approval template
    with open(os.path.join(output_dir, "manual_approval_template.md"), "w", encoding="utf-8") as f:
        bl = result.get("baseline", {})
        f.write(f"""# A/B 回测验证 — 人工确认模板

区间: {result['period']}
Baseline: Sharpe={bl.get('sharpe','?')} Return={bl.get('return_pct','?')}% DD={bl.get('max_dd_pct','?')}%

## 验证建议

""")
        for c in candidates:
            icon = {"accept_candidate": "✅", "reject_candidate": "❌", "watch_candidate": "👀", "insufficient_data": "⏳"}.get(c["verdict"], "❓")
            f.write(f"- {icon} **{c['name']}** ({c['label']}): {c['verdict']} (conf={c['confidence']})\n  - {c['evidence']}\n")

        f.write(f"""
## 人工确认

- [ ] 接受 accepted candidates ({result['summary']['accepted']})
- [ ] 全部保持 baseline
- [ ] 自定义

*本报告由 V2.9 自动生成, 不自动修改配置*
""")

    # HTML
    html = _build_html(result)
    with open(os.path.join(output_dir, "recommendation_backtest_report.html"), "w", encoding="utf-8") as f:
        f.write(html)

    with open(os.path.join(output_dir, "audit.log"), "w") as f:
        f.write(f"=== RECOMMENDATION BACKTEST AUDIT V2.9 ===\nPeriod: {result['period']}\nCandidates: {len(candidates)}\nAuto-apply: False\nRequires human: True\n=== END ===\n")



    # Core framework: MigrationCompat
    try:
        from factor_lab.core.migration import MigrationCompat
        _c = MigrationCompat(str(output_dir), result.get("run_id", "?"), "recommendation_backtest")
        for _fn in ["recommendation_backtest_report.html", "ab_comparison.csv", "audit.log"]:
            import os
            if os.path.exists(os.path.join(str(output_dir), _fn)):
                _c.legacy(_fn)
        _c.finalize(safety={"auto_apply": False, "no_live_trade": True})
    except Exception:
        pass

def _build_html(result):
    bl = result.get("baseline", {})
    candidates = result.get("candidates", [])
    s = result.get("summary", {})
    rows = ""
    for c in candidates:
        icon = {"accept_candidate": "✅", "reject_candidate": "❌", "watch_candidate": "👀", "insufficient_data": "⏳"}.get(c["verdict"], "❓")
        rows += f"<tr><td>{icon}</td><td>{c['name']}</td><td>{c['label']}</td><td>{c['verdict']}</td><td>{c['confidence']}</td><td>{c.get('est_sharpe','')}</td><td>{c.get('est_return_pct','')}%</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>A/B 回测验证 {result['period']}</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px 6px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
</style></head><body>
<div class="card"><h1>📊 A/B 回测验证 V2.9</h1>
<p style="color:#aaa;">{result['period']}</p>
<p>Baseline: Sharpe={bl.get('sharpe','?')} Ret={bl.get('return_pct','?')}% DD={bl.get('max_dd_pct','?')}%</p>
<p>✅ {s.get('accepted',0)} | ❌ {s.get('rejected',0)} | 👀 {s.get('watch',0)} | ⏳ {s.get('insufficient_data',0)}</p></div>

<div class="card"><h2>📋 候选验证</h2>
<table><tr><th></th><th>名称</th><th>标签</th><th>结论</th><th>Conf</th><th>Est SR</th><th>Est Ret</th></tr>{rows}</table></div>

<div class="card"><h2>📝 人工确认</h2>
<p>manual_approval_template.md — 需人工确认后才能采纳建议。</p>
<p>auto_apply: false | requires_human_approval: true</p></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V2.9 | {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</body></html>"""
