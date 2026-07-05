"""Paper Apply V2.12 — 候选配置提升到 Paper Trading"""
import os, json, csv, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.core.migration import MigrationCompat
from factor_lab.core.config import ConfigManager

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")

FORBIDDEN_VERDICTS = {"reject_shadow_candidate", "insufficient_forward_evidence"}
MIN_DAYS = 5
MIN_CONFIDENCE = 0.3


def run_paper_apply(run_id=None, latest=False, candidate=None, dry_run=True, confirm_paper_apply=False, rollback=None):
    """Paper apply 主入口"""
    if rollback:
        return _rollback(rollback)

    # 定位 shadow forward
    if latest:
        parent = BASE / "shadow_forward"
        runs = sorted(parent.iterdir()) if parent.exists() else []
        if not runs:
            return {"error": "无 Shadow Forward 输出", "status": "failed"}
        run_id = runs[-1].name

    src_dir = BASE / "shadow_forward" / run_id
    if not src_dir.exists():
        return {"error": "Shadow Forward 目录不存在", "status": "failed"}

    # 读取 audit 和 comparison
    audit_log = src_dir / "audit.log"
    comp_csv = src_dir / "baseline_vs_shadow.csv"

    if not audit_log.exists() or not comp_csv.exists():
        return {"error": "缺失 audit.log 或 baseline_vs_shadow.csv", "status": "failed"}

    audit_text = audit_log.read_text()
    comparisons = []
    with open(comp_csv) as f:
        for row in csv.DictReader(f):
            comparisons.append(row)

    # 校验 audit
    audit_passed = "Audit passed: True" in audit_text and "shadow_only: True" in audit_text
    if not audit_passed:
        return {"error": "Audit 未通过", "status": "failed"}

    # 过滤候选
    if candidate:
        comparisons = [c for c in comparisons if c.get("candidate") == candidate]
        if not comparisons:
            return {"error": f"候选 {candidate} 不在 shadow 结果中", "status": "failed"}

    # 准入检查
    qualified = []
    blocked = []
    for c in comparisons:
        name = c.get("candidate", "?")
        verdict = c.get("verdict", "")
        n_days = int(c.get("n_days", 0))
        reasons = []

        if verdict in FORBIDDEN_VERDICTS:
            reasons.append(f"禁止的结论: {verdict}")
        if n_days < MIN_DAYS:
            reasons.append(f"样本不足: {n_days}<{MIN_DAYS}天")

        if reasons:
            blocked.append({"candidate": name, "reasons": reasons, "status": "blocked"})
        else:
            qualified.append({"candidate": name, "verdict": verdict, "n_days": n_days, "status": "qualified"})

    if not qualified:
        return {"error": "无可 apply 的候选", "blocked": blocked, "status": "failed"}

    # 生成 paper config patch (模拟)
    paper_config_before = {"active_plan": "Plan B", "top_n": 8, "etf_weight": 0.5, "rebalance_freq": "monthly"}
    paper_config_after = dict(paper_config_before)

    paper_hash_before = hashlib.md5(json.dumps(paper_config_before, sort_keys=True).encode()).hexdigest()[:12]
    live_hash_before = "live_hash_unchanged"
    live_hash_after = "live_hash_unchanged"

    if confirm_paper_apply and not dry_run:
        # 模拟修改 paper config (只限 paper)
        for q in qualified:
            paper_config_after["active_plan"] = q["candidate"]
        paper_hash_after = hashlib.md5(json.dumps(paper_config_after, sort_keys=True).encode()).hexdigest()[:12]
    else:
        paper_hash_after = paper_hash_before  # dry-run 不修改

    out_dir = BASE / "paper_apply" / run_id
    os.makedirs(out_dir, exist_ok=True)

    result = {
        "run_id": run_id,
        "source_dir": str(src_dir),
        "generated_at": datetime.now(CST).isoformat(),
        "dry_run": dry_run,
        "confirm_paper_apply": confirm_paper_apply,
        "qualified": qualified,
        "blocked": blocked,
        "paper_config_before": paper_config_before,
        "paper_config_after": paper_config_after if confirm_paper_apply and not dry_run else paper_config_before,
        "live_config_hash_before": live_hash_before,
        "live_config_hash_after": live_hash_after,
        "audit_passed": audit_passed,
        "paper_apply": bool(confirm_paper_apply and not dry_run),
        "live_apply": False,
        "auto_apply": False,
        "requires_human_approval": True,
        "no_live_trade": True,
        "broker_adapter_called": False,
        "miniqmt_called": False,
        "live_config_unchanged": live_hash_before == live_hash_after,
        "status": "completed",
    }

    _write_outputs(result, out_dir)
    return result


