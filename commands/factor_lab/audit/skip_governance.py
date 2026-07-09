"""
Skip Governance — 记录和管理 Gate 跳过行为。

所有 skip 必须记录：
  - skip 的 Gate
  - skip 原因
  - skip 发起者（auto/manual/user）
  - skip 时间
  - skip 是否允许
  - skip 过期时间
  - skip 风险等级

禁止静默跳过。
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from .base import AuditFinding, AuditReport


CST = timezone(timedelta(hours=8))


@dataclass
class SkipRecord:
    gate: str
    reason: str
    initiator: str = "auto"  # "auto" | "manual" | "user"
    timestamp: str = ""
    allowed: bool = True
    expires_at: Optional[str] = None
    risk: str = "LOW"

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(CST).isoformat()

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at)
            return datetime.now(CST) > exp
        except (ValueError, TypeError):
            return False

    def to_dict(self) -> dict:
        return {
            "gate": self.gate,
            "reason": self.reason,
            "initiator": self.initiator,
            "timestamp": self.timestamp,
            "allowed": self.allowed,
            "expires_at": self.expires_at or "",
            "risk": self.risk,
        }


SKIP_REGISTRY: list[SkipRecord] = []


def record_skip(
    gate: str,
    reason: str,
    initiator: str = "auto",
    allowed: bool = True,
    expires_at: Optional[str] = None,
    risk: str = "LOW",
) -> SkipRecord:
    """记录一次 Gate 跳过。"""
    r = SkipRecord(
        gate=gate,
        reason=reason,
        initiator=initiator,
        allowed=allowed,
        expires_at=expires_at,
        risk=risk,
    )
    SKIP_REGISTRY.append(r)
    return r


def validate_skip(gate: str, risk: str = "LOW") -> tuple[bool, str]:
    """检查是否可以跳过指定 Gate。

    Returns:
        (allowed, reason) — allowed=False 时禁止跳过
    """
    # 高风险下不允许跳过 Gate 5
    if risk == "HIGH" and gate == "gate5":
        return False, "高风险模块不允许跳过语义审查 (Gate 5)"

    # 高风险下不允许跳过 Gate 4
    if risk == "HIGH" and gate == "gate4":
        return False, "高风险模块不允许跳过运行时校验 (Gate 4)"

    return True, ""


def findings_from_skips() -> list[AuditFinding]:
    """将 SKIP_REGISTRY 转换为 AuditFinding 列表。"""
    findings: list[AuditFinding] = []
    for s in SKIP_REGISTRY:
        cat = "UNAUTHORIZED_SKIP"
        sev = "WARN"
        if not s.allowed:
            cat = "UNAUTHORIZED_SKIP"
            sev = "FAIL"
        elif s.is_expired():
            cat = "SKIP_EXPIRED"
            sev = "WARN"
        elif not s.reason:
            cat = "SKIP_REASON_MISSING"
            sev = "WARN"
        elif s.risk == "HIGH" and s.gate in ("gate4", "gate5"):
            cat = "HIGH_RISK_GATE_SKIPPED"
            sev = "FAIL"
        else:
            cat = "SKIP_OK"
            sev = "INFO"

        findings.append(AuditFinding(
            gate="skip_governance",
            severity=sev,
            category=cat,
            file="",
            message=f"Gate {s.gate} 被跳过: {s.reason or '(无原因)'}",
            detail=f"发起者={s.initiator}, 风险={s.risk}, 时间={s.timestamp}",
        ))
    return findings


def clear_registry():
    """重置（用于测试）。"""
    SKIP_REGISTRY.clear()
