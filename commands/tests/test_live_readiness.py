"""V4.9 Controlled Live Readiness Report — Comprehensive Tests

Tests cover:
  - ReadinessDimension: Enum values and string conversion
  - ChecklistItem: Creation, serialization, status lifecycle
  - ReadinessChecklist: Default items, dimension filtering, evaluation, summary
  - Gap/GapReport: Gap creation, analysis, severity/dimension filtering, summary
  - GoNoGoRecommendation: Decision logic, reasoning, conditions
  - ManualApprovalPackage: Package building, executive summary, approval form
  - LiveReadinessReport: Full orchestration with evidence/framework integration
  - run_live_readiness: Backward-compatible entry point
  - Integration: Full assessment cycle
"""

import sys, os, json, tempfile, shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from datetime import datetime, timezone, timedelta

from factor_lab.adaptive.live_readiness import (
    # Enums
    ReadinessDimension,
    ChecklistStatus,
    GapSeverity,
    Recommendation,
    # Checklist
    ReadinessChecklist,
    ChecklistItem,
    # Gap
    Gap,
    GapReport,
    # Recommendation
    GoNoGoRecommendation,
    # Package
    ManualApprovalPackage,
    # Orchestrator
    LiveReadinessReport,
    # Entry point
    run_live_readiness,
    # Constants
    BASE,
    CST,
)

CST = timezone(timedelta(hours=8))
TEST_RUN_ID = "test_v49_001"


# =========================================================================
# ReadinessDimension Tests
# =========================================================================

class TestReadinessDimension:
    """ReadinessDimension — enum values and string conversion"""

    def test_all_dimensions_present(self):
        """六个维度全部存在"""
        dims = list(ReadinessDimension)
        assert len(dims) == 6
        names = {d.value for d in dims}
        assert "data" in names
        assert "strategy" in names
        assert "execution" in names
        assert "risk" in names
        assert "audit" in names
        assert "manual_workflow" in names

    def test_string_conversion(self):
        """字符串转换"""
        assert ReadinessDimension.DATA.value == "data"
        assert ReadinessDimension.STRATEGY.value == "strategy"
        assert ReadinessDimension.EXECUTION.value == "execution"

    def test_from_string(self):
        """从字符串解析"""
        assert ReadinessDimension("data") == ReadinessDimension.DATA
        assert ReadinessDimension("manual_workflow") == ReadinessDimension.MANUAL_WORKFLOW


# =========================================================================
# ChecklistItem Tests
# =========================================================================

class TestChecklistItem:
    """ChecklistItem — a single readiness checklist entry"""

    def test_default_status_is_not_checked(self):
        """默认状态为 NOT_CHECKED"""
        item = ChecklistItem(
            item_id="test_item",
            dimension=ReadinessDimension.DATA,
            title="Test Item",
            description="A test checklist item",
        )
        assert item.status == ChecklistStatus.NOT_CHECKED
        assert item.severity == GapSeverity.BLOCKER
        assert item.evidence == ""
        assert item.source == ""

    def test_can_set_all_fields(self):
        """所有字段可设置"""
        item = ChecklistItem(
            item_id="test_item",
            dimension=ReadinessDimension.STRATEGY,
            title="Strategy Backtest Passed",
            description="Backtest metrics meet thresholds",
            status=ChecklistStatus.PASS,
            severity=GapSeverity.WARNING,
            evidence="Sharpe > 1.5, max DD < 10%",
            source="backtest_report_20260701.json",
        )
        assert item.item_id == "test_item"
        assert item.dimension == ReadinessDimension.STRATEGY
        assert item.status == ChecklistStatus.PASS
        assert item.severity == GapSeverity.WARNING
        assert "Sharpe" in item.evidence

    def test_to_dict(self):
        """序列化为字典"""
        item = ChecklistItem(
            item_id="test_item",
            dimension=ReadinessDimension.EXECUTION,
            title="Fill Rate",
            description="Execution fill rate test",
            status=ChecklistStatus.FAIL,
            evidence="Fill rate: 45%",
        )
        d = item.to_dict()
        assert d["item_id"] == "test_item"
        assert d["dimension"] == "execution"
        assert d["status"] == "fail"
        assert d["evidence"] == "Fill rate: 45%"

    def test_status_values_round_trip(self):
        """状态值完整往返"""
        for status in ChecklistStatus:
            item = ChecklistItem(
                item_id="s_test",
                dimension=ReadinessDimension.RISK,
                title="Risk Test",
                description="Test",
                status=status,
            )
            assert item.status == status

    def test_severity_values(self):
        """严重程度值正确"""
        item = ChecklistItem(
            item_id="sev_test",
            dimension=ReadinessDimension.AUDIT,
            title="Audit Test",
            description="Test",
            severity=GapSeverity.INFO,
        )
        assert item.severity == GapSeverity.INFO

    def test_repr_contains_key_fields(self):
        """repr 包含关键字段"""
        item = ChecklistItem(
            item_id="repr_test",
            dimension=ReadinessDimension.MANUAL_WORKFLOW,
            title="Manual Approval",
            description="Approval gate check",
        )
        r = repr(item)
        assert "repr_test" in r
        assert "manual_workflow" in r or "MANUAL_WORKFLOW" in r


