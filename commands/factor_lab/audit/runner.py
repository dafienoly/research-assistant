"""Anti-Cheat Audit Runner — 统一调度 5 道闸门

升级特性:
  - 风险等级自动选择 gate (risk_classifier)
  - skip 治理 (skip_governance)
  - 增强报告输出 (report_writer: md/json/jsonl/manifest)
  - 双映射交叉验证 (auditor_mapping)
  - 运行时证据 (Gate 4 runtime smoke)
  - LLM 语义审查 + prompt injection 防护 (Gate 5)
"""

from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .base import AuditReport
from .risk_classifier import classify_risk, required_gates
from .skip_governance import record_skip, validate_skip, findings_from_skips, clear_registry
from .report_writer import write_report

CST = timezone(timedelta(hours=8))
BASE = Path(os.environ.get("RESEARCH_ASSISTANT_ROOT",
                           "/home/ly/.hermes/research-assistant"))
AUDIT_REPORTS_DIR = BASE / "agent_tasks" / "audit_reports"


def run_all_gates(
    version: str = "",
    skip_gates: Optional[list[str]] = None,
    plan_path: Optional[str] = None,
    enable_gate5: bool = False,
    risk: str = "auto",
    output_dir: Optional[str] = None,
) -> AuditReport:
    """运行全部 5 道闸门，基于风险等级自动选择。

    Args:
        version: 版本号
        skip_gates: 跳过指定闸门
        plan_path: 计划文件路径
        enable_gate5: 启用 Gate 5 (向后兼容)
        risk: "auto" | "LOW" | "MEDIUM" | "HIGH" — 风险等级
        output_dir: 报告输出目录
    """
    skip = set(skip_gates or [])
    report = AuditReport(version=version)

    # 1. 获取变更文件并判断风险等级
    from .git_utils import get_all_changed_files
    changed_files = get_all_changed_files(include_untracked=True)

    # 获取 diff 文本用于风险分类
    diff_text = ""
    import subprocess
    for cmd in [["git", "diff"], ["git", "diff", "--cached"],
                ["git", "diff", "HEAD~3", "HEAD"]]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=str(BASE))
            if r.stdout.strip():
                diff_text = r.stdout
                break
        except Exception:
            pass

    current_risk = risk if risk != "auto" else classify_risk(changed_files, diff_text)
    report.extras["risk"] = current_risk

    # 清空 skip 注册表（防止跨次累计）
    clear_registry()

    # 2. 确定要跑的 gate
    if enable_gate5:
        # 向后兼容: enable_gate5 时始终包含 gate5
        gates_to_run = required_gates(current_risk)
        if "gate5" not in gates_to_run:
            gates_to_run.append("gate5")
    else:
        gates_to_run = required_gates(current_risk)

    # 3. 应用 skip 并记录
    skip_info = []
    final_gates = []
    for g in gates_to_run:
        if g in skip:
            # 检查 skip 是否允许
            allowed, reason = validate_skip(g, current_risk)
            record_skip(gate=g, reason=reason or "用户跳过", initiator="manual",
                        allowed=allowed, risk=current_risk)
            skip_info.append({"gate": g, "reason": reason or "用户跳过", "allowed": allowed})
            if not allowed:
                # 不允许跳过，仍然跑
                final_gates.append(g)
        else:
            final_gates.append(g)

    report.extras["skip_info"] = skip_info
    report.extras["risk"] = current_risk
    report.extras["gates_requested"] = gates_to_run

    # ── 4. 执行各 Gate ────────────────────────────────────────
    runtime_log = ""
    pytest_log = ""

    # Gate 1
    if "gate1" in final_gates:
        try:
            from .gate1_traceability import run_gate1
            run_gate1(report, plan_path=plan_path)
        except Exception as e:
            report.add(_gate_error("gate1", e))

    # Gate 2
    if "gate2" in final_gates:
        try:
            from .gate2_stub_detect import run_gate2
            run_gate2(report)
        except Exception as e:
            report.add(_gate_error("gate2", e))

    # Gate 3
    if "gate3" in final_gates:
        try:
            from .gate3_test_coverage import run_gate3
            run_gate3(report)
        except Exception as e:
            report.add(_gate_error("gate3", e))

    # Gate 4 (Runtime Smoke)
    if "gate4" in final_gates:
        try:
            from .gate4_runtime_smoke import run_gate4
            run_gate4(report)
        except Exception as e:
            report.add(_gate_error("gate4", e))

    # Gate 5 (Semantic Audit)
    if "gate5" in final_gates:
        try:
            from .gate5_llm_review import run_gate5
            run_gate5(report, risk=current_risk)
        except Exception as e:
            report.add(_gate_error("gate5", e))

    # 5. Skip 治理发现
    skip_findings = findings_from_skips()
    report.extend(skip_findings)

    # 6. 最终判定
    report.finished_at = datetime.now(CST).isoformat()

    # 7. 报告输出
    try:
        write_report(report, extra=report.extras, output_dir=output_dir,
                     runtime_log=runtime_log, pytest_log=pytest_log)
    except Exception as e:
        pass  # 报告输出失败不阻断审计

    return report


def _gate_error(gate: str, exc: Exception):
    from .base import AuditFinding
    return AuditFinding(
        gate=gate, severity="FAIL", category="GATE_ERROR",
        file="", message=f"Gate 执行异常: {exc}",
        detail=str(exc)[:300],
    )


def save_report(report: AuditReport) -> str:
    """保存审计报告到文件（兼容旧接口）。"""
    AUDIT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    ver = report.version or "unknown"
    path = AUDIT_REPORTS_DIR / f"anti_cheat_{ver}_{ts}.json"
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    latest = AUDIT_REPORTS_DIR / "anti_cheat_latest.json"
    latest.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    return str(path)


def cmd_main(args: list[str] = None) -> int:
    """CLI 入口"""
    import argparse
    p = argparse.ArgumentParser(description="Anti-Cheat Audit: 5 道闸门代码审计")
    p.add_argument("--version", default="", help="版本号")
    p.add_argument("--skip", nargs="*", default=[],
                   choices=["gate1", "gate2", "gate3", "gate4", "gate5"],
                   help="跳过指定的闸门")
    p.add_argument("--plan", default="", help="计划文件路径")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.add_argument("--save", action="store_true", default=True, help="保存报告到文件")
    p.add_argument("--enable-gate5", action="store_true",
                   help="启用 Gate 5 (语义审查)")
    p.add_argument("--risk", default="auto",
                   choices=["auto", "LOW", "MEDIUM", "HIGH"],
                   help="风险等级 (auto=根据 diff 自动判断)")
    p.add_argument("--output", default="",
                   help="报告输出目录 (默认: /mnt/d/HermesReports/code_audit/)")

    opts = p.parse_args(args or [])

    report = run_all_gates(
        version=opts.version,
        skip_gates=opts.skip if opts.skip else None,
        plan_path=opts.plan or None,
        enable_gate5=opts.enable_gate5,
        risk=opts.risk,
        output_dir=opts.output or None,
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
