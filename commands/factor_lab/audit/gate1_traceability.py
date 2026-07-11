"""Gate 1 — 需求→代码追溯 + 调用链追溯

继承原有功能（检查文件/函数是否存在），新增：
  4. 检查新增模块是否接入对应 registry
  5. 检查新增 CLI command 是否挂到 CommandRegistry
  6. 检查新增 Alpha 是否挂到 AlphaRegistry
  7. 检查新增 DataProvider 是否挂到 DataProviderRegistry
  8. 检查新增 Gate 是否挂到 GateEngine
"""

from __future__ import annotations
import os, re, subprocess, json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from .base import AuditFinding, AuditReport, Severity
from .git_utils import get_all_changed_files, BASE, COMMANDS, GIT_DIR

# ─── Plan 解析 ────────────────────────────────────────────────
TASK_HEADER_RE = re.compile(r"^###\s+Task\s+\d+", re.MULTILINE | re.IGNORECASE)
FILE_CREATE_RE = re.compile(r"- \*\*Create:\*\*\s+`([^`]+)`", re.IGNORECASE)
FILE_MODIFY_RE = re.compile(r"- \*\*Modify:\*\*\s+`([^`]+)`", re.IGNORECASE)
FUNC_DEF_RE = re.compile(r"^def\s+(test_)?(\w+)", re.MULTILINE)
CLASS_DEF_RE = re.compile(r"^class\s+(\w+)", re.MULTILINE)
ENDPOINT_RE = re.compile(r"@app\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]")

STUB_SUSPECT_NAMES = re.compile(
    r"^(compute_?|calculate_?|fetch_?|load_?|parse_?|validate_?|"
    r"transform_?|build_?|generate_?|resolve_?|process_?|score_?|rank_?|"
    r"predict_?|evaluate_?|backtest_?|run_?|sync_?|migrate_?|convert_?)",
    re.IGNORECASE,
)

# ── Registry 检测模式 ─────────────────────────────────────────
REGISTRY_PATTERNS = {
    "CommandRegistry": r"CommandRegistry\(\)|\.register\(.*command|hermes_cli\.register\(|commands\[|COMMAND_REGISTRY",
    "AlphaRegistry": r"AlphaRegistry|alpha_registry\.register|register_alpha|ALPHA_REGISTRY",
    "DataProviderRegistry": r"DataProviderRegistry|data_provider_registry|register_provider|DataProvider",
    "GateEngine": r"GateEngine|gate_engine\.register|GATE_ENGINE",
    "ReportBuilder": r"ReportBuilder|report_builder\.register|REPORT_BUILDER|ReportManifest",
}


@dataclass
class PlanTask:
    title: str
    expected_creates: list[str] = field(default_factory=list)
    expected_modifies: list[str] = field(default_factory=list)


