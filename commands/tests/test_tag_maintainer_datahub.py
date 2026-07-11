from __future__ import annotations

from pathlib import Path

import pandas as pd

import tag_maintainer


def test_tag_maintainer_uses_canonical_reference_and_atomic_outputs(monkeypatch, tmp_path: Path) -> None:
    tags = tmp_path / "tags"
    audit = tmp_path / "audit"
    tags.mkdir()
    audit.mkdir()
    monkeypatch.setitem(tag_maintainer.PATHS, "tags", tags)
    monkeypatch.setitem(tag_maintainer.PATHS, "audit", audit)
    monkeypatch.setattr(tag_maintainer, "read_stock_name_map", lambda: {"688012": "中微公司"})
    monkeypatch.setattr(tag_maintainer, "read_stock_industry_map", lambda: {"688012": "半导体"})

    maintainer = tag_maintainer.TagMaintainer()
    maintainer.update_semiconductor_tags()
    maintainer.update_theme_tags()
    maintainer.update_industry_tags()

    semiconductor = pd.read_csv(tags / "semiconductor_chain_tags.csv", dtype={"code": "string"})
    themes = pd.read_csv(tags / "stock_theme_tags.csv", dtype={"code": "string"})
    industries = pd.read_csv(tags / "industry_chain_tags.csv", dtype={"code": "string"})
    assert "688012" in set(semiconductor["code"])
    assert themes.loc[themes["code"] == "688012", "name"].iloc[0] == "中微公司"
    row = industries.loc[industries["code"] == "688012"].iloc[0]
    assert row["baostock_industry"] == "半导体"
    assert row["industry_source"] == "datahub:stock_basic"


def test_tag_maintainer_has_no_provider_or_non_atomic_writer() -> None:
    source = Path(tag_maintainer.__file__).read_text(encoding="utf-8").lower()
    for forbidden in ("import baostock", "query_stock_industry", "query_profit_data", "csv.dictwriter", "open("):
        assert forbidden not in source
    assert "atomic_write_frame" in source
    assert "factorinputprojection" in source
