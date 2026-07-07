"""Gate 2 — 虚假实现检测 (Stub/Fake Detection)

检测策略:
  1. AST 扫描: 函数体只有 pass / ... / return <literal> / return None
  2. Radon 圈复杂度: 函数名暗示复杂逻辑但 CC=1
  3. Hardcoded 数据检测: 函数返回字面量 dict/list 且不依赖输入
  4. 缺失外部调用检测: 函数名暗示 IO/计算但没有预期调用

依赖:
  - radon (pip install radon)
  - Python ast (stdlib)
"""

from __future__ import annotations
import ast
import json
import os
import subprocess
from pathlib import Path
from typing import Optional, Any

from .base import AuditFinding, AuditReport, Severity

BASE = Path(os.environ.get("RESEARCH_ASSISTANT_ROOT",
                           "/home/ly/.hermes/research-assistant"))
COMMANDS = BASE / "commands"

# 名称暗示需要复杂计算的函数
COMPLEX_NAME_PATTERN = (
    "compute", "calculate", "fetch", "load", "parse", "validate",
    "transform", "build", "generate", "resolve", "process", "score",
    "rank", "predict", "evaluate", "backtest", "run", "sync", "migrate",
    "convert", "train", "fit", "optimize", "solve", "aggregate", "filter",
    "cluster", "classify", "detect", "estimate", "infer",
)


# ─── Git 辅助 ───────────────────────────────────────────────────

def _git_diff_files() -> list[str]:
    files: set[str] = set()
    for cmd in [["git", "diff", "--name-only"], ["git", "diff", "--cached", "--name-only"]]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10,
                               cwd=str(BASE))
            if r.returncode == 0:
                files.update(r.stdout.strip().splitlines())
        except Exception:
            pass
    # 如果 diff 为空，取最近提交的变更
    if not files:
        try:
            r = subprocess.run(["git", "diff", "--name-only", "HEAD~3", "HEAD"],
                               capture_output=True, text=True, timeout=10, cwd=str(BASE))
            if r.returncode == 0:
                files.update(r.stdout.strip().splitlines())
        except Exception:
            pass
    return sorted(f for f in files if f.strip() and f.endswith(".py"))


# ─── AST 检测器 ─────────────────────────────────────────────────