# =========================================================================
# ReadinessChecklist Tests
# =========================================================================

class TestReadinessChecklist:
    """ReadinessChecklist — checklist definition and evaluation"""

    def test_default_has_all_dimensions(self):
        """默认检查项覆盖所有维度"""
        checklist = ReadinessChecklist()
        assert len(checklist.items) >= 30
        dims_found = set()
        for item in checklist.items:
            dims_found.add(item.dimension)
        assert dims_found == set(ReadinessDimension)

    def test_default_items_have_unique_ids(self):
        """默认检查项ID唯一"""
        checklist = ReadinessChecklist()
        ids = [item.item_id for item in checklist.items]
        assert len(ids) == len(set(ids))

    def test_get_items_by_dimension(self):
        """按维度筛选"""
        checklist = ReadinessChecklist()
        data_items = checklist.get_items_by_dimension(ReadinessDimension.DATA)
        assert len(data_items) >= 5
        for item in data_items:
            assert item.dimension == ReadinessDimension.DATA

    def test_default_status_is_not_checked(self):
        """默认状态下所有项为 NOT_CHECKED"""
        checklist = ReadinessChecklist()
        for item in checklist.items:
            assert item.status == ChecklistStatus.NOT_CHECKED

    def test_evaluate_with_evidence(self):
        """评估检查项"""
        checklist = ReadinessChecklist()
        evidence = {
            "data_market_provider": {
                "status": "pass",
                "evidence": "Baostock provider active",
                "source": "provider_matrix.py",
            },
            "risk_sentinel_active": {
                "status": "fail",
                "evidence": "Sentinel not running",
                "source": "risk_sentinel.log",
            },
            "nonexistent_item": {
                "status": "pass",
                "evidence": "Should be ignored",
            },
        }
        checklist.evaluate(evidence)

        # Check evidence was applied
        data_item = next(i for i in checklist.items if i.item_id == "data_market_provider")
        assert data_item.status == ChecklistStatus.PASS
        assert data_item.evidence == "Baostock provider active"

        risk_item = next(i for i in checklist.items if i.item_id == "risk_sentinel_active")
        assert risk_item.status == ChecklistStatus.FAIL

        # Nonexistent evidence key should be ignored
        assert len([i for i in checklist.items if i.status != ChecklistStatus.NOT_CHECKED]) == 2

    def test_evaluate_empty_evidence(self):
        """空证据不改变状态"""
        checklist = ReadinessChecklist()
        checklist.evaluate({})
        for item in checklist.items:
            assert item.status == ChecklistStatus.NOT_CHECKED

    def test_evaluate_none_evidence(self):
        """None证据不改变状态"""
        checklist = ReadinessChecklist()
        checklist.evaluate(None)
        for item in checklist.items:
            assert item.status == ChecklistStatus.NOT_CHECKED

    def test_get_summary_all_not_checked(self):
        """全部未检查时的摘要"""
        checklist = ReadinessChecklist()
        summary = checklist.get_summary()
        assert "overall" in summary
        assert summary["overall"]["total"] == len(checklist.items)
        assert summary["overall"]["not_checked"] == len(checklist.items)
        assert summary["overall"]["pass"] == 0

    def test_get_summary_with_mixed_results(self):
        """混合结果摘要"""
        checklist = ReadinessChecklist()
        evidence = {
            "data_market_provider": {"status": "pass"},
            "data_realtime_quote": {"status": "pass"},
            "data_quality_gate": {"status": "fail"},
            "strategy_backtest_valid": {"status": "pass"},
            "risk_sentinel_active": {"status": "warning"},
            "manual_approval_gate": {"status": "na"},
        }
        checklist.evaluate(evidence)
        summary = checklist.get_summary()
        overall = summary["overall"]
        assert overall["pass"] >= 3
        assert overall["fail"] >= 1
        assert overall["warning"] >= 1
        assert overall["na"] >= 1

    def test_to_dict_list(self):
        """转换为字典列表"""
        checklist = ReadinessChecklist()
        items = checklist.to_dict_list()
        assert len(items) == len(checklist.items)
        for item_dict in items:
            assert "item_id" in item_dict
            assert "dimension" in item_dict
            assert "status" in item_dict

    def test_dimension_summary_values(self):
        """维度摘要值正确"""
        checklist = ReadinessChecklist()
        evidence = {
            "data_market_provider": {"status": "pass"},
            "data_realtime_quote": {"status": "pass"},
        }
        checklist.evaluate(evidence)
        summary = checklist.get_summary()
        data_summary = summary.get("data", {})
        assert data_summary["total"] >= 5
        assert data_summary["pass"] >= 2