def _find_plan_files() -> list[Path]:
    plans_dir = BASE / ".hermes" / "plans"
    if not plans_dir.is_dir():
        return []
    candidates = sorted(plans_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[:3]


def _parse_plan_md(text: str) -> list[PlanTask]:
    tasks: list[PlanTask] = []
    current: Optional[PlanTask] = None
    for line in text.splitlines():
        m = re.match(r"^###\s+(Task\s+\d+.*)", line, re.IGNORECASE)
        if m:
            if current:
                tasks.append(current)
            current = PlanTask(title=m.group(1).strip())
            continue
        if current is None:
            continue
        m = re.search(r"- \*\*Create:\*\*\s+`([^`]+)`", line, re.IGNORECASE)
        if m:
            current.expected_creates.append(m.group(1))
            continue
        m = re.search(r"- \*\*Modify:\*\*\s+`([^`]+)`", line, re.IGNORECASE)
        if m:
            current.expected_modifies.append(m.group(1))
            continue
    if current:
        tasks.append(current)
    return tasks


def _extract_functions_from_code(file_path: str) -> list[str]:
    full_path = Path(file_path)
    if not full_path.is_file():
        return []
    try:
        text = full_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    funcs = [m.group(2) for m in FUNC_DEF_RE.finditer(text) if m.group(2)]
    classes = [m.group(1) for m in CLASS_DEF_RE.finditer(text)]
    return list(set(funcs + classes))


# ─── 新增: Registry 检查 ─────────────────────────────────────

def _check_registration(file_paths: list[str]) -> list[AuditFinding]:
    """检查新增文件是否应该在 registry 中注册但未注册。
    
    只在文件是**新增**（非修改）且文件名/内容暗示需要注册时检查。
    """
    findings: list[AuditFinding] = []
    # 检查哪些文件是新增的（不在 git 历史中）
    import subprocess
    new_files = set()
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=A"],
            capture_output=True, text=True, timeout=5, cwd=str(BASE),
        )
        if r.returncode == 0:
            new_files = set(r.stdout.strip().splitlines())
    except Exception:
        pass
    # 也包含未跟踪的文件
    try:
        r = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=5, cwd=str(BASE),
        )
        if r.returncode == 0:
            new_files.update(r.stdout.strip().splitlines())
    except Exception:
        pass

    for fp in file_paths:
        if not fp.endswith(".py"):
            continue
        if "/tests/" in fp or fp.startswith("tests/"):
            continue
        # 只检查新增文件或名明确涉及 registry 的文件
        is_new = fp in new_files
        candidates = [BASE / fp, COMMANDS / fp, Path(fp)]
        full = None
        for c in candidates:
            if c.is_file():
                full = c
                break
        if not full:
            continue
        try:
            src = full.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        # 根据文件内容判断是否需要注册
        needs_registry = False
        registry_type = ""
        if is_new and re.search(r"class\s+\w+Command|class\s+\w+CLI|CommandRegistry", src):
            needs_registry = True
            registry_type = "CommandRegistry"
        elif is_new and re.search(r"class\s+\w+Alpha|AlphaRegistry|def\s+compute_alpha", src):
            needs_registry = True
            registry_type = "AlphaRegistry"
        elif is_new and re.search(r"class\s+\w+Provider|ProviderRegistry|class\s+\w+DataSource", src):
            needs_registry = True
            registry_type = "DataProviderRegistry"
        elif is_new and re.search(r"class\s+\w+Gate|GateEngine", src):
            needs_registry = True
            registry_type = "GateEngine"
        elif not is_new:
            # 修改文件只检查 registry 模式新增
            reg_pat = REGISTRY_PATTERNS.get("CommandRegistry", "")
            if reg_pat and re.search(r"@app\.|router\.|route\(", src):
                needs_registry = True
                registry_type = "CommandRegistry"

        if needs_registry:
            pat = REGISTRY_PATTERNS.get(registry_type, registry_type)
            if not re.search(pat, src):
                findings.append(AuditFinding(
                    gate="gate1", severity="WARN", category="SYMBOL_NOT_REGISTERED",
                    file=fp,
                    message=f"新增 {registry_type} 组件但未发现注册代码: {Path(fp).name}",
                ))

    return findings


def _check_registry_for_file(fp: str, registry_name: str, src: str,
                              findings: list[AuditFinding]):
    """如果文件是新增的且包含某类组件，检查是否引用了对应的 registry。"""
    pat = REGISTRY_PATTERNS.get(registry_name, registry_name)
    if not re.search(pat, src):
        findings.append(AuditFinding(
            gate="gate1", severity="WARN", category="SYMBOL_NOT_REGISTERED",
            file=fp, message=f"疑似 {registry_name} 组件但未发现注册代码: {Path(fp).name}",
            detail=f"该文件看起来应该注册到 {registry_name}，但源码中未找到注册调用",
        ))


# ─── 核心检测 ─────────────────────────────────────────────────

