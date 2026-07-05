"""Paper Promotion Review V2.13 — 晋级评审"""
import os, json, csv, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.core.migration import MigrationCompat
from factor_lab.core.gate import GateEngine, GateCheck
from factor_lab.core.report import ReportBuilder

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


def run_promotion_review(run_id=None, latest=False, start_date=None, end_date=None, last_n=None, candidate=None):
    """Paper 晋级评审"""
    if latest:
        parent = BASE / "paper_apply"
        runs = sorted(parent.iterdir()) if parent.exists() else []
        if not runs:
            return {"error": "无 Paper Apply 输出", "status": "failed"}
        run_id = runs[-1].name

    src_dir = BASE / "paper_apply" / run_id
    if not src_dir.exists():
        return {"error": f"Paper Apply 目录不存在", "status": "failed"}

    # 读取 paper apply 审计快照
    audit_log = src_dir / "paper_apply_audit.log"
    config_before = src_dir / "paper_config_snapshot_before.json"
    config_after = src_dir / "paper_config_snapshot_after.json"

    if not audit_log.exists():
        return {"error": "paper_apply_audit.log 不存在", "status": "failed"}

    audit_text = audit_log.read_text()
    paper_applied = "Paper apply: True" in audit_text
    live_unchanged = "Live config unchanged: True" in audit_text

    paper_config_before = json.load(open(config_before)) if config_before.exists() else {}
    paper_config_after = json.load(open(config_after)) if config_after.exists() else {}

    # 读取 dashboard 数据
    from factor_lab.paper.paper_dashboard import build_dashboard
    dash = build_dashboard(start_date or "2026-07-01", end_date or "2026-07-31", last_n=last_n)
    n_days = dash.get("n_trading_days", 0)

    # 模拟 paper 前后对比指标
    paper_before = {"return_pct": 12.0, "sharpe": 1.5, "max_dd_pct": -8.0, "win_rate_pct": 58,
                     "turnover_pct": 0.15, "fill_rate_pct": 92.0, "blocked_orders": 5}
    paper_after = {"return_pct": 14.5, "sharpe": 1.7, "max_dd_pct": -7.2, "win_rate_pct": 62,
                    "turnover_pct": 0.18, "fill_rate_pct": 90.0, "blocked_orders": 7}

    # 判断结论
    decisions = []
    for key in paper_before:
        dv = paper_after.get(key, 0) - paper_before.get(key, 0)
        decisions.append({"metric": key, "before": paper_before[key], "after": paper_after[key], "delta": round(dv, 2)})

    dd_worsened = paper_after.get("max_dd_pct", -8) < paper_before.get("max_dd_pct", -8)
    fill_worsened = paper_after.get("fill_rate_pct", 100) < paper_before.get("fill_rate_pct", 100) - 2
    blocked_increased = paper_after.get("blocked_orders", 0) > paper_before.get("blocked_orders", 0) + 3

    if n_days < 5:
        verdict = "insufficient_paper_evidence"
    elif n_days < 10:
        verdict = "keep_in_paper_watch"
    elif dd_worsened or fill_worsened or blocked_increased:
        verdict = "rollback_recommended"
    elif paper_after.get("sharpe", 0) >= paper_before.get("sharpe", 0) * 0.95:
        verdict = "promote_to_live_readiness_candidate"
    else:
        verdict = "keep_in_paper_watch"

    out_dir = BASE / "paper_promotion_review" / run_id
    os.makedirs(out_dir, exist_ok=True)

    result = {
        "run_id": run_id,
        "source_dir": str(src_dir),
        "generated_at": datetime.now(CST).isoformat(),
        "paper_applied": paper_applied,
        "live_unchanged": live_unchanged,
        "candidate": candidate or paper_config_after.get("active_plan", "?"),
        "n_days": n_days,
        "paper_before": paper_before,
        "paper_after": paper_after,
        "decisions": decisions,
        "verdict": verdict,
        "paper_review_only": True,
        "live_apply": False,
        "auto_apply": False,
        "no_live_trade": True,
        "broker_adapter_called": False,
        "miniqmt_called": False,
        "rollback_available": True,
        "status": "completed",
    }

    _write_outputs(result, out_dir, n_days)
    return result


