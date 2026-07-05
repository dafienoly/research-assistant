"""Version Report — 版本开发报告生成"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from factor_lab.leader.roadmap_cursor import get_cursor
from factor_lab.leader.roadmap import get_version
from factor_lab.leader.workloop import TASKS_DIR, read_completion

CST = timezone(timedelta(hours=8))
REPORT_DIR = Path("/mnt/d/HermesReports/version_reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def generate_report(version: str = None) -> dict:
    """生成版本开发报告"""
    cursor = get_cursor()
    versions_data = cursor.get("completed_versions", [])
    failed = cursor.get("failed_versions", [])
    current = cursor.get("current_version", "?")
    completion = read_completion()

    details = []
    for v in versions_data + failed:
        vd = get_version(v)
        status = "failed" if v in failed else "completed"
        details.append({
            "version": v,
            "name": vd.name if vd else v,
            "objective": vd.objective if vd else "",
            "status": status,
        })

    report = {
        "generated_at": datetime.now(CST).isoformat(),
        "current_version": current,
        "total_completed": len(versions_data),
        "total_failed": len(failed),
        "versions": details,
        "last_completion": completion,
    }

    ts = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"version_report_{ts}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    # 同时写入 latest report
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report
