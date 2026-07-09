"""Gate 2 — 虚假实现检测 (Stub/Fake Detection) + 生产路径防假数据

继承原有检测（pass/.../return literal/低复杂度），新增:
  5. 生产代码中的 mock/demo/sample/fallback 数据检测
  6. except Exception: pass 检测
  7. 空数据返回伪装成成功
  8. 默认 use_demo=True 检测
"""

from __future__ import annotations
import ast
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Any

from .base import AuditFinding, AuditReport, Severity
from .git_utils import get_all_changed_files, BASE, COMMANDS

# ── 名称暗示需要复杂计算 ─────────────────────────────────────
COMPLEX_NAME_PATTERN = (
    "compute", "calculate", "fetch", "load", "parse", "validate",
    "transform", "build", "generate", "resolve", "process", "score",
    "rank", "predict", "evaluate", "backtest", "run", "sync", "migrate",
    "convert", "train", "fit", "optimize", "solve", "aggregate", "filter",
    "cluster", "classify", "detect", "estimate", "infer",
)

# ── 生产路径（严格要求） ──────────────────────────────────────
PROD_PATHS = {
    "data/providers", "execution", "risk", "portfolio",
    "backtest", "live", "paper", "broker", "report",
    "hermes_cli.py",
}

# ── 假数据关键词 ────────────────────────────────────────────────
FAKE_DATA_PATTERNS = re.compile(
    r"(demo_data|sample_data|mock_data|fake_data|fallback_data|"
    r"use_demo\s*=\s*True|"
    r"\.demo\s*=|"
    r"is_demo|is_mock|is_fake|is_sample)",
    re.IGNORECASE,
)

HARDCODED_MARKET_PATTERNS = re.compile(
    r"price\s*[:=]\s*\d+\.\d+|"
    r"volume\s*[:=]\s*\d+|"
    r"amount\s*[:=]\s*\d+\.\d+|"
    r"high\s*[:=]\s*\d+\.\d+|"
    r"low\s*[:=]\s*\d+\.\d+|"
    r"open\s*[:=]\s*\d+\.\d+|"
    r"close\s*[:=]\s*\d+\.\d+",
)

BROAD_EXCEPT_PATTERNS = re.compile(
    r"except\s+(\w*Exception\w*|Error)\s*:\s*(pass|return None|return\s*\[\]|return\s*\{\})"
)

SILENT_FAIL_PATTERNS = re.compile(
    r"except\s*:[^a-z]*\b(pass|return None|return\s*\[\]|return\s*\{\}|continue)\b",
    re.DOTALL,
)


def _git_diff_files() -> list[str]:
    return get_all_changed_files()


def _is_prod_path(fp: str) -> bool:
    for pp in PROD_PATHS:
        if fp == pp or fp.startswith(pp) or f"/{pp}" in fp:
            if "/tests/" in fp or "/audit/" in fp:
                return False
            return True
    return False


# ─── AST 检测器（原有） ─────────────────────────────────────

