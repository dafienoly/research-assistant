"""V6.0 Research Skill Runtime — Tests

Covers:
  - SkillSpec creation and validation
  - SkillParam creation
  - SkillRegistry CRUD (register, list, get, delete)
  - SkillRuntime execution
  - Parameter validation (types, defaults, required, choices)
  - Built-in skill registration
  - Error handling (missing skill, missing execute, timeout)
  - Edge cases (empty params, invalid params)
  - Run history and persistence
"""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

from factor_lab.research_skill.skill_spec import (
    SkillSpec, SkillParam, SkillCategory, SkillStatus, SkillResult,
    validate_spec, VALID_CATEGORIES,
)
from factor_lab.research_skill.skill_registry import SkillRegistry, init_registry
from factor_lab.research_skill.skill_runtime import SkillRuntime, ResearchContext
from factor_lab.research_skill.builtins import BUILTIN_SKILLS

CST = timezone(timedelta(hours=8))


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture()
def isolated_registry(tmp_path, monkeypatch):
    """将注册表根目录重定向到临时目录"""
    from factor_lab.research_skill import skill_registry as reg_mod
    from factor_lab.research_skill import skill_runtime as run_mod

    test_root = tmp_path / "skill_registry"
    monkeypatch.setattr(reg_mod, "REGISTRY_ROOT", test_root)
    monkeypatch.setattr(run_mod, "RUNTIME_ROOT", tmp_path / "skill_runs")

    yield SkillRegistry(root=test_root)


@pytest.fixture()
def seeded_registry(isolated_registry):
    """预填充内置 Skills 的注册表"""
    isolated_registry.seed_defaults(BUILTIN_SKILLS)
    return isolated_registry


@pytest.fixture()
def isolated_runtime(isolated_registry, monkeypatch, tmp_path):
    """隔离的 SkillRuntime"""
    from factor_lab.research_skill import skill_runtime as run_mod
    run_root = tmp_path / "skill_runs"
    monkeypatch.setattr(run_mod, "RUNTIME_ROOT", run_root)
    return SkillRuntime(registry=isolated_registry, runtime_root=run_root)


# =========================================================================
# SkillSpec Tests
# =========================================================================

class TestSkillSpec:

    def test_create_minimal(self):
        spec = SkillSpec(
            skill_id="test-skill",
            name="测试 Skill",
            description="A test skill",
        )
        assert spec.skill_id == "test-skill"
        assert spec.name == "测试 Skill"
        assert spec.category == SkillCategory.ANALYSIS.value
        assert spec.version == "1.0.0"
        assert spec.created_at
        assert spec.updated_at

    def test_create_with_params(self):
        spec = SkillSpec(
            skill_id="param-skill",
            name="Param Skill",
            description="Skill with params",
            category=SkillCategory.DATA.value,
            params=[
                SkillParam(name="limit", type="int", label="Limit", default=10),
                SkillParam(name="verbose", type="bool", label="Verbose", default=False),
            ],
            tags=["data", "test"],
        )
        assert len(spec.params) == 2
        assert spec.params[0].name == "limit"
        assert spec.params[0].type == "int"
        assert spec.params[1].name == "verbose"
        assert spec.params[1].type == "bool"

    def test_to_dict_serialization(self):
        spec = SkillSpec(
            skill_id="test",
            name="Test",
            description="Test skill",
            params=[SkillParam(name="p1", type="string", label="P1")],
            tags=["tag1"],
        )
        d = spec.to_dict()
        assert d["skill_id"] == "test"
        assert d["name"] == "Test"
        assert len(d["params"]) == 1
        assert d["params"][0]["name"] == "p1"
        assert "execute" in d  # empty string for None

    def test_from_dict_roundtrip(self):
        original = SkillSpec(
            skill_id="roundtrip",
            name="Round Trip",
            description="Test roundtrip",
            category=SkillCategory.MONITOR.value,
            params=[SkillParam(name="x", type="float", label="X Factor", default=1.5)],
            tags=["test"],
        )
        d = original.to_dict()
        restored = SkillSpec.from_dict(d)
        assert restored.skill_id == original.skill_id
        assert restored.name == original.name
        assert restored.category == original.category
        assert len(restored.params) == 1
        assert restored.params[0].name == "x"
        assert restored.params[0].default == 1.5

    def test_validate_valid(self):
        spec = SkillSpec(
            skill_id="valid-skill",
            name="Valid Skill",
            description="A valid skill",
            category=SkillCategory.ANALYSIS.value,
            params=[SkillParam(name="p1", type="string", label="P1")],
        )
        errors = validate_spec(spec)
        assert errors == []

    def test_validate_missing_skill_id(self):
        spec = SkillSpec(skill_id="", name="Bad", description="Bad")
        errors = validate_spec(spec)
        assert any("skill_id" in e for e in errors)

    def test_validate_missing_name(self):
        spec = SkillSpec(skill_id="test", name="", description="Bad")
        errors = validate_spec(spec)
        assert any("name" in e for e in errors)

    def test_validate_missing_description(self):
        spec = SkillSpec(skill_id="test", name="Test", description="")
        errors = validate_spec(spec)
        assert any("description" in e for e in errors)

    def test_validate_invalid_category(self):
        spec = SkillSpec(
            skill_id="test", name="Test", description="Test",
            category="invalid_category",
        )
        errors = validate_spec(spec)
        assert any("category" in e for e in errors)

    def test_validate_invalid_param_type(self):
        spec = SkillSpec(
            skill_id="test", name="Test", description="Test",
            params=[SkillParam(name="p1", type="invalid_type", label="P1")],
        )
        errors = validate_spec(spec)
        assert any("param type" in e for e in errors)


