def _industry_relative(df: pd.DataFrame, value: pd.Series) -> pd.Series:
@register("ret5_industry_adj", "industry_relative", {"window": 5, "method": "median"},
@register("ret10_industry_adj", "industry_relative", {"window": 10, "method": "median"},
@register("ret20_industry_adj", "industry_relative", {"window": 20, "method": "median"},
    return _industry_relative(df, raw)
@register("volatility20_industry_adj", "industry_relative", {"window": 20, "method": "median"},
    return _industry_relative(df, raw)
@register("vol_ratio20_industry_adj", "industry_relative", {"window": 20, "method": "median"},
    return _industry_relative(df, raw)
@register("amihud_industry_adj", "industry_relative", {"window": 20, "method": "rank"},
@register("industry_neutral_quality", "industry_relative", {},
@register("fund_flow_industry_adj", "industry_relative", {},
@register("industry_neutral_composite", "industry_relative", {},
@register("cross_sector_strength", "industry_relative", {},
    adj_5 = _industry_relative(df, ret5_raw)