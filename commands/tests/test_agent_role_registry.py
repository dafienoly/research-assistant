"""V8.0 Agent Role Registry — Tests

Covers:
  - AgentRoleSpec creation and validation
  - Role assignment and completion
  - AgentRoleRegistry CRUD (register, list, get, delete)
  - Capability-based discovery
  - Backend matching
  - Standard role seeding
  - Assignment tracking and stats
  - Edge cases (duplicate role, invalid capability, not found)
  - Concurrency limits
  - Persistence across reloads
"""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

from factor_lab.leader.agent_role_registry import (
    AgentRoleSpec, RoleAssignment, AgentRoleRegistry,
    validate_role_spec, init_registry,
    Capability, STANDARD_ROLES, VALID_CAPABILITIES,
)

CST = timezone(timedelta(hours=8))


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture()
def isolated_registry(tmp_path, monkeypatch):
    """将注册表根目录重定向到临时目录"""
    from factor_lab.leader import agent_role_registry as reg_mod

    test_root = tmp_path / "agent_role_registry"
    monkeypatch.setattr(reg_mod, "REGISTRY_ROOT", test_root)
    yield AgentRoleRegistry(root=test_root)


@pytest.fixture()
def seeded_registry(isolated_registry):
    """预填充标准角色的注册表"""
    isolated_registry.seed_defaults()
    return isolated_registry


@pytest.fixture()
def sample_spec():
    return AgentRoleSpec(
        role_id="test-role",
        name="Test Role",
        description="A role for testing",
        capabilities=[Capability.WRITE_TEST, Capability.REVIEW_CODE],
        responsibilities=["Write tests", "Review code"],
        constraints=["No production access"],
        allowed_backends=["dry-run"],
        max_concurrent_tasks=2,
        auto_assignable=True,
    )


# =========================================================================
# AgentRoleSpec Tests
# =========================================================================

class TestAgentRoleSpec:
    def test_create_minimal_spec(self):
        """最简创建应自动填充时间戳"""
        spec = AgentRoleSpec(role_id="minimal", name="Min", description="Minimal role")
        assert spec.role_id == "minimal"
        assert spec.created_at != ""
        assert spec.updated_at != ""
        assert spec.capabilities == []
        assert spec.max_concurrent_tasks == 1
        assert spec.auto_assignable is True

    def test_create_full_spec(self, sample_spec):
        assert sample_spec.role_id == "test-role"
        assert sample_spec.name == "Test Role"
        assert Capability.WRITE_TEST in sample_spec.capabilities
        assert sample_spec.max_concurrent_tasks == 2

    def test_to_dict_roundtrip(self, sample_spec):
        d = sample_spec.to_dict()
        assert d["role_id"] == "test-role"
        assert d["name"] == "Test Role"
        assert d["capabilities"] == [Capability.WRITE_TEST, Capability.REVIEW_CODE]
        restored = AgentRoleSpec.from_dict(d)
        assert restored.role_id == sample_spec.role_id
        assert restored.capabilities == sample_spec.capabilities

    def test_from_dict_preserves_all_fields(self, sample_spec):
        d = sample_spec.to_dict()
        restored = AgentRoleSpec.from_dict(d)
        for k, v in d.items():
            assert getattr(restored, k) == v, f"Field {k} mismatch"

    def test_created_at_auto_fill(self):
        """未传 created_at 应自动填充"""
        spec = AgentRoleSpec(role_id="auto", name="Auto", description="Auto")
        assert spec.created_at != ""
        # Pass explicit created_at
        explicit = "2026-01-01T00:00:00+08:00"
        spec2 = AgentRoleSpec(role_id="manual", name="Manual", description="Manual", created_at=explicit)
        assert spec2.created_at == explicit


# =========================================================================
# RoleAssignment Tests
# =========================================================================

class TestRoleAssignment:
    def test_create_assignment(self):
        a = RoleAssignment(
            assignment_id="a1",
            role_id="developer",
            task_id="T001",
            task_desc="Implement feature",
            backend="claude",
        )
        assert a.assignment_id == "a1"
        assert a.role_id == "developer"
        assert a.status == "assigned"
        assert a.assigned_at != ""

    def test_assignment_to_dict(self):
        a = RoleAssignment("a1", "pm", "T001", "Plan sprint", backend="dry-run")
        d = a.to_dict()
        assert d["assignment_id"] == "a1"
        assert d["status"] == "assigned"
        restored = RoleAssignment.from_dict(d)
        assert restored.assignment_id == "a1"


