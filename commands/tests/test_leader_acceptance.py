"""Tests for Leader acceptance checks."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from factor_lab.leader.acceptance import REQUIRED_MIGRATION_FILES, run_acceptance
from factor_lab.leader.planner import inspect_system


def test_required_migration_file_contract_contains_extended_outputs():
    required = set(REQUIRED_MIGRATION_FILES)
    assert "factor_alpha_mapping.csv" in required
    assert "factor_data_requirements.csv" in required
    assert "factor_correlation_baseline.csv" in required
    assert "alpha_registry_update_preview.json" in required
    assert "audit.log" in required


def test_leader_accept_cli_is_detected():
    report = inspect_system()
    assert report["cli"]["has_leader_accept"] is True


def test_acceptance_quick_report_runs_without_full_pytest():
    result = run_acceptance(full_tests=False, smoke=False)
    assert result["full_tests"] is False
    assert result["output_dir"]
    assert result["checks_total"] > 0


def test_acceptance_reports_migration_artifact_check_not_crash():
    result = run_acceptance(full_tests=False, smoke=False)
    names = [c["name"] for c in result["checks"]]
    assert "migration required files complete" in names
    assert result["verdict"] in ("passed", "failed")
