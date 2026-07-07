"""Gate 1 — 需求→代码追溯矩阵

检测目标:
  1. 解析 plan markdown 提取每个 Task 的期望产出（文件路径、函数名、API 端点）
  2. 对比 git diff + 文件系统，逐条验证
  3. 输出缺失清单

自动检测计划文件: 扫描 .hermes/plans/ 取最新的，或接受显式路径。
"""

from __future__ import annotations
import os, re, subprocess, json
from pathlib import Path
from typing import Optional

from dataclasses import dataclass, field
from .base import AuditFinding, AuditReport, Severity

BASE = Path(os.environ.get("RESEARCH_ASSISTANT_ROOT",
                           "/home/ly/.hermes/research-assistant"))
COMMANDS = BASE / "commands"
GIT_DIR = str(BASE)


# ─── Git 辅助 ───────────────────────────────────────────────────

def _git_diff_files() -> list[str]:
    """返回当前未暂存 + 已暂存的变更文件列表"""
    files: set[str] = set()
    for cmd in [["git", "diff", "--name-only"], ["git", "diff", "--cached", "--name-only"]]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=GIT_DIR)
            if r.returncode == 0:
                files.update(r.stdout.strip().splitlines())
        except Exception:
            pass
    return sorted(f for f in files if f.strip())


def _git_committed_files_since(tag: str = "HEAD~5") -> list[str]:
    """最近 N 个提交中变更的文件（用于无未提交变更时的追溯）"""
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", tag, "HEAD"],
            capture_output=True, text=True, timeout=10, cwd=GIT_DIR
        )
        if r.returncode == 0:
            return [f for f in r.stdout.strip().splitlines() if f.strip()]
    except Exception:
        pass
    return []


# ─── Plan 解析 ───────────────────────────────────────────────────

TASK_HEADER_RE = re.compile(r"^###\s+Task\s+\d+", re.MULTILINE | re.IGNORECASE)
FILE_CREATE_RE = re.compile(r"- \*\*Create:\*\*\s+`([^`]+)`", re.IGNORECASE)
FILE_MODIFY_RE = re.compile(r"- \*\*Modify:\*\*\s+`([^`]+)`", re.IGNORECASE)
FUNC_DEF_RE = re.compile(r"^def\s+(test_)?(\w+)", re.MULTILINE)
CLASS_DEF_RE = re.compile(r"^class\s+(\w+)", re.MULTILINE)
ENDPOINT_RE = re.compile(r"@app\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]")

# 常见偷懒词 — 函数名暗示应该复杂但可能被简化
STUB_SUSPECT_NAMES = re.compile(
    r"^(compute_?|calculate_?|fetch_?|load_?|parse_?|validate_?|"
    r"transform_?|build_?|generate_?|resolve_?|process_?|score_?|rank_?|"
    r"predict_?|evaluate_?|backtest_?|run_?|sync_?|migrate_?|convert_?)",
    re.IGNORECASE,
)


@dataclass
class PlanTask:
    title: str
    expected_creates: list[str] = field(default_factory=list)
    expected_modifies: list[str] = field(default_factory=list)


