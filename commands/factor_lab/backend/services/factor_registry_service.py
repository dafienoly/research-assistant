"""Factor Registry Service — 从 REGISTRY 动态读取因子，返回结构化数据。

直接从 factor_lab.factor_base 的 REGISTRY（约124+因子）读取，无 mock/demo/sample。
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

from factor_lab.factor_base import REGISTRY, _load_evolved

CST = timezone(timedelta(hours=8))

# ─── 输入字段推断 ─────────────────────────────────
_CATEGORY_INPUTS = {
    "momentum":      ["close"],
    "trend":         ["close"],
    "reversal":      ["close"],
    "volatility":    ["close", "high", "low"],
    "volume":        ["close", "volume", "amount"],
    "liquidity":     ["close", "volume", "amount"],
    "breakout":      ["close", "high"],
    "pullback":      ["close", "volume"],
    "ret5_filter":   ["close", "volume", "amount"],
    "quality":       ["roe", "gross_margin", "net_margin", "debt_ratio", "eps"],
    "valuation":     ["pe_ttm", "pb_lf", "ps_ttm", "pcf_ttm"],
    "growth":        ["revenue_growth_q", "profit_growth_q"],
    "fund_flow":     ["net_main_force", "net_super_large", "net_large", "net_medium", "net_small"],
    "north_bound":   ["nb_net_flow", "nb_total_buy", "nb_total_sell", "nb_holding_value", "nb_holding_ratio"],
    "margin":        ["margin_buy", "margin_repay", "margin_balance", "sec_lending_balance"],
    "sentiment":     ["sentiment_score"],
    "technical":     ["close", "high", "low"],
    "event":         ["lockup_days_to_expiry", "buyback_active", "dividend_yield", "forecast_type_code", "sentiment_score"],
    "industry_relative": ["close", "volume", "amount", "industry"],
    "composite":     ["close", "roe", "gross_margin", "net_margin", "debt_ratio"],
}

_INPUTS_CATEGORY_DEFAULT = ["close", "volume", "amount"]


def _extract_lookback(params: dict) -> int:
    """从 params 中提取最大回看窗口"""
    vals = [v for v in params.values() if isinstance(v, (int, float))]
    return int(max(vals)) if vals else 0


def _derive_expression(name: str, params: dict, description: str) -> str:
    """从因子名 + params 推导表达式表示。

    REGISTRY 未存储原始表达式字符串，我们用 name + params 构造
    可读的表达式标识。如果 description 已包含公式字样则优先使用。
    """
    if params:
        parts = ", ".join(f"{k}={v}" for k, v in params.items())
        return f"{name}({parts})"
    return name


def _infer_inputs(category: str, params: dict) -> list[str]:
    """根据分类和参数推断输入字段"""
    base = _CATEGORY_INPUTS.get(category, _INPUTS_CATEGORY_DEFAULT)
    # 有窗口参数的动量/趋势类因子只需要 close
    if category in ("momentum", "trend", "reversal") and list(params.keys()) == ["window"]:
        base = ["close"]
    return base


def _entry_to_factor(entry: dict) -> dict:
    """将 REGISTRY 单条记录转为结构化 API 因子 dict。"""
    name = entry["name"]
    category = entry["category"]
    params = entry.get("params", {})
    description = entry.get("description", "")
    # 进化因子可能带 expression 字段
    raw_expr = entry.get("expression", "")

    expression = raw_expr or _derive_expression(name, params, description)
    lookback = _extract_lookback(params)
    inputs = _infer_inputs(category, params)

    return {
        "id": name,                     # name 作为唯一标识
        "name": name,
        "category": category,
        "expression": expression,
        "description": description,
        "lookback": lookback,
        "inputs": inputs,
        "source": "factor_lab",
        "status": "active",
        "as_of_date": datetime.now(CST).isoformat(),
        "freshness": "fresh",
        "lineage": [],
    }


# ─── 公共 API ─────────────────────────────────────

def get_all_factors(category: Optional[str] = None) -> list[dict]:
    """获取所有因子列表，可按分类筛选。

    每次调用都确保 _load_evolved() 已加载进化因子。
    """
    _load_evolved()
    entries = REGISTRY
    if category:
        entries = [e for e in entries if e["category"] == category]
    return [_entry_to_factor(e) for e in entries]


def get_factor_by_id(factor_id: str) -> Optional[dict]:
    """按名称查找因子，返回结构化 dict，不存在返回 None。"""
    _load_evolved()
    for entry in REGISTRY:
        if entry["name"] == factor_id:
            return _entry_to_factor(entry)
    return None


def get_category_names() -> list[str]:
    """返回所有分类名称（去重）。"""
    _load_evolved()
    cats = sorted({e["category"] for e in REGISTRY})
    return cats


def count_factors() -> int:
    """返回注册因子总数。"""
    _load_evolved()
    return len(REGISTRY)