# =========================================================================
# SkillRegistry Tests
# =========================================================================

class TestSkillRegistry:

    def test_register_and_list(self, isolated_registry):
        spec = SkillSpec(
            skill_id="my-skill",
            name="My Skill",
            description="A test skill",
            category=SkillCategory.ANALYSIS.value,
            tags=["test"],
        )
        result = isolated_registry.register(spec)
        assert result["status"] == "ok"
        assert result["skill_id"] == "my-skill"

        skills = isolated_registry.list()
        assert len(skills) == 1
        assert skills[0]["skill_id"] == "my-skill"

    def test_register_invalid(self, isolated_registry):
        spec = SkillSpec(skill_id="", name="", description="")
        result = isolated_registry.register(spec)
        assert result["status"] == "error"
        assert len(result["errors"]) > 0

    def test_get(self, isolated_registry):
        spec = SkillSpec(
            skill_id="get-test",
            name="Get Test",
            description="Test get",
        )
        isolated_registry.register(spec)
        retrieved = isolated_registry.get("get-test")
        assert retrieved is not None
        assert retrieved.skill_id == "get-test"

    def test_get_unknown(self, isolated_registry):
        retrieved = isolated_registry.get("nonexistent")
        assert retrieved is None

    def test_delete(self, isolated_registry):
        spec = SkillSpec(
            skill_id="del-test",
            name="Delete Test",
            description="Test delete",
        )
        isolated_registry.register(spec)
        result = isolated_registry.delete("del-test")
        assert result["status"] == "ok"
        assert isolated_registry.get("del-test") is None

    def test_delete_unknown(self, isolated_registry):
        result = isolated_registry.delete("nonexistent")
        assert result["status"] == "error"

    def test_list_filter_by_category(self, isolated_registry):
        _register_sample(isolated_registry)
        analysis = isolated_registry.list(category="analysis")
        data = isolated_registry.list(category="data")
        assert len(analysis) >= 2
        assert len(data) == 1
        assert all(s["category"] == "analysis" for s in analysis)

    def test_list_filter_by_tag(self, isolated_registry):
        _register_sample(isolated_registry)
        tagged = isolated_registry.list(tag="test")
        assert len(tagged) > 0

    def test_list_empty(self, isolated_registry):
        skills = isolated_registry.list()
        assert skills == []

    def test_count_by_category(self, isolated_registry):
        _register_sample(isolated_registry)
        counts = isolated_registry.count_by_category()
        assert "analysis" in counts
        assert counts["analysis"] >= 2

    def test_seed_defaults(self, isolated_registry):
        count = isolated_registry.seed_defaults(BUILTIN_SKILLS)
        assert count == len(BUILTIN_SKILLS)
        skills = isolated_registry.list()
        assert len(skills) == len(BUILTIN_SKILLS)

    def test_seed_defaults_idempotent(self, isolated_registry):
        isolated_registry.seed_defaults(BUILTIN_SKILLS)
        count = isolated_registry.seed_defaults(BUILTIN_SKILLS)
        assert count == 0  # no new skills added

    def test_persistence(self, isolated_registry):
        """Skills survive registry reload"""
        spec = SkillSpec(
            skill_id="persist-test",
            name="Persistence",
            description="Should survive reload",
        )
        isolated_registry.register(spec)

        # Create new registry instance with same root
        registry2 = SkillRegistry(root=isolated_registry.root)
        assert registry2.get("persist-test") is not None
        assert registry2.get("persist-test").name == "Persistence"

    def test_init_registry(self, tmp_path, monkeypatch):
        from factor_lab.research_skill import skill_registry as reg_mod
        monkeypatch.setattr(reg_mod, "REGISTRY_ROOT", tmp_path / "skill_registry")

        registry = init_registry(builtins=BUILTIN_SKILLS[:2])
        skills = registry.list()
        assert len(skills) == 2


