"""HealthTracker — 数据源健康追踪

Tracks fetch attempts per source with rolling-window success rate computation.
Auto-transitions source status based on health thresholds.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from factor_lab.data_source.spec import DataSourceStatus
from factor_lab.data_source.registry import DataRegistry


CST = timezone(timedelta(hours=8))
REGISTRY_ROOT = Path("/mnt/d/HermesData/data_source_registry")

# Health thresholds
ACTIVE_THRESHOLD = 80     # success_rate >= 80 -> active
DEGRADED_THRESHOLD = 50   # success_rate >= 50 -> degraded; else inactive
ROLLING_WINDOW = 100       # last N calls for computation


@dataclass
class HealthReport:
    """数据源健康报告"""
    source_id: str
    status: str
    success_rate: float
    total_calls: int
    error_count: int
    last_check: str
    avg_latency_ms: float = 0.0
    recent_errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _health_history_path(source_id: str) -> Path:
    return REGISTRY_ROOT / source_id / "health_history.jsonl"


class HealthTracker:
    """健康追踪器 — 记录调用并计算健康度"""

    def __init__(self, registry: Optional[DataRegistry] = None):
        self.registry = registry or DataRegistry()

    def record_call(self, source_id: str, success: bool, latency_ms: float = 0.0,
                    error: str = ""):
        """记录一次数据源调用

        Args:
            source_id: 数据源ID
            success: 是否成功
            latency_ms: 延迟（毫秒）
            error: 错误信息（失败时）
        """
        record = {
            "timestamp": datetime.now(CST).isoformat(),
            "source_id": source_id,
            "success": success,
            "latency_ms": round(latency_ms, 1),
            "error": (error or "")[:200],
        }

        path = _health_history_path(source_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def check_health(self, source_id: str) -> HealthReport:
        """计算数据源当前健康状态

        分析最近 ROLLING_WINDOW 次调用记录，返回健康报告。
        同时触发 auto_update_status 更新注册表状态。
        """
        path = _health_history_path(source_id)
        records = self._load_records(path)

        # Take rolling window
        window = records[-ROLLING_WINDOW:] if len(records) > ROLLING_WINDOW else records

        total = len(window)
        if total == 0:
            report = HealthReport(
                source_id=source_id,
                status=DataSourceStatus.UNCHECKED.value,
                success_rate=100.0,
                total_calls=0,
                error_count=0,
                last_check=datetime.now(CST).isoformat(),
            )
            self._sync_status(source_id, report)
            return report

        success_count = sum(1 for r in window if r.get("success", False))
        error_count = total - success_count
        success_rate = round((success_count / total) * 100, 1)
        avg_latency = round(
            sum(r.get("latency_ms", 0) for r in window if r.get("latency_ms", 0) > 0) / max(success_count, 1),
            1,
        )

        # Determine status
        if success_rate >= ACTIVE_THRESHOLD:
            status = DataSourceStatus.ACTIVE.value
        elif success_rate >= DEGRADED_THRESHOLD:
            status = DataSourceStatus.DEGRADED.value
        else:
            status = DataSourceStatus.INACTIVE.value

        # Recent errors (last 5)
        recent_errors = [
            r.get("error", "") for r in reversed(window[-10:])
            if not r.get("success", False) and r.get("error", "")
        ][:5]

        report = HealthReport(
            source_id=source_id,
            status=status,
            success_rate=success_rate,
            total_calls=total,
            error_count=error_count,
            last_check=datetime.now(CST).isoformat(),
            avg_latency_ms=avg_latency,
            recent_errors=recent_errors,
        )

        self._sync_status(source_id, report)
        return report

    def auto_update_status(self, source_id: str) -> str:
        """根据健康记录自动更新状态，返回新状态"""
        report = self.check_health(source_id)
        return report.status

    # ---- Internal ----

    def _load_records(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        records = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return records

    def _sync_status(self, source_id: str, report: HealthReport):
        """将健康推断的状态更新到注册表"""
        spec = self.registry.get_source(source_id)
        if spec is None:
            return

        spec.status = report.status
        spec.health = {
            "last_check": report.last_check,
            "success_rate": report.success_rate,
            "total_calls": report.total_calls,
            "error_count": report.error_count,
            "avg_latency_ms": report.avg_latency_ms,
        }
        spec.updated_at = datetime.now(CST).isoformat()

        # Write updated spec directly (not via registry.update_status)
        # to avoid re-reading a stale copy after the update
        from factor_lab.data_source.registry import _spec_path
        _spec_path(source_id).write_text(
            json.dumps(spec.to_dict(), indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        # Also update the registry index status
        from factor_lab.data_source.registry import _load_index, _save_index
        index = _load_index()
        for entry in index:
            if entry["source_id"] == source_id:
                entry["status"] = report.status
                break
        _save_index(index)
