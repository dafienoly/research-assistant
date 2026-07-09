"""
Factor Results Cache — Read/write factor computed metrics from/to JSON.

Cache file: data/factor_results.json
Structure: { "<factor_name>": { ic, rank_ic, icir, top_bottom, cost_adjusted_return, turnover, max_drawdown, excess_vs_semiconductor_ew, risk_flags, computed_at } }
"""
import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))

BASE = Path(__file__).resolve().parent.parent.parent.parent  # .../research-assistant/
CACHE_FILE = BASE / "data" / "factor_results.json"


def load_results() -> dict:
    """读取缓存文件，返回 {factor_name: metrics}。"""
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_results(results: dict):
    """写缓存文件。"""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def get_factor_metrics(factor_name: str) -> dict | None:
    """获取单个因子的计算结果。"""
    results = load_results()
    return results.get(factor_name)


def merge_metrics_into_definitions(definitions: list[dict]) -> list[dict]:
    """将缓存的计算指标合并到因子定义列表，供 API 返回。"""
    results = load_results()
    enriched = []
    for fdef in definitions:
        name = fdef.get("id") or fdef.get("name", "")
        metrics = results.get(name, {})
        enriched.append({
            **fdef,
            "IC": metrics.get("ic"),
            "RankIC": metrics.get("rank_ic"),
            "ICIR": metrics.get("icir"),
            "TopBottom": metrics.get("top_bottom"),
            "excess_vs_semiconductor_ew": metrics.get("excess_vs_semiconductor_ew"),
            "cost_adjusted_return": metrics.get("cost_adjusted_return"),
            "turnover": metrics.get("turnover"),
            "max_drawdown": metrics.get("max_drawdown"),
            "risk_flags": metrics.get("risk_flags", []),
            "computed_at": metrics.get("computed_at"),
        })
    return enriched
