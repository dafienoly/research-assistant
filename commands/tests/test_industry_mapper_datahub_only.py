from pathlib import Path

import pytest

import factor_lab.alpha.industry_mapper as industry


def test_industry_mapper_missing_canonical_data_is_explicit(monkeypatch) -> None:
    monkeypatch.setattr(
        industry,
        "read_stock_industry_map",
        lambda: (_ for _ in ()).throw(FileNotFoundError("missing canonical reference")),
    )
    mapper = industry.IndustryMapper()
    assert mapper.status == "MISSING"
    assert mapper.get_industry_map() == {}
    assert mapper.get_industry("688012") == "unknown"
    assert "missing canonical reference" in mapper.error


def test_industry_mapper_rejects_parallel_cache_write() -> None:
    mapper = industry.IndustryMapper(auto_load=False)
    with pytest.raises(RuntimeError, match="DataHub-owned"):
        mapper.save_cache()


def test_industry_mapper_has_no_legacy_feature_fallback() -> None:
    source = Path(industry.__file__).read_text(encoding="utf-8")
    for forbidden in ("tag_features.csv", "pool.csv", "stock_industry.csv", "_try_load_from_cache"):
        assert forbidden not in source
    assert "read_stock_industry_map" in source
