"""审计日志服务 — 记录 API 调用和重要操作。"""

from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from pydantic import BaseModel

CST = timezone(timedelta(hours=8))


class AuditEvent(BaseModel):
    """单条审计事件。"""
    event_id: str
    event_type: str  # api_call / job_run / backtest / portfolio / config_change / login / error
    actor: str = "system"
    resource: str = ""  # 操作的资源，例如 /api/jobs/run
    action: str = ""    # 操作类型，例如 create / update / delete / execute
    detail: dict = {}
    outcome: str = "success"  # success / failure / pending
    ip_address: str = ""
    user_agent: str = ""
    run_id: str = ""
    timestamp: str = ""


class AuditService:
    """内存审计日志存储，支持事件记录和查询。"""

    def __init__(self, max_events: int = 10000):
        self._events: list[AuditEvent] = []
        self._max_events = max_events

    def record(
        self,
        event_type: str,
        actor: str = "system",
        resource: str = "",
        action: str = "",
        detail: Optional[dict] = None,
        outcome: str = "success",
        ip_address: str = "",
        user_agent: str = "",
        run_id: str = "",
    ) -> AuditEvent:
        """记录一条审计事件。"""
        import uuid
        event = AuditEvent(
            event_id=f"evt_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
            event_type=event_type,
            actor=actor,
            resource=resource,
            action=action,
            detail=detail or {},
            outcome=outcome,
            ip_address=ip_address,
            user_agent=user_agent,
            run_id=run_id,
            timestamp=datetime.now(CST).isoformat(),
        )
        self._events.append(event)
        # 限制内存占用
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]
        return event

    def list(
        self,
        event_type: Optional[str] = None,
        outcome: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AuditEvent], int]:
        """查询审计事件。返回 (过滤后事件列表, 总数)。"""
        events = list(self._events)
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if outcome:
            events = [e for e in events if e.outcome == outcome]
        events.sort(key=lambda e: e.timestamp, reverse=True)
        total = len(events)
        page = events[offset : offset + limit]
        return page, total

    def get_by_run_id(self, run_id: str) -> list[AuditEvent]:
        """通过 run_id 查询相关审计事件。"""
        return [e for e in self._events if e.run_id == run_id]

    def get_stats(self) -> dict:
        """审计统计摘要。"""
        total = len(self._events)
        by_type: dict[str, int] = {}
        by_outcome: dict[str, int] = {}
        for e in self._events:
            by_type[e.event_type] = by_type.get(e.event_type, 0) + 1
            by_outcome[e.outcome] = by_outcome.get(e.outcome, 0) + 1
        return {
            "total_events": total,
            "by_type": by_type,
            "by_outcome": by_outcome,
        }


# 全局单例
audit_service = AuditService()
