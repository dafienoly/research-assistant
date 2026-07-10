from factor_lab.vnext.contracts import DataStatus
from factor_lab.vnext.data_quality import DataQualityGate


def test_data_quality_gate_reports_missing_file(tmp_path):
    result = DataQualityGate().inspect_file("daily", tmp_path / "missing.csv", required_fields=["close"])
    assert result.status == DataStatus.MISSING
    assert result.missing_fields == ["close"]