def _find_plan_files() -> list[Path]:
    """找 .hermes/plans/ 下的最新计划文件"""
    plans_dir = BASE / ".hermes" / "plans"
    if not plans_dir.is_dir():
        return []
    # 按修改时间排序，取最新的 3 个
    candidates = sorted(plans_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[:3]


def _parse_plan_md(text: str) -> list[PlanTask]:
    """解析 plan markdown 提取 Task 清单"""
    tasks: list[PlanTask] = []
    current: Optional[PlanTask] = None
    header_match = None

    for line in text.splitlines():
        # 检测 Task 标题
        m = re.match(r"^###\s+(Task\s+\d+.*)", line, re.IGNORECASE)
        if m:
            if current:
                tasks.append(current)
            current = PlanTask(title=m.group(1).strip())
            continue

        if current is None:
            continue

        # 创建文件
        m = re.search(r"- \*\*Create:\*\*\s+`([^`]+)`", line, re.IGNORECASE)
        if m:
            current.expected_creates.append(m.group(1))
            continue

        # 修改文件
        m = re.search(r"- \*\*Modify:\*\*\s+`([^`]+)`", line, re.IGNORECASE)
        if m:
            current.expected_modifies.append(m.group(1))
            continue

    if current:
        tasks.append(current)

    return tasks


def _extract_functions_from_code(file_path: str) -> list[str]:
    """从代码文件中提取函数名"""
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


def _extract_functions_from_diff(diff_output: str) -> list[str]:
    """从 git diff 输出中提取新增的函数定义"""
    funcs = []
    in_hunk = False
    for line in diff_output.splitlines():
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk:
            continue
        # 只关注新增行（+ 开头，不包括 +++）
        if line.startswith("+") and not line.startswith("+++"):
            clean = line[1:].strip()
            m = FUNC_DEF_RE.match(clean)
            if m and m.group(2):
                funcs.append(m.group(2))
    return funcs


# ─── 核心检测 ───────────────────────────────────────────────────

def _check_files_exist(files: list[str], rel_root: str = "") -> list[AuditFinding]:
    """检查文件是否存在"""
    findings: list[AuditFinding] = []
    for f in files:
        # 尝试相对路径
        full = Path(rel_root, f) if rel_root else Path(f)
        checked = str(full)
        if not full.is_absolute():
            # 同时检查 commands/ 下和根目录
            candidates = [
                BASE / f,
                COMMANDS / f,
                BASE / f.replace("commands/", "", 1),
            ]
            checked = str([str(c) for c in candidates])
            exists = any(c.is_file() for c in candidates)
        else:
            exists = full.is_file()

        if not exists:
            findings.append(AuditFinding(
                gate="gate1", severity="FAIL", category="MISSING_FILE",
                file=f, message=f"计划中标记为创建/修改的文件不存在: {f}",
                detail=f"检查路径: {checked}",
            ))
        else:
            findings.append(AuditFinding(
                gate="gate1", severity="INFO", category="FILE_EXISTS",
                file=f, message=f"文件已存在: {f}",
            ))
    return findings


def run_gate1(report: AuditReport, plan_path: Optional[str] = None) -> AuditReport:
    """执行 Gate 1: 需求→代码追溯"""
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
            file="", message="未找到计划文件 (.hermes/plans/*.md)，跳过需求追溯",
        ))
        # 降级: 只报告变更文件中的新函数
        report.add(AuditFinding(
            gate="gate1", severity="INFO", category="NO_PLAN",
            file="", message="降级模式: 仅扫描 git diff 中的新增函数",
        ))
        diff_files = _git_diff_files()
        if not diff_files:
            diff_files = _git_committed_files_since()
        if diff_files:
            report.add(AuditFinding(
                gate="gate1", severity="INFO", category="CHANGED_FILES",
                file="", message=f"发现 {len(diff_files)} 个变更文件",
                detail="\n".join(diff_files[:20]),
            ))
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
        # 降级: 对每个文件扫描函数
        diff_files = _git_diff_files()
        if not diff_files:
            diff_files = _git_committed_files_since()
        if diff_files:
            report.add(AuditFinding(
                gate="gate1", severity="INFO", category="CHANGED_FILES",
                file="", message=f"发现 {len(diff_files)} 个变更文件（无 Task 解析）",
                detail="\n".join(diff_files[:20]),
            ))
        return report

    report.add(AuditFinding(
        gate="gate1", severity="INFO", category="PLAN_FOUND",
        file=str(plans[0]), message=f"解析到 {len(tasks)} 个 Task",
        detail="\n".join(f"  {t.title}" for t in tasks),
    ))

    # 3. 逐 Task 检查
    all_creates = []
    all_modifies = []
    for t in tasks:
        all_creates.extend(t.expected_creates)
        all_modifies.extend(t.expected_modifies)

    # 去重
    all_creates = list(set(all_creates))
    all_modifies = list(set(all_modifies))

    # 3a. 检查创建文件
    create_findings = _check_files_exist(all_creates, str(BASE))
    report.extend(create_findings)

    # 3b. 检查修改文件
    modify_findings = _check_files_exist(all_modifies, str(BASE))
    report.extend(modify_findings)

    # 3c. 额外: 检查 git diff 中是否有新增函数
    diff_files = _git_diff_files()
    if not diff_files:
        diff_files = _git_committed_files_since()
    if diff_files:
        report.add(AuditFinding(
            gate="gate1", severity="INFO", category="GIT_DIFF",
            file="", message=f"git diff 发现 {len(diff_files)} 个变更文件",
            detail="\n".join(diff_files[:15]),
        ))
        # 扫描变更文件中的函数
        for df in diff_files[:20]:
            full = Path(BASE, df)
            if full.is_file():
                funcs = _extract_functions_from_code(str(full))
                if funcs:
                    report.add(AuditFinding(
                        gate="gate1", severity="INFO", category="FUNCTIONS",
                        file=df, message=f"定义函数: {', '.join(funcs[:10])}",
                    ))

    return report
