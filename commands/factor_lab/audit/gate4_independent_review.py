"""Gate 4 — 独立需求审计

两种模式:
  A) **Agent 模式**（推荐）— Hermes Agent 调用 delegate_task 派发独立审查
     CLI 命令输出 audit prompt, Hermes 可以用它作为任务输入

  B) **规则降级模式**— CLI 中无 delegate_task 可用时，
     用规则引擎做基础检查: 文件是否存在、函数体是否非空、diff 是否有实质内容

设计原则:
  - 不能在 CLI 中假装有 delegate_task — 这不诚实
  - CLI 输出结构化 audit prompt 给上层
  - 或者用规则引擎做表面检查
"""

from __future__ import annotations
import ast
import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from .base import AuditFinding, AuditReport, Severity
from .git_utils import get_all_changed_files, BASE, COMMANDS


# ─── Git 辅助 ───────────────────────────────────────────────────

def _git_diff_text() -> str:
    for cmd in [["git", "diff"], ["git", "diff", "--cached"],
                ["git", "diff", "HEAD~3", "HEAD"]]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=str(BASE))
            if r.stdout.strip():
                return r.stdout
        except Exception:
            pass
    return ""


def _git_diff_files() -> list[str]:
    return get_all_changed_files()


def _get_recent_plans() -> str:
    plans_dir = BASE / ".hermes" / "plans"
    if not plans_dir.is_dir():
        return ""
    plans = sorted(plans_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    parts = []
    for p in plans[:2]:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            parts.append(f"=== {p.name} ===\n{text[:3000]}")
        except Exception:
            pass
    return "\n\n".join(parts)


# ─── 规则引擎降级 ───────────────────────────────────────────────

def _rule_based_analysis(diff_text: str, diff_files: list[str], plan_text: str) -> list[AuditFinding]:
    """当 delegate_task 不可用时，用规则引擎做基础检查"""
    findings: list[AuditFinding] = []

    if not diff_files and not diff_text:
        findings.append(AuditFinding(
            gate="gate4", severity="INFO", category="RULE_NO_DIFF",
            file="", message="无 git diff — 无法做需求对比",
        ))
        return findings

    # 1. 检查 diff 是否只有非代码文件
    code_files = [f for f in diff_files if f.endswith(".py")]
    if not code_files:
        findings.append(AuditFinding(
            gate="gate4", severity="INFO", category="RULE_NO_PY",
            file="", message=f"变更中无 Python 文件 (仅 {len(diff_files)} 个非代码文件变更)",
        ))
        return findings

    # 2. 检查是否 plan 存在但 diff 文件极少
    if plan_text and len(diff_files) <= 2:
        findings.append(AuditFinding(
            gate="gate4", severity="WARN", category="RULE_PLAN_VS_DIFF",
            file="", message=f"存在 plan 但仅 {len(diff_files)} 个文件变更，可能跳过需求",
            detail=f"Plan:\n{plan_text[:500]}",
        ))

    # 3. 检查 diff 中是否有实质性的新增代码行（非空/非注释/非 import）
    if diff_text:
        added_lines = 0
        for line in diff_text.splitlines():
            if line.startswith("+") and not line.startswith("+++") and line.strip("+ "):
                cl = line[1:].strip()
                if cl and not cl.startswith("#") and not cl.startswith("import") and not cl.startswith("from "):
                    added_lines += 1
        if added_lines == 0:
            findings.append(AuditFinding(
                gate="gate4", severity="FAIL", category="RULE_NO_SUBSTANCE",
                file="", message="diff 中无实质性新增代码（仅 import/注释/空行）",
            ))
        elif added_lines < 10:
            # 检查是否有 plan
            if plan_text:
                findings.append(AuditFinding(
                    gate="gate4", severity="WARN", category="RULE_LOW_OUTPUT",
                    file="", message=f"存在 plan 但仅有 {added_lines} 行有效新增代码 — 可能缩减实现",
                    detail=f"Plan:\n{plan_text[:500]}",
                ))

        # 4. 检查 diff 中是否包含 TODO/FIXME/HACK 标记
        todo_lines = []
        for i, line in enumerate(diff_text.splitlines()):
            if line.startswith("+") and ("TODO" in line or "FIXME" in line or "HACK" in line or "XXX" in line):
                todo_lines.append(f"  L{i+1}: {line[1:].strip()[:100]}")
        if todo_lines:
            findings.append(AuditFinding(
                gate="gate4", severity="WARN", category="RULE_TODO_LEFT",
                file="", message=f"diff 中包含 {len(todo_lines)} 个 TODO/FIXME 标记",
                detail="\n".join(todo_lines[:5]),
            ))

    # 5. 检查是否新的 .py 文件只有空类/空函数
    for f in diff_files:
        if not f.endswith(".py"):
            continue
        full = Path(BASE, f) if not f.startswith("/") else Path(f)
        if not full.is_file():
            continue
        try:
            source = full.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=f)
        except (SyntaxError, Exception):
            continue

        empty_funcs = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # 检查是否只有 docstring 或 pass
                body_lines = [n for n in node.body
                              if not (isinstance(n, ast.Expr)
                                      and isinstance(n.value, ast.Constant)
                                      and isinstance(n.value.value, str))]
                if not body_lines or all(isinstance(n, ast.Pass) for n in body_lines):
                    empty_funcs.append(node.name)

        if empty_funcs:
            findings.append(AuditFinding(
                gate="gate4", severity="FAIL", category="RULE_EMPTY_FUNCTIONS",
                file=f, message=f"文件中有空函数: {', '.join(empty_funcs[:5])}",
                detail=f"这些函数没有实际实现，可能是 stub",
            ))

    # 6. 检查是否有对应的 test 文件
    for f in code_files:
        test_path = COMMANDS / "tests" / f"test_{Path(f).name}"
        if not test_path.is_file():
            # 只在确定这是新功能文件时才警告
            findings.append(AuditFinding(
                gate="gate4", severity="WARN", category="RULE_NO_TEST_FILE",
                file=f, message=f"新增源文件没有对应测试文件",
                detail=f"期望: {test_path}",
            ))

    return findings


