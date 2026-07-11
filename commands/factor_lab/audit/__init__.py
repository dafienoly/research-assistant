"""Anti-Cheat Audit — 4 道闸门检测 LLM Agent 偷工减料行为

检测范围:
  gate1 — 需求→代码追溯矩阵: 计划中的文件/函数是否真实存在
  gate2 — 虚假实现检测: pass/硬编码/return 常量 等 stub 模式
  gate3 — 测试覆盖检查: 新代码是否有对应新测试
  gate4 — 独立需求审计: 第三方 Agent 审查需求 vs 实现

用法:
  from factor_lab.audit.runner import run_all_gates
  report = run_all_gates(version="Vx.y")
  print(report.summary_text())
"""

from .base import AuditFinding, AuditReport, Severity
from .runner import run_all_gates, run_code_audit, cmd_main
from .coordinator import AuditCoordinator, AuditRequest

__all__ = [
    "AuditFinding", "AuditReport", "Severity",
    "run_all_gates", "run_code_audit", "cmd_main", "AuditCoordinator", "AuditRequest",
]
