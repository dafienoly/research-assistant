"""Meta-test: 检测局部 import 阴影全局 import 的潜在 UnboundLocalError。

扫描 leader 目录 + leader_commands.py，查找以下危险模式：
  模块级有 import XXX
  函数体内也有 import XXX（非 as 别名）
  且函数体内在 import 之前就使用了 XXX
"""
import ast
import os
from pathlib import Path


def _module_imports(tree):
    names = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = (alias.asname or alias.name).split(".")[0].strip()
                if name:
                    names.add(name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                name = (alias.asname or alias.name).strip()
                if name:
                    names.add(name)
    return names


def _function_local_imports(node):
    imports = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Import):
            for alias in sub.names:
                name = (alias.asname or alias.name).split(".")[0].strip()
                if name:
                    imports.append((sub.lineno, name))
        elif isinstance(sub, ast.ImportFrom):
            for alias in sub.names:
                name = (alias.asname or alias.name).strip()
                if name:
                    imports.append((sub.lineno, name))
    return imports


def _name_used_before(tree, func_node, name, import_lineno):
    refs = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Name) and node.id == name and node.lineno and node.lineno < import_lineno:
            refs.append(node.lineno)
    return refs


def scan_file(filepath):
    findings = []
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            tree = ast.parse(f.read(), filename=filepath)
    except (SyntaxError, Exception):
        return findings
    mod_imports = _module_imports(tree)
    if not mod_imports:
        return findings
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for lineno, name in _function_local_imports(node):
            if name not in mod_imports:
                continue
            refs = _name_used_before(tree, node, name, lineno)
            if refs:
                findings.append({
                    "file": filepath, "function": node.name,
                    "import_name": name, "import_lineno": lineno,
                    "used_before_at": refs,
                })
    return findings


LEADER_DIR = "/home/ly/.hermes/research-assistant/commands/factor_lab/leader"
EXTRA_FILES = ["/home/ly/.hermes/research-assistant/commands/leader_commands.py"]
IGNORE_DIRS = {"__pycache__"}


def test_no_shadowed_imports_leader():
    """leader 目录无局部 import 阴影全局 import"""
    findings = []
    for root, dirs, files in os.walk(LEADER_DIR):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in files:
            if f.endswith(".py"):
                findings.extend(scan_file(os.path.join(root, f)))
    for f in EXTRA_FILES:
        if os.path.exists(f):
            findings.extend(scan_file(f))

    if findings:
        msg = [f"发现 {len(findings)} 处危险阴影:"]
        for f in findings[:20]:
            rel = os.path.relpath(f["file"], "/home/ly/.hermes/research-assistant")
            msg.append(f"  {rel}:{f['import_lineno']} — {f['function']}() "
                       f"局部导入 '{f['import_name']}' 但前面已使用")
        if len(findings) > 20:
            msg.append(f"  ... 还有 {len(findings)-20} 处")
        assert False, "\n".join(msg)