def _register_sample(registry):
    """Helper: register sample skills for list/filter tests"""
    registry.register(SkillSpec(
        skill_id="sample-analysis",
        name="Analysis Skill",
        description="An analysis skill",
        category=SkillCategory.ANALYSIS.value,
        tags=["test", "analysis"],
    ))
    registry.register(SkillSpec(
        skill_id="sample-analysis-2",
        name="Analysis Skill 2",
        description="Another analysis skill",
        category=SkillCategory.ANALYSIS.value,
        tags=["test"],
    ))
    registry.register(SkillSpec(
        skill_id="sample-data",
        name="Data Skill",
        description="A data skill",
        category=SkillCategory.DATA.value,
        tags=["test", "data"],
    ))


# =========================================================================
# SkillRuntime Tests
# =========================================================================

class TestSkillRuntime:

    def test_run_basic(self, isolated_runtime):
        """Run a simple skill with no params"""
        isolated_runtime.registry.register(SkillSpec(
            skill_id="hello",
            name="Hello",
            description="Simple hello skill",
            execute=lambda ctx, params: {"message": "hello world"},
        ))
        result = isolated_runtime.run("hello")
        assert result.status == SkillStatus.COMPLETED.value
        assert result.data.get("message") == "hello world"
        assert result.duration_ms >= 0  # fast executions may be near-zero
        assert result.run_id
        assert result.started_at
        assert result.completed_at

    def test_run_with_params(self, isolated_runtime):
        """Run a skill with parameter passing"""
        def _execute(ctx, params):
            return {"received": params, "limit": params.get("limit")}

        isolated_runtime.registry.register(SkillSpec(
            skill_id="with-params",
            name="With Params",
            description="Skill that uses params",
            params=[SkillParam(name="limit", type="int", label="Limit", default=10)],
            execute=_execute,
        ))
        result = isolated_runtime.run("with-params", {"limit": 42})
        assert result.status == SkillStatus.COMPLETED.value
        assert result.data["received"]["limit"] == 42

    def test_run_uses_defaults(self, isolated_runtime):
        """Missing optional params use defaults"""
        def _execute(ctx, params):
            return {"limit": params.get("limit"), "name": params.get("name", "default_name")}

        isolated_runtime.registry.register(SkillSpec(
            skill_id="defaults",
            name="Defaults",
            description="Uses defaults",
            params=[
                SkillParam(name="limit", type="int", label="Limit", default=100),
                SkillParam(name="name", type="string", label="Name", default="default_name"),
            ],
            execute=_execute,
        ))
        result = isolated_runtime.run("defaults", {})
        assert result.status == SkillStatus.COMPLETED.value
        assert result.data["limit"] == 100
        assert result.data["name"] == "default_name"

    def test_run_missing_required_param(self, isolated_runtime):
        """Missing required param returns error"""
        isolated_runtime.registry.register(SkillSpec(
            skill_id="requires-param",
            name="Requires Param",
            description="Required param test",
            params=[SkillParam(name="required_field", type="string", label="Required", required=True)],
            execute=lambda ctx, params: {"ok": True},
        ))
        result = isolated_runtime.run("requires-param", {})
        assert result.status == SkillStatus.FAILED.value
        assert "required parameter" in result.error

    def test_run_unknown_skill(self, isolated_runtime):
        """Unknown skill returns error"""
        result = isolated_runtime.run("nonexistent")
        assert result.status == SkillStatus.FAILED.value
        assert "not found" in result.error

    def test_run_no_execute_function(self, isolated_runtime):
        """Skill without execute function returns error"""
        isolated_runtime.registry.register(SkillSpec(
            skill_id="no-exec",
            name="No Exec",
            description="No execute function",
            execute=None,
        ))
        result = isolated_runtime.run("no-exec")
        assert result.status == SkillStatus.FAILED.value
        assert "no execute function" in result.error

    def test_run_skill_that_raises(self, isolated_runtime):
        """Skill that raises an exception returns failed"""
        def _broken(ctx, params):
            raise ValueError("something went wrong")

        isolated_runtime.registry.register(SkillSpec(
            skill_id="broken",
            name="Broken",
            description="Broken skill",
            execute=_broken,
        ))
        result = isolated_runtime.run("broken")
        assert result.status == SkillStatus.FAILED.value
        assert "ValueError" in result.error

    def test_param_type_conversion(self, isolated_runtime):
        """Parameters are auto-converted to the declared type"""

        def _check(ctx, params):
            return {
                "int_val": type(params["int_val"]).__name__,
                "float_val": type(params["float_val"]).__name__,
                "bool_val": type(params["bool_val"]).__name__,
                "list_val": type(params["list_val"]).__name__,
            }

        isolated_runtime.registry.register(SkillSpec(
            skill_id="type-check",
            name="Type Check",
            description="Type conversion check",
            params=[
                SkillParam(name="int_val", type="int", label="Int"),
                SkillParam(name="float_val", type="float", label="Float"),
                SkillParam(name="bool_val", type="bool", label="Bool"),
                SkillParam(name="list_val", type="list", label="List"),
            ],
            execute=_check,
        ))
        result = isolated_runtime.run("type-check", {
            "int_val": "42",
            "float_val": "3.14",
            "bool_val": "true",
            "list_val": "a,b,c",
        })
        assert result.status == SkillStatus.COMPLETED.value
        assert result.data["int_val"] == "int"
        assert result.data["float_val"] == "float"
        assert result.data["bool_val"] == "bool"
        assert result.data["list_val"] == "list"

    def test_choices_validation(self, isolated_runtime):
        """Parameter choices are enforced"""

        isolated_runtime.registry.register(SkillSpec(
            skill_id="choices-test",
            name="Choices",
            description="Choices validation",
            params=[SkillParam(
                name="mode", type="string", label="Mode",
                choices=["fast", "slow"],
            )],
            execute=lambda ctx, params: {"mode": params["mode"]},
        ))
        # Valid choice
        result = isolated_runtime.run("choices-test", {"mode": "fast"})
        assert result.status == SkillStatus.COMPLETED.value

        # Invalid choice
        result = isolated_runtime.run("choices-test", {"mode": "invalid"})
        assert result.status == SkillStatus.FAILED.value
        assert "must be one of" in result.error

    def test_run_many(self, isolated_runtime):
        """Sequential execution of multiple skills"""
        isolated_runtime.registry.register(SkillSpec(
            skill_id="first", name="First", description="First",
            execute=lambda ctx, p: {"order": 1},
        ))
        isolated_runtime.registry.register(SkillSpec(
            skill_id="second", name="Second", description="Second",
            execute=lambda ctx, p: {"order": 2},
        ))
        results = isolated_runtime.run_many(["first", "second"])
        assert len(results) == 2
        assert results[0].data["order"] == 1
        assert results[1].data["order"] == 2

    def test_run_with_research_context(self, isolated_runtime):
        """ResearchContext is passed to the skill"""

        def _check_ctx(ctx, params):
            return {
                "run_id": ctx.run_id,
                "start_date": ctx.start_date,
                "end_date": ctx.end_date,
                "symbols": ctx.symbols,
                "extra": ctx.extra,
            }

        isolated_runtime.registry.register(SkillSpec(
            skill_id="ctx-test",
            name="Context Test",
            description="Context check",
            execute=_check_ctx,
        ))
        ctx = ResearchContext(
            run_id="custom-run-001",
            start_date="2026-01-01",
            end_date="2026-06-30",
            symbols=["000001", "600519"],
            extra={"source": "test"},
        )
        result = isolated_runtime.run("ctx-test", context=ctx)
        assert result.status == SkillStatus.COMPLETED.value
        assert result.data["run_id"] == "custom-run-001"
        assert result.data["start_date"] == "2026-01-01"
        assert result.data["symbols"] == ["000001", "600519"]


