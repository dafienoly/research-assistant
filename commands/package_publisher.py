"""Hermes A股投研助手 — Package 发布器

原子发布数据包到 Codex incoming_from_hermes 目录。
"""

import shutil
import json
from pathlib import Path
from datetime import datetime

from config import (
    INCOMING, PATHS, now_cst, now_str, ts_id, date_id,
    CODEX_DATA,
    file_sha256, file_rows, safe_write_json, ensure_dirs,
)


class PackagePublisher:
    """数据包发布器

    使用方式:
        pp = PackagePublisher()
        pp.create("preopen_events")
        pp.add_file("events/preopen_events.csv")
        pp.add_file("audit/data_freshness_report.json")
        pp.finalize()
    """

    def __init__(self, package_type: str, timestamp: str = None):
        ensure_dirs()
        self.package_type = package_type
        self.ts = timestamp or ts_id()
        self.package_id = f"{self.ts}_{package_type}"
        self.created_at = now_str()
        self.data_date = date_id()
        self.files_meta = []
        self.source_summary = {}
        self.freshness_status = "ok"
        self.freshness_blocking = False
        self.max_delay_seconds = 0

        # 临时目录
        self.tmp_dir = INCOMING / f"{self.package_id}.tmp"
        self.payload_dir = self.tmp_dir / "payload"
        self.manifest_path = self.tmp_dir / "manifest.json"
        self.success_path = self.tmp_dir / "_SUCCESS"

        # 最终目录
        self.final_dir = INCOMING / self.package_id

        # 清理残留
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        if self.final_dir.exists():
            shutil.rmtree(self.final_dir)

    def add_file(self, rel_path: str, source_name: str = None, target_rel_path: str = None):
        """添加一个文件到 package

        rel_path: 相对于 data/ 的源文件路径，如 "events/preopen_events.csv"
        source_name: 数据源名称，用于 source_summary
        target_rel_path: 发布时的目标路径（可选，不指定则与 rel_path 相同）
        """
        src = PATHS.get("data", Path()) / rel_path
        if not src.exists():
            raise FileNotFoundError(f"源文件不存在: {src}")

        dest_rel = target_rel_path or rel_path
        dest = self.payload_dir / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

        rows = file_rows(dest)
        sha = file_sha256(dest)

        manifest_file = {
            "path": rel_path,
            "rows": rows,
            "sha256": sha,
        }
        self.files_meta.append(manifest_file)

        if source_name:
            if source_name not in self.source_summary:
                self.source_summary[source_name] = {"source": source_name, "status": "ok", "records": 0}
            self.source_summary[source_name]["records"] += rows

    def set_freshness(self, status: str, blocking: bool = False, max_delay_seconds: int = 0):
        self.freshness_status = status
        self.freshness_blocking = blocking
        self.max_delay_seconds = max_delay_seconds

    def _build_manifest(self) -> dict:
        return {
            "package_id": self.package_id,
            "producer": "hermes",
            "env": "wsl",
            "created_at": self.created_at,
            "type": self.package_type,
            "data_date": self.data_date,
            "files": self.files_meta,
            "freshness": {
                "status": self.freshness_status,
                "blocking": self.freshness_blocking,
                "max_delay_seconds": self.max_delay_seconds,
            },
            "source_summary": list(self.source_summary.values()),
        }

    def finalize(self):
        """完成发布：写 manifest + 原子重命名 + _SUCCESS"""
        # 写 manifest
        manifest = self._build_manifest()
        safe_write_json(self.manifest_path, manifest)

        # 计算 manifest 自身 hash 并更新
        manifest_sha = file_sha256(self.manifest_path)
        manifest["manifest_sha256"] = manifest_sha
        safe_write_json(self.manifest_path, manifest)

        # 原子重命名: .tmp → 正式目录
        self.tmp_dir.rename(self.final_dir)

        # 写 _SUCCESS
        success_path = self.final_dir / "_SUCCESS"
        success_path.write_text(f"Package {self.package_id} completed at {now_str()}\n")

        return self.package_id

    def abort(self):
        """清理临时目录"""
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)
        if self.final_dir.exists():
            shutil.rmtree(self.final_dir)

    @staticmethod
    def list_pending() -> list:
        """列出待消费的 packages（有 _SUCCESS）"""
        if not INCOMING.exists():
            return []
        packages = []
        for d in sorted(INCOMING.iterdir()):
            if d.is_dir() and (d / "_SUCCESS").exists() and not d.name.startswith("_"):
                packages.append(d.name)
        return packages


