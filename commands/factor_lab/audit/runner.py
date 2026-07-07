"""Anti-Cheat Audit Runner — 统一调度 4 道闸门

用法:
  from factor_lab.audit import run_all_gates

  report = run_all_gates(version="Vx.y")
  print(report.summary_text())
  if not report.passed:
      print("❌ 审计未通过，请修复以上问题")
      exit(1)
"""

from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .base import AuditFinding, AuditReport, Severity

CST = timezone(timedelta(hours=8))
BASE = Path(os.environ.get("RESEARCH_ASSISTANT_ROOT",
                           "/home/ly/.hermes/research-assistant"))
AUDIT_REPORTS_DIR = BASE / "agent_tasks" / "audit_reports"


def run_all_gates(
    version: str = "",
    skip_gates: Optional[list[str]] = None,
    plan_path: Optional[str] = None,
) -> AuditReport:
    """运行全部 4 道闸门或指定子集

    Args:
        version: 当前版本号
        skip_gates: 跳过指定的闸门 (如 ["gate4"])
        plan_path: 计划文件的显式路径
    """
    skip = set(skip_gates or [])
    report = AuditReport(version=version)

    # Gate 1: 需求→代码追溯
    if "gate1" not in skip:
        from .gate1_traceability import run_gate1
        run_gate1(report, plan_path=plan_path)

    # Gate 2: 虚假实现检测
    if "gate2" not in skip:
        from .gate2_stub_detect import run_gate2
        run_gate2(report)

    # Gate 3: 测试覆盖检查
    if "gate3" not in skip:
        from .gate3_test_coverage import run_gate3
        run_gate3(report)

    # Gate 4: 独立需求审计
    if "gate4" not in skip:
        from .gate4_independent_review import run_gate4
        run_gate4(report)

    # 最终判定
    report.finished_at = datetime.now(CST).isoformat()

    return report


def save_report(report: AuditReport) -> str:
    """保存审计报告到文件"""
    AUDIT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    ver = report.version or "unknown"
    path = AUDIT_REPORTS_DIR / f"anti_cheat_{ver}_{ts}.json"
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    # also update latest
    (AUDIT_REPORTS_DIR / "anti_cheat_latest.json").write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    return str(path)


def cmd_main(args: list[str] = None) -> int:
    """CLI 入口"""
    import argparse
    p = argparse.ArgumentParser(description="Anti-Cheat Audit: 检测 LLM Agent 偷工减料")
    p.add_argument("--version", default="", help="版本号")
    p.add_argument("--skip", nargs="*", default=[],
                   choices=["gate1", "gate2", "gate3", "gate4"],
                   help="跳过指定的闸门")
    p.add_argument("--plan", default="", help="计划文件路径")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--save", action="store_true", default=True, help="保存报告到文件")

    opts = p.parse_args(args or [])

    report = run_all_gates(
        version=opts.version,
        skip_gates=opts.skip if opts.skip else None,
        plan_path=opts.plan or None,
    )

    if opts.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(report.summary_text())

    if opts.save:
        path = save_report(report)
        print(f"\n报告已保存: {path}")

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(cmd_main())