# =========================================================================
# Run History Tests
# =========================================================================

class TestRunHistory:

    def test_run_is_persisted(self, isolated_runtime):
        isolated_runtime.registry.register(SkillSpec(
            skill_id="persist-run",
            name="Persist Run",
            description="Check persistence",
            execute=lambda ctx, p: {"ok": True},
        ))
        result = isolated_runtime.run("persist-run")
        saved = isolated_runtime.get_run(result.run_id)
        assert saved is not None
        assert saved["skill_id"] == "persist-run"
        assert saved["status"] == SkillStatus.COMPLETED.value
        assert saved["duration_ms"] >= 0  # fast executions may be near-zero

    def test_list_runs(self, isolated_runtime):
        isolated_runtime.registry.register(SkillSpec(
            skill_id="list-me",
            name="List Me",
            description="List test",
            execute=lambda ctx, p: {"ok": True},
        ))
        r1 = isolated_runtime.run("list-me")
        r2 = isolated_runtime.run("list-me")
        runs = isolated_runtime.list_runs(limit=10)
        assert len(runs) >= 2

    def test_list_runs_filter_by_skill(self, isolated_runtime):
        isolated_runtime.registry.register(SkillSpec(
            skill_id="filter-a",
            name="Filter A",
            description="Filter test A",
            execute=lambda ctx, p: {"ok": True},
        ))
        isolated_runtime.registry.register(SkillSpec(
            skill_id="filter-b",
            name="Filter B",
            description="Filter test B",
            execute=lambda ctx, p: {"ok": True},
        ))
        isolated_runtime.run("filter-a")
        isolated_runtime.run("filter-b")
        a_runs = isolated_runtime.list_runs(skill_id="filter-a")
        b_runs = isolated_runtime.list_runs(skill_id="filter-b")
        assert len(a_runs) == 1
        assert len(b_runs) == 1
        assert a_runs[0]["skill_id"] == "filter-a"
        assert b_runs[0]["skill_id"] == "filter-b"

    def test_list_runs_empty(self, isolated_runtime):
        runs = isolated_runtime.list_runs()
        assert runs == []

    def test_get_unknown_run(self, isolated_runtime):
        run = isolated_runtime.get_run("nonexistent-run")
        assert run is None


