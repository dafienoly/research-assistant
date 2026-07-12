"""Release-only source audit.

旧 Gate/LLM/GitNexus/pytest 编排已退役。只有显式 major_version 才会运行
source_audit，且只读取源码变更；普通提交和推送返回 SKIPPED。
"""

from .base import AuditFinding, AuditReport, Severity
from .runner import run_all_gates, run_code_audit, cmd_main
from .coordinator import AuditCoordinator, AuditRequest
from .source_audit import run_source_audit

__all__ = [
    "AuditFinding", "AuditReport", "Severity",
    "run_all_gates", "run_code_audit", "cmd_main", "AuditCoordinator", "AuditRequest", "run_source_audit",
]