def _check_files_exist(files: list[str], rel_root: str = "") -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for f in files:
        full = Path(rel_root, f) if rel_root else Path(f)
        checked = str(full)
        if not full.is_absolute():
            candidates = [BASE / f, COMMANDS / f, BASE / f.replace("commands/", "", 1)]
            checked = str([str(c) for c in candidates])
            exists = any(c.is_file() for c in candidates)
        else:
            exists = full.is_file()
        findings.append(AuditFinding(
            gate="gate1",
            severity="INFO" if exists else "FAIL",
            category="FILE_EXISTS" if exists else "MISSING_FILE",
            file=f, message=f"{'文件已存在' if exists else '文件不存在'}: {f}",
            detail="" if exists else f"检查路径: {checked}",
        ))
    return findings


# ─── 主入口 ───────────────────────────────────────────────────

def run_gate1(report: AuditReport, plan_path: Optional[str] = None) -> AuditReport:
    report.gates_run.append("gate1")

    # 1. 找 plan 文件
    plans: list[Path] = []
    if plan_path:
        pp = Path(plan_path)
        if pp.is_file():
            plans = [pp]
    if not plans:
        plans = _find_plan_files()

    if not plans:
        report.add(AuditFinding(
            gate="gate1", severity="WARN", category="NO_PLAN",
            file="", message="未找到计划文件，跳过需求追溯",
        ))
        diff_files = get_all_changed_files()
        if diff_files:
            report.add(AuditFinding(
                gate="gate1", severity="INFO", category="CHANGED_FILES",
                file="", message=f"发现 {len(diff_files)} 个变更文件",
                detail="\n".join(diff_files[:20]),
            ))
        # 降级模式下仍检查 registry
        reg_findings = _check_registration(diff_files)
        report.extend(reg_findings)
        return report

    # 2. 解析计划
    tasks: list[PlanTask] = []
    for pf in plans:
        tasks.extend(_parse_plan_md(pf.read_text(encoding="utf-8", errors="replace")))

    if not tasks:
        report.add(AuditFinding(
            gate="gate1", severity="WARN", category="NO_TASKS",
            file="", message="Plan 文件中未解析到 Task 定义（格式: ### Task N）",
        ))
        diff_files = get_all_changed_files()
        if diff_files:
            report.add(AuditFinding(
                gate="gate1", severity="INFO", category="CHANGED_FILES",
                file="", message=f"发现 {len(diff_files)} 个变更文件（无 Task 解析）",
                detail="\n".join(diff_files[:20]),
            ))
        reg_findings = _check_registration(diff_files)
        report.extend(reg_findings)
        return report

    report.add(AuditFinding(
        gate="gate1", severity="INFO", category="PLAN_FOUND",
        file=str(plans[0]), message=f"解析到 {len(tasks)} 个 Task",
        detail="\n".join(f"  {t.title}" for t in tasks),
    ))

    # 3. 逐 Task 检查文件
    all_creates = []
    all_modifies = []
    for t in tasks:
        all_creates.extend(t.expected_creates)
        all_modifies.extend(t.expected_modifies)
    all_creates = list(set(all_creates))
    all_modifies = list(set(all_modifies))

    create_findings = _check_files_exist(all_creates, str(BASE))
    report.extend(create_findings)
    modify_findings = _check_files_exist(all_modifies, str(BASE))
    report.extend(modify_findings)

    # 4. 扫描 git diff 中的新增函数
    diff_files = get_all_changed_files()
    if diff_files:
        report.add(AuditFinding(
            gate="gate1", severity="INFO", category="GIT_DIFF",
            file="", message=f"git diff 发现 {len(diff_files)} 个变更文件",
            detail="\n".join(diff_files[:15]),
        ))
        for df in diff_files[:20]:
            full = Path(BASE, df)
            if full.is_file():
                funcs = _extract_functions_from_code(str(full))
                if funcs:
                    report.add(AuditFinding(
                        gate="gate1", severity="INFO", category="FUNCTIONS",
                        file=df, message=f"定义函数: {', '.join(funcs[:10])}",
                    ))

    # 5. Registry 检查 (新增)
    reg_findings = _check_registration(diff_files)
    report.extend(reg_findings)

    return report