# =========================================================================
# Built-in Skills Tests
# =========================================================================

class TestBuiltins:

    def test_builtin_skills_can_register(self, isolated_registry):
        count = isolated_registry.seed_defaults(BUILTIN_SKILLS)
        assert count == len(BUILTIN_SKILLS)

    def test_builtin_skills_have_valid_specs(self):
        for spec in BUILTIN_SKILLS:
            errors = validate_spec(spec)
            assert errors == [], f"Builtin {spec.skill_id} has validation errors: {errors}"

    def test_builtin_data_quality_skill(self, isolated_runtime):
        isolated_runtime.registry.register(
            [s for s in BUILTIN_SKILLS if s.skill_id == "data-quality"][0]
        )
        result = isolated_runtime.run("data-quality")
        # Should complete (may have empty results in test env, but shouldn't crash)
        assert result.status == SkillStatus.COMPLETED.value
        assert isinstance(result.data, dict)

    def test_builtin_factor_ranking_skill(self, isolated_runtime):
        isolated_runtime.registry.register(
            [s for s in BUILTIN_SKILLS if s.skill_id == "factor-ranking"][0]
        )
        result = isolated_runtime.run("factor-ranking", {"top_n": 10})
        assert result.status == SkillStatus.COMPLETED.value
        assert isinstance(result.data, dict)

    def test_builtin_market_snapshot_skill(self, isolated_runtime):
        isolated_runtime.registry.register(
            [s for s in BUILTIN_SKILLS if s.skill_id == "market-snapshot"][0]
        )
        result = isolated_runtime.run("market-snapshot")
        assert result.status == SkillStatus.COMPLETED.value
        assert isinstance(result.data, dict)

    def test_skill_specs_have_unique_ids(self):
        ids = [s.skill_id for s in BUILTIN_SKILLS]
        assert len(ids) == len(set(ids)), "Duplicate skill_ids in BUILTIN_SKILLS"


