"""Hermes A股投研助手 — 数据质量检查

包含新鲜度检查 (freshness-checker) 和数据缺口报告 (data-gap-reporter)。
"""

import csv
import json
from datetime import datetime

from config import (
    PATHS, append_jsonl, now_cst, now_str, safe_write_json,
)


# ========== 新鲜度检查 ==========

class FreshnessChecker:
    """检查各数据文件的新鲜度和完整性"""

    THRESHOLDS = {
        "market/pool.csv": {"max_age_minutes": 1440, "gate_scope": "auxiliary"},
        "market/live_snapshot.csv": {"max_age_seconds": 60, "gate_scope": "auxiliary_intraday"},
        "fundamentals/financial_snapshot.csv": {"max_age_days": 7, "gate_scope": "auxiliary"},
        "events/preopen_events.csv": {"max_age_hours": 18, "gate_scope": "auxiliary"},
        "intraday/live_snapshot_priority.csv": {"max_age_seconds": 60, "gate_scope": "auxiliary_intraday"},
    }

    def check_all(self) -> dict:
        """检查所有关键文件，返回报告"""
        now = now_cst()
        report = {
            "check_time": now_str(),
            "overall_status": "ok",
            "files": [],
            "blocking": False,
        }

        data_dir = PATHS["data"]

        for rel_path, thresholds in self.THRESHOLDS.items():
            abs_path = data_dir / rel_path
            entry = {
                "path": rel_path,
                "status": "missing",
                "last_updated": None,
                "max_age_seconds": 0,
                "actual_age_seconds": 0,
                "gate_scope": thresholds.get("gate_scope", "auxiliary"),
                "note": "",
            }

            if not abs_path.exists():
                entry["status"] = "missing"
                entry["note"] = "文件不存在"
                report["files"].append(entry)
                continue

            mtime = datetime.fromtimestamp(abs_path.stat().st_mtime, tz=now.tzinfo)
            age_seconds = (now - mtime).total_seconds()
            entry["last_updated"] = mtime.strftime("%Y-%m-%dT%H:%M:%S+08:00")
            entry["actual_age_seconds"] = int(age_seconds)

            # 判断阈值类型
            if "max_age_seconds" in thresholds:
                max_age = thresholds["max_age_seconds"]
                entry["max_age_seconds"] = max_age
                if age_seconds > max_age:
                    entry["status"] = "stale"
                    entry["note"] = f"延迟 {int(age_seconds)}s > 阈值 {max_age}s"
                else:
                    entry["status"] = "ok"
            elif "max_age_minutes" in thresholds:
                max_age = thresholds["max_age_minutes"] * 60
                entry["max_age_seconds"] = max_age
                if age_seconds > max_age:
                    entry["status"] = "stale"
                else:
                    entry["status"] = "ok"
            elif "max_age_hours" in thresholds:
                max_age = thresholds["max_age_hours"] * 3600
                entry["max_age_seconds"] = max_age
                if age_seconds > max_age:
                    entry["status"] = "stale"
                else:
                    entry["status"] = "ok"
            elif "max_age_days" in thresholds:
                max_age = thresholds["max_age_days"] * 86400
                entry["max_age_seconds"] = max_age
                if age_seconds > max_age:
                    entry["status"] = "stale"
                else:
                    entry["status"] = "ok"

            report["files"].append(entry)

        # 总体状态
        statuses = [f["status"] for f in report["files"]]
        if "missing" in statuses:
            report["overall_status"] = "missing_files"
        elif "stale" in statuses:
            report["overall_status"] = "stale"
        else:
            report["overall_status"] = "ok"
        report["auxiliary_degraded"] = report["overall_status"] != "ok"

        return report

    def run(self) -> dict:
        """执行检查并保存报告"""
        report = self.check_all()
        audit_dir = PATHS["audit"]
        audit_dir.mkdir(parents=True, exist_ok=True)
        report_path = audit_dir / "data_freshness_report.json"
        safe_write_json(report_path, report)

        # 也写入 fetch_log
        append_jsonl(audit_dir / "fetch_log.jsonl", {
            "timestamp": now_str(),
            "action": "freshness_check",
            "status": report["overall_status"],
            "blocking": report["blocking"],
        })

        status_icon = {"ok": "✅", "stale": "⚠️", "missing_files": "❌"}
        print(f"{status_icon.get(report['overall_status'], '❓')} 新鲜度检查完成: {report['overall_status']}")
        if report["blocking"]:
            print("🚫 存在阻塞性数据延迟！")

        return report


# ========== 数据缺口报告 ==========

