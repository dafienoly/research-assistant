from __future__ import annotations

import json

import data_quality
from data_quality import DataGapReporter


def test_gap_reporter_honors_formal_tag_source_unavailability(tmp_path, monkeypatch):
    tags = tmp_path / "tags"
    tags.mkdir(parents=True)
    (tags / "tag_availability.json").write_text(json.dumps({
        "datasets": {
            "industry_chain_tags.csv": {
                "status": "MISSING_SOURCE_DATA",
                "source": None,
                "reason": "verified upstream payload unavailable",
            }
        }
    }), encoding="utf-8")
    monkeypatch.setitem(data_quality.PATHS, "data", tmp_path)
    monkeypatch.setitem(data_quality.PATHS, "audit", tmp_path / "audit")

    report = DataGapReporter().report()
    gap = next(row for row in report["gaps"] if "industry_chain_tags.csv" in row["recommendation"])

    assert gap["gap_type"] == "source_unavailable"
    assert gap["failure_reason"] == "verified upstream payload unavailable"
    assert "不得用空文件" in gap["recommendation"]
