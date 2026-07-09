"""
Auditor Mapping — 审计器从 git diff + AST 自动反推的需求→代码映射。

不依赖开发 Agent 自证的 developer_mapping.json。
与 developer mapping 交叉比对可发现自证不实或未声明代码。

输出:
  - auditor_mapping.json (审计器反推)
  - mapping_cross_check.json (对比结果)
"""

from __future__ import annotations
import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from .git_utils import BASE, COMMANDS
from .traceability import (
    TraceabilityMapping, Requirement, CodeLocation, MAPPING_FILE,
)


# ── 输出路径 ────────────────────────────────────────────────
TRACE_DIR = Path.home() / ".hermes" / "research-assistant" / "agent_tasks" / "traceability"
AUDITOR_MAPPING_FILE = TRACE_DIR / "auditor_mapping.json"
CROSS_CHECK_FILE = TRACE_DIR / "mapping_cross_check.json"


# ── Git + AST 分析 ────────────────────────────────────────────

def _get_diff_files() -> list[str]:
    """获取变更文件列表（同 git_utils）。"""
    from .git_utils import get_all_changed_files
    return get_all_changed_files()


def _get_diff_text() -> str:
    for cmd in [["git", "diff"], ["git", "diff", "--cached"],
                ["git", "diff", "HEAD~3", "HEAD"]]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, cwd=str(BASE))
            if r.stdout.strip():
                return r.stdout
        except Exception:
            pass
    return ""


def _extract_new_functions(file_path: str) -> list[dict]:
    """从新增文件中提取函数/类定义。"""
    results = []
    candidates = [BASE / file_path, COMMANDS / file_path, Path(file_path)]
    full = None
    for c in candidates:
        if c.is_file():
            full = c
            break
    if not full:
        return results
    try:
        src = full.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except (SyntaxError, OSError):
        return results

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body_ok = not _is_stub_body(node.body)
            results.append({
                "type": "function",
                "name": node.name,
                "line": node.lineno,
                "has_body": body_ok,
            })
        elif isinstance(node, ast.ClassDef):
            results.append({
                "type": "class",
                "name": node.name,
                "line": node.lineno,
            })
    return results


def _is_stub_body(body: list) -> bool:
    if len(body) == 1:
        if isinstance(body[0], ast.Pass):
            return True
        if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and body[0].value.value is Ellipsis:
            return True
        if isinstance(body[0], ast.Return) and body[0].value is None:
            return True
    return False


def _extract_keywords(file_path: str, src: str) -> list[str]:
    """从源码中提取外部调用关键词。"""
    keywords = set()
    # 检测 import
    for m in re.finditer(r"(?:import|from)\s+(\w+)", src):
        keywords.add(f"import {m.group(1)}")
    # 检测 HTTP 调用
    for m in re.finditer(r'https?://[^\s"\'\)]+', src):
        url = m.group(0)[:50]
        keywords.add(f"url:{url}")
    # 检测 API 调用模式
    for m in re.finditer(r'(requests|urllib|aiohttp|httpx)\s*\.\s*(get|post|put|delete)', src):
        pass  # already captured by import
    # 检测 subprocess
    if "subprocess.run" in src or "subprocess.Popen" in src:
        keywords.add("subprocess")
    # 检测文件操作
    if "open(" in src or ".read_text()" in src or ".write_text" in src:
        keywords.add("file_io")
    return sorted(keywords)


# ── 审计器映射生成 ────────────────────────────────────────────

def generate_auditor_mapping() -> TraceabilityMapping:
    """从 git diff + AST 自动生成 auditor_mapping。

    不需要 developer mapping 作为输入。
    每个变更文件中的新增函数/类都被视为一条需求声明。
    """
    mapping = TraceabilityMapping(source="auditor")
    changed_files = _get_diff_files()

    for fp in changed_files:
        if not fp.endswith(".py"):
            continue
        funcs = _extract_new_functions(fp)
        if not funcs:
            continue

        # 每个文件作为一个 requirement
        candidates = [BASE / fp, COMMANDS / fp, Path(fp)]
        full = None
        for c in candidates:
            if c.is_file():
                full = c
                break
        src = full.read_text(encoding="utf-8", errors="replace") if full else ""
        keywords = _extract_keywords(fp, src) if src else []

        code_locs = [
            CodeLocation(file=fp, function=f["name"], line=f["line"])
            for f in funcs if f["type"] == "function"
        ]
        if not code_locs:
            continue

        mapping.requirements.append(Requirement(
            id=f"AUTO-{len(mapping.requirements) + 1}",
            title=f"新增模块: {fp}",
            code_locations=code_locs,
            expected_keywords=keywords,
            behavior=f"来自审计器自动反推: {fp} 中的 {len(funcs)} 个新增函数/类",
            verified=False,
        ))

    return mapping


# ── 交叉验证 ──────────────────────────────────────────────────

def cross_check_mappings(developer: Optional[TraceabilityMapping],
                          auditor: TraceabilityMapping) -> dict:
    """比对 developer mapping 与 auditor mapping，输出交叉验证结果。

    Returns:
        dict 格式的验证报告
    """
    result = {
        "developer_claims": [],
        "unverified_claims": [],
        "unmapped_code": [],
        "conflicts": [],
        "summary": {},
    }

    dev_reqs = {r.id: r for r in developer.requirements} if developer else {}

    # 检查 developer 声称的需求是否被 auditor 验证
    for rid, req in dev_reqs.items():
        verified = False
        for loc in req.code_locations:
            for a_req in auditor.requirements:
                for a_loc in a_req.code_locations:
                    if loc.file == a_loc.file and loc.function == a_loc.function:
                        verified = True
                        break
        result["developer_claims"].append({
            "id": rid,
            "title": req.title[:60],
            "verified": verified,
            "code_locations": [loc.to_dict() for loc in req.code_locations],
        })
        if not verified:
            result["unverified_claims"].append({
                "id": rid,
                "title": req.title[:60],
            })

    # 检查 auditor 发现但 developer 未声明的
    auditor_set = set()
    for a_req in auditor.requirements:
        for a_loc in a_req.code_locations:
            auditor_set.add((a_loc.file, a_loc.function))

    dev_set = set()
    for req in dev_reqs.values():
        for loc in req.code_locations:
            dev_set.add((loc.file, loc.function))

    for (fp, fn) in sorted(auditor_set - dev_set):
        result["unmapped_code"].append({
            "file": fp,
            "function": fn,
            "message": "审计器发现但 developer mapping 未声明",
        })

    result["summary"] = {
        "developer_claims": len(dev_reqs),
        "unverified": len(result["unverified_claims"]),
        "unmapped": len(result["unmapped_code"]),
        "conflicts": len(result["conflicts"]),
    }

    return result


def run_cross_check() -> Optional[dict]:
    """运行完整的双映射交叉验证。"""
    # 加载 developer mapping
    dev_map = None
    if MAPPING_FILE.is_file():
        dev_map = TraceabilityMapping.load()

    # 生成 auditor mapping
    auditor_map = generate_auditor_mapping()

    # 保存 auditor mapping
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    auditor_map.save(AUDITOR_MAPPING_FILE)

    # 交叉验证
    cross = cross_check_mappings(dev_map, auditor_map)

    # 保存交叉验证结果
    CROSS_CHECK_FILE.write_text(
        json.dumps(cross, indent=2, ensure_ascii=False)
    )

    return cross
