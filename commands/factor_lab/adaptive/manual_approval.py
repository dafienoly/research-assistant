"""Manual Approval V2.10 — 人工审批 + 配置变更草案"""
import os, json, csv as _csv
from pathlib import Path
from datetime import datetime, timezone, timedelta
from copy import deepcopy

CST = timezone(timedelta(hours=8))
BASE = Path("/mnt/d/HermesReports")


def run_approval_workflow(run_id: str = None, latest: bool = False, candidate: str = None,
                          approve: str = None, reject: str = None, defer: str = None) -> dict:
    """运行人工审批流程"""
    # 定位 V2.9 输出
    if latest:
        parent = BASE / "recommendation_backtest"
        runs = sorted(parent.iterdir()) if parent.exists() else []
        if not runs:
            return {"error": "没有找到 V2.9 输出", "status": "failed"}
        run_id = runs[-1].name

    src_dir = BASE / "recommendation_backtest" / run_id
    if not src_dir.exists():
        return {"error": f"V2.9 目录不存在: {src_dir}", "status": "failed"}

    # 加载候选
    ab_path = src_dir / "ab_comparison.csv"
    if not ab_path.exists():
        return {"error": "ab_comparison.csv 不存在", "status": "failed"}

    import csv
    candidates = []
    with open(ab_path) as f:
        for row in csv.DictReader(f):
            candidates.append(row)

    if not candidates:
        return {"error": "无候选数据", "status": "failed"}

    # 应用审批动作
    approved = []
    rejected = []
    deferred = []

    for c in candidates:
        name = c.get("name", "?")
        verdict = c.get("verdict", "insufficient_data")
        confidence = float(c.get("confidence", 0))

        # 确定是否被选中操作
        is_target = (candidate is None or name == candidate)
        action = None
        if approve and name == approve:
            action = "approve"
        elif reject and name == reject:
            action = "reject"
        elif defer and name == defer:
            action = "defer"

        # 安全规则
        if verdict == "reject_candidate" and action == "approve" and not is_target:
            action = "reject"  # reject 候选不能 approve

        if verdict == "insufficient_data" and action == "approve":
            action = "defer"  # insufficient_data 只能 defer

        if confidence < 0.3 and action == "approve":
            action = "defer"  # 低置信度只能 defer

        if action == "approve" or (verdict == "accept_candidate" and action is None and is_target):
            entry = _build_entry(c, "approved")
            approved.append(entry)
        elif action == "reject" or (verdict == "reject_candidate" and action is None):
            rejected.append(_build_entry(c, "rejected"))
        else:
            deferred.append(_build_entry(c, "deferred"))

    out_dir = BASE / "manual_approval" / run_id
    os.makedirs(out_dir, exist_ok=True)

    result = {
        "run_id": run_id,
        "source_dir": str(src_dir),
        "generated_at": datetime.now(CST).isoformat(),
        "approved": approved,
        "rejected": rejected,
        "deferred": deferred,
        "summary": {"approved": len(approved), "rejected": len(rejected), "deferred": len(deferred)},
        "auto_apply": False,
        "requires_human_approval": True,
        "status": "completed",
    }

    _write_outputs(result, out_dir)
    return result


def _build_entry(c, status):
    return {
        "candidate_name": c.get("name", "?"),
        "label": c.get("label", ""),
        "verdict": c.get("verdict", "?"),
        "approval_status": status,
        "confidence": c.get("confidence", "?"),
        "evidence": c.get("evidence", ""),
        "est_sharpe": c.get("est_sharpe", ""),
        "est_return_pct": c.get("est_return_pct", ""),
    }