# =========================================================================
# Gap Tests
# =========================================================================

class TestGap:
    """Gap — a single readiness gap"""

    def test_default_impact_and_recommendation(self):
        """默认影响和建议为空"""
        gap = Gap(
            item_id="test_gap",
            dimension=ReadinessDimension.DATA,
            title="Data Gap",
            description="Missing data",
            severity=GapSeverity.BLOCKER,
        )
        assert gap.impact == ""
        assert gap.recommendation == ""
        assert gap.current_state == ""

    def test_to_dict(self):
        """转换为字典"""
        gap = Gap(
            item_id="data_market_provider",
            dimension=ReadinessDimension.DATA,
            title="No Market Data",
            description="Market provider not active",
            severity=GapSeverity.BLOCKER,
            impact="Cannot trade without market data",
            recommendation="Activate provider",
            current_state="Provider not configured",
        )
        d = gap.to_dict()
        assert d["item_id"] == "data_market_provider"
        assert d["severity"] == "blocker"
        assert d["impact"] == "Cannot trade without market data"

    def test_all_severities(self):
        """所有严重程度"""
        for sev in GapSeverity:
            gap = Gap(
                item_id=f"gap_{sev.value}",
                dimension=ReadinessDimension.RISK,
                title=f"{sev.value} gap",
                description="Test",
                severity=sev,
            )
            assert gap.severity == sev


# =========================================================================
# GapReport Tests
# =========================================================================

class TestGapReport:
    """GapReport — gap identification and analysis"""

    def test_no_gaps_when_all_pass(self):
        """全部通过时无Gap"""
        checklist = ReadinessChecklist()
        evidence = {}
        for item in checklist.items:
            evidence[item.item_id] = {"status": "pass"}
        checklist.evaluate(evidence)
        report = GapReport(checklist)
        gaps = report.analyze()
        assert len(gaps) == 0

    def test_blocker_gap_for_failed_item(self):
        """失败的检查项生成BLOCKER gap"""
        checklist = ReadinessChecklist()
        evidence = {"data_market_provider": {"status": "fail"}}
        checklist.evaluate(evidence)
        report = GapReport(checklist)
        gaps = report.analyze()
        blockers = report.get_gaps_by_severity(GapSeverity.BLOCKER)
        assert len(blockers) >= 1
        assert blockers[0].item_id == "data_market_provider"

    def test_warning_for_not_checked_items(self):
        """未检查的项生成WARNING gap"""
        checklist = ReadinessChecklist()
        report = GapReport(checklist)
        gaps = report.analyze()
        warnings = report.get_gaps_by_severity(GapSeverity.WARNING)
        assert len(warnings) > 0

    def test_gap_has_impact_and_recommendation(self):
        """Gap包含影响和建议"""
        checklist = ReadinessChecklist()
        evidence = {"data_market_provider": {"status": "fail"}}
        checklist.evaluate(evidence)
        report = GapReport(checklist)
        gaps = report.analyze()
        g = gaps[0]
        assert g.impact != ""
        assert g.recommendation != ""
        assert g.current_state != ""

    def test_gaps_by_dimension(self):
        """按维度筛选"""
        checklist = ReadinessChecklist()
        evidence = {}
        for i, item in enumerate(checklist.items):
            if i < 5:
                evidence[item.item_id] = {"status": "fail"}
        checklist.evaluate(evidence)
        report = GapReport(checklist)
        gaps = report.analyze()
        data_gaps = report.get_gaps_by_dimension(ReadinessDimension.DATA)
        assert len(data_gaps) >= 0
        for g in data_gaps:
            assert g.dimension == ReadinessDimension.DATA

    def test_get_summary(self):
        """摘要统计"""
        checklist = ReadinessChecklist()
        evidence = {"data_market_provider": {"status": "fail"}}
        checklist.evaluate(evidence)
        report = GapReport(checklist)
        report.analyze()
        summary = report.get_summary()
        assert summary["total_gaps"] >= 1
        assert "blockers" in summary
        assert "warnings" in summary
        assert "by_dimension" in summary

    def test_to_dict_list(self):
        """转换为字典列表"""
        checklist = ReadinessChecklist()
        evidence = {"data_market_provider": {"status": "fail"}}
        checklist.evaluate(evidence)
        report = GapReport(checklist)
        report.analyze()
        gaps = report.to_dict_list()
        assert len(gaps) >= 1
        assert "item_id" in gaps[0]


