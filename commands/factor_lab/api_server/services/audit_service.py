"""Persistent append-only operational event ledger."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

CST = timezone(timedelta(hours=8))


class AuditEvent(BaseModel):
    event_id: str
    event_type: str
    actor: str = "system"
    resource: str = ""
    action: str = ""
    detail: dict = Field(default_factory=dict)
    outcome: str = "success"
    ip_address: str = ""
    user_agent: str = ""
    run_id: str = ""
    timestamp: str = ""
    prev_hash: str = ""
    event_hash: str = ""


class AuditService:
    """Thread-safe JSONL ledger with a verifiable hash chain."""

    def __init__(self, max_events: int = 10000, path: Path | None = None):
        default = Path.home() / ".hermes/state/research-assistant/ops-audit/events.jsonl"
        self._path = path or Path(os.environ.get("HERMES_OPS_AUDIT_FILE", default))
        self._events: list[AuditEvent] = []
        self._max_events = max_events
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()[-self._max_events:]
        except OSError:
            return
        for line in lines:
            try:
                self._events.append(AuditEvent.model_validate_json(line))
            except Exception:
                continue

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
        with self._lock:
            previous = self._events[-1].event_hash if self._events else ""
            payload = {
                "event_id": f"evt_{datetime.now(CST).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
                "event_type": event_type,
                "actor": actor,
                "resource": resource,
                "action": action,
                "detail": detail or {},
                "outcome": outcome,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "run_id": run_id,
                "timestamp": datetime.now(CST).isoformat(),
                "prev_hash": previous,
            }
            canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            payload["event_hash"] = hashlib.sha256((previous + canonical).encode("utf-8")).hexdigest()
            event = AuditEvent(**payload)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as stream:
                stream.write(event.model_dump_json() + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._events.append(event)
            self._events = self._events[-self._max_events:]
            return event

    def list(self, event_type: Optional[str] = None, outcome: Optional[str] = None,
             limit: int = 100, offset: int = 0) -> tuple[list[AuditEvent], int]:
        with self._lock:
            events = list(self._events)
        if event_type:
            events = [event for event in events if event.event_type == event_type]
        if outcome:
            events = [event for event in events if event.outcome == outcome]
        events.sort(key=lambda event: event.timestamp, reverse=True)
        return events[offset:offset + limit], len(events)

    def get_by_run_id(self, run_id: str) -> list[AuditEvent]:
        with self._lock:
            return [event for event in self._events if event.run_id == run_id]

    def get_stats(self) -> dict:
        with self._lock:
            events = list(self._events)
        by_type: dict[str, int] = {}
        by_outcome: dict[str, int] = {}
        for event in events:
            by_type[event.event_type] = by_type.get(event.event_type, 0) + 1
            by_outcome[event.outcome] = by_outcome.get(event.outcome, 0) + 1
        return {"total_events": len(events), "by_type": by_type, "by_outcome": by_outcome}


audit_service = AuditService()