# =========================================================================
# Validation Tests
# =========================================================================

class TestValidation:
    def test_valid_spec_passes(self, sample_spec):
        errors = validate_role_spec(sample_spec)
        assert errors == []

    def test_empty_role_id_fails(self):
        spec = AgentRoleSpec(role_id="", name="X", description="X")
        errors = validate_role_spec(spec)
        assert any("role_id" in e for e in errors)

    def test_empty_name_fails(self):
        spec = AgentRoleSpec(role_id="x", name="", description="X")
        errors = validate_role_spec(spec)
        assert any("name" in e for e in errors)

    def test_empty_description_fails(self, sample_spec):
        spec = AgentRoleSpec(role_id="x", name="X", description="")
        errors = validate_role_spec(spec)
        assert any("description" in e for e in errors)

    def test_unknown_capability_fails(self):
        spec = AgentRoleSpec(
            role_id="x", name="X", description="X",
            capabilities=["invalid:capability"],
        )
        errors = validate_role_spec(spec)
        assert any("unknown capability" in e for e in errors)

    def test_valid_capabilities_all_known(self):
        """VALID_CAPABILITIES 集合中的所有能力都应该是字符串"""
        for cap in VALID_CAPABILITIES:
            assert isinstance(cap, str)
        assert len(VALID_CAPABILITIES) >= 20


# =========================================================================
# AgentRoleRegistry Tests — CRUD
# =========================================================================