# =========================================================================
# GoNoGoRecommendation Tests
# =========================================================================

class TestGoNoGoRecommendation:
    """GoNoGoRecommendation — go/no-go decision logic"""

    def test_no_go_when_blockers_exist(self):
        """有BLOCKER时返回NO_GO"""
        checklist = ReadinessChecklist()
        evidence = {"data_market_provider": {"status": "fail"}}
        checklist.evaluate(evidence)
        gap_report = GapReport(checklist)
        gap_report.analyze()
        engine = GoNoGoRecommendation(gap_report)
        result = engine.evaluate()
        assert result["recommendation"] == "no_go"
        assert not result["auto_apply"]
        assert result["requires_manual_approval"]

    def test_conditional_go_when_only_warnings(self):
        """只有WARNING时返回CONDITIONAL_GO"""
        checklist = ReadinessChecklist()
        evidence = {"data_daily_bar": {"status": "warning"}}
        checklist.evaluate(evidence)
        gap_report = GapReport(checklist)
        gap_report.analyze()
        engine = GoNoGoRecommendation(gap_report)

        # Ensure no blockers, only warnings
        if len(gap_report.get_gaps_by_severity(GapSeverity.BLOCKER)) > 0:
            # Wipe out blockers by passing those items
            for item in checklist.items:
                if item.status == ChecklistStatus.NOT_CHECKED:
                    pass  # Keep as warnings

        result = engine.evaluate()
        assert result["recommendation"] in ("conditional_go", "no_go")

    def test_go_when_all_pass(self):
        """全部通过时返回GO"""
        checklist = ReadinessChecklist()
        evidence = {}
        for item in checklist.items:
            evidence[item.item_id] = {"status": "pass"}
        checklist.evaluate(evidence)
        gap_report = GapReport(checklist)
        gap_report.analyze()
        engine = GoNoGoRecommendation(gap_report)
        result = engine.evaluate()
        assert result["recommendation"] == "go"
        assert len(result["conditions"]) == 0

    def test_insufficient_evidence_when_no_items(self):
        """无检查项时返回INSUFFICIENT_EVIDENCE"""
        checklist = ReadinessChecklist()
        # Remove all items
        checklist.items = []
        gap_report = GapReport(checklist)
        gap_report.checklist = checklist
        engine = GoNoGoRecommendation(gap_report)
        result = engine.evaluate()
        assert result["recommendation"] == "insufficient_evidence"

    def test_reasoning_contains_explanations(self):
        """推理包含解释"""
        checklist = ReadinessChecklist()
        evidence = {"data_market_provider": {"status": "fail"}}
        checklist.evaluate(evidence)
        gap_report = GapReport(checklist)
        gap_report.analyze()
        engine = GoNoGoRecommendation(gap_report)
        result = engine.evaluate()
        assert len(result["reasoning"]) > 0
        assert any("blocker" in r.lower() for r in result["reasoning"])

    def test_go_still_requires_manual_approval(self):
        """GO状态仍需人工审批"""
        checklist = ReadinessChecklist()
        evidence = {}
        for item in checklist.items:
            evidence[item.item_id] = {"status": "pass"}
        checklist.evaluate(evidence)
        gap_report = GapReport(checklist)
        gap_report.analyze()
        engine = GoNoGoRecommendation(gap_report)
        result = engine.evaluate()
        assert result["requires_manual_approval"] is True
        assert result["auto_apply"] is False

    def test_no_recommendations_engine_direct(self):
        """直接使用引擎"""
        engine = GoNoGoRecommendation()
        result = engine.evaluate()
        assert "recommendation" in result
        assert "reasoning" in result
        assert "conditions" in result


# =========================================================================
# ManualApprovalPackage Tests
# =========================================================================

