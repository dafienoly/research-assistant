from __future__ import annotations

from pathlib import Path

from factor_lab.vnext.acceptance import AcceptanceEvidenceBuilder


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_acceptance_builder_packages_every_required_evidence_file() -> None:
    result = AcceptanceEvidenceBuilder().build(PROJECT_ROOT)
    destination = Path(result["path"])

    assert result["status"] == "PARTIAL"
    assert result["promotion_status"] == "BLOCKED"
    assert result["file_count"] == 24
    assert (destination / "security_test_report.xml").exists()
    assert (destination / "integration_test_report.xml").exists()
    assert (destination / "sbom.cdx.json").exists()
    assert (destination / "unresolved_items.md").exists()