class StubDetector(ast.NodeVisitor):
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
        raw_name = node.name

        # ── 检测 1: pass ──
        if len(body) == 1 and isinstance(body[0], ast.Pass):
            self.findings.append(AuditFinding(
                gate="gate2", severity="FAIL", category="STUB_PASS",
                file=self.file_path, line=node.lineno,
                message=f"函数 '{name}' 只有 pass 占位",
            ))
            return

        # ── 检测 2: ... ──
        if len(body) == 1 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and body[0].value.value is Ellipsis:
            self.findings.append(AuditFinding(
                gate="gate2", severity="FAIL", category="STUB_ELLIPSIS",
                file=self.file_path, line=node.lineno,
                message=f"函数 '{name}' 只有 ... 占位",
            ))
            return

        # ── 检测 3: return None / literal ──
        if len(body) == 1 and isinstance(body[0], ast.Return):
            ret = body[0]
            if ret.value is None:
                alias = name.lower().replace("_", "").replace("-", "")
                if any(p in alias for p in ["compute", "calculate", "fetch", "load"]):
                    self.findings.append(AuditFinding(
                        gate="gate2", severity="WARN", category="STUB_RETURN_NONE",
                        file=self.file_path, line=node.lineno,
                        message=f"函数 '{name}' 直接 return None",
                    ))
            elif isinstance(ret.value, ast.Constant):
                val = ret.value.value
                if isinstance(val, (int, float, str, bool)):
                    self.findings.append(AuditFinding(
                        gate="gate2", severity="WARN", category="STUB_RETURN_LITERAL",
                        file=self.file_path, line=node.lineno,
                        message=f"函数 '{name}' 返回固定常量: {repr(val)[:50]}",
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

        # ── 跳过 AST visitor 和短方法 ──
        if raw_name.startswith("visit_") or raw_name == "generic_visit":
            return
        short_methods = {"__init__", "__str__", "__repr__", "__post_init__",
                         "__len__", "__bool__", "__hash__", "__iter__", "__next__",
                         "__enter__", "__exit__", "__call__", "__getattr__",
                         "__setattr__", "__delattr__", "__contains__",
                         "properties", "abstractmethod", "staticmethod", "classmethod"}
        if name in short_methods:
            return

        # ── 检测 4: 简短函数体 (< 3 行非装饰器代码) ──
        real_lines = []
        for n in body:
            if isinstance(n, (ast.Expr,)) and isinstance(getattr(n, 'value', None), ast.Constant) \
                    and isinstance(getattr(n.value, 'value', None), str):
                continue  # skip docstring
            real_lines.append(n)
        if len(real_lines) <= 2:
            alias = raw_name.lower().replace("_", "").replace("-", "")
            if any(p in alias for p in COMPLEX_NAME_PATTERN):
                self.findings.append(AuditFinding(
                    gate="gate2", severity="WARN", category="STUB_LOW_COMPLEXITY",
                    file=self.file_path, line=node.lineno,
                    message=f"函数 '{name}' 代码行数={len(real_lines)}（名称暗示复杂逻辑）",
                ))


# ─── 新增: 生产路径假数据检测 ───────────────────────────────

def _check_fake_data_in_prod(file_paths: list[str]) -> list[AuditFinding]:
    """检查生产路径中是否使用 mock/demo/sample/fallback 数据。"""
    findings: list[AuditFinding] = []
    for fp in file_paths:
        if not fp.endswith(".py"):
            continue
        if not _is_prod_path(fp):
            continue
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

        lines = src.splitlines()

        # 检查假数据关键词
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue

            # demo/sample/mock/fake
            m = FAKE_DATA_PATTERNS.search(stripped)
            if m:
                cat_map = {
                    "demo": "PROD_DEMO_DATA",
                    "sample": "PROD_SAMPLE_DATA",
                    "mock": "PROD_MOCK_DATA",
                    "fake": "PROD_MOCK_DATA",
                    "fallback": "PROD_FALLBACK_DATA",
                }
                matched = m.group(0).lower()
                cat = "PROD_MOCK_DATA"
                for k, v in cat_map.items():
                    if k in matched:
                        cat = v
                        break
                findings.append(AuditFinding(
                    gate="gate2", severity="FAIL" if "demo" in matched else "WARN",
                    category=cat, file=fp, line=i,
                    message=f"生产路径发现 '{matched.strip()}' — 不允许生产代码使用假数据",
                    detail=f"路径 {fp} 被标记为生产路径，不允许出现 mock/demo/fallback 数据",
                ))

            # use_demo=True
            if "use_demo" in stripped and "True" in stripped:
                findings.append(AuditFinding(
                    gate="gate2", severity="FAIL", category="DEFAULT_DEMO_ENABLED",
                    file=fp, line=i,
                    message="生产代码默认 use_demo=True — 不允许",
                ))

            # except Exception: pass
            m = BROAD_EXCEPT_PATTERNS.search(stripped)
            if m:
                findings.append(AuditFinding(
                    gate="gate2", severity="WARN", category="BROAD_EXCEPT_PASS",
                    file=fp, line=i,
                    message=f"检测到宽泛 except + {m.group(2)} — 可能静默吞异常",
                    detail="生产路径中禁止 except Exception: pass/return None/return []",
                ))

            # except: pass (bare except)
            m = re.search(r"except\s*:\s*(pass|return None|return\s*\[\])", stripped)
            if m:
                findings.append(AuditFinding(
                    gate="gate2", severity="FAIL", category="BROAD_EXCEPT_PASS",
                    file=fp, line=i,
                    message=f"裸 except: {m.group(1)} — 风险极高",
                ))

            # 硬编码行情数据 (只在高风险路径检查)
            if _is_prod_path(fp):
                m = HARDCODED_MARKET_PATTERNS.search(stripped)
                if m and "def " not in stripped and "return" not in stripped:
                    # 只在 return 语句中检查硬编码
                    pass
                if "return" in stripped and m:
                    findings.append(AuditFinding(
                        gate="gate2", severity="WARN", category="HARDCODED_MARKET_DATA",
                        file=fp, line=i,
                        message=f"生产路径 return 语句包含硬编码行情数据",
                        detail=m.group(0),
                    ))

            # 空数据返回伪装成功
            if "return" in stripped and ("pd.DataFrame()" in stripped or
                    "pd.Series()" in stripped or "[]" in stripped or "{}" in stripped):
                findings.append(AuditFinding(
                    gate="gate2", severity="WARN", category="EMPTY_DATA_AS_SUCCESS",
                    file=fp, line=i,
                    message="返回空数据而未标记 degraded — 可能伪装正常",
                ))

    return findings


# ─── Radon 检测 (同原有) ─────────────────────────────────────

def _check_radon_complexity(file_paths: list[str]) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    try:
        import radon.complexity as radon_cc
        from radon.visitors import FunctionData
    except ImportError:
        return findings
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
            if cc is None or cc != 1:
                continue
            alias = name.lower().replace("_", "").replace("-", "")
            if any(p in alias for p in COMPLEX_NAME_PATTERN):
                findings.append(AuditFinding(
                    gate="gate2", severity="WARN", category="STUB_LOW_COMPLEXITY",
                    file=fp, line=getattr(block, 'lineno', 0),
                    message=f"函数 '{name}' 圈复杂度=1（名称暗示复杂逻辑）",
                    detail=f"radon 检测: cc=1 — 可能为 stub",
                ))
    return findings


# ─── Semgrep 检测 (同原有) ───────────────────────────────────

def _check_semgrep(file_paths: list[str]) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    try:
        r = subprocess.run(["semgrep", "--version"], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return findings
    except Exception:
        return findings

    rule_yaml = """rules:
  - id: hardcoded-return-dict
    pattern: |
      def $F(...):
          return {...}
    message: "函数 $F 返回硬编码字典"
    languages: [python]
    severity: ERROR
  - id: hardcoded-market-data
    pattern: |
      return {"$KEY": $VAL}
    message: "函数返回硬编码数据"
    languages: [python]
    severity: WARNING
"""
    import tempfile
    rule_file = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
    try:
        rule_file.write(rule_yaml)
        rule_file.close()
        # 一次 semgrep 扫描全部文件（比逐文件快 20-40x）
        valid_files = []
        for fp in file_paths:
            full = Path(BASE, fp) if not fp.startswith("/") else Path(fp)
            if full.is_file():
                valid_files.append(str(full))
        if not valid_files:
            return findings
        try:
            r = subprocess.run(
                ["semgrep", "--config", rule_file.name, "--json", "-q"] + valid_files,
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode in (0, 1):
                try:
                    data = json.loads(r.stdout) if r.stdout.strip() else {}
                    for res in data.get("results", []):
                        # 将 semgrep 输出的文件路径映射回相对路径
                        sg_path = res.get("path", "")
                        rel_path = sg_path
                        if BASE in Path(sg_path).parents:
                            try:
                                rel_path = str(Path(sg_path).relative_to(BASE))
                            except ValueError:
                                pass
                        findings.append(AuditFinding(
                            gate="gate2", severity="WARN", category="SEMGREP",
                            file=rel_path, line=res.get("start", {}).get("line", 0),
                            message=res.get("extra", {}).get("message", "semgrep 告警"),
                        ))
                except (json.JSONDecodeError, KeyError):
                    pass
        except Exception:
            pass
    finally:
        os.unlink(rule_file.name)
    return findings


# ─── 主入口 ───────────────────────────────────────────────────

def run_gate2(report: AuditReport) -> AuditReport:
    """执行 Gate 2: 虚假实现检测 + 生产路径防假数据"""
    report.gates_run.append("gate2")

    py_files = [f for f in _git_diff_files() if f.endswith(".py")]
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

    # 1. AST 扫描（原有 stub 检测）
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

    # 2. Radon 复杂度
    radon_findings = _check_radon_complexity(py_files)
    report.extend(radon_findings)

    # 3. Semgrep（可选）
    semgrep_findings = _check_semgrep(py_files)
    report.extend(semgrep_findings)

    # 4. 新增: 生产路径假数据检测
    fake_findings = _check_fake_data_in_prod(py_files)
    report.extend(fake_findings)

    # 5. 综合评分
    fail_count = len([f for f in report.findings if f.gate == "gate2" and f.severity == "FAIL"])
    if fail_count > 0:
        report.add(AuditFinding(
            gate="gate2", severity="FAIL", category="STUB_FOUND",
            file="", message=f"{fail_count} 个 FAIL 项 — 存在虚假实现嫌疑",
        ))

    return report