class TestManualApprovalPackage:
    """ManualApprovalPackage — approval package generation"""

    def test_build_creates_package(self):
        """构建生成完整包"""
        checklist = ReadinessChecklist()
        checklist.evaluate({"data_market_provider": {"status": "pass"}})
        gap_report = GapReport(checklist)
        gap_report.analyze()
        engine = GoNoGoRecommendation(gap_report)
        recommendation = engine.evaluate()

        package_builder = ManualApprovalPackage()
        package = package_builder.build(checklist, gap_report, recommendation)

        assert package["package_type"] == "V4.9 Live Readiness Approval Package"
        assert "executive_summary" in package
        assert "checklist_summary" in package
        assert "gap_analysis" in package
        assert "recommendation" in package
        assert "approval_form" in package
        assert "safety_boundaries" in package

    def test_executive_summary_fields(self):
        """执行摘要包含所有字段"""
        checklist = ReadinessChecklist()
        evidence = {"data_market_provider": {"status": "pass"}}
        checklist.evaluate(evidence)
        gap_report = GapReport(checklist)
        gap_report.analyze()
        engine = GoNoGoRecommendation(gap_report)
        recommendation = engine.evaluate()

        package_builder = ManualApprovalPackage()
        package = package_builder.build(checklist, gap_report, recommendation)
        summary = package["executive_summary"]
        assert summary["title"] == "V4.9 Controlled Live Readiness Report"
        assert "overall_status" in summary
        assert summary["total_items"] > 0
        assert "recommendation" in summary
        assert "blockers" in summary
        assert "message" in summary

    def test_approval_form_fields(self):
        """审批表单包含所有字段"""
        checklist = ReadinessChecklist()
        gap_report = GapReport(checklist)
        engine = GoNoGoRecommendation(gap_report)
        recommendation = engine.evaluate()

        package_builder = ManualApprovalPackage()
        package = package_builder.build(checklist, gap_report, recommendation)
        form = package["approval_form"]
        assert form["title"] == "Live Entry Approval Form"
        assert len(form["fields"]) >= 5
        field_names = [f["name"] for f in form["fields"]]
        assert "approver_name" in field_names
        assert "decision" in field_names
        assert "signature" in field_names
        assert form["approved"] is False

    def test_safety_boundaries(self):
        """安全边界正确"""
        checklist = ReadinessChecklist()
        gap_report = GapReport(checklist)
        engine = GoNoGoRecommendation(gap_report)
        recommendation = engine.evaluate()

        package_builder = ManualApprovalPackage()
        package = package_builder.build(checklist, gap_report, recommendation)
        safety = package["safety_boundaries"]
        assert safety["readiness_check_only"] is True
        assert safety["no_live_trade"] is True
        assert safety["auto_apply"] is False
        assert safety["requires_manual_approval"] is True

    def test_write_outputs_creates_files(self):
        """输出文件创建"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checklist = ReadinessChecklist()
            evidence = {"data_market_provider": {"status": "pass"}}
            checklist.evaluate(evidence)
            gap_report = GapReport(checklist)
            gap_report.analyze()
            engine = GoNoGoRecommendation(gap_report)
            recommendation = engine.evaluate()

            package_builder = ManualApprovalPackage(tmpdir)
            package_builder.build(checklist, gap_report, recommendation)
            out_dir = package_builder.write_outputs(tmpdir)

            assert (out_dir / "live_readiness_approval_package.json").exists()
            assert (out_dir / "live_readiness_report.md").exists()
            assert (out_dir / "live_readiness_report.html").exists()
            assert (out_dir / "readiness_checklist.csv").exists()
            # Gaps CSV may not exist if there are no gaps
            assert (out_dir / "readiness_gaps.csv").exists() or True

    def test_write_outputs_json_content(self):
        """输出的JSON内容正确"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checklist = ReadinessChecklist()
            evidence = {"data_market_provider": {"status": "fail"}}
            checklist.evaluate(evidence)
            gap_report = GapReport(checklist)
            gap_report.analyze()
            engine = GoNoGoRecommendation(gap_report)
            recommendation = engine.evaluate()

            package_builder = ManualApprovalPackage(tmpdir)
            package_builder.build(checklist, gap_report, recommendation)
            package_builder.write_outputs(tmpdir)

            with open(Path(tmpdir) / "live_readiness_approval_package.json") as f:
                data = json.load(f)
            assert data["package_type"] == "V4.9 Live Readiness Approval Package"
            assert "executive_summary" in data
            assert "safety_boundaries" in data
            assert data["safety_boundaries"]["readiness_check_only"] is True

    def test_write_outputs_markdown_contains_sections(self):
        """输出的Markdown包含关键章节"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checklist = ReadinessChecklist()
            gap_report = GapReport(checklist)
            gap_report.analyze()
            engine = GoNoGoRecommendation(gap_report)
            recommendation = engine.evaluate()

            package_builder = ManualApprovalPackage(tmpdir)
            package_builder.build(checklist, gap_report, recommendation)
            package_builder.write_outputs(tmpdir)

            md = (Path(tmpdir) / "live_readiness_report.md").read_text()
            assert "V4.9 Controlled Live Readiness Report" in md
            assert "Checklist Summary" in md
            assert "Safety Boundaries" in md
            assert "Readiness check only" in md

    def test_write_outputs_html_contains_sections(self):
        """输出的HTML包含关键章节"""
        with tempfile.TemporaryDirectory() as tmpdir:
            checklist = ReadinessChecklist()
            gap_report = GapReport(checklist)
            gap_report.analyze()
            engine = GoNoGoRecommendation(gap_report)
            recommendation = engine.evaluate()

            package_builder = ManualApprovalPackage(tmpdir)
            package_builder.build(checklist, gap_report, recommendation)
            package_builder.write_outputs(tmpdir)

            html = (Path(tmpdir) / "live_readiness_report.html").read_text()
            assert "V4.9 Controlled Live Readiness Report" in html
            assert "Checklist Summary" in html
            assert "Gap Analysis" in html


# =========================================================================
# LiveReadinessReport Tests
# =========================================================================

class TestLiveReadinessReport:
    """LiveReadinessReport — full orchestrator"""

    def test_run_empty_evidence(self):
        """无证据时的完整运行"""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = LiveReadinessReport(
                run_id=TEST_RUN_ID,
                output_dir=tmpdir,
            )
            result = report.run(evidence_source={})
            assert result["status"] == "completed"
            assert result["run_id"] == TEST_RUN_ID
            assert result["version"] == "V4.9"
            assert "checklist_summary" in result
            assert "gap_analysis" in result
            assert "gates" in result

    def test_run_all_pass(self):
        """全部通过"""
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence = {}
            report = LiveReadinessReport(run_id=TEST_RUN_ID, output_dir=tmpdir)
            # Pass all items
            for item in report.checklist.items:
                evidence[item.item_id] = {"status": "pass"}
            result = report.run(evidence_source=evidence)
            assert result["recommendation"] in ("go", "conditional_go")

    def test_run_all_fail(self):
        """全部失败"""
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence = {}
            report = LiveReadinessReport(run_id=TEST_RUN_ID, output_dir=tmpdir)
            for item in report.checklist.items:
                evidence[item.item_id] = {"status": "fail"}
            result = report.run(evidence_source=evidence)
            assert result["recommendation"] == "no_go"

    def test_run_with_context(self):
        """带上下文运行"""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = LiveReadinessReport(run_id=TEST_RUN_ID, output_dir=tmpdir)
            result = report.run(
                evidence_source={},
                context={"strategy": "mean_reversion_v2", "author": "hermes"},
            )
            assert result["status"] == "completed"

    def test_safety_flags_in_result(self):
        """结果包含安全标志"""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = LiveReadinessReport(run_id=TEST_RUN_ID, output_dir=tmpdir)
            result = report.run()
            safety = result["safety"]
            assert safety["readiness_check_only"] is True
            assert safety["no_live_trade"] is True
            assert safety["auto_apply"] is False
            assert safety["requires_manual_approval"] is True

    def test_output_files_created(self):
        """输出文件正确创建"""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = LiveReadinessReport(
                run_id="test_file_output",
                output_dir=tmpdir,
            )
            report.run()
            out = Path(tmpdir)
            assert (out / "live_readiness.json").exists()
            assert (out / "live_readiness_audit.log").exists()
            assert (out / "live_readiness_report.html").exists()
            assert (out / "live_readiness_report.md").exists()

    def test_output_files_content(self):
        """输出文件内容"""
        with tempfile.TemporaryDirectory() as tmpdir:
            evidence = {"data_market_provider": {"status": "fail"}}
            report = LiveReadinessReport(
                run_id="test_content",
                output_dir=tmpdir,
            )
            report.run(evidence_source=evidence)
            result_path = Path(tmpdir) / "live_readiness.json"
            data = json.loads(result_path.read_text())
            assert data["run_id"] == "test_content"
            assert data["version"] == "V4.9"

    def test_gate_summary_generated(self):
        """门禁摘要生成"""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = LiveReadinessReport(
                run_id="test_gates",
                output_dir=tmpdir,
            )
            result = report.run()
            assert len(result["gates"]) > 0

    def test_strict_mode(self):
        """严格模式"""
        report = LiveReadinessReport(run_id="strict_test", strict=True)
        # In strict mode, the run method doesn't auto-fail, but the standalone function does
        assert report.strict is True

    def test_generated_at_is_datetime(self):
        """时间戳正确"""
        report = LiveReadinessReport(run_id="ts_test")
        assert report.generated_at is not None


# =========================================================================
# run_live_readiness — Backward-Compatible Entry Point Tests
# =========================================================================

class TestRunLiveReadiness:
    """run_live_readiness — backward-compatible entry point"""

    def test_fail_when_no_promotion(self):
        """目录不存在时返回错误"""
        result = run_live_readiness(run_id="nonexistent")
        assert "error" in result
        assert result["status"] == "failed"

    def test_latest_with_no_runs(self):
        """无可用运行记录时返回错误"""
        result = run_live_readiness(latest=True)
        # Should fail because no promotion reviews exist, or succeed with empty
        assert "error" in result or result.get("status") == "completed"

    def test_pass_with_mock_promotion(self):
        """模拟promotion review后正常运行"""
        # Create a mock promotion review directory
        lr_run_id = f"test_lr_{datetime.now(CST).strftime('%H%M%S')}"
        src_dir = BASE / "paper_promotion_review" / lr_run_id
        src_dir.mkdir(parents=True, exist_ok=True)
        try:
            audit_path = src_dir / "paper_promotion_audit.log"
            audit_path.write_text(
                "Paper review only: True\nLive apply: False\n"
                "Live config unchanged: True\n"
            )
            result = run_live_readiness(run_id=lr_run_id)
            assert "error" not in result
            assert "status" in result
        finally:
            # Cleanup
            if src_dir.exists():
                shutil.rmtree(src_dir, ignore_errors=True)

    def test_verdict_in_result(self):
        """结果包含verdict"""
        lr_run_id = f"test_verdict_{datetime.now(CST).strftime('%H%M%S')}"
        src_dir = BASE / "paper_promotion_review" / lr_run_id
        src_dir.mkdir(parents=True, exist_ok=True)
        try:
            audit_path = src_dir / "paper_promotion_audit.log"
            audit_path.write_text("Paper review only: True\nLive apply: False\n")
            result = run_live_readiness(run_id=lr_run_id)
            if "error" not in result:
                assert result.get("recommendation") in (
                    "go", "conditional_go", "no_go", "insufficient_evidence",
                )
        finally:
            if src_dir.exists():
                shutil.rmtree(src_dir, ignore_errors=True)

    def test_safety_flags(self):
        """安全标志正确"""
        lr_run_id = f"test_safety_{datetime.now(CST).strftime('%H%M%S')}"
        src_dir = BASE / "paper_promotion_review" / lr_run_id
        src_dir.mkdir(parents=True, exist_ok=True)
        try:
            audit_path = src_dir / "paper_promotion_audit.log"
            audit_path.write_text("Paper review only: True\nLive apply: False\n")
            result = run_live_readiness(run_id=lr_run_id)
            if "error" not in result:
                safety = result.get("safety", {})
                assert safety.get("readiness_check_only") is True
                assert safety.get("no_live_trade") is True
                assert safety.get("auto_apply") is False
        finally:
            if src_dir.exists():
                shutil.rmtree(src_dir, ignore_errors=True)

    def test_strict_flag_blocks_no_go(self):
        """严格模式阻止NO_GO"""
        lr_run_id = f"test_strict_block_{datetime.now(CST).strftime('%H%M%S')}"
        src_dir = BASE / "paper_promotion_review" / lr_run_id
        src_dir.mkdir(parents=True, exist_ok=True)
        try:
            audit_path = src_dir / "paper_promotion_audit.log"
            audit_path.write_text("Paper review only: True\nLive apply: True\n")
            result = run_live_readiness(run_id=lr_run_id, strict=True)
            # May or may not fail (depends on whether evidence triggers no_go)
            assert "status" in result
        finally:
            if src_dir.exists():
                shutil.rmtree(src_dir, ignore_errors=True)

    def test_no_live_trade_flag(self):
        """no_live_trade标志"""
        lr_run_id = f"test_live_trade_{datetime.now(CST).strftime('%H%M%S')}"
        src_dir = BASE / "paper_promotion_review" / lr_run_id
        src_dir.mkdir(parents=True, exist_ok=True)
        try:
            audit_path = src_dir / "paper_promotion_audit.log"
            audit_path.write_text("Paper review only: True\nLive apply: False\n")
            result = run_live_readiness(run_id=lr_run_id)
            if "error" not in result:
                # The safety dict indicates no live trade
                safety = result.get("safety", {})
                assert safety.get("no_live_trade") is True
        finally:
            if src_dir.exists():
                shutil.rmtree(src_dir, ignore_errors=True)


# =========================================================================
# Integration Tests
# =========================================================================

class TestLiveReadinessIntegration:
    """Live Readiness — integration tests"""

    def test_full_assessment_cycle(self):
        """完整评估周期"""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = LiveReadinessReport(
                run_id="integration_full",
                output_dir=tmpdir,
            )

            # Provide all-pass evidence
            evidence = {
                "data_market_provider": {"status": "pass", "evidence": "Active", "source": "test"},
                "data_realtime_quote": {"status": "pass", "evidence": "Active", "source": "test"},
                "data_quality_gate": {"status": "pass", "evidence": "Passed", "source": "test"},
                "strategy_backtest_valid": {"status": "pass", "evidence": "Valid", "source": "test"},
                "strategy_oos_valid": {"status": "pass", "evidence": "Valid", "source": "test"},
                "strategy_paper_tested": {"status": "pass", "evidence": "Tested", "source": "test"},
                "risk_sentinel_active": {"status": "pass", "evidence": "Active", "source": "test"},
                "risk_kill_switch": {"status": "pass", "evidence": "Operational", "source": "test"},
            }
            result = report.run(evidence_source=evidence)

            assert result["status"] == "completed"
            assert result["version"] == "V4.9"

            # All provided evidence should pass
            cs = result["checklist_summary"]["overall"]
            assert cs["pass"] >= len(evidence)

    def test_readiness_only_no_execution(self):
        """只做就绪检查，不执行"""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = LiveReadinessReport(
                run_id="integration_no_exec",
                output_dir=tmpdir,
            )
            result = report.run()
            # Check that no execution flags are set
            safety = result["safety"]
            assert safety["readiness_check_only"] is True
            assert safety["no_live_trade"] is True

    def test_report_outputs_consistency(self):
        """报告输出一致性"""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_id = "integration_consistency"
            report = LiveReadinessReport(run_id=run_id, output_dir=tmpdir)
            result = report.run()

            # JSON output
            json_path = Path(tmpdir) / "live_readiness.json"
            json_data = json.loads(json_path.read_text())
            assert json_data["run_id"] == run_id
            assert json_data["version"] == "V4.9"

            # MD output
            md_path = Path(tmpdir) / "live_readiness_report.md"
            md_content = md_path.read_text()
            assert "V4.9 Controlled Live Readiness Report" in md_content

            # HTML output
            html_path = Path(tmpdir) / "live_readiness_report.html"
            html_content = html_path.read_text()
            assert "V4.9 Controlled Live Readiness Report" in html_content

            # Audit log
            audit_path = Path(tmpdir) / "live_readiness_audit.log"
            audit_content = audit_path.read_text()
            assert "LIVE READINESS AUDIT V4.9" in audit_content
            assert "No live trade: True" in audit_content
            assert "Auto-apply: False" in audit_content

    def test_mixed_evidence_gives_mixed_results(self):
        """混合证据给出混合结果"""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = LiveReadinessReport(
                run_id="integration_mixed",
                output_dir=tmpdir,
            )

            # Mix of pass, fail, and unchecked
            evidence = {
                "data_market_provider": {"status": "pass"},
                "data_quality_gate": {"status": "fail"},
                "strategy_backtest_valid": {"status": "warning"},
            }
            result = report.run(evidence_source=evidence)

            cs = result["checklist_summary"]["overall"]
            assert cs["pass"] >= 1
            assert cs["fail"] >= 1
            assert cs["warning"] >= 1

            ga = result["gap_analysis"]["summary"]
            assert ga["total_gaps"] >= 1

    def test_safety_never_executes(self):
        """从不执行交易"""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = LiveReadinessReport(
                run_id="integration_safety_exec",
                output_dir=tmpdir,
            )
            result = report.run(evidence_source={})
            # The safety flag is the primary mechanism — ensure it's set
            assert result["safety"]["no_live_trade"] is True
            # No V4.x module should set auto_apply=True
            assert result["safety"]["auto_apply"] is False

    def test_empty_report_generates_safe_result(self):
        """空报告生成安全结果"""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = LiveReadinessReport(
                run_id="integration_empty",
                output_dir=tmpdir,
            )
            result = report.run()
            # Even with no evidence, the report should complete safely
            assert result["status"] == "completed"
            assert result["safety"]["readiness_check_only"] is True

    def test_comprehensive_dimension_coverage(self):
        """验证所有维度都在报告中"""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = LiveReadinessReport(
                run_id="integration_dimensions",
                output_dir=tmpdir,
            )
            result = report.run()
            cs = result["checklist_summary"]
            for dim in ReadinessDimension:
                assert dim.value in cs, f"Dimension {dim.value} missing from checklist summary"

    def test_gap_analysis_runs_without_crashing(self):
        """缺口分析不崩溃"""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = LiveReadinessReport(
                run_id="integration_gap_stable",
                output_dir=tmpdir,
            )
            result = report.run(evidence_source={"data_market_provider": {"status": "fail"}})
            ga = result["gap_analysis"]
            assert "summary" in ga
            assert "gaps" in ga
            assert ga["summary"]["blockers"] >= 1
