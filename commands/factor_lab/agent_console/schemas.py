"""Agent Console Schema — 统一事件类型"""
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

CST = timezone(timedelta(hours=8))

EVENT_TYPES = {"answer_delta", "diagnostic", "error", "status", "done"}


@dataclass
class AgentEvent:
    type: str  # answer_delta / diagnostic / error / status / done
    session_id: str
    data: str = ""         # answer_delta: 回答正文；diagnostic: 诊断文本
    status: str = ""       # running / completed / cancelled / failed
    agent: str = ""        # hermes / claude
    prompt: str = ""
    timestamp: str = ""

    def to_sse(self) -> str:
        import json
        payload = {"type": self.type, "session_id": self.session_id,
                   "data": self.data[:2000], "status": self.status,
                   "agent": self.agent, "timestamp": self.timestamp}
        return f"event: {self.type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def to_dict(self):
        return {"type": self.type, "session_id": self.session_id,
                "data": self.data, "status": self.status,
                "agent": self.agent, "prompt": self.prompt,
                "timestamp": self.timestamp or datetime.now(CST).isoformat()}


@dataclass
class SessionState:
    session_id: str
    agent: str = ""
    prompt: str = ""
    status: str = "pending"  # pending / running / completed / cancelled / failed
    created_at: str = ""
    answer_md: str = ""
    diagnostics: list = field(default_factory=list)