class StubDetector(ast.NodeVisitor):
    """AST 遍历器，检测 stub 模式"""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.findings: list[AuditFinding] = []
        self.current_class: Optional[str] = None

    def visit_ClassDef(self, node: ast.ClassDef):
        old = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = old

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._check_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._check_function(node)
        self.generic_visit(node)

    def _func_name(self, node: ast.FunctionDef) -> str:
        if self.current_class:
            return f"{self.current_class}.{node.name}"
        return node.name

    def _check_function(self, node: ast.AST):
        name = self._func_name(node)
        body = node.body

        # ── 检测 1: pass 函数体 ──
        if len(body) == 1 and isinstance(body[0], ast.Pass):
            self.findings.append(AuditFinding(
                gate="gate2", severity="FAIL", category="STUB_PASS",
                file=self.file_path, line=node.lineno,
                message=f"函数 '{name}' 只有 pass 占位",
                detail=f"函数体为空实现",
            ))
            return

        # ── 检测 2: Ellipsis (…) 函数体 ──
        if len(body) == 1 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and body[0].value.value is Ellipsis:
            self.findings.append(AuditFinding(
                gate="gate2", severity="FAIL", category="STUB_ELLIPSIS",
                file=self.file_path, line=node.lineno,
                message=f"函数 '{name}' 只有 ... 占位",
                detail=f"函数体为空实现（Ellipsis）",
            ))
            return

        # ── 检测 3: return None 或 return <literal> ──
        if len(body) == 1 and isinstance(body[0], ast.Return):
            ret = body[0]
            if ret.value is None:
                # 裸 return
                alias = name.lower().replace("_", "").replace("-", "")
                if any(p in alias for p in ["compute", "calculate", "fetch", "load"]):
                    self.findings.append(AuditFinding(
                        gate="gate2", severity="WARN", category="STUB_RETURN_NONE",
                        file=self.file_path, line=node.lineno,
                        message=f"函数 '{name}' 直接 return None（名称暗示应有返回值）",
                    ))
            elif isinstance(ret.value, ast.Constant):
                val = ret.value.value
                if val is None:
                    self.findings.append(AuditFinding(
                        gate="gate2", severity="INFO", category="STUB_RETURN_NONE",
                        file=self.file_path, line=node.lineno,
                        message=f"函数 '{name}' 返回 None",
                    ))
                # 返回字面常量（数字、字符串、布尔）— 可能是硬编码
                elif isinstance(val, (int, float, str, bool)):
                    self.findings.append(AuditFinding(
                        gate="gate2", severity="WARN", category="STUB_RETURN_LITERAL",
                        file=self.file_path, line=node.lineno,
                        message=f"函数 '{name}' 返回固定常量: {repr(val)[:50]}",
                        detail=f"如果该函数应计算动态结果，这是硬编码嫌疑",
                    ))
            elif isinstance(ret.value, ast.List):
                elements = ret.value.elts
                if len(elements) <= 3 and all(isinstance(e, ast.Constant) for e in elements):
                    vals = [str(e.value) for e in elements]
                    self.findings.append(AuditFinding(
                        gate="gate2", severity="WARN", category="STUB_RETURN_LIST",
                        file=self.file_path, line=node.lineno,
                        message=f"函数 '{name}' 返回硬编码列表: [{', '.join(vals)}]",
                    ))
            elif isinstance(ret.value, ast.Dict):
                keys = [k.value if isinstance(k, ast.Constant) else "?" for k in (ret.value.keys or [])]
                self.findings.append(AuditFinding(
                    gate="gate2", severity="WARN", category="STUB_RETURN_DICT",
                    file=self.file_path, line=node.lineno,
                    message=f"函数 '{name}' 返回硬编码字典: keys={keys}",
                ))

        # ── 检测 4: 简短函数体 (<=2 行非装饰器/docstring 代码) ──
        code_lines = [n for n in body
                      if not isinstance(n, (ast.Expr, ast.Pass))
                      or not isinstance(getattr(n, 'value', None), ast.Constant)]
        # 排除 docstring（Expr + Constant(str)）
        stmt_lines = [n for n in body
                      if not (isinstance(n, ast.Expr)
                              and isinstance(n.value, ast.Constant)
                              and isinstance(n.value.value, str))]
        # docstring 去掉后看有效语句数
        # 只有 1 条有效语句 + 函数名暗示复杂 → WARN
        alias = name.lower().replace("_", "").replace("-", "")
        is_complex_name = any(p in alias for p in COMPLEX_NAME_PATTERN)
        if is_complex_name and len(stmt_lines) <= 2:
            # 避免误报: 属性访问、简单委托等
            has_real_call = any(
                isinstance(n, ast.Call) for n in stmt_lines
            )
            has_control_flow = any(
                isinstance(n, (ast.If, ast.For, ast.While, ast.Try))
                for n in stmt_lines
            )
            if not has_real_call and not has_control_flow:
                self.findings.append(AuditFinding(
                    gate="gate2", severity="WARN", category="STUB_TOO_SIMPLE",
                    file=self.file_path, line=node.lineno,
                    message=f"函数 '{name}' 名称暗示复杂逻辑但仅有 {len(stmt_lines)} 条语句",
                    detail=f"有效代码行数: {len(stmt_lines)}",
                ))

        # ── 检测 5: 函数体只有一行字符串（可能是 docstring-only stub）──
        if len(body) == 1 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str) and '\n' not in body[0].value.value:
            self.findings.append(AuditFinding(
                gate="gate2", severity="WARN", category="STUB_DOCSTRING_ONLY",
                file=self.file_path, line=node.lineno,
                message=f"函数 '{name}' 只有一行 docstring，无实际逻辑",
            ))


# ─── Radon 圈复杂度检测 ───────────────────────────────────────────

def _check_radon_complexity(file_paths: list[str]) -> list[AuditFinding]:
    """使用 radon 检测圈复杂度异常低的函数"""
    findings: list[AuditFinding] = []
    try:
        import radon.complexity as radon_cc
        from radon.visitors import FunctionData
    except ImportError:
        return findings  # 无 radon 时跳过

    for fp in file_paths:
        full = Path(BASE, fp) if not fp.startswith("/") else Path(fp)
        if not full.is_file():
            continue
        try:
            source = full.read_text(encoding="utf-8", errors="replace")
            blocks = radon_cc.cc_visit(source)
        except Exception:
            continue

        for block in blocks:
            if not hasattr(block, 'name'):
                continue
            name = block.name
            cc = getattr(block, 'complexity', None)
            if cc is None:
                continue
            # 只看 CC=1 且名称暗示复杂逻辑的函数
            if cc != 1:
                continue
            alias = name.lower().replace("_", "").replace("-", "")
            if any(p in alias for p in COMPLEX_NAME_PATTERN):
                findings.append(AuditFinding(
                    gate="gate2", severity="WARN", category="STUB_LOW_COMPLEXITY",
                    file=fp, line=getattr(block, 'lineno', 0),
                    message=f"函数 '{name}' 圈复杂度=1（名称暗示复杂逻辑）",
                    detail=f"radon 检测: {cc=} — 可能为 stub",
                ))
    return findings