def _sync_to_codex_root(package_id: str):
    """将发布的文件同步到 Codex datahub 根级别"""
    pkg_dir = INCOMING / package_id
    payload_dir = pkg_dir / "payload"
    if not payload_dir.exists():
        return
    for f in payload_dir.rglob("*"):
        if f.is_file() and f.suffix in (".csv", ".json", ".jsonl"):
            rel = f.relative_to(payload_dir)
            dest = CODEX_DATA / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)


# === CLI 命令 ===
def cmd_publish_preopen():
    """hermes package:publish-preopen — 发布事件 + 公告 + 基本面数据"""
    pp = PackagePublisher("preopen_events")
    try:
        # 事件类
        for f in ["events/preopen_events.csv", "events/policy_events.csv"]:
            p = PATHS.get("data", Path()) / f
            if p.exists():
                pp.add_file(f)

        # 公告（本地名 → Codex 期望名）
        ann_src = "fundamentals/announcements_extracted.csv"
        ann_dst = "events/announcements.csv"
        p = PATHS.get("data", Path()) / ann_src
        if p.exists():
            pp.add_file(ann_src, target_rel_path=ann_dst)

        # 基本面
        for f in ["fundamentals/financial_snapshot.csv"]:
            p = PATHS.get("data", Path()) / f
            if p.exists():
                pp.add_file(f)

        # 业绩预告（本地名 → Codex 期望名）
        fc_src = "fundamentals/forecast_report.csv"
        fc_dst = "fundamentals/earnings_forecast.csv"
        p = PATHS.get("data", Path()) / fc_src
        if p.exists():
            pp.add_file(fc_src, target_rel_path=fc_dst)

        # 审计报告
        p = PATHS.get("audit", Path()) / "data_freshness_report.json"
        if p.exists():
            pp.add_file("audit/data_freshness_report.json")

        pp.set_freshness("ok", max_delay_seconds=0)
        pid = pp.finalize()
        _sync_to_codex_root(pid)
        print(f"✅ Published: {pid}")
    except Exception as e:
        pp.abort()
        print(f"❌ Failed: {e}")


def cmd_publish_intraday_alerts():
    """hermes package:publish-intraday-alerts"""
    pp = PackagePublisher("intraday_alerts")
    try:
        intraday_dir = PATHS["intraday"]
        for f in ["events_log.jsonl", "intraday_digest.json",
                   "codex_escalations.jsonl", "risk_state.json",
                   "live_snapshot_priority.csv", "wechat_push_log.jsonl"]:
            p = intraday_dir / f
            if p.exists():
                pp.add_file(f"intraday/{f}")
        # 审计
        audit_dir = PATHS["audit"]
        for f in ["data_freshness_report.json", "fetch_log.jsonl"]:
            p = audit_dir / f
            if p.exists():
                pp.add_file(f"audit/{f}")
        pp.set_freshness("ok", max_delay_seconds=30)
        pid = pp.finalize()
        _sync_to_codex_root(pid)
        print(f"✅ Published: {pid}")
    except Exception as e:
        pp.abort()
        print(f"❌ Failed: {e}")


def cmd_publish_market():
    """hermes package:publish-market — 发布行情快照"""
    pp = PackagePublisher("market_snapshot")
    try:
        for f in ["market/live_snapshot.csv", "market/pool.csv"]:
            p = PATHS.get("data", Path()) / f
            if p.exists():
                pp.add_file(f)
        pp.set_freshness("ok", max_delay_seconds=30)
        pid = pp.finalize()
        _sync_to_codex_root(pid)
        print(f"✅ Published: {pid}")
    except Exception as e:
        pp.abort()
        print(f"❌ Failed: {e}")


def cmd_publish_all():
    """hermes package:publish-all — 发布所有待发数据"""
    cmd_publish_preopen()
    cmd_publish_market()
    cmd_publish_intraday_alerts()


if __name__ == "__main__":
    import sys
    cmds = {
        "publish-preopen": cmd_publish_preopen,
        "publish-market": cmd_publish_market,
        "publish-intraday-alerts": cmd_publish_intraday_alerts,
        "publish-all": cmd_publish_all,
    }
    if len(sys.argv) > 1 and sys.argv[1] in cmds:
        cmds[sys.argv[1]]()
    else:
        print("Usage: python package_publisher.py <command>")
        print(f"Commands: {', '.join(cmds.keys())}")
