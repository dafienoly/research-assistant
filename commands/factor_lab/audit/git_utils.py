"""Git 辅助 — 获取所有变更文件（含未跟踪的新文件）

供各 gate 模块共享使用，避免在各处重复相同的逻辑。
"""

from __future__ import annotations
import os
import subprocess
from pathlib import Path

BASE = Path(os.environ.get("RESEARCH_ASSISTANT_ROOT",
                           "/home/ly/.hermes/research-assistant"))
COMMANDS = BASE / "commands"
GIT_DIR = str(BASE)

# 只关注这些后缀的文件
INTERESTING_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".sh", ".yaml", ".yml", ".json", ".toml"}


def get_all_changed_files(include_untracked: bool = True,
                          skip_cached: bool = False) -> list[str]:
    """获取所有变更文件（含未跟踪的新文件）

    当 skip_cached=True 时跳过 `git diff --cached`（用于 auto-trigger 模式，
    避免扫描大量已暂存但与当前对话无关的文件）。
    也受环境变量 AUDIT_SKIP_CACHED=1 控制。

    Args:
        include_untracked: 是否包含未跟踪的新文件
        skip_cached: 是否跳过已暂存的变更

    Returns:
        相对于仓库根目录的文件路径列表，去重排序
    """
    # 环境变量覆盖
    if os.environ.get("AUDIT_SKIP_CACHED", "").strip() == "1":
        skip_cached = True

    files: set[str] = set()

    # 1. 未暂存的变更
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True, timeout=10, cwd=str(BASE))
        if r.returncode == 0:
            files.update(r.stdout.strip().splitlines())
    except Exception:
        pass

    # 2. 已暂存的变更 (auto-trigger 时跳过，避免扫描大量无关文件)
    if not skip_cached:
        try:
            r = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                capture_output=True, text=True, timeout=10, cwd=str(BASE))
            if r.returncode == 0:
                files.update(r.stdout.strip().splitlines())
        except Exception:
            pass

    # 3. 最近提交的变更（兜底）
    if not files:
        try:
            r = subprocess.run(
                ["git", "diff", "--name-only", "HEAD~3", "HEAD"],
                capture_output=True, text=True, timeout=10, cwd=str(BASE))
            if r.returncode == 0:
                files.update(r.stdout.strip().splitlines())
        except Exception:
            pass

    # 4. 未跟踪的新文件（新增但未 git add）
    if include_untracked:
        try:
            r = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                capture_output=True, text=True, timeout=10, cwd=str(BASE))
            if r.returncode == 0:
                for f in r.stdout.strip().splitlines():
                    f = f.strip()
                    if not f:
                        continue
                    ext = Path(f).suffix.lower()
                    if ext in INTERESTING_EXTENSIONS:
                        files.add(f)
        except Exception:
            pass

    return sorted(f for f in files if f.strip())


def get_source_files(extensions: set[str] | None = None) -> list[str]:
    """仅获取源代码类型的变更文件"""
    exts = extensions or {".py"}
    all_files = get_all_changed_files()
    return [f for f in all_files if Path(f).suffix.lower() in exts]