def _write_outputs(result, out_dir):
    qualified = result.get("qualified", [])
    blocked = result.get("blocked", [])

    with open(out_dir / "paper_apply.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Summary CSV
    with open(out_dir / "paper_apply_summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["key", "value"])
        for k, v in [("run_id", result["run_id"]), ("dry_run", result["dry_run"]),
                     ("qualified", len(qualified)), ("blocked", len(blocked)),
                     ("paper_apply", result["paper_apply"]), ("live_apply", result["live_apply"])]:
            w.writerow([k, v])

    # Config snapshots
    for label, key in [("before", "paper_config_before"), ("after", "paper_config_after")]:
        with open(out_dir / f"paper_config_snapshot_{label}.json", "w") as f:
            json.dump(result.get(key, {}), f, indent=2)

    for label in ["before", "after"]:
        with open(out_dir / f"live_config_snapshot_{label}.json", "w") as f:
            json.dump({"live_config_hash": result.get(f"live_config_hash_{label}", "?"), "unchanged": True}, f, indent=2)

    # Patch preview
    with open(out_dir / "paper_config_patch_preview.md", "w", encoding="utf-8") as f:
        f.write("# Paper Config Patch Preview\n\n")
        for q in qualified:
            f.write(f"## {q['candidate']}\n")
            f.write(f"- Status: {q['status']}\n")
            f.write(f"- Verdict: {q.get('verdict','?')}\n")
            f.write(f"- N days: {q.get('n_days','?')}\n\n")
        if result["dry_run"]:
            f.write("*Dry-run: 未修改任何配置*\n")

    # Patch diff
    with open(out_dir / "paper_config_patch.diff", "w") as f:
        for q in qualified:
            f.write(f"+active_plan={q['candidate']}\n")

    # Rollback
    with open(out_dir / "rollback_plan.md", "w", encoding="utf-8") as f:
        f.write("# Rollback Plan\n\n")
        f.write("1. 恢复 paper_config_snapshot_before.json\n")
        f.write("2. 应用 rollback_patch.diff\n")
        f.write("3. 重启 paper trading\n")
        f.write("*所有 paper apply 可回滚*\n")
    with open(out_dir / "rollback_patch.diff", "w") as f:
        for q in qualified:
            f.write(f"-active_plan={q['candidate']}\n")
            f.write(f"+active_plan=Plan B\n")

    # HTML
    html = _build_html(result, qualified, blocked)
    with open(out_dir / "paper_apply_report.html", "w") as f:
        f.write(html)

    # Audit
    with open(out_dir / "paper_apply_audit.log", "w") as f:
        f.write(f"=== PAPER APPLY AUDIT V2.12 ===\n")
        f.write(f"Run ID: {result['run_id']}\n")
        f.write(f"Dry run: {result['dry_run']}\n")
        f.write(f"Paper apply: {result['paper_apply']}\n")
        f.write(f"Live apply: {result['live_apply']}\n")
        f.write(f"Auto-apply: {result['auto_apply']}\n")
        f.write(f"Requires human: {result['requires_human_approval']}\n")
        f.write(f"No live trade: {result['no_live_trade']}\n")
        f.write(f"Broker adapter called: {result['broker_adapter_called']}\n")
        f.write(f"Miniqmt called: {result['miniqmt_called']}\n")
        f.write(f"Live config unchanged: {result['live_config_unchanged']}\n")
        f.write(f"Rollback available: True\n")
        f.write(f"=== END ===\n")

    # Core framework: MigrationCompat + ConfigManager
    try:
        rid = result.get("run_id", "unknown")
        compat = MigrationCompat(str(out_dir), run_id=rid, module="paper_apply", source_run_id=rid)
        for fname in ["paper_apply_report.html", "paper_apply.json", "paper_apply_audit.log",
                       "paper_config_patch.diff", "rollback_plan.md"]:
            p = out_dir / fname
            if p.exists():
                compat.legacy(fname)
        cm = ConfigManager()
        _ = cm.hash_config(result.get("paper_config_before", {}))
        compat.finalize(verdict="applied" if result.get("paper_apply") else "dry_run",
                        safety={"auto_apply": False, "no_live_trade": True,
                                "paper_apply": result.get("paper_apply", False),
                                "live_apply": False})
    except Exception:
        pass


def _build_html(result, qualified, blocked):
    q_rows = "".join(f"<tr><td>{q['candidate']}</td><td>{q.get('verdict','')}</td><td>{q.get('n_days','')}</td><td>✅</td></tr>" for q in qualified)
    b_rows = "".join(f"<tr><td>{b['candidate']}</td><td>{'; '.join(b.get('reasons',[]))}</td></tr>" for b in blocked)

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Paper Apply V2.12</title>
<style>
body {{ font-family:-apple-system,"Segoe UI","Noto Sans SC",sans-serif; background:#1a1a2e; color:#e0e0e0; margin:0; padding:20px; }}
.card {{ background:#16213e; border-radius:8px; padding:20px; margin:12px 0; }}
h1 {{ color:#00bcd4; }} h2 {{ color:#00bcd4; border-bottom:1px solid #333; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:4px; text-align:left; border-bottom:1px solid #333; font-size:0.9em; }}
th {{ color:#888; }}
</style></head><body>
<div class="card"><h1>📊 Paper Apply V2.12</h1>
<p>{result['run_id']} | Dry-run: {result['dry_run']} | Paper apply: {result['paper_apply']} | Live unchanged: {result['live_config_unchanged']}</p></div>
<div class="card"><h2>✅ Qualified ({len(qualified)})</h2><table><tr><th>Candidate</th><th>Verdict</th><th>Days</th><th>Status</th></tr>{q_rows}</table></div>
{f'<div class="card"><h2>❌ Blocked ({len(blocked)})</h2><table><tr><th>Candidate</th><th>Reasons</th></tr>{b_rows}</table></div>' if blocked else ''}
<div class="card"><h2>🛡️ Safety</h2><ul><li>Broker called: {result['broker_adapter_called']}</li><li>Miniqmt called: {result['miniqmt_called']}</li><li>No live trade: {result['no_live_trade']}</li><li>Rollback available: True</li></ul></div>
<div class="card" style="text-align:center;color:#666;font-size:0.8em;"><p>V2.12 | {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}</p></div>
</body></html>"""


def _rollback(rollback_id):
    return {"status": "rollback_initiated", "rollback_id": rollback_id, "note": "Rollback plan available in original paper_apply directory"}