class DataGapReporter:
    """检测数据采集中的缺口问题"""

    REQUIRED_FILES = [
        "market/pool.csv",
        "fundamentals/financial_snapshot.csv",
        "events/preopen_events.csv",
        "tags/industry_chain_tags.csv",
        "tags/semiconductor_chain_tags.csv",
        "tags/stock_theme_tags.csv",
    ]

    def report(self) -> dict:
        """生成数据缺口报告"""
        data_dir = PATHS["data"]
        gaps = []
        availability = self._tag_availability(data_dir / "tags/tag_availability.json")

        # 检查必需文件
        for rel_path in self.REQUIRED_FILES:
            abs_path = data_dir / rel_path
            if not abs_path.exists():
                declared = availability.get(rel_path.removeprefix("tags/"), {})
                unavailable = declared.get("status") == "MISSING_SOURCE_DATA"
                gaps.append({
                    "name": rel_path,
                    "description": declared.get("reason") if unavailable else f"必需文件缺失: {rel_path}",
                    "category": self._categorize(rel_path),
                    "gap_type": "source_unavailable" if unavailable else "missing_file",
                    "affected_stocks": [],
                    "affected_fields": [],
                    "failed_source": declared.get("source") or "",
                    "failure_reason": declared.get("reason") if unavailable else f"必需文件缺失: {rel_path}",
                    "impact": "blocking" if rel_path == "market/pool.csv" else "partial",
                    "blocking_codex": rel_path == "market/pool.csv",
                    "recommendation": (
                        f"接入并验证 {rel_path} 的 durable upstream 后增量生成；不得用空文件解除门禁"
                        if unavailable else f"请运行对应 fetcher 生成 {rel_path}"
                    ),
                })

        # 检查盘前事件是否覆盖
        preopen_path = data_dir / "events/preopen_events.csv"
        if preopen_path.exists():
            try:
                with open(preopen_path, "r", encoding="utf-8-sig") as f:
                    rows = list(csv.DictReader(f))
                if not rows:
                    gaps.append({
                        "name": "events/preopen_events.csv",
                        "description": "preopen_events.csv 为空",
                        "category": "event",
                        "gap_type": "empty_file",
                        "affected_stocks": [],
                        "affected_fields": [],
                        "failed_source": "policy_event_fetcher",
                        "failure_reason": "preopen_events.csv 为空",
                        "impact": "minor",
                        "blocking_codex": False,
                        "recommendation": "检查政策/新闻数据源",
                    })
            except Exception as e:
                gaps.append({
                    "name": "events/preopen_events.csv",
                    "description": f"preopen_events.csv 解析失败: {e}",
                    "category": "event",
                    "gap_type": "parse_error",
                    "affected_stocks": [],
                    "affected_fields": [],
                    "failed_source": "policy_event_fetcher",
                    "failure_reason": f"preopen_events.csv 解析失败: {e}",
                    "impact": "partial",
                    "blocking_codex": False,
                    "recommendation": "检查 CSV 格式",
                })

        # 统计
        blocking_count = sum(1 for g in gaps if g.get("impact") == "blocking")
        partial_count = sum(1 for g in gaps if g.get("impact") == "partial")

        report = {
            "report_time": now_str(),
            "gaps": gaps,
            "summary": {
                "total_gaps": len(gaps),
                "blocking_gaps": blocking_count,
                "partial_gaps": partial_count,
                "blocking_codex": any(g.get("blocking_codex") for g in gaps),
            },
        }

        # 保存报告
        audit_dir = PATHS["audit"]
        audit_dir.mkdir(parents=True, exist_ok=True)
        report_path = audit_dir / "data_gap_report.json"
        safe_write_json(report_path, report)

        # 写入 fetch_log
        append_jsonl(audit_dir / "fetch_log.jsonl", {
            "timestamp": now_str(),
            "action": "gap_report",
            "total_gaps": len(gaps),
            "blocking": report["summary"]["blocking_codex"],
        })

        return report

    @staticmethod
    def _tag_availability(path):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            datasets = payload.get("datasets", {})
            return datasets if isinstance(datasets, dict) else {}
        except (OSError, json.JSONDecodeError, AttributeError):
            return {}

    @staticmethod
    def _categorize(rel_path: str) -> str:
        if rel_path.startswith("market/"):
            return "market"
        if rel_path.startswith("fundamentals/"):
            return "fundamental"
        if rel_path.startswith("events/"):
            return "event"
        if rel_path.startswith("tags/"):
            return "tag"
        if rel_path.startswith("intraday/"):
            return "intraday"
        return "other"


# === CLI 命令 ===
def cmd_freshness():
    fc = FreshnessChecker()
    fc.run()


def cmd_gap():
    dgr = DataGapReporter()
    report = dgr.report()
    summary = report["summary"]
    print(f"📋 数据缺口报告: {summary['total_gaps']} 缺口, {summary['blocking_gaps']} 阻塞")
    for g in report["gaps"]:
        print(f"  {'🚫' if g['impact']=='blocking' else '⚠️'} [{g['category']}] {g['failure_reason']}")


if __name__ == "__main__":
    import sys
    cmds = {
        "freshness": cmd_freshness,
        "gap": cmd_gap,
    }
    if len(sys.argv) > 1 and sys.argv[1] in cmds:
        cmds[sys.argv[1]]()
    else:
        print("Usage: python data_quality.py <command>")
        print(f"Commands: {', '.join(cmds.keys())}")
