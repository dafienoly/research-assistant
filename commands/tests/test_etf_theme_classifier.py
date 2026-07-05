"""测试: ETF 主题分类 + 受限→主题映射"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from factor_lab.etf.etf_universe import map_restricted_to_theme, get_etf_by_theme


def test_map_star_to_semiconductor():
    """科创板+芯片关键词 → 科创芯片"""
    theme = map_restricted_to_theme("科创板", keywords=["688385", "芯片"])
    assert theme == "科创芯片", f"预期科创芯片, 实际 {theme}"


def test_map_star_default():
    """科创板无关键词 → 科创50"""
    theme = map_restricted_to_theme("科创板", keywords=[])
    assert theme == "科创50", f"预期科创50, 实际 {theme}"


def test_map_chinext_growth():
    """创业板 → 创业板成长"""
    theme = map_restricted_to_theme("创业板", keywords=["300750"])
    assert theme == "创业板成长"


def test_theme_has_etfs():
    """每个主题都有对应的 ETF"""
    themes = ["科创芯片", "科创50", "科创100", "芯片", "创业板", "创业板成长", "人工智能"]
    for t in themes:
        etfs = get_etf_by_theme(t)
        assert len(etfs) >= 1, f"{t} 主题无 ETF"
