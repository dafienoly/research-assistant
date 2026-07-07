"""Factor ↔ Alpha Bridge 单元测试"""

import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from factor_lab.factor_alpha_bridge import (
    sync_factors_to_alpha, sync_single_factor_to_alpha,
    sync_alpha_to_factors, unified_list,
    cmd_sync, cmd_unified_list,
)


class TestSyncBridge:
    def test_sync_dry_run(self):
        """dry-run 模式不写 Alpha Registry"""
        result = sync_factors_to_alpha(dry_run=True)
        assert result["dry_run"] is True
        # 可能部分因子已同步，但至少不应报错
        assert result["errors"] == 0
        assert "synced" in result

    def test_sync_dry_run_by_category(self):
        """按 category 筛选"""
        result = sync_factors_to_alpha(dry_run=True, category="momentum")
        assert result["dry_run"] is True
        # 所有同步的都应该是 momentum 类别
        for s in result["details"]["synced"]:
            from factor_lab.factor_base import list_factors
            factor = [f for f in list_factors() if f["name"] == s["name"]]
            if factor:
                assert factor[0]["category"] == "momentum"

    def test_sync_single_not_found(self):
        """不存在的因子返回 None"""
        aid = sync_single_factor_to_alpha("nonexistent_factor_xyz")
        assert aid is None

    def test_unified_list_structure(self):
        """统一视图的字段完整性"""
        entries = unified_list()
        assert len(entries) > 0
        for e in entries[:5]:
            assert "name" in e
            assert "category" in e
            assert "alpha_status" in e

    def test_unified_list_by_category(self):
        """按 category 筛选统一视图"""
        entries = unified_list(category="momentum")
        assert len(entries) > 0
        for e in entries:
            assert e["category"] == "momentum"

    def test_cmd_unified_list_output(self):
        """CLI 辅助函数输出"""
        output = cmd_unified_list()
        assert "统一因子视图" in output
        assert "因子总数" in output or "Alpha" in output or "统一因子视图" in output

    def test_cmd_sync_dry_run_output(self):
        """CLI 同步 dry-run 输出"""
        output = cmd_sync(dry_run=True)
        assert "同步" in output
        assert "将同步" in output or "已同步" in output or "Dry" in output

    def test_alpha_to_factors_sync(self):
        """alpha → factor 反向同步不崩溃"""
        count = sync_alpha_to_factors()
        assert isinstance(count, int)
        assert count >= 0

    def test_sync_idempotent(self):
        """dry-run 两次结果一致"""
        r1 = sync_factors_to_alpha(dry_run=True)
        r2 = sync_factors_to_alpha(dry_run=True)
        assert r1["synced"] == r2["synced"]
