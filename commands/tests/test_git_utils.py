"""git_utils 单元测试"""
import os, sys, subprocess, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


class TestGitUtils:
    def test_imports(self):
        from factor_lab.audit.git_utils import get_all_changed_files, BASE, COMMANDS, GIT_DIR
        assert str(BASE).endswith("research-assistant")
        assert str(COMMANDS).endswith("commands")
        assert isinstance(GIT_DIR, str)

    def test_get_all_changed_files_returns_list(self):
        from factor_lab.audit.git_utils import get_all_changed_files
        files = get_all_changed_files()
        assert isinstance(files, list)
        # 应该在 commands/ 目录内有文件
        commands_files = [f for f in files if f.startswith("commands/")]
        assert len(commands_files) > 0, "应该有 commands/ 目录下的变更文件"

    def test_get_all_changed_files_no_symlinks_or_abs(self):
        from factor_lab.audit.git_utils import get_all_changed_files
        files = get_all_changed_files()
        for f in files[:20]:
            assert not f.startswith("/"), f"路径应该是相对的: {f}"

    def test_get_source_files_returns_py(self):
        from factor_lab.audit.git_utils import get_source_files
        py_files = get_source_files()
        assert all(f.endswith(".py") for f in py_files)

    def test_get_source_files_custom_ext(self):
        from factor_lab.audit.git_utils import get_source_files
        md_files = get_source_files(extensions={".md"})
        assert all(f.endswith(".md") for f in md_files)