# =========================================================================
# Edge Cases
# =========================================================================

class TestEdgeCases:

    def test_empty_params_list(self, isolated_runtime):
        """Empty params dict is handled gracefully"""
        isolated_runtime.registry.register(SkillSpec(
            skill_id="empty-params",
            name="Empty Params",
            description="Empty params",
            execute=lambda ctx, p: {"params": p},
        ))
        result = isolated_runtime.run("empty-params", {})
        assert result.status == SkillStatus.COMPLETED.value
        assert result.data["params"] == {}

    def test_multiple_registrations(self, isolated_registry):
        """Re-registering the same skill_id overwrites"""
        spec1 = SkillSpec(
            skill_id="dup", name="Version 1", description="First",
        )
        spec2 = SkillSpec(
            skill_id="dup", name="Version 2", description="Second",
        )
        isolated_registry.register(spec1)
        isolated_registry.register(spec2)
        retrieved = isolated_registry.get("dup")
        assert retrieved.name == "Version 2"

    def test_validate_empty_registry(self, isolated_registry):
        assert isolated_registry.list() == []
        assert isolated_registry.count_by_category() == {}

    def test_runtime_no_registry_crash(self, tmp_path):
        """Runtime with no explicit registry and no seed doesn't crash"""
        runtime = SkillRuntime()
        result = runtime.run("nonexistent")
        assert result.status == SkillStatus.FAILED.value
        assert "not found" in result.error


# =========================================================================
# Category Tests
# =========================================================================

class TestCategories:

    def test_all_skills_have_valid_category(self):
        for spec in BUILTIN_SKILLS:
            assert spec.category in VALID_CATEGORIES, (
                f"{spec.skill_id} has invalid category: {spec.category}"
            )

    def test_category_enum_values(self):
        assert SkillCategory.ANALYSIS.value == "analysis"
        assert SkillCategory.DATA.value == "data"
        assert SkillCategory.REPORT.value == "report"
        assert SkillCategory.MONITOR.value == "monitor"
        assert SkillCategory.UNIVERSE.value == "universe"
        assert SkillCategory.BACKTEST.value == "backtest"