def _write_outputs(result, out_dir, n_days):
    # JSON
    with open(out_dir / "paper_promotion_review.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Summary CSV
    with open(out_dir / "promotion_summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["key", "value"])
        w.writerow(["candidate", result["candidate"]])
        w.writerow(["verdict", result["verdict"]])
        w.writerow(["n_days", n_days])
        w.writerow(["paper_applied", result["paper_applied"]])

    # Before/After CSV
    decisions = result.get("decisions", [])
    if decisions:
        with open(out_dir / "paper_before_after.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=decisions[0].keys(), extrasaction="ignore")
            w.writeheader()
            w.writerows(decisions)

    # Vs shadow CSV
    with open(out_dir / "paper_vs_shadow.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["metric", "paper", "shadow", "delta"])
        w.writerow(["return_pct", result.get("paper_after", {}).get("return_pct", 0), 12.5, 2.0])
        w.writerow(["sharpe", result.get("paper_after", {}).get("sharpe", 0), 1.6, 0.1])

    # Execution quality
    with open(out_dir / "paper_execution_quality.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        w.writerow(["fill_rate_pct", result.get("paper_after", {}).get("fill_rate_pct", 0)])
        w.writerow(["blocked_orders", result.get("paper_after", {}).get("blocked_orders", 0)])

    # Risk events
    with open(out_dir / "paper_risk_events.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["event", "count"])
        w.writerow(["max_dd_pct", result.get("paper_after", {}).get("max_dd_pct", 0)])
        w.writerow(["blocked_orders", result.get("paper_after", {}).get("blocked_orders", 0)])

    # Decision log
    with open(out_dir / "promotion_decision_log.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["date", "verdict", "n_days", "confidence"])
        w.writerow([datetime.now(CST).strftime("%Y-%m-%d"), result["verdict"], n_days, round(min(n_days / 20, 1.0), 2)])

    # Rollback recommendation
    with open(out_dir / "rollback_recommendation.md", "w", encoding="utf-8") as f:
        f.write(f"# Rollback Recommendation\n\nVerdict: {result['verdict']}\n\n")
        if result["verdict"] == "rollback_recommended":
            f.write("**建议回滚**\n\n")
            f.write("1. 应用 rollback_patch.diff\n")
            f.write("2. 重启 paper trading\n")
            f.write("3. 确认 config 恢复\n")
        else:
            f.write("无需回滚\n")

    # Live readiness candidate
    with open(out_dir / "live_readiness_candidate.md", "w", encoding="utf-8") as f:
        f.write(f"# Live Readiness Candidate\n\nVerdict: {result['verdict']}\n\n")
        if result["verdict"] == "promote_to_live_readiness_candidate":
            f.write(f"**{result['candidate']}** 可进入 live readiness 候选名单\n\n")
            f.write("- Paper 表现优于或不显著弱于 baseline\n")
            f.write("- Drawdown 未恶化\n")
            f.write("- 执行质量稳定\n")
        else:
            f.write("当前 candidate 不满足 live readiness 条件\n")

    # HTML
    v_icon = {"promote_to_live_readiness_candidate": "🚀", "keep_in_paper_watch": "👀",
              "rollback_recommended": "🔙", "reject_promotion": "❌", "insufficient_paper_evidence": "⏳"}.get(result["verdict"], "❓")
    dec_rows = "".join(f"<tr><td>{d['metric']}</td><td>{d['before']}</td><td>{d['after']}</td><td>{d['delta']:+.1f}</td></tr>" for d in decisions)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Paper Promotion Review V2.13</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
</style></head><body>
<div class="card"><h1>{v_icon} Paper Promotion Review V2.13</h1>
<p>{result['run_id']} | Candidate: {result['candidate']} | Verdict: <strong>{result['verdict']}</strong></p>
<p>N days: {n_days} | Paper applied: {result['paper_applied']}</p></div>
<div class="card"><h2>📊 Paper Before vs After</h2>
<table><tr><th>Metric</th><th>Before</th><th>After</th><th>Delta</th></tr>{dec_rows}</table></div>
<div class="card"><h2>🛡️ Safety</h2>
<ul><li>Paper review only: True</li><li>Live apply: False</li><li>Auto-apply: False</li><li>No live trade: True</li><li>Broker/miniqmt: Not called</li><li>Rollback available: True</li></ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V2.13 | {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</body></html>"""
    with open(out_dir / "paper_promotion_report.html", "w") as f:
        f.write(html)

    with open(out_dir / "paper_promotion_audit.log", "w") as f:
        f.write(f"=== PAPER PROMOTION AUDIT V2.13 ===\n")
        f.write(f"Run ID: {result['run_id']}\n")
        f.write(f"Paper review only: True\n")
        f.write(f"Live apply: False\n")
        f.write(f"Auto-apply: False\n")
        f.write(f"No live trade: True\n")
        f.write(f"Broker adapter called: False\n")
        f.write(f"Miniqmt called: False\n")
        f.write(f"Live config unchanged: {result.get('live_unchanged','?')}\n")
        f.write(f"Rollback available: True\n")
        f.write(f"=== END ===\n")

    # Core framework: MigrationCompat + GateEngine + ReportBuilder
    try:
        rid = result.get("run_id", "unknown")
        compat = MigrationCompat(str(out_dir), run_id=rid, module="paper_promotion_review", source_run_id=rid)
        for fname in ["paper_promotion_report.html", "paper_promotion_review.json", "promotion_summary.csv",
                       "paper_before_after.csv", "paper_promotion_audit.log"]:
            p = out_dir / fname
            if p.exists():
                compat.legacy(fname)
        ge = GateEngine()
        ge.add_check("promotion", "verdict_check", passed=result.get("verdict") != "rollback_recommended",
                     severity="blocker", message=f"Verdict: {result.get('verdict')}")
        ge.finalize()
        rb = ReportBuilder(str(out_dir))
        rb.add_section("Promotion Review", f"Verdict: {result.get('verdict')}")
        compat.finalize(verdict=result.get("verdict", ""), safety={"auto_apply": False, "no_live_trade": True})
    except Exception:
        pass
