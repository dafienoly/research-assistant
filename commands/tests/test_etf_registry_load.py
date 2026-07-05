"""测试: ETF registry 加载"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.etf.etf_universe import load_etf_registry, list_themes, get_etf_by_theme


def test_registry_loads():
    etfs = load_etf_registry()
    assert len(etfs) > 0, "ETF registry 不为空"
    assert all(e.get("etf_code") for e in etfs), "每只 ETF 有 code"


def test_registry_required_fields():
    etfs = load_etf_registry()
    required = ["etf_code", "etf_name", "theme", "exchange", "expense_ratio"]
    for e in etfs:
        for field in required:
            assert e.get(field), f"{e['etf_code']} 缺少 {field}"


def test_themes_nonempty():
    themes = list_themes()
    assert len(themes) >= 5, f"至少 5 个主题, 实际 {len(themes)}"


def test_get_by_theme():
    etfs = get_etf_by_theme("科创芯片")
    assert len(etfs) >= 1, "科创芯片至少 1 只 ETF"