def _write_outputs(result, out_dir):
    approved = result.get("approved", [])
    rejected = result.get("rejected", [])
    deferred = result.get("deferred", [])

    # JSON
    with open(out_dir / "manual_approval.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # CSVs
    for key, label, data in [("approved", "approved_candidates", approved),
                              ("rejected", "rejected_candidates", rejected),
                              ("deferred", "deferred_candidates", deferred)]:
        path = out_dir / f"{label}.csv"
        if data:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = _csv.DictWriter(f, fieldnames=data[0].keys(), extrasaction="ignore")
                w.writeheader()
                w.writerows(data)

    # Approval summary
    s = result.get("summary", {})
    import csv as _csv_mod
    with open(out_dir / "approval_summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = _csv_mod.writer(f)
        w.writerow(["key", "value"])
        for k, v in s.items():
            w.writerow([k, v])

    # Config patch preview
    with open(out_dir / "config_patch_preview.md", "w", encoding="utf-8") as f:
        f.write("# 配置变更预览\n\n## 变更内容\n\n")
        for a in approved:
            f.write(f"- **{a['candidate_name']}** ({a['label']}): {a['approval_status']}\n")
            f.write(f"  - Evidence: {a.get('evidence','')}\n")
            f.write(f"  - Est Sharpe: {a.get('est_sharpe','')}\n\n")
        f.write("\n*以上变更需人工确认后才能应用*\n")

    # Config patch diff
    diff_lines = []
    for a in approved:
        diff_lines.append(f"+# Enable: {a['candidate_name']}")
        diff_lines.append(f"+config.{a['candidate_name']}=true")
        diff_lines.append(f"+evidence={a.get('evidence','')}")
        diff_lines.append(f"+updated_at={datetime.now(CST).isoformat()}")
        diff_lines.append("")
    with open(out_dir / "config_patch.diff", "w") as f:
        f.write("\n".join(diff_lines) + "\n")

    # Rollback plan
    with open(out_dir / "rollback_plan.md", "w", encoding="utf-8") as f:
        f.write("# 回滚计划\n\n## 回滚步骤\n\n")
        for a in approved:
            f.write(f"1. 如果 {a['candidate_name']} 导致异常:\n")
            f.write(f"   - 恢复 baseline 配置\n")
            f.write(f"   - 重新运行 recommendation-backtest\n")
            f.write(f"   - 确认风险\n\n")
        f.write("*所有配置变更可回滚*\n")

    # Manual apply instructions
    with open(out_dir / "manual_apply_instructions.md", "w", encoding="utf-8") as f:
        f.write("# 人工应用说明\n\n")
        f.write("1. 审查 approved_candidates.csv\n")
        f.write("2. 审查 config_patch.diff\n")
        f.write("3. 手动修改对应配置文件\n")
        f.write("4. 重启策略服务\n")
        f.write("5. 验证变更生效\n")
        f.write("6. 保留 rollback_plan.md\n\n")
        f.write("*系统不自动修改配置*\n")

    # Audit log
    with open(out_dir / "audit.log", "w") as f:
        f.write(f"=== MANUAL APPROVAL AUDIT V2.10 ===\n")
        f.write(f"Source: {result['source_dir']}\n")
        f.write(f"Approved: {s.get('approved',0)}\n")
        f.write(f"Rejected: {s.get('rejected',0)}\n")
        f.write(f"Deferred: {s.get('deferred',0)}\n")
        f.write(f"Auto-apply: False\n")
        f.write(f"Requires human: True\n")
        f.write(f"No production changes: True\n")
        f.write(f"=== END ===\n")

    print(f"📁 {out_dir}")

    # Core framework: MigrationCompat
    try:
        from factor_lab.core.migration import MigrationCompat as _Compat
        from pathlib import Path as _Path
        _c = _Compat(str(out_dir), result.get("run_id", "?"), "manual_approval")
        for _fn in ["approval_report.html", "manual_approval.json", "audit.log"]:
            if _Path(str(out_dir / _fn)).exists():
                _c.legacy(_fn)
        _c.finalize(safety={"auto_apply": False, "no_live_trade": True, "requires_human_approval": True, "approval_only": True})
    except Exception:
        pass
