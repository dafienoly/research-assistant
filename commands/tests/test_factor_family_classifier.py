"""测试: 因子家族分类"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.scoring.factor_family import classify_factor, classify_all_factors


def test_classify_momentum():
    f = classify_factor("ret5", "momentum", "5日收益率动量")
    assert f["family"] == "momentum", f"预期 momentum, 实际 {f['family']}"
    assert f["label"] == "动量"


def test_classify_reversal():
    f = classify_factor("reversal5", "reversal", "5日反转")
    assert f["family"] == "reversal"


def test_classify_trend():
    f = classify_factor("close_gt_ma20", "trend", "站上20日均线")
    assert f["family"] == "trend"


def test_classify_volume_price():
    f = classify_factor("vol_ratio60", "volume", "60日量比")
    assert f["family"] == "volume_price"


def test_classify_volatility():
    f = classify_factor("atr20", "volatility", "ATR")
    assert f["family"] == "volatility"


def test_classify_unknown():
    f = classify_factor("unknown_xyz", "", "")
    assert f["family"] == "unknown"


def test_classify_all():
    results = classify_all_factors()
    assert len(results) > 0
    for r in results:
        assert "family" in r
        assert "label" in r