class TestRegistryCRUD:
    def test_register_returns_ok(self, isolated_registry, sample_spec):
        result = isolated_registry.register(sample_spec)
        assert result["status"] == "ok"
        assert result["role_id"] == "test-role"

    def test_register_invalid_returns_error(self, isolated_registry):
        spec = AgentRoleSpec(role_id="", name="", description="")
        result = isolated_registry.register(spec)
        assert result["status"] == "error"
        assert "errors" in result

    def test_register_duplicate_overwrites(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        spec2 = AgentRoleSpec(
            role_id="test-role", name="Updated", description="Updated",
        )
        result = isolated_registry.register(spec2)
        assert result["status"] == "ok"
        got = isolated_registry.get("test-role")
        assert got is not None
        assert got.name == "Updated"

    def test_list_returns_all(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        spec2 = AgentRoleSpec(role_id="role2", name="Role2", description="Second role")
        isolated_registry.register(spec2)
        roles = isolated_registry.list()
        assert len(roles) == 2

    def test_list_sorted_by_role_id(self, isolated_registry):
        spec_b = AgentRoleSpec(role_id="b-role", name="B", description="B role")
        spec_a = AgentRoleSpec(role_id="a-role", name="A", description="A role")
        isolated_registry.register(spec_b)
        isolated_registry.register(spec_a)
        roles = isolated_registry.list()
        assert roles[0]["role_id"] == "a-role"

    def test_get_existing(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        got = isolated_registry.get("test-role")
        assert got is not None
        assert got.role_id == "test-role"

    def test_get_nonexistent(self, isolated_registry):
        assert isolated_registry.get("nonexistent") is None

    def test_delete_existing(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        result = isolated_registry.delete("test-role")
        assert result["status"] == "ok"
        assert isolated_registry.get("test-role") is None

    def test_delete_nonexistent(self, isolated_registry):
        result = isolated_registry.delete("nonexistent")
        assert result["status"] == "error"


# =========================================================================
# Capability Discovery
# =========================================================================

class TestCapabilityDiscovery:
    def test_find_by_capability_matches(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        results = isolated_registry.find_by_capability(Capability.WRITE_TEST)
        assert len(results) == 1
        assert results[0]["role_id"] == "test-role"

    def test_find_by_capability_no_match(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        results = isolated_registry.find_by_capability(Capability.DESIGN_ARCH)
        assert len(results) == 0

    def test_find_by_backend(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        results = isolated_registry.find_by_backend("dry-run")
        assert len(results) == 1
        results = isolated_registry.find_by_backend("claude")
        assert len(results) == 0  # sample_spec only allows dry-run

    def test_has_capability_true(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        assert isolated_registry.has_capability("test-role", Capability.WRITE_TEST) is True

    def test_has_capability_false(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        assert isolated_registry.has_capability("test-role", Capability.FIX_BUG) is False

    def test_has_capability_role_not_found(self, isolated_registry):
        assert isolated_registry.has_capability("ghost", Capability.WRITE_TEST) is False

    def test_list_with_capability_filter(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        spec2 = AgentRoleSpec(
            role_id="dev-only", name="Dev", description="Dev only",
            capabilities=[Capability.IMPLEMENT_CODE, Capability.FIX_BUG],
        )
        isolated_registry.register(spec2)
        results = isolated_registry.list(capability=Capability.FIX_BUG)
        assert len(results) == 1
        assert results[0]["role_id"] == "dev-only"


# =========================================================================
# Backend Matching
# =========================================================================

class TestBackendMatching:
    def test_match_backend_default(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        result = isolated_registry.match_backend("test-role")
        assert result["selected_backend"] == "dry-run"  # only backend in allowed

    def test_match_backend_with_preferred(self, isolated_registry):
        spec = AgentRoleSpec(
            role_id="multi", name="Multi", description="Multi backend",
            allowed_backends=["claude", "dry-run", "codex"],
        )
        isolated_registry.register(spec)
        result = isolated_registry.match_backend("multi", preferred="codex")
        assert result["selected_backend"] == "codex"

    def test_match_backend_fallback(self, isolated_registry):
        spec = AgentRoleSpec(
            role_id="multi", name="Multi", description="Multi backend",
            allowed_backends=["codex"],
        )
        isolated_registry.register(spec)
        result = isolated_registry.match_backend("multi", preferred="nonexistent")
        assert result["selected_backend"] == "codex"  # falls back to first available

    def test_match_backend_priority_order(self, isolated_registry):
        """应优先选择 claude > dry-run > 其他"""
        spec = AgentRoleSpec(
            role_id="multi", name="Multi", description="Multi backend",
            allowed_backends=["codex", "dry-run"],
        )
        isolated_registry.register(spec)
        result = isolated_registry.match_backend("multi")
        assert result["selected_backend"] == "dry-run"  # dry-run higher priority than codex

    def test_match_backend_no_backends(self, isolated_registry):
        spec = AgentRoleSpec(
            role_id="empty", name="Empty", description="No backends",
            allowed_backends=[],
        )
        isolated_registry.register(spec)
        result = isolated_registry.match_backend("empty")
        assert result["selected_backend"] == "dry-run"  # fallback

    def test_match_backend_role_not_found(self, isolated_registry):
        result = isolated_registry.match_backend("ghost")
        assert "error" in result


# =========================================================================
# Role Assignment
# =========================================================================

class TestRoleAssignmentRegistry:
    def test_assign_role_ok(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        result = isolated_registry.assign_role("test-role", "T001", "Test task")
        assert result["status"] == "ok"
        assert result["assignment"]["role_id"] == "test-role"
        assert result["assignment"]["task_id"] == "T001"

    def test_assign_role_not_found(self, isolated_registry):
        result = isolated_registry.assign_role("ghost", "T001")
        assert result["status"] == "error"

    def test_assign_role_not_auto_assignable(self, isolated_registry):
        spec = AgentRoleSpec(
            role_id="manual-only", name="Manual", description="Manual only",
            auto_assignable=False,
        )
        isolated_registry.register(spec)
        result = isolated_registry.assign_role("manual-only", "T001")
        assert result["status"] == "error"
        assert "not auto-assignable" in result["error"]

    def test_assign_role_concurrency_limit(self, isolated_registry):
        spec = AgentRoleSpec(
            role_id="limited", name="Limited", description="Max 1 concurrent",
            max_concurrent_tasks=1,
            auto_assignable=True,
        )
        isolated_registry.register(spec)
        # First assignment
        r1 = isolated_registry.assign_role("limited", "T001")
        assert r1["status"] == "ok"
        # Manually set first to running
        a_id = r1["assignment"]["assignment_id"]
        isolated_registry.complete_assignment(a_id, "running")
        # Second should exceed limit
        r2 = isolated_registry.assign_role("limited", "T002")
        assert r2["status"] == "error"
        assert "max concurrent" in r2["error"]

    def test_complete_assignment_ok(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        r = isolated_registry.assign_role("test-role", "T001")
        a_id = r["assignment"]["assignment_id"]
        result = isolated_registry.complete_assignment(a_id, "completed")
        assert result["status"] == "ok"
        assert result["assignment"]["status"] == "completed"
        assert result["assignment"]["completed_at"] != ""

    def test_complete_assignment_not_found(self, isolated_registry):
        result = isolated_registry.complete_assignment("ghost")
        assert result["status"] == "error"

    def test_list_assignments_empty(self, isolated_registry):
        assert isolated_registry.list_assignments() == []

    def test_list_assignments_filter_by_role(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        isolated_registry.assign_role("test-role", "T001")
        isolated_registry.assign_role("test-role", "T002")
        spec2 = AgentRoleSpec(role_id="other", name="Other", description="Other role")
        isolated_registry.register(spec2)
        isolated_registry.assign_role("other", "T003")
        results = isolated_registry.list_assignments(role_id="test-role")
        assert len(results) == 2

    def test_list_assignments_filter_by_status(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        r = isolated_registry.assign_role("test-role", "T001")
        a_id = r["assignment"]["assignment_id"]
        isolated_registry.complete_assignment(a_id, "completed")
        isolated_registry.assign_role("test-role", "T002")
        completed = isolated_registry.list_assignments(status="completed")
        assert len(completed) == 1
        assigned = isolated_registry.list_assignments(status="assigned")
        assert len(assigned) == 1


# =========================================================================
# Standard Roles
# =========================================================================

class TestStandardRoles:
    def test_seed_defaults_count(self, isolated_registry):
        count = isolated_registry.seed_defaults()
        assert count == len(STANDARD_ROLES)

    def test_seed_defaults_idempotent(self, isolated_registry):
        count1 = isolated_registry.seed_defaults()
        count2 = isolated_registry.seed_defaults()
        assert count2 == 0  # 第二次不应新增
        all_roles = isolated_registry.list()
        assert len(all_roles) == count1

    def test_pm_role_has_expected_capabilities(self, seeded_registry):
        pm = seeded_registry.get("pm")
        assert pm is not None
        assert pm.name == "Project Manager"
        assert Capability.PLAN_TASK in pm.capabilities
        assert Capability.ASSIGN_ROLE in pm.capabilities

    def test_pm_role_cannot_modify_code(self, seeded_registry):
        pm = seeded_registry.get("pm")
        assert Capability.IMPLEMENT_CODE not in pm.capabilities

    def test_developer_role_has_expected_capabilities(self, seeded_registry):
        dev = seeded_registry.get("developer")
        assert dev is not None
        assert dev.name == "Developer"
        assert Capability.IMPLEMENT_CODE in dev.capabilities
        assert Capability.FIX_BUG in dev.capabilities

    def test_developer_requires_approval(self, seeded_registry):
        dev = seeded_registry.get("developer")
        assert dev.requires_approval is True

    def test_architect_role_no_direct_implement(self, seeded_registry):
        arch = seeded_registry.get("architect")
        assert arch is not None
        assert Capability.DESIGN_ARCH in arch.capabilities
        assert Capability.IMPLEMENT_CODE not in arch.capabilities

    def test_tester_role_no_production_code(self, seeded_registry):
        tester = seeded_registry.get("tester")
        assert tester is not None
        assert Capability.TEST_UNIT in tester.capabilities
        assert Capability.IMPLEMENT_CODE not in tester.capabilities

    def test_auditor_role_verify_acceptance(self, seeded_registry):
        auditor = seeded_registry.get("auditor")
        assert auditor is not None
        assert Capability.VERIFY_ACCEPTANCE in auditor.capabilities
        assert Capability.IMPLEMENT_CODE not in auditor.capabilities

    def test_all_standard_roles_have_required_fields(self, seeded_registry):
        for role_id in STANDARD_ROLES:
            spec = seeded_registry.get(role_id)
            assert spec is not None, f"{role_id} not found"
            assert spec.description != ""
            assert len(spec.capabilities) > 0
            assert len(spec.responsibilities) > 0
            assert len(spec.allowed_backends) > 0

    def test_standard_roles_have_valid_capabilities(self, seeded_registry):
        for role_id in STANDARD_ROLES:
            spec = seeded_registry.get(role_id)
            for cap in spec.capabilities:
                assert cap in VALID_CAPABILITIES, f"{role_id}: unknown capability {cap}"


# =========================================================================
# init_registry
# =========================================================================

class TestInitRegistry:
    def test_init_registry_returns_seeded(self, tmp_path, monkeypatch):
        from factor_lab.leader import agent_role_registry as reg_mod
        test_root = tmp_path / "agent_role_registry"
        monkeypatch.setattr(reg_mod, "REGISTRY_ROOT", test_root)
        registry = init_registry()
        assert isinstance(registry, AgentRoleRegistry)
        roles = registry.list()
        assert len(roles) == len(STANDARD_ROLES)

    def test_init_registry_idempotent(self, tmp_path, monkeypatch):
        from factor_lab.leader import agent_role_registry as reg_mod
        test_root = tmp_path / "agent_role_registry"
        monkeypatch.setattr(reg_mod, "REGISTRY_ROOT", test_root)
        r1 = init_registry()
        r2 = init_registry()
        assert len(r1.list()) == len(r2.list())


# =========================================================================
# Statistics
# =========================================================================

class TestStatistics:
    def test_stats_empty_registry(self, isolated_registry):
        s = isolated_registry.stats()
        assert s["total_roles"] == 0
        assert s["total_assignments"] == 0

    def test_stats_with_roles_and_assignments(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        isolated_registry.assign_role("test-role", "T001")
        s = isolated_registry.stats()
        assert s["total_roles"] == 1
        assert s["total_assignments"] == 1
        assert s["active_assignments"] == 0  # assigned != running
        # Complete and check
        r = isolated_registry.assign_role("test-role", "T002")
        a_id = r["assignment"]["assignment_id"]
        isolated_registry.complete_assignment(a_id, "running")
        s2 = isolated_registry.stats()
        assert s2["active_assignments"] == 1

    def test_stats_roles_by_backend(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        s = isolated_registry.stats()
        assert "dry-run" in s["roles_by_backend"]

    def test_stats_with_standard_roles(self, seeded_registry):
        s = seeded_registry.stats()
        assert s["total_roles"] == len(STANDARD_ROLES)
        # 所有角色都有 dry-run 后端
        assert s["roles_by_backend"].get("dry-run", 0) == len(STANDARD_ROLES)


# =========================================================================
# Persistence
# =========================================================================

class TestPersistence:
    def test_persistence_across_reload(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        isolated_registry.assign_role("test-role", "T001")
        # Create new registry pointing to same root
        registry2 = AgentRoleRegistry(root=isolated_registry.root)
        assert registry2.get("test-role") is not None
        roles = registry2.list()
        assert len(roles) == 1

    def test_persistence_with_assignments(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        r = isolated_registry.assign_role("test-role", "T001")
        a_id = r["assignment"]["assignment_id"]
        isolated_registry.complete_assignment(a_id, "completed")
        # Reload
        registry2 = AgentRoleRegistry(root=isolated_registry.root)
        assigns = registry2.list_assignments()
        assert len(assigns) >= 1
        completed = [a for a in assigns if a["status"] == "completed"]
        assert len(completed) >= 1

    def test_persistence_empty_root(self, tmp_path):
        empty_root = tmp_path / "empty"
        registry = AgentRoleRegistry(root=empty_root)
        assert registry.list() == []


# =========================================================================
# Edge Cases
# =========================================================================

class TestEdgeCases:
    def test_role_with_no_capabilities(self, isolated_registry):
        spec = AgentRoleSpec(
            role_id="no-cap", name="No Cap", description="No capabilities",
            capabilities=[], auto_assignable=True,
        )
        result = isolated_registry.register(spec)
        assert result["status"] == "ok"
        assert len(spec.capabilities) == 0

    def test_assignment_with_empty_task_desc(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        result = isolated_registry.assign_role("test-role", "T001")
        assert result["status"] == "ok"

    def test_list_with_invalid_capability_filter(self, isolated_registry):
        """不存在的能力参数应返回空列表"""
        results = isolated_registry.list(capability="nonexistent:cap")
        assert results == []

    def test_disallowed_backend_in_match(self, isolated_registry):
        spec = AgentRoleSpec(
            role_id="strict", name="Strict", description="Strict backends",
            allowed_backends=["dry-run"],
        )
        isolated_registry.register(spec)
        result = isolated_registry.match_backend("strict", preferred="claude")
        assert result["selected_backend"] == "dry-run"  # 不应选 claude

    def test_delete_persists_removal(self, isolated_registry, sample_spec):
        isolated_registry.register(sample_spec)
        isolated_registry.delete("test-role")
        registry2 = AgentRoleRegistry(root=isolated_registry.root)
        assert registry2.get("test-role") is None