# ─── Semgrep 规则检测 ───────────────────────────────────────────

def _check_semgrep(file_paths: list[str]) -> list[AuditFinding]:
    """使用 semgrep 运行自定义 anti-stub 规则（15s 超时，忽略失败）"""
    findings: list[AuditFinding] = []
    try:
        # 检查 semgrep 是否可用
        import subprocess as _sp
        r = _sp.run(["semgrep", "--version"], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return findings
    except Exception:
        return findings

    # 使用 semgrep 命令行
    rule_yaml = """
rules:
  - id: hardcoded-return-dict
    pattern: |
      def $F(...):
          return {...}
    message: "函数 $F 返回硬编码字典"
    languages: [python]
    severity: WARNING
  - id: hardcoded-return-list
    pattern: |
      def $F(...):
          return [...]
    message: "函数 $F 返回硬编码列表"
    languages: [python]
    severity: WARNING
  - id: stub-return-zero
    patterns:
      - pattern: |
          def $F(...):
              return 0
      - metavariable-regex:
          metavariable: $F
          regex: (compute|calculate|fetch|build|generate|predict).*
    message: "函数 $F 返回固定值 0，疑似 stub"
    languages: [python]
    severity: WARNING
  - id: empty-except-pass
    pattern: |
      except:
          pass
    message: "bare except + pass — 静默吞异常"
    languages: [python]
    severity: WARNING
  - id: todo-stub
    pattern: |
      def $F(...):
          ...
    message: "函数 $F 只有 ... 占位"
    languages: [python]
    severity: WARNING
"""
    import tempfile
    rule_file = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    try:
        rule_file.write(rule_yaml)
        rule_file.close()

        for fp in file_paths:
            full = Path(BASE, fp) if not fp.startswith("/") else Path(fp)
            if not full.is_file():
                continue
            try:
                r = subprocess.run(
                    ["semgrep", "--config", rule_file.name, "--json", "-q", str(full)],
                    capture_output=True, text=True, timeout=15,
                )
                if r.returncode not in (0, 1):
                    continue
                try:
                    data = json.loads(r.stdout) if r.stdout.strip() else {}
                    results = data.get("results", [])
                    for res in results:
                        findings.append(AuditFinding(
                            gate="gate2", severity="WARN", category="SEMGREP",
                            file=fp,
                            line=res.get("start", {}).get("line", 0),
                            message=res.get("extra", {}).get("message", "semgrep 告警"),
                            detail=f"规则: {res.get('check_id', '?')} | {res.get('extra', {}).get('message', '')}",
                        ))
                except (json.JSONDecodeError, KeyError):
                    pass
            except Exception:
                pass
    finally:
        os.unlink(rule_file.name)

    return findings


# ─── 主入口 ─────────────────────────────────────────────────────

def run_gate2(report: AuditReport) -> AuditReport:
    """执行 Gate 2: 虚假实现检测"""
    report.gates_run.append("gate2")

    # 1. 获取变更的 .py 文件
    py_files = _git_diff_files()
    if not py_files:
        report.add(AuditFinding(
            gate="gate2", severity="INFO", category="NO_CHANGES",
            file="", message="无变更的 Python 文件，跳过",
        ))
        return report

    report.add(AuditFinding(
        gate="gate2", severity="INFO", category="SCAN_FILES",
        file="", message=f"扫描 {len(py_files)} 个 Python 文件",
        detail="\n".join(py_files[:15]),
    ))

    # 2. AST 扫描
    for fp in py_files:
        full = Path(BASE, fp) if not fp.startswith("/") else Path(fp)
        if not full.is_file():
            continue
        try:
            source = full.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=fp)
            detector = StubDetector(fp)
            detector.visit(tree)
            report.extend(detector.findings)
        except SyntaxError:
            report.add(AuditFinding(
                gate="gate2", severity="FAIL", category="SYNTAX_ERROR",
                file=fp, message="Python 语法错误（Stub 检测跳过）",
            ))

    # 3. Radon 复杂度检测
    radon_findings = _check_radon_complexity(py_files)
    report.extend(radon_findings)

    # 4. Semgrep 规则检测（如果可用）
    semgrep_findings = _check_semgrep(py_files)
    report.extend(semgrep_findings)

    # 5. 综合评分
    if not report.fails:
        fail_count = len([f for f in report.findings if f.gate == "gate2" and f.severity == "FAIL"])
        if fail_count > 0:
            report.add(AuditFinding(
                gate="gate2", severity="FAIL", category="STUB_FOUND",
                file="", message=f"{fail_count} 个 FAIL 项 — 存在虚假实现嫌疑",
            ))

    return report