# ─── Prompt 生成 ────────────────────────────────────────────────

INDEPENDENT_AUDIT_PROMPT = """## 独立需求审计任务

你是独立代码审计员。你没有参与本次开发，你的视角是客观的、无偏的。

### 你的任务

对比 {section} 中的原始需求/计划和 {section} 中的实际产出，
评估每一项需求是否被真实实现。

### 评估标准

| 标记 | 含义 | Severity |
|------|------|----------|
| IMPLEMENTED | 有明确证据表明被真实实现了 | INFO |
| STUB | 文件/函数存在但实现为空或硬编码 | FAIL |
| MISSING | 完全没有对应代码产出 | FAIL |
| MOCK_DATA | 使用了硬编码数据代替真实计算 | FAIL |
| UNVERIFIABLE | 无法判断 | WARN |

### 输出格式

返回 ONLY 以下 JSON，不要有其他文字：

```json
{{
  "verdicts": [
    {{
      "requirement": "需求描述",
      "status": "IMPLEMENTED|STUB|MISSING|MOCK_DATA|UNVERIFIABLE",
      "evidence": "具体依据",
      "severity": "FAIL|WARN|INFO"
    }}
  ],
  "summary": {{
    "total": 0,
    "implemented": 0,
    "stub": 0,
    "missing": 0,
    "mock_data": 0
  }},
  "overall_passed": true_or_false,
  "risks": ["高风险描述", ...]
}}
```
"""


def build_audit_prompt() -> str:
    """构建独立审计用的 prompt（供 delegate_task 使用）"""
    diff_text = _git_diff_text()
    diff_files = _git_diff_files()
    plan_text = _get_recent_plans()

    sections = {
        "原始需求/计划": plan_text or "(无 plan 文件)",
        "变更文件": "\n".join(f"  - {f}" for f in diff_files[:30]) if diff_files else "(无变更)",
        "Git Diff（截取前 15000 字符）": diff_text[:15000] if diff_text else "(无 diff)",
    }

    body_parts = []
    for title, content in sections.items():
        body_parts.append(f"### {title}\n\n{content}")

    prompt = INDEPENDENT_AUDIT_PROMPT.format(section="各")
    return prompt + "\n\n" + "\n\n".join(body_parts)


def run_gate4(report: AuditReport) -> AuditReport:
    """执行 Gate 4: 独立需求审计（规则降级模式）"""
    report.gates_run.append("gate4")

    diff_text = _git_diff_text()
    diff_files = _git_diff_files()
    plan_text = _get_recent_plans()

    if not diff_text and not diff_files:
        report.add(AuditFinding(
            gate="gate4", severity="INFO", category="NO_CHANGES",
            file="", message="无变更，跳过独立审计",
        ))
        return report

    # 规则引擎降级模式
    findings = _rule_based_analysis(diff_text, diff_files, plan_text)
    report.extend(findings)

    # 同时生成 audit prompt（说明: 用 delegate_task 可获得更深入的审查）
    prompt = build_audit_prompt()
    report.add(AuditFinding(
        gate="gate4", severity="INFO", category="PROMPT_AVAILABLE",
        file="", message="已生成独立审计 prompt — 可用 delegate_task 派发深度审查",
        detail=prompt[:500] + "\n...(full prompt in report)",
    ))
    # 额外的深度审计 fallback: 在 audit prompt 中输出，可以供外部消费
    report.extras = getattr(report, 'extras', {})
    report.extras["gate4_prompt"] = prompt

    return report
